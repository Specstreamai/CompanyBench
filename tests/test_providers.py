"""Offline contracts: no credentials or external requests are used."""

from datetime import UTC, datetime

import pytest

from companybench.models import Criterion, Query, SearchJob, SearchRequest, Usage
from companybench.pricing import estimate_cost, estimate_max_cost
from companybench.providers.common import candidates_from_payload
from companybench.providers.registry import PRESETS, provider_names, resolve
from companybench.providers.specstream import company_row, request_text


class FakeContext:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.state = {}

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert self.responses, f"Unexpected request: {method} {url}"
        return self.responses.pop(0)

    def checkpoint(self, key, value):
        self.state[key] = value

    def load(self, key):
        return self.state.get(key)


@pytest.fixture
def search_request():
    return SearchRequest(
        query=Query(
            id="test",
            index=1,
            query="Find US software companies",
            family="firmographic",
            complexity="L1",
            industry="Software",
            conditions=[Criterion(id="c1", description="US software company")],
        ),
        reference_time=datetime(2026, 10, 6, tzinfo=UTC),
        task_id="unit-test",
    )


def test_all_presets_resolve_without_reading_keys():
    assert len(PRESETS) == 15
    assert all(resolve(name).name == name for name in PRESETS)
    with pytest.raises(ValueError, match="Unknown provider"):
        resolve("not-a-provider")


@pytest.mark.asyncio
async def test_websets_initial_idle_is_not_finished(search_request):
    provider = resolve("exa-websets", {"api_key": "test"})
    context = FakeContext([{"id": "ws1", "status": "idle", "searches": [{"status": "created"}]}])
    job = await provider.submit(search_request, context)
    assert job.status == "queued"
    assert job.result is None


@pytest.mark.asyncio
async def test_parallel_ignores_internal_nonmatched_candidates(search_request):
    provider = resolve("parallel-core", {"api_key": "test"})
    context = FakeContext(
        [
            {"findall_id": "fa1", "status": {"status": "queued"}},
            {
                "run": {"findall_id": "fa1", "status": {"status": "completed"}},
                "candidates": [
                    {
                        "candidate_id": "a",
                        "name": "A",
                        "url": "a.example",
                        "match_status": "matched",
                    },
                    {
                        "candidate_id": "b",
                        "name": "B",
                        "url": "b.example",
                        "match_status": "unmatched",
                    },
                ],
            },
        ]
    )
    job = await provider.submit(search_request, context)
    job = await provider.poll(search_request, job, context)
    assert job.status == "completed"
    assert [c.name for c in job.result.candidates] == ["A"]
    assert len(job.result.raw["candidates"]) == 2


@pytest.mark.asyncio
async def test_openai_counts_search_actions_not_page_opens_and_preserves_duplicates(search_request):
    provider = resolve("openai-sol-medium", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "id": "resp1",
                "status": "completed",
                "model": "gpt-6.1-sol",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {"type": "search", "queries": ["US software"]},
                    },
                    {"type": "web_search_call", "action": {"type": "open_page"}},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"companies":[{"name":"A","domain":"a.example"},{"name":"A","domain":"a.example"}]}',
                            }
                        ],
                    },
                ],
            }
        ]
    )
    result = await provider.search(search_request, context)
    assert len(result.candidates) == 2
    assert result.usage.search_requests == 1
    body = context.calls[0][2]["json"]
    assert body["reasoning"]["effort"] == "medium"
    assert "temperature" not in body


def test_missing_usage_is_unknown_cost():
    assert estimate_cost("openai", Usage(), model="gpt-6.1-sol").public_usd is None


def test_cached_tokens_and_thinking_are_not_double_charged():
    usage = Usage(
        input_tokens=100_000,
        output_tokens=10_000,
        cached_input_tokens=50_000,
        metadata={"tokens_reported": True, "searches_reported": True},
    )
    cost = estimate_cost("openai", usage, model="gpt-6.1-sol")
    assert cost.public_usd == pytest.approx(0.205)


def test_subscription_cost_is_allocated_and_confirmed_stays_unknown():
    cost = estimate_cost("avina", Usage(units={"credits": 100}))
    assert cost.public_usd == pytest.approx(100 * 1699 / 6500)
    assert cost.confirmed_usd is None
    assert "utilization" in " ".join(cost.assumptions)


