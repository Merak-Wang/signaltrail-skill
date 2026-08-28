# Evidence-Driven Professional Narrative Delivery

**Purpose:** Track the staged implementation and acceptance of a verified professional narrative,
story stream, and optional media projections downstream of the canonical SignalTrail report.
**Status:** Active
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

This is the durable execution record for the capability defined by the
[architecture record](../design-docs/evidence-driven-professional-narrative-report.md) and
[product specification](../product-specs/evidence-driven-professional-narrative-report.md).
The completed metering and Token-optimization foundation is recorded separately in the
[2026-08-23 implementation record](completed-2026-08-23-llm-usage-optimization-implementation.md).

## Outcome

Deliver a natural, professional storytelling layer that explains selected news and dialectical
analysis without weakening evidence boundaries. The immutable report and index remain factual
authorities. A narrative, story stream, audio track, or video is a downstream projection and can
never modify or revoke a valid report.

Only an independently verified, current, hash-bound script may enter reader or media stages.
Rejected, stale, incomplete, or mismatched scripts remain visible evidence but are never promoted.

## Delivery sequence

```text
immutable report + immutable index
-> bounded narrative packet
-> storyteller draft
-> deterministic validation
-> immutable canonical script revision
-> independent per-beat verification
-> immutable verified-gate receipt
-> reader projection
-> deterministic story stream
-> licensed TTS + subtitles
-> reproducible video + media and rights QA
```

## Work packages

1. Define strict schemas, typed state, immutable repositories, hashes, and recovery rules for
   packets, scripts, verification, and gate receipts.
2. Build a bounded packet from a fully completed report and accept one storyteller submission with
   at most one shared repair.
3. Verify every beat independently and expose one public loader that returns only a current typed
   verified capability.
4. Render the verified narrative in local HTML and Markdown without changing canonical report
   content or continuity state.
5. Compile a deterministic, rights-aware story stream using verified beats and explicit fallback
   media.
6. Add licensed TTS, measured subtitles, reproducible video rendering, and technical/rights QA
   only after the story-stream gate passes.

## Acceptance gates

- Python owns IDs, revisions, hashes, evidence authorization, freshness, state, repair limits,
  persistence, and downstream admission.
- Final verified claims cover at least 60% of distinct featured events, all three analysis domains,
  and the required cross-perspective synthesis under the versioned contract.
- An independent verifier passes every final beat; failures cannot be hidden by partial media
  output or a force flag.
- Three consecutive fully accepted editions, including at least one morning and one evening, pass
  the pre-frozen Version 1 Token ceiling and all quality/evidence gates.
- The full repository validation gate passes on Windows and Linux before any phase is promoted.

## Recovery and rollback

- Every attempt, script revision, verification, and gate receipt is immutable and collision-safe.
- A changed report, index, contract, packet, script, or freshness decision invalidates dependent
  work instead of silently migrating it.
- Disabling or failing narrative/media phases leaves the canonical report delivered and valid.
- Reader and media entry points accept only an explicit verified bundle; they never scan for a
  latest file or accept raw objects, partial beat sets, or bypass flags.

## Progress

- [x] Accepted the controlled analysis-stage Token reduction under the model-token-only cost
  definition while retaining quality and latency as rollout guardrails.
- [x] Recorded the Draft architecture and product contract with matching Chinese translations.
- [ ] Implement narrative schemas, repositories, packet projection, storyteller submission, and
  deterministic validation.
- [ ] Implement independent per-beat verification, bounded repair, and the verified-only gate.
- [ ] Add verified reader projections and complete three consecutive N1–N5 acceptance editions.
- [ ] Implement and accept the rights-aware story stream.
- [ ] Implement and accept licensed TTS, subtitles, reproducible video, and media QA.
