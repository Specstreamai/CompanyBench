# CompanyBench

An open benchmark for **company list building**: given a search query, which companies
does a system return, how many satisfy the requirements, and what does the useful list
cost in money and time?

CompanyBench includes **250 public-web queries**, search adapters for Avina, Exa, Parallel,
and foundational models, and **three judging options**. Fourteen predefined combinations
of providers and settings are included. It runs locally with a Python CLI, saves resumable
artifacts, and produces inspectable HTML, JSON, CSV, and Markdown reports.

**Status:** this repository contains the catalogue and benchmark implementation, not measured
provider rankings. Adapters have offline contract tests; they have not been live-verified.
Avina's adapter follows a draft API contract whose deployment still needs verification.

## Example queries

These are actual catalogue entries. L1–L4 describe increasing complexity; they are authored
labels, not measured difficulty scores.

| ID | Complexity | Query |
|---|---|---|
| `CSB-001` | L1 · Basic filters | Find B2B SaaS companies headquartered in the United States. |
| `CSB-002` | L2 · Multiple filters | Find marketing agencies headquartered in the United Kingdom with 11–50 employees. |
| `CSB-129` | L3 · Technology evidence | Find financial-services companies that publicly describe Snowflake and dbt operating together in their production analytics stack. |
| `CSB-064` | L4 · Ordered events | Find B2B software companies headquartered in the United States that closed a Series A round in the last 180 days and then advertised their explicitly stated first Head of Finance role within 60 days after that close. |

Each query has acceptance criteria, evidence requirements, and classification fields.
Download the complete [CSV, JSON, or XLSX catalogue](catalogue/README.md), or inspect a case
after installation:

```bash
companybench queries --id CSB-064 --full
```

## Results explorer

The [interactive site](website/README.md) presents quality, cost, and search time, with
shared filters, provider comparisons, and company-level evidence inspection. Its initial
data is **synthetic**, not measured benchmark results. It can also load a saved CompanyBench
report locally in your browser.

Open the self-contained [preview](website/preview.html) after downloading it, or serve the site:

```bash
python3 -m http.server 8000 --directory website/dist --bind 127.0.0.1
```

Then open `http://localhost:8000`. No frontend build or API keys are required.

## Install

Requires Python 3.11 or later.

```bash
git clone https://github.com/Mesh-Interactive/CompanyBench.git
cd CompanyBench
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
companybench validate
```

