from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from daily_intelligence.hermes_runner import coverage_complete
from daily_intelligence.hosts.hermes import (
    HermesObserver,
    bounded_delegation_config,
    file_worker_tasks,
    is_usage_command,
)
from daily_intelligence.llm_usage import UsageLedger


def test_concurrent_observer_is_exact_and_preserves_lineage(tmp_path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})

    def call(index):
        sid = f"private-session-{index}"
        observer.observe("subagent_start", {"child_session_id": sid,
                         "parent_session_id": "private-parent",
                         "child_goal": "[signaltrail-phase:brief-authoring] secret instructions"})
        payload = {"session_id": sid, "api_request_id": f"private-request-{index}",
                   "provider": "opencode-go", "started_at": 1788835201.25,
                   "request": {"api_key": "secret-key", "prompt": "private text"}}
        observer.observe("pre_api_request", payload)
        observer.observe("post_api_request", {**payload, "ended_at": 1788835202.5,
                         "api_duration": 1.25,
                         "usage": {"input_tokens": 100, "cache_read_tokens": 20,
                                   "cache_write_tokens": 0, "output_tokens": 10,
                                   "prompt_tokens": 120, "total_tokens": 130}})

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(call, range(6)))
    summary = ledger.summarize_task(task)
    receipt = {**observer.receipt(), "database_reconciliation": {"status": "matched"}}
    assert coverage_complete(summary, receipt)
    assert summary["tokens"]["accounted_total"]["value"] == 780
    assert summary["call_lifecycle"]["finished_call_count"] == 6
    assert summary["lineage_coverage"]["fields"]["parent_session_id_hash"]["missing"] == 0
    serialized = "\n".join(p.read_text(encoding="utf-8") for p in task.path.rglob("*.json"))
    assert not any(word in serialized for word in ("private-", "secret-key", "secret instructions"))
    ledger.finalize_task(task)
    assert ledger.summarize_task(task)["tokens"]["accounted_total"]["value"] == 780


def test_missing_and_failed_observation_cannot_pass(tmp_path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})
    assert not coverage_complete(ledger.summarize_task(task), observer.receipt())
    payload = {"session_id": "parent", "api_request_id": "request"}
    observer.observe("pre_api_request", payload)
    assert not coverage_complete(ledger.summarize_task(task), observer.receipt())
    observer.observe("api_request_error", payload)
    summary = ledger.summarize_task(task)
    assert summary["call_lifecycle"]["failed_call_count"] == 1
    assert not coverage_complete(summary, observer.receipt())
    ledger.finalize_task(task, status="partial")
    observer.observe("pre_api_request", {**payload, "api_request_id": "late"})
    assert observer.receipt()["failures"]


@pytest.mark.parametrize("command, expected", [
    ('C:/my dir/Scripts/signaltrail-usage.exe hook', False),
    ('"C:/my dir/Scripts/signaltrail-usage.exe" hook', True),
    ('signaltrail-usage hook', True), ('other-command hook', False),
    ('signaltrail-usage hook --other', False), ('echo signaltrail-usage hook', False),
    ('echo C:/Scripts/signaltrail-usage.exe hook', False),
])
def test_only_existing_usage_shell_commands_are_replaced(command, expected):
    assert is_usage_command(command) is expected


def test_host_budget_and_file_contract_do_not_duplicate_worker_generation():
    original = {"max_iterations": 250, "max_concurrent_children": 8, "provider": "opencode-go"}
    bounded = bounded_delegation_config(original)
    assert bounded["max_iterations"] == 40
    assert bounded["max_concurrent_children"] == 3
    assert bounded["provider"] == "opencode-go"
    assert original["max_iterations"] == 250
    assert bounded_delegation_config({"max_iterations": 9})["max_iterations"] == 9
    tasks = [{"goal": "[signaltrail-phase:analysis-authoring] Write assigned packet",
              "context": "Read the packet output_schema and submit the file.",
              "output_schema": {"type": "object"}}]
    cleaned, is_file = file_worker_tasks(tasks)
    assert is_file and "output_schema" not in cleaned[0]
    assert cleaned[0]["context"] == tasks[0]["context"]
    assert "output_schema" in tasks[0]
    other = [{"goal": "Return structured data", "output_schema": {"type": "object"}}]
    assert file_worker_tasks(other) == (other, False)