@pytest.mark.asyncio
async def test_avina_separates_creation_and_run_and_preserves_signal_checkpoint(search_request):
    provider = resolve("avina", {"api_key": "test"})
    context = FakeContext(
        [
            {"id": "sig1", "type": "custom_ai", "monitor": {"enabled": False}},
            {"id": "run1", "status": "queued"},
        ]
    )
    job = await provider.submit(search_request, context)
    assert context.load("avina_signal")["id"] == "sig1"
    assert job.handles["signal_id"] == "sig1"
    create = context.calls[0][2]
    assert create["json"]["persona_ids"] == []
    assert create["json"]["icp_criteria"]
    assert "initial_count" not in create["json"]
    assert create["idempotency_header"] == "Idempotency-Key"
    assert context.calls[1][2]["operation"] != create["operation"]


@pytest.mark.asyncio
async def test_avina_reuses_checkpoint_and_reads_all_pages(search_request):
    provider = resolve("avina", {"api_key": "test"})
    context = FakeContext(
        [
            {"id": "run1", "status": "queued"},
            {"id": "run1", "status": "completed", "completed_at": None},
            {
                "data": [
                    {
                        "id": "a",
                        "signal_type": "custom_ai",
                        "company": {"name": "A", "domain": "a.example"},
                    }
                ],
                "has_more": True,
                "next_cursor": "cursor1",
            },
            {
                "data": [
                    {
                        "id": "b",
                        "signal_type": "custom_ai",
                        "company": {"name": "B", "domain": "b.example"},
                    }
                ],
                "has_more": False,
                "next_cursor": "cursor2",
            },
        ]
    )
    context.checkpoint("avina_signal", {"id": "sig1", "type": "custom_ai"})
    job = await provider.submit(search_request, context)
    result = await provider.poll(search_request, job, context)
    assert context.calls[0][1].endswith("/signals/sig1/runs")
    assert result.status == "completed"
    assert len(result.result.candidates) == 2
    assert result.result.usage.units["credits"] == 4
    assert "after=cursor1" in context.calls[-1][1]


@pytest.mark.asyncio
async def test_websets_repeated_cursor_fails_instead_of_looping(search_request):
    provider = resolve("exa-websets", {"api_key": "test"})
    context = FakeContext(
        [
            {"id": "ws", "status": "idle"},
            {"id": "ws", "status": "idle", "searches": [{"status": "completed"}]},
            {"data": [], "hasMore": True, "nextCursor": "same"},
            {"data": [], "hasMore": True, "nextCursor": "same"},
        ]
    )
    job = await provider.submit(search_request, context)
    with pytest.raises(ValueError, match="pagination did not advance"):
        await provider.poll(search_request, job, context)


@pytest.mark.asyncio
async def test_exa_agent_structured_grounding_and_reported_cost(search_request):
    provider = resolve("exa-agent-auto", {"api_key": "test"})
    context = FakeContext(
        [
            {"id": "agent1", "status": "queued"},
            {
                "id": "agent1",
                "status": "completed",
                "stopReason": "budget_reached",
                "output": {
                    "structured": {"companies": [{"name": "A", "domain": "a.example"}]},
                    "grounding": [
                        {
                            "field": "companies[0].name",
                            "citations": [{"url": "https://a.example/about"}],
                        }
                    ],
                },
                "costDollars": {"total": 1.234},
                "usage": {"searches": 3},
            },
        ]
    )
    job = await provider.submit(search_request, context)
    job = await provider.poll(search_request, job, context)
    assert job.result.status == "partial"
    assert job.result.candidates[0].citations == ["https://a.example/about"]
    assert job.result.cost.confirmed_usd == pytest.approx(1.234)
    assert "Exa-Beta" not in context.calls[0][2]["headers"]


@pytest.mark.asyncio
async def test_claude_pause_continuation_preserves_content_and_counts_all_usage(search_request):
    provider = resolve("claude-opus-max", {"api_key": "test"})
    content = [{"type": "thinking", "thinking": "", "signature": "opaque"}]
    native = {
        "input_tokens": 100,
        "output_tokens": 20,
        "server_tool_use": {"web_search_requests": 1},
    }
    context = FakeContext(
        [
            {"stop_reason": "pause_turn", "content": content, "usage": native},
            {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": '{"companies":[{"name":"A","domain":"a.example"}]}'}
                ],
                "usage": native,
            },
        ]
    )
    result = await provider.search(search_request, context)
    assert result.status == "completed"
    assert result.usage.search_requests == 2
    assert result.usage.output_tokens == 40
    assert context.calls[1][2]["json"]["messages"][-1]["content"] == content
    assert context.calls[1][2]["json"]["max_tokens"] == 127980
    assert context.calls[0][2]["json"]["output_config"] == {"effort": "max"}
    assert not result.metadata["formatter_used"]


