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

New daily collection automatically recycles collection files older than seven days. This covers `indexes/`, `content/`, `snapshots/`, the monitor snapshot and unreferenced files under `media/images/`, using file modification time. Evidence referenced by an active run is retained. Report JSON/Markdown/HTML/PDF, illustrated slides, narration and videos have no automatic expiration; images referenced by report, narration or active-run records are also retained. Successful image recycling removes its media-cache entries; a failed recycle keeps both the image and its entries. Preview or apply the same policy manually:

```sh
signaltrail --data-dir DATA_DIR cleanup --days 7
signaltrail --data-dir DATA_DIR cleanup --days 7 --apply
```

Cleanup uses the system recycle bin. A failed recycle operation leaves the original file in place and reports the reason. The default command only lists the proposed cleanup.

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

Both [sources.yaml](../configs/sources.yaml) and [discovery-sources.yaml](../configs/discovery-sources.yaml) supply regular report sources through their existing module/category mappings. The 127 configured IDs include 124 enabled sources; disabled sources remain disabled. Every source retains all verifiable current-day stories in its original Top order within the finite public Feed/page response. Shared discovery slots and per-source 1/2/15-item quotas no longer limit reports. See [collection extensions](platform.md).

`collection.item_order: source` preserves page, ranking, or feed order. `published_at` orders valid publication times newest first, retaining input order for ties and unknown dates. A source can override this setting. Publisher rank remains in `metadata.source_rank`; ranking sources such as Hugging Face Papers retain their discovery semantics.

Source cache reuse preserves original evidence dates and publisher rank. Brief plans retain all eligible current-day entries in each source's Top order, de-duplicating only within that source. Cross-source references and positions remain visible while identical original writing is reused. There is no shared discovery quota or fixed target refill.

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

The optional local monitor shows collected news, story clusters, source health, and pending verification. Collection and clustering use no model calls. Its server defaults to read-only operation without periodic collection. The daily workflow runs on demand and delivers report HTML/PDF, slides, and optional video. See [collection extensions and event archives](platform.md).

## Host usage and optional scoring

The edition driver materializes complete inputs in a dedicated `author-inputs/` directory, preserving evidence, order, writing style and schema. Brief, analysis and slide tasks expose ordered `input_parts` filenames under `input_parts_dir`; each part contains at most 7,500 `o200k_base` tokens, and concatenating their UTF-8 bytes restores the complete input. Authors read every part in order, one part per tool result, before writing. Each task uses a new context with no preceding author history. Complete input files remain available for programmatic use and audit.

After program date/evidence checks, enrichment and input freeze, visual event review can run alongside brief authors. It still reviews every eligible candidate and saves merging/ranking decisions before finalization. Brief coverage follows the source index independently of the visual top 50.

Brief packets carry the edition date and frozen collection window. Authors assess importance from this edition's developments, impact, and timeliness, preserving original publication dates and observed listing changes for older research. Major ongoing impact can still justify a high score. For packets with a frozen end time, validation requires a precise publication time today or yesterday for `NEW`, and uses `WATCH` for unknown dates, date-only values, and research listing signals. The edition driver validates submitted drafts together and returns targeted repair errors. Standalone packets retain optional `preflight_command` and submission commands for manual recovery.

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

## Source-bound execution

Use an absolute Python with `scripts/run_signaltrail.py` from the complete checkout to ensure this checkout owns CLI execution even when host startup hooks add an installed skill. After collection, enrichment and `begin-authoring`, use `--advance-edition RUN.json --data-dir DATA_DIR`. It accepts ready drafts, prepares analysis, assembles and finalizes the report, then completes the tail and renders accepted slides. It stops at required authoring or editorial decisions. Pass the completed event review with `--slides-review REVIEW.json`.

The driver returns at most three short task tickets with part-reading metadata, `draft_result_path` and `read_max_output_tokens`. Set `--task-limit` to the free worker count and repeat `--in-flight BATCH_ID_OR_PACKET_PATH` to exclude running tasks. Full errors stay in `repair_errors_file` and exceptional issues in `issues_file`; the responsible author reads them directly. Each task gets a fresh context; in Codex use `spawn_agent` with `fork_turns="none"`. Authors use the supplied parts without printing the large complete input or inventing a splitter. Both outer `functions.exec` and nested `exec_command` output limits use `read_max_output_tokens`; each result holds just one part. Save the draft and run `check_command` within the same tool execution, printing a short result. Python normalizes deterministic WATCH before checking and accepting briefs. `--advance-dispatch INPUT.json --materialize-inputs --compact-dispatch` serves one session or plan; `--prepare-input-parts FILE` prepares an existing frozen input for recovery.

Candidate review skips navigation when extracting its bounded lead and retains `body_chars` and `evidence_chars` in the compact input. These describe available material and do not exclude short announcements. A review prepared from the index resolves canonical URL aliases when binding report text, retaining its original event IDs and merged source references.

`slides review --index INDEX.json --max-news 50 --model-input --parts-dir REVIEW_INPUT_DIR` prepares all eligible candidates with the same ordered reader. The reviewer reads all parts before merging and ranking events.

Slide authoring returns `background_commands` for image prefetch and any unfinished edition tail/PDF. Start each once alongside the authors, retain the process handles and pass `--in-flight slides-images` / `--in-flight edition-tail` while running. Wait for both before rendering, since tail and rendering update the report projection. `slides prefetch-images --plan PLAN.json` writes enriched news and metrics atomically to `images-slides-plan-rN.json` beside the immutable plan; rendering reuses it without fetching pages again. `--refresh` refreshes the receipt. Without prefetch, rendering keeps its image-collection behavior.

HTTP index prefetch reads up to `browser.http_prefetch_max_bytes` decompressed bytes (8 MiB by default). Truncated pages retain their candidates and receive one browser fallback; page diagnostics record both attempts.

Run `prefetch-media` alongside authoring to populate the shared image cache. Its independent
`media.prefetch_max_total_bytes` budget defaults to 250 MiB of new downloads; cache hits consume
none of that budget. Requests rotate across domains and try the highest available image size
before fallback. Final report images retain their separate `media.max_total_bytes` limit of
250 MiB and follow the accepted importance order. The prefetch receipt reports ready images,
downloaded bytes, reused items, failures and budget omissions. Failed URLs retain the existing
60-minute retry interval. After at least two transport failures without a successful response
from that host, prefetch temporarily defers its remaining URLs and continues other hosts.
HTTP errors still permit image-size fallback.
