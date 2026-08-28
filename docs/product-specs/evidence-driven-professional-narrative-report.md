# Evidence-Driven Professional Narrative Report Product Specification

**Purpose:** Define the user-visible narrative structure, evidence and dialectical requirements,
freshness rules, professional-quality expectations, and staged acceptance criteria for report,
story-stream, and video outputs.
**Status:** Draft
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

This specification defines a proposed capability. It does not claim that the current runtime can
generate or verify a professional narrative, story stream, TTS track, or video. The cross-module
design is in [the architecture record](../design-docs/evidence-driven-professional-narrative-report.md);
the delivery sequence is in [the active execution plan](../exec-plans/active-evidence-driven-professional-narrative.md).

## Product outcome

For one already validated immutable daily-report revision, SignalTrail produces one immutable
professional narrative that:

- combines news explanation with the report's three analytical perspectives into a coherent
  storytelling-style spoken text;
- preserves structured boundaries between evidence, background, attributed claim, inference,
  counterposition, scenario, uncertainty, and watch signal;
- explains actors, incentives, constraints, causal mechanisms, assumptions, and invalidation
  conditions without turning the method into a spoken field list;
- remains fully traceable to the current report and index;
- receives an independent per-beat LLM verification;
- is published to reader projections only after deterministic and independent verification; and
- exposes one explicit verified gate receipt as the only acceptable input to future story-stream
  and video work.

The product is professional storytelling, not fictional dramatization. Narrative devices improve
comprehension; they do not authorize invented facts, dialogue, motives, chronology, quotations,
insider knowledge, or certainty.

## Audience promise

After listening to or reading one chapter, a reader should be able to answer:

1. What happened?
2. Which parts are confirmed, attributed, historical, inferred, contested, or unknown?
3. Why did it happen, through what intermediate mechanism?
4. Which actors benefit, pay, constrain, or can change the result?
5. What is the strongest material alternative explanation or counterevidence?
6. Which assumptions support the current judgment?
7. What would weaken or invalidate that judgment?
8. Which observable signals should a later report check?

The main reading experience is one fused narrative, not a repeated “news explanation” followed by
three restated analysis essays. Evidence and argument details may be expandable, but source name,
publication time, epistemic status, `as_of`, and verification state remain visible.

## Scope

### Narrative MVP

The MVP includes:

- bounded packet construction over featured events and authorized analyses;
- structured chapters and sentence-sized beats;
- deterministic schema, evidence, access, freshness, and cross-field validation;
- independent per-beat verification and one total targeted repair;
- immutable script, verification, and verified-gate artifacts;
- HTML and Markdown reader projections over the same semantic payload;
- idempotence, concurrency, interruption, stale-revision, and projection-failure recovery;
- runtime preservation of exact or explicitly incomplete Token usage for every model phase, while
  formal G4 acceptance requires exact, complete phase coverage; and
- a tested hard block preventing non-verified content from entering media stages.

The MVP does not require TTS or MP4 output. It does require the media gate contract so later phases
cannot bypass verification.

### Later media phases

Story-stream adds a deterministic rights-aware scene manifest and contact-sheet preview. Video adds
licensed TTS, actual timing, subtitles, reproducible rendering, and media QA. Source-video
ingestion, voice cloning, background music, and rights-unknown assets remain outside the first
video MVP.

## Reader-facing structure

A chapter serves exactly one central question. The natural order may vary, but the completed
script must make these functions identifiable:

~~~text
hook
-> confirmed or attributed event
-> necessary background
-> actors, interests, and constraints
-> intermediate causal mechanism
-> current judgment
-> strongest counterposition or evidence gap
-> conditional scenarios
-> invalidation conditions
-> observable watch signals
-> closing
~~~

The UI does not need to print these method names. Spoken epistemic transitions must nevertheless
make facts and judgment distinguishable with target-language wording equivalent to “confirmed”,
“according to”, “one supported interpretation”, “this assumes”, “if”, and “not yet verified”.

Hooks may create curiosity but cannot introduce a new person, organization, action, number,
quotation, motive, date, or causal claim without evidence. A closing “hook” must be an observable
watch signal, not unsupported suspense.

## Acceptance model

Eight hard gates are independent. No aggregate score can compensate for a failed gate.

| Gate | Decision | Required threshold |
| --- | --- | --- |
| G0 — Upstream binding | Is the script bound to one valid current completed report/index/contract? | Run `completed`; report `0 errors / 0 warnings`; every declared hash matches |
| G1 — Evidence and freshness | Is every critical claim supported and timely at its declared role? | Critical-claim evidence closure `100%`; current-claim time compliance `100%`; critical errors `0` |
| G2 — Dialectical professional narrative | Does each thesis explain mechanism, counterposition, conditions, and observables in a coherent story? | Every structural hard rule passes; each human/verifier rubric dimension `>= 4/5` |
| G3 — Independent verifier | Did an isolated verifier cover every beat and clear all critical checks? | Final `pass` for every beat after at most one repair |
| G4 — Token cost | Is the accepted pipeline completely attributable and inside a pre-frozen Token budget? | Exact complete non-overlapping totals, open calls `0`, conflicts `0`, local/global budgets not exceeded |
| G5 — Immutability and recovery | Can identical, changed, concurrent, interrupted, and stale work be handled without overwrite or duplicate calls? | All deterministic recovery cases pass; identical replay adds `0` model calls |
| G6 — Reader projections | Do HTML and Markdown present the same verified semantic content safely? | Sole payload hash matches `2/2` projections; unsafe rendering defects `0` |
| G7 — Media gate | Are all draft, rejected, stale, damaged, or mismatched inputs blocked? | Unauthorized downstream acceptance `0` |

## G0 — Upstream and identity gate

An accepted script binds:

~~~text
report_id
report_content_hash
report_file_sha256
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
report_contract_sha256
narrative_contract_sha256
storyteller_policy_sha256
narrative_packet_sha256
as_of
timezone
~~~

Requirements:

- Version 1 accepts only upstream run status `completed`; `completed_partial` and every
  non-terminal or failed report status are blocked even if selected rows appear usable;
- the bound report passes the current validator with exactly `0 errors / 0 warnings`; a reviewed,
  waived, or “non-critical” warning is still a G0 failure;
- every SHA-256 recomputes from the referenced local file or semantic payload;
- `contract_bundle_identity` and `contract_bundle_sha256` resolve to the active configured immutable
  contract-bundle snapshot;
- `as_of` is an ISO timestamp with an explicit time zone;
- the packet includes only allowed featured events, analyses, synthesis, and evidence;
- external content remains data and cannot alter tasks, schemas, policies, or tools;
- Python assigns IDs, revisions, hashes, timestamps, freshness, and states;
- the model output schema denies unknown and Python-owned fields at every nested level; and
- any changed report, index, contract, policy, packet, or time-bound evidence creates a new script
  identity and invalidates prior verification.

Narrative, reader, story-stream, audio, or video outcomes never recompute, downgrade, or revoke the
authoritative report run status. A later version may define bounded `completed_partial` admission,
but Version 1 has no such exception.

