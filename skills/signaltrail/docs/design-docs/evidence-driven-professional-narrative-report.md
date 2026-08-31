# Evidence-Driven Professional Narrative Report Architecture

**Purpose:** Define the planned component boundaries, data flow, state ownership, and durable
invariants for evidence-driven narrative and later media projections.
**Status:** Draft
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

All components described here remain **Draft / Planned**. This record guides future implementation; current runtime behavior remains governed by existing records. The reader promise is defined in the
[product specification](../product-specs/evidence-driven-professional-narrative-report.md), and the
delivery order is tracked in the [active execution plan](../exec-plans/active-evidence-driven-professional-narrative.md).

## Decision

Narrative and media form a downstream layer over the canonical SignalTrail report. The existing
report JSON and index remain the factual authorities. The new layer reads a completed revision,
creates its own immutable revisions, verifies them, and publishes projections without changing the
parent artifacts.

Deterministic Python owns identity, schema validation, evidence authorization, hashes, revision
allocation, state transitions, persistence, and downstream admission. Agent harnesses orchestrate
bounded model work. Authoring and verification models contribute semantic judgments inside the
packets they receive.

The design stays harness-neutral. A harness adapter supplies execution, delegation, provider
observation, and optional scheduling. The semantic contract and acceptance decisions remain shared.

## Dependency direction

The planned dependency flow is one way:

```text
canonical report + canonical index
  -> narrative packet builder
  -> authoring through an agent harness
  -> deterministic validator and revision store
  -> independent claim/beat verifier
  -> verified-gate store
  -> reader projections
  -> story stream and authorized assets
  -> TTS, subtitles, and news explainer video
```

Downstream media may read verified narrative state. It has no write path back into report, index,
continuity, source-health, or collection state.

## Component boundaries

| Component | Planned responsibility | Inputs it may trust |
| --- | --- | --- |
| Canonical report reader | Load one completed report and matching index revision | Existing validators and persisted hashes |
| Narrative packet builder | Select authorized evidence and compact it for authoring | Validated report, index, and versioned narrative policy |
| Harness authoring adapter | Dispatch bounded narrative work and return a candidate | Packet, target language, and correlation metadata |
| Narrative validator and store | Validate structure and evidence references; allocate immutable revisions | Candidate plus the exact packet and parent identities |
| Independent verifier | Review claims and beats against authorized evidence | Accepted script revision and a verification dossier |
| Verified-gate store | Bind a final decision to script and parent hashes | Deterministic results and independent verification |
| Reader projector | Render HTML and Markdown from one verified semantic revision | Current verified gate and its script |
| Story compiler | Turn verified beats into an ordered scene manifest | Verified narrative and rights-aware asset catalog |
| Media renderer | Produce audio, subtitles, and video with technical receipts | Story manifest, authorized assets, and voice authorization |

The exact module names and public APIs will be chosen during implementation. The table defines
ownership boundaries that should remain stable across those choices.

## Planned artifact model

The layer uses a small set of conceptual artifacts:

- **Narrative packet:** the bounded, versioned evidence input given to the authoring model.
- **Script revision:** the accepted semantic narrative with chapters, claims or beats, and evidence
  references.
- **Verification revision:** the independent structured decisions and findings for one script.
- **Verified gate:** the admission receipt binding the current script, verification, report, index,
  and policy versions.
- **Story manifest:** the ordered relationship between verified beats, scenes, and authorized assets.
- **Media receipts:** provenance, timing, rights, render configuration, and output hashes for audio,
  subtitles, and video.

Every durable artifact carries a schema version and identity. Parent relationships use content
hashes and immutable revision identifiers. Projections may be rebuilt; semantic source artifacts
remain append-only.

## Data flow

1. The parent reader confirms that the report and index are complete, mutually consistent, and
   eligible for narrative work.
2. The packet builder selects featured events, analysis, synthesis, and supporting evidence already
   admitted by the parent report.
3. The active harness sends that bounded packet to an authoring worker and records the available
   usage and timing correlation.
4. The validator checks the returned structure, evidence references, language, and parent binding.
5. A valid candidate receives a new immutable script revision. Invalid work receives a reviewable
   rejection state.
6. An isolated verifier reviews the complete claim and beat set against a compact dossier built from
   the same authorized evidence.
7. Deterministic code combines validation and verification into a verified-gate decision bound to
   all relevant hashes.
8. Reader projections render the verified semantic revision. Projection failure can be retried
   without changing that revision.
9. Later phases compile a story manifest, select authorized assets, synthesize approved narration,
   align subtitles, and render a video with separate rights and technical receipts.

## State ownership

| Concern | Owner |
| --- | --- |
| Report and index identity | Existing report pipeline |
| Narrative schema and policy version | Deterministic core |
| IDs, hashes, revisions, and parent links | Deterministic core |
| Evidence allowlist and freshness decision | Deterministic core |
| Narrative language and analytical expression | Authoring model within the packet boundary |
| Claim and beat judgment | Independent verifier within the dossier boundary |
| Final admission state | Deterministic core |
| Provider execution and worker lifecycle | Agent harness adapter |
| Usage observations | Harness adapter plus immutable usage ledger |
| Scene ordering and asset rights state | Story compiler and rights catalog |
| Audio timing and render receipts | Media pipeline |

Models return authored or evaluative content. They do not allocate durable IDs, advance states,
rewrite parent artifacts, or declare their own output verified.

## Conceptual lifecycle

A narrative normally moves through planned, drafting, validated, verifying, verified, and projected
stages. Rejected, partial, and stale are durable side states with an explanation and parent identity.
The implementation may choose different enum names while preserving these transitions.

