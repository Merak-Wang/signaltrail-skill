# Evidence-Driven Professional Narrative Report Architecture

**Purpose:** Define the proposed cross-module boundaries, artifact lineage, state ownership,
verification gates, and media dependency direction for professional storytelling-style daily
reports.
**Status:** Draft
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

This record designs a capability that is not implemented yet. Current runtime authority remains
with [the repository architecture](../../ARCHITECTURE.md), the
[report contract](../../templates/report-contract.md), and their tests. The active implementation
sequence is maintained in [the active execution plan](../exec-plans/active-evidence-driven-professional-narrative.md); the reader-facing behavior and staged
gates are defined in the
[product specification](../product-specs/evidence-driven-professional-narrative-report.md).

## Decision

SignalTrail will keep facts and analysis structurally separate while allowing one verified spoken
narrative to fuse them in presentation. The resulting style is professional storytelling:
evidence makes claims auditable, dialectical analysis exposes mechanisms and counterpositions,
and narrative ordering makes the material understandable without turning the schema into a spoken
checklist.

The immutable report and index remain the factual authorities. The professional narrative is a
new immutable downstream artifact with its own revisions and verification. It may explain and
rephrase authorized report content but cannot create a new source identity, upgrade evidence
access, alter freshness, modify the report, or become a continuity input before acceptance.

## Architectural invariants

1. Python owns identity, revision allocation, hashes, evidence authorization, freshness
   classification, state transitions, repair limits, validation, persistence, and downstream
   gates.
2. The storyteller model owns only chapter arrangement and natural spoken wording over a bounded
   authorized packet.
3. An independent verifier owns per-beat decisions but cannot edit a saved draft or allocate a
   revision.
4. Model outputs are untrusted drafts. External titles, summaries, articles, and webpages remain
   untrusted data and never change the contract or workflow.
5. Every accepted artifact is bound to upstream hashes. A changed report, index, contract, packet,
   script, or freshness decision invalidates dependent work.
6. A narrative failure cannot revoke a completed report. A media failure cannot revoke a verified
   narrative.
7. Unverified, rejected, stale, or hash-mismatched scripts cannot enter story-stream, TTS,
   subtitle, or video stages. Those stages accept only an explicit current verified-gate receipt.
8. Story-stream compilation, subtitle layout, video composition, and media QA are deterministic
   zero-model operations. TTS is separately metered if it uses an inference service.
9. Existing revisions are never overwritten. Rejected attempts remain evidence.
10. Token cost is measured in model tokens. Currency is optional telemetry, not an acceptance
    dimension.
11. Version 1 starts narrative authoring only from a fully `completed` report. A
    `completed_partial` report remains deliverable but is not eligible for narrative authoring
    until a later version defines evidence-completeness and spoken-degradation rules.
12. One public gate loader recursively validates list-form typed parent references, the active
    contract-bundle identity, and current admission before returning a typed capability. No reader
    or media entry point accepts a raw script, force flag, latest pointer, or partial beat subset.

## Proposed layer and dependency direction

The new Professional narrative layer sits after Report and before media projections. It may depend
on Foundation, Usage audit, Evidence, Context, Evaluation, and Report. Those lower layers do not
depend on it. Orchestration schedules it as an independently retryable post-report workflow.

~~~mermaid
flowchart LR
    R["Immutable report + index"] --> P["Bounded narrative packet"]
    P --> S["Storyteller draft"]
    S --> D["Deterministic validation"]
    D -->|valid| X["Immutable canonical script revision"]
    D -->|shared one-repair budget| Y["Targeted revised draft"]
    Y --> D2["Deterministic revalidation"]
    D2 -->|valid| X2["New immutable canonical script revision"]
    X --> V["Independent beat verifier"]
    X2 --> V2["Independent beat re-verifier"]
    V -->|pass| E["Immutable pass verification"]
    V -->|repair| Y
    V -->|reject| B["Blocked reader and media admission"]
    V2 -->|pass| E2["Immutable pass re-verification"]
    V2 -->|non-pass| B
    E --> G["Python-issued immutable gate receipt"]
    E2 --> G2["Python-issued immutable gate revision"]
    G --> C["Deterministic story-stream compiler"]
    G2 --> C
    C --> A["TTS + subtitle timing"]
    A --> M["Deterministic video renderer"]
    M --> Q["Rights + technical QA"]
~~~

Dependencies move only to the right:

- a script cannot update the report or index;
- verification cannot overwrite a draft;
- a canonical script exists before verification, and verification cannot create a second script;
- story-stream cannot rewrite narration;
- TTS and video cannot repair content;
- media retry cannot create a new fact or analysis; and
- a downstream failure changes only that downstream state.

## Component ownership