@pytest.mark.asyncio
async def test_claude_formatter_cannot_add_company(search_request):
    provider = resolve("claude-sonnet-medium", {"api_key": "test"})
    native = {
        "input_tokens": 10,
        "output_tokens": 10,
        "server_tool_use": {"web_search_requests": 1},
    }
    context = FakeContext(
        [
            {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "1. A (https://a.example)"}],
                "usage": native,
            },
            {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": '{"companies":[{"name":"B","domain":"b.example"}]}'}
                ],
                "usage": {"input_tokens": 20, "output_tokens": 20},
            },
        ]
    )
    result = await provider.search(search_request, context)
    assert result.status == "failed"
    assert result.candidates == []
    assert result.usage.output_tokens == 30
    assert "tools" not in context.calls[-1][2]["json"]


@pytest.mark.asyncio
async def test_gemini_counts_nested_queries_and_separate_thought_tokens(search_request):
    provider = resolve("gemini-flash-high", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "status": "completed",
                "steps": [
                    {
                        "type": "google_search_call",
                        "arguments": {"queries": ["alpha", "alpha", "beta"]},
                    },
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": '{"companies":[]}'}],
                    },
                ],
                "usage": {
                    "total_input_tokens": 10,
                    "total_output_tokens": 5,
                    "total_thought_tokens": 20,
                },
            }
        ]
    )
    result = await provider.search(search_request, context)
    assert result.usage.output_tokens == 25
    assert result.usage.search_requests == 2
    assert context.calls[0][2]["json"]["generation_config"]["thinking_level"] == "high"


@pytest.mark.asyncio
async def test_grok_normalizes_reasoning_and_exact_billed_ticks(search_request):
    provider = resolve("grok-xhigh", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"companies":[]}'}],
                    }
                ],
                "usage": {
                    "input_tokens": 32,
                    "output_tokens": 9,
                    "output_tokens_details": {"reasoning_tokens": 110},
                    "server_side_tool_usage_details": {"web_search_calls": 3},
                    "cost_in_usd_ticks": 37756000,
                },
            }
        ]
    )
    result = await provider.search(search_request, context)
    assert result.usage.output_tokens == 119
    assert result.usage.search_requests == 3
    assert result.cost.confirmed_usd == pytest.approx(0.0037756)
    assert context.calls[0][2]["json"]["reasoning"] == {"effort": "xhigh"}


def test_aggregate_requests_do_not_accidentally_trigger_long_context_pricing():
    part = Usage(
        input_tokens=200000,
        output_tokens=100,
        metadata={"tokens_reported": True, "searches_reported": True},
    )
    aggregate = Usage(
        input_tokens=400000,
        output_tokens=200,
        metadata={"requests": [part.model_dump(), part.model_dump()]},
    )
    assert estimate_cost("openai", aggregate, model="gpt-6.1-sol").public_usd == pytest.approx(
        0.802
    )


def test_name_only_identity_is_resolvable_not_malformed():
    rows = candidates_from_payload(
        [
            {"name": "A", "domain": None},
            {"domain": "https://a.example"},
            {"domain": "not a domain"},
            "bad",
        ]
    )
    assert [row.malformed for row in rows] == [False, False, True, True]
    assert rows[0].domain is None


def test_custom_provider_factories_accept_options_and_keep_declared_name(tmp_path, monkeypatch):
    source = """from companybench.providers.base import ImmediateProvider
class Custom(ImmediateProvider):
    name = "declared-name"
    def __init__(self, marker):
        self.marker = marker
def create(**options):
    return Custom(**options)
def invalid(**options):
    return object()
"""
    path = tmp_path / "extension.py"
    path.write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    for reference in (f"{path}:create", "extension:create"):
        provider = resolve(reference, {"marker": "value"})
        assert provider.name == "declared-name"
        assert provider.marker == "value"
    with pytest.raises(TypeError, match="must return"):
        resolve(f"{path}:invalid")