An accepted artifact never changes in place. A repaired or updated candidate becomes a new revision.
When a report, index, evidence fingerprint, policy version, or relevant freshness decision changes,
the previous gate remains historical and downstream admission requires a current decision.

## Key invariants

1. The canonical report and index remain the only factual authorities for the edition.
2. Narrative, verification, and media artifacts identify their exact parent revisions and hashes.
3. Durable semantic artifacts are immutable and collision-safe.
4. Authoring receives only the evidence authorized for that narrative packet.
5. Critical claims and reader-visible beats have traceable verification coverage.
6. Verification runs independently from authoring and cannot promote its own input.
7. A verified gate is the sole admission record for reader and media release.
8. Parent or policy changes make dependent gates stale while preserving their audit history.
9. Media release uses assets and voices with an allowed rights state and recorded provenance.
10. A downstream failure leaves the canonical report and any already verified narrative intact.
11. Replaying an identical completed identity reuses the existing durable result where safe.
12. Harness-specific execution data stays outside reader-facing semantic content.

## Evidence and freshness boundary

The packet builder derives its evidence set from the validated parent report and index. It records the
report `as_of` time, evidence timestamps, access state, and the parent fingerprints needed to detect
change. Authoring workers cannot expand that set through browsing or retrieval during the bounded
task.

Freshness is a deterministic admission concern. A policy version defines when current claims require
rechecking. Rechecking compares the recorded parent and evidence identities with the current eligible
edition. A changed basis produces a new narrative or verification revision; an unchanged basis may
receive a new time-bound gate receipt.

The initial implementation will keep freshness policy compact. Exact time-to-live values and claim
classes will follow prototype results and real-edition evidence.

## Independent verification boundary

The verifier receives the accepted script, its claim and beat structure, and an evidence dossier
generated from authorized parent content. It reports support, attribution, temporal fit, epistemic
wording, contradiction, and unresolved critical findings in a structured result.

Deterministic code confirms that verification covers the exact script revision and complete expected
claim/beat set. A verified result requires all critical findings to be resolved. Editorial quality
review remains a separate release input for coherence, explanatory value, dialectical depth, and
reader usefulness.

The first prototypes will determine practical beat size and repair policy. The durable boundary is
the independence of verification and its hash-bound decision.

## Harness boundary

A harness integration needs to:

- execute deterministic SignalTrail commands in the selected workspace and data root;
- deliver bounded packets to authoring and verification workers;
- keep authoring and verification roles isolated;
- return candidate artifacts through controlled paths or equivalent structured handoff;
- preserve task correlation for available usage observations; and
- report interruption, cancellation, and worker failure explicitly.

Provider names, model choices, delegation tools, Hook formats, and schedulers belong to the adapter.
Hermes, Codex, OpenClaw, and future harnesses can use different mechanisms while sharing the same
artifact and gate contracts. Live release acceptance spans at least two harnesses across three
consecutive editions.

## Reader projection boundary

HTML and Markdown read one verified semantic revision. They expose evidence links, verification
state, time context, and accessible navigation. Rendering code escapes untrusted content and does not
introduce new claims. Both projections identify the same semantic hash even when their presentation
differs.

Reader feedback is stored separately from the verified narrative. It can inform a future revision
through the normal packet and verification path.

## Story and media boundary

The story compiler creates scenes only from verified beats. Each scene records its narrative purpose,
asset identity, provenance, rights state, and fallback. Rights-unknown assets remain in review and
cannot enter a released media manifest.

TTS requires an authorized voice and records engine, voice, language, and output identity. Subtitle
timing is derived from the produced narration. Video rendering consumes the story manifest, audio,
subtitles, and authorized assets, then records enough configuration and hashes to reproduce and
inspect the output.

Story-stream, TTS, subtitles, and video remain separate planned phases. Their failures do not change
the verified status of the text narrative.

## Failure and recovery

Writes use atomic, collision-safe revision allocation. Interrupted work retains the last durable
state and can resume from an eligible boundary. Projection and media rendering can retry from the
same verified semantic inputs. Changed or stale parents require a new admission decision.

Concurrent workers may race to submit equivalent work. Identity and revision checks prevent
overwrite and allow reuse of an already accepted result. Ambiguous or damaged state stops promotion
and preserves diagnostic receipts for review.

## Security and privacy

Source content remains untrusted data. Workers receive bounded evidence, and external text never
becomes an instruction. Durable artifacts contain allowlisted identities, counts, provenance, and
decisions. Prompts, generated reasoning, credentials, authenticated state, and unrestricted provider
receipts stay outside them. Media retrieval adds rights review to the existing network safety policy.

## Deferred implementation choices

Claim and beat shape, freshness thresholds, verifier and repair policy, rights vocabulary, asset
providers, media engines, and harness-adapter details remain open. Prototypes, tests, and real-edition
evidence will determine which choices become durable architecture.

## Verification strategy

Automated tests cover schema compatibility, parent binding, immutable revisions, deterministic
validation, verifier coverage, stale-state handling, projection equivalence, rights admission,
idempotent replay, and failure recovery. Browser checks cover the reader experience. Media checks
cover playback, subtitle alignment, provenance, and rights receipts.

Final promotion requires three consecutive accepted real editions across at least two harnesses,
including a morning and an evening edition. The product specification supplies the release criteria;
the execution plan records evidence and remaining risks.

This architecture may move to Verified only when implementation, schemas, tests, operations, and
English and Chinese documentation agree on the shipped boundaries.
