# Report A: collection sources and implementation

**Purpose:** Connect Report A section 3 to verified upstream sources and the implemented collection behavior.
**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-09-11

[中文](../zh-CN/research/2026-09-11-collection-evidence.md)

## Sources checked

The supplied report and its `appendix/research_sources.json` identify the following sources.
The official pages were opened on 2026-09-11. These are capability references, not a comparative
accuracy benchmark or authorization to bypass a publisher's access restrictions.

| Report reference | Primary source | Engineering disposition |
| --- | --- | --- |
| 13 | [RSSHub](https://github.com/DIYgod/RSSHub) | Existing configured RSS/Atom ingestion can consume an approved RSSHub route. No new public instance or untested route was added. |
| 14 | [Mozilla Readability](https://github.com/mozilla/readability) | Article HTML, text and metadata are separate outputs; extracted HTML needs separate sanitization before display. SignalTrail continues to render its own text projection. |
| 15 | [Trafilatura](https://trafilatura.readthedocs.io/en/latest/) and [extraction API](https://trafilatura.readthedocs.io/en/latest/corefunctions.html) | Added an optional local candidate extractor, with comments excluded and table/link/formatting retention requested. The actual installed integration was checked with version 2.2.0. |
| 16 | [Crawl4AI](https://docs.crawl4ai.com/) | Browser extraction reference. The existing Playwright path supplies one bounded escalation; no second browser framework was added. |
| 17 | [Firecrawl Scrape](https://docs.firecrawl.dev/features/scrape) | API success and target-page status are separate. This is a future provider option, not an installed dependency or a successful live-site benchmark. |
| 18 | [Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) | Extraction provider reference; no credentials or external API calls were introduced. |
| 19 | [Parallel Search](https://docs.parallel.ai/search/search-quickstart) | Search excerpts remain discovery material. An excerpt must not be relabeled as complete article evidence. |
| 20 | [GDELT](https://www.gdeltproject.org/) | Global media discovery reference. Configured-source coverage does not measure global event frequency or completeness. |

Section 3 also cites the repository's historical [SKILL.md at the reviewed commit](https://github.com/Merak-Wang/signaltrail-skill/blob/c324c5e8529ae22268b2bd53a7b8394f3f8af26f/SKILL.md)
as reference 2. The current runtime remains authoritative. Reference 12 is the user's private
16-page “我的 AI 实践：橘鸦 AI 早报” attachment; the supplied research bundle contains its
bibliographic description but not that PDF. This change did not reread it or claim access to
the author's unpublished implementation.

## Implemented behavior

`collection_diagnostics` adds configured region × topic × source-role cells to the context.
It reads canonical root items, excludes retained monitor history, and preserves failed,
rate-limited and not-collected sources. New indexes retain their configured dimensions in
`source_policies`; older indexes label use of current configuration. The roles are existing
source roles, not an inferred stakeholder taxonomy. Source counts do not establish independent
corroboration, and unconfigured regions are outside the diagnostic's scope.
Monitor snapshots also carry coverage for the current refresh, including discovery sources
when selected; historical records from other refreshes do not increase this count.

Context also includes an `enrichment_plan` with at most the configured full-text limit of body-gap
suggestions. It rotates among sources while retaining each source's candidate order, records
missing fields, requested source role and per-action attempt bounds, and leaves event identity
and claim sufficiency unassigned. The coordinator still selects explicit IDs by editorial
importance. Exhausted or blocked actions are not automatically recommended again. This does
not implement arbitrary search, claim-driven research, or a calibrated utility/cost score.

The built-in extractor retains specific short articles. Its quality record now includes lexical
title overlap, numeric tables without explicit headers, truncation and unknown semantic/media
checks. Headerless numeric tables retain their cells and are at most partial; title overlap is
a diagnostic, not a semantic gate. Optional Trafilatura runs only after the baseline falls short,
against already pruned HTML. It cannot erase a specific region's missing conditions by removing
them. Accepted provider output remains partial. Missing packages, exceptions and empty results
leave the baseline usable and record the reason.

Each saved structured document records the input's SHA-256, byte count, input kind and truncation
scope, plus generator identity, quality and page-declared author/publisher/language. The index
records hashes of the structured JSON and Markdown. Cache reuse verifies these hashes when
present and checks that files resolve under the data root; older files without hashes remain
readable. Browser fingerprints cover the visible DOM snapshot after hidden elements are removed,
not the original network response. Page declarations do not prove authorship or independence.

Eligible partial bodies now receive one browser attempt. Access restrictions, unsupported types,
known HTTP truncation and partial content with explicit incomplete markers do not trigger that
escalation. HTTP/browser attempts and final body-gap stop reasons are distinct from the selected
evidence. A failed or unhelpful attempt preserves the earlier usable artifact. Metrics distinguish
usable content, structurally complete content and content delivered with gaps. Compact quality
observations reach both brief and analysis inputs; writing workers retain their existing tool boundary.

Browser acquisition waits within the source timeout for visible text instead of accepting an
empty attached container. An offline headless Edge fixture with delayed article insertion,
CSS-hidden text and a table reproduced the earlier `Loading`-only extraction and passed after
the readiness fix. The successful browser result retained its structured table and excluded the
hidden text; enabling public HTTP retention still did not save browser-session HTML.

## Configuration

Existing configurations keep the built-in extractor and no raw response retention. To enable
the local candidate extractor, install the optional extra in the project's environment:

```sh
python -m pip install -e ".[extraction]"
```

Then merge these settings into the configuration supplied to the CLI:

```yaml
collection:
  item_order: source
  fallback_extractor: trafilatura
  retain_public_html: false
```

For permitted public-response auditing, `retain_public_html: true` stores a bounded HTTP input
as a non-rendered `.response.bin` beside usable structured evidence. It does not save cookies,
response headers, challenge pages or browser-session HTML. The default stores only the input
fingerprint. These artifacts belong in the ignored runtime data root and must not be committed.

The daily Top15 contract, explicit enrichment selection, cumulative 12-article run limit,
root/nested index synchronization and release snapshots are preserved. Runtime policy lives in
[editorial policy](../../references/editorial-policy.md) and
[system contracts](../../references/system-design.md).

## Validation and remaining work

Behavior tests cover input/artifact hashes, modified-cache rejection, raw-retention opt-in,
headerless tables, optional provider availability/failure, real local Trafilatura extraction,
single browser escalation, preserved partial evidence, immutable index revisions, source
coverage, bounded plans and quality propagation to authoring. These tests use synthetic pages;
they do not establish live-site extraction accuracy.

Final repository verification: **479 tests passed in 50.46 seconds**, including the installed
Trafilatura adapter. Ruff, compileall, Chinese code-comment checks, documentation checks and
`git diff --check` passed. The separate offline Edge check also passed. Feed failure regression
coverage confirms that stale cached items remain readable but do not increase current coverage.

See TD-040 for multilingual corpus acceptance and TD-041 for claim-level source relationships,
stakeholder coverage and evidence-gap search. No hosted scraping/search service or global
discovery feed was activated in this change.