def test_entry_point_discovery_does_not_load_code_and_rejects_collisions(monkeypatch):
    from companybench.providers import registry

    class Entry:
        name = "third-party"

        def load(self):
            raise AssertionError("Listing providers must not execute plugin code")

    monkeypatch.setattr(registry.metadata, "entry_points", lambda **kw: [Entry()])
    assert provider_names()[-1] == "third-party"
    Entry.name = "avina"
    with pytest.raises(ValueError, match="collision"):
        provider_names()


@pytest.mark.asyncio
async def test_gemini_tool_context_and_opaque_search_usage_are_not_free(search_request):
    provider = resolve("gemini-flash-high", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "status": "incomplete",
                "continuation_token": "opaque",
                "steps": [
                    {"type": "google_search_result", "result": []},
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": '{"companies":[]}'}],
                    },
                ],
                "usage": {
                    "total_input_tokens": 10,
                    "total_tool_use_tokens": 100,
                    "total_output_tokens": 5,
                    "total_thought_tokens": 20,
                },
            }
        ]
    )
    result = await provider.search(search_request, context)
    assert result.usage.input_tokens == 110
    assert result.cost.public_usd is None
    assert result.status == "truncated"
    assert result.metadata["continuation_available"]


def test_exa_auto_cap_is_public_estimate_separate_from_reported_charge():
    cost = estimate_cost(
        "exa-agent-auto",
        Usage(
            search_requests=100,
            units={"agent_compute_units": 100, "reported_usd": 4.75},
            metadata={"searches_reported": True, "native_status": "completed"},
        ),
    )
    assert cost.public_usd == 5.0
    assert cost.confirmed_usd == 4.75


def test_credential_environment_override_is_used_by_preflight_and_headers(monkeypatch):
    monkeypatch.setenv("BENCHMARK_OPENAI_KEY", "unit-test-key")
    provider = resolve("openai-sol-medium", {"api_key_env": "BENCHMARK_OPENAI_KEY"})
    assert provider.api_key_env == "BENCHMARK_OPENAI_KEY"
    assert provider.headers()["Authorization"] == "Bearer unit-test-key"


@pytest.mark.asyncio
async def test_openai_missing_native_action_is_unknown_search_cost(search_request):
    provider = resolve("openai-sol-medium", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "output": [
                    {"type": "web_search_call"},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"companies":[]}'}],
                    },
                ],
            }
        ]
    )
    result = await provider.search(search_request, context)
    assert not result.usage.metadata["searches_reported"]
    assert result.cost.public_usd is None


@pytest.mark.asyncio
async def test_websets_missing_native_evaluations_is_unknown_credit_cost(search_request):
    provider = resolve("exa-websets", {"api_key": "test"})
    context = FakeContext(
        [
            {"id": "ws", "status": "idle"},
            {"status": "idle", "searches": [{"status": "completed"}]},
            {
                "data": [{"properties": {"url": "https://a.example", "company": {"name": "A"}}}],
                "hasMore": False,
            },
        ]
    )
    job = await provider.poll(
        search_request, await provider.submit(search_request, context), context
    )
    assert job.result.cost.public_usd is None
    assert job.result.candidates[0].name == "A"


@pytest.mark.parametrize(
    "name, options",
    [
        ("openai-sol-medium", {"reasonning_effort": "high"}),
        ("gemini-flash-high", {"effort": "max"}),
        ("exa-agent-auto", {"effort": "imaginary"}),
        ("parallel-core", {"generator": "imaginary"}),
        ("exa-agent-high", {"max_cost_usd": 20}),
        ("exa-agent-auto", {"max_duration_seconds": 500}),
    ],
)
def test_unsupported_options_fail_before_paid_calls(name, options):
    with pytest.raises(ValueError):
        resolve(name, options)


