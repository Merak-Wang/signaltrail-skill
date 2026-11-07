# Collection extensions and archive APIs

When live collection and the current monitor snapshot contain the same source and canonical article, live ranking and access status remain authoritative. Missing descriptions and matching, substantive Feed content can be reused from the snapshot; stale or navigation-only evidence is excluded.

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

This guide covers the local collection monitor, supplementary discovery sources, RSSHub, Crawl4AI, and report and event APIs for integrations. [中文](zh-CN/platform.md)

## Collection monitor and report delivery

Daily editions run on demand through [SKILL.md](../SKILL.md). The commands below are optional inspection tools. The server defaults to read-only operation with periodic collection disabled, including when no snapshot exists; report generation does not start it.

```sh
signaltrail --data-dir DATA_DIR refresh-monitor
signaltrail --data-dir DATA_DIR serve --open
```

Use the same absolute data root as the report workflow. The default URL is `http://127.0.0.1:8765`. The monitor displays collected news, lexical story clusters, source health, and pending verification. Refreshing and clustering make no model calls. The complete daily-edition workflow in [SKILL.md](../SKILL.md) produces the formal report and its projections.

Original titles and the selected output-language translations, summaries, and analysis follow the saved report contract. Versioned JSON/Markdown remain authoritative. Published report HTML, PDF, slides, and video continue through their existing workflow and delivery paths.

The report catalog APIs `/api/editions` and `/api/edition`, persistent events and follows are available for client integrations. Report language selection returns actual generated versions; a missing language version returns `unavailable` with the requested selection and available editions.

Persistent events, articles and follows are stored in `DATA_DIR/platform/events.sqlite`. Archive synchronization reuses complete monitor groups, including their configured clustering threshold and story identities, and clusters only articles whose groups are missing or contain filtered navigation links. The retained event API can project report evidence, titles, summaries, and analysis when the report and event are linked.


## Discovery source configuration

The [extension catalog](../configs/discovery-sources.yaml) covers international, domestic, markets, technology and open-source news. Enabled entries join the regular report sections; inspect actual source health for availability. Legacy zero target fields do not limit admission: the new edition policy records each source's actual current-day count.

## Collection window and source ordering

Core-source cache eligibility uses the edition's frozen `collection_window`. Stale Feed responses, retained history, and explicitly out-of-window publication dates do not count as current coverage that can skip a source refresh; missing publication dates remain unknown.

During an on-demand edition, a recent snapshot is also checked for newly enabled sources, changed Feed entries, and each source's own `checked_at`. Only missing, changed, or expired sources are collected again. Updating one source leaves other sources' observation times intact. Stale Feed items remain readable but allow alternate-Feed discovery and static HTML fallback; current Feed or HTML material replaces a stale copy of the same URL.

After collection, non-discovery sources place explicitly in-window items before unknown-date/history items, preserving order within each group and retaining publisher rank in `metadata.source_rank`. Sources whose role is `discovery`, such as paper and repository rankings, retain their ranking semantics. Core source targets stay unchanged.

Brief planning retains every eligible current-day article in each source's original Top order. Same-source canonical duplicates merge; cross-source entries retain their own IDs, references and ranks while sharing identical original writing. Original rank is preserved after filtering. Semantic multi-publisher event merging and impact ranking belong to the separate visual stream.

Publication, revision, and observation have separate meanings. Dates are normalized from ISO, RFC, and explicit `YYYY/MM/DD` forms. A date without a time retains day precision in `metadata.published_precision`; `updated_at` records a source revision, while `first_discovered_at` records the earliest retained observation. Date-only candidates use calendar-day overlap with the frozen window and receive `published_date_overlap` and `WATCH`; unknown publication times also remain `WATCH`.

Research rankings retain their original order and publication dates. Observation compares consecutive snapshots and records `new_listing`, `reappeared`, `rank_rise`, or `updated`, with a stable `signal_at`. A first observation without a baseline is `bootstrap_watch`; an ordinary refresh preserves the previous signal time. Older papers and projects can enter the research radar on an in-window signal as `WATCH`. A ranking rise describes renewed attention to existing research.

Saved Feed fields also remain available to brief and analysis authors through `feed_content_path`, character count, and an independent partial-evidence marker. Reading their JSON text/blocks adds no network work and does not promote Feed material to verified article full text.

## Use discovery sources in future daily editions

Enabled sources in both bundles enter the existing report sections. The current configuration has 32 core and 95 extension entries, with 92 extensions enabled: 127 unique IDs and 124 enabled sources. Each source contributes every verifiable original article published on the edition's Asia/Shanghai day before the frozen cutoff, in its original source Top order. Finite Feed/page responses are read completely within the configured byte/page boundaries. Unknown/older originals and ranking/submission times do not qualify. Same-source canonical duplicates merge; cross-source positions remain visible and identical writing can be reused. The old shared 30-slot pool and per-source 1/2/15 limits do not apply. Slides/video separately merge semantic events and order up to 50 by impact.

Anadolu Agency (`anadolu_en`), IRNA English (`irna_en`) and Emirates News Agency (`wam_en`) remain disabled. Their bundle comment says to keep unavailable candidates disabled until this deployment can extract items; individual historical failure details are unknown.

## Body enrichment

`enrichment_plan` ranks observable body gaps using importance, structural gaps, available Feed material, the bounded fetch cost, and diminishing priority for already selected sources and domains. Each canonical URL receives at most one action. The coordinator selects the final IDs under the existing per-run limit; authors continue reading bounded packets.

HTTP and browser extraction share concrete body-region selection and structured tables. Explicit table headers and spans are preserved; numerical tables without declared headers retain their gap. Text PDFs use the normal bounded HTTP response and `pypdf`, with at most 80 pages and page numbers. Their evidence status is `partial`; scanned, encrypted, or unreadable files retain metadata/Feed evidence.

Trafilatura is a base dependency and the default local fallback when the built-in extractor leaves gaps. Complete bodies skip the fallback. Specific body regions and tables are preserved; a replacement for an existing partial body must retain at least 70% of its substantial text blocks, weighted by characters. Candidates can add text, while excessive compression of a live report keeps the original body. `fallback_extractor: none` disables this comparison.



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
