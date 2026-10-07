import hashlib
import json

import pytest

from signaltrail.config import resolve_data_dir, resolve_hermes_data_dir
from signaltrail.runtime import (
    bind_data_root,
    data_root_registry_path,
    load_bound_data_root,
    require_data_root_path,
    validate_run_data_root,
)


def test_hermes_launcher_reuses_renamed_registry_without_affecting_regular_cli(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / "hermes"
    old_root = hermes_home / "daily-intelligence"
    old_root.mkdir(parents=True)
    (hermes_home / "state").mkdir()
    (hermes_home / "state" / "daily-intelligence-data-root.json").write_text(
        json.dumps({"schema_version": "1.0", "data_root": str(old_root)}),
        encoding="utf-8",
    )
    old_root.rename(hermes_home / "signaltrail")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.delenv("SIGNALTRAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)

    assert resolve_hermes_data_dir() == (hermes_home / "signaltrail").resolve()
    assert resolve_data_dir() == (tmp_path / "local" / "signaltrail").resolve()
    assert load_bound_data_root(hermes_home) == old_root.resolve()


def test_explicit_app_adoption_remaps_only_registered_previous_paths(monkeypatch, tmp_path):
    app_home = tmp_path / "local" / "signaltrail"
    old_root = tmp_path / "legacy-data"
    new_root = tmp_path / "current-data"
    old_index = old_root / "indexes" / "2026-09-23" / "morning-r1.json"
    new_index = new_root / "indexes" / "2026-09-23" / "morning-r1.json"
    run_path = new_root / "runs" / "2026-09-23" / "morning.json"
    old_index.parent.mkdir(parents=True)
    new_index.parent.mkdir(parents=True)
    run_path.parent.mkdir(parents=True)
    old_index.write_text('{"items":[]}\n', encoding="utf-8")
    new_index.write_bytes(old_index.read_bytes())
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))

    bind_data_root(old_root, app_home)
    bound = bind_data_root(new_root, app_home, adopt=True)
    run = {
        "data_root": str(old_root),
        "artifacts": {"index_path": str(old_index)},
    }

    assert bound["previous_data_root"] == str(old_root.resolve())
    assert data_root_registry_path(app_home).is_file()
    assert resolve_data_dir() == new_root.resolve()
    validate_run_data_root(run, run_path, new_root)
    assert run["data_root"] == str(new_root.resolve())
    assert run["artifacts"]["index_path"] == str(new_index.resolve())
    assert require_data_root_path(old_index, new_root, "Run index") == new_index.resolve()


def test_legacy_paths_are_not_guessed_without_explicit_adoption(monkeypatch, tmp_path):
    app_home = tmp_path / "local" / "signaltrail"
    legacy = tmp_path / "daily-intelligence"
    current = tmp_path / "signaltrail"
    legacy.mkdir()
    current.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("SIGNALTRAIL_DATA_DIR", raising=False)
    monkeypatch.delenv("DAILY_INTEL_DATA_DIR", raising=False)

    assert resolve_data_dir() == app_home.resolve()
    with pytest.raises(ValueError, match="outside the active data root"):
        require_data_root_path(legacy / "runs" / "old.json", current, "Run manifest")


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

    assert resolve_hermes_data_dir() == new_root.resolve()
    validate_run_data_root(run, run_path, new_root)

    assert run["data_root"] == str(new_root.resolve())
    assert run["artifacts"]["index_path"] == str(new_index.resolve())
    assert run["artifacts"]["enrichment"]["selection_path"] == str(
        (new_root / "state" / "selection.json").resolve()
    )
    assert require_data_root_path(old_index, new_root, "Run index") == new_index.resolve()
    assert old_index.read_bytes() == new_index.read_bytes()