@pytest.mark.asyncio
async def test_exa_documented_effort_and_budget_overrides_affect_wire_and_reservation(
    search_request,
):
    options = {"effort": "ultra", "max_cost_usd": 12, "max_duration_seconds": 600}
    assert estimate_max_cost("exa-agent-auto", 50, options) == 12
    assert estimate_max_cost("exa-agent-high", 50, {"effort": "ultra"}) == 20
    assert estimate_max_cost("exa-agent-auto", 50, {"effort": "medium"}) == 0.1
    assert estimate_max_cost("parallel-core", 50, {"generator": "pro"}) == 60
    provider = resolve("exa-agent-auto", {**options, "api_key": "test"})
    context = FakeContext([{"id": "agent1", "status": "queued"}])
    await provider.submit(search_request, context)
    assert context.calls[0][2]["json"]["budget"] == {
        "maxCostDollars": 12,
        "maxDurationSeconds": 600,
    }
    cost = estimate_cost(
        "exa-agent-auto",
        Usage(
            search_requests=1,
            units={"agent_compute_units": 200},
            metadata={"searches_reported": True, "native_status": "completed"},
        ),
        options=options,
    )
    assert cost.public_usd == 12


@pytest.mark.asyncio
async def test_claude_accumulates_native_answers_and_citation_annotations(search_request):
    provider = resolve("claude-opus-max", {"api_key": "test"})
    usage = {"input_tokens": 10, "output_tokens": 10, "server_tool_use": {"web_search_requests": 1}}
    context = FakeContext(
        [
            {
                "model": "claude-opus-5-5-20261001",
                "stop_reason": "pause_turn",
                "usage": usage,
                "content": [
                    {
                        "type": "text",
                        "text": "1. Alpha makes sensors.",
                        "citations": [
                            {
                                "type": "web_search_result_location",
                                "url": "https://alpha.example/about",
                                "cited_text": "Alpha makes sensors.",
                            }
                        ],
                    }
                ],
            },
            {
                "model": "claude-opus-5-5-20261001",
                "stop_reason": "end_turn",
                "usage": usage,
                "content": [
                    {
                        "type": "text",
                        "text": "2. Beta makes motors.",
                        "citations": [
                            {
                                "type": "web_search_result_location",
                                "url": "https://beta.example/about",
                                "cited_text": "Beta makes motors.",
                            }
                        ],
                    }
                ],
            },
            {
                "model": "claude-opus-5-5-20261001",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "content": [
                    {
                        "type": "text",
                        "text": '{"companies":[{"name":"Alpha","domain":"alpha.example","citations":["https://alpha.example/about"],"evidence":"Alpha makes sensors."},{"name":"Beta","domain":"beta.example","citations":["https://beta.example/about"],"evidence":"Beta makes motors."}]}',
                    }
                ],
            },
        ]
    )
    result = await provider.search(search_request, context)
    assert result.status == "completed"
    assert result.model == "claude-opus-5-5-20261001"
    assert [c.name for c in result.candidates] == ["Alpha", "Beta"]
    assert result.candidates[0].citations == ["https://alpha.example/about"]
    formatter_input = context.calls[-1][2]["json"]["messages"][0]["content"]
    assert "Alpha makes sensors." in formatter_input
    assert "Beta makes motors." in formatter_input
    assert "https://alpha.example/about" in formatter_input
    assert result.usage.output_tokens == 30


@pytest.mark.asyncio
async def test_claude_formatter_cannot_add_evidence_claims(search_request):
    provider = resolve("claude-sonnet-medium", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": "Alpha at https://alpha.example makes sensors."}
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 10,
                    "server_tool_use": {"web_search_requests": 1},
                },
            },
            {
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": '{"companies":[{"name":"Alpha","domain":"alpha.example","evidence":"Alpha has 1000 employees."}]}',
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        ]
    )
    result = await provider.search(search_request, context)
    assert result.status == "failed"
    assert result.candidates == []
    assert "evidence absent" in result.error
    assert result.usage.output_tokens == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("stop,expected", [("refusal", "refused"), ("max_tokens", "truncated")])
async def test_claude_formatter_finish_reason_is_preserved_even_for_valid_json(
    search_request, stop, expected
):
    provider = resolve("claude-sonnet-medium", {"api_key": "test"})
    context = FakeContext(
        [
            {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "No companies found."}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 10,
                    "server_tool_use": {"web_search_requests": 1},
                },
            },
            {
                "stop_reason": stop,
                "content": [{"type": "text", "text": '{"companies":[]}'}],
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        ]
    )
    result = await provider.search(search_request, context)
    assert result.status == expected
    assert result.usage.output_tokens == 20


