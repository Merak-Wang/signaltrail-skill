# Usage

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

Use this guide after the [quick start](../README.en.md). It covers local configuration,
host setup, and where to find a finished report. [中文](zh-CN/usage.md)

## Installation

Install the checkout with `python -m pip install -e .`, then load its root `SKILL.md` in
your agent. Keep the checkout: source configuration, schemas, and templates are runtime inputs.
When launching outside it, set `DAILY_INTEL_SKILL_DIR` to the absolute checkout path.

Windows can use system Edge. For browser collection on macOS or Linux, install Chromium
in the same Python environment:

```sh
python -m playwright install chromium
```

On a new Debian or Ubuntu machine, `python -m playwright install-deps chromium` installs
the system libraries and may require administrator access. The Hermes install scripts in
the README synchronize the skill to `skills/research/signaltrail`; Windows-specific setup
is in [windows-setup.md](../references/windows-setup.md).

## Data directory

Pass `--data-dir DATA_DIR` before the subcommand, or set `DAILY_INTEL_DATA_DIR`.
Reuse the existing directory on upgrades. Hermes defaults are
`%LOCALAPPDATA%\hermes\daily-intelligence` on Windows and `~/.hermes/daily-intelligence`
on macOS/Linux. A configured `HERMES_HOME` uses its `daily-intelligence/` child.

```sh
signaltrail --data-dir DATA_DIR data-root status
```

The first run binds the data root. `data-root adopt` explicitly changes that binding;
use it only for a deliberate migration. It does not copy existing reports to the new path.
Run files and their referenced artifacts must belong to the same data root.

## Language and source order

The default report language is `zh-CN`. Ask the agent for English, or pass `--language en`
to `run-edition`. The command prepares the run; the agent still needs to complete writing
through [SKILL.md](../SKILL.md). Set the default in `configs/sources.yaml`:

```yaml
output:
  language: en
```

Translated titles, summaries, analysis, and reading formats follow that language;
original headlines remain unchanged.

Edit [sources.yaml](../configs/sources.yaml) for formal reports and
[discovery-sources.yaml](../configs/discovery-sources.yaml) for the monitor.
Formal sources use `report_target: 15` and `report_max: 15`; fewer available candidates
produce fewer summaries. Discovery sources use zero for both and never fill report quotas.

`collection.item_order: source` preserves the page, ranking, or feed order.
`published_at` sorts the fetched index by valid publication time, newest first; missing
and tied times retain their input order. A source can override `item_order` locally.
Both modes preserve `source_rank`; summaries are not re-sorted by importance.
Hugging Face Papers uses Trending order, which can include older papers.

## Metered Hermes runs

For the audited Hermes 0.21 integration, start the host through:

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

Replace the uppercase placeholders with paths. `HERMES_PYTHON` is the Hermes virtual
environment's Python with SignalTrail installed; `PROMPT.txt` contains the report request.
Optional `--provider` and `--model` select the route.

This entry point starts metering before model work, includes workers and supported auxiliary
calls, and launches an independent evaluator with a separate task. It checks host counters
before sealing. Missing observations remain partial. Direct Hermes CLI and legacy Cron
do not automatically receive the same coverage. See [usage metering](../references/llm-usage.md)
for exact limits and Codex/OpenClaw imports.

Other agents can drive the same writing packets. Without an audited usage adapter, the run
remains usable but has explicit `unmetered` coverage and null token totals. A host without
automatic evaluator scheduling must dispatch the dossier itself and call `finalize-evaluation`.

## Reports and recovery

| Under `DATA_DIR` | Contents |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` and `.md` | Original versioned report |
| Matching `.html` and `.pdf` | Reading and printing copies |
| `reports/index.html` | Local report history |
| `runs/YYYY-MM-DD/EDITION.json` | Current stage, artifact paths, errors, next commands |
| `usage/` and `host-runs/` | Usage events and host launch receipts |

The workflow also writes a portable desktop HTML copy with available validated images embedded.
It returns HTML first, then finishes PDF, requested Notion delivery, and evaluation in a retryable
tail. The default PDF soft size budget is 50 MiB; exceeding it records a warning.

Read the run manifest before retrying. Use its `tail.command` for pending delivery work.
Never edit status JSON or delete a lock while its process is active. Detailed stage recovery
is in the [runbook](../references/runbook.md).

Collection keeps login, challenge, rate-limit, and failure states visible. To handle a pending
source interactively, run `verify-pending` when you are ready for a browser window.
Unattended runs must not pass `--open-verification`.

Notion is optional and requires explicit `--publish` plus credentials configured through
[Notion setup](../references/notion-setup.md). Local reports remain available when remote
delivery fails.
