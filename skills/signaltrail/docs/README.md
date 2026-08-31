# Engineering Records

**Purpose:** Catalog the canonical engineering records and their authority, status, and translations.
**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-08-23

This directory is SignalTrail's engineering system of record. `AGENTS.md` points here;
it does not duplicate the content. English records are canonical, with matching Chinese
translations under [`zh-CN/`](zh-CN/README.md).

## Catalog

| Record | Question answered | Status |
| --- | --- | --- |
| [Architecture](../ARCHITECTURE.md) | What are the system boundaries and dependency directions? | Verified |
| [Engineering principles](design-docs/core-beliefs.md) | Which principles govern repository boundaries? | Verified |
| [Design catalog](design-docs/index.md) | Which design records are authoritative or detailed? | Verified |
| [Execution plans](exec-plans/index.md) | What work is active, completed, or tracked as debt? | Verified |
| [Technical-debt tracker](exec-plans/tech-debt-tracker.md) | Which known gaps still need a decision or refactor? | Verified |
| [Product-spec catalog](product-specs/index.md) | Where are user and report contracts defined? | Verified |
| [Verification matrix](quality-score.md) | Which checks exist and which gaps remain open? | Verified |
| [Operations runbook](../references/runbook.md) | How are runs operated and recovered? | Verified detail |
| [Editorial policy](../references/editorial-policy.md) | What evidence and selection rules apply? | Verified detail |
| [System design detail](../references/system-design.md) | What are the detailed data and state contracts? | Verified detail |
| [LLM usage operations](../references/llm-usage.md) | How are host calls metered without storing prompts, responses, or secrets? | Verified detail |

## Record Status

- **Draft:** under active review; not yet a decision source.
- **Verified:** checked against current code and tests on the stated date.
- **Historical:** retained for rationale, not current behavior.
- **Generated:** produced mechanically from its canonical source; direct edits are discarded.

If a document and implementation disagree, follow the precedence in
[`AGENTS.md`](../AGENTS.md) and fix the document in the same change.

## Documentation Maintenance

Each change starts in the smallest authoritative English record and includes its matching
`docs/zh-CN/` translation. Scope or authority changes also update the relevant catalog, status,
owner, and verification date. Overviews link to detailed records so that policy has one maintained
home. CI runs `scripts/check_docs.py` and `tests/test_docs.py` for structural verification.

Durable design decisions live in `design-docs/`; multi-step implementation records live in
`exec-plans/`. Completed plans retain their rationale under a dated name. README and product
contracts describe user-visible behavior, while operating detail remains in `references/`.

Maintained Python functions and classes carry concise semantic Chinese logic/input/output notes.
Inputs identify their upstream source and consumed information; outputs state what the result
means to the next stage. Type-only or function-name paraphrases fail
`python scripts/check_code_comments.py`. Keep inline comments focused on non-obvious decisions.

## Language Policy

English is the canonical engineering record shared by automation tools and contributors. Chinese
translations are reviewable mirrors for maintainers and are updated in the same change. A
translation cannot introduce a rule absent from English.
