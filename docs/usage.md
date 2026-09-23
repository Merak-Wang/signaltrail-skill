# Usage

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-23

Use this guide after the [quick start](../README.en.md). It covers local configuration,
host setup, and where to find a finished report. [中文](zh-CN/usage.md)

## Installation

Install the checkout with `python -m pip install -e .`, then load its root `SKILL.md` in
your agent. The Python import is `signaltrail`; its module entry point is
`python -m signaltrail.cli`. Keep the checkout: configuration, schemas and templates are runtime
inputs. `DAILY_INTEL_SKILL_DIR` remains accepted when launching outside the checkout.

The checkout maintains one root `src/`. A release build places the complete installable skill
in `dist/signaltrail/`, including `SKILL.md`, source, configuration, schemas, templates, references,
and assets. Run the installer from the checkout or extracted package root; it synchronizes
the complete skill into Hermes and installs the Python project from that directory. Virtual
environments and runtime data are excluded. `-Editable` (Windows) or `--editable` (macOS/Linux)
instead binds the Python installation to the original source directory for development.

The Python distribution is now `signaltrail-skill`, replacing `daily-intelligence-skill`.
The main command is `signaltrail`; new installations do not provide `daily-intel`. Update scripts
and scheduled jobs to use the new command. Existing `DAILY_INTEL_*` environment variables and
stored report IDs remain supported.

Windows can use system Edge. For browser collection on macOS or Linux, install Chromium
in the same Python environment:

```sh
python -m playwright install chromium
```

On a new Debian or Ubuntu machine, `python -m playwright install-deps chromium` installs
the system libraries and may require administrator access. The Hermes install scripts in
the README synchronize the skill to `skills/research/signaltrail`; Windows-specific setup
is in [windows-setup.md](../references/windows-setup.md).

## Upgrade from an earlier version

Stop SignalTrail and Hermes jobs before moving data or browser profiles. Uninstall the old Python
distribution, then install the complete new checkout or release package. On Windows:

```powershell
python -m pip uninstall daily-intelligence-skill
Move-Item "$env:LOCALAPPDATA\hermes\daily-intelligence" "$env:LOCALAPPDATA\hermes\signaltrail"
Move-Item "$env:LOCALAPPDATA\hermes\browser-profiles\daily-intelligence" "$env:LOCALAPPDATA\hermes\browser-profiles\signaltrail"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\signaltrail" data-root adopt
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\signaltrail" data-root status
```

On macOS/Linux, from the checkout or complete extracted package:

```sh
python -m pip uninstall daily-intelligence-skill
mv ~/.hermes/daily-intelligence ~/.hermes/signaltrail
mv ~/.hermes/browser-profiles/daily-intelligence ~/.hermes/browser-profiles/signaltrail
bash ./scripts/install.sh
signaltrail --data-dir "$HOME/.hermes/signaltrail" data-root adopt
signaltrail --data-dir "$HOME/.hermes/signaltrail" data-root status
```

Run each rename only when the old directory exists and the new destination does not. If both paths
exist, stop and inspect them; do not merge histories automatically. A configured `HERMES_HOME`
replaces the default root above. Directory renames preserve reports, runs, indexes, cache and usage
history. After a rename, use `data-root adopt` to write the new
`state/signaltrail-data-root.json` registry and record the prior root, then use `status` to confirm it.
The old registry remains a read-only fallback. A copy-based migration may keep the old tree staged:
copy the complete data root and verify it independently before adopting the new path. Adoption changes
the binding and records the prior root; it does not copy files or verify their integrity. Update saved
`--profile-dir` paths and scheduled commands too.

## Data directory

Pass `--data-dir DATA_DIR` before the subcommand, or set the legacy `DAILY_INTEL_DATA_DIR`.
Hermes defaults are `%LOCALAPPDATA%\hermes\signaltrail` on Windows and `~/.hermes/signaltrail`
on macOS/Linux. A configured `HERMES_HOME` uses its `signaltrail/` child. Dedicated browser profiles
default to `browser-profiles/signaltrail/` under the Hermes home.

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

