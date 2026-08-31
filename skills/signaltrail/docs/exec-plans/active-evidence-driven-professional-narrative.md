# Evidence-Driven Professional Narrative Delivery

**Purpose:** Track staged delivery and acceptance for evidence-driven news explanation and its later
reader and media projections.
**Status:** Active
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

The [product specification](../product-specs/evidence-driven-professional-narrative-report.md) defines
the planned user result. The
[architecture record](../design-docs/evidence-driven-professional-narrative-report.md) defines
component ownership and invariants. The completed usage-metering and Token-optimization foundation is
recorded in the
[2026-08-23 implementation record](completed-2026-08-23-llm-usage-optimization-implementation.md).

Evidence-driven news explanation, independent claim and beat verification, story stream, authorized
assets, TTS, subtitles, news explainer video, and three consecutive accepted editions across multiple
agent harnesses all remain **Draft / Planned**.

## Phases and deliverables

| Phase | State | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| 0 — Contract reset | In progress | Concise bilingual product and architecture records; aligned catalogs and roadmap language | Documentation checks pass and all user-facing references identify the capability as Draft / Planned |
| 1 — Narrative foundation | Planned | Versioned narrative schema, parent report/index binding, bounded packet, immutable script revisions, deterministic validation | Focused fixtures cover valid, invalid, stale, replayed, interrupted, and concurrent work without overwriting history |
| 2 — Verification and reading | Planned | Independent claim/beat verifier, hash-bound verified gate, HTML and Markdown narrative views | Complete verification coverage, projection equivalence, browser QA, and blocked release for unresolved critical findings |
| 3 — Story stream and assets | Planned | Ordered scene manifest, authorized-asset catalog, provenance and rights receipts, deterministic fallbacks | Every released scene traces to a verified beat and an allowed asset; rights-unknown material remains blocked |
| 4 — Audio and video | Planned | Authorized TTS, measured subtitle timing, reproducible news explainer video, technical and rights QA | Playback, subtitle alignment, output identity, provenance, and retry behavior pass on representative editions |
| 5 — Multi-harness acceptance | Planned | Three consecutive real editions across at least two harnesses, including a morning and an evening edition | Each included phase passes the product gates, budgets, replay checks, and reader review with no harness-dependent semantic drift |

Each phase produces an independently reviewable increment. Failure or deferral in a media phase leaves
the canonical report and any verified text narrative available.

## Validation

### Automated validation

- Schema and persistence tests cover parent binding, immutable revisions, stale dependencies, and
  collision-safe replay.
- Narrative tests cover evidence references, language, deterministic validation, and claim/beat
  completeness.
- Verification tests cover role isolation, exact script binding, complete expected coverage, and
  explicit unresolved findings.
- Projection tests compare HTML and Markdown semantic identity and exercise safe browser rendering.
- Media tests cover scene lineage, asset rights, audio timing, subtitle alignment, output hashes, and
  recoverable rendering failures.
- Documentation and packaging checks keep English and Chinese records, public status, and shipped
  artifacts aligned.

### Real-edition validation

Before product promotion, run three consecutive editions across at least two agent harnesses. Record
the harness, parent report and index revisions, narrative and verification revisions, model-usage
coverage, elapsed time, gate decisions, editorial review, and projection or media results.

The sequence includes at least one morning edition and one evening edition. A failed or blocked
edition restarts the consecutive acceptance sequence after the underlying issue is addressed.

### Repository gate

Each phase passes focused tests during implementation and the full repository validation gate before
promotion. Reader and media phases also receive visual or playback review in the environments they
claim to support.

## Risks

| Risk | Impact | Planned response |
| --- | --- | --- |
| Narrative fluency weakens evidence boundaries | Unsupported certainty or misleading causal claims reach readers | Keep evidence authorization and admission deterministic; require independent verification and editorial review |
| Author and verifier are insufficiently independent | Shared assumptions allow the same error through both stages | Isolate roles and dossiers; compare verifier findings with human review during acceptance |
| Parent evidence changes after verification | A previously valid explanation appears current after its basis changes | Bind gates to parent hashes and freshness state; require a new decision for changed parents |
| Asset rights are ambiguous | Story or video output cannot be distributed safely | Maintain an explicit rights catalog and deterministic fallback; block unknown rights from release |
| Harness behavior differs | Provider, delegation, or usage details change outcomes | Keep semantic gates in the deterministic core and require consecutive acceptance across multiple harnesses |
| Model cost or latency exceeds the operating budget | Narrative or media delivery becomes impractical | Record phase usage and elapsed time, apply versioned budgets, and allow later phases to remain deferred |
| Media rendering fails after text verification | Audio or video delivery is partial | Keep media downstream and retryable; preserve the verified text revision and diagnostic receipts |
| The proposal freezes implementation too early | Prototypes inherit unnecessary fields and coupling | Finalize schemas and adapters from tested boundaries and real-edition evidence |

## Current progress

- [x] Usage metering and the controlled Token-optimization foundation are recorded separately.
- [x] Product, architecture, and execution records have been reset around user outcomes and durable
  boundaries.
- [ ] Phase 1 — narrative foundation.
- [ ] Phase 2 — independent verification and reader views.
- [ ] Phase 3 — story stream and authorized assets.
- [ ] Phase 4 — TTS, subtitles, and news explainer video.
- [ ] Phase 5 — three consecutive accepted editions across multiple harnesses.

## Plan completion

Move this plan to completed only after the shipped scope passes its automated and real-edition
validation, user documentation reflects the delivered behavior, English and Chinese records agree,
and any deferred media phase is clearly recorded as remaining work.
