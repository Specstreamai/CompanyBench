"""SpecStream Deep Search: compile, quote, authorize the quoted maximum, then read the find."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote, urlencode

from companybench.models import SearchJob, SearchRequest, SearchResult, Usage
from companybench.pricing import estimate_cost
from companybench.providers.base import JobProvider, objective
from companybench.providers.common import (
    HTTPProvider,
    JobStatus,
    ResultStatus,
    candidates_from_payload,
    citation_urls,
)
from companybench.storage import fingerprint

FIND_STATES: dict[str, JobStatus] = {
    "queued": "queued",
    "planning": "running",
    "running": "running",
    "completed": "completed",
    "partial": "completed",
    "failed": "failed",
    "canceled": "cancelled",
    "expired": "failed",
}
# CompanyBench pools and credits a company only with a name and a hostname, so the
# request asks for the website; a reading names it with this output field.
WEBSITE_FIELD = "organization.website"
WEBSITE_ASK = "Bring back each company's official website."


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"]
    return None


def _cell_value(cell: dict[str, Any]) -> Any:
    return cell.get("display") if cell.get("display") is not None else cell.get("value")


def _is_website(cell: dict[str, Any]) -> bool:
    column = str(cell.get("column_id", "")).casefold()
    label = str(cell.get("label", "")).casefold()
    return column == "link" or any(word in column + label for word in ("website", "domain"))


def company_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map one delivered row; every cell and condition source stays with its company."""
    cells = [c for c in [*row.get("cells", []), *row.get("details", [])] if isinstance(c, dict)]
    # The requested website arrives in the column named by its output field. Only a
    # read value counts; an absent cell's display ("Not published") is not a website.
    candidates = [c for c in cells if c.get("column_id") == WEBSITE_FIELD]
    candidates += [c for c in cells if c.get("column_id") != WEBSITE_FIELD and _is_website(c)]
    website_cell = next((c for c in candidates if _text(c.get("value"))), None)
    name = None
    claims: dict[str, Any] = {}
    for cell in cells:
        column = str(cell.get("column_id", ""))
        if column == "identity" and name is None:
            name = _text(cell.get("display")) or _text(cell.get("value"))
        elif cell is not website_cell:
            claims[column] = _cell_value(cell)
    website = _text(website_cell.get("value")) if website_cell else None
    sources = [(c.get("provenance") or {}).get("source_url") for c in cells]
    sources += [p.get("source_url") for p in row.get("predicates", []) if isinstance(p, dict)]
    return {
        **claims,
        "id": row.get("entity_id"),
        "name": name,
        "website": website,
        "citations": citation_urls([s for s in sources if s]),
        "ordinal": row.get("ordinal"),
        "billable": row.get("billable"),
        "conditions": [
            {
                "field_id": p.get("field_id"),
                "passed": p.get("passed"),
                "observed_value": p.get("observed_value"),
                "source_url": p.get("source_url"),
                "observed_at": p.get("observed_at"),
            }
            for p in row.get("predicates", [])
            if isinstance(p, dict)
        ],
    }