| Component | Owns | Forbidden responsibility |
| --- | --- | --- |
| Narrative packet builder | Minimal authorized event, evidence, analysis, freshness, and contract projection | Broad collection, arbitrary browsing, prose generation |
| Storyteller | Structured chapters and natural sentence-sized beats | IDs, hashes, evidence upgrades, freshness, verification, state, publication |
| Deterministic receiver | Schema, ID subsets, field ownership, language, evidence/access rules, time rules, hashes, repair budget | Semantic invention or silent correction |
| Independent verifier | Per-beat fact, time, attribution, causal, dialectical, uncertainty, and expression verdicts | In-place draft editing, revision allocation, publication |
| Narrative repository | Collision-safe revision allocation, immutable attempts/scripts/verifications/gate receipts, latest pointers | Source-of-truth report mutation |
| Verified-gate loader | Recursive typed-parent, data-root, file/semantic-hash, beat-set, pass-verification, and freshness admission; returns `VerifiedNarrativeBundle` | Raw-script admission, latest discovery, force/skip/allow-stale flags, repair, or publication |
| Story-stream compiler | Explicit-gate admission, verified beat-to-scene mapping, allowed media, credits, rights state, fallback, manifest hash | Raw script admission, directory discovery, new narration, facts, or analysis |
| TTS/subtitles | Engine and voice identity, license, audio hash, actual duration, word/segment timing, subtitle tracks | Text repair or news verification |
| Video renderer | Reproducible composition and technical receipt | Content selection, factual judgment, upstream state mutation |
| Orchestration | Independent scheduling, preflight, state, recovery, usage bindings, feature gates | Copying authoritative artifact bodies or token totals |

## Bounded authoring packet

The storyteller packet is derived from one current immutable report revision and its bound index.
Version 1 requires that report run to be `completed`, not `completed_partial`; this eligibility
check occurs before packet allocation and does not change delivery of an ineligible report.
It includes only:

- Version 1 `mode = edition_narrative` with six to ten featured events where available and final
  verified-claim coverage of at least 60% of all distinct report featured events;
- exact analysis-domain coverage `geopolitics = 1/1`, `ai_technology = 1/1`, and
  `markets = 1/1` through final claim-level registry references;
- at least one final `cross_perspective_synthesis` reference, or an immutable deterministic
  not-applicable receipt only when the canonical `cross_perspective_synthesis` field is absent or
  empty under a versioned deterministic rule; existing weak content cannot be judged subjectively
  immaterial;
- every excluded featured-event ID and one contract-enumerated exclusion reason;
- authorized item and event IDs;
- visible title, description, publication time, access status, and bounded content excerpts;
- structured facts, causal chains, assumptions, counterevidence, scenarios, invalidation signals,
  and watch signals from authorized analyses;
- cross-perspective synthesis only where it serves the selected central question;
- the target language, edition, time zone, `as_of`, freshness rules, and strict output schema; and
- hashes for the report, index, contract, policy, and packet.

It excludes the full ordinary-brief corpus, unrelated report prose, prior model conversations,
remote instructions, unselected evidence, cookies, credentials, raw host receipts, and any
Python-owned identity or status field. Metadata-only evidence carries only the text actually
observed. The packet builder records included and excluded counts so boundedness is reviewable.
Version 1 has no focused single-event or small-subset mode. Define:

~~~text
featured_event_coverage =
distinct report featured events referenced by final verified claim units
/
distinct featured events in the bound report
~~~

The denominator must be nonzero and acceptance requires `featured_event_coverage >= 0.60` plus
analysis-domain coverage `3/3`. Python derives the authoritative Claim-to-Event mapping only from
`sections[].items[].source_refs[].item_id -> sections[].items[].event_id` in the bound report. The
packet persists the result as sorted Python-owned `featured_event_evidence_membership[]` rows with
`item_id`, `event_id`, and `source_ref_sha256`, plus `membership_sha256`; the scope receipt binds
that hash. Claim validation, the current-event quota, and the 60% metric consume only this registry.
Each evidence item must map to exactly one featured event; zero, duplicate, or multiple matches
fail rather than being guessed. A multi-event claim counts every distinct event backed by one of
its mapped evidence items. Chapter `event_ids[]` are authorization scope only, must contain all
events mapped from their claims, and never increase the numerator.

## Structured narrative contract

A script contains one or more chapters. Each chapter serves exactly one central question or
falsifiable thesis and cites a coherent subset of current featured events and analysis identities.
Same date, same domain, or a broad topic label is not a causal connection.

The model submits sentence-sized beats rather than one independent long transcript. Python joins
accepted beat text in order to create the transcript, preventing a parallel prose field from
drifting away from structured evidence.

The planned root fields include:

~~~text
schema_version
script_id
script_revision
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
narrative_contract_sha256
narrative_packet_sha256
membership_sha256
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
as_of
timezone
frozen_at
language
hydrated_analysis_refs[]
chapters[]
~~~

`script_id`, `script_revision`, hashes, timestamps, and status are Python-owned. A generic script
field named `revision` is invalid. A chapter carries:

~~~text
chapter_id
chapter_title
central_question
core_thesis
event_ids[]
analysis_ref_ids[]
beats[]
~~~

Each beat carries:

~~~text
beat_id
kind
epistemic_status
text
evidence_item_ids[]
analysis_ref_ids[]
claim_units[]
assumptions[]
counter_evidence_item_ids[]
invalidation_signals[]
~~~

The packet owns an `analysis_reference_registry[]`. Each row has a stable `ref_id`,
`source_kind` (`analysis` or `cross_perspective_synthesis`), optional `analysis_id`, an exact RFC
6901 `json_pointer` into the bound immutable report, and a mandatory canonical `value_sha256`.
This one representation addresses scalar fields, array entries, nested object members, and
cross-perspective synthesis. The model emits only allowed `analysis_ref_ids[]`; Python resolves and
hydrates the full typed rows into the canonical script. A model cannot emit a path or hash.

The packet also owns sorted `featured_event_evidence_membership[]` rows with `item_id`, `event_id`,
and `source_ref_sha256`, derived only from
`sections[].items[].source_refs[].item_id -> sections[].items[].event_id`. Canonical JSON over the
sorted rows yields `membership_sha256`; the scope receipt and script bind it. Validators never
infer event membership from model prose, titles, chapter scope, or another report view.

Chapter-level analysis references define the authorized scope only. Beat- and claim-level
references are the proof for an inference and never replace item evidence for its factual
premises. Every fact-bearing or inferential beat contains atomic `claim_units[]` with a
Python-owned `claim_id`, exact deterministic `text_span.start` (inclusive) and `text_span.end`
(exclusive) measured in Unicode code points of the saved beat text,
`normalized_claim_sha256`, `epistemic_status`, `claim_type`, `criticality`,
`criticality_reason`, `evidence_item_ids[]`, `analysis_ref_ids[]`, `freshness_class`, and
`freshness_evidence_item_ids[]`.
`normalized_claim_sha256` is Python-derived from the exact slice under a versioned normalization
rule and cannot replace the span. Python rejects overlap, invalid offsets,
claim-bearing text outside the union of claim spans, and evidence items that do not map uniquely
to authorized report featured events. `claim_type` is one of `entity`, `action`, `time`,
`sequence`, `number`, `quotation`, `attribution`, `factual_premise`, `inference`, or `other`.
Python applies versioned type rules to mark deterministic critical units. The verifier may
escalate a noncritical unit to critical but cannot downgrade a Python-critical unit. Only a
claim-free transition may omit claim units. The nonempty union of Python-critical and
verifier-escalated units is the evidence-closure denominator; it is not guessed from a compound
sentence.

Python derives each claim's freshness class and sorted, duplicate-free publication-proof IDs from
that claim's direct evidence. `freshness_evidence_item_ids[]` is always a subset of the same
claim's `evidence_item_ids[]`; it cannot authorize evidence and is the only input to that claim's
freshness and current-event mapping.

The canonical script also stores sorted, unique `script_evidence_closure_item_ids[]` and
`script_evidence_closure_sha256`. Python computes their union from beat-, claim-, and
counter-evidence plus evidence reached transitively through every hydrated analysis reference. The
model cannot add, remove, or reorder closure members.

The transcript should normally realize these narrative functions:

~~~text
hook -> fact -> background -> mechanism -> analysis
-> counterpoint -> scenario -> watch_signal -> closing
~~~

The sequence is semantic, not a visible method outline. Natural transitions signal when the
speaker moves from confirmed material to attributed claims, inference, uncertainty, or scenario.

## Epistemic roles

The minimum enum is:

| Status | Meaning | Required boundary |
| --- | --- | --- |
| `confirmed_fact` | Supported current or historical fact | Authorized evidence and applicable publication time |
| `reported_claim` | A source's claim not independently promoted to fact | Explicit attribution and authorized evidence |
| `background` | Earlier material needed to explain the current event | Historical wording; never “just now” or “latest” |
| `supported_inference` | Reasoned judgment from authorized facts and analysis | Analysis references, assumptions, qualification, invalidation signals |
| `contested` | Materially conflicting evidence or interpretation | Both positions represented within observed evidence |
| `scenario` | Conditional future path | Trigger, horizon, observable signals, non-factual wording |
| `unknown` | Important unresolved point | Explicit uncertainty; no silent completion |
| `watch_signal` | Observable fact that can update a later judgment | Testable condition and downstream meaning |
| `transition` | Claim-free narrative bridge | Must not introduce a person, number, motive, time, quote, or other fact |

Hooks may be engaging but follow the same transition rule unless they bind supporting evidence.
The contract forbids invented dialogue, first-person experience, insider knowledge, psychology,
secret motive, quotation, chronology, or dramatic certainty.

## Evidence and access boundary