def test_bridge_enforces_host_limits_at_actual_dispatch(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    import daily_intelligence.hosts.hermes as bridge

    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})
    calls = []
    delegation = SimpleNamespace(
        _load_config=lambda: {"max_iterations": 250},
        _get_max_concurrent_children=lambda: 8,
        _strip_model_hidden_task_fields=lambda tasks: tasks,
        delegate_task=lambda **kwargs: calls.append(kwargs) or "finished",
    )

    class Agent:
        pass

    modules = {
        "cli": SimpleNamespace(_finalize_single_query=lambda host: None),
        "agent": SimpleNamespace(shell_hooks=SimpleNamespace(register_from_config=lambda cfg: [])),
        "hermes_cli": SimpleNamespace(lifecycle=SimpleNamespace(
            invoke_hook=lambda *args, **kwargs: [], has_hook=lambda event: False)),
        "run_agent": SimpleNamespace(AIAgent=Agent),
        "tools": SimpleNamespace(delegate_tool=delegation),
        "tools.delegate_tool": delegation,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(bridge, "install_auxiliary_bridge", lambda observer: None)
    monkeypatch.setattr(bridge, "install_iteration_summary_bridge", lambda observer: None)
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    bridge.install_bridge(observer)
    assert delegation._load_config()["max_iterations"] == 40
    assert delegation._get_max_concurrent_children() == 3
    agent = Agent()
    assert agent._dispatch_delegate_task({"tasks": [{
        "goal": "[signaltrail-phase:brief-authoring] Write packet",
        "output_schema": {"type": "object"},
    }]}) == "finished"
    assert calls[0]["background"] is False
    assert calls[0]["parent_agent"] is agent
    assert "output_schema" not in calls[0]["tasks"][0]
    assert calls[0]["output_schema"] is None


def test_forced_summary_preserves_affinity_and_records_success_and_failure(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    from daily_intelligence.hosts.hermes import install_iteration_summary_bridge

    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})
    native_usage = []
    helper = SimpleNamespace(
        _managed_summary_call=lambda agent, request_id, request, callback, **kwargs:
            callback(request),
        handle_max_iterations=lambda *args: "summary",
    )

    def headers(request, provider, base_url, session):
        assert provider == "opencode-go" and session == "private-session"
        request.setdefault("extra_headers", {}).setdefault("x-opencode-session", session)
        return request

    monkeypatch.setitem(sys.modules, "agent", SimpleNamespace(chat_completion_helpers=helper))
    monkeypatch.setitem(sys.modules, "agent.opencode_affinity",
                        SimpleNamespace(merge_opencode_session_headers=headers))
    usage = {"input_tokens": 100, "cache_read_tokens": 20, "cache_write_tokens": 0,
             "output_tokens": 10, "reasoning_tokens": 3, "total_tokens": 130}
    agent = SimpleNamespace(
        provider="opencode-go", base_url="https://opencode.ai/zen/go/v1",
        session_id="private-session", model="test-model", api_mode="chat_completions",
        _usage_summary_for_api_request_hook=lambda response: usage,
        _session_db=SimpleNamespace(record_auxiliary_usage=lambda *args, **kwargs:
                                    native_usage.append(kwargs)),
    )
    install_iteration_summary_bridge(observer)

    def success(request):
        assert request["extra_headers"]["x-opencode-session"] == "pinned-affinity"
        return SimpleNamespace(model="test-model")

    helper._managed_summary_call(agent, "logical-id", {
        "extra_headers": {"x-opencode-session": "pinned-affinity"}}, success, retry_count=0)
    summary = ledger.summarize_task(task)
    assert summary["tokens"]["accounted_total"]["value"] == 130
    assert summary["lineage_coverage"]["by_phase"] == {"auxiliary": 1}
    assert native_usage[0]["task"] == "iteration_summary"
    assert native_usage[0]["api_call_count"] == 1

    def failure(request):
        assert request["extra_headers"]["x-opencode-session"] == "private-session"
        raise RuntimeError("private provider body")

    with pytest.raises(RuntimeError):
        helper._managed_summary_call(agent, "logical-id", {}, failure, retry_count=1)
    summary = ledger.summarize_task(task)
    assert summary["call_lifecycle"]["attempted_call_count"] == 2
    assert summary["call_lifecycle"]["failed_call_count"] == 1
    assert summary["tokens"]["accounted_total"]["value"] is None
    assert summary["tokens"]["accounted_total"]["known_value"] == 130
    assert len(native_usage) == 1
    serialized = "".join(p.read_text(encoding="utf-8") for p in task.path.rglob("*.json"))
    assert "private provider body" not in serialized and "pinned-affinity" not in serialized
    agent.api_mode = "codex_responses"
    assert helper.handle_max_iterations(agent, [], 1) == "summary"
    assert observer.receipt()["failures"]["unsupported_iteration_summary_transport"] == 1