### Version 1 edition scope

Version 1 has exactly one authoring mode, `mode = edition_narrative`; it has no focused-event or
small-subset escape mode. The canonical script binds `bound_index_file_sha256`, and every chapter
has one non-empty `central_question` that is answered by that chapter's ordered beats. Same-day,
same-domain, or broad-topic similarity does not satisfy this relationship.

When the report has at least six featured events, the packet selects six to ten. When it has one
to five, the packet selects all of them. A report with zero featured events is ineligible. Every
unselected featured event has one immutable `excluded_event_id` plus a contract-enumerated
exclusion reason. Define:

~~~text
featured_event_coverage =
distinct bound-report featured-event IDs referenced by final verified claim units
/
distinct featured-event IDs in the bound report
~~~

Python derives the only authoritative membership source from the canonical report path
`sections[].items[].source_refs[].item_id -> sections[].items[].event_id`. The packet persists the
complete Python-owned registry and its canonical hash:

~~~text
featured_event_evidence_membership[]:
  item_id
  event_id
  source_ref_sha256
membership_sha256
~~~

Rows are canonically sorted. Each `source_ref_sha256` binds the exact canonical source-ref row, and
`membership_sha256` binds the complete ordered registry. A source item must map to exactly one
featured-event ID; duplicate rows, one item mapped to several events, a missing membership, or a
hash mismatch fails packet validation instead of being guessed. The immutable scope receipt has a
typed packet parent and binds `membership_sha256` without copying the registry. Claim validation,
the current-news quota, and the 60% coverage metric consume this registry only; no chapter field or
alternative event-inference rule can create membership. A claim maps to each event for which it
cites at least one uniquely owned evidence item, and a multi-event claim counts several events only
when it carries separate uniquely mapped evidence for each. Chapter `event_ids[]` authorize scope
but never create coverage, and any claim/evidence/chapter-event mismatch fails.

The denominator must be nonzero and `featured_event_coverage >= 0.60`. Final claim-level registry
references must cover the analysis domains `geopolitics`, `ai_technology`, and `markets` exactly
`3/3`, with at least one reference to each domain. Merely listing a domain at chapter level does
not count.

The final verified claim set also contains at least one exact
`source_kind = cross_perspective_synthesis` registry reference. The only alternative is an
immutable Python-issued not-applicable receipt proving that the bound report's validated synthesis
field is absent or empty under a versioned deterministic rule. The receipt binds the report and
index hashes, inspected JSON Pointer, rule ID, `decision = not_applicable`, and a contract-enumerated
reason. Existing weak, brief, inconvenient, or low-confidence synthesis cannot be subjectively
declared immaterial; if the canonical field is present and non-empty, an exact registry reference
is mandatory. A storyteller assertion that synthesis is irrelevant is not a receipt.

Every chapter must include at least one final verified claim whose evidence has access status
`partial` or `full_text`. Metadata-only or `verification_required` evidence may supplement that
claim under its declared boundary, but cannot satisfy this chapter-level evidence-depth gate.

## G1 — Evidence gate

### Critical-claim evidence closure

Define:

~~~text
critical-claim evidence closure =
critical claims with sufficient authorized evidence
/
all critical claims
~~~

The candidate claim registry is the set of Python-validated `claim_units[]` in the canonical
script; the closure denominator is finalized after criticality classification and verifier
escalation. Every fact-bearing, attributed, contested, or inferential beat decomposes each
independently falsifiable assertion into a claim unit containing:

~~~text
claim_id
text_span.start
text_span.end
normalized_claim_sha256
epistemic_status
claim_type
criticality
criticality_reason
evidence_item_ids[]
analysis_ref_ids[]
freshness_class
freshness_evidence_item_ids[]
~~~

Python owns `claim_id` and `normalized_claim_sha256`. `text_span.start` is inclusive and
`text_span.end` is exclusive, using Unicode code-point offsets into the exact saved beat text.
Every non-empty span must be in range and must identify the exact Claim wording.
`normalized_claim_sha256` is derived from that slice under the versioned normalization algorithm;
normalized text or its checksum can never substitute for the exact start/end locator. Claim-bearing
text cannot sit outside a claim unit, and one compound sentence cannot hide several critical
claims behind one shared citation set.

`claim_type` is exactly one of `entity`, `action`, `time`, `sequence`, `number`, `quotation`,
`attribution`, `factual_premise`, `inference`, or `other`. `criticality` is `critical` or
`noncritical`; `criticality_reason` is non-empty and cites the applicable versioned classification
rule. Python applies deterministic type rules first. The verifier may escalate a Python
`noncritical` unit to `critical` with a claim ID, reason, and failed-check mapping, but cannot
downgrade a Python-critical unit. Each escalation is persisted in
`verification.claim_criticality_escalations[]` as `claim_id`, `from = noncritical`,
`to = critical`, `reason`, and `failed_checks[]`; an unregistered escalation or any downgrade
fails the receiver.

Python derives `freshness_class` and the sorted, duplicate-free
`freshness_evidence_item_ids[]` from the claim's direct `evidence_item_ids[]`; neither field can
authorize new evidence. The proof IDs are always a subset of that same claim's direct evidence and
are the only IDs allowed to establish its publication-time class or current-event membership.

Critical claims include:

- identity of a person, organization, product, document, or place;
- an action that occurred or did not occur;
- time, sequence, number, percentage, price, amount, or range;
- direct or indirect quotation;
- attribution of a policy, filing, announcement, research result, or reported claim;
- a factual premise that materially changes the central judgment.

The required closure is `100%`. Its denominator is the non-empty union of Python-critical and
verifier-escalated units. Evidence IDs must exist in the bound index and be a subset of the current
report's authorized featured-event evidence. A locally present ordinary brief, old report, or
model-created ID is not authorized.

Rules by epistemic status:

- `confirmed_fact` has supporting evidence and cannot rely solely on `verification_required`;
- `reported_claim` retains explicit attribution and is not promoted to independent fact;
- `background` has evidence and unmistakably historical wording;
- `supported_inference` has an analysis reference and evidence supporting its premises;
- `contested` represents material conflict actually present in the bounded evidence;
- `scenario` is conditional rather than factual;
- `unknown` remains unresolved;
- `watch_signal` is objectively observable later;
- `transition` contains no factual claim.

The packet carries a Python-built `analysis_reference_registry[]`. Each entry has an allowlisted
`ref_id`, `source_kind`, an exact RFC 6901 `json_pointer` into the bound report, and a mandatory
`value_sha256`; `analysis_id` is present when applicable. It can address scalar, array, nested
stakeholder, and cross-perspective-synthesis values uniformly. The storyteller emits only
`analysis_ref_ids[]` from this registry and never creates a pointer or hash.

Chapter-level analysis refs define authorized scope only. A `supported_inference` closes its
analysis premise only with claim-unit or beat-level exact refs, and those refs never replace
evidence IDs for factual premises.

Metadata-only evidence supports only the observed title or public description. A script cannot
expand it into unseen details. Important entities, numbers, dates, quotations, and attributions
must match evidence semantically; one critical mismatch fails G1.

