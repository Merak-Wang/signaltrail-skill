# Repository Verification Matrix

**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-08-28
**Purpose:** Record objective repository checks and link each open gap to its maintained record.

| Area | Automated or versioned evidence | Current gap |
| --- | --- | --- |
| Documentation map | `scripts/check_docs.py` checks canonical records, translations, dates, links, and entry-document size | Detailed runtime references remain primarily Chinese; see [TD-003](exec-plans/tech-debt-tracker.md) |
| Report contract | `schemas/report.schema.json`, report validators, and reporting/architecture tests enforce the current shape | Narrative continuity and inline evidence references need tighter machine bounds; see TD-019 |
| State and persistence | Typed statuses, immutable revisions, atomic writers, and recovery tests cover the main lifecycle | Several mutators can retain stale state while waiting for a lock; see TD-025 |
| Harness boundary | The CLI and packet contracts use explicit paths and host-neutral structured input/output | Automatic evaluator scheduling is currently a Hermes integration, and non-built-in usage adapters require Python integration; see TD-020, TD-021, and TD-026 |
| Usage accounting | Immutable allowlisted events preserve exact, unknown, and unmetered observations without model content | Some providers and hosts do not expose cost or tool-token splits; see TD-023 and TD-033 |
| Rendering and delivery | HTML/PDF projection tests cover desktop delivery, mobile navigation, and printable output | Production-scale PDF size and latency still need a comparable measurement; see TD-017 |
| Packaging | The allowlisted Hermes builder and packaging tests reject runtime data and common secret patterns | The tracked release snapshot was rebuilt from canonical sources on 2026-08-28; later source changes require another explicit release rebuild |
| Maintainability | Static analysis, compile checks, semantic docstring checks, and the full test suite run in CI | Large validation, rendering, and CLI dispatch functions remain; see TD-002 and TD-004 |

The [technical-debt tracker](exec-plans/tech-debt-tracker.md) owns the detailed evidence and exit
conditions. This matrix changes when a check or repository boundary changes; it does not assign a
subjective score.
