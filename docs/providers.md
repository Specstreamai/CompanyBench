# Providers and settings

CompanyBench compares configured products, including each model, effort and native
research workflow. It does not claim that identically named effort settings are
equivalent across vendors. Presets are in `companybench.providers.registry.PRESETS`;
override their options in `[providers.PRESET-NAME]` in your TOML configuration.
Built-in adapters reject unrecognized options and unsupported effort/generator
values before starting a paid request. `api_key_env` selects an alternate
environment-variable name; credentials themselves do not belong in TOML.

| Preset | Product / model | Credential |
| --- | --- | --- |
| `avina` | Public v1 saved signal, fresh signal for each query/trial | `AVINA_API_KEY` |
| `exa-websets` | Websets, company entity | `EXA_API_KEY` |
| `exa-agent-high` | Exa Agent, high effort | `EXA_API_KEY` |
| `exa-agent-auto` | Exa Agent, auto effort | `EXA_API_KEY` |
| `parallel-core` | FindAll, core generator | `PARALLEL_API_KEY` |
| `parallel-pro` | FindAll, pro generator | `PARALLEL_API_KEY` |
| `specstream` | Deep Search find, compiled, quoted and authorized | `SPECSTREAM_API_KEY` |
| `openai-sol-medium` | GPT-6.1 Sol, medium | `OPENAI_API_KEY` |
| `openai-astra-max` | GPT-6 Astra, max | `OPENAI_API_KEY` |
| `claude-sonnet-medium` | Claude Sonnet 5.5, medium | `ANTHROPIC_API_KEY` |
| `claude-opus-max` | Claude Opus 5.5, max | `ANTHROPIC_API_KEY` |
| `gemini-flash-high` | Gemini 3.8 Flash, high | `GEMINI_API_KEY` |
| `gemini-pro-high` | Gemini 3.1 Pro Preview, high | `GEMINI_API_KEY` |
| `grok-low` | Grok 4.7, low | `XAI_API_KEY` |
| `grok-xhigh` | Grok 4.7, xhigh | `XAI_API_KEY` |

All built-in adapters are **contract-tested**, not live-verified. Avina's supplied
public API contract is a draft and its deployment must be verified before a paid
run. Override `base_url` for the deployment you intend to test. No adapter imports
private Avina application code or uses its internal endpoints.
Local option validation checks the adapter's accepted values; it does not establish
that a model identifier supports that combination of effort, tools, token limits,
and output format. Confirm each selected configuration with a paid smoke test before
running or publishing a comparison.

## Native behavior

Avina creates a saved signal, checkpoints its ID, starts a separate run with a
maximum of 50 companies, polls that specific run, and follows result cursors. It
sets `persona_ids=[]` and an explicit ICP override, avoiding hidden workspace ICP
settings. Monitoring stays off. Use an isolated workspace: the draft's API-only
delivery behavior still requires live verification. Archiving a signal is cleanup,
not cancellation of a running search.

Exa Websets waits for child searches to finish; an initially `idle` Webset is not
completion. Agent uses the current `/agent/runs` API and records its field-level
grounding, native stop reason and `costDollars`. No Exa Connect data sources,
enrichments, previews or recall-estimation operations are requested.
Explicit effort overrides also support documented fixed efforts and `ultra`.
Reservations follow the chosen effort: Auto defaults to a $5 cap, Ultra to $20.
`max_cost_usd` accepts $1–$100 for Auto/Ultra; `max_duration_seconds` accepts
300–10,800 for Ultra. These override the named preset and appear in frozen settings.

Parallel submits the complete acceptance logic as a native match condition. Only
`matched` candidates become its returned company list; its rejected/generated
internal candidates remain in raw artifacts. Its match classification is not the
benchmark's validity judgment.

SpecStream reads a request in plain words into conditions, so instruction lines would be
read as conditions too. Its adapter sends `POST /v1/parse` the query sentence with the
requested count after its leading "Find", the acceptance text as a second sentence, and
one sentence asking for each company's official website, because identity pooling needs a
hostname. This is the query and acceptance content of `objective(request)` without its
labels and rule dump. It quotes the reading for the requested count with `POST /v1/capacity/quotes`, and authorizes that quote with
`POST /v1/capacity/executions`, sending the quote's maximum as `confirm_max_cents`. Reading
and quoting spend nothing; the quote is checkpointed so a resumed task authorizes the same
quote with the same request key. An unrunnable reading fails before any paid request. The
optional `max_cost_usd` refuses a quote above it. Polling reads `GET /v1/finds/{id}` and
follows `next_cursor` on `GET /v1/finds/{id}/rows` (100 rows a page) until it is null.
Each delivered row becomes a company in native order: its `identity` cell is the name, the
read value of the `organization.website` or `knowledge.official_sites` cell (the first URL
of a list; else a `link`, website or domain cell) is the website, an unpublished website stays empty, other cells are kept as claims, and every
cell and condition source URL is kept as a citation. Undelivered `possible` rows remain in
raw artifacts only. A finished find keeps polling while its charge settlement is
`pending`. Cancellation uses `POST /v1/finds/{id}/cancel`; there is no cleanup call.

Foundational-model presets use native web search. There is no outer search agent,
query expansion loop or list refill. OpenAI uses Responses, standard reasoning
mode and standard service tier. Gemini uses Interactions with Google Search and
URL context. Grok uses Responses with web search only.

Claude continues only native `pause_turn` responses. Citations cannot be combined
with strict JSON output, so it first requests a JSON answer without strict mode.
If extraction is needed, a single tool-free formatting call converts that answer;
its cost and latency count. Names, domains and ordering are checked against the
native answer, including citation annotations accumulated across continuation
responses. Evidence text must be copied verbatim; the formatter cannot add
researched companies or facts. Refusal, truncation,
tool errors and formatting failures remain explicit outcomes.