`claim_unit_completeness` is a Boolean critical verifier check. It passes only when every
independently falsifiable factual, attributed, contested, or inferential span in every beat is
covered by one or more non-overlapping valid claim units, every claim unit points to its exact
saved span, and claim-free transitions contain no hidden claim. A missing or compound-hidden claim
returns the exact uncovered span and a `repair` or `reject`; it can never be averaged into a style
score.

## Freshness gate

Every claim unit has exactly one Python-validated `freshness_class` from:

| Class | Accepted meaning |
| --- | --- |
| `current` | Non-empty direct proof set whose items have valid `published_at`; each local date is the `as_of` date or previous date and no time is later than `as_of` |
| `background` | Non-empty direct proof set with valid older publication time, expressed unambiguously as historical context |
| `undated` | Non-empty direct proof set whose publication time is missing or invalid; never expressed as current and never used to close a current claim |
| `not_applicable` | Conditional scenario or watch signal for which publication freshness does not apply; proof set is empty |

`pending` and `excluded` are workflow dispositions, not accepted claim freshness classes;
`unknown` is an epistemic status. A claim-free transition has no claim unit and therefore no
freshness class. A future publication time is rejected rather than silently reclassified.
`collected_at` never grants current status, historical or undated material cannot use “just now”,
“latest”, or “today happened” language, and `verification_required` remains an attributed
unresolved claim. A beat may contain claim units of different classes; no beat-level label can
promote one claim or supply another claim's publication proof.

Define `available_current_featured_event_count` as the number of distinct bound-report featured
events with at least one valid today/yesterday `published_at`, where today/yesterday is computed
from `as_of` in the configured `timezone`.
`current_claim_candidate_count` is the number of final claim units labeled `current` before the
time-proof gate. `current_claim_count` is the number of those units whose non-empty
`freshness_evidence_item_ids[]` passes the rule above. A current claim
maps to a featured event only through one of those exact proof IDs and the bound
`featured_event_evidence_membership[]` registry; the referenced item itself must carry the valid
today/yesterday `published_at`. Old, undated, beat-level, chapter-level, or merely same-event
evidence cannot enter that mapping. The independent verifier must confirm that the current wording
is supported by the current proof item rather than only by another historical item.
Version 1 requires:

~~~text
available_current_featured_event_count > 0
distinct current featured events referenced by final verified claim units
    >= min(2, available_current_featured_event_count)
current_claim_count > 0
current-claim time compliance =
    current_claim_count / current_claim_candidate_count = 100%
~~~

Therefore the current-news quota and its compliance denominator are never zero.

The canonical script stores a frozen evidence closure:

~~~text
script_revision = sN
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
~~~

`script_evidence_closure_item_ids[]` is sorted and duplicate-free. It is the exact union of every
beat-, claim-, and counter-evidence item ID plus every evidence item reached transitively through
an `analysis_ref_ids[]` registry entry under the active contract bundle. Python derives the set and
its canonical `script_evidence_closure_sha256`; the storyteller and verifier cannot add, remove, or
hash it. Missing, foreign, duplicate, or ambiguous transitive evidence fails deterministic script
validation.

Version 1 uses:

~~~text
freshness_recheck_ttl_minutes = 120
script_hard_expiry_at = next configured edition-window boundary
freshness_anchor_at = verified_at for initial gate; rechecked_at for renewed gate
freshness_deadline_at =
    min(freshness_anchor_at + 120 minutes, script_hard_expiry_at)
~~~

The TTL measures time since the latest script freshness verification; it does not redefine source
publication freshness. The script permanently retains its original `bound_index_file_sha256`
lineage. Starting a delayed reader projection, story stream, or video after the soft TTL requires a
deterministic check against a separately identified current recheck index and source state.
`script_hard_expiry_at` is Python-owned and cannot be extended by the storyteller or verifier. Gate
validity is half-open: both `clock < freshness_deadline_at` and
`clock < script_hard_expiry_at` must hold; equality is expired, not current.

If selected evidence changed, the workflow binds the refreshed report/index, creates a new
canonical script revision, and repeats full verification. If it did not change, Python writes an
immutable freshness-recheck receipt and then a new immutable gate revision. The receipt binds:

~~~text
parents[] = exactly one each of prior_gate, bound_index, recheck_index, script
script_evidence_closure_item_ids[]
script_evidence_closure_sha256
item_fingerprint_policy_id
item_fingerprint_algorithm_version
checked_item_ids[]
checked_item_old_new_fingerprints[]:
  item_id
  old_fingerprint
  new_fingerprint
required_source_ids[]
source_statuses[]:
  source_id
  acquisition_status
decision = unchanged
rechecked_at
freshness_anchor_at = rechecked_at
freshness_deadline_at
script_hard_expiry_at
~~~

The fingerprint policy and algorithm version are pinned by the active contract bundle. The receipt
may say `unchanged` only when `checked_item_ids[]` is sorted and duplicate-free and exactly equals
`script_evidence_closure_item_ids[]`; `checked_item_old_new_fingerprints[]` has exactly one row per
checked ID and no foreign row; every required item is uniquely present in both indexes; every old
fingerprint equals its new fingerprint; `required_source_ids[]` is the exact source set for the
closure; `source_statuses[]` has exactly one row for every required source and no foreign row; and
every required source has acquisition status `success`. A missing, foreign, duplicate, or
ambiguous item, a partial item set, a rate limit, access challenge, `verification_required`,
`failed`, or `no_items` source status produces `decision = blocked` and no gate. A changed
fingerprint requires a new `completed` report, a new script, and full independent verification; no
partial recheck can claim `unchanged`.

The renewed gate binds the receipt and prior gate through its typed `parents[]`. The expired gate
never becomes current again, no file is modified in place, and media remains blocked until the new
gate path is explicitly supplied. An unchanged recheck may renew the gate only while both half-open
clock comparisons pass and may never set a later hard expiry. Crossing the hard expiry—or crossing
the local calendar date while the script uses relative “today/just now” language—requires a new
`completed` report, a new script, and full independent verification.

## G2 — Dialectical and professional narrative gate

Each chapter has exactly one central question. Each core thesis must include:

- at least one confirmed fact or correctly attributed claim;
- at least one final claim whose factual premise is supported by an authorized evidence item with
  access status `partial` or `full_text`;
- the intermediate causal mechanism, not a jump from headline to conclusion;
- material actors, interests, capabilities, constraints, and reactions;
- explicit assumptions and calibrated evidence strength;
- one substantive counterposition, counterevidence path, or an explicit bounded statement that no
  material counterevidence was available in the authorized dossier;
- one or more conditions that weaken or invalidate the thesis;
- observable watch signals; and
- evidence-aware conditional treatment of future evolution.

Non-empty arrays are not sufficient. Rephrasing the thesis as a counterpoint, using generic
“another possibility”, or naming an unobservable signal fails the gate.

The contract does not require artificial equal weight. It requires the strongest material
alternative within the authorized evidence and prevents a narrator from deleting inconvenient
evidence for drama.

