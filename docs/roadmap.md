# Roadmap: news explainers

**Status:** Draft · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

This proposal extends a finished report into an evidence-backed explainer, then into optional
audio and video. None of these features has shipped. It replaces the overlapping product,
architecture, and execution proposals with one scope and acceptance record. [中文](zh-CN/roadmap.md)

## Intended result

Start with a chapter-based text explainer: what happened, why it matters, what connects the
events, and where plausible interpretations disagree. Each important claim links to evidence
already admitted by the parent report. A beat is a short reader-visible group of related claims.

An independent verifier checks every released claim and beat for support, attribution, time
context, uncertainty, and contradictions. Unresolved critical findings leave the explainer
in Draft. Accepted text has HTML and Markdown views of the same semantic revision.

Later stages turn verified beats into an ordered scene plan, choose authorized assets, and
produce speech, measured subtitles, and a news-explainer video. A failed media stage leaves
verified text available. Public-channel publishing and live broadcasting are outside this scope.

## Boundaries

```text
completed report + index → bounded narrative packet → authored script revision
→ independent verification → current acceptance receipt → HTML / Markdown
→ scene plan + authorized assets → speech / subtitles / video
```

Python owns IDs, revisions, schemas, evidence authorization, hashes, freshness checks, and
admission to the next stage. Models write or judge only the supplied packet. Author and verifier
are isolated. Downstream stages have no write path into the parent report, index, or continuity.

Each semantic artifact has its own immutable revision and parent hashes. The acceptance receipt
binds the script, verification, parent report/index, and policy version. A change to a parent,
evidence fingerprint, freshness decision, or policy requires a new current decision; old receipts
remain historical. Identical completed work can be reused when those bindings still match.

Media scenes identify the beat they explain and the provenance and usage rights of every asset.
Unknown rights, unapproved voice cloning, invented quotes, and unverifiable scenes cannot enter
a released artifact. Keep a deterministic fallback for missing assets. Record voice/engine
provenance, measured narration timing, render settings, and output hashes for reproducibility.

Module names, exact schemas, beat size, expiry periods, repair limits, and renderer APIs will
follow prototypes. They are not frozen by this proposal.

## Delivery sequence

| Stage | Deliverable | Evidence needed |
| --- | --- | --- |
| 1. Narrative | Parent binding, bounded packet, immutable script | Schema, stale-input, replay, interruption, and collision tests |
| 2. Verification and reading | Independent verifier, acceptance receipt, HTML/Markdown | Complete claim coverage, unresolved findings blocked, equivalent reading views, visual review |
| 3. Scenes and assets | Scene manifest, asset provenance, rights receipts, fallbacks | Every scene traces to a verified beat and an allowed asset |
| 4. Audio and video | Authorized speech, timed subtitles, reproducible video | Playback, alignment, content, rights, identity, and retry checks |
| 5. Live acceptance | Three consecutive editions across at least two agent hosts | At least one morning and one evening edition; fixed quality, usage, and time criteria |

All stages are planned. Text can ship before media, provided its included stages pass acceptance.
Metering and earlier optimization work are recorded separately in the
[2026-08-23 implementation history](exec-plans/completed-2026-08-23-llm-usage-optimization-implementation.md).

## Acceptance

The previous G0–G7 labels remain useful for comparing release evidence:

| Gate | Required result |
| --- | --- |
| G0 Parent binding | A completed report and matching index, with verified IDs and hashes |
| G1 Evidence and freshness | Critical claims supported at the stated time; stale evidence cannot pass as current |
| G2 Narrative quality | Clear explanation, credible counterarguments, uncertainty, and reader usefulness at a versioned threshold |
| G3 Independent verification | Complete claim/beat coverage tied to the exact script; no unresolved critical findings |
| G4 Cost and observation | Attributed phase usage, explicit partial/unknown fields, and compliance with the recorded budget |
| G5 Revision and recovery | No overwrite, safe replay, explicit interrupted state, tested concurrency |
| G6 Reader projections | HTML and Markdown preserve the same verified meaning and evidence links |
| G7 Media admission | Current verified content, authorized assets and voices, technical playback checks |

A total quality score cannot override a failed evidence, identity, verification, or rights gate.
Before promotion, freeze the thresholds and run three consecutive real editions across two or
more hosts. Record parent/script/verification revisions, usage coverage, elapsed time, gate
decisions, reader review, and projection results. A failed edition restarts that sequence after
the issue is fixed. Media stages require their own live acceptance when implemented.

Open implementation gaps in the current report pipeline remain in the
[technical-debt tracker](exec-plans/tech-debt-tracker.md).
