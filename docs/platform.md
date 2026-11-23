# Collection extensions and archive APIs

When live collection and the current monitor snapshot contain the same source and canonical article, live ranking and access status remain authoritative. Missing descriptions and matching, substantive Feed content can be reused from the snapshot; stale or navigation-only evidence is excluded.

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-11

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

The [extension catalog](../configs/discovery-sources.yaml) covers international and domestic news, markets, defense, technology news, and papers. Enabled entries join the regular report sections; inspect actual source health for availability. Legacy zero target fields do not limit admission: the new edition policy records each source's actual current-day count.

## Collection window and source ordering

Daily sources collect all articles in their finite configured pages; reaching the old 15-item target does not skip those pages. Sources with an explicit item limit use original-publication date and the frozen cutoff to decide whether cached coverage is sufficient. Yesterday's articles, unknown original dates, and platform ranking times do not count toward that threshold. Stale Feed responses and retained history remain excluded.

During an on-demand edition, a recent snapshot is also checked for newly enabled sources, changed Feed entries, and each source's own `checked_at`. Only missing, changed, or expired sources are collected again. Updating one source preserves the observation times of other enabled sources. A refresh removes items and health rows for removed or disabled sources from the current snapshot while preserving historical archives. Stale Feed items remain readable but allow alternate-Feed discovery and static HTML fallback; current Feed or HTML material replaces a stale copy of the same URL.

After collection, non-discovery sources place explicitly in-window items before unknown-date/history items, preserving order within each group and retaining publisher rank in `metadata.source_rank`. Sources whose role is `discovery`, such as paper and repository rankings, retain their ranking semantics. Core source targets stay unchanged.

Brief planning selects up to 15 eligible current-day articles per source by original publication time, newest first. Same-source canonical duplicates merge; cross-source entries retain their own IDs, references and ranks while sharing identical original writing. Original rank is preserved after filtering. Semantic multi-publisher event merging and impact ranking belong to the separate visual stream.

Collection keeps the complete observed article index and actual access statuses. Before daily admission, article links without an original publication date receive a bounded HTTP metadata request, deduplicated by canonical URL and reusing previously obtained dates. Publisher metadata, article JSON-LD, and source-specific listing fields supply publication dates; update times, ranking times and capture times remain separate. Navigation links are excluded by each publisher's article patterns. A source with accessible older or undated articles remains successful even when its current-day writing count is zero.

When a Xinhua English listing supplies only the edition date, collection reads the original article header before applying the cutoff and sorting. The precise publication timestamp is also used in the report.

For articles that pass the current edition's selection, a complete HTML response from the date probe can also supply the article body. The normal extractor saves reusable full text, structured blocks and image references in the content store. When the article is selected for enrichment, that evidence replaces a second HTTP request. Truncated responses, incomplete text and unresolved tables continue through normal enrichment. Browser responses remain in memory and are never saved as raw HTML.

For publishers that provide a public Google News sitemap, a configured `feed_urls` entry can collect article headlines, links and original `news:publication_date` values. Forbes uses this route. A sitemap's `lastmod` describes a revision. A zero in the report's source table counts admitted briefs from that configured section up to the cutoff. To establish whether the publisher had a release that day, check its dated archive or an article with an original timestamp.

Reuters collection can also use AOL's public news listing. Only cards labelled Reuters supply reprints, and the linked article's publication metadata governs the daily cutoff. The index retains the AOL article address and the Reuters credit, together with the separately observed Reuters homepage status.

SEC EDGAR records the Atom filing date and update time separately. The filing detail page's `Accepted` field supplies the New York time used for the daily cutoff.

ABC live updates with an `entryId` use the matching update's published time. When that update is missing from the returned page, its publication time remains unknown.

Discovery links can use the publisher's explicit `og:published_time`, as on Mastodon posts. Lobsters archive links are excluded from article selection.