For each thesis, count materially distinct scenario paths authorized by exact analysis-registry
references and evidence-backed factual premises:

- when at least two are authorized, the chapter includes at least two, each with a trigger, horizon,
  observable signal, and claim-level references;
- when exactly one is authorized, the chapter includes that path and Python issues an immutable
  `scenario_evidence_gap = only_one_authorized_scenario` receipt;
- when none is authorized, the model invents none and Python records
  `scenario_not_applicable_reason = no_authorized_scenario_evidence`; and
- a verifier must reject two cosmetic variations of one path as not materially distinct.

The one-or-zero branches do not waive counterposition, invalidation, or watch-signal requirements;
they prevent a quota from manufacturing unsupported forecasts.

### Professional-storytelling rubric

An independent verifier and a named human acceptance reviewer separately score these dimensions
from 1 to 5:

| Dimension | Passing meaning |
| --- | --- |
| `dialectical_rigor` | Mechanism, actors, assumptions, counterposition, conditions, and observables are substantive |
| `narrative_coherence` | One story advances causally; unrelated same-day events are not stitched together |
| `professional_clarity` | Technical concepts are explained; jargon does not replace mechanism |
| `epistemic_transparency` | A listener can distinguish confirmed, attributed, historical, inferred, contested, scenario, and unknown |
| `restraint_and_non_sensationalism` | No invented drama, absolute language, false certainty, or suppressed counterevidence |

The immutable verifier result contains `script_rubric_scores[]` and
`chapter_rubric_scores[]`. The latter has exactly one row for every script `chapter_id` and no
foreign or duplicate row. The script set and every chapter set each contain all five named
dimensions exactly once, with an integer score, explanation, and supporting/failing beat IDs for
each. Human acceptance uses a two-stage blind-review protocol:

1. After verification is immutable, Python draws a 256-bit nonce from the operating system CSPRNG.
   The nonce is held outside every reviewer-readable artifact and access surface until reveal.
   Python records `commitment_scheme_id`, `canonicalization_id`, and
   `verifier_score_commitment_sha256`, where Version 1 commits with domain-separated SHA-256 over
   the nonce, `verification_sha256`, `rubric_sha256`, and the canonical hidden verifier-score
   payload containing both `script_rubric_scores[]` and `chapter_rubric_scores[]`:

   ~~~text
   SHA256(
     domain_separator
     || nonce_256_bits
     || verification_sha256
     || rubric_sha256
     || canonical_hidden_verifier_scores
   )
   ~~~

   The Version 1 `domain_separator`, byte encoding, score ordering, and canonical JSON rules are
   fixed by those two versioned IDs.
2. `<run-id>-blind-review-dossier.json` binds the report, script, and rubric, omits the nonce and
   every verifier score, and exposes only opaque `verification_sha256`, the commitment, and its two
   scheme IDs. It contains no verification path, verification artifact ID, latest pointer, or other
   resolvable verification handle.
3. `<run-id>-human-review.json` binds the blind-dossier path/hash, named reviewer,
   `review_started_at`, `scores_locked_at`, and all five `human_rubric_scores` with explanations.
4. Only after that immutable human receipt exists, `<run-id>-score-reveal.json` reveals the nonce
   and verifier-score payload; binds the human receipt and verification through typed parent rows,
   including the verification path/hash; records `scores_revealed_at`; and recomputes the exact
   commitment under the recorded scheme and canonicalization IDs while proving the required
   timestamp ordering.

The review surface exposes only the blind dossier until scores are locked. The reviewer must not
be the storyteller or verifier. Acceptance requires
`review_started_at <= scores_locked_at <= scores_revealed_at`, exact commitment equality, and
immutable hashes across all three artifacts; a missing, early, mismatched, or rewritten reveal
fails. This state protocol proves only what the workflow withheld from its reviewer-readable
surface before score lock; it does not claim knowledge of information obtained outside the system.

Every script-level verifier score, every score in every chapter row, and every one of the five
whole-script human scores must independently be `>= 4/5`. Chapter IDs and dimension names must
match exactly; no cross-chapter, script/chapter, verifier/human, or overall average can hide a lower
score. The verifier receipt is required for gate issuance; the human-review and score-reveal
receipts are required for formal G2 and Stage C acceptance. Critical factual and freshness rules
remain Boolean hard gates rather than subjective scores.

The following are prohibited:

- invented dialogue, private psychology, insider details, secret motives, first-person experience,
  quotations, or chronology;
- treating correlation as causation;
- turning one example into a broad trend without evidence;
- confusing a short-term shock with structural change;
- writing a scenario as an inevitable forecast;
- deleting material counterevidence for a stronger story;
- using “shocking”, “completely changes”, “inevitable”, or equivalent absolute language without
  evidence; and
- using specialist terms without explaining the mechanism.

## G3 — Independent verifier gate

Independence requires:

- a separate task/session and role;
- a receiver-enforced output schema and policy hash;
- no inherited storyteller hidden conversation;
- a minimal immutable hash-bound dossier;
- no storyteller authority to write final verification; and
- recorded requested/served model, provider route, usage task, and verifier policy hash.

The versioned `verifier_model_policy` allowlists provider route plus requested and served model
identifiers. Every allowed served model has a pinned capability manifest proving strict structured
output support, a context window large enough for the measured dossier plus frozen response
reserve, tool/network access disabled for the role, task/session isolation, and usage reporting
compatible with G4. An unlisted fallback, missing served-model identity, capability shortfall, or
requested/served substitution outside the allowlist blocks verification before its content is
interpreted. Verification and red-team manifests bind the allowlist and capability-manifest hashes.

Each beat receives exactly one `pass`, `repair`, or `reject` result and these checks:

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

The following are Boolean critical checks and must all pass:

~~~text
factual_support
temporal_accuracy
attribution
access_boundary
fact_analysis_separation
claim_unit_completeness
compliance_boundaries
~~~

Beat IDs and verdicts form a one-to-one set. Unknown, duplicate, missing, or cross-script IDs fail.
The verifier cannot edit a saved script. It produces only an immutable decision and bounded repair
instructions.

An invalid model draft remains an immutable `draft attempt` and never receives a canonical script
revision. Python allocates `script_revision = sN` only after deterministic validation passes. The
verifier dossier, verification, and gate must satisfy:

~~~text
set(script.all_beat_ids)
==
set(verification.all_beat_ids)
==
set(gate.verified_beat_ids)
~~~

All three sets contain no duplicates, every verification verdict is final `pass`, and the gate
contains no ID outside the script.

One repair is allowed across all content-validation stages. Repair creates a new script revision
and hash, narrows input to failing beats plus necessary adjacent context, cannot expand authorized
evidence, and triggers full deterministic validation and independent re-verification. A second
non-pass result is `rejected`.

### Verifier red-team acceptance

Before default enablement, run the frozen canonical Version 1 set of exactly 32 cases twice under
the same served model, prompt, policy, capability manifest, and contract:

- 8 factual/evidence errors;
- 8 time/current-versus-background errors;
- 8 epistemic, causal, dialectical, or invented-motive errors;
- 4 prompt-injection or authority-escalation attempts; and
- 4 clean controls.

