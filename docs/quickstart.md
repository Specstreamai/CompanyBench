# Quickstart

CompanyBench runs locally on Python 3.11+. No database, service, or API keys are needed to
inspect the catalogue, validate a dataset, or run the synthetic demo.

## Install and inspect

```bash
git clone https://github.com/Mesh-Interactive/CompanyBench.git
cd CompanyBench
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
companybench validate
companybench providers
companybench judges
companybench demo --output runs/demo
```

On Windows, activate with `.venv\Scripts\activate`. With uv, replace the environment and
pip steps with `uv sync --extra dev`, then use `uv run companybench ...`.

The demo prints an HTML report path and uses entirely synthetic data. It demonstrates
duplicates, unknowns, failures, evidence inspection, and reporting without measured provider
results. Run each demo into a new directory.

## Choose queries

These commands only read the catalogue:

```bash
companybench queries --segment simple
companybench queries --segment technographic --sample 10 --seed 42
companybench queries --segment ai_companies
companybench queries --where 'industry == "Manufacturing" and complexity in ["L1", "L2"]'
companybench queries --range 100:150
companybench queries --indices '[12,101,142]'
companybench queries --id CSB-001 --id CSB-261 --full
```

The same selectors work with `run` and `search`. Ranges include both endpoints. Indexes
are one-based release positions; stable query IDs are different. Explicit IDs, indexes,
and ranges are unioned, repeated filters and segments intersect, and seeded sampling happens
last. Query order remains the catalogue order. Choose the subset before inspecting outcomes.

Named segments are `simple`, `complex`, `technographic`, `ai_companies`, `ai_adoption`,
`manufacturing`, `signals`, and `finite_reference`. Any scalar or list metadata field can
be used in a filter. See [dataset](dataset.md) for the schema, custom JSONL/Python datasets,
and the separate `development` examples.

```bash
companybench export catalogue.csv
companybench export manufacturing.jsonl --segment manufacturing
companybench validate --dataset manufacturing.jsonl
```

XLSX export requires the `excel` extra, already included in the development installation.

## Configure a paid run

Adapters are offline contract-tested, not live-verified. Confirm access to the exact endpoint
and model before running a large comparison. Avina follows a draft contract; use an isolated
benchmark workspace and verify its deployment and delivery behavior first.

Supply credentials through environment variables in your shell or secret manager. Keys
are never configuration-file values; CompanyBench does not automatically load a `.env` file.

| Component | Environment variable |
|---|---|
| Avina | `AVINA_API_KEY` |
| Exa configurations | `EXA_API_KEY` |
| Parallel configurations | `PARALLEL_API_KEY` |
| SpecStream | `SPECSTREAM_API_KEY` |
| OpenAI configurations, independent research, LLM and Decisions judges | `OPENAI_API_KEY` |
| Claude configurations | `ANTHROPIC_API_KEY` |
| Gemini configurations | `GEMINI_API_KEY` |
| Grok configurations | `XAI_API_KEY` |
| Jev judge | `JEV_API_KEY` or `TYPESAFE_API_KEY` |

Only selected components need credentials. A complete benchmark with any search provider
needs `OPENAI_API_KEY` for independent research and, by default, the LLM judge. A search-only
run needs only its search providers' keys. `doctor` checks local key presence and configuration;
it does not verify credentials with the vendor or make paid calls.

```bash
companybench doctor --provider exa-agent-high --provider parallel-core
companybench run --provider exa-agent-high --provider parallel-core \
  --sample 5 --seed 42 --target-count 10 --output runs/pilot --dry-run
```

Read the plan's query IDs, task count, missing credentials, and cost assumptions. Dry-run
estimates are incomplete when usage or prices are unknown, and do not predict the full
research and grading bill. `--budget-usd` is a **soft estimate**, not a guaranteed charge cap.
Already accepted remote work and unknown-price requests can exceed it. See [pricing](pricing.md).

