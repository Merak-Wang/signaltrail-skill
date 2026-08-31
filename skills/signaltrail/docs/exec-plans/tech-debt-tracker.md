# Technical-Debt Tracker

**Purpose:** Track unresolved implementation and integration gaps through concise evidence,
impact, and measurable exit conditions.
**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

## Open Items

| ID | Priority | Gap | Evidence / impact | Exit condition |
| --- | --- | --- | --- | --- |
| TD-002 | Medium | Validation and rendering remain concentrated in very long functions. | `validate_report_data`, `compile_report_data`, `render_report_markdown`, and `report_to_blocks` combine several rule or rendering families, increasing change and review risk. | Characterization coverage protects current output while cohesive typed helpers own individual rule and rendering families. |
| TD-003 | Medium | Detailed `references/` are primarily Chinese while runtime entry documents are English. | Language authority is unclear when a detailed reference has no canonical English record or cataloged single-language status. | Every maintained reference declares its language authority; touched bilingual records keep a canonical English file and synchronized Chinese mirror. |
| TD-004 | Low | CLI dispatch remains concentrated in `main()`. | Shared JSON readers and writers exist, while command routing still couples many unrelated handlers. | Cohesive command families have typed handlers and command-level characterization coverage. |
| TD-005 | Medium | The zero-model monitor reports some collector-only formal sources as `unsupported`. | The [2026-08-05 run](completed-2026-08-05-morning-report-regeneration.md) showed the mismatch for Weibo; PBOC and ByteDance share it. Failure-rate reporting is overstated. | A collector-only status is visible and excluded from failure rates; monitor refresh stays free of specialized collection. |
| TD-006 | High | A process-wide enrichment failure can strand a run in `extracting_content`. | The state persists before `extract_content`; ordinary preparation returns the existing non-terminal run and cannot resume the interrupted work. | Enrichment is checkpointed and re-entrant, with fault-injection coverage after the state transition and during immutable index creation. |
| TD-007 | High | Authoring packets are mutable and lack a cryptographic binding to context and session. | Submission validates the packet currently on disk, while the session binds only the main context hash. Packet replacement can change authorized work after dispatch. | Packets are immutable; context and session persist each packet hash and authorized item IDs; begin, submit, and recovery revalidate the binding. |
| TD-008 | High | Source-cache health and authoring-session lineage can be overstated after state changes. | Cached items can yield formal `success` after a partial acquisition, and enrichment can rebuild context after authoring dispatch. Downstream state may describe a superseded evidence boundary. | Acquisition health is stored separately from item availability, and a rebuilt bound context deterministically invalidates its authoring session. |
| TD-009 | Medium | Context compaction can omit an explicitly enriched item below the per-source cap. | `_compact_candidates` expands by enriched-item count, so an enriched item below rank 25 can remain outside the prefix. | Explicitly enriched evidence is unioned into bounded context while Top order remains stable; a rank-26-or-lower regression passes. |
| TD-010 | Medium | Report persistence lacks a shared revision transaction, and evaluator attempts share a mutable pre-save draft path. | JSON can persist before its Markdown peer; concurrent evaluator attempts can replace the same draft before entering the edition lock. | One report-revision transaction covers paired artifacts, and each evaluator attempt has an immutable draft with crash and collision coverage. |
| TD-011 | Low | Acquisition-path telemetry is coarser than authoring telemetry. | Live acquisition is recorded as `browser_or_http`; legacy batch timing can start at session creation when a host omits dispatch time. This limits latency diagnosis. | Browser and HTTP paths have distinct measurements; host dispatch timestamps are used when present, and absent latency remains unknown. |
| TD-012 | Medium | Monitor eligibility and projection-ready milestones use separate truth checks. | Direct loading accepts states that preflight rejects, and an HTML failure can be followed by an unconditional ready milestone. | A shared monitor-snapshot validator governs every reader, and readiness derives from confirmed artifact existence. |
| TD-013 | Medium | `published_at` ordering covers only the bounded rows returned by an adapter. | Adapter truncation can occur before shared sorting, so recency is guaranteed only within the fetched subset. | Each adapter declares acquisition depth and truncation; pagination and window fixtures establish the supported recency boundary. |
| TD-014 | High | Standalone `save-report` can bypass the run-owned brief plan. | Its index-and-draft interface permits compilation outside `finalize_edition` without exact `default_item_ids` enforcement. | The command requires a context/plan artifact or is constrained to diagnostic use, and an out-of-plan CLI fixture is rejected. |
| TD-015 | Medium | Verified multi-page source merging lacks sufficient behavior coverage. | Ordering, duplicate replacement, partial-page provenance, and retry behavior span capture and merge paths. | Page-order, duplicate, partial-page, and retry fixtures characterize the boundary before refactoring. |
| TD-016 | Medium | The nominal 45-item authoring batch size is a soft balancing target. | Whole-source grouping can produce a larger packet, leaving output and token exposure without a strict packet invariant. | A persisted hard cap or a documented maximum whole-source overshoot is enforced by validation and tests. |
| TD-017 | Low | PDF image resampling lacks a comparable production before/after measurement. | Edge and ReportLab share the 1600×1000, quality-82 print projection, a 50 MiB soft budget, and visual smoke coverage. Production readability, first-render size, and latency have not been compared under a stable input. | An image-heavy report supplies comparable size, latency, and rendered-page evidence within the readability and size envelope. |
| TD-019 | Medium | Narrative continuity and inline evidence references are not fully machine-bounded. | Structured evidence IDs validate, while prose can mention evidence outside featured events and `change_from_prior` can select a non-adjacent report. | Inline item IDs validate against featured-event evidence, and continuity binds to the immediately preceding eligible report and claims. |
| TD-020 | High | **Hermes integration:** scheduled evaluators cannot route per-request hooks to the task-specific child ledger. | Direct hooks retain terminal lineage. The [2026-08-25 scheduled run](completed-2026-08-25-morning-report-acceptance.md) emitted no task-routed leaves and required aggregate import. | An audited job-environment mapping yields complete pre/post/error leaves and an exact child ledger for a scheduled Hermes evaluator. |
| TD-021 | Medium | **Codex/OpenClaw integrations:** usage adapters lack sanitized fixtures from identified real host versions. | Synthetic cumulative-counter and SQLite schema-v17 fixtures cover audited layouts; host-format changes remain unverified against real samples. | Minimal secret-free fixtures carry explicit host versions and pass fail-closed parser regressions. |
| TD-023 | Medium | **Host integration:** provider cost and tool-call token splits are unavailable when the host omits them. | The ledger records omitted fields as `unobservable`; this limits cost comparison while preserving accounting truth. | Exposed host fields are retained exactly. Any derived value is versioned, provenance-bound, and labeled as an estimate; unavailable fields remain unobservable. |
| TD-025 | High | Workflow mutators can retain stale run state while waiting for the edition lock. | Begin, analysis preparation, assembly, enrichment, finalization, and index adoption do not all re-read attempt and artifact lineage inside one lock boundary. | Every mutator revalidates current attempt and lineage under the lock; long work commits through attempt/context-hash compare-and-swap with restart-race coverage. |
| TD-026 | Medium | **Codex/OpenClaw integrations:** durable-log imports lack task-selective scope. | OpenClaw import reads every usage-bearing row in the supplied audited per-agent database; Codex JSONL uses a fixed 64 MiB cap and no session/time filter. | Agent, session, and time filters bound both imports; Codex parsing streams bounded records, and absent provider-attempt counts remain unknown. |
| TD-029 | High | Compiler-owned event IDs lack a verified cross-item continuation mechanism. | Python derives IDs from authorized current items, while a new article that updates an older event has no safe lineage declaration. | A bounded prior-event candidate set and validated update/supersession field support legitimate continuation and reject forged history. |
| TD-030 | High | **Hermes integration:** delegated workers inherit the parent toolset. | Current `delegate_task` requests retain browser, search, and delegation schemas even when packet and output paths are narrow. Core packet validation still constrains accepted data. | Hermes supports per-child least-privilege toolsets, and delegated request-schema tests confirm the intended narrow capability set. |
| TD-031 | High | Controlled optimization evidence has not met the stable quality and lifecycle gate. | The v2 trial reduced analysis tokens by 70.1% and missed quality floors. The 2026-08-25 run reached 37/45 under changed inputs with deadline and open-call qualifications. | Single-variable batch-size and phase-model trials pass quality floors, and a comparable lifecycle finishes within budget with zero open calls. |
| TD-032 | Medium | **Host orchestration:** root-like provider turns remain a context and tool-schema concentration. | Available sessions differ in model, snapshot, and recovery path; observed call totals span 33 to 108, preventing a causal root-turn comparison. | Comparable per-leaf measurements classify repeated context, tool schema, and polling; accepted changes reach at most 51 calls with stable quality and zero open lifecycles. |
| TD-033 | High | **Hermes integration:** successful one-shot work can lack terminal hook events. | A v2 control recorded 24 attempts and 22 token-accounted terminal observations. The missing terminals make the task total a lower bound; core finalization correctly preserves `partial`. | Cancellation or transport terminals, or a durable reconciliation source, close every attempted request; unresolved fields remain unknown and the task remains partial. |

