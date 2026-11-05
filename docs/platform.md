# Collection extensions and research APIs

When live collection and the current monitor snapshot contain the same source and canonical article, live ranking and access status remain authoritative. Missing descriptions and matching, substantive Feed content can be reused from the snapshot; stale or navigation-only evidence is excluded.

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

This guide covers the local collection monitor, supplementary discovery sources, RSSHub, Crawl4AI, and report, event, and research APIs for integrations. [中文](zh-CN/platform.md)

## Collection monitor and report delivery

Daily editions run on demand through [SKILL.md](../SKILL.md). The commands below are optional inspection tools. The server defaults to read-only operation with periodic collection disabled, including when no snapshot exists; report generation does not start it.

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

Use the same absolute data root as the report workflow. The default URL is `http://127.0.0.1:8765`. The monitor displays collected news, lexical story clusters, source health, and pending verification. Refreshing and clustering make no model calls. The complete daily-edition workflow in [SKILL.md](../SKILL.md) produces the formal report and its projections.

Original titles and the selected output-language translations, summaries, and analysis follow the saved report contract. Versioned JSON/Markdown remain authoritative. Published report HTML, PDF, slides, and video continue through their existing workflow and delivery paths.

The report catalog APIs `/api/editions` and `/api/edition`, persistent events, follows, and research backend are available for client integrations. Report language selection returns actual generated versions; a missing language version returns `unavailable` with the requested selection and available editions.

Persistent events, articles, follows, and research records are stored in `DATA_DIR/platform/events.sqlite`. Archive synchronization reuses complete monitor groups, including their configured clustering threshold and story identities, and clusters only articles whose groups are missing or contain filtered navigation links. The retained event API can project report evidence, titles, summaries, and analysis when the report and event are linked.

## Research an event

The retained research API accepts an archived event, a question, an optional perspective, and a language. Task records expose queued/running/completed/failed states and the saved answer with its sources. Access research through the API or commands below. The research service freezes the event evidence for the local host; it runs one worker and reuses a matching active task. Research calls the host model; reading, feed collection, and event ranking do not call a model.

By default the service reuses an installed Hermes command and its model configuration. Set `SIGNALTRAIL_RESEARCH_PROVIDER` and/or `SIGNALTRAIL_RESEARCH_MODEL` before starting `serve` to override the provider/model for the automatic Hermes research subprocess. Empty values inherit the existing Hermes configuration; the global Hermes configuration is unchanged. These overrides do not apply to `SIGNALTRAIL_RESEARCH_COMMAND`, whose argument array is supplied entirely by the user. Jobs record the selected backend and any explicit provider/model under `worker`. A custom local host can be selected using `SIGNALTRAIL_RESEARCH_COMMAND`, a JSON argv array containing `{packet}` and `{output}` placeholders. The command reads the UTF-8 JSON packet and writes the declared result JSON to the output path. Configure the command before starting `serve`.

```text
SIGNALTRAIL_RESEARCH_COMMAND=["your-agent-command","--packet","{packet}","--output","{output}"]
SIGNALTRAIL_RESEARCH_TIMEOUT_SECONDS=180
SIGNALTRAIL_RESEARCH_COOLDOWN_HOURS=6
```

An unavailable host leaves the task at `awaiting_model`, with its packet preserved for an external host. An explicit empty command array `[]` selects this external-host path. Task records keep execution errors and never present a failed or waiting task as a completed answer. Research results remain attached to their event.

For an external skill host, list waiting jobs, read the returned frozen packet, write its declared result JSON, and submit it:

```sh
signaltrail --data-dir DATA_DIR platform-research list --status awaiting_model
signaltrail --data-dir DATA_DIR platform-research submit --job JOB_ID --input RESULT.json
signaltrail --data-dir DATA_DIR platform-research run --job JOB_ID
```

A running server also schedules research for followed events when substantive new evidence arrives, with a six-hour default cooldown. Identical evidence and repeated syndication do not trigger another analysis.

## Discovery source configuration

The [discovery catalog](../configs/discovery-sources.yaml) covers international, domestic, markets, technology, and open-source news. Edit Feed addresses and `enabled` settings to change coverage; check actual availability in the monitor's source health. Discovery sources use `report_target: 0` and `report_max: 0`; sources selected for the shared pool receive the actual selected brief count in that edition.

## Collection window and source ordering

Core-source cache eligibility uses the edition's frozen `collection_window`. Stale Feed responses, retained history, and explicitly out-of-window publication dates do not count as current coverage that can skip a source refresh; missing publication dates remain unknown.

During an on-demand edition, a recent snapshot is also checked for newly enabled sources, changed Feed entries, and each source's own `checked_at`. Only missing, changed, or expired sources are collected again. Updating one source leaves other sources' observation times intact. Stale Feed items remain readable but allow alternate-Feed discovery and static HTML fallback; current Feed or HTML material replaces a stale copy of the same URL.

After collection, non-discovery sources place explicitly in-window items before unknown-date/history items, preserving order within each group and retaining publisher rank in `metadata.source_rank`. Sources whose role is `discovery`, such as paper and repository rankings, retain their ranking semantics. Core source targets stay unchanged.

Brief planning allocates each canonical article URL once across sources. It scans the existing source order and fills a duplicate position with the next unique article from that source, preserving source targets, section allocation, and original publisher rank. The compact writing input includes these later candidates. `brief_plan.shortfall_count` records an actual shortage of unique articles. Different URLs remain separate evidence even when their titles or events are similar. The shared discovery pool deduplicates against the selected core articles; an unused tail candidate does not exclude a discovery article.