All evidence IDs are subsets of the current report's authorized featured-event evidence. A script
cannot cite an ordinary brief or another report revision merely because it exists locally.

Deterministic validation checks identity, subset, access status, and field ownership. The
independent verifier checks whether the evidence actually supports the wording:

- metadata-only evidence supports only what the observed title or public description states;
- `verification_required` material remains an attributed, unresolved claim;
- a number, date, entity, action, quotation, or attribution must match the bounded evidence;
- unbound analysis prose cannot become a factual source;
- a supported inference must expose its factual premises and analysis reference; and
- critical failures cannot be averaged away by high style scores.

## Freshness boundary

Every script has time-zone-aware `as_of`, a declared IANA `timezone`, and `frozen_at`. “Current
date” is the calendar date obtained from `as_of` in that timezone, and “yesterday” is its immediately
preceding calendar date; neither comes from the machine date or a source locale. Current-news
status derives only from valid `published_at` values under that rule. `collected_at` never grants
current status. Every claim unit, rather than every beat, carries one Python-validated
`freshness_class` from:

~~~text
current
background
undated
not_applicable
~~~

`current` requires a non-empty publication-proof set whose directly cited items all have valid
today/yesterday `published_at` values and no future time. `background` and `undated` require
non-empty directly cited proof sets matching their respective time class. Scenario or watch-signal
claims use `not_applicable` with an empty proof set; a claim-free transition has no claim unit and
no class. `pending` and `excluded` are workflow dispositions, not accepted claim freshness classes;
`unknown` remains an epistemic status. Undated material cannot use current-news language. Mixed
claim classes may coexist in one beat, but no beat-level label can transfer freshness between them.

`available_current_featured_event_count` counts distinct report featured events in the bound
membership registry with valid current-date/previous-date publication time under `as_of` and its
timezone and must be nonzero. `current_claim_candidate_count` counts all final claim units labeled
`current` before proof validation; `current_claim_count` counts the valid-proof subset, and their
ratio must be `100%`. The final verified script has `current_claim_count > 0` and references current
claims from at least
`min(2, available_current_featured_event_count)` distinct current featured events. Both the count
and event mapping use only each current claim's non-empty `freshness_evidence_item_ids[]`, and every
such ID must itself have valid today/yesterday `published_at` and map uniquely through the bound
membership registry. An old or undated item from an otherwise current event cannot count. The
verifier checks that the current wording is supported by those exact current proof items,
preventing a zero or borrowed time-compliance denominator.

The script permanently binds `bound_index_file_sha256`. Before reader or media admission, a
freshness preflight applies the 120-minute soft TTL and separately records `recheck_index_path`
and `recheck_index_file_sha256`. The recheck records the exact pinned
`item_fingerprint_policy_id` and `item_fingerprint_algorithm_version`.
Its duplicate-free checked item-ID set must equal `script_evidence_closure_item_ids[]` exactly, and
its checked source-ID set must equal the deterministic source set for those items exactly. Every
required item resolves uniquely, every old/new fingerprint is present and equal, and every required
source status is an allowed success status. Missing, foreign, duplicate, ambiguous, rate-limited,
challenged, `verification_required`, failed, or `no_items` results set admission to `blocked` and
cannot issue a gate. Any changed fingerprint or source membership/status requires a new
`completed` report, script, and full verification.

Python owns `script_hard_expiry_at` at the next configured edition-window boundary. The initial gate
uses `freshness_anchor_at = verified_at`; a renewed gate after unchanged evidence uses
`freshness_anchor_at = rechecked_at`. Every gate computes
`freshness_deadline_at = min(freshness_anchor_at + 120 minutes, script_hard_expiry_at)`. Admission
is half-open and requires both `clock < freshness_deadline_at` and
`clock < script_hard_expiry_at`. An unchanged recheck creates an immutable receipt followed by a
new gate revision only within those bounds and never extends hard expiry. Crossing the runtime
calendar date, evaluated in the script timezone against the `as_of`-anchored current date, while
relative current-news language is present requires a new `completed` report and script. The
expired gate is never mutated or reused.

## Dialectical and professional-analysis boundary

Each central thesis must expose:

- supporting facts and an intermediate causal mechanism;
- at least one authorized evidence item with access `partial` or `full_text`;
- material actors, interests, capabilities, constraints, and reactions;
- assumptions and evidence strength;
- the strongest authorized counterposition, or an explicit bounded statement that no material
  counterevidence was available in the authorized dossier;
- conditions that weaken or invalidate the judgment;
- only authorized scenarios, with triggers, horizons, and observables; and
- watch signals that a later report can resolve.

If the authorized analysis contains at least two materially different scenarios, the narrative
preserves at least two. If it contains one, it preserves that one and Python issues
`scenario_evidence_gap = only_one_authorized_scenario`. If it contains none, the storyteller
invents none and Python records
`scenario_not_applicable_reason = no_authorized_scenario_evidence`. Metadata-only evidence may
support attributed background but cannot be the sole support for a chapter's core thesis.

