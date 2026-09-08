# Development

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-08

This guide covers local changes and test selection. Read [architecture](../ARCHITECTURE.md)
for code ownership and [AGENTS.md](../AGENTS.md) for invariants. [中文](zh-CN/development.md)

## Setup and checks

```sh
python -m venv .venv
# Activate .venv in your shell, then:
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m compileall -q src tests scripts
python scripts/check_code_comments.py
python scripts/check_docs.py
git diff --check
```

Unit tests use temporary data roots and fake network/host responses. They need no production
data, browser login, Notion credentials, or model calls. CI runs on Windows and Ubuntu with
Python 3.11 and 3.12. Run a focused group while editing, then the full gate before submitting.

| Change | Focused tests |
| --- | --- |
| CLI options, aliases, dispatch | `tests/test_cli.py` |
| Source configuration and filtering | `tests/test_config.py`, `tests/test_normalize.py`, `tests/test_collector.py` |
| Feed, monitor, clustering | `tests/test_feeds.py`, `tests/test_monitor.py`, `tests/test_clustering.py` |
| Context and writing | `tests/test_context.py`, `tests/test_authoring.py`, `tests/test_semantics.py` |
| Report contract and persistence | `tests/test_reporting.py`, `tests/test_report_persistence.py`, `tests/test_storage.py` |
| Run lifecycle and evaluation | `tests/test_workflow.py`, `tests/test_evaluation_workflow.py`, `tests/test_evaluation.py` |
| Browser verification and Notion | `tests/test_verification.py`, `tests/test_notion.py` |
| Local output and media | `tests/test_desktop_delivery.py`, `tests/test_content.py`, `tests/test_media.py` |
| Usage and host integration | `tests/test_llm_usage*.py`, `tests/test_usage_cli.py`, `tests/test_hermes_runner.py` |
| Packaging and documentation | `tests/test_hermes_package.py`, `tests/test_docs.py`, `tests/test_code_comments.py` |

Shared report setup lives in `tests/report_helpers.py`. Keep a fixture local unless several
tests need the same setup. Parameterize cases that differ only in inputs and expected outcomes;
keep distinct failure and recovery scenarios readable. Do not test prose by matching sentences
or delete regression coverage merely to reduce the test count.

## Names and modules

| Name | Use |
| --- | --- |
| SignalTrail / `signaltrail` | Product, skill ID, preferred CLI |
| `daily-intel` | Supported CLI alias; generated commands and old integrations may still use it |
| `daily_intelligence` | Existing Python import package |
| `daily-intelligence-skill` | Existing Python distribution name |
| `DAILY_INTEL_*`, data directories, report IDs | Persisted compatibility surface; change only with a tested migration |

Use verbs for operations (`collect_sources`, `save_report`) and nouns for data.
CLI handlers use `handle_<command>` and live in `commands/`; they translate options into domain
calls and output, while `cli.py` loads configuration and binds the data root. Shared output
and the typed context live in `commands/common.py`. Keep domain code independent of CLI modules.

Split a module when a coherent responsibility can be named and tested independently.
Avoid creating generic `manager`, `helper`, or `utils` modules for unrelated operations.
`reporting.py` owns compilation/validation and `reports.py` owns storage/Markdown today;
their remaining large functions are TD-002, not a reason to add another ambiguous report module.

Maintained functions and classes use Chinese docstrings explaining the operation, the source
and consumed content of inputs, and the result's downstream meaning. Keep these concrete:
“returns the validated index path” is useful; “returns the result of processing” is not.
Add inline comments for non-obvious safety, state, compatibility, or concurrency choices.

## Documentation and releases

README introduces the product and first run. This directory holds usage, development, the
roadmap, and dated engineering history. `references/` owns detailed runtime policy;
`SKILL.md` contains the agent procedure and conditional links to those references.

Each maintained engineering record states its purpose, status, owner, and verification date.
English records and their Chinese mirrors change together. The documentation index catalogs
single-language runtime references and historical/generated records. Keep one home for each
rule. Write about actual behavior with short examples; remove slogans, repeated feature lists,
and speculative implementation detail. Mark proposals Draft and completed run records Historical.

The documentation checker verifies local links, images, translation pairs, metadata, and current
record dates. Historical dates remain historical; they do not expire after six months.
The comment checker covers the maintained source modules and maintenance scripts.

Edit canonical sources. Only rebuild `skills/signaltrail/`, `dist/`, or `build/` for an explicit
release request, using `scripts/build_hermes_skill.py`. Its Git-tracked allowlist excludes runtime
data and credentials. A repository refactor does not update an installed skill automatically.

Unresolved issues belong in the [technical-debt tracker](exec-plans/tech-debt-tracker.md), with
evidence and an exit condition. Record released changes in [CHANGELOG.md](../CHANGELOG.md).
