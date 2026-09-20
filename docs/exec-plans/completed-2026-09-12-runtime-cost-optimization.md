# Runtime Cost and Latency Optimization

**Purpose:** Record the deterministic runtime optimizations, offline evidence and measurement limits.
**Status:** Historical
**Owner:** Repository maintainers
**Last verified:** 2026-09-12

## Delivered behavior

The implementation reduces repeated input and local work while retaining the configured models,
source coverage, report schema, evidence restrictions and evaluation requirements. The baseline
is commit `7eb422c`. No provider request or production publication was needed for this change.

| Area | Change | Expected effect |
| --- | --- | --- |
| Image acquisition | Consume complete prefetch windows and share one HTTP client/thread pool throughout materialization. Preserve URL deduplication, per-domain limits, fallbacks and budgets. | Fewer sequential download barriers, connection setups and cache writes. Fully warm caches allocate no network resources. |
| Coordinator input | Write a separate immutable coordinator projection, bounded by the existing analysis-state policy. Omit cached brief prose, Python-only fingerprints and duplicated authorized-item lists. | Less repeated model input as history and accepted briefs accumulate. Full context remains authoritative for Python. |
| Semantic reuse | Use extractor-owned body-text SHA-256 instead of the storage path when available. Keep the legacy path fingerprint for old records. | Relocating identical evidence no longer invalidates approved translations/summaries. Changed evidence and language/evaluation checks still invalidate reuse. |
| Evidence selection | Union enriched items outside the normal candidate prefix into context without changing index order or the Top15 brief plan. | Body retrieval for a lower-ranked selected item is available to analysis rather than wasted. |
| Recovery | Save the accepted enrichment selection before work and the completed extraction payload before index commit. Resume the same operation, verify its binding, and reuse an already committed matching revision. | Index/context commit failures no longer require repeating completed extraction. Failures and verification states remain explicit. |
| Authoring inputs | Create immutable brief/analysis inputs, bind packet hashes and authorized IDs to new sessions, preserve analysis start time on idempotent preparation, and reject replaced inputs at acceptance/recovery. | Prevent accepted model output being mixed with changed evidence or triggering avoidable downstream repair. |
| Workflow concurrency | Reread run attempt/state/artifact lineage inside edition locks, including batch/metrics acceptance and verified-index adoption. Reject enrichment/index replacement after authoring dispatch. | Stale operations cannot overwrite a restarted run or change dispatched evidence. |
| Usage ledger | Reuse a validated event snapshot only within one thread's locked hook transaction. Drop it on exit and verify disk again on the next operation. | Less repeated event-file I/O without weakening unknown values, task sealing or cross-operation corruption detection. |

## Offline evidence

These measurements describe work counts or serialized bytes, not production token billing or
end-to-end delivery time. Timings from test execution are not runtime performance estimates.

| Probe | Before | After | Interpretation |
| --- | --- | --- | --- |
| 36 distinct cold image URLs; global concurrency 12 | 25 batches: 12, then 24 single-image batches | 3 batches: 12, 12, 12 | Download batches/cache checkpoints fall by 88%; attached count and order are preserved. |
| Connection/thread pools for that image run | 25 pairs | 1 pair | Resources span the full operation and close at the end; the warm rerun creates none. |
| Ten distinct Hermes post-hook fixtures, each reporting 3 input and 2 output tokens | 110 validated event-file reads | 55 reads | 50% fewer reads; the synthetic accounted total stays 50. This fixture has usage observations, not pre/error lifecycle events. |
| Coordinator with 300 active thesis rows and 300 watcher rows, no current candidates | Full context about 755 KB | Projection about 45 KB | About 94% fewer serialized bytes in this deliberately history-heavy fixture. Current report inputs have different sizes. |

The history probe repeats `A bounded historical claim. ` twenty times per claim and
`A public signal to check. ` twenty times per signal; each row has a stable ID, active status
and the geopolitics domain. The thesis and watcher arrays each contain 300 rows. Byte counts
vary slightly with temporary paths. Production candidates are retained; the reduction must
not be extrapolated to every edition or converted into an assumed token or price saving.

Behavior regressions live in `test_media.py`, `test_context.py`, `test_semantics.py`,
`test_content.py`, `test_authoring.py`, `test_workflow.py` and
`test_llm_usage_ledger_integrity.py`. They exercise cold/warm images, moved evidence, state
bounds, rank-29 enrichment, orphan packets, input replacement, repeated analysis preparation,
interrupted index commits, extraction/context failures, nine pre-lock races and next-operation
ledger corruption detection. Final validation passed: **515 tests**, Ruff, compileall,
Chinese code-comment checks, documentation checks and `git diff --check`.

## Remaining limits

- A process killed before the complete extraction checkpoint can repeat that bounded acquisition
  stage. When the run deadline has passed and no completed checkpoint exists, resume skips new
  acquisition and records budget exhaustion. Existing stale edition-lock files still require the
  runbook's ownership check before manual removal.
- Legacy records without a body digest keep path-based cache identity. Legacy sessions lacking
  packet hashes do not acquire a historical integrity guarantee retroactively. New sessions bind
  their current inputs; normal new contexts and packets use the strengthened contract.
- Completed extraction checkpoints add one durable copy of the index payload per enrichment
  operation. Hash checks add local reads. These costs buy recovery and consistent evidence.
- This change does not convert browser index adapters to an async shared-context API, add a
  persistent report/archive catalog, or provide a paired JSON/Markdown report transaction.
  Those changes need separate adapter, invalidation and crash-boundary coverage.
- Per-phase model routing, narrower host toolsets, authoring-batch experiments and reviewer
  prompt changes still require host support and a frozen quality comparison. No production
  dollar saving, total token reduction, delivery-time reduction or unchanged model quality is
  asserted from these offline probes. See [remaining technical debt](tech-debt-tracker.md).

[中文](../zh-CN/exec-plans/completed-2026-09-12-runtime-cost-optimization.md)