With [uv](https://docs.astral.sh/uv/), use `uv sync --extra dev`, then prefix commands with
`uv run`. Windows activation instructions and the full setup guide are in the
[quickstart](docs/quickstart.md).

## Run a small real benchmark

This example uses Exa Agent High to search three queries, requesting up to ten companies
per query. OpenAI independently researches the results and runs the default LLM judge.
Both API keys are required. **The benchmark makes paid API calls.**

```bash
export EXA_API_KEY="your-exa-api-key"
export OPENAI_API_KEY="your-openai-api-key"

# Preview the selected queries, settings, and cost assumptions without API calls.
companybench run --provider exa-agent-high --sample 3 --seed 42 \
  --target-count 10 --output runs/first-run --dry-run

# Run search, research, grading, and reporting.
companybench run --provider exa-agent-high --sample 3 --seed 42 \
  --target-count 10 --output runs/first-run
```

Open the printed `report.html` path to inspect the results. The dry-run estimate does not
include the full research and judging bill. Endpoint and model access still need live
verification; see [provider compatibility](docs/providers.md).

The [quickstart](docs/quickstart.md) is the complete running guide: credentials, multiple
providers, all 250 queries, resume, regrading, and publication. Choose providers explicitly;
removing query selectors selects the entire catalogue.

### Try it without API keys

```bash
companybench demo --output runs/demo
```

The offline demo uses invented companies, evidence, prices, and timings. It makes no API
calls and prints an HTML report path.

## Explore query segments

Use `--segment` with `queries` to inspect a subset or with `run` to benchmark it. A few
available segments:

| Segment | What it selects |
|---|---|
| `simple` | Basic filters: L1 queries |
| `complex` | Specialist evidence and compound requirements: L3 and L4 queries |
| `technographic` | Requirements about technologies a company uses |
| `ai_companies` | AI vendor searches; currently two queries |
| `manufacturing` | Manufacturing industry queries |
| `signals` | Date-sensitive requirements, including recent events and dated financial evidence |

```bash
companybench queries --segment technographic --sample 5 --seed 42
companybench queries --segment ai_companies
companybench run --provider exa-agent-high --segment manufacturing \
  --sample 3 --seed 42 --target-count 10 --dry-run
```

Combine segments with filters for narrower subsets, such as simple manufacturing queries:

```bash
companybench queries --segment manufacturing --where 'complexity == "L1"'
```

Selection also supports stable IDs, inclusive index ranges, explicit index lists, and
seeded sampling. See the [complete filtering guide](docs/dataset.md#selection-and-custom-datasets) for all
segments, fields, and intersections. The [research ledger](docs/sources.md) records the
sources of query ideas.

## What it measures

Every returned position is retained, including duplicates and malformed entries. Search
results are pooled by query and company, researched independently, and graded against the
authored acceptance conditions using the same frozen evidence packet for every judge.
Missing evidence stays unknown. Judges do not see provider names, ranks, costs, or answer keys.

Reports include valid companies found, precision, valid companies as a percentage of the
requested count, cost per valid company, search time, and search time per valid company. The quality score rewards
valid yield while penalizing filler; a separate cost efficiency score includes search cost.
**True recall is reported only for the ten exhaustive reference cohorts.** Open-ended searches
have no known complete denominator. See the [methodology](docs/methodology.md) for formulas,
uncertainty, failed runs, and aggregation.

Reports can be filtered by the same query segments and metadata fields.

## Providers and settings

A configuration means a specific provider with fixed settings, including its model and
effort level where applicable. For example, Exa Agent High and Exa Agent Auto are two
configurations because their settings can affect quality, cost, and time. Use the name in
the first column with `--provider`.

| CLI name | Provider and settings |
|---|---|
| `avina` | Avina company signal search |
| `exa-websets` | Exa Websets |
| `exa-agent-high` | Exa Agent, high effort |
| `exa-agent-auto` | Exa Agent, auto effort |
| `parallel-core` | Parallel FindAll, core |
| `parallel-pro` | Parallel FindAll, pro |
| `specstream` | SpecStream Deep Search |
| `openai-sol-medium` | GPT-6.1 Sol, medium |
| `openai-astra-max` | GPT-6 Astra, max |
| `claude-sonnet-medium` | Claude Sonnet 5.5, medium |
| `claude-opus-max` | Claude Opus 5.5, max |
| `gemini-flash-high` | Gemini 3.8 Flash, high |
| `gemini-pro-high` | Gemini 3.1 Pro Preview, high |
| `grok-low` | Grok 4.7, low |
| `grok-xhigh` | Grok 4.7, xhigh |

Foundational-model configurations use native web search. Effort names are vendor-specific;
these presets are starting points, not proven optimal settings. The [provider guide](docs/providers.md)
documents exact contracts, native behavior, keys, and extension interfaces. Public price
assumptions and unknown-cost handling are in [pricing](docs/pricing.md).

The default judge is an evidence-grounded LLM (`llm`). OpenAI Decisions (`decisions`) and
Jev / TypeSafe (`jev`) are optional; choose any combination and inspect each judge's results
separately. Research uses OpenAI independently of the chosen search provider. See
[judges and review](docs/judges.md) for prompts, limitations, and optional human corrections.

## Contribute

Add queries as JSONL or a small Python dataset factory. Add providers through an immediate
search adapter or a submit/poll adapter; the shared client supplies synchronous and
asynchronous search. Providers and judges can also be installed as entry-point plugins.
No server or database is required.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [extension examples](examples/README.md),
[architecture](docs/architecture.md), [benchmark design references](docs/benchmark-design.md), and
the [development workflow](CLAUDE.md). Tests use mocks and synthetic fixtures, so contributors
can work without API keys. Reports and frozen bundles retain errors and provenance to make
corrections reviewable.
The [corrections policy](docs/corrections.md) explains how disputed results are retained and revised.

## Ownership and limits

Avina / Mesh Interactive created CompanyBench and has a commercial interest in the results.
The catalogue is an **authored breadth sample**, not a measurement of which searches customers
run most often. Automated results are preliminary: evidence retrieval and judges can be wrong,
and agreement between judges is not proof of correctness. Published comparisons should name
the exact configurations, dataset, selection, date, judge, and cost assumptions, and include
unfavorable results and failures.

Code and authored catalogue are available under the [MIT license](LICENSE). Third-party
source material retains its own rights; publication omits captured source text without
recorded redistribution permission.
