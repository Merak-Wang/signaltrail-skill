# 2026-08-23 LLM Usage and Optimization Implementation

**Purpose:** Record the completed repository implementation and qualified external evidence from
the active auditable-usage and daily-report optimization plan without overstating partial results.
**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-08-24

## Outcome

The repository implementation is complete for the plan's deterministic and testable scope:

- a host-neutral immutable usage ledger, strict schema, Hermes/Codex/OpenClaw adapters, CLI, safe
  task/run bindings, call lifecycle validation, hashed lineage, and unknown-preserving summaries;
- explicit phase, batch, Agent role, run, repair, evaluation, and parent-session correlation, with
  packet hints, hook environment inputs, durable-import flags, and coverage diagnostics;
- observed-plus-reserved token gates before brief, analysis, repair, and evaluator phases;
- stable analysis-domain identities with history-preserving supersession and watch closure;
- semantic-cache separation between stable translated title/TL;DR and run-relative
  importance/status, plus reasoned metrics and versioned targeted invalidation;
- immutable structured rejection receipts and a hard maximum of one repair for brief and analysis;
- self-contained brief/analysis output schemas shared by model packets and receivers, including
  nested types, enums, additional-property boundaries, and Python-owned field exclusions;
- current-report evaluator preflight, read-only Hermes Cron reconciliation, at most two total
  attempts, a parent-linked evaluator usage task, and an immutable report/index-hash dossier;
- deferred PDF delivery, same-revision reuse, print-bound image resampling, explicit render/size
  receipts, a 50 MiB soft budget, and Poppler page-raster regression coverage.

The active root [measurement plan](../../plan.md) remains authoritative for the two instrumented
2026-08-23 runs and for external acceptance. This implementation record does not claim the
combined run was a latency/quality success.

## Qualified External Acceptance

The immutable `projection-ab-v2` experiment held one index, clean skeleton, embedded cache
decision snapshot, model/provider, output contract, and file-only tool surface constant. Brief
packet bytes fell 41.6% and analysis packet bytes fell 79.5%. Both analysis arms passed on their
first submission and compiled to reports with zero current errors or warnings. The projected
analysis used 5 calls and 174,588 exact tokens versus 9 calls and 584,418 exact tokens for control:
a 44.4% call reduction and 70.1% token reduction. Provider wall time was effectively unchanged
(+0.5%), and projected output tokens increased 11.8%, so this is accepted only as an analysis-phase
resource result.

The brief comparison remains qualified because the control task has two unclosed API lifecycles;
its 658,525 known tokens are a lower bound, while projected has 228,465 exact tokens. Both reports
passed validation. The first two counterbalanced evaluator cells scored 31/45 with `selective`
continuity; the other two cells and one fresh recovery initially returned `api_request_error`
before creating output. After provider recovery on 2026-08-24, append-only `resume-2` lifecycles
completed control/dossier and projected/full on their first submissions at 33/45 with `accept`
continuity. The complete matrix therefore scores 31/33/33/31. Every cell is below the recorded
34/45 and dimension-floor guardrails. Control dossier usage was exact at 227,083 tokens versus a
1,419,766 known full subtotal, while projected dossier had a 736,545 known subtotal versus 489,658
exact full usage. The crossed directions reject dossier parity, stable savings, and quality
acceptance rather than merely leaving them unknown.

Recovery evidence passed independently: a persisted interrupted evaluation short-circuited both
preflight and scheduling after completion without creating a host job, and real Hermes job
`c71034b5b9bb` reconciled read-only from persisted `scheduled` to `failed / host_job_error`.
The first runner projection's object-sharing fault was recovered from the original hash-bound model
drafts without another model call; the faulty projection remained preserved rather than overwritten.

## External Acceptance Still Required

Repository tests cannot substitute for provider and host evidence. The following remain open in
the technical-debt tracker:

- evaluator per-request hooks require Hermes job-specific environment/plugin routing (TD-020);
- a genuinely narrow child tool schema requires Hermes per-delegation toolset support (TD-030);
- the controlled A/B established one exact analysis-phase result and completed its evaluator
  matrix, but that matrix failed the quality floors; independent batch/model trials, quality
  remediation, and multi-run stability remain required (TD-031); and
- isolated analysis calls fell from 9 to 5, but root-like provider-turn reduction still requires
  root-session leaf evidence (TD-032).

These are deliberately not marked complete or inferred from unit tests.

## Verification

The implementation is accepted only when the repository's full gate passes:

```powershell
python -m pytest
python -m ruff check .
python -m compileall -q src tests scripts
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

Focused regression coverage lives in `test_llm_usage*.py`, `test_usage_cli.py`,
`test_llm_budget.py`, `test_evaluation.py`, `test_authoring.py`, `test_semantics.py`,
`test_reporting.py`, `test_architecture.py`, and `test_desktop_delivery.py`.

## Recovery

All new authoritative records are append-only or atomically replaceable derived state. Rejected
optimization experiments retain their measured ledger/report/evaluation artifacts. Rollback of a
projection or routing change must rebuild from canonical root sources; generated or installed
snapshots must never be edited as a recovery shortcut.