class SpecStreamProvider(HTTPProvider, JobProvider):
    name = "specstream"
    api_key_env = "SPECSTREAM_API_KEY"
    default_base_url = "https://api.specstream.ai"
    allowed_options = {"max_cost_usd"}

    def __init__(self, name: str | None = None, **options: Any) -> None:
        super().__init__(name=name, **options)
        cap = options.get("max_cost_usd")
        if cap is not None and (
            not isinstance(cap, (int, float))
            or isinstance(cap, bool)
            or not math.isfinite(cap)
            or cap <= 0
        ):
            raise ValueError("max_cost_usd must be a finite positive dollar amount")

    async def submit(self, request: SearchRequest, context: Any) -> SearchJob:
        if request.target_count > 10000:
            raise ValueError("SpecStream quotes accept at most 10000 results per find")
        query = f"{objective(request)}\n{WEBSITE_ASK}"
        if len(query) > 16000:
            raise ValueError("SpecStream's plain-language request is limited to 16000 characters")
        headers = self.headers()
        # Reading and pricing never spend; the quote is saved so a resumed run
        # authorizes the same quote and the journaled request stays identical.
        offer = context.load("specstream_quote")
        if offer is None:
            reading = (
                await context.request(
                    "POST",
                    f"{self.base_url}/v1/parse",
                    operation="specstream.parse",
                    headers=headers,
                    json={"q": query},
                )
            )["data"]
            if reading.get("status") != "runnable" or not reading.get("ast_hash"):
                raise ValueError(
                    f"SpecStream could not run the request ({reading.get('status')!r}): "
                    f"{reading.get('read_back') or reading.get('unsupported')}"
                )
            offer = (
                await context.request(
                    "POST",
                    f"{self.base_url}/v1/capacity/quotes",
                    operation="specstream.quote",
                    headers=headers,
                    json={
                        "ast_hash": reading["ast_hash"],
                        "operation": "find",
                        "requested_units": request.target_count,
                    },
                )
            )["data"]
            context.checkpoint("specstream_reading", reading)
            context.checkpoint("specstream_quote", offer)
        if offer.get("can_authorize") is False:
            raise ValueError("SpecStream quote cannot be authorized for this key")
        maximum = offer["maximum_cents"]
        cap = self.options.get("max_cost_usd")
        if cap is not None and maximum > round(cap * 100):
            raise ValueError(
                f"SpecStream quote maximum ${maximum / 100:.2f} exceeds max_cost_usd ${cap:.2f}"
            )
        key = fingerprint([request.task_id, request.trial, offer["quote_id"]])[:48]
        execution = (
            await context.request(
                "POST",
                f"{self.base_url}/v1/capacity/executions",
                operation="specstream.authorize",
                billable=True,
                headers=headers,
                estimated_usd=maximum / 100,
                json={
                    "quote_id": offer["quote_id"],
                    "quote_hash": offer["quote_hash"],
                    "idempotency_key": f"companybench-{key}",
                    "confirm_max_cents": maximum,
                },
            )
        )["data"]
        if not execution.get("find_id"):
            raise ValueError(
                f"SpecStream authorization {execution.get('reservation_id')!r} returned no find"
            )
        return SearchJob(
            id=execution["find_id"],
            status="queued",
            handles={
                "reservation_id": execution.get("reservation_id"),
                "maximum_cents": maximum,
                "quote_id": offer["quote_id"],
            },
            progress=execution,
        )

    async def poll(self, request: SearchRequest, job: SearchJob, context: Any) -> SearchJob:
        find_id = quote(job.id, safe="")
        headers = self.headers()
        find = (
            await context.request(
                "GET",
                f"{self.base_url}/v1/finds/{find_id}",
                operation="specstream.poll",
                headers=headers,
            )
        )["data"]
        state = find.get("status")
        if state not in FIND_STATES:
            raise ValueError(f"Unknown SpecStream find status: {state!r}")
        rows: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        cursor = None
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = (
                await context.request(
                    "GET",
                    f"{self.base_url}/v1/finds/{find_id}/rows?{urlencode(params)}",
                    operation="specstream.rows",
                    headers=headers,
                )
            )["data"]
            pages.append(page)
            rows.extend(page.get("rows", []))
            cursor = page.get("next_cursor")
            if not cursor:
                break
            if cursor in seen:
                raise ValueError("SpecStream pagination did not advance")
            seen.add(cursor)
        commerce = find.get("commerce") or {}
        settlement = commerce.get("settlement_status")
        job_state = FIND_STATES[state]
        if job_state != "queued" and job_state != "running" and settlement == "pending":
            # The rows are final, but the charge is not; keep polling for the settled amount.
            job_state = "running"
        billed = commerce.get("billed_units")
        units: dict[str, float] = {}
        if settlement == "settled" and isinstance(commerce.get("amount_captured_cents"), int):
            units["reported_usd"] = commerce["amount_captured_cents"] / 100
        if isinstance(billed, list):
            units["billed_rows"] = len(billed)
            units["billed_row_cents"] = sum(int(u.get("unit_cents", 0)) for u in billed)
        usage = Usage(
            units=units,
            metadata={
                "native_status": state,
                "settlement_status": settlement,
                "amount_authorized_cents": commerce.get("amount_authorized_cents"),
                "amount_captured_cents": commerce.get("amount_captured_cents"),
                "amount_refunded_cents": commerce.get("amount_refunded_cents"),
                "delivered_rows": commerce.get("delivered_rows"),
                "maximum_cents": job.handles.get("maximum_cents"),
            },
        )
        result_status: ResultStatus = (
            "completed"
            if state == "completed"
            else "failed"
            if state in {"failed", "expired"}
            else "partial"
        )
        result = SearchResult(
            provider=self.name,
            candidates=candidates_from_payload([company_row(r) for r in rows]),
            status=result_status,
            usage=usage,
            error=str(find["error_code"]) if find.get("error_code") else None,
            raw={"find": find, "pages": pages},
            metadata={
                "stop_reason": find.get("stop_reason"),
                "requested_count": find.get("requested_count"),
                "accepted_count": find.get("accepted_count"),
                "ast_hash": find.get("ast_hash"),
            },
        )
        if state == "expired" and not result.error:
            result.error = "SpecStream find expired"
        result.cost = estimate_cost(self.name, usage, options=self.options)
        return SearchJob(
            id=job.id,
            status=job_state,
            handles=job.handles,
            progress={"status": state, "settlement_status": settlement},
            result=result,
            error=result.error,
        )

    async def cancel(self, job: SearchJob, context: Any) -> bool:
        await context.request(
            "POST",
            f"{self.base_url}/v1/finds/{quote(job.id, safe='')}/cancel",
            operation="specstream.cancel",
            headers=self.headers(),
        )
        return True