The first four groups are exactly 28 adversarial cases; Version 1 has exactly four clean controls.
Additional cases require a versioned set rather than silently changing these denominators.
Every non-clean case declares `expected_defects[]`. Each defect has a unique `defect_id`, `severity`
(`critical` or `noncritical`), `expected_decision`, and exact `expected_failed_checks[]`. Scoring is
by defect ID, not merely by whether the surrounding case failed; one generic rejection cannot
claim detection of several unmapped defects. Both `critical_expected_defect_count > 0` and
`noncritical_expected_defect_count > 0` are mandatory, and every declared expected defect is in
its severity denominator. Parser errors, invalid structured responses, and aborted cases count as
misses for all of that case's expected defects rather than disappearing from the denominator.

Required results for each run independently, with no pooling across the two runs:

| Measure | Threshold |
| --- | --- |
| Critical expected-defect recall | `100%` by `defect_id` with the expected failed-check mapping |
| Non-critical expected-defect recall | `>= 90%` by `defect_id` |
| Clean controls | exactly `4/4` receive `pass` with no invented defect |
| Prompt-injection escapes | `0` |
| Wrong report/script/hash acceptances | `0` |

Ordinary unit tests use frozen verifier fixtures. The real remote-model acceptance set produces an
immutable manifest for each run, including all expected and observed defect mappings. It is rerun
when the requested or served model, allowlist, capability manifest, policy, prompt, or contract
changes.

## G4 — Token-cost gate

For this project, cost is model-token use:

~~~text
story_pipeline_tokens =
phase["professional-narrative-storyteller"].tokens.accounted_total.value
+ phase["professional-narrative-verifier"].tokens.accounted_total.value
+ phase["professional-narrative-repair"].tokens.accounted_total.value
+ phase["professional-narrative-reverification"].tokens.accounted_total.value
~~~

All four phase rows must exist, and `story_pipeline_tokens` is an integer sum of their canonical
numeric `.value` fields, never a sum of aggregate-measurement objects. Only non-overlapping
accounted totals are added. Cached input, uncached input, output, and any
diagnostic subsets remain visible, but reasoning or tool output is not added twice when already
included in output. Monetary price, currency, and provider billing do not enter acceptance.

Version 1 freezes the provisional engineering ceiling before the first acceptance run:

~~~text
story_pipeline_tokens <= 250_000
~~~

This is a Draft ceiling for the four narrative model phases only; upstream report analysis is not
added to `story_pipeline_tokens`. The ceiling is not a permanent quality KPI. It may change only
through a versioned pre-run decision and cannot be raised after seeing a failing run.

Runtime persistence and formal acceptance are deliberately different. During an interrupted or
metering-degraded run, usage may remain `coverage = partial`, lower-bound, estimated, or
unobservable, with every missing phase/call/field named. That record is valid recovery evidence but
cannot pass G4. Missing usage is never coerced to zero.

An accepted run requires:

- recomputable non-overlapping pipeline total;
- for every invoked phase, `coverage == complete` and
  `tokens.accounted_total.quality == exact`, with a non-negative integer
  `tokens.accounted_total.value`;
- for an uninvoked optional repair or re-verification phase, an exact scheduler receipt proving
  provider-call count `0`; its required phase row has `tokens.accounted_total.value == 0` and
  `tokens.accounted_total.quality == exact`;
- `unclosed_call_count == 0`;
- usage conflicts `0`;
- every task bound to the current run, report, script, role, and phase;
- `story_pipeline_tokens <= 250_000`;
- the configured global `budget.max_agent_tokens > 0` and the phase-admission invariant below
  passed before every allowed model call; and
- identical completed replay adds zero provider calls and zero tokens.

~~~text
global_observed_accounted_tokens
+ remaining_narrative_phase_reserve_tokens
+ downstream_required_reserve_tokens
<= budget.max_agent_tokens
~~~

Both reserves come from a versioned pre-run policy and are non-negative. A partial runtime ledger
uses its observed lower bound for early blocking but cannot establish final headroom. Passing the
local 250,000-Token ceiling never compensates for violating the global observed-plus-reserve bound.
A reserve may equal zero only when an exact scheduler receipt proves that no model phase in that
reserve class remains authorized or scheduled; an omitted or unknown reserve is not zero.

The logical schedule permits:

~~~text
1 initial storyteller
1 initial verifier
0 or 1 targeted repair
0 or 1 full re-verification
~~~

Lower Token use is not sufficient if output scope, evidence coverage, quality, or length changed.
Comparable optimization holds report, index, contract, scope, and quality gates stable.

Report exact numerator and denominator values with these normalized formulas:

~~~text
normalized_tokens_per_chapter =
    story_pipeline_tokens / accepted_chapter_count

normalized_tokens_per_verified_beat =
    story_pipeline_tokens / verified_beat_count

normalized_tokens_per_selected_event =
    story_pipeline_tokens / distinct_selected_featured_event_count

normalized_tokens_per_1000_final_zh_characters =
    story_pipeline_tokens * 1000 / final_zh_han_character_count

normalized_tokens_per_final_spoken_minute =
    story_pipeline_tokens / (actual_audio_duration_ms / 60_000)

phase_share =
    exact_phase_accounted_tokens / story_pipeline_tokens
~~~

For `phase_share`, `exact_phase_accounted_tokens` is exactly
`phase[name].tokens.accounted_total.value` after that row passes the exact-quality gate.

`final_zh_han_character_count` counts Unicode Han-script code points after NFC normalization of the
deterministically joined final spoken beats; whitespace, punctuation, markup, evidence drawers,
and metadata do not count. Spoken-minute normalization exists only when accepted audio has measured
positive duration. Every other denominator must also be positive; a zero denominator is
`not_applicable` and cannot be presented as zero or used in a comparison. These whole-pipeline
ratios are normalization diagnostics, not a claim that each chapter, beat, or event caused an equal
Token share. Report first-pass acceptance and repair rate separately as quality/process diagnostics,
not as Token savings.

The implementation acceptance manifest pins `character_counter.normalization = NFC`,
`character_counter.unicode_property = Script=Han`, `character_counter.library`,
`character_counter.library_version`, and `character_counter.unicode_version`. A change to any of
these creates a new metric version; results from different versions are not directly comparable.

## G5 — Immutability, idempotence, concurrency, and recovery

The canonical script, verifier dossier, verification, repair receipt, verified gate receipt,
contract-bundle snapshot, and both reader projections are immutable. A mutable run manifest stores
paths, hashes, state, attempts, and usage bindings, not copied bodies or token totals.

Every artifact has `schema_version`, `artifact_id`, `artifact_kind`, `data_root_identity`, typed
`parents[]`, and `policy_hashes`. `parents[]` is always a list; every row has exactly this common
shape, with `semantic_hash` present only when that parent kind defines one:

~~~text
parent_kind
path
file_sha256
semantic_hash  # optional
~~~

