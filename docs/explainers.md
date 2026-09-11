# Experimental bilingual explainers

**Status:** Active · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

This guide describes the implemented report-derived explainer workflow and its limits.
[中文](zh-CN/explainers.md)

`signaltrail explainer` now freezes evidence, accepts a shared claim ledger, saves independent
Chinese and English scripts, prepares isolated semantic and bilingual reviews, and renders an
illustrated HTML reading stream. It runs after a saved edition and never modifies its report,
index, or continuity state. The reading page combines explanation and conditional analysis.

This is an experimental snapshot workflow. `render --mode current` deliberately fails:
automated correction-chain retrieval, calibrated claim expiry, host-metered model dispatch,
human comprehension tests, and the multi-host live acceptance sequence remain pending. A
`verified_snapshot` means the exact script received a structurally complete supporting model
review of its supplied evidence. It does not mean the underlying news was independently
confirmed or remains current. There is no automatic publishing or model invocation.

## Run the workflow

Use the existing data root and explicit artifact paths returned by each command. `--experimental`
allows a `completed_partial` parent only for a disclosed preview; the default requires `completed`.
The first implementation freezes all featured events and their associated original spans. It
does not use ordinary brief prose as independent evidence or silently fetch extra sources.

```text
signaltrail explainer prepare --run RUN.json --experimental
signaltrail explainer ledger --packet PACKET.json --input CLAIMS.json
signaltrail explainer script --ledger LEDGER.json --input ZH.json --author-context AUTHOR_CONTEXT
signaltrail explainer script --ledger LEDGER.json --input EN.json --author-context AUTHOR_CONTEXT
signaltrail explainer review-packet --script ZH_SCRIPT.json
signaltrail explainer review-packet --script EN_SCRIPT.json
signaltrail explainer review --packet ZH_REVIEW_PACKET.json --input ZH_REVIEW.json --reviewer-context ZH_REVIEW_CONTEXT
signaltrail explainer review --packet EN_REVIEW_PACKET.json --input EN_REVIEW.json --reviewer-context EN_REVIEW_CONTEXT
signaltrail explainer bilingual-packet --zh-review ZH_RECEIPT.json --en-review EN_RECEIPT.json
signaltrail explainer bilingual --packet BILINGUAL_PACKET.json --input BILINGUAL_REVIEW.json --reviewer-context BILINGUAL_CONTEXT
signaltrail explainer story --script ZH_SCRIPT.json --script EN_SCRIPT.json --bilingual BILINGUAL_RECEIPT.json
signaltrail explainer render --story STORY.json
signaltrail explainer status --script ZH_SCRIPT.json
```

The injected `payload.output_schema` is the executable output contract. Claim IDs and script
segment IDs are Python-owned. The host supplies context identifiers; only their hashes are
stored. Use genuinely separate author/reviewer contexts: checking different labels is a guard
against accidental reuse, not a security boundary or proof of model independence. Usage remains
explicitly `unmetered` with null counts. Do not infer exact token savings.

Author both languages from the same ledger. Include every required claim in body beats;
decorative title references do not count. Record visual node text in the script so the independent
review includes it. A language has an initial script attempt and one repair shared across format
and semantic failures. Exact replay consumes no additional attempt. Language retries remain
independent. Current ledger edits require new downstream reviews.

Each reviewer re-extracts assertions from the entire script. The receiver checks every segment
exactly once, including headings, transitions and visual labels; valid quotes, authorized spans,
registered claims and required-fact coverage are mandatory. Contradiction, insufficiency,
unmapped assertions, required omissions or critical/major findings keep the script in Draft.
Quality scores cannot compensate. Semantic correctness still depends on the reviewer.

## Reading and visual review

Without a bilingual receipt, `story` can create a clearly labeled Draft preview with either
language, supporting independent recovery. With a receipt it requires the exact reviewed pair.
The renderer repeats script text verbatim, provides linked sources and expandable claim details,
and builds original explanatory diagrams from registered visual labels. Parallel or narrative
order is not rendered as an asserted causal arrow. No external photos are admitted in this
version; the full text is always the deterministic fallback. A shared Chinese claim ledger is
visible only in the optional audit disclosure of the English page and is marked `lang="zh-CN"`.

Inspect both languages at desktop and mobile widths. Save local PNG screenshots under the
data root, then submit a `VISUAL_SCHEMA` response (defined in `narrative_contracts.py`) with exact
projection SHA-256, every card ID and relative screenshot paths:

```text
signaltrail explainer visual-review --projection PROJECTION.json --input VISUAL_REVIEW.json
```

Missing observations must be `unavailable`. The receiver checks bindings and image signatures;
it cannot prove that a submitted screenshot was actually inspected. Any HTML or layout change
requires a new projection and visual review. No speech durations or video assets are generated.

## Persistence and recovery

Records live under `narratives/<report-id>-<packet-hash>/`. Each stage allocates its revision
inside a session lock. A temporary directory containing JSON and authoritative Markdown is
atomically renamed; a JSON hard link indexes the committed revision. If interruption occurs
after directory commit, replay repairs the missing index. Existing revisions are never replaced.
Markdown has its own byte hash. Every loader checks parent byte hashes recursively and the
current policy; it never chooses an author-supplied pass label or a latest receipt by filename.

Locks fail promptly when held by another process. Retry after that process finishes. An orphan
lock requires confirming its owner is no longer active before removing it. Temporary directories
are never considered committed artifacts. Projection failures leave the authoritative story and
parent report available for exact replay. Local hashes detect inconsistent edits, not an attacker
who can rewrite the entire store and all its hashes.

The upstream TD-007/TD-025 gaps are isolated by the new immutable packet and submission locks;
they are not repaired globally. Current-news and formal acceptance work stays in the
[roadmap](roadmap.md) and [technical-debt tracker](exec-plans/tech-debt-tracker.md).
