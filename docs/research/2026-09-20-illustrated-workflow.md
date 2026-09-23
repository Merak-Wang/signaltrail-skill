# Question-driven research and illustrated writing

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-20

This record implements the research/writing part of the September 20 supplied proposal.
[中文](../zh-CN/research/2026-09-20-illustrated-workflow.md).
Collection work is recorded separately in [collection improvements](2026-09-20-collection-improvements.md).

## Design and implemented behavior

The daily pipeline and research consume separate frozen inputs. `research prepare` needs a
canonical index and explicitly selected item IDs, not a completed report. It embeds bounded
original blocks, times, content status and provenance in the existing immutable narrative store.
The source index fingerprint records provenance but is not a live dependency: continued daily
extraction cannot invalidate an already dispatched research snapshot. Explicit IDs can also select from a monitor snapshot via `--discovery MONITOR.json`; selected Feed blocks are retained without upgrading their content status or changing daily quotas. Additional evidence uses
`--previous` to create a new snapshot. Changed supporting text reopens affected questions.

`research search` reuses the project's English tokens and Chinese bigrams with BM25 over source
blocks. `research select` greedily covers unresolved weighted questions and suppresses matching
original-record IDs and identical content. It stops when no additional question gains a candidate.
These are relevance suggestions, not automatic answers or independent corroboration. Cross-language
semantic search is not implemented; use original-language keywords alongside translated questions.

The question ledger distinguishes answered, partial, contested and not evidenced. Omitted questions
survive updates. A memo records conditions, counterarguments and observable watch points; new
research analyses receive `RA-` IDs and evidence receives `RE-` IDs. Native ledger compilation,
language scripts and isolated reviews are reused. Research inference cannot borrow the daily
report's analysis IDs or evidence outside its own premises.

Writing loads only the requested [Chinese](../../templates/research-style-zh.md) or
[English](../../templates/research-style-en.md) card. Optional tables register every header, cell and
editorial caption as a reviewable segment. Original constructed tables have a null publisher caption.
No external documentary images are admitted. A single-language story can use its exact supporting
review; bilingual acceptance still requires the bilingual receipt.

`research bind` validates the actual completed daily report and records extends/qualifies/disputes
relations without authorizing new facts in the old report. `research render` creates a separate HTML
revision, with research directly below the original three analyses and cross-perspective synthesis.
JSON and Markdown preserve the parents and text; the Markdown includes research as an appendix.
Old report JSON, Markdown, HTML, continuity and run status are untouched. The daily finalizer never
calls or waits for research. Host resource reservation and model dispatch remain host responsibilities.

## Evidence behind the design

STORM separates pre-writing inquiry from outline construction; its authors also describe source-bias
transfer and inappropriate association as unresolved problems. This supports adopting question-led
preparation without treating more perspectives as proof of correctness.
[Shao et al., NAACL 2024](https://aclanthology.org/2024.naacl-long.347/).
ALCE measures fluency, correctness and citation quality separately, supporting separate writing and
evidence checks rather than one overall score.
[Gao et al., EMNLP 2023](https://aclanthology.org/2023.emnlp-main.398/).
These are design inferences from the papers, not measurements of SignalTrail.

## Reproducible component comparison

Run `python scripts/evaluate_research_workflow.py --output output/research-workflow/benchmark.json`.
The fixed eight-case fixture includes four Chinese and four English questions. Relevant terms
deliberately appear only in saved body blocks. Both paths receive the same articles and cutoff.

| Measurement | Observed result |
| --- | --- |
| Title-only lexical top-1 hits | 0/8 |
| Body-block BM25 top-1 hits | 8/8 |
| Initial eight-article snapshot | 46.180 ms |
| Warm search, 160 samples, p50 / p95 | 3.163 / 4.442 ms |
| Network / model calls in this component experiment | 0 / 0 |
| Environment | Windows, Python 3.12.11 |

This demonstrates retrieval of information absent from titles on constructed examples. It is not a
production quality improvement estimate or a comparison against a pre-existing full-body retriever.
Timings include local artifact loading and vary with filesystem/cache state; there is no production
morning/evening p50/p95 or token-savings claim.

Behavior tests exercise preparation before a report, frozen content during upstream mutation,
Chinese retrieval, repeated-origin suppression, question retention, evidence correction, scoped
inference, table review, single-language review binding and immutable composite output. Existing
report/explainer tests remain the regression baseline. Runtime outputs belong under ignored `output/`
or the configured data root, not in Git.

## Acceptance limits

The Chinese reading demonstration uses the two original paper abstracts and contains three chapters,
one process diagram and one comparison table. An isolated reviewer checked 27 visible segments,
33 assertions and all six registered claims in the revised script. The initial review caught three
unmapped chapter headings and an unsupported statement about materials the author had obtained.
One author revision fixed these and added a concrete example; the receiving validator returned no
blocking findings. Model editorial scores were clarity 4/5, narrative 4/5 and explanation 4/5
(explanation was 3/5 before repair), with one minor mechanism-explanation suggestion remaining.
These scores are not a blind comparison or a measured reader-understanding improvement.

Desktop/tablet/mobile browser checks at 1440, 820 and 390 pixels found no page-width overflow on
either the standalone reading or composite fixture. The reading retained three chapters, one table,
one diagram and zero external asset dependencies. The composite preserved all three original analysis
domains and placed research before evaluation. Its parent is the repository's historical July 12
example, explicitly labeled as a test rather than a current edition. Identical reviewer input allowed
reuse of the same observed semantic judgment with separately bound receipts.

The CLI reports declared question coverage separately from semantic accuracy, independent
confirmations, reader comprehension and usage; unavailable measurements remain null. A model's
supporting review is not a human comprehension trial. The accompanying reading demonstration uses
historical research sources, not a live news edition. Automated targeted web research, robust
republication attribution, metered host dispatch, external-photo admission, and three-edition live
acceptance remain open. Current-news mode stays blocked. See TD-038 and TD-041 in the
[debt tracker](../exec-plans/tech-debt-tracker.md) and the
[runtime procedure](../../references/research-workflow.md).