Weibo uses its official listing endpoint with a configurable public 60s API fallback. Each returned topic records `listing_endpoint`. Hugging Face Papers reads the edition's dated paper list as well as the trending list. Paper metadata and the first arXiv submission in the version history can supply original timestamps. `submittedOnDailyAt` and platform activity describe listing or observation. In a retrospective check, a dated public comment can establish that the paper page was already visible at that time. A relative age such as “hours ago” requires an original-page date before daily admission. Year-only and month-only research catalog dates retain their uncertainty.

Google News item dates remain separate from confirmed publisher dates. When an accessible static wrapper has no date, an anonymous browser follows its normal public redirect and reads the publisher's publication metadata. The publisher's complete HTML can supply reusable full text under the same rules. Publisher access failures remain visible, and the resolved original URL remains available for subsequent body retrieval. Aggregate topic pages are excluded from article candidates.

Publication, revision, and observation have separate meanings. Dates are normalized from ISO, RFC, and explicit `YYYY/MM/DD` forms. A date without a time retains day precision in `metadata.published_precision`; `updated_at` records a source revision, while `first_discovered_at` records the earliest retained observation. Date-only candidates use calendar-day overlap with the frozen window and receive `published_date_overlap` and `WATCH`; unknown publication times also remain `WATCH`.

Research rankings retain their original order and publication dates. Observation compares consecutive snapshots and records `new_listing`, `reappeared`, `rank_rise`, or `updated`, with a stable `signal_at`. A first observation without a baseline is `bootstrap_watch`; an ordinary refresh preserves the previous signal time. Older papers and projects can enter the research radar on an in-window signal as `WATCH`. A ranking rise describes renewed attention to existing research.

Saved Feed fields also remain available to brief and analysis authors through `feed_content_path`, character count, and an independent partial-evidence marker. Reading their JSON text/blocks adds no network work and does not promote Feed material to verified article full text.

## Use discovery sources in future daily editions

Enabled sources in both bundles enter the existing report sections. The default catalog has 45 source IDs across both bundles, with 43 enabled. Each source contributes up to 15 verifiable original articles published on the edition's Asia/Shanghai day before the frozen cutoff, newest first after same-source canonical de-duplication. Finite Feed/page responses are read completely within the configured byte/page boundaries. Unknown/older originals and ranking/submission times do not qualify. Same-source canonical duplicates merge; cross-source positions remain visible and identical writing can be reused. The old shared 30-slot pool and per-source 1/2 limits do not apply. Slides/video separately merge semantic events and order up to 50 by impact.

IRNA English (`irna_en`) and Emirates News Agency (`wam_en`) are disabled in the default configuration.

## Body enrichment

`enrichment_plan` ranks observable body gaps using importance, structural gaps, available Feed material, the bounded fetch cost, and diminishing priority for already selected sources and domains. Each canonical URL receives at most one action. The coordinator selects the final IDs under the existing per-run limit; authors continue reading bounded packets.

HTTP and browser extraction share concrete body-region selection and structured tables. Explicit table headers and spans are preserved; numerical tables without declared headers retain their gap. Text PDFs use the normal bounded HTTP response and `pypdf`, with at most 80 pages and page numbers. Their evidence status is `partial`; scanned, encrypted, or unreadable files retain metadata/Feed evidence.

Trafilatura is a base dependency and the default local fallback when the built-in extractor leaves gaps. Complete bodies skip the fallback. Specific body regions and tables are preserved; a replacement for an existing partial body must retain at least 70% of its substantial text blocks, weighted by characters. Candidates can add text, while excessive compression of a live report keeps the original body. `fallback_extractor: none` disables this comparison.



## RSSHub sources

RSSHub runs as an external service. Copy the [platform source template](../configs/platform-sources.example.yaml) and set `rsshub.base_url` to your instance. For each source you add to `sources`, supply its `id`, `name`, `url`, and `rsshub_route`. SignalTrail tries any native feeds in `feed_urls` first.

Run `signaltrail --config CONFIG_FILE --data-dir DATA_DIR refresh-monitor` with the configured copy. Route availability depends on the upstream site and your RSSHub instance. RSSHub is licensed under [AGPL-3.0](https://github.com/DIYgod/RSSHub/blob/master/LICENSE).

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