The discovery catalog adds TASS, Bank of Russia, Xinhua English, China MFA remarks,
MOFCOM press conferences and UN meeting coverage. Anadolu, IRNA and WAM remain disabled
until this deployment can fetch usable items. ReliefWeb remains a documented candidate
pending its approved API appname. See the [probe record](research/2026-09-20-collection-improvements.md).
Source `origin_scope`, `coverage_regions` and `publisher_group` distinguish organization origin,
coverage and publisher grouping; they do not certify independent evidence.

Feed long content is saved separately while descriptions remain capped at 600 characters.
Only selected enrichment items load those records as partial evidence. Browser fallback uses
one persistent context with bounded concurrent pages; optional `ready_selector` replaces the
generic readiness check, and explicit `wait_ms` takes precedence. No collection step calls a model.

To fetch selected article bodies from an existing index, run `extract-content` with the exact
item IDs. This creates a new enriched index revision under the same data root; it does not edit
the input index. Use the returned path in later authoring steps. A visible browser and persistent
profile can be supplied when a publisher requires interactive verification:

```sh
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID --headed --profile-dir PROFILE_DIR
```

## Metered Hermes runs

For the audited Hermes 0.21 integration, start the host through:

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

Replace the uppercase placeholders with paths. `HERMES_PYTHON` is the Hermes virtual
environment's Python with SignalTrail installed; `PROMPT.txt` contains the report request.
Optional `--provider` and `--model` select the route.

This entry point starts metering before model work, includes workers and supported auxiliary
calls, and supports explicitly requested independent scoring in a separate task. It checks host counters
before sealing. Missing observations remain partial. Direct Hermes CLI and legacy Cron
do not automatically receive the same coverage. See [usage metering](../references/llm-usage.md)
for exact limits and Codex/OpenClaw imports.

Other agents can drive the same writing packets. Without an audited usage adapter, the run
remains usable but has explicit `unmetered` coverage and null token totals. A host without
automatic evaluator scheduling dispatches the dossier itself and calls `finalize-evaluation`
only when the user requests quality scoring.

Quality scoring is off by default. To request it for one edition, add `--evaluate` to
`finalize-edition` or `complete-edition-tail`. The run retains the request for tail recovery;
ordinary finalization and PDF delivery create no evaluator task. Existing scores remain
available. Unscored briefs stay outside the approved semantic cache, so future reports may
need more fresh writing. Structural and evidence validation still run normally.

## Reports and recovery

| Under `DATA_DIR` | Contents |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` and `.md` | Original versioned report |
| Matching `.html` and `.pdf` | Reading and printing copies |
| `reports/index.html` | Local report history |
| `runs/YYYY-MM-DD/EDITION.json` | Current stage, artifact paths, errors, next commands |
| `usage/` and `host-runs/` | Usage events and host launch receipts |

The workflow also writes a portable desktop HTML copy with available validated images embedded.
It returns HTML first, then finishes PDF, requested Notion delivery, and requested scoring in a retryable
tail. The default PDF soft size budget is 50 MiB; exceeding it records a warning.

Images retain the news site's caption in its original language. The report's `image.caption`
is an empty string when no caption is available; headlines, alt text, and generated descriptions
are never used as substitutes. Image credits remain separate from captions.

The HTML reader uses a three-column masthead with the report date, edition, and recorded
generation time. White pages, black text, and red source rules frame a continuous news list.
When an animated slide projection exists, the screen layout embeds it in the former “today's
summary” area and keeps a button to open the standalone HTML; print hides the deck and restores
the summary. Without a slide projection, the ordinary summary remains in place. The original
floating directory retains its expand/collapse and scroll tracking behavior. Search, archive/PDF
links, and the sources/status entry remain available. See the [slide guide](news-slides.md).

Read the run manifest before retrying. Use its `tail.command` for pending delivery work.
Never edit status JSON or delete a lock while its process is active. Detailed stage recovery
is in the [runbook](../references/runbook.md).

Collection keeps login, challenge, rate-limit, and failure states visible. To handle a pending
source interactively, run `verify-pending` when you are ready for a browser window.
Unattended runs must not pass `--open-verification`.

Notion is optional and requires explicit `--publish` plus credentials configured through
[Notion setup](../references/notion-setup.md). Local reports remain available when remote
delivery fails.