## Resolved Items

Resolved during the 2026-08-28 documentation and release cleanup:

- TD-001: the tracked `skills/signaltrail/` snapshot was rebuilt from the allowlisted canonical
  sources. Package validation and the repository gate verify the synchronized release copy.

Resolved in the 2026-08-02 audit:

- Time-sensitive monitor fixtures use an injected clock.
- JSON, text, and byte writers share collision-safe atomic replacement.
- Immutable JSON creation rejects concurrent overwrite.
- Typed JSON-object reads and CLI JSON output use shared helpers.
- Maintained Python definitions carry semantic Chinese input/output contracts, with AST and inline
  rationale checks for the documented boundaries.

Resolved during the
[2026-08-05 regeneration](completed-2026-08-05-morning-report-regeneration.md):

- Formal report eligibility excludes retained monitor history.
- Successful live acquisition precedes deduplicated monitor tail fallback.
- Retry merges preserve the original source-group position.
- Draft validation uses a validation-only identity on an unchanged input.
- Evaluation finalization binds to canonical source and contract through a shell-neutral launcher.
- The canonical SignalTrail runtime was verified, and legacy skill copies were retired.

Resolved during the
[2026-08-23 LLM-usage audit](completed-2026-08-23-llm-usage-optimization-implementation.md):

- Immutable local usage events, allowlisted host adapters, unknown-preserving summaries, and
  verified `run.llm_usage` task bindings omit raw model content.
- Independent evaluation scheduling is single-run and idempotent under the canonical SignalTrail
  skill identity.
- Evaluation saves recover interrupted current revisions, preserve historical revisions, and
  prevent stale evaluators from advancing current projections.
- Phase, batch, role, run, repair, evaluation, and hashed parent-session lineage are explicit.
- Observed-plus-reserved budget gates cover brief, analysis, repair, and evaluation stages;
  unmetered values remain null.
- Semantic cache separates content-stable fields from run-relative state and records versioned
  invalidation reasons while preserving plan order.
- Stable analysis-domain IDs retain superseded history and close orphaned watchers safely.
- Brief and analysis rejection receipts, evaluation preflight, scheduler reconciliation, bounded
  evaluator attempts, and the hash-bound evaluator dossier are immutable.
- Brief and analysis packets are self-contained and receiver-validated through nested output
  schemas and explicit Python-owned fields.