def specstream_find(status="completed", settlement="settled", captured=20):
    return {
        "data": {
            "find_id": "fnd_1",
            "status": status,
            "ast_hash": "a" * 64,
            "requested_count": 50,
            "accepted_count": 2,
            "stop_reason": "saturated_discovery",
            "error_code": None,
            "commerce": {
                "find_id": "fnd_1",
                "settlement_status": settlement,
                "amount_authorized_cents": 5000,
                "amount_captured_cents": captured,
                "amount_refunded_cents": 5000 - captured,
                "delivered_rows": 2,
                "billed_units": [
                    {"id": "ent_a", "unit_cents": 5},
                    {"id": "ent_b", "unit_cents": 15},
                ],
            },
        }
    }


def specstream_row(entity, name, website, source):
    # Delivered-row shape: identity, condition columns, the requested website and details.
    website_cell = {
        "column_id": "organization.website",
        "label": "Website",
        "value": website,
        "display": website,
        "provenance": {"field_id": "organization.website", "source_url": website},
    }
    if website is None:
        website_cell = {
            "column_id": "organization.website",
            "label": "Website",
            "value": None,
            "display": "Not published",
            "absence": "Not published",
            "provenance": None,
        }
    return {
        "spec_version": "accepted_row.v1",
        "entity_id": entity,
        "ordinal": 0,
        "billable": True,
        "contact_visibility": "full",
        "cells": [
            {
                "column_id": "identity",
                "label": "Organization",
                "value": name,
                "display": name,
                "provenance": {"field_id": "organization.name", "source_url": source},
            },
            {
                "column_id": "condition:c1",
                "label": "US software company",
                "value": True,
                "display": "Yes",
                "provenance": {"field_id": "condition:c1", "source_url": source},
            },
            website_cell,
        ],
        "details": [
            {
                "column_id": "organization.legal_name",
                "label": "Legal name",
                "value": f"{name} Inc.",
                "display": f"{name} Inc.",
                "provenance": {"field_id": "organization.legal_name", "source_url": source},
            },
            {
                "column_id": "organization.address",
                "label": "Address",
                "value": "1 Main St, Austin, TX",
                "display": "1 Main St, Austin, TX",
                "provenance": None,
            },
        ],
        "predicates": [
            {
                "field_id": "c1",
                "op": "eq",
                "required_value": True,
                "observed_value": True,
                "passed": True,
                "source_label": "About page",
                "source_url": source + "#about",
                "observed_at": "2026-10-06T00:00:00Z",
            }
        ],
    }


SPECSTREAM_READING = {"data": {"status": "runnable", "ast_hash": "a" * 64, "read_back": "x"}}
SPECSTREAM_QUOTE = {
    "data": {
        "quote_id": "q1",
        "quote_hash": "b" * 64,
        "maximum_cents": 5000,
        "can_authorize": True,
    }
}
SPECSTREAM_EXECUTION = {
    "data": {"reservation_id": "r1", "find_id": "fnd_1", "maximum_cents": 5000, "state": "reserved"}
}


@pytest.mark.asyncio
async def test_specstream_compiles_quotes_and_authorizes_the_quoted_maximum(search_request):
    provider = resolve("specstream", {"api_key": "test"})
    context = FakeContext([SPECSTREAM_READING, SPECSTREAM_QUOTE, SPECSTREAM_EXECUTION])
    job = await provider.submit(search_request, context)
    assert job.id == "fnd_1" and job.status == "queued"
    paths = [url.removeprefix("https://api.specstream.ai") for _, url, _ in context.calls]
    assert paths == ["/v1/parse", "/v1/capacity/quotes", "/v1/capacity/executions"]
    assert context.calls[0][2]["json"]["q"] == request_text(search_request)
    assert [c[2].get("billable", False) for c in context.calls] == [False, False, True]
    assert context.calls[1][2]["json"]["requested_units"] == search_request.target_count
    authorize = context.calls[2][2]["json"]
    assert authorize["confirm_max_cents"] == 5000
    assert authorize["quote_hash"] == "b" * 64
    assert 8 <= len(authorize["idempotency_key"]) <= 128
    assert context.calls[2][2]["headers"]["Authorization"] == "Bearer test"
    assert context.load("specstream_quote")["quote_id"] == "q1"