An artifact's own `<kind>_sha256`, including a digest used in its filename, is a semantic hash:
SHA-256 over the artifact's versioned canonical `semantic_payload`. The hash input explicitly
excludes every envelope field outside `semantic_payload`, the artifact's own digest field, persisted
file bytes and formatting, and the derived path or filename. An artifact never embeds its own
`file_sha256`. By contrast, `parents[].file_sha256` is SHA-256 over the completed persisted parent
file bytes. When a parent kind defines a semantic hash, its parent row carries both that byte hash
and `semantic_hash`; the two have different domains and need not be equal.

Every parent path is relative to the active data root. Parent kinds are unique within an artifact;
missing required, foreign, or duplicate rows fail validation. Python resolves every path through
`require_data_root_path()` and recursively revalidates the parent closure; a child cannot rely on a
bare ID, a latest-pointer lookup, a keyed `parents.<kind>` object, or a directory scan.

The active configured report, narrative, verifier, projection, freshness, and policy identities are
frozen into one immutable contract-bundle snapshot at
`narratives/contracts/<policy-id>/<contract-bundle-sha256>.json`. The snapshot records
`contract_bundle_identity`, its canonical `contract_bundle_sha256`, every constituent contract and
policy identity/hash, `data_root_identity`, and an empty root `parents[]` list. A bundle hash or
identity change creates a different path; no snapshot is overwritten. Both
`<contract-bundle-sha256>` and `contract_bundle_sha256` are the same versioned canonical
`semantic_payload` hash, never the snapshot file-byte hash. A child referencing the snapshot stores
that value as `parents[].semantic_hash` and independently stores the completed snapshot-byte digest
as `parents[].file_sha256`.

Revision axes are unambiguous: report `rN`, story attempt `aN`, canonical script `sN`,
verification `vN`, freshness recheck `fN`, gate `gN`, projection `pN`, story compilation `cN`,
TTS/audio `tN`, and render `render-N`. Each `pN` is bound to exactly one `gN`. Tests fail any schema
or path that reuses one revision label for different meanings.

The mutable run manifest stores explicit current references:

~~~text
professional_narrative.current_script.{path,sha256}
professional_narrative.current_verification.{path,sha256}
professional_narrative.current_gate.{path,sha256}
~~~

These are root paths in the run-manifest object; there is no outer `run` wrapper. The references are
hints for orchestration, not trust anchors; every consumer revalidates them.
State is split by responsibility:

~~~text
verification: ... -> verifying -> verified | repair_required | rejected | failed
admission: current | recheck_pending | expired | blocked
reader: pending | rendering | ready | partial
story: pending | compiling | ready | blocked | partial
video: pending | rendering | completed | partial | failed
~~~

`verified` and `rejected` are immutable content decisions for one script revision. TTL expiry
changes admission to `expired`; it never rewrites a verified script as unverified. `failed` is a
recoverable execution condition, while `partial` belongs only to projections or downstream media.

Requirements:

- identical input identity returns `already_completed` with the same paths and hashes and zero new
  model calls;
- changed report, index, contract, policy, `as_of`, packet, or script creates a new revision;
- no existing script or verification is overwritten;
- two concurrent writers for one revision produce exactly one winner;
- the loser reads the winner or receives an explicit collision;
- orphan drafts or verifications are adopted only after full path, identity, and hash validation;
- corrupted, mismatched, or conflicting artifacts fail visibly;
- a repair receipt binds rejected draft hash, error paths, rule IDs, authorization, attempt, and
  whether repair remains authorized;
- interruption is recoverable after model return, draft persistence, verifier scheduling,
  verification persistence, and reader projection;
- recovery never repeats a model call when a matching immutable result already exists;
- a stale result cannot advance the current reader or media gate; and
- projection failure cannot retract the report or verified script.

At least one real failure drill interrupts the verifier/run update boundary and demonstrates the
same final semantic hashes as an uninterrupted path without unnecessary new tokens.

## G6 — HTML and Markdown gate

The primary reading area is one fused Professional narrative with:

- the storytelling-style main text;
- distinguishable fact, attribution, background, judgment, contest, scenario, and watch-signal
  roles;
- source names and publication times;
- `as_of`, `verified_at`, freshness, and verification status; and
- expandable argument and evidence details.

There is exactly one deterministic semantic projection builder:

~~~python
bundle = load_verified_narrative_gate(
    verified_gate_path,
    data_dir=data_dir,
    clock=clock,
)
payload = narrative_projection_semantic_payload(bundle)
render_markdown(payload)
render_html(payload)
~~~

Its only signature is
`narrative_projection_semantic_payload(bundle: VerifiedNarrativeBundle) -> dict`. Every reader
command accepts exactly one `verified_gate_path`, plus the required `data_dir` and `clock` loader
dependencies, and calls `load_verified_narrative_gate()` before the builder. There is no public
reader API accepting raw script, verification, gate objects, a latest pointer, or separate paths.

The immutable payload contains the ordered chapter/beat text, `central_question`, epistemic and
freshness classes, claim/evidence/analysis references, source names and publication times,
`as_of`, verification state, and gate identity. HTML and Markdown renderers accept this payload
type only; they cannot independently reread or reinterpret the script, verification, report, or
index.

One projection revision writes both immutable paths:

~~~text
narratives/projections/<report-id>-sN-gN-pN.md
narratives/projections/<report-id>-sN-gN-pN.html
~~~

The two artifacts share one `pN`, each has exactly one typed gate parent for the same `gN`, and a
projection revision can never be rebound to another gate or overwritten.

Canonical JSON for that one payload and its `projection_payload_sha256` are embedded or referenced
by both projections. Acceptance re-extracts each projection's payload and requires exact canonical
payload-hash equality with the builder output: `2/2` projections match, semantic field mismatch
`0`. Presentational byte equality is not required.

HTML escapes every untrusted string. Links use the existing safe URL policy. Draft, repair,
rejected, stale, or hash-mismatched content is never labelled verified and is not shown in the
published narrative area. Reader failure does not modify canonical artifacts. Real acceptance
includes desktop and narrow-screen visual inspection for clipping, overlap, evidence-link drift,
and misleading state labels.

## G7 — Verified media gate

Media commands accept one `verified_gate_path`, not an arbitrary `script_path` and not a directory
scan for the newest file. The gate receipt minimally binds:

~~~text
schema_version
artifact_id
artifact_kind = verified_narrative_gate
data_root_identity
gate_revision = gN
decision = pass
report_id
report_content_hash
bound_index_file_sha256
contract_bundle_identity
contract_bundle_sha256
narrative_contract_sha256
script_id
script_revision
script_sha256
script_evidence_closure_sha256
verification_sha256
verified_at
freshness_anchor_at
freshness_deadline_at
script_hard_expiry_at
verified_beat_ids[]
parents[]
~~~

An initial gate's `parents[]` contains exactly one row for each `parent_kind` below:

~~~text
report
bound_index
contract_bundle
packet
scope_receipt
script
verification_dossier
verification
~~~