This does not force artificial equal weight. It prevents the storyteller from hiding material
counterevidence or using a token “on the other hand” sentence that cannot change the thesis.
Professionalism comes from traceable mechanism, calibrated conclusion strength, and falsifiability,
not jargon density. Correlation cannot silently become causation; a single example cannot silently
become a trend; short-term shock and structural change remain distinct.

## Verification architecture

The verifier uses a separate task/session and role, without the storyteller's hidden conversation.
Its immutable dossier binds:

~~~text
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
report_contract_sha256
narrative_contract_sha256
storyteller_policy_sha256
verifier_model_policy_id
verifier_output_schema_sha256
narrative_packet_sha256
script_sha256
as_of
timezone
~~~

`verifier_model_policy_id` resolves to a versioned allowlist of served models and required
capabilities: receiver-enforced structured output, sufficient context for the bounded dossier, an
independent session, and exact usage observability. An unknown model, fallback outside the
allowlist, or changed model/prompt/policy/contract blocks G3 and requires the frozen red-team suite
to pass again.

The Version 1 suite is exactly 32 canonical cases: 8 factual/evidence, 8 time/freshness,
8 epistemic/causal/dialectical, 4 prompt-injection/authority-escalation, and exactly 4 clean
controls. The expected-defect registry has nonzero critical and noncritical populations, and every
expected defect enters the applicable denominator. Each of two independent runs requires 100%
critical recall, at least 90% noncritical recall, and exactly 4/4 clean passes, without pooling.
Changing or extending the suite creates a new versioned policy.

It contains the script plus only the evidence and analysis rows needed to judge submitted beats.
Every beat receives exactly one `pass`, `repair`, or `reject` verdict with:

~~~text
factual_support
temporal_accuracy
attribution
access_boundary
fact_analysis_separation
claim_unit_completeness
causal_support
dialectical_completeness
uncertainty_language
narrative_integrity
professional_clarity
compliance_boundaries
~~~

Fact, time, attribution, access, fact/analysis separation, claim-unit completeness, and compliance
are Boolean hard gates. `claim_unit_completeness` requires the verifier to confirm that every
independently falsifiable factual or inferential assertion appears in a claim unit. Subjective
narrative dimensions cannot override a hard failure.

The verification artifact also contains `script_rubric_scores[]` and
`chapter_rubric_scores[]`; the latter has exactly one row for every script `chapter_id` and no
foreign or duplicate row. The script set and every chapter set contain each dimension exactly
once. Every dimension is an integer from 1 to 5 and includes a finding plus
`evidence_beat_ids[]`:

~~~text
dialectical_rigor
narrative_coherence
professional_clarity
epistemic_transparency
restraint_and_non_sensationalism
~~~

Every whole-script and per-chapter verifier score must be at least 4; no aggregate or cross-chapter
average can hide a lower dimension. Human acceptance uses a two-stage blind protocol. Before
creating reviewer-readable material, Python obtains a 256-bit nonce from the operating-system
CSPRNG and withholds it outside all reviewer-readable artifacts until reveal. Versioned
`commitment_scheme_id` and `canonicalization_id` values define a domain-separated
SHA-256 commitment over the nonce, `verification_sha256`, rubric hash, and canonical hidden score
payload containing both score arrays.

Python first creates immutable `<run-id>-blind-review-dossier.json`. It contains only an opaque
verification hash and the commitment: no resolvable verification path, embedded verification
artifact, latest pointer, nonce, or verifier score. The reviewer receives only that dossier and
writes immutable `<run-id>-human-review.json` with `reviewer_id`, dossier hash,
`review_started_at`, `scores_locked_at`, the same five independently chosen scores, and rationale.
Only after lock may Python create `<run-id>-score-reveal.json`, binding the human receipt and
revealing the nonce, verifier scores, verification path/hash, and `scores_revealed_at`. Acceptance
recomputes the commitment and requires
`review_started_at <= scores_locked_at <= scores_revealed_at`. This audits what the workflow
withheld; it does not claim knowledge of information a reviewer obtained outside the system. Every
human score must also be at least 4. The two score sets cannot be averaged together.

The verifier writes only an immutable decision and bounded repair instructions. One repair is
shared across deterministic and semantic rejection for one story attempt. A deterministic
rejection records an immutable draft/rejection receipt but allocates no canonical script revision.
Only a deterministically accepted draft becomes canonical `sN`. A verifier-requested repair
creates a new draft and, after full deterministic acceptance, canonical `sN+1`, followed by full
independent re-verification. A second non-pass result becomes `rejected`.

After the final `pass`, Python derives a separate immutable verified-gate receipt with at least:

~~~text
decision = pass
schema_version
data_root_identity
report_id
report_content_hash
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
script_id
script_revision
script_sha256
verification_sha256
verified_at
freshness_anchor_at
freshness_deadline_at
script_hard_expiry_at
verified_beat_ids[]
parents[]
~~~

`parents[]` is always a list whose rows are exactly
`{parent_kind, path, file_sha256, semantic_hash?}`; `path` is canonical and relative to the
validated data root. An initial gate contains exactly one parent kind each for `report`,
`bound_index`, `contract_bundle`, `packet`, `scope_receipt`, `script`, `verification_dossier`, and
`verification`. A renewed gate contains those same eight plus exactly one `prior_gate` and one
`freshness_recheck`. Missing, foreign, or duplicate kinds fail. The loader also requires the
contract bundle to equal the active configured identity. Gate issuance requires exact,
duplicate-free set equality among script beat IDs, verification beat IDs, pass beat IDs, and
`verified_beat_ids[]`; a requested subset is insufficient. The receipt is a minimal downstream
admission capability, not a copied script. A non-pass decision, half-open deadline failure,
corruption, or parent/hash/beat mismatch cannot produce or reuse a gate.

## State and recovery

Narrative content state is nested under the report run but does not change or recalculate the
report's completion:

~~~text
not_requested
-> pending
-> authoring
-> draft_persisted
-> deterministic_validation
-> script_accepted
-> verification_pending
-> verifying
-> verified | repair_required | rejected | failed

repair_required -> repairing -> draft_persisted (one shared repair only)
~~~

`verified` is terminal for the semantic content of one script revision; expiry does not rewrite it
as stale. Admission, reader projection, story-stream, and video retain separate retryable states:

~~~text
admission current | recheck_pending | expired | blocked
reader pending -> rendering -> ready | partial
story pending -> compiling -> ready | blocked | partial
video pending -> rendering -> completed | partial | failed
~~~

Recovery revalidates file identity and hashes before advancing. Matching completed inputs return
`already_completed` without a new model call. A persisted draft or verification is adopted only
when every identity matches. Concurrent revision allocation has one winner; other writers read the
winner or receive a clear collision. Corruption, mismatched hashes, conflicting task identity, or
exhausted repair budget fails visibly and never overwrites.

Every new narrative artifact carries `schema_version`, `artifact_id`, `artifact_kind`,
`data_root_identity`, a canonical path relative to the validated data root, and list-form typed
`parents[]` rows `{parent_kind, path, file_sha256, semantic_hash?}`. Keyed parent maps, absolute
paths, bare IDs, and directory discovery are invalid. An artifact's own `<kind>_sha256`, including
any digest used in its filename, is the semantic hash of its versioned canonical
`semantic_payload`; that payload excludes the persistence envelope, the artifact's own digest,
complete-file bytes, and path. A `parents[].file_sha256` instead hashes the complete persisted bytes
of that parent, and an artifact never embeds its own `file_sha256`. Consequently the
`contract-bundle-sha256` filename component and contract-bundle identity are semantic hashes, not
complete-file byte hashes. The only public loader,
`load_verified_narrative_gate(gate_path, data_dir, clock) -> VerifiedNarrativeBundle`, recursively
reopens and validates the exact gate parent closure and requires its immutable contract bundle to
equal the active configured identity. There is no `force`, `skip_verification`, raw-script,
allow-stale, or latest-file variant. Run manifests store only checked current references and hashes
under `professional_narrative.{current_script,current_verification,current_gate}`.

## Artifact authority

Planned paths are shown as code because they do not exist yet:

| Artifact | Mutability | Authority |
| --- | --- | --- |
| `narratives/contracts/<policy-id>/<contract-bundle-sha256>.json` | Immutable | Active contract-bundle snapshot and identity for all schemas, policies, and deterministic rule versions |
| `narratives/packets/<report-id>-aN.json` | Immutable | Authorized bounded storyteller input plus analysis-reference and featured-event membership registries |
| `narratives/scope-receipts/<report-id>-aN.json` | Immutable | Selected/excluded event coverage, membership hash, 3/3 domains, and synthesis applicability |
| `narratives/drafts/<report-id>-aN.json` | Immutable | Submitted model authoring attempt; not yet a canonical script |
| `narratives/validation-receipts/<report-id>-aN.json` | Immutable | Deterministic decision, failing paths/rules, and remaining repair authorization |
| `narratives/scripts/<report-id>-sN.json` | Immutable new revision | Canonical structured spoken script |
| `narratives/verification-dossiers/<report-id>-sN-vN.json` | Immutable | Minimal exact-script verifier input and recursive parent closure |
| `narratives/verifications/<report-id>-sN-vN.json` | Immutable new revision | Independent per-beat decision |
| `narratives/repair-receipts/<report-id>-sN-vN.json` | Immutable | Semantic non-pass decision, bounded repair instruction, and remaining repair authorization |
| `narratives/freshness-rechecks/<report-id>-sN-fN.json` | Immutable new revision | Exact evidence-closure/source-set comparison under the pinned fingerprint policy after TTL expiry |
| `narratives/verified/<report-id>-sN-gN.json` | Immutable new revision | Exact-parent current gate over a pass verification or successful unchanged recheck |
| `narratives/projections/<report-id>-sN-gN-pN.md` | Immutable paired revision | Canonical reviewable projection bound to exactly one gate |
| `narratives/projections/<report-id>-sN-gN-pN.html` | Immutable paired revision | Safe local projection bound to the identical gate and semantic payload |
| `narratives/acceptance/<policy-id>/<run-id>.json` | Immutable | Fixture, red-team, real-run, recovery, and Token acceptance evidence |
| `narratives/acceptance/<policy-id>/<run-id>-blind-review-dossier.json` | Immutable | Score/nonce/path-withheld input with opaque verification hash and commitment |
| `narratives/acceptance/<policy-id>/<run-id>-human-review.json` | Immutable | Named human five-dimension scores locked against the blind dossier |
| `narratives/acceptance/<policy-id>/<run-id>-score-reveal.json` | Immutable | Post-lock nonce/score/path reveal chronology and commitment check |
| `story-streams/<report-id>-sN-cN.json` | Immutable new revision | Deterministic scene manifest |
| `audio/<report-id>-sN/manifest-tN.json` | Immutable new revision | TTS, timing, subtitle, and audio lineage |
| `videos/<report-id>-sN/render-N.json` | Immutable new revision | Renderer inputs, output hashes, and QA |

`aN`, `sN`, `vN`, `fN`, `gN`, `pN`, `cN`, `tN`, and render numbers are distinct authoring-attempt,
script, verification, freshness, gate, projection, compilation, TTS/audio, and render identities;
report IDs already contain the report revision and are not suffixed with an ambiguous second `rN`.
Mutable run manifests store references and scheduler state, not copied script bodies or token totals.
Latest pointers are
atomic derived views and never override immutable revisions or select a reader/media input.

## Story-stream and media boundary

Reader projection uses one deterministic function,
`narrative_projection_semantic_payload(bundle: VerifiedNarrativeBundle) -> dict`. Every public
reader command accepts `verified_gate_path`, invokes
`load_verified_narrative_gate(verified_gate_path, data_dir, clock)`, and passes only its returned
bundle. No reader API accepts raw script, verification, or gate objects. Markdown and HTML consume
and embed the same canonical semantic JSON in an immutable paired
`<report-id>-sN-gN-pN.md|html` revision. Acceptance extracts and compares those payloads exactly;
string-containment assertions do not prove semantic equivalence.

Reader projection and compilation accept only a `VerifiedNarrativeBundle` returned by the public
gate loader. They do
not accept a raw `script_path`, does not scan a directory for the newest file, and has no force or
skip path. The loader recursively recomputes every parent identity and hash, validates the data
root and active contract bundle, requires exact equality of the complete
script/verification/gate beat sets, and checks the half-open gate or freshness-recheck gate
deadline. Story-stream covers every script beat exactly
once in original order unless a new immutable cut/script is independently verified; callers
cannot request an arbitrary subset.

Gate loading is G7 admission only. Scene hashes, rights, and text-card fallback cannot be checked
until deterministic compilation has produced the scene manifest; those post-compilation checks
belong to M1 and cannot be moved into a circular pre-compilation gate.

Scene schema is discriminated:

~~~text
media_asset:
  scene_type = media_asset
  image_sha256 required
  rights_status = owned | licensed | public_domain

text_card:
  scene_type = text_card
  image_sha256 absent
  fallback_reason required
~~~

Publicly reachable media is not automatically licensed for public video. Rights status
`unknown` or `rejected` is permitted only on rejected candidates and selects an allowed asset or
text card. The first media MVP uses licensed
static images, one licensed TTS voice, source credits, and subtitles. Source-video ingestion,
voice cloning, and rights-unknown music are excluded.

M1 acceptance requires gate-beat coverage 100%, missing/duplicate/foreign beats 0, selected
unsafe-rights media 0, compiler model calls 0, and semantic-hash mismatches for identical inputs
0.

TTS records engine, version, voice, license, configuration, usage, audio hash, and actual timing.
Subtitle and scene timing derive from actual audio duration. Video records codec, resolution,
frame rate, bitrate, fonts, color settings, input hashes, output hash, and technical QA. Rendering
failure leaves report and verified script valid; video cannot omit, duplicate, or reorder a spoken
beat.

## Token and call boundary

The model phases are separately metered:

~~~text
professional-narrative-storyteller
professional-narrative-repair
professional-narrative-verifier
professional-narrative-reverification
~~~

