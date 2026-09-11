# Roadmap: news explainers and illustrated reading

**Status:** Active · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

This upgrade extends a completed report into a verified explainer and an illustrated reading
stream. The 2026-09-08 research and experimental prompts are complete; the runtime features below
now include an implemented experimental N1–N3 snapshot path; current-news admission and N4 remain pending. Speech, subtitles, and video are the next upgrade. This is the single
implementation scope and acceptance record. [中文](zh-CN/roadmap.md)

The [research](research/2026-09-08-news-explainer-workflows.md) covers source evidence, alternatives,
access limits, and a historical example. The [Chinese prompt pack](../templates/news-explainer-prompts.md)
defines seven editing stages; it is experimental, not an executable runtime contract.

Implemented scope is deliberately narrower than the intended current-news contract: snapshots only, no external photos, no model dispatch, and no current receipts. See [the implementation guide](explainers.md) and TD-038. The remaining requirements below still govern promotion.

## Intended result

Provide chapter-based Chinese and English narration for readers with some background: what changed, what
background is needed, how the mechanism works, and what can reasonably be inferred. In the
analysis area, a composed reading view adds explanation and naturally introduces the existing
professional judgments with their conditions. The child artifact does not rewrite the saved
report. Existing report-only readers remain compatible.

The user confirmed Chinese oral-storytelling rhythm and English novel-like narrative continuity,
with professional analysis in both. Author each language from one shared claim/analysis ledger;
do not require literal translation. Preserve language-specific revisions and check agreement on
material facts, time, attribution, causality, conditions, and certainty. Do not mix languages in
the existing single-language report schema. Novel-like refers to structure and expression,
not invented scenes, dialogue, motives, or endings.

Each factual or inferential assertion links to admitted evidence or an authorized analysis
dependency. A beat is a short reader-visible group of related claims. One chapter answers one
question; distinct mechanisms belong in separate chapters. Retain complete scripts for revision
and review, then edit for speech. Do not invent scenes, motives, quotations, opposition, or endings.

An independent verifier re-extracts assertions from the complete script, including titles and
transitions, and checks support, attribution, time, uncertainty, contradictions, and omissions
against the required-fact list. Critical unresolved findings leave the explainer in Draft.
Versioned JSON and Markdown preserve accepted meaning; HTML is a rebuildable view.

This upgrade also produces an ordered story manifest and a responsive illustrated page:
timelines, mechanism diagrams, data comparisons, attributed positions, evidence gaps, and relevant
authorized images. Initial renderers may reuse accepted wording verbatim. New card headings,
copy, captions, chart labels, and alternative text require semantic review bound to that card
revision. Renderers cannot generate or rewrite semantic content.

The next upgrade adds speech, measured subtitles, and video. Keep stable beat/claim/asset
references now, without inventing audio durations or freezing an engine. Public-channel posting,
platform algorithm optimization, and live broadcasting are outside the current scope.

## Boundaries

```text
completed report + index → bounded evidence and editorial intent → claim/time checks
→ outline and script → independent verification → current script receipt
→ card/asset draft → semantic and visual review → accepted story manifest
→ versioned Markdown + HTML

next upgrade: accepted story manifest → speech / measured subtitles / video
```

Python owns IDs, revisions, schemas, evidence authorization, hashes, freshness checks, and
admission. Models write or judge only their supplied packet. Separate author and verifier
contexts; a second model call is not an independent source. Downstream stages cannot write into
the parent report, index, or continuity. New facts discovered during rechecks go through upstream
collection and new report/index revisions before authoring resumes.

Each semantic artifact has an immutable revision and parent hashes. Receipts bind the script,
verification, parent report/index, packet, and policy; story receipts also bind the manifest and
its reviews. Loaders check recursive parent closure and exact claim/beat coverage, not latest-file
scans or author-supplied pass labels. Parent, evidence, policy, or semantic changes need a new
decision. Old receipts remain historical; unchanged valid work can be reused. Rejected attempts
and interruptions stay observable.

Content verification, current admission, and projection status are separate. Accepted historical
text may become ineligible as current news without overwriting history. Narrative or story failure
cannot revoke a valid report. Use completed reports initially; partial-report support needs a
separate policy. Missing assets have a deterministic text/diagram fallback.

Assets retain their associated beat, provenance, subject/time context, and permitted use. Safe
downloading is not a rights receipt. Unknown rights or unverifiable depictions cannot enter
released cards. Diagrams preserve units, periods, uncertainty, and text alternatives.

Exact schemas, module names, beat size, and renderer APIs follow prototypes. Candidate budgets
and thresholds below must be frozen before promotion; they are not implemented defaults.

## Time and evidence admission

Preserve event time/precision, publication time, source update time, fetch time/fingerprint,
script cutoff/timezone, and check time separately. Missing remains unknown. Collection time
cannot make old news current. Future scheduled events are valid as plans; a future publication
timestamp is a different validation issue.

Check critical state before writing and before publishing or delayed rendering. Inspect the
publisher's correction/update chain: an unchanged old page does not exclude a new update URL.
The earlier 120-minute soft TTL is only a candidate upper bound for ordinary news; fast-changing
claims need stricter checks. Use an edition-boundary hard expiry and reject at the exact deadline.
Failed access, missing required sources, or material unresolved conflicts block current admission,
not the parent report. Record the exact checked evidence set and recheck time.

Apply freshness to individual claims, including mixed historical/current claims in one beat.
A title or beat label cannot transfer freshness to unrelated evidence. Changed evidence or stale
relative wording needs a new semantic decision; changed evidence also needs upstream report
revision. Targeted wording repair does not authorize extra research by the writer.

## Delivery sequence

