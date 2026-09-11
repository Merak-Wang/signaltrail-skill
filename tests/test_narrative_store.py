from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daily_intelligence.narrative_store import load_artifact, save_artifact


def test_immutable_pair_and_markdown_tampering(tmp_path):
    first = save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "中文\n\n正文\n")
    assert save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "中文\n\n正文\n") == first
    second = save_artifact(tmp_path, "session", "ledger", {"n": 2}, {}, "新修订\n")
    assert first != second
    assert load_artifact(first, tmp_path)["payload"] == {"n": 1}
    (first.parent / "ledger-r1" / "artifact.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Markdown changed"):
        load_artifact(first, tmp_path)


def test_interruption_before_atomic_directory_commit_has_no_partial_artifact(tmp_path, monkeypatch):
    original = Path.rename

    def fail(path, target):
        if path.name.endswith(".tmp"):
            raise OSError("interrupted before commit")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError):
        save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    directory = tmp_path / "narratives/session"
    assert not list(directory.glob("ledger-r*"))
    assert not list(directory.glob("*.tmp"))


def test_interruption_after_pair_commit_repairs_index_on_replay(tmp_path, monkeypatch):
    import os

    original = os.link

    def fail(*args, **kwargs):
        raise OSError("index interrupted")

    monkeypatch.setattr("daily_intelligence.narrative_store.os.link", fail)
    with pytest.raises(OSError):
        save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    directory = tmp_path / "narratives/session"
    assert (directory / "ledger-r1/artifact.json").is_file()
    assert (directory / "ledger-r1/artifact.md").is_file()
    monkeypatch.setattr("daily_intelligence.narrative_store.os.link", original)
    repaired = save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    assert repaired.name == "ledger-r1.json"
    assert not (directory / "ledger-r2").exists()


def test_concurrent_writers_never_replace_a_committed_revision(tmp_path):
    def write(n):
        try:
            return save_artifact(tmp_path, "session", "ledger", {"n": n}, {}, str(n))
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(write, range(8)))
    saved = [p for p in paths if p]
    assert saved and len(saved) == len(set(saved))
    for path in saved:
        value = load_artifact(path, tmp_path)
        markdown = path.parent / f"ledger-r{value['revision']}" / "artifact.md"
        assert markdown.read_text(encoding="utf-8") == str(value["payload"]["n"])


def test_parent_paths_cannot_escape_the_data_root(tmp_path):
    outside = tmp_path.parent / "outside-evidence.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError):
        save_artifact(tmp_path, "session", "ledger", {}, {"evidence": outside})


def test_transient_windows_directory_lock_retries_same_immutable_revision(tmp_path, monkeypatch):
    original = Path.rename
    attempts = []

    def temporarily_locked(path, target):
        attempts.append(target)
        if len(attempts) < 3:
            error = PermissionError("temporary scanner lock")
            error.winerror = 5
            raise error
        return original(path, target)

    monkeypatch.setattr(Path, "rename", temporarily_locked)
    monkeypatch.setattr("daily_intelligence.narrative_store.time.sleep", lambda _: None)
    saved = save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    assert len(attempts) == 3 and len(set(attempts)) == 1
    assert saved.name == "ledger-r1.json"
    assert load_artifact(saved, tmp_path)["payload"] == {"n": 1}


def test_persistent_windows_directory_lock_fails_after_bounded_retries(tmp_path, monkeypatch):
    attempts = []

    def always_locked(path, target):
        attempts.append(target)
        error = PermissionError("persistent access failure")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "rename", always_locked)
    monkeypatch.setattr("daily_intelligence.narrative_store.time.sleep", lambda _: None)
    with pytest.raises(PermissionError, match="persistent access failure"):
        save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    assert len(attempts) == 5
    directory = tmp_path / "narratives/session"
    assert not list(directory.glob("ledger-r*"))
    assert not list(directory.glob("*.tmp"))


def test_retry_never_overwrites_a_destination_created_after_the_first_attempt(
    tmp_path, monkeypatch,
):
    def collision(path, target):
        target.mkdir()
        (target / "existing.txt").write_text("keep", encoding="utf-8")
        error = PermissionError("temporary scanner lock")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "rename", collision)
    monkeypatch.setattr("daily_intelligence.narrative_store.time.sleep", lambda _: None)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        save_artifact(tmp_path, "session", "ledger", {"n": 1}, {}, "paired")
    directory = tmp_path / "narratives/session/ledger-r1"
    assert (directory / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert not (directory / "artifact.json").exists()