The logical ceiling is one initial storyteller task, one initial verifier task, zero or one
targeted repair, and zero or one re-verification. Runtime may persist exact, estimated,
lower-bound, or incomplete observations, and missing usage remains unknown rather than zero.
Formal acceptance requires every executed story phase to have `coverage = complete`,
`tokens.accounted_total.quality = exact`, a non-negative integer
`tokens.accounted_total.value`, zero open calls, zero conflicts, non-overlapping totals, and
bindings to the current report and script. All four phase rows exist. An uncalled
repair/re-verification phase has value `0` and exact quality only when deterministic scheduler
evidence proves zero provider calls. Currency is outside the savings gate.

The executable pipeline total sums numeric measurement values, never aggregate-measurement
objects:

~~~text
story_pipeline_tokens =
phase["professional-narrative-storyteller"].tokens.accounted_total.value
+ phase["professional-narrative-verifier"].tokens.accounted_total.value
+ phase["professional-narrative-repair"].tokens.accounted_total.value
+ phase["professional-narrative-reverification"].tokens.accounted_total.value
~~~

Version 1 pre-freezes a provisional `250_000` accounted-token ceiling for the complete story
pipeline, but the local ceiling cannot bypass the existing global budget. Every preflight satisfies:

~~~text
story_pipeline_tokens <= 250_000
AND global_observed_accounted_tokens
    + remaining_narrative_phase_reserve_tokens
    + downstream_required_reserve_tokens
    <= budget.max_agent_tokens
~~~

Neither ceiling can be raised after a run begins. Three accepted editions may inform only a
versioned next-run ceiling.

Packet construction, validation, persistence, story-stream compilation, subtitle layout, video
rendering, and QA make zero model calls. Real-run baselines report pipeline total and explicitly
named normalized ratios:

~~~text
normalized_tokens_per_chapter = story_pipeline_tokens / accepted_chapter_count
normalized_tokens_per_verified_beat = story_pipeline_tokens / verified_beat_count
normalized_tokens_per_selected_event =
    story_pipeline_tokens / distinct_selected_featured_event_count
normalized_tokens_per_1000_final_zh_characters =
    story_pipeline_tokens * 1000 / final_zh_han_character_count
normalized_tokens_per_final_spoken_minute =
    story_pipeline_tokens / (actual_audio_duration_ms / 60_000)
~~~

`final_zh_han_character_count` counts only NFC-normalized Unicode Han-script code points in final
spoken Chinese, excluding whitespace, punctuation, markup, the Evidence Drawer, and metadata. The
implementation manifest pins the Unicode-property library and Unicode-data version.
`actual_audio_duration_ms` is the measured positive final TTS duration. Every denominator must be
positive; a zero denominator is `not_applicable`, never zero. These ratios are not provider phase
attribution.

## Security and privacy

- External content remains data, never instruction.
- Storyteller and verifier receive no browser, shell, delegation, credential, cookie, or raw-host
  access unless a later audited design explicitly requires it.
- Persisted packets contain bounded report evidence, not prompts, hidden reasoning, raw sessions,
  tool arguments, or secrets.
- HTML escapes all untrusted text and accepts only safe local or allowed source links.
- Generated scripts cannot grant media rights or alter source access classification.
- Usage accounting stores allowlisted metrics and hashed lineage under the existing privacy
  boundary.

## Implementation impact

The proposed implementation is expected to add focused schema, narrative, verification,
story-stream, and later media modules plus tests. Existing report schema and current architecture
remain authoritative until those changes land. At implementation time, update the top-level
architecture, report/user contracts, runtime policy, Skill procedure, packaging allowlist, examples,
and English/Chinese records in the same verified change.

## Verification map

| Boundary | Planned primary tests |
| --- | --- |
| Packet allowlist, canonical membership registry, script evidence closure, epistemic and `as_of`/timezone rules | `test_professional_narrative.py` |
| Verifier dossier, per-beat verdicts, repair, exact recheck closure, half-open stale/hash gates | `test_narrative_verification.py` |
| Contract bundle, exact list-form gate parents, immutable revisions, idempotence, concurrency, recovery | `test_architecture.py` |
| Bundle-only reader admission, paired `pN` HTML/Markdown semantic equivalence, safe rendering | `test_desktop_delivery.py` |
| Usage binding, Token budget, open-call and replay behavior | `test_llm_usage.py`, `test_llm_budget.py` |
| Story scenes, media hashes, rights, deterministic fallback | `test_story_stream.py`, `test_media.py` |
| Packaging and bilingual documentation | `test_hermes_package.py`, `test_docs.py` |

Acceptance fixtures also cover absent/empty versus weak synthesis, OS-CSPRNG blind-score nonce
withholding and reveal, commitment recomputation, inactive contract bundles, missing/foreign/
duplicate gate parents, recheck access failures, and reader/raw-object bypass attempts.

This Draft becomes Verified only after schemas, Python state and persistence, independent
verification, tests, user-facing projections, recovery evidence, Token measurements, and the
staged real-run criteria in the product specification all agree.