def test_local_evaluator_launch_is_metered_and_never_duplicated(monkeypatch, tmp_path):
    import daily_intelligence.workflow as workflow

    monkeypatch.setenv("SIGNALTRAIL_HERMES_PYTHON", "hermes-python")
    monkeypatch.setenv("SIGNALTRAIL_HERMES_MODEL", "test-model")
    monkeypatch.setattr(workflow, "project_root", lambda: tmp_path)
    dossier = tmp_path / "dossier.json"
    dossier.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(workflow, "build_evaluation_dossier", lambda *args: dossier)
    calls = []

    class Process:
        pid = 123

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

    monkeypatch.setattr(workflow.subprocess, "Popen", Process)
    args = (tmp_path / "report.json", tmp_path / "index.json", tmp_path,
            "report-1", "content-hash")
    receipt = workflow.schedule_independent_evaluation(*args, usage_task_id="eval-task")
    assert receipt["backend"] == "metered-local"
    command = calls[0][0]
    assert "--evaluation-attempt" in command
    assert command[command.index("--task-id") + 1] == "eval-task"
    assert "cron" not in command
    prompt = (tmp_path / "evaluation-launches/eval-task/prompt.txt").read_text(encoding="utf-8")
    assert '"hermes-python" -m daily_intelligence.cli' in prompt
    assert 'runpy.run_module' not in prompt
    assert prompt.endswith('{}')
    assert workflow.reconcile_evaluation_scheduler(receipt)["status"] == "unknown"
    result_path = tmp_path / "host-runs" / "eval-task" / "receipt.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({"task_id": "eval-task", "status": "completed"}))
    assert workflow.reconcile_evaluation_scheduler(receipt)["status"] == "completed"
    result_path.write_text(json.dumps({"task_id": "wrong-task", "status": "completed"}))
    assert workflow.reconcile_evaluation_scheduler(receipt)["status"] == "failed"
    duplicate = workflow.schedule_independent_evaluation(*args, usage_task_id="eval-task")
    assert duplicate["status"] == "unknown"
    assert len(calls) == 1


def test_unknown_local_evaluator_is_rechecked_without_redispatch(monkeypatch, tmp_path):
    import daily_intelligence.workflow as workflow

    scheduler = {"backend": "metered-local", "status": "unknown", "attempt": 1}
    run = {"artifacts": {"json_path": str(tmp_path / "report.json"),
                         "report_id": "report-1", "content_hash": "hash"},
           "evaluation": {"status": "pending", "scheduler": scheduler}}
    reconciliations = []
    monkeypatch.setattr(workflow, "evaluation_preflight",
                        lambda *args: {"status": "evaluation_required"})

    def reconcile(receipt):
        reconciliations.append(receipt)
        return {**receipt, "status": "unknown", "reason": "metered_process_not_sealed"}

    monkeypatch.setattr(workflow, "reconcile_evaluation_scheduler", reconcile)
    first = workflow._schedule_evaluation_attempt(
        run, tmp_path / "run.json", tmp_path, publish_notion=False
    )
    assert first["scheduler"]["status"] == "unknown"
    workflow._schedule_evaluation_attempt(run, tmp_path / "run.json", tmp_path,
                                          publish_notion=False)
    assert len(reconciliations) == 2


def test_measurement_sum_is_stable_without_rounding_large_integers():
    from daily_intelligence.llm_usage.ledger import _sum_measurements
    from daily_intelligence.llm_usage.models import exact, unobservable

    values = [exact(value, "test") for value in [0.1, 0.2, 0.3]]
    assert _sum_measurements(values)["value"] == 0.6
    assert _sum_measurements(values, legacy_float_sum=True)["value"] == 0.6000000000000001
    large = [exact(2**60, "test"), exact(1, "test")]
    assert _sum_measurements(large)["value"] == 2**60 + 1
    partial = [*values, unobservable("missing")]
    assert _sum_measurements(partial)["value"] is None
    assert _sum_measurements(partial)["known_value"] == 0.6


def test_historical_float_seal_is_verified_without_accepting_tampering(tmp_path):
    from daily_intelligence.llm_usage.adapters.base import canonical_digest

    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    for index, latency in enumerate([0.1, 0.2, 0.3]):
        ledger.ingest_hook(task, "hermes", {
            "hook_event_name": "post_api_request", "api_request_id": str(index),
            "duration_ms": latency, "usage": {"input_tokens": 3, "output_tokens": 2,
                                                "total_tokens": 5},
        })
    path = ledger.finalize_task(task)
    seal = json.loads(path.read_text(encoding="utf-8"))
    latency = seal["data"]["summary"]["latency_ms"]["wall_ms"]
    latency["value"] = latency["known_value"] = 0.6000000000000001
    seal["payload_hash"] = "sha256:" + canonical_digest(seal["data"])
    path.write_text(json.dumps(seal), encoding="utf-8")
    before = path.read_bytes()
    assert ledger.summarize_task(task)["latency_ms"]["wall_ms"]["value"] == 0.6
    assert path.read_bytes() == before
    latency["value"] = latency["known_value"] = 0.6000000001
    seal["payload_hash"] = "sha256:" + canonical_digest(seal["data"])
    path.write_text(json.dumps(seal), encoding="utf-8")
    with pytest.raises(RuntimeError, match="summary does not match"):
        ledger.summarize_task(task)


