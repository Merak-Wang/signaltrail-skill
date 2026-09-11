# Report A section 2: code-review disposition

**Purpose:** Record verified defects, their repairs and the limits of the research recommendations.
**Status:** Historical
**Owner:** Repository maintainers
**Last verified:** 2026-09-11

[中文](../zh-CN/exec-plans/completed-2026-09-11-report-a-code-review.md)

The supplied Report A reviewed commit `c324c5e8529ae22268b2bd53a7b8394f3f8af26f`.
This change checked its second section against the current working tree, which already contained
experimental explainer work. The research files and production data are not copied into the repo.

| Finding | Disposition and evidence |
| --- | --- |
| A01 | Fixed flattened article evidence. `content_extraction` retains ordered headings, paragraphs, lists and table cells, including span declarations, in JSON; Markdown derives from the same blocks. Each extraction has unique artifact paths. |
| A02 | Fixed short-announcement loss and length-only `full_text`. HTTP and browser paths share region selection, substantive-block and link-density checks, incomplete markers and explicit HTTP truncation. Short specific content can be complete; broad or truncated content is at most partial. Classification remains a structural heuristic (TD-040), not fact verification. Non-HTML HTTP errors also preserve access failure. |
| A03 | Fixed descriptor-blind reversal and downstream `src` precedence in feed, static-index and browser-index paths. Valid `w`/`x` groups sort by descending value with stable ties; mixed units retain group order. Browser index records current source and natural dimensions; media decoding still supplies actual dimensions. Crop/target suitability remains TD-040. |
| A04 | Added caption, alt text, adjacent paragraph, purpose and lexical relevance provenance for selected-article images. Contextual images precede generic metadata; unlabeled images do not displace publisher metadata. Broad-body/recommendation/decorative images are excluded from article candidates. No model-based visual verification is claimed (TD-040). |
| A05 | Product constraint, explicitly identified as such by the report. Top order and the 12-article enrichment limit remain the daily-report contract. A research channel is separate future scope. |
| A06 | Capability limitation. Monitor clustering remains a lexical discovery aid. `source_count` counts source IDs, not independent corroboration; formal report events remain bound to articles. Cross-language event verification needs a separate corpus and design. |
| A07 | Fixed domain/thesis collision in persisted state. Report `analysis_id` remains the domain-column identity; state schema 1.2 adds claim-and-evidence `thesis_id`. Different claims/evidence retain separate histories, and `analysis-domains.json` provides the latest column projection. Ambiguous legacy records are preserved and labeled. |
| A08 | Fixed omission-based watcher closure and trivial whitespace duplication. Watch IDs bind to a thesis and normalized signal text; only explicit closure of that same thesis closes its watchers. Structured cross-wording triggers and validated continuation remain TD-039. |
| A09 | The five-report context window is a bounded continuity input. Long-range entity/date retrieval is a separate capability; it was not implemented by increasing the prompt window. |
| A10 | The review offered an information-architecture proposal without a measured UI defect. No general report UI rewrite was made. |
| A11 | The cited TD-002/007/010 remain open. Small extraction helpers and unique content paths do not resolve packet binding or paired report transactions. |
| A12 | The cited roadmap predates current experimental explainer changes. Existing snapshot-preview work was preserved; current-news admission and formal multimedia acceptance remain limited by TD-038. No video capability is claimed. |

Behavior regressions cover descriptor ordering, all three acquisition entrances, short complete
articles, link farms, hidden/recommended content, inline words, table spans, truncation, image
context, collision-safe content paths, legacy state, multiple same-domain theses, watcher omission,
explicit closure, late reports, evaluation exclusions, packet identity and the shared state lock.

The full repository gate uses the existing `.venv` Python environment. A separate offline headless
Edge check exercises browser acquisition with a local HTML fixture, CSS-hidden text and structured
persistence. These checks do not measure live-site extraction accuracy or run a credentialed report.

Final verification: **453 tests passed in 49.00 seconds**. Ruff, compileall, Chinese code-comment
checks, documentation checks and `git diff --check` passed. The final offline Edge fixture also
passed with its visibility stylesheet located inside the body.

The first two full-gate runs also exposed intermittent Windows `WinError 5` failures at the existing
explainer directory commit. A bounded retry now handles Windows access/sharing-lock errors only;
persistent errors still fail and an existing destination is never replaced. Fault-injection tests
cover transient recovery, exhaustion and a destination appearing between attempts. This preserves
the existing explainer behavior and does not resolve the report transaction gap in TD-010.

Runtime policy lives in [system contracts](../../references/system-design.md),
[editorial policy](../../references/editorial-policy.md) and the
[report contract](../../templates/report-contract.md). Pending capability acceptance is recorded in
the [technical-debt tracker](tech-debt-tracker.md), TD-039 and TD-040.

The responsive-image parser follows the descriptor distinction and URL tokenization described in
the [HTML standard](https://html.spec.whatwg.org/multipage/images.html#parse-a-srcset-attribute);
it is a deterministic acquisition preference, not a browser layout or crop-selection engine.
