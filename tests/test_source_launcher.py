"""源码绑定入口和轻量任务分派的行为检查。"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "source_launcher", Path(__file__).parents[1] / "scripts/run_signaltrail.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_dispatch_omits_accepted_and_keeps_packet_only(tmp_path):
    accepted = tmp_path / "accepted.json"
    accepted.write_text("{}", encoding="utf-8")
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"date": "2026-11-05", "edition": "daily", "batches": [
        {"packet_path": "first.json", "result_path": str(accepted)},
        {"batch_id": "brief-batch-2", "packet_path": "second.json",
         "draft_result_path": str(tmp_path / "draft.json"),
         "result_path": str(tmp_path / "pending.json")}
    ]}), encoding="utf-8")
    plan = launcher.dispatch_plan(session, tmp_path)
    assert plan["max_workers"] == 3
    assert [task["packet_path"] for task in plan["tasks"]] == ["second.json"]
    assert plan["tasks"][0]["kind"] == "brief"
    assert plan["tasks"][0]["input_command"][-1] == "--include-evidence"
    assert plan["tasks"][0]["preflight_command"][-1] == "--check-only"
    assert plan["coordinator_commands"][0][-1] == "--all"
    assert Path(plan["cli_prefix"][0]).is_absolute()
    assert Path(plan["cli_prefix"][1]).is_absolute()

    assert plan["cli_prefix"][-2:] == ["--data-dir", str(tmp_path.resolve())]


def test_launcher_precedes_installed_copy(tmp_path):
    package = tmp_path / "signaltrail"
    package.mkdir()
    (package / "__init__.py").write_text(
        'raise RuntimeError("installed copy was imported")', encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, str(Path(launcher.__file__)), "--help"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "slides" in result.stdout


def test_analysis_dispatch_uses_file_and_real_assembly_command(tmp_path):
    packet = tmp_path / "analysis-packet.json"
    draft = tmp_path / "analysis-draft.json"
    packet.write_text(json.dumps({"analysis_result_path": str(draft)}), encoding="utf-8")
    (tmp_path / "session.json").write_text(json.dumps({
        "date": "2026-11-05", "edition": "daily"}), encoding="utf-8")
    plan = launcher.dispatch_plan(packet, tmp_path)
    task = plan["tasks"][0]
    assert task["kind"] == "analysis"
    assert task["input_file"] == str(packet)
    assert task["input_command"] is None
    assert task["preflight_command"] is None
    assert task["fresh_context"] and not task["inherit_history"]
    assert plan["coordinator_commands"][0][-2:] == ["--analysis", str(draft)]
    assert "assemble-authoring" in plan["coordinator_commands"][0]


def test_slide_dispatch_uses_pending_packets_and_batch_submission(tmp_path):
    plan_path = tmp_path / "slides-plan-r1.json"
    plan_path.write_text(json.dumps({"kind": "slides-plan", "payload": {
        "batches": [[{"event_id": "one"}], [{"event_id": "two"}]]}}), encoding="utf-8")
    (tmp_path / "slides-result-1-r1.json").write_text("{}", encoding="utf-8")
    packet = tmp_path / "slides-packet-2-r1.json"
    packet.write_text("{}", encoding="utf-8")
    plan = launcher.dispatch_plan(plan_path, tmp_path)
    assert len(plan["tasks"]) == 1
    task = plan["tasks"][0]
    assert task["kind"] == "slides"
    assert task["input_command"][-4:] == ["slides", "input", "--packet", str(packet)]
    assert task["draft_result_path"] == str(tmp_path / "batch-2-draft.json")
    assert task["preflight_command"][-1] == "--check-only"
    assert plan["coordinator_commands"][0][-1] == "--check-only"
    assert plan["coordinator_commands"][1][-2:] == ["--draft-dir", str(tmp_path)]


def test_analysis_dispatch_skips_accepted_analysis(tmp_path):
    packet = tmp_path / "analysis-packet.json"
    packet.write_text(json.dumps({
        "analysis_result_path": str(tmp_path / "analysis-draft.json")}), encoding="utf-8")
    (tmp_path / "session.json").write_text(json.dumps({
        "date": "2026-11-05", "edition": "daily", "status": "ready",
        "analysis_completed_at": "2026-11-05T15:52:06+08:00"}), encoding="utf-8")
    plan = launcher.dispatch_plan(packet, tmp_path)
    assert plan["tasks"] == []
    assert plan["coordinator_commands"] == []


def test_advance_submits_ready_and_dispatches_only_missing_or_invalid(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"date": "2026-11-05", "edition": "daily", "batches": [
        {"batch_id": name, "packet_path": f"{name}.json"}
        for name in ("accepted", "missing", "invalid")]}), encoding="utf-8")
    invalid = tmp_path / "invalid-draft.json"
    invalid.write_text("{}", encoding="utf-8")
    rows = [
        {"batch_id": "accepted", "accepted_path": str(tmp_path / "accepted.json"),
         "draft_path": str(tmp_path / "accepted-draft.json"), "errors": []},
        {"batch_id": "missing", "draft_path": str(tmp_path / "missing.json"),
         "errors": ["missing draft"]},
        {"batch_id": "invalid", "draft_path": str(invalid), "errors": ["missing field"]},
    ]
    calls = []

    def submit(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, json.dumps({
            "accepted": [rows[0]["accepted_path"]], "batches": rows}), "")

    monkeypatch.setattr(launcher.subprocess, "run", submit)
    plan = launcher.advance_dispatch(session, tmp_path)
    assert calls[0][-3:] == ["--run", str(tmp_path / "runs/2026-11-05/daily.json"), "--all"]
    assert len(calls) == 1
    assert [(row["batch_id"], row["action"], row["errors"]) for row in plan["tasks"]] == [
        ("missing", "write", []), ("invalid", "repair", ["missing field"])]
    assert plan["accepted_count"] == 1 and plan["max_workers"] == 3
    assert all(row["fresh_context"] and not row["inherit_history"] for row in plan["tasks"])


def test_advance_slides_reports_broken_accepted_result_without_redispatch(tmp_path, monkeypatch):
    session = tmp_path / "slides-plan-r1.json"
    session.write_text(json.dumps({"kind": "slides-plan"}), encoding="utf-8")
    result_path = tmp_path / "slides-result-1-r1.json"
    result_path.write_text("{}", encoding="utf-8")
    rows = [{"batch_id": 1, "packet_path": "packet.json",
             "draft_path": str(tmp_path / "batch-1-draft.json"),
             "expected_path": str(result_path), "errors": ["wrong packet"]}]
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, json.dumps({
                            "accepted": [], "batches": rows}), ""))
    plan = launcher.advance_dispatch(session, tmp_path)
    assert plan["tasks"] == []
    assert plan["issues"] == [{"batch_id": 1, "errors": ["wrong packet"]}]


def test_advance_brief_cli_preserves_repair_budget(tmp_path):
    from signaltrail.utils import read_json, write_json
    from signaltrail.workflow import begin_authoring
    from tests.test_authoring import _authoring_run, _valid_batch_payload

    data_dir, run = _authoring_run(tmp_path)
    begin_authoring(run, data_dir)
    session_path = Path(read_json(run)["artifacts"]["authoring"]["session_path"])
    batch = read_json(session_path)["batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    draft_path = Path(batch["draft_result_path"])
    valid = _valid_batch_payload(packet)
    write_json(draft_path, {"briefs": []})
    command = [sys.executable, str(Path(launcher.__file__)), "--advance-dispatch",
               str(session_path), "--data-dir", str(data_dir), "--run", str(run)]

    def advance():
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    for _ in range(2):
        plan = advance()
        assert plan["tasks"][0]["action"] == "repair"
        assert plan["tasks"][0]["errors"]
    rejection_dir = Path(batch["packet_path"]).with_name(
        f"{Path(batch['packet_path']).stem}-rejections")
    assert not list(rejection_dir.glob("attempt-*.json"))
    write_json(draft_path, valid)
    assert advance()["tasks"] == []
    accepted = Path(batch["result_path"])
    before = accepted.read_bytes()
    assert advance()["accepted_count"] == 1
    assert accepted.read_bytes() == before


def test_advance_edition_materializes_briefs_then_prepares_analysis(tmp_path):
    from signaltrail.utils import read_json, write_json
    from signaltrail.workflow import begin_authoring
    from tests.test_authoring import _authoring_run, _valid_batch_payload

    data_dir, run = _authoring_run(tmp_path)
    begin_authoring(run, data_dir)
    plan = launcher.advance_edition(run, data_dir)
    assert plan["stage"] == "briefs"
    assert plan["tasks"]
    sizes = [task["input_bytes"] for task in plan["tasks"]]
    assert sizes == sorted(sizes, reverse=True)
    for task in plan["tasks"]:
        original = read_json(Path(task["packet_path"]))
        projected = read_json(Path(task["input_file"]))
        assert projected["output_schema"] == original["output_schema"]
        assert len(projected["candidates"]) == len(original["candidates"])
        assert set(projected["evidence_by_item_id"]) == {
            row["item_id"] for row in original["candidates"]}
        assert "input_args" not in task
        write_json(Path(task["draft_result_path"]), _valid_batch_payload(original))
    analysis = launcher.advance_edition(run, data_dir)
    assert analysis["stage"] == "analysis"
    assert len(analysis["tasks"]) == 1
    task = analysis["tasks"][0]
    assert task["fresh_context"] and not task["inherit_history"]
    assert task["input_command"] is None
    assert Path(task["input_file"]).is_file()
    accepted = read_json(Path(read_json(run)["artifacts"]["authoring"]["session_path"]))
    assert all(Path(batch["result_path"]).is_file() for batch in accepted["batches"])


def test_advance_edition_finishes_tail_and_renders_without_model_roundtrips(tmp_path, monkeypatch):
    run = tmp_path / "daily.json"
    run.write_text(json.dumps({"status": "completed_partial", "artifacts": {
        "slides": {"plan_path": "plan.json"}}}), encoding="utf-8")
    monkeypatch.setattr(launcher, "advance_dispatch", lambda *args: {"tasks": [], "issues": []})
    calls = []

    def execute(data_dir, arguments):
        calls.append(arguments)
        if arguments[0] == "edition-status":
            finished = len(calls) > 1
            return {"delivery_complete": finished,
                    "pending_steps": [] if finished else ["tail", "slides_render"]}
        if arguments[:2] == ["slides", "render"]:
            return {"json_path": "deck.json"}
        return {}

    monkeypatch.setattr(launcher, "run_command", execute)
    result = launcher.advance_edition(run, tmp_path)
    assert result["stage"] == "complete" and result["deck_path"] == "deck.json"
    assert [row[0] for row in calls] == [
        "edition-status", "complete-edition-tail", "slides", "edition-status"]


def test_compact_dispatch_bounds_tickets_and_preserves_full_repair_errors(tmp_path):
    tasks = [{"kind": "brief", "batch_id": str(number), "packet_path": f"packet-{number}.json",
              "input_file": "input.json", "draft_result_path": str(tmp_path / f"{number}.json"),
              "errors": ["content issue " * 100] if number == 1 else []}
             for number in range(8)]
    compact = launcher.compact_dispatch({"tasks": tasks, "issues": [], "cli_prefix": ["long"]},
                                         limit=2, in_flight=("0",))
    assert [task["batch_id"] for task in compact["tasks"]] == ["1", "2"]
    assert compact["pending_task_count"] == 8 and "cli_prefix" not in compact
    assert "errors" not in compact["tasks"][0]
    saved = json.loads(Path(compact["tasks"][0]["repair_errors_file"]).read_text(encoding="utf-8"))
    assert saved["errors"] == tasks[1]["errors"]


def test_ordered_input_parts_preserve_utf8_bytes_and_bound_each_read(tmp_path):
    import tiktoken

    from signaltrail.author_inputs import materialize_input_parts

    text = json.dumps({"schema": {"required": ["news"]},
                       "news": ["文章事实与证据🌏🧬。ASCII words / numbers 12345\n" * 2500]},
                      ensure_ascii=False)
    source = tmp_path / "input.json"
    source.write_bytes((text + "\r\n").encode("utf-8"))
    manifest = materialize_input_parts(source)
    parts = [Path(manifest["input_parts_dir"]) / name for name in manifest["input_parts"]]
    assert len(parts) > 1
    assert b"".join(path.read_bytes() for path in parts) == source.read_bytes()
    encoding = tiktoken.get_encoding("o200k_base")
    assert all(len(encoding.encode(path.read_text(encoding="utf-8"))) <= 7500 for path in parts)
    assert materialize_input_parts(source) == manifest
    source.write_bytes((text + "\r\nchanged input 中文🌏").encode("utf-8"))
    updated = materialize_input_parts(source)
    assert updated["input_sha256"] != manifest["input_sha256"]
    assert updated["input_parts_dir"] != manifest["input_parts_dir"]
    assert b"".join((Path(updated["input_parts_dir"]) / name).read_bytes()
                    for name in updated["input_parts"]) == source.read_bytes()
    assert all(path.is_file() for path in parts)
