import hashlib
import json

import pytest

from signaltrail.config import resolve_data_dir
from signaltrail.runtime import (
    bind_data_root,
    data_root_registry_path,
    load_bound_data_root,
    require_data_root_path,
    validate_run_data_root,
)


def test_renamed_legacy_data_root_and_registry_are_reused(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes"
    old_root = hermes_home / "daily-intelligence"
    run_path = old_root / "runs" / "2026-09-23" / "morning.json"
    report_path = old_root / "reports" / "2026-09-23" / "morning-r1.json"
    run_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True)
    report_bytes = b'{"report_id":"historic"}\n'
    report_path.write_bytes(report_bytes)
    (hermes_home / "state").mkdir()
    (hermes_home / "state" / "daily-intelligence-data-root.json").write_text(
        json.dumps({"schema_version": "1.0", "data_root": str(old_root)}),
        encoding="utf-8",
    )
    old_root.rename(hermes_home / "signaltrail")
    new_root = hermes_home / "signaltrail"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)

    assert resolve_data_dir() == new_root.resolve()
    assert load_bound_data_root(hermes_home) == new_root.resolve()
    result = bind_data_root(new_root, hermes_home)
    assert result["status"] == "bound"
    assert data_root_registry_path(hermes_home).is_file()
    assert (hermes_home / "state" / "daily-intelligence-data-root.json").is_file()
    assert (new_root / "reports" / "2026-09-23" / "morning-r1.json").read_bytes() == report_bytes


def test_historical_run_paths_are_remapped_in_memory_only(tmp_path):
    hermes_home = tmp_path / "hermes"
    old_root = hermes_home / "daily-intelligence"
    run_path = old_root / "runs" / "2026-09-23" / "morning.json"
    index_path = old_root / "indexes" / "2026-09-23" / "morning-r1.json"
    context_path = old_root / "context" / "2026-09-23" / "morning-r1.json"
    index_path.parent.mkdir(parents=True)
    context_path.parent.mkdir(parents=True)
    run_path.parent.mkdir(parents=True)
    index_path.write_text('{"items":[]}\n', encoding="utf-8")
    context_path.write_text('{"edition":"morning"}\n', encoding="utf-8")
    run = {
        "data_root": str(old_root),
        "artifacts": {
            "index_path": str(index_path),
            "selection": {"session_path": str(context_path)},
        },
    }
    run_bytes = json.dumps(run, ensure_ascii=False).encode("utf-8")
    run_path.write_bytes(run_bytes)
    old_root.rename(hermes_home / "signaltrail")
    new_root = hermes_home / "signaltrail"
    current_run_path = new_root / run_path.relative_to(old_root)
    manifest_digest = hashlib.sha256(current_run_path.read_bytes()).hexdigest()
    index_digest = hashlib.sha256(
        (new_root / index_path.relative_to(old_root)).read_bytes()
    ).hexdigest()

    validate_run_data_root(run, current_run_path, new_root)

    assert run["data_root"] == str(new_root.resolve())
    assert run["artifacts"]["index_path"] == str(
        (new_root / index_path.relative_to(old_root)).resolve()
    )
    assert run["artifacts"]["selection"]["session_path"] == str(
        (new_root / context_path.relative_to(old_root)).resolve()
    )
    assert require_data_root_path(index_path, new_root, "Run index").is_file()
    assert hashlib.sha256(current_run_path.read_bytes()).hexdigest() == manifest_digest
    assert hashlib.sha256(
        (new_root / index_path.relative_to(old_root)).read_bytes()
    ).hexdigest() == index_digest


def test_explicit_migration_binding_maps_paths_while_legacy_copy_remains(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes"
    old_root = hermes_home / "daily-intelligence"
    new_root = hermes_home / "signaltrail"
    old_index = old_root / "indexes" / "2026-09-23" / "morning-r1.json"
    new_index = new_root / "indexes" / "2026-09-23" / "morning-r1.json"
    run_path = new_root / "runs" / "2026-09-23" / "morning.json"
    old_index.parent.mkdir(parents=True)
    new_index.parent.mkdir(parents=True)
    run_path.parent.mkdir(parents=True)
    old_index.write_text('{"items":["old"]}\n', encoding="utf-8")
    new_index.write_bytes(old_index.read_bytes())
    (hermes_home / "state").mkdir()
    data_root_registry_path(hermes_home).write_text(
        json.dumps({
            "schema_version": "1.0",
            "data_root": str(new_root),
            "previous_data_root": str(old_root),
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)
    run = {
        "data_root": str(old_root),
        "artifacts": {
            "index_path": str(old_index),
            "enrichment": {"selection_path": str(old_root / "state" / "selection.json")},
        },
    }

    assert resolve_data_dir() == new_root.resolve()
    validate_run_data_root(run, run_path, new_root)

    assert run["data_root"] == str(new_root.resolve())
    assert run["artifacts"]["index_path"] == str(new_index.resolve())
    assert run["artifacts"]["enrichment"]["selection_path"] == str(
        (new_root / "state" / "selection.json").resolve()
    )
    assert require_data_root_path(old_index, new_root, "Run index") == new_index.resolve()
    assert old_index.read_bytes() == new_index.read_bytes()


def test_legacy_path_is_not_guessed_when_both_roots_exist(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes"
    legacy = hermes_home / "daily-intelligence"
    current = hermes_home / "signaltrail"
    legacy.mkdir(parents=True)
    current.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)

    with pytest.raises(ValueError, match="Both legacy and SignalTrail data directories"):
        resolve_data_dir(explicit=None)

    with pytest.raises(ValueError, match="outside the active DAILY_INTEL_DATA_DIR"):
        require_data_root_path(legacy / "runs" / "old.json", current, "Run manifest")
