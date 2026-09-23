# Source expansion and collection improvements

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-20

This record covers the collection-only implementation of the supplied September 20 research
proposal. [中文](../zh-CN/research/2026-09-20-collection-improvements.md)

## Result

The formal report still has 32 sources with 15 briefs each. Discovery now has 60 configured
sources: 57 enabled and three pending. Six new enabled sources contribute regional reporting,
policy statements and institutional records without creating new brief or model-call quotas.
Origin, coverage and publisher group are separate optional fields. They do not establish
independent corroboration or verify the claims of a quoted speaker.

## Deployment probes

Public requests were made from the development Windows machine on September 20, 2026.
The final integrated monitor run produced the following current candidates. These counts
are observations from one run, not an availability guarantee or editorial quality score.

| Source | Entry used | Result / candidates |
| --- | --- | --- |
| TASS English | [RSS](https://tass.com/rss/v2.xml) | HTTP 200, RSS, 40 |
| Bank of Russia | [Press](https://www.cbr.ru/rss/EngRssPress), [site updates](https://www.cbr.ru/rss/EngRssNews) | HTTP 200, RSS, 53 combined |
| Xinhua English | [Homepage](https://english.news.cn/) | HTTP 200, static HTML, 43 |
| China MFA | [Spokesperson remarks](https://www.fmprc.gov.cn/eng/xw/fyrbt/) | HTTP 200, static HTML, 14 |
| MOFCOM | [News publication directory](https://www.mofcom.gov.cn/xwfb/) | HTTP 200, static HTML, 6 press conferences |
| UN meeting coverage | [Press homepage](https://press.un.org/en) | HTTP 200, static HTML, 20 |

The Bank of Russia [official catalog](https://www.cbr.ru/eng/about/rss/) advertises HTTP
addresses; their HTTPS variants were tested directly before configuration. The latest observed
publication dates in the initial probes were September 20 for TASS, September 18 for CBR site
updates and September 17 for CBR press releases. MOFCOM uses a continuing directory with several
conference dates, rather than the proposal's single September 10 transcript.

Anadolu's [homepage](https://www.aa.com.tr/en) and official
[RSS endpoint](https://www.aa.com.tr/en/rss/default?cat=live) disconnected before an HTTP response
on this machine. [IRNA](https://en.irna.ir/) and [WAM](https://www.wam.ae/en) returned HTTP 200
but no usable static article links in these probes. They remain disabled. The web retrieval
service could read Anadolu and IRNA; that result is not substituted for deployment acceptance.
[ReliefWeb](https://apidoc.reliefweb.int/) requires an approved appname and remains a documented
candidate, with no credential-free API configuration presented as connected.

The integrated six-source run produced **176 candidates and 53 Feed content records** in an
isolated temporary data root. Cold collection took **4.038 seconds**; the subsequent refresh took
**2.171 seconds** with the same 53 content files. Both monitor snapshots report zero model tokens.
HTML sources were still requested on the second run; this is not an all-cache benchmark.
No production report was generated and no daily-report p50/p95 or writing-quality claim is made.

## Implementation

- `feed_content` preserves the source's long field as structured blocks, links, images and
  publisher captions. RSS HTML, Atom text/HTML/XHTML, inherited language and nested `xml:base`
  have separate parsing paths. Content-addressed JSON files preserve changes at the same URL
  without rewriting previous records. The list description stays capped at 600 characters.
- Only selected enrichment items load a Feed record into partial local evidence. Failed web
  completion keeps that evidence and its limitations. Feed length never confers `full_text`.
  Unselected items retain their original candidate bounds and `not_fetched` status.
- Feed collection advances independently per source, including alternative discovery. Known
  feeds do not wait for unrelated homepage discovery. Domain permission precedes global
  permission in both feed and HTML collection, preventing same-domain waiters from filling
  the global pool.
- Discovery classifies 429/403 before generic errors. Retry-After is retained in the existing
  registry and prevents another discovery/HTML request during cooldown. Cached evidence from
  a failed feed refresh remains stale/partial during backoff.
- HTTP prefetch uses the same bounded streaming reader as article extraction. Truncated
  index responses are explicit partial/failed results. Index and article image selection
  include `picture/source` and lazy `data-srcset` candidates.
- Browser fallback uses asynchronous pages in one persistent context, with global and domain
  limits and original output order. DOM readiness replaces the generic fixed delay; explicit
  site waits remain supported. Browser and synchronous verification paths share extraction
  scripts and item conversion functions for the six built-in adapters.

Regression tests cover retained tail conditions, real nested XHTML images and captions, plain
text versus HTML, declared encoding, missing body, same-URL updates, identical-content reuse,
bounded authoring projections, discovery scheduling, cross-domain starvation, streamed truncation,
429 cooldown, access failures, browser lifecycle, readiness and source order. Final validation passed: **553 tests**, Ruff, compileall, Chinese code-comment checks,
documentation checks and `git diff --check`, using the repository virtual environment.

A real headless Edge smoke run against local HTTP fixtures also exercised all six built-in
adapters: browser index, arXiv, TWZ, latest-year index, Weibo JSON and Seed API. Each returned
one expected item successfully; the browser index also selected the large responsive image.
The profile and public probe outputs were kept outside the repository.

This change does not implement research evidence authorization, parallel long-form writing,
story binding or current-news admission. Those belong to the proposal's later research work.
