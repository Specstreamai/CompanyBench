"""Versioned public-rate estimates, independent of invoice-confirmed charges.

Rates were checked on 2026-10-06. Subscription prices allocate a fully used credit
pool; they are not marginal cash charges. Missing usage is never treated as free.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

from companybench.models import Cost, Usage

RATE_DATE = "2026-10-06"
EXA_FIXED_RATES = {"minimal": 0.012, "low": 0.025, "medium": 0.10, "high": 0.50, "xhigh": 1.0}
EXA_METERED_CAPS = {"auto": 5.0, "ultra": 20.0}
# USD per million tokens: input, output, cached input. Thinking is included in output.
MODEL_RATES = {
    "gpt-6.1-sol": (2.0, 10.0, 0.1),
    "gpt-6-astra": (10.0, 50.0, 1.0),
    "gpt-6-luna": (0.1, 0.5, 0.01),
    "claude-sonnet-5-5": (2.0, 10.0, 0.2),
    "claude-opus-5-5": (4.0, 20.0, 0.2),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.1-pro-preview": (2.0, 12.0, 0.2),
    "grok-4.7": (2.0, 6.0, 0.5),
    "jev-1.13.0": (0.042, 0.0, 0.042),
}
SOURCES = {
    "openai": "https://developers.openai.com/api/docs/pricing",
    "claude": "https://platform.claude.com/docs/en/models/overview",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "grok": "https://docs.x.ai/developers/pricing",
    "avina": "https://www.avina.io/pricing",
    "exa-websets": "https://websets.exa.ai/websets/billing",
    "exa-agent": "https://exa.ai/docs/admin/pricing",
    "parallel": "https://docs.parallel.ai/getting-started/pricing",
    "specstream": "https://specstream.ai/pricing",
    "jev": "https://docs.typesafe.ai/models",
}


def exa_run_cap(effort: str, options: dict[str, Any]) -> float:
    """Documented per-run default/override cap; Connect is never enabled here."""
    if effort not in EXA_FIXED_RATES and effort not in EXA_METERED_CAPS:
        raise ValueError(f"Unsupported Exa Agent effort: {effort!r}")
    override = options.get("max_cost_usd")
    if override is not None:
        if (
            effort not in EXA_METERED_CAPS
            or not isinstance(override, (int, float))
            or not math.isfinite(override)
            or not 1 <= override <= 100
        ):
            raise ValueError("max_cost_usd accepts $1–$100 for Exa auto/ultra only")
        return float(override)
    return EXA_FIXED_RATES[effort] if effort in EXA_FIXED_RATES else EXA_METERED_CAPS[effort]


def estimate_cost(
    provider: str, usage: Usage, *, model: str | None = None, options: dict[str, Any] | None = None
) -> Cost:
    options = options or {}
    family = next((p for p in SOURCES if provider == p or provider.startswith(p + "-")), provider)
    source = SOURCES.get(family)
    cost = Cost(
        source_urls=[source] if source else [],
        assumptions=[f"Rate snapshot {RATE_DATE}; USD; excludes taxes and free allowances."],
    )
    amount: Decimal | None = None

    def d(value: Any) -> Decimal:
        return Decimal(str(value))

    if usage.metadata.get("requests"):
        # Long-context tiers apply per request, not to a sum of independent calls.
        parts = [
            estimate_cost(provider, Usage.model_validate(part), model=model, options=options)
            for part in usage.metadata["requests"]
        ]
        if all(part.public_usd is not None for part in parts):
            cost.public_usd = float(sum((d(part.public_usd) for part in parts), Decimal(0)))
            cost.basis = "public_rate_estimate"
        if "account_cost_usd" in options:
            cost.account_usd = float(options["account_cost_usd"])
        return cost
    if family in {"avina", "exa-websets"}:
        credits = usage.units.get("credits")
        if credits is not None:
            monthly, included = (1699, 6500) if family == "avina" else (449, 100000)
            monthly = options.get("public_monthly_usd", monthly)
            included = options.get("public_included_credits", included)
            if included <= 0:
                raise ValueError("public_included_credits must be positive")
            amount = d(credits) * d(monthly) / d(included)
            cost.assumptions.append(
                f"Full utilization of a ${monthly}/month, {included}-credit subscription; allocated cost, not marginal billed spend."
            )
    elif family == "parallel":
        matches = usage.units.get("native_matches")
        if matches is not None:
            generator = options.get("generator", "pro" if provider.endswith("pro") else "core")
            if generator not in {"base", "core", "pro"}:
                raise ValueError(f"Unsupported FindAll generator: {generator!r}")
            base, match = {"base": (0.25, 0.03), "core": (2, 0.15), "pro": (10, 1)}[generator]
            amount = d(base) + d(matches) * d(match)
            cost.assumptions.append(
                "Per native run and provider-matched entity; validity judged independently."
            )
    elif family == "specstream":
        # The API names each billed row's rate and the captured charge once settled.
        if "reported_usd" in usage.units:
            cost.confirmed_usd = usage.units["reported_usd"]
        if "billed_row_cents" in usage.units:
            amount = d(usage.units["billed_row_cents"]) / d(100)
            cost.assumptions.append(
                "Per delivered row at the rate the API reports for it (5¢, 15¢ or $1); duplicates and contradicted rows are not billed."
            )
    elif family == "exa-agent":
        # Actual charges stay separate from public tariff estimates/discounts.
        if "reported_usd" in usage.units:
            cost.confirmed_usd = usage.units["reported_usd"]
        effort = options.get("effort", "auto" if provider.endswith("auto") else "high")
        cap = exa_run_cap(effort, options)
        if usage.metadata.get("native_status") == "completed":
            if effort in EXA_FIXED_RATES:
                amount = d(EXA_FIXED_RATES[effort])
            elif (
                effort in EXA_METERED_CAPS
                and "agent_compute_units" in usage.units
                and usage.metadata.get("searches_reported")
            ):
                amount = d(usage.units["agent_compute_units"]) * d("0.10") + d(
                    usage.search_requests
                ) * d("0.005")
            if amount is not None:
                amount += d(usage.units.get("emails", 0)) * d("0.02") + d(
                    usage.units.get("phone_numbers", 0)
                ) * d("0.07")
                if effort in EXA_METERED_CAPS:
                    amount = min(d(cap), amount)
    elif (model in MODEL_RATES or "public_token_rates" in options) and usage.metadata.get(
        "tokens_reported"
    ):
        rates = (
            options["public_token_rates"]
            if "public_token_rates" in options
            else MODEL_RATES[model or ""]
        )
        input_rate, output_rate, cache_rate = map(d, rates)
        billed_on = date.fromisoformat(str(options.get("price_date", RATE_DATE))[:10])
        if model == "gemini-3.8-flash" and billed_on >= date(2027, 1, 1):
            input_rate *= 2
            output_rate *= 2
            cache_rate *= 2
        if usage.input_tokens > (272000 if family == "openai" else 200000):
            if family == "openai":
                input_rate *= 2
                cache_rate *= 2
                output_rate *= d(1.5)
            elif model == "gemini-3.1-pro-preview":
                input_rate *= 2
                cache_rate *= 2
                output_rate *= d(1.5)
            elif family == "grok":
                input_rate *= 2
                output_rate *= 2
                cache_rate *= 2
        cached = min(usage.cached_input_tokens, usage.input_tokens)
        amount = (
            d(usage.input_tokens - cached) * input_rate
            + d(cached) * cache_rate
            + d(usage.output_tokens) * output_rate
        ) / d(1_000_000)
        # Anthropic input_tokens excludes cache writes/reads; adapters normalize reads
        # into inclusive input_tokens and expose writes separately.
        amount += (
            d(usage.units.get("cache_write_5m_tokens", 0)) * input_rate * d(1.25) / d(1_000_000)
        )
        amount += d(usage.units.get("cache_write_1h_tokens", 0)) * input_rate * d(2) / d(1_000_000)
        if usage.units.get("openai_cache_write_tokens"):
            # Already included at the base rate; add the 25% write premium.
            amount += (
                d(usage.units["openai_cache_write_tokens"]) * input_rate * d(0.25) / d(1_000_000)
            )
        search_rate = {"openai": 0.01, "claude": 0.01, "gemini": 0.014, "grok": 0.005}.get(family)
        if search_rate is not None:
            if not usage.metadata.get("searches_reported"):
                amount = None
                cost.assumptions.append(
                    "Hosted-search usage unavailable; token-only subtotal is not a total search cost."
                )
            else:
                amount += d(usage.search_requests) * d(search_rate)
    if amount is not None:
        cost.public_usd = float(amount)
        cost.basis = "public_rate_estimate"
    if cost.confirmed_usd is not None:
        cost.basis = (
            "public_estimate_and_reported_charge" if amount is not None else "reported_charge"
        )
    account_credit_price = options.get(
        "account_credit_price", options.get("account_usd_per_credit")
    )
    if account_credit_price is not None and "credits" in usage.units:
        cost.account_usd = float(d(account_credit_price) * d(usage.units["credits"]))
    if "account_cost_usd" in options:
        cost.account_usd = float(options["account_cost_usd"])
    return cost


def estimate_max_cost(
    name: str, target_count: int, options: dict[str, Any] | None = None
) -> float | None:
    """Reservation estimates, not billing guarantees; unknown LLM work stays unknown."""
    options = options or {}
    if name == "avina":
        return estimate_cost(
            name, Usage(units={"credits": 2 * target_count}), options=options
        ).public_usd
    if name == "exa-websets":
        return estimate_cost(
            name, Usage(units={"credits": 10 * target_count}), options=options
        ).public_usd
    if name in {"exa-agent-auto", "exa-agent-high"}:
        return exa_run_cap(
            options.get("effort", "auto" if name.endswith("auto") else "high"), options
        )
    if name == "specstream":
        # $1 is the highest per-row rate; no contact details are requested.
        cap = options.get("max_cost_usd")
        return min(float(target_count), float(cap)) if cap is not None else float(target_count)
    if name in {"parallel-core", "parallel-pro"}:
        return estimate_cost(
            name, Usage(units={"native_matches": target_count}), options=options
        ).public_usd
    return None