The following command makes paid calls. It requests ten companies for each of five queries
from two systems, then researches, grades, and reports the results:

```bash
companybench run --provider exa-agent-high --provider parallel-core \
  --sample 5 --seed 42 --target-count 10 --output runs/pilot
```

For a smaller endpoint check, `companybench smoke --provider exa-agent-high --output runs/smoke`
is also **paid**: one development query, up to three requested companies, search only.
No live API calls or paid measurements were used to validate this repository's initial release.

## Run a declared comparison

Copy [minimal.toml](../configs/minimal.toml) or
[full-comparison.toml](../configs/full-comparison.toml) and edit it. The latter names all
14 configurations; it can incur substantial costs. With no query selector, all 250 public
queries run. The default target is 50 companies and one trial per query/configuration.

```bash
companybench run --config configs/full-comparison.toml --dry-run
```

After reviewing the plan and configuring the selected keys, removing `--dry-run` starts the
paid comparison. Use `--output runs/comparison` to choose its directory. Use `--trials 3`
for three declared trials, or `--judge llm --judge decisions --judge jev` to use all three
judges. More trials and judges increase cost. A complete run compares all selected judges
against the same evidence and retains their scores separately.

CLI values override their matching configuration values. Use a timezone-aware
`--reference-time 2026-10-06T00:00:00Z` to set a declared reference time; otherwise the run
records its start time. Historical reference time does not turn live web retrieval into
a historical archive. See [methodology](methodology.md) before interpreting dated signals.

## Resume or work by stage

Use a new directory for a new experiment. `resume` uses the saved manifest, preserves
completed work, and polls accepted jobs. It does not blindly resubmit work whose acceptance
is uncertain; that requires reconciliation with the provider.

```bash
companybench resume runs/pilot --dry-run
companybench resume runs/pilot
```

The stages are also available separately. Search, research, and grading below can make
paid calls; reporting is offline:

```bash
companybench search --provider exa-agent-high --sample 5 --seed 42 --output runs/staged
companybench research runs/staged
companybench grade runs/staged --judge llm --judge decisions
companybench report runs/staged
```

Grading another judge reuses frozen evidence. Changing research settings, adding a provider
to the cohort, or applying reviewed identity corrections requires a new evidence revision
and regrading. Optional blinded human review and identity corrections are documented in
[judges](judges.md). `companybench cleanup runs/staged` only lists benchmark-owned remote
resources; `--execute` asks adapters to clean them up. Cleanup does not imply cancellation
of active jobs or a refund.

## Inspect and publish

The report command prints the HTML path. Its directory also contains `report.json`,
`report.md`, and `results.csv`. HTML supports provider/judge selection and inspection of
query results, judgments, and evidence. More focused reports require no new API calls:

```bash
companybench report runs/pilot --segment manufacturing --output runs/pilot/manufacturing
companybench report runs/pilot --prefix 10 --cost-view public --output runs/pilot/top10
companybench report runs/pilot --publication --output runs/pilot/release-v1
```

Use `--evidence-version FULL_SHA256` to report a retained evidence revision. Its
`evidence/VERSION/metadata.json` records the research settings. This supports comparisons
after a new research pass without rewriting earlier evidence or rerunning search.

A shorter prefix evaluates original result positions without refilling duplicates or bad
entries; the complete search cost remains attributed. Public, account, and confirmed cost
views are distinct. Publication requires complete declared grading coverage, but preserves
search failures. It creates a redacted, checksummed `publication/` bundle and refuses to
silently replace a changed bundle. Use a new output directory for a corrected release.
Share that bundle, not the private run directory: raw API responses and cached sources can
contain information unsuitable for redistribution. Third-party excerpts without permission
are omitted from publication.

Automated comparisons remain labeled preliminary. Publish the exact query selection,
configurations, judge, evidence version, unknown rates, errors, and cost basis alongside
any claim. The [methodology](methodology.md) explains what each metric can establish.
