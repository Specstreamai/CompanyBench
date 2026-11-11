# Pricing and cost accounting

CompanyBench records observed usage separately from calculated prices. All amounts are USD.
The built-in rate snapshot is **2026-10-06**; it is not a live quote. Verify prices and account
terms before a paid run. The implementation is [pricing.py](../src/companybench/pricing.py).

## Three cost views

| View | Meaning |
|---|---|
| `public` | Observed usage priced at the declared public rate assumptions. Default comparison view. |
| `account` | An explicitly supplied account rate or per-query amount. This is an estimate, not invoice proof. |
| `confirmed` | A monetary charge reported by the API, when available. This is not an independently audited invoice. |

Select a view without repeating searches:

```bash
companybench report runs/pilot --cost-view public --output runs/pilot/public-cost
companybench report runs/pilot --cost-view confirmed --output runs/pilot/confirmed-cost
```

Missing usage, price, or charge remains **unknown**, never zero. Reports retain known
subtotals and price coverage. Do not rank systems by cost using incomplete totals. API-reported
charges and public estimates can differ because of discounts, caching, allowances, or vendor
billing rules. Public estimates exclude taxes and free allowances.

Search cost belongs to the evaluated system. Independent evidence research and judging have
a separate evaluation-cost ledger; those costs are not charged to a provider's cost per
valid company. Human review imports record zero API spend, not free human labor. Unknown
evaluation costs remain visible too.

## Company-search products

| Configuration | Public estimate in this snapshot |
|---|---|
| Avina | Credits × $1,699 / 6,500, allocating the assumed Growth subscription at full utilization. |
| Exa Websets | Credits × $449 / 100,000, allocating the assumed Pro subscription at full utilization. |
| Exa Agent high | $0.50 for a completed native run; API-reported charge retained separately. |
| Exa Agent auto | $0.10 per compute unit + $0.005 per search, capped at $5 per completed run. |
| Parallel core | $2 per native run + $0.15 per provider-matched entity. |
| Parallel pro | $10 per native run + $1 per provider-matched entity. |
| SpecStream | 5¢, 15¢ or $1 per delivered row, at the rate the API reports for each billed row; API-captured charge retained separately. |

Subscription allocation assumes the entire included credit pool is used. It is neither the
incremental cash cost of a query nor the amount a new account must pay. Avina's 6,500-credit
denominator is an explicit tier assumption; verify the actual entitlement. Change the
declared tier when that assumption does not apply. Avina credit usage is inferred from
returned signal types; Websets credits are inferred from native evaluated matches. These
are estimates, not invoice-confirmed credit debits.

Parallel's native match decision determines tariff usage, not benchmark validity. Exa Agent
retains its reported `costDollars`; reported contact enrichments, if present, add their native
tariff, although the supplied configuration does not request them. A failed or incomplete
request is not automatically free. Unknown charges remain unknown.

Sources: [Avina](https://www.avina.io/pricing),
[Exa Websets](https://websets.exa.ai/websets/billing),
[Exa Agent](https://exa.ai/docs/admin/pricing),
[Parallel](https://docs.parallel.ai/getting-started/pricing), and
[SpecStream](https://specstream.ai/pricing).

## Native web-search models

These are the standard-context token assumptions in USD per million tokens. Output includes
reasoning tokens when the API reports them as billable output.

| Model | Input | Output | Cached input |
|---|---:|---:|---:|
| GPT-6.1 Sol | 2.00 | 10.00 | 0.10 |
| GPT-6 Astra | 10.00 | 50.00 | 1.00 |
| Claude Sonnet 5.5 | 2.00 | 10.00 | 0.20 |
| Claude Opus 5.5 | 4.00 | 20.00 | 0.20 |
| Gemini 3.8 Flash | 0.75 | 3.75 | 0.075 |
| Gemini 3.1 Pro Preview | 2.00 | 12.00 | 0.20 |
| Grok 4.7 | 2.00 | 6.00 | 0.50 |

The model adapters additionally price reported web-search calls at $0.01 for OpenAI,
$0.01 for Claude, $0.014 for Gemini, and $0.005 for Grok. These are vendor-specific billing
units, not equivalent amounts of search work. Missing hosted-search usage makes the total
estimate unknown even when token usage is available. Grok's API-reported request cost is
retained separately when returned.

The estimator applies supported long-context tiers **per request**, includes reported cache
write premiums, and sums continuation/formatting calls. Gemini Flash's promotional rates
double from 2027-01-01 when `price_date` is set accordingly. The default remains the recorded
snapshot date, so an old run is not silently repriced as time passes. Overrides do not
automatically cover every future vendor pricing change; inspect the estimator and native
usage when a tariff changes.

Sources: [OpenAI](https://developers.openai.com/api/docs/pricing),
[Claude](https://platform.claude.com/docs/en/models/overview),
[Gemini](https://ai.google.dev/gemini-api/docs/pricing), and
[Grok](https://docs.x.ai/developers/pricing).

## Research and judges

The default researcher and LLM judge use GPT-6 Astra at the declared token rates. Research
also uses paid hosted search. The researcher pools companies across systems and trials
within a query, so the evaluation bill is not simply a fixed fee per returned row.

OpenAI Decisions defaults to GPT-6 Luna with the input-only beta assumption of **$0.10 per
million input tokens**. Jev 1.13 defaults to **$0.042 per million input tokens**. Both preserve
missing usage as unknown and accept explicit rate overrides. These are judging API tariffs,
not the general chat-generation prices of similarly named models. See the
[Decisions guide](https://developers.openai.com/api/docs/guides/decisions) and
[TypeSafe models](https://docs.typesafe.ai/models).

## Declare overrides

Overrides belong to the selected preset's TOML section. Keep the assumption and its source
with your run. For example:

```toml
[run]
providers = ["exa-websets", "gemini-flash-high"]
judges = ["llm", "decisions", "jev"]

[providers.exa-websets]
public_monthly_usd = 449
public_included_credits = 100000
account_credit_price = 0.00449 # Illustrative declared account rate; not a confirmed charge.

[providers.gemini-flash-high]
price_date = "2026-10-06"

[judges.decisions]
input_usd_per_million = 0.10
output_usd_per_million = 0

[judges.jev]
input_usd_per_million = 0.042
output_usd_per_million = 0
```

`public_token_rates = [input, output, cached_input]` can replace a model's base rates;
supported context/date adjustments still apply. `account_cost_usd` supplies an explicit
per-query account amount; only use it when that same amount genuinely applies to every
query in the configuration. Merely changing a configuration file does not reprice completed
artifacts. A pricing correction must preserve observed usage, record the change, and produce
a new version rather than editing a published bundle in place.

## Plan spend

`run --dry-run` reports known search reservation estimates and unknown estimates. It does
not reserve funds or predict complete evaluation costs. The default is 50 requested
companies; without selectors, the full 250-query catalogue runs. Fourteen configurations
therefore create 3,500 search tasks per trial, before independent research and grading.

`--budget-usd` is a soft, estimate-based limit. In-flight jobs, native tool use, opaque usage,
and unpriced operations can exceed it. Timeouts and cleanup do not guarantee cancellation
or refunds. Run a small paid pilot, inspect observed usage, and use vendor account controls
when an enforceable spending limit is required.