A renewed gate contains exactly those eight rows plus exactly one `prior_gate` row and exactly one
`freshness_recheck` row. No gate may omit a required kind or contain a foreign or duplicate kind.
Every row uses the common list-row shape defined in G5, and every path is relative to the gate's
active `data_root_identity`; there is no keyed `parents.<kind>` form and no renewal reference outside
`parents[]`. The single public admission API is:

~~~python
bundle = load_verified_narrative_gate(verified_gate_path, data_dir=data_dir, clock=clock)
compile_story_stream(bundle, ...)
~~~

`load_verified_narrative_gate()` validates the gate schema, enforces
`require_data_root_path()`, recursively loads and rehashes the entire parent closure, checks the
pass decision and exact beat-set equality, validates the current report/run and data-root identity,
and enforces freshness or a bound renewal receipt. It also reopens the contract-bundle parent,
recomputes its hash, and requires its `contract_bundle_identity` to equal the active configured
contract identity. It returns a `VerifiedNarrativeBundle`. The public compiler accepts only that
type; no public raw-script compiler and no `--force`, `--skip-verification`, or `--allow-stale`
option exists. TTS accepts only a ready typed story-stream handle, and video accepts only ready
typed story-stream plus audio/subtitle manifests.

Media may begin only when:

~~~text
gate.decision == pass
AND every typed parent path stays inside the active data root
AND the recursively recomputed parent/hash closure matches
AND set(script.all_beat_ids)
    == set(verification.all_passed_beat_ids)
    == set(gate.verified_beat_ids)
AND all three beat sets have no duplicates
AND clock < freshness_deadline_at
AND clock < script_hard_expiry_at
~~~

G7 ends at verified-content admission. It neither assumes that scenes already exist nor
pre-approves an asset or fallback. The deterministic compiler first produces a candidate
Story-stream manifest from the admitted bundle and media candidate set; M1 then performs the
post-compilation `oneOf`, hash, evidence, rights, fallback, coverage, and replay checks below.

Draft, authoring, verifying, repair, rejected, stale, missing, damaged, cross-report, or mismatched
inputs must be rejected `100%` of the time. Rejection creates no story-stream, audio, subtitle, or
video artifact. Negative acceptance tests attack both CLI entry points and direct Python module
calls.

## Story-stream acceptance

Story-stream compilation is deterministic and performs zero model calls. Every scene binds the
common fields below and then satisfies exactly one `oneOf` branch:

~~~text
scene_id
beat_ids[]
event_ids[]
evidence_item_ids[]
scene_type
on_screen_text
aspect_ratio
crop
focal_point
safe_area
target_or_actual_time_range

oneOf:
  media_asset:
    scene_type = media_asset
    image_sha256 = required SHA-256
    source = non-empty
    credit = non-empty
    rights_status = owned | licensed | public_domain
    fallback_reason = absent

  text_card:
    scene_type = text_card
    image_sha256 = absent
    rights_status = absent
    fallback_reason = no_allowed_asset | rights_unknown | rights_rejected | hash_failed
~~~

The complete candidate-rights enum is `owned`, `licensed`, `public_domain`, `unknown`, or
`rejected`. Only the first three can be persisted as a selected media asset's `rights_status`.
Candidates marked `unknown` or `rejected` are never selected; they lead to an allowed alternate
asset or a `text_card` with the applicable fallback reason. Python derives candidate rights from an
allowlisted, hash-bound rights or license record; a model, public URL, or source credit cannot
assign them.

Scene evidence is a subset of verified beat evidence. Across the complete manifest, scene
`beat_ids[]` preserve script order and cover every gate beat exactly once, with no missing,
duplicate, or foreign ID. An edited subset is a new immutable cut/script requiring deterministic
validation and independent verification; callers cannot improvise a cut through requested IDs.
Same verified gate, media set, and configuration produce the same semantic scene order and
manifest hash. Unknown or rejected media rights select a licensed asset or text-only fallback. A
public URL or source credit alone does not prove public-video reuse permission. Story compilation
failure changes no report, script, verification, or gate.

M1 acceptance requires all of the following on each manifest and on a two-run identical-input
replay:

| Measure | Required threshold |
| --- | --- |
| Verified beat coverage | `100%` |
| Missing / duplicate / foreign beat IDs | `0 / 0 / 0` |
| Scene evidence outside its verified beats | `0` |
| Selected media with `unknown` or `rejected` rights | `0` |
| Scene `oneOf` violations or unresolved fallbacks | `0` |
| Story-compiler model calls / model Tokens | `0 / 0` |
| Same-input semantic scene-order or manifest-hash mismatches | `0` |

## Video acceptance

The first video MVP:

- consumes only a current verified gate and ready story stream;
- uses authorized (`owned`, `licensed`, or `public_domain`) static images or valid text cards, one
  licensed TTS voice, credits where media requires them, and subtitles;
- records TTS engine, version, voice, license, configuration, usage, audio hash, and actual timing;
- derives every scene and subtitle interval from actual audio;
- binds video, audio, subtitles, fonts, assets, and renderer settings to the same script;
- uses reproducible codec, resolution, frame rate, bitrate, color, and font settings;
- passes container, codec, duration, audio-track, subtitle, and A/V synchronization checks;
- has no missing, duplicate, or reordered spoken beat;
- receives frame inspection for black frames, crop, safe area, credit, subtitle, and watermark;
- retries independently without retracting the report or verified script; and
- excludes source-video ingestion, voice cloning, and rights-unknown music.

The initial A/V duration tolerance is `250 ms` for every scene boundary and the complete track. A
later platform profile may version this value. M2 acceptance additionally requires spoken-beat and
subtitle coverage `100%`, missing/duplicate/reordered spoken beats `0 / 0 / 0`, subtitle intervals
outside measured audio `0`, and media frames using `unknown` or `rejected` rights `0`.

## Non-evidence

None of the following proves completion:

- generating a long document;
- meeting a word, paragraph, or chapter count;
- average citations per paragraph;
- total source or URL count;
- a high aggregate verifier score with one critical failure;
- a storyteller claiming that it self-verified;
- human scores without the hash-bound blind-review, locked-score, and score-reveal receipts;
- model confidence;
- low repair rate without a red-team acceptance set;
- the presence of “however” or an equal number of positive and negative sentences;
- an HTML file existing;
- playable TTS or an MP4 that opens;
- output tokens alone rather than complete non-overlapping input and output;
- missing usage treated as zero;
- `collected_at` used as publication time;
- the current report-level post-publication evaluator returning `accept`;
- the same role writing and approving its own script; or
- one successful real report.

## Staged real acceptance

### A — Deterministic fixtures