def test_host_database_reconciliation_scopes_sessions(tmp_path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})
    payload = {"session_id": "selected", "api_request_id": "request"}
    observer.observe("pre_api_request", payload)
    observer.observe("post_api_request", {**payload, "usage": {
        "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
    }})
    db_path = tmp_path / "host.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE session_model_usage (session_id TEXT, api_call_count INT, "
                   "input_tokens INT, output_tokens INT, cache_read_tokens INT, "
                   "cache_write_tokens INT)")
        db.execute("INSERT INTO session_model_usage VALUES ('selected',1,3,2,0,0)")
        db.execute("INSERT INTO session_model_usage VALUES ('unrelated',900,500000,999,0,0)")
    assert observer.reconcile_database(db_path) == {
        "status": "matched", "api_call_count": 1, "accounted_tokens": 5,
    }
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE session_model_usage SET api_call_count=2 WHERE session_id='selected'")
    assert observer.reconcile_database(db_path)["status"] == "mismatch"


def test_auxiliary_sync_async_failures_and_format_compatibility(monkeypatch, tmp_path):
    import asyncio
    import contextvars
    import sys
    from dataclasses import dataclass
    from types import ModuleType, SimpleNamespace

    from daily_intelligence.hosts.hermes import install_auxiliary_bridge

    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes")
    observer = HermesObserver({"SIGNALTRAIL_USAGE_LEDGER": str(tmp_path),
                               "SIGNALTRAIL_USAGE_TASK": task.task_id})
    calls = []

    @dataclass
    class Usage:
        input_tokens: int = 3
        output_tokens: int = 2
        cache_read_tokens: int = 1
        cache_write_tokens: int = 0
        total_tokens: int = 6
        prompt_tokens: int = 4

    def sync(client, kwargs, **options):
        calls.append(kwargs)
        if kwargs.get("fail"):
            raise RuntimeError("private provider failure")
        return SimpleNamespace(usage={"total": 6}, model=kwargs["model"])

    async def asynchronous(client, kwargs, **options):
        return sync(client, kwargs, **options)

    auxiliary = ModuleType("agent.auxiliary_client")
    auxiliary._relay_sync_completion = sync
    auxiliary._relay_async_completion = asynchronous
    auxiliary._relay_sync_stream = lambda *args, **kwargs: iter([])
    auxiliary._RELAY_AUX_CALL_CONTEXT = contextvars.ContextVar("test_aux")
    auxiliary._RELAY_AUX_CALL_CONTEXT.set({"task": "title_generation"})
    auxiliary._without_structured_output_format = lambda kwargs: {
        key: value for key, value in kwargs.items() if key != "response_format"
    }
    accounting = ModuleType("agent.aux_accounting")
    accounting._accounting = contextvars.ContextVar("test_accounting")
    accounting._accounting.set((None, "session"))
    pricing = ModuleType("agent.usage_pricing")
    pricing.normalize_usage = lambda *args, **kwargs: Usage()
    agent = ModuleType("agent")
    agent.auxiliary_client = auxiliary
    agent.aux_accounting = accounting
    for name, module in (("agent", agent), ("agent.aux_accounting", accounting),
                         ("agent.auxiliary_client", auxiliary), ("agent.usage_pricing", pricing)):
        monkeypatch.setitem(sys.modules, name, module)
    install_auxiliary_bridge(observer)
    request = {"model": "deepseek-v4-flash-vision-exp", "response_format": {"type": "json_schema"}}
    auxiliary._relay_sync_completion(None, request, provider="opencode-go")
    assert "response_format" not in calls[0]
    assert "response_format" in request
    asyncio.run(auxiliary._relay_async_completion(None, request, provider="different"))
    assert "response_format" in calls[1]
    with pytest.raises(RuntimeError):
        auxiliary._relay_sync_completion(None, {**request, "fail": True})
    summary = ledger.summarize_task(task)
    assert summary["call_lifecycle"]["attempted_call_count"] == 3
    assert summary["call_lifecycle"]["unclosed_call_count"] == 0
    assert summary["tokens"]["accounted_total"]["value"] is None
    assert summary["tokens"]["accounted_total"]["known_value"] == 12
    auxiliary._relay_sync_stream(None, {})
    assert observer.receipt()["failures"]["unsupported_raw_auxiliary_stream"] == 1
