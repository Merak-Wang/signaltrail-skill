# Usage

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

Use this guide to configure an installed SignalTrail skill, choose sources and language, and find or resume an edition. Follow [SKILL.md](../SKILL.md) for the complete agent workflow. [中文](zh-CN/usage.md)

## Installation

From the complete checkout or extracted skill package:

```sh
python -m pip install -e .
signaltrail --help
```

Load the root `SKILL.md` in your agent. Keep the resource directory: configuration, templates, schemas, and assets are used at runtime. The Python distribution is `signaltrail-skill`, the command is `signaltrail`, and the module entry point is `python -m signaltrail.cli`.

The installation scripts can optionally sync a copy into a Hermes skill directory. Sync updates matching files and retains extra files; back up customized configuration before updating. `-Editable` on Windows or `--editable` on macOS/Linux uses the original checkout. See [Hermes integration](../references/hermes-integration.md) for host-specific setup.

Windows can use system Edge. Install Chromium in the same Python environment for browser collection on macOS/Linux:

```sh
python -m playwright install chromium
```

Debian/Ubuntu may also require `python -m playwright install-deps chromium`.

## Data and browser profile

Pass `--data-dir` before the subcommand, or set `SIGNALTRAIL_DATA_DIR`. Defaults are `%LOCALAPPDATA%\signaltrail` on Windows and `${XDG_DATA_HOME:-~/.local/share}/signaltrail` on macOS/Linux. Set `SIGNALTRAIL_PROFILE_DIR` or use `--profile-dir` to choose a browser profile.

```sh
signaltrail --data-dir DATA_DIR data-root status
signaltrail --data-dir DATA_DIR data-root adopt
```

`adopt` registers the existing directory for later runs without an explicit path. It keeps the files in place. Run manifests and their referenced artifacts must use the same data root. If resources cannot be found from an installation outside the checkout, set `SIGNALTRAIL_SKILL_DIR` to the complete skill directory.

<a id="upgrade-from-an-earlier-version"></a>

When upgrading an earlier installation, stop active jobs, uninstall `daily-intelligence-skill`, and install the current package. Retain the old data and profile directories and pass their absolute paths. Legacy `DAILY_INTEL_*` environment variables and saved report IDs remain supported. Update scheduled commands to `signaltrail` and preserve their data/profile settings.

## Daily run and language

```sh
signaltrail --timezone Asia/Shanghai run-edition --edition daily
signaltrail --timezone Asia/Shanghai run-edition --edition daily --language en
```

The command prepares the run; the host agent completes selection and writing through the skill. A daily edition uses the 24 hours preceding its start in the chosen timezone. Schedule one run at a consistent local time and resume `runs/DATE/daily.json` after interruptions. `--restart` explicitly creates another attempt. Existing morning/evening runs can still be resumed.

Output defaults to `zh-CN`. Ask the agent for English, pass `--language en`, or set:

```yaml
output:
  language: en
```

Titles, summaries, analysis, slides, and speech follow the selected language. Original headlines and source links remain available for reference.

## Sources and article evidence

Edit [sources.yaml](../configs/sources.yaml) for core report sources and [discovery-sources.yaml](../configs/discovery-sources.yaml) for discovery feeds. Each core source has its own `report_target` and `report_max`. Discovery sources use zero targets and can contribute to the shared supplementary pool, controlled by `collection.discovery_brief_limit` (default 30). See [collection extensions](platform.md) for configuration.

`collection.item_order: source` preserves page, ranking, or feed order. `published_at` orders valid publication times newest first, retaining input order for ties and unknown dates. A source can override this setting. Publisher rank remains in `metadata.source_rank`; ranking sources such as Hugging Face Papers retain their discovery semantics.

Core-source cache reuse requires current coverage in the frozen collection window. Collection places in-window core items before unknown-date or historical items. Brief planning uses each canonical URL once and refills duplicate positions from later unique articles in the same source, preserving source targets and publisher rank. The supplementary discovery pool deduplicates against these selected core articles.

Date-only publication values keep day precision and receive `WATCH`, as do unknown publication times. Source updates and first discovery remain separate fields. Older papers and repositories can enter the research radar through current listing, return, ranking-rise, or revision signals as `WATCH`; ordinary refreshes preserve the original signal time.

