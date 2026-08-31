# Evidence-Driven Professional Narrative Report Product Specification

**Purpose:** Define the planned reader experience, scope, quality promise, and release criteria for
evidence-driven news explanation and its later media projections.
**Status:** Draft
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

Every capability in this record remains **Draft / Planned**. The current SignalTrail runtime delivers
the canonical report described by the existing report contract. This proposal begins after that
report has been completed and validated. The related component design is in the
[architecture record](../design-docs/evidence-driven-professional-narrative-report.md), and staged
delivery is tracked in the
[active execution plan](../exec-plans/active-evidence-driven-professional-narrative.md).

## Product outcome

SignalTrail should turn selected events and existing analysis from one report revision into a
coherent news explanation. A reader should leave with a clear account of:

- what happened and what remains uncertain;
- which evidence supports each important statement;
- how actors, incentives, constraints, and causal mechanisms connect the events;
- where credible interpretations disagree;
- which assumptions support the current judgment; and
- which observable signals could strengthen, weaken, or change that judgment.

The narrative remains bound to the report and index that supplied its evidence. It preserves visible
source attribution, time context, uncertainty, and verification state while presenting the material
in natural prose suitable for reading or listening.

## Intended users

The planned capability serves readers who need a coherent, explainable briefing from a set of
headlines. Typical uses include an executive morning readout, an analyst handoff, a team briefing,
and a narrated review of a completed edition.

The same product contract applies across agent harnesses. Harnesses may differ in provider routing,
delegation, scheduling, and usage observation. Those differences must not change the evidence or
release requirements of the resulting narrative.

## Reader experience

Each narrative edition contains a short orientation followed by a small number of chapters. A
chapter follows one central question and connects the relevant news, background, analysis, and watch
signals into a continuous explanation.

The presentation should make these distinctions understandable without exposing an internal field
list:

- confirmed information and attributed statements;
- historical or contextual background;
- supported interpretation and causal reasoning;
- counterevidence, alternative explanations, and uncertainty;
- conditional scenarios and their assumptions; and
- observable follow-up signals.

Readers can open the evidence behind a chapter or claim. Source name, publication time, access state,
report `as_of` time, and verification result remain available in the reading view. The prose may use
storytelling techniques such as pacing, setup, and transition. Every factual detail and quotation
still follows the report's evidence boundary.

## Planned scope

### 1. Evidence-driven news explanation

The first planned stage produces a versioned narrative script from one completed report revision and
its matching index. It includes:

- chapters grounded in featured events, the three analysis perspectives, and cross-perspective
  synthesis when available;
- concise claim or beat units that can be traced and reviewed independently;
- visible treatment of evidence quality, freshness, disagreement, and uncertainty;
- deterministic validation before any narrative is presented as verified;
- local HTML and Markdown reading views derived from the same accepted semantic revision; and
- preserved usage and timing observations when the active harness exposes them.

A **claim** is an important factual or analytical statement. A **beat** is a small reader-visible
unit that groups one or more closely related claims. The implementation may refine their exact
schema after prototypes, while the traceability and verification promise remains stable.

### 2. Independent claim and beat verification

An independent verifier reviews the narrative against the authorized evidence from its parent
report. Verification covers support, attribution, time context, epistemic wording, and material
omissions or contradictions. The verifier produces a structured decision tied to the script,
report, and index hashes.

Failed or incomplete verification leaves the narrative in a reviewable Draft state. A later revision
may address the findings and receive a new verification result. Reader and media release requires a
current verified receipt.

### 3. Story stream and authorized assets

A later planned stage converts verified beats into a story stream: an ordered scene plan for visual
explanation. Each scene links to the verified beat it serves and records the origin and usage rights
of its selected asset.

Assets may come from approved public sources, repository-owned media, licensed libraries, or
purpose-created visuals with documented provenance. A deterministic fallback remains available when
an appropriate authorized asset cannot be found.

### 4. Audio, subtitles, and news explainer video

Later media stages add:

- authorized TTS with recorded voice and engine provenance;
- subtitles aligned to measured narration timing;
- a reproducible news explainer video built from the verified script and story stream; and
- technical and rights review before media delivery.

These stages remain independently releasable. A media failure leaves the verified text narrative
available.

## Product boundaries

The planned first release excludes:

- live broadcasting or automatic publication to public channels;
- impersonation, unapproved voice cloning, and synthetic quotes;
- assets with unknown or incompatible usage rights;
- source-video ingestion whose rights and provenance cannot be established;
- invented scenes, dialogue, motives, chronology, or insider knowledge;
- personalized financial, legal, medical, or military operational advice; and
- changes to the canonical report, index, or their continuity history.

The feature explains the evidence already admitted by SignalTrail. Source collection, access
verification, report authoring, and the existing report quality gate keep their current authority.

## Version and evidence contract

Every accepted narrative has a schema version, its own immutable revision, and hashes for the parent
report and index. Verification and media artifacts identify the exact narrative revision they use.
Changed parent content creates a new dependency state and requires a new verification decision.

The product contract reserves room for implementation learning. Exact filenames, function
signatures, prompt formats, model choices, and scene-renderer APIs will be selected during delivery
and recorded in the architecture only when they become durable boundaries.

## Quality principles

- **Traceability:** important claims lead to authorized evidence in the parent edition.
- **Clarity:** a reader can distinguish observation, attribution, interpretation, and uncertainty.
- **Explanatory value:** the narrative connects causes, constraints, incentives, and consequences.
- **Dialectical depth:** material counterevidence and alternative explanations receive fair treatment.
- **Freshness:** current judgments disclose their time basis and expire or return to review when that
  basis changes.
- **Revision integrity:** accepted artifacts remain reproducible from their recorded parents and
  cannot be silently overwritten.
- **Harness consistency:** the same edition reaches the same acceptance decision regardless of the
  harness used to orchestrate model work.
- **Rights safety:** every delivered media asset has an allowed provenance and use state.

## Compact acceptance model

The existing G0–G7 names remain as release labels. Each gate has one primary decision and a small
set of observable outcomes.

| Gate | Planned decision | Minimum observable outcome |
| --- | --- | --- |
| G0 — Parent binding | Is the narrative based on one completed current report revision? | Report and index identities, revisions, and hashes match the declared parents. |
| G1 — Evidence and freshness | Are important claims supported at the stated time and epistemic role? | Every critical claim has authorized evidence or an explicit unresolved result; stale evidence cannot receive a current verified decision. |
| G2 — Narrative quality | Does the edition explain events coherently and handle credible disagreement? | Editorial review passes clarity, explanation, counterposition, uncertainty, and usefulness at the versioned release threshold. |
| G3 — Independent verification | Did an isolated verifier review the complete claim and beat set? | Every released beat has a final structured decision, and the verified receipt covers the exact script revision. |
| G4 — Cost and observation | Is model work attributable and within the approved operating budget? | Required phases have exact or explicitly partial usage coverage; a release candidate stays inside its versioned budget. |
| G5 — Revision and recovery | Can replay, interruption, and concurrent work preserve history? | Existing revisions remain unchanged, duplicate work is avoided where identity matches, and recoverable failures retain an explicit state. |
| G6 — Reader projections | Do reading formats carry the same verified meaning? | HTML and Markdown identify the same semantic revision and preserve evidence links and safe rendering. |
| G7 — Media admission | Does every media stage use current verified content and authorized assets? | Draft, stale, mismatched, or rights-unknown input is blocked from released story-stream, audio, subtitle, and video artifacts. |

An aggregate quality score may support editorial review. It cannot override a failed parent,
evidence, verification, revision, or rights decision.

## Real-edition acceptance

Automated fixtures establish deterministic behavior before live acceptance. Product release then
requires three consecutive real editions produced across at least two agent harnesses. The sequence
includes at least one morning edition and one evening edition.

For each of the three editions:

- G0–G7 pass for every stage included in that release candidate;
- readers can trace a representative sample of critical claims to the parent report evidence;
- the independent verifier and editorial review agree that unresolved critical findings are absent;
- the edition stays within its recorded time and model-usage budget or records a blocked result;
- replay and projection checks preserve the same revisions and hashes; and
- harness-specific orchestration details do not appear in reader content or alter acceptance.

Story-stream, audio, subtitles, and video receive separate live acceptance when their phases are
implemented. Their release evidence includes rights review and technical playback checks.

## Release state

The evidence-driven news explanation, independent claim and beat verification, story stream,
authorized-media selection, TTS, subtitles, news explainer video, and multi-harness three-edition
acceptance all remain **Draft / Planned**.

This record may move to Verified only after implementation, schemas, automated tests, real-edition
evidence, user documentation, and the English and Chinese records describe the same shipped behavior.