OpenAI and Claude default to 128,000 generated tokens per query (including
reasoning); Claude's continuation requests receive the remaining output allowance.
Gemini's native cap is 65,536. **Grok's 262,144-token cap covers visible output only**:
its API does not apply `max_output_tokens` to reasoning or tool calls. The harness
deadline and soft cost budget therefore remain relevant. Search-count defaults are
vendor-native; optional `max_tool_calls` (OpenAI) or `max_uses` (Claude) overrides
are recorded as different configurations.

Gemini long-decode `incomplete` responses remain truncated and retain their native
`continuation_token`. Automatic resumption is not enabled: the documented token
does not establish whether returned text and usage are incremental or cumulative.
That path requires a live contract fixture before publication as a supported
continuation workflow. The normal synchronous Interactions path is implemented.

Model and effort choices are starting points, not assertions of the best cost or
quality. Keep full preset names in reports. A model's maximum-effort run is a
capability-ceiling attempt and can be more expensive without improving this task.

## Cost provenance

Rates are checked as of **2026-10-06**. Measured token/credit usage is distinct from
estimated USD and API-confirmed USD. Public estimates exclude free allowances,
taxes and private discounts. `account_credit_price` supplies an account-rate
estimate; it is not invoice confirmation.

Avina uses Growth ($1,699 / 6,500 credits) and Exa Websets uses Pro ($449 / 100,000
credits) at full utilization. Their estimates allocate subscription fees; actual
monthly cash outlay and marginal spend differ. Override
`public_monthly_usd` / `public_included_credits` to compare a documented tier.
Avina credits are inferred from returned signal types, not an unsafe shared-account
balance delta. Websets credits are inferred from native evaluated matches.

Parallel uses its per-run plus native-match tariff. Exa Agent retains the API's
reported charge. SpecStream bills per delivered row; its public estimate sums the
`billed_units` rates the find reports, and its confirmed charge is `amount_captured_cents`
once `settlement_status` is `settled`. Grok exposes invoice-confirmed request cost through
`usage.cost_in_usd_ticks / 10_000_000_000`, including native tool use. Other native
models apply versioned rates to observed usage. Missing search usage makes a total
USD estimate unknown rather than treating hidden search work as free. All raw
usage remains available for repricing. Gemini Flash 3.8's promotional rates end on
2026-12-31; set `price_date` when repricing later activity.

## Extension contract

An immediate adapter subclasses `ImmediateProvider` and implements
`async search(request, context) -> SearchResult`. A job adapter subclasses
`JobProvider` and implements `submit` and `poll`; `cancel` and `cleanup` are optional.
The shared client owns sync/async facades, polling and deadlines.

Route every request through `context.request(method, url, operation=..., ...)`.
Use stable operation names, set `billable=True` on paid submissions, and supply an
idempotency header only when the vendor documents it. Save native handles through
`context.checkpoint`. Do not retry a POST blindly or wrap the transport in an SDK
that retries invisibly. Preserve native list order, duplicates, malformed rows,
raw evidence and usage. The grader decides validity later.

Load a trusted local provider as `my_package.provider:create` or
`/absolute/path/provider.py:create`. The callable receives `**options` and returns
an `ImmediateProvider` or `JobProvider` instance. Judge factories instead receive
one `options={...}` dictionary; dataset factories receive no arguments. Python
file modules include their source-content hash in the module identity and support
dataclasses. These imports execute Python, so
only select code you trust. The provider's declared name is preserved; the runner
also records the selected system reference. Quoted TOML keys allow local paths:

```toml
[run]
providers = ["my_package.provider:create"]

[providers."my_package.provider:create"]
model = "my-model"
```

Distributable packages can register factories through entry points:

```toml
[project.entry-points."companybench.providers"]
my-search = "my_package.provider:create"
```

`provider_names()` lists entry points without loading their code. Duplicate names,
including collisions with built-in presets, fail explicitly. Custom providers
have unknown public cost unless they supply their own `Cost`; missing prices are
never inferred from a similarly named vendor.

## Contracts and pricing sources

- [Avina Node public contract](https://github.com/Mesh-Interactive/mesh-analytics-backend/pull/273), [Python implementation](https://github.com/Mesh-Interactive/mesh-analytics-backend-python/pull/1796), [pricing](https://www.avina.io/pricing)
- [Exa Websets](https://exa.ai/docs/websets/api/websets/create-a-webset), [Agent](https://exa.ai/docs/reference/agent-api/create-a-run), [Websets pricing](https://websets.exa.ai/websets/billing), [Agent pricing](https://exa.ai/docs/admin/pricing)
- [Parallel FindAll](https://docs.parallel.ai/findall-api/findall-quickstart), [pricing](https://docs.parallel.ai/getting-started/pricing)
- [SpecStream OpenAPI](https://api.specstream.ai/openapi.json), [agent guide](https://specstream.ai/agents.md), [pricing](https://specstream.ai/pricing)
- [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search), [pricing](https://developers.openai.com/api/docs/pricing)
- [Claude web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [models and prices](https://platform.claude.com/docs/en/models/overview)
- [Gemini Interactions](https://ai.google.dev/api/interactions-api), [grounding](https://ai.google.dev/gemini-api/docs/google-search), [pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Grok Responses](https://docs.x.ai/developers/rest-api-reference/inference/responses), [cost tracking](https://docs.x.ai/developers/cost-tracking), [pricing](https://docs.x.ai/developers/pricing)