Article text is the first evidence choice, followed by saved Feed text/blocks and short descriptions. Packets expose Feed material as partial evidence with its own path and status. Enrichment suggestions weigh importance, observed gaps, available evidence, and source/domain diversity. Trafilatura now supplies a default local fallback with body-retention checks. Text PDFs retain page numbers and partial status. Fetch selected article bodies explicitly with:

```sh
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID
signaltrail --data-dir DATA_DIR extract-content --index INDEX.json --item-id ITEM_ID --headed --profile-dir PROFILE_DIR
```

Extraction creates an enriched index revision. Use the returned path in later steps. Collection keeps login, challenge, rate-limit, and failure states visible. Use `verify-pending` for interactive browser verification. The [editorial policy](../references/editorial-policy.md) covers source selection and evidence handling.

## Collection monitor

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

The optional local monitor shows collected news, story clusters, source health, and pending verification. Collection and clustering use no model calls. Its server defaults to read-only operation without periodic collection. The daily workflow runs on demand and delivers report HTML/PDF, slides, and optional video. See [collection extensions and research APIs](platform.md).

## Host usage and optional scoring

Brief authors read `signaltrail --data-dir DATA_DIR brief-input --packet PACKET.json` once. Its single-line input retains complete candidate evidence, order, writing style, schema, and draft/preflight commands. Matching candidate IDs replace the repeated authorization list; distinct legacy authorizations remain explicit. Evidence paths are read as needed.

Brief packets carry the edition date and frozen collection window. Authors assess importance from this edition's developments, impact, and timeliness, preserving original publication dates and observed listing changes for older research. Major ongoing impact can still justify a high score. For packets with a frozen end time, validation requires a precise publication time today or yesterday for `NEW`, and uses `WATCH` for unknown dates, date-only values, and research listing signals. Coordinated workers run `preflight_command` and return drafts for coordinator submission with `submit-authoring-batch --all`. Standalone workers follow the coordinator's submission instruction. Older packets support preflight by appending `--check-only` to `submission_command`.

Any capable host agent can drive the writing packets. Runs without an audited usage adapter record `unmetered` coverage and `null` usage totals. For audited Hermes metering, launch through:

```sh
signaltrail-hermes run --ledger DATA_DIR --hermes-python HERMES_PYTHON --prompt-file PROMPT.txt --timeout 3600
```

The launcher begins metering before model work and reconciles supported calls with host counters. `--provider` and `--model` choose the route. Read [usage metering](../references/llm-usage.md) for coverage and other host imports, and [Hermes integration](../references/hermes-integration.md) for setup.

Independent quality scoring is optional. Add `--evaluate` to `finalize-edition` or `complete-edition-tail` to request it. The default external backend returns a dossier and submission command for an independent agent. Use `--evaluation-backend hermes` to select Hermes scheduling. The run retains this request during recovery. An unscored brief remains outside the approved semantic cache.

Default analysis uses one fresh-context packet. `prepare-analysis --parallel` offers a staged path: selection, three domain packets, synthesis, then assembly. It can reduce authoring wait while repeating more shared input. Follow the returned commands and [runbook](../references/runbook.md). Use global `--compact` before a subcommand to shorten stdout while keeping saved artifacts complete.

## Outputs and recovery

| Under `DATA_DIR` | Contents |
| --- | --- |
| `reports/YYYY-MM-DD/EDITION-rN.json` and `.md` | Versioned report records |
| Matching `.html` and `.pdf` | Reading and print copies |
| `reports/index.html` | Report history |
| `runs/YYYY-MM-DD/EDITION.json` | Stage, artifacts, errors, and next commands |
| `usage/` and `host-runs/` | Usage records and host launch receipts |

The workflow returns HTML first and creates a portable desktop copy with available images embedded. A retryable tail handles PDF, requested Notion delivery, and requested scoring. The default PDF size budget is 50 MiB; an oversized file records a warning.

Report HTML embeds the rendered slides, with a separate open link; video export adds playback in the same area. Printing restores the report summary. Each daily edition requires rendered slides. Use `edition-status --run RUN.json --require-complete` to check the complete delivery. See [slides and video](news-slides.md).

Before retrying, read the run manifest and use its exact `tail.command` for pending delivery. The [runbook](../references/runbook.md) gives stage-specific recovery steps. Notion publishing requires explicit `--publish` and [configured credentials](../references/notion-setup.md).