Publication, revision, and observation have separate meanings. Dates are normalized from ISO, RFC, and explicit `YYYY/MM/DD` forms. A date without a time retains day precision in `metadata.published_precision`; `updated_at` records a source revision, while `first_discovered_at` records the earliest retained observation. Date-only candidates use calendar-day overlap with the frozen window and receive `published_date_overlap` and `WATCH`; unknown publication times also remain `WATCH`.

Research rankings retain their original order and publication dates. Observation compares consecutive snapshots and records `new_listing`, `reappeared`, `rank_rise`, or `updated`, with a stable `signal_at`. A first observation without a baseline is `bootstrap_watch`; an ordinary refresh preserves the previous signal time. Older papers and projects can enter the research radar on an in-window signal as `WATCH`. A ranking rise describes renewed attention to existing research.

Saved Feed fields also remain available to brief and analysis authors through `feed_content_path`, character count, and an independent partial-evidence marker. Reading their JSON text/blocks adds no network work and does not promote Feed material to verified article full text.

## Use discovery sources in future daily editions

`collection.discovery_brief_limit: 30` enables a shared supplementary brief pool for a new full collection/daily edition; set it to `0` to disable it (range `0..120`). The default 30 slots are allocated across international (15), markets (6), and technology (9), with at most two briefs per source. Unfilled slots are reassigned in international/markets/technology order.

Selection reuses a fresh monitor snapshot within the edition's frozen 24-hour window. News selection uses publication time or an overlapping publication date; research papers and projects may also qualify through a current ranking signal. Stale/retained records and explicitly future publications are excluded. Deduplication uses canonical URLs. Explicit source-targeted collection does not append this pool. Only selected discovery sources receive their actual one/two-brief policy in the new index, then enter the ordinary brief and three-perspective analysis workflow. Existing report versions remain unchanged.

## Body enrichment

`enrichment_plan` ranks observable body gaps using importance, structural gaps, available Feed material, the bounded fetch cost, and diminishing priority for already selected sources and domains. Each canonical URL receives at most one action. The coordinator selects the final IDs under the existing per-run limit; authors continue reading bounded packets.

HTTP and browser extraction share concrete body-region selection and structured tables. Explicit table headers and spans are preserved; numerical tables without declared headers retain their gap. Text PDFs use the normal bounded HTTP response and `pypdf`, with at most 80 pages and page numbers. Their evidence status is `partial`; scanned, encrypted, or unreadable files retain metadata/Feed evidence.

Trafilatura is a base dependency and the default local fallback when the built-in extractor leaves gaps. Complete bodies skip the fallback. Specific body regions and tables are preserved; a replacement for an existing partial body must retain at least 70% of its substantial text blocks, weighted by characters. Candidates can add text, while excessive compression of a live report keeps the original body. `fallback_extractor: none` disables this comparison.

For archived event research, a substantive change to a Feed, title, or description marks the associated body for refresh. Until refreshed, the current Feed or description supplies the packet. A successful new partial body replaces a stale full body; discovery-time changes alone leave the body reusable. Each research task freezes its own evidence packet.

```yaml
collection:
  discovery_brief_limit: 30
```

## RSSHub sources

RSSHub runs as an external service. Configure your own reachable instance and a source route; native feeds in `feed_urls` are tried first. The [platform source example](../configs/platform-sources.example.yaml) provides a complete discovery-only configuration.

The default catalog uses native Feeds and has no active RSSHub route. The adapter becomes part of collection after an instance and routes are configured; ordinary report generation does not start an RSSHub service.

```yaml
rsshub:
  base_url: http://127.0.0.1:1200
sources:
  - id: rsshub_updates
    name: RSSHub Updates
    url: https://t.me/s/awesomeRSSHub
    feed_urls: []
    rsshub_route: /telegram/channel/awesomeRSSHub
    module: technology
    category: open_source
    role: discovery
    report_target: 0
    report_max: 0
```

Use `signaltrail --config configs/platform-sources.example.yaml --data-dir DATA_DIR refresh-monitor` to collect the example. Replace the address and route with your deployed instance. RSSHub route availability depends on the upstream site and that instance. The example route is a configuration example, not an acceptance-tested deployment. RSSHub is licensed under [AGPL-3.0](https://github.com/DIYgod/RSSHub/blob/master/LICENSE).

## Optional Crawl4AI extraction

Install the optional Python extra and browser runtime in the SignalTrail environment:

```sh
python -m pip install -e ".[crawl4ai]"
crawl4ai-setup
```

```yaml
collection:
  browser_extractor: crawl4ai
```

The default `browser_extractor: auto` keeps HTTP first. When a selected body needs rendering, non-interactive runs use an installed Crawl4AI SDK; otherwise they use Playwright. Visible-window requests use Playwright. Explicit `playwright` and `crawl4ai` settings select their respective backend. Each article receives one browser attempt; startup failure retains available HTTP evidence and its error. Crawl4AI preserves article text, available image candidates, and video candidates for downstream reading. Feed collection continues through the Feed pipeline.

Crawl4AI's [license](https://github.com/unclecode/crawl4ai/blob/main/LICENSE) contains the Apache-2.0 text and an additional attribution requirement:

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).