| Stage | Deliverable | Evidence needed |
| --- | --- | --- |
| R0. Research — complete | Sources, limitations, historical example, seven prompt templates | Core sources read, code mapping checked, proposals marked |
| N1. Script foundation — experimental implementation | One-chapter prototype, then edition packet/claim ledger and immutable script | Parent/schema binding, authorization, time semantics, replay, interruption, collision tests |
| N2. Verification and reading — experimental implementation | Independent reviews, language revisions, bilingual consistency, current receipts, explanation in the analysis area | Complete assertion/required-fact coverage, no language drift or critical failure, equivalent reading meaning |
| N3. Illustrated reading — experimental implementation; this upgrade's endpoint | Card review, story manifest, asset provenance, local HTML/Markdown | Every card/visual traces to accepted claims; fallback, mobile layout, accessibility, correction propagation |
| N4. Live acceptance — planned | Three consecutive N1–N3 editions across at least two hosts | At least one morning and one evening; frozen quality, token, and time criteria |
| V1. Speech and video — next upgrade | Authorized speech, actual subtitle timing, reproducible video | Separate playback, alignment, provenance, rights, and recovery acceptance |

N1 samples do not establish edition acceptance. N2 text can ship once its own gates pass; N3 is
required to complete this upgrade. The experimental runtime is described in [the explainer guide](explainers.md). Current-news admission remains blocked until the external freshness adapter and live acceptance are complete. Earlier
metering and optimization are in the [2026-08-23 implementation history](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md).

## Implementation map and first slice

| Work | Existing boundaries to read | Proposed tests |
| --- | --- | --- |
| Packet and claim ledger | `context.py`, `authoring.py`, `content.py`, report contract | `test_narrative.py`: authorized evidence, unknown time, unregistered assertions |
| Independent fact/time review | `evaluation.py`, `llm_usage/`, `storage.py` | `test_narrative_verification.py`: coverage, repair exhaustion, stale gate, critical omissions |
| Reading composition | `reports.py`, `local_output.py`, `workflow.py` | `test_narrative_delivery.py`: child binding, equivalent meaning, report unaffected by failure |
| Cards and assets | `media.py`, `image_policy.py`, local renderers | `test_story_stream.py`: qualifiers, caption/diagram claims, rights fallback, recovery |

These filenames and possible new `narrative`/`story_stream` modules are proposals, not current
commands. Existing `verification.py` handles browser access challenges; keep semantic review
separate and avoid adding it to the large report validator.

Before N1 integration, address or explicitly isolate TD-007 packet binding and TD-025 mutation
races. Test around TD-008 context invalidation and TD-019 prose evidence boundaries. Use a safe
new revision transaction without assuming TD-010 is resolved. The existing technical-debt
entries remain the authoritative gap records.

The first coding slice is an offline, fixture-driven packet/claim/script contract with immutable
save/load and no model dispatch. Then attach the storyteller and isolated reviewer. Runtime
steps enter `SKILL.md` and detailed policy enters `references/` when their behavior is implemented.

## Acceptance

Keep G0–G7 for comparison with earlier proposals:

| Gate | Required result |
| --- | --- |
| G0 Parent binding | Completed report and matching index, verified IDs/hashes |
| G1 Evidence and freshness | Time-qualified support, checked update chains, no unknown/stale evidence presented as current |
| G2 Narrative quality | Clear explanation, supported analysis/objections, uncertainty, and reader understanding |
| G3 Independent verification | Exact claim/beat coverage, independent extraction, required facts/corrections included, no critical unresolved findings |
| G4 Cost and observation | Attributed phase usage, explicit partial/unknown fields, compliance with recorded budget |
| G5 Revision and recovery | No overwrite, safe replay, explicit interruptions, tested concurrency |
| G6 Reader projections | JSON/Markdown and HTML preserve accepted meaning and links, no semantic rewrite during rendering |
| G7 Illustrated admission | Current script/story decisions, reviewed copy/visual claims, permitted assets, text alternatives and fallbacks; voice/playback checks deferred to V1 |

A quality score cannot override evidence, identity, verification, or rights failure. Freeze scope,
prompt/model policy, token ceilings, time limits, and quality criteria before live acceptance.
Keep 6–10 selected events, at least 60% distinct featured-event coverage, and all three analysis
domains as the initial formal scope candidate. Count admitted claims, not decorative chapter
references. A one-chapter prototype does not bypass edition-wide requirements.

Candidate evaluation: the older 32-case split (8 factual, 8 temporal, 8 causal/epistemic,
4 injection, 4 clean); two separate runs each detecting all critical defects, at least 90%
noncritical defects, and passing 4/4 clean controls. Version the defect denominator and human
labels. A finite test target is not proof of zero production error. Retain one shared repair as
the initial budget. Compare single-prompt and staged authoring on identical frozen evidence;
measure tokens, time, omissions, and reader understanding as well as style.

Human review records actual read-through issues and whether readers can explain the change,
background, mechanism, uncertainty, and watch point. An initial candidate is four of five
comprehension answers correct with no confusion of the central fact and inference. Calibrate
rubrics and reviewers before freezing. Model self-scores are not human review or measured speech.

Review understanding separately with readers of each language. A bilingual bundle requires
current decisions for both language revisions and their consistency review; single-language
success cannot represent a completed bilingual edition. Preserve independent retries and
explicit availability when one language is pending.

Run three consecutive real editions across at least two hosts, recording all parent/child
revisions, usage coverage, elapsed time, decisions, reader review, and projections. A failed
edition restarts the sequence after repair. Missing usage stays unknown and cannot support an
exact savings claim. Audio/video require a separate live sequence when implemented.

Existing implementation gaps remain in the [technical-debt tracker](exec-plans/tech-debt-tracker.md).