@pytest.mark.asyncio
async def test_specstream_resume_authorizes_the_saved_quote_with_the_same_key(search_request):
    provider = resolve("specstream", {"api_key": "test"})
    first = FakeContext([SPECSTREAM_READING, SPECSTREAM_QUOTE, SPECSTREAM_EXECUTION])
    await provider.submit(search_request, first)
    resumed = FakeContext([SPECSTREAM_EXECUTION])
    resumed.checkpoint("specstream_quote", SPECSTREAM_QUOTE["data"])
    await provider.submit(search_request, resumed)
    assert len(resumed.calls) == 1
    assert resumed.calls[0][2]["json"] == first.calls[2][2]["json"]


@pytest.mark.asyncio
async def test_specstream_unrunnable_reading_and_quote_over_cap_start_no_paid_work(
    search_request,
):
    provider = resolve("specstream", {"api_key": "test"})
    context = FakeContext([{"data": {"status": "needs_edit", "ast_hash": None}}])
    with pytest.raises(ValueError, match="needs_edit"):
        await provider.submit(search_request, context)
    capped = resolve("specstream", {"api_key": "test", "max_cost_usd": 10})
    context = FakeContext([SPECSTREAM_READING, SPECSTREAM_QUOTE])
    with pytest.raises(ValueError, match="exceeds max_cost_usd"):
        await capped.submit(search_request, context)
    assert not any(c[2].get("billable") for c in context.calls)
    with pytest.raises(ValueError, match="max_cost_usd"):
        resolve("specstream", {"max_cost_usd": -1})


@pytest.mark.asyncio
async def test_specstream_reads_every_row_page_with_sources_and_settled_charge(search_request):
    provider = resolve("specstream", {"api_key": "test"})
    context = FakeContext(
        [
            specstream_find(),
            {
                "data": {
                    "find_id": "fnd_1",
                    "status": "completed",
                    "accepted_count": 2,
                    "entitlement": "full",
                    "rows": [
                        specstream_row(
                            "ent_a", "Alpha", "https://alpha.example", "https://alpha.example/about"
                        )
                    ],
                    "possible": [
                        {"entity_id": "ent_p", "ordinal": 0, "cells": [], "conditions": []}
                    ],
                    "next_cursor": "c1",
                }
            },
            {
                "data": {
                    "find_id": "fnd_1",
                    "status": "completed",
                    "accepted_count": 2,
                    "entitlement": "full",
                    "rows": [
                        specstream_row(
                            "ent_b", "Beta", "https://www.beta.example", "https://news.example/beta"
                        )
                    ],
                    "next_cursor": None,
                }
            },
        ]
    )
    job = await provider.poll(search_request, SearchJob(id="fnd_1", status="queued"), context)
    assert job.status == "completed"
    assert "cursor=c1" in context.calls[-1][1] and "limit=100" in context.calls[-1][1]
    alpha, beta = job.result.candidates
    assert (alpha.name, alpha.domain, alpha.native_id) == ("Alpha", "alpha.example", "ent_a")
    assert beta.domain == "beta.example"
    assert alpha.citations == [
        "https://alpha.example/about",
        "https://alpha.example",
        "https://alpha.example/about#about",
    ]
    assert alpha.claims["organization.address"] == "1 Main St, Austin, TX"
    assert alpha.claims["organization.legal_name"] == "Alpha Inc."
    assert "organization.website" not in alpha.claims
    assert alpha.claims["conditions"][0]["passed"] is True
    assert job.result.cost.confirmed_usd == pytest.approx(0.20)
    assert job.result.cost.public_usd == pytest.approx(0.20)
    assert job.result.cost.basis == "public_estimate_and_reported_charge"
    assert len(job.result.raw["pages"][0]["possible"]) == 1


@pytest.mark.asyncio
async def test_specstream_waits_for_settlement_and_keeps_partial_finds_partial(search_request):
    provider = resolve("specstream", {"api_key": "test"})
    empty = {"data": {"find_id": "fnd_1", "status": "partial", "rows": [], "next_cursor": None}}
    context = FakeContext([specstream_find("partial", "pending"), empty])
    job = await provider.poll(search_request, SearchJob(id="fnd_1", status="running"), context)
    assert job.status == "running"
    assert job.result.cost.confirmed_usd is None
    context = FakeContext([specstream_find("partial", "settled"), empty])
    job = await provider.poll(search_request, job, context)
    assert job.status == "completed"
    assert job.result.status == "partial"
    assert job.result.cost.confirmed_usd == pytest.approx(0.20)


