# Usage

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-10-07

Use this guide after the [quick start](../README.en.md). It covers local configuration,
host setup, and where to find a finished report. [中文](zh-CN/usage.md)

## Installation

Install the checkout with `python -m pip install -e .`, then load its root `SKILL.md` in
your agent. The Python import is `signaltrail`; its module entry point is
`python -m signaltrail.cli`. Keep the checkout: configuration, schemas and templates are runtime
inputs. `DAILY_INTEL_SKILL_DIR` remains accepted when launching outside the checkout.

The checkout maintains one root `src/`. A release build places the complete installable skill
in `dist/signaltrail/`, including `SKILL.md`, source, configuration, schemas, templates, references,
and assets. Install from the checkout or extracted package root. The installer can also sync
the skill into a Hermes Skill directory for that host; this is optional. Virtual environments
and runtime data are excluded. `-Editable` (Windows) or `--editable` (macOS/Linux) binds the
Python installation to the original source directory for development.

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
the system libraries and may require administrator access. Hermes-specific installation is
described in [Hermes integration](../references/hermes-integration.md); Windows browser details
are in [windows-setup.md](../references/windows-setup.md).

## Upgrade from an earlier version

Stop active SignalTrail and Hermes jobs before upgrading. Uninstall the old Python distribution,
then install from the new checkout. Existing Hermes data does not need to be moved; keep using its
current absolute path explicitly and register it for later no-argument runs:

Replace the example data and profile paths below with your existing absolute paths, whether
their directory names are `daily-intelligence` or `signaltrail`.

```powershell
python -m pip uninstall daily-intelligence-skill
python -m pip install -e .
$env:SIGNALTRAIL_PROFILE_DIR = "$env:LOCALAPPDATA\hermes\browser-profiles\daily-intelligence"
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root adopt
signaltrail --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root status
```

On macOS/Linux, from the checkout or complete extracted package:

```sh
python -m pip uninstall daily-intelligence-skill
python -m pip install -e .
export SIGNALTRAIL_PROFILE_DIR="$HOME/.hermes/browser-profiles/daily-intelligence"
signaltrail --data-dir "$HOME/.hermes/daily-intelligence" data-root adopt
signaltrail --data-dir "$HOME/.hermes/daily-intelligence" data-root status
```

These commands keep existing data and profiles in place. `data-root adopt` records the selected
root in the SignalTrail application's own data directory; it does not move or copy files. Keep
passing the same `--data-dir` or set `SIGNALTRAIL_DATA_DIR`, and set the old profile explicitly
with `SIGNALTRAIL_PROFILE_DIR` or `--profile-dir`. Update scheduled commands too.
The environment assignments above apply to the current shell; save the profile setting in
the scheduler's environment or pass `--profile-dir` in its command. Keep existing roots in
place: moving a root across directories also requires its historical path mapping.

## Data directories

Pass `--data-dir DATA_DIR` before the subcommand, or set `SIGNALTRAIL_DATA_DIR`
(the legacy `DAILY_INTEL_DATA_DIR` remains accepted). Without an explicit root, data defaults
to `%LOCALAPPDATA%\signaltrail` on Windows and `${XDG_DATA_HOME:-~/.local/share}/signaltrail`
on macOS/Linux. Set `SIGNALTRAIL_PROFILE_DIR` or pass `--profile-dir` to choose a browser profile;
the default is `browser-profiles/signaltrail/` under the SignalTrail application data directory.
For packaged installations launched outside the checkout, set `SIGNALTRAIL_SKILL_DIR` to the
complete skill package directory when runtime resources cannot be found relative to the installed module.

```sh
signaltrail --data-dir DATA_DIR data-root status
```

An explicit `--data-dir` is used directly and is not registered automatically.
`data-root adopt` records a root for later no-argument runs; its registry lives under the
SignalTrail application data directory, never under Hermes home. Run files and referenced
artifacts must belong to the same data root.

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

## Hermes metering (optional)

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

Authoring status also shows bounded delegation metrics for its child batches. Hermes reports the
prompt token count with cache tokens included, while this callback does not expose the uncached
input and cache buckets separately. The host-reported total may also be absent, so the view marks
coverage `exact`, `partial`, or `unobservable` from reported totals. It excludes coordinator,
auxiliary, and evaluator calls; use the sealed usage task summary for the whole run.

Other agents can drive the same writing packets. Without an audited usage adapter, the run
remains usable but has explicit `unmetered` coverage and null token totals. A host without
automatic evaluator scheduling dispatches the dossier itself and calls `finalize-evaluation`
only when the user requests quality scoring.

Quality scoring is off by default. To request it for one edition, add `--evaluate` to
`finalize-edition` or `complete-edition-tail`. The run retains the request for tail recovery;
ordinary finalization and PDF delivery create no evaluator task. Existing scores remain
available. Unscored briefs stay outside the approved semantic cache, so future reports may
need more fresh writing. Structural and evidence validation still run normally.

The default evaluation backend is external. An independent Agent that did not write the report
can read the dossier and submit a score; if no independent evaluator is available, leave scoring
pending. To use Hermes instead, explicitly pass `--evaluation-backend hermes`. With `--evaluate`,
the tail creates the hash-bound dossier and `edition-status`
returns its path, a draft path, and the exact `finalize-evaluation` command. The external
evaluator reads the dossier and writes the draft, then runs that command. External mode does
not schedule Hermes or create an evaluator usage task; completion is recorded only after the
draft passes `finalize-evaluation`. External handoff has one attempt and is not automatically
redispatched on recovery.

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