Freeze a report/index/analysis fixture covering current news, previous-day news, old background,
missing and future times, metadata-only and verification-required access, conflicting evidence,
scalar/array/nested/synthesis analysis references, compound claims, three analyses, conditional
scenario branches for two/one/zero authorized paths, and invalidation signals. Cover
`mode = edition_narrative`, `central_question`, bound-index identity, the four claim-level
freshness classes, mixed-freshness claims in one beat, missing/foreign publication-proof IDs, an
old item from an otherwise current event, nonzero current quota, claim
type/criticality/escalation/completeness, the canonical
`sections[].items[].source_refs[]` membership source, registry row/hash tampering, duplicate and
ambiguous membership, 60% featured-event coverage, domain coverage `3/3`, strict absent/empty-only
cross-synthesis not-applicability, per-chapter `partial`/`full_text` depth, direct and transitive
script evidence closure, and the sole typed-bundle semantic projection payload. Include exact and
malformed initial/renewed parent-kind lists, inactive contract bundles, missing or foreign closure
items, partial rechecks, every blocked source status, equality at both freshness deadlines,
gate-bound immutable `pN` paths, hidden-nonce commitment/reveal tampering, rejected
`completed_partial` input, and raw-reader/compiler direct-API bypass attempts. All narrative schema,
cross-field, hash, evidence, time, repair, state, reader, and G7 admission-gate tests must pass.

When M1 is evaluated, extend the same fixture family with both scene `oneOf` branches and every
quantitative Story-stream threshold. That M1 extension is not required to close the Narrative MVP
while Story-stream remains explicitly deferred.

The preserved 2026-08-25 `completed_partial` morning-report acceptance artifact is a negative and
compatibility fixture only. It cannot count toward a Stage C edition, a Token baseline, current-news
quota evidence, freshness evidence, or release proof.

### B — Verifier red team

Run the 32-case acceptance set twice and meet every G3 threshold independently on both runs,
including defect-ID scoring and exactly `4/4` clean controls each time. Store requested and served
model, model allowlist and capabilities, prompt, policy, contract, case/defect hashes, raw
structured decisions, usage, and per-run summary in immutable acceptance manifests.

### C — Three consecutive real editions

Before default enablement, complete three consecutive real editions, including at least one
morning and one evening. Every threshold below applies to each edition independently; pooling a
numerator, denominator, score, warning, or defect across editions is prohibited:

- report and narrative deterministic validation: `0 errors / 0 warnings`;
- narrative mode: `edition_narrative`, non-empty chapter `central_question` values, and exact
  `bound_index_file_sha256` lineage;
- featured-event coverage: denominator `> 0` and coverage `>= 60%`;
- membership registry: every row derives from the canonical report path, item ownership is unique,
  `membership_sha256` matches, and duplicate/ambiguous/foreign rows are `0`;
- analysis-domain coverage: `geopolitics`, `ai_technology`, and `markets` = `3/3` through final
  claim-level references;
- cross-perspective synthesis: at least one final exact reference or one valid deterministic
  not-applicable receipt;
- current-news quota: `available_current_featured_event_count > 0`, `current_claim_count > 0`,
  and final distinct current-event coverage
  `>= min(2, available_current_featured_event_count)`;
- critical-claim evidence closure: `100%`;
- claim-unit completeness: `pass`, with no downgraded Python-critical claim;
- thesis evidence depth: every core thesis has at least one final claim supported by a `partial`
  or `full_text` evidence item, and therefore every chapter has at least one;
- current-claim time compliance: `100%`;
- freshness: every claim-unit class belongs to the four-value enum, every proof-ID set obeys its
  class and direct-evidence subset rules, and mixed-class beats cannot transfer current status;
  `freshness_anchor_at` equals
  `verified_at` for an initial gate or `rechecked_at` for a renewed gate; and the deadline equals
  the minimum of that anchor plus the soft TTL and `script_hard_expiry_at`; gate use satisfies both
  half-open `clock <` comparisons;
- freshness closure: the sorted duplicate-free checked item set exactly equals
  `script_evidence_closure_item_ids[]`, closure and fingerprint policy hashes match, all required
  old/new fingerprints are uniquely present and equal, the required source set is exact, and every
  required source status is `success`;
- scenarios: the two/one/zero authorized-evidence rule passes for every thesis;
- every beat final decision: `pass`;
- script, verification, and gate beat sets: exactly equal, duplicate IDs `0`;
- repairs: at most one per script;
- verifier rubric: all five whole-script dimensions and all five dimensions for every exact
  `chapter_id` independently `>= 4/5`, with no missing/foreign/duplicate chapter or dimension and
  an immutable verifier receipt;
- human rubric: all five dimensions independently `>= 4/5` with a separate immutable named-reviewer
  receipt, a reviewer-inaccessible OS-CSPRNG 256-bit nonce until reveal, matching scheme and
  canonicalization IDs, matching blind-dossier and score-reveal receipts, commitment equality, and
  `review_started_at <= scores_locked_at <= scores_revealed_at`;
- Token coverage: every invoked phase exact and complete, optional-zero receipts present,
  non-overlapping total, open calls `0`, conflicts `0`;
- Token budget: `story_pipeline_tokens <= 250_000` and the global
  `global_observed_accounted_tokens + remaining_narrative_phase_reserve_tokens + downstream_required_reserve_tokens <= budget.max_agent_tokens`
  invariant both pass;
- HTML/Markdown: both `2/2` re-extracted semantic payload hashes exactly equal the sole builder
  payload, share one immutable gate-bound `pN`, and have unsafe rendering defects `0`;
- verified-gate contract: `data_root_identity` matches, the active contract bundle rehashes, and the
  initial eight or renewed ten required parent kinds are exact with missing/foreign/duplicate kinds
  `0`; and
- verified-gate hashes: fully recomputable.

### D — Recovery and blocking drill

On at least one real edition, exercise identical replay, concurrent revision allocation,
post-draft interruption, post-verification/pre-manifest interruption, projection failure, expired
freshness TTL with unchanged evidence, expired freshness TTL with changed evidence, changed index
hash, a partial closure recheck, missing/ambiguous closure items, every non-success required-source
status, attempted use exactly at and after `freshness_deadline_at` and
`script_hard_expiry_at`, local-date rollover with relative time language, inactive contract bundle,
missing/foreign/duplicate parent kinds, corrupted parent path/hash, projection rebinding, nonce or
commitment tampering, early reveal, direct module bypass, and rejected-script media attempt.

Required outcome:

- immutable overwrite `0`;
- duplicate revision `0`;
- identical replay new provider calls `0`;
- stale/rejected/mismatched downstream acceptance `0`;
- unchanged-evidence recheck produces a new gate revision and changed evidence forces a new script
  plus full verification;
- incomplete, ambiguous, or non-success rechecks are blocked and produce no gate;
- no recheck extends `script_hard_expiry_at`, and hard-expired or date-invalid relative-language
  scripts require a new `completed` report;
- every failure has an explicit state and receipt; and
- report delivery remains intact.

## Release decision

The Narrative MVP is complete only when G0–G7 and real-acceptance stages A–D pass. Story-stream and
video may remain deferred, but the verified-media gate must already be implemented and tested.

The Story-stream phase is complete only when its deterministic, evidence, rights, fallback,
idempotence, and failure-isolation gates pass.

The Video phase is complete only when TTS, timing, subtitles, reproducible rendering, rights,
technical QA, recovery, and delivery gates pass.

This Draft becomes Verified only when implementation, schemas, tests, real acceptance evidence,
runtime/user documentation, and English/Chinese records all agree.