def test_specstream_request_text_carries_query_count_and_acceptance_without_scaffolding(
    search_request,
):
    text = request_text(search_request)
    assert text == ("Find 50 US software companies\nBring back each company's official website.")
    query = search_request.query.model_copy(
        update={
            "query": "Find wholesale distributors headquartered in Japan.",
            "acceptance": "Company sells goods wholesale to other businesses",
        }
    )
    request = search_request.model_copy(update={"query": query, "target_count": 10})
    assert request_text(request).splitlines() == [
        "Find 10 wholesale distributors headquartered in Japan.",
        "Company sells goods wholesale to other businesses.",
        "Bring back each company's official website.",
    ]
    for scaffold in ("Conditions:", "Acceptance logic", "Company unit", "Reference time"):
        assert scaffold not in request_text(request)
    restated = query.model_copy(update={"acceptance": "headquartered in Japan"})
    assert len(request_text(request.model_copy(update={"query": restated})).splitlines()) == 2
    unled = query.model_copy(update={"query": "Wholesale distributors in Japan."})
    assert request_text(request.model_copy(update={"query": unled})).startswith(
        "Find 10 companies. Wholesale distributors in Japan."
    )


@pytest.mark.parametrize(
    ("column", "value", "website"),
    [
        ("organization.website", "https://alpha.example", "https://alpha.example"),
        (
            "knowledge.official_sites",
            ["https://alpha.example", "https://alpha.example/de"],
            "https://alpha.example",
        ),
        ("knowledge.official_sites", [{"url": "https://alpha.example"}], "https://alpha.example"),
        ("knowledge.official_sites", {"url": "https://alpha.example"}, "https://alpha.example"),
    ],
)
def test_specstream_website_shapes(column, value, website):
    row = specstream_row("ent_a", "Alpha", None, "https://registry.example/alpha")
    row["cells"].append(
        {"column_id": column, "label": "Official websites", "value": value, "display": None}
    )
    mapped = company_row(row)
    assert mapped["website"] == website
    (candidate,) = candidates_from_payload([mapped])
    assert candidate.domain == "alpha.example"


def test_specstream_absent_website_value_is_never_used():
    row = specstream_row("ent_a", "Alpha", None, "https://registry.example/alpha")
    row["cells"].append(
        {
            "column_id": "knowledge.official_sites",
            "label": "Official websites",
            "value": "https://stale.example",
            "display": "Couldn't check",
            "absence": "Couldn't check",
        }
    )
    assert company_row(row)["website"] is None


def test_specstream_unpublished_website_is_not_a_domain():
    row = specstream_row("ent_c", "Gamma", None, "https://registry.example/gamma")
    row["cells"].append(
        {"column_id": "link", "label": "Link", "value": "https://gamma.example", "display": None}
    )
    mapped = company_row(row)
    assert mapped["website"] == "https://gamma.example"
    assert mapped["organization.website"] == "Not published"
    row["cells"].pop()
    (candidate,) = candidates_from_payload([company_row(row)])
    assert (candidate.name, candidate.website, candidate.domain) == ("Gamma", None, None)
    assert not candidate.malformed


@pytest.mark.asyncio
async def test_specstream_unknown_status_and_repeated_cursor_fail(search_request):
    provider = resolve("specstream", {"api_key": "test"})
    context = FakeContext([{"data": {"find_id": "fnd_1", "status": "imaginary"}}])
    with pytest.raises(ValueError, match="Unknown SpecStream find status"):
        await provider.poll(search_request, SearchJob(id="fnd_1", status="queued"), context)
    page = {"data": {"find_id": "fnd_1", "status": "running", "rows": [], "next_cursor": "same"}}
    context = FakeContext([specstream_find("running", "none"), page, page])
    with pytest.raises(ValueError, match="pagination did not advance"):
        await provider.poll(search_request, SearchJob(id="fnd_1", status="queued"), context)


def test_specstream_reservation_uses_the_highest_row_rate_or_cap():
    assert estimate_max_cost("specstream", 50) == 50
    assert estimate_max_cost("specstream", 50, {"max_cost_usd": 12}) == 12
