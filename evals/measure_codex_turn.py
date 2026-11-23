"""用固定宿主日志验证整轮计量与显式窗口的差别。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def row(second: int, kind: str, **payload) -> dict:
    """构造带时标的原生宿主日志记录。"""
    return {"timestamp": f"2026-11-17T00:00:{second:02d}Z", "type": kind, "payload": payload}


def write_log(path: Path, records: list[dict]) -> None:
    """逐条写入供生产命令读取的隔离日志。"""
    path.write_text("".join(json.dumps(value) + "\n" for value in records), encoding="utf-8")


def main() -> None:
    """验证全树归属、缓存计数、最终回复后的用量落盘和混合轮拒绝。"""
    project = Path(__file__).resolve().parents[1]
    output = project / "output" / f"completed-turn-evaluation-{uuid4().hex[:8]}"
    logs = output / "sessions"
    logs.mkdir(parents=True)
    usage = {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 7,
             "reasoning_output_tokens": 3, "total_tokens": 200}
    root = [
        row(0, "session_meta", id="root", source="vscode"),
        row(0, "event_msg", type="task_started", turn_id="turn", root_turn_id="turn",
            turn_attribution={"turn_trigger": "composer"}),
        row(1, "event_msg", type="item_completed", thread_id="root", turn_id="turn",
            item={"type": "UserMessage", "id": "request"}),
        row(2, "turn_context", turn_id="turn", model="gpt-6.1-terra", effort="medium"),
        row(7, "event_msg", type="item_completed", thread_id="root", turn_id="turn",
            item={"type": "AgentMessage", "phase": "final_answer", "id": "reply"}),
        row(8, "token_usage_record", thread_id="root", turn_id="turn", root_turn_id="turn",
            response_id="root-final", usage=usage),
        row(9, "event_msg", type="task_complete", turn_id="turn", root_turn_id="turn"),
        {"type": "event_msg", "payload": {
            "type": "item_completed", "thread_id": "root", "turn_id": "old-turn",
            "item": {"type": "UserMessage", "id": "old-request"},
        }},
    ]
    write_log(logs / "root.jsonl", root)
    for name, parent in (("child", "root"), ("grandchild", "child"), ("unrelated", "other")):
        response = row(
            3, "token_usage_record", thread_id=name, turn_id=name, root_turn_id="turn",
            response_id=name, usage=usage,
        )
        write_log(logs / f"{name}.jsonl", [
            row(2, "session_meta", id=name,
                source={"subagent": {"thread_spawn": {"parent_thread_id": parent}}}),
            row(2, "turn_context", turn_id=name, model="gpt-6.1-terra",
                effort="low" if name == "child" else None),
            response,
            response,
            row(4, "token_usage_record", thread_id=name, turn_id=name, root_turn_id="other",
                response_id=f"{name}-other", usage=usage),
        ])

    command = [
        sys.executable, str(project / "scripts" / "measure_codex_turn.py"),
        "--log-root", str(logs), "--root-thread-id", "root", "--root-turn-id", "turn",
    ]
    complete = output / "completed.json"
    subprocess.run([*command, "--completed-turn", "--output", str(complete)],
                   check=True, capture_output=True)
    measured = json.loads(complete.read_text(encoding="utf-8"))
    assert measured["wall_seconds"] == 6 and measured["scope"] == "completed_turn"
    assert measured["integrity"]["response_records_after_final_reply"] == 1
    assert measured["total"]["responses"] == 3
    assert measured["total"]["cached_input_tokens"] == 60
    assert measured["total"]["total_tokens"] == 321
    assert measured["model_effort_response_counts"] == [
        {"model": "gpt-6.1-terra", "effort": effort, "responses": 1}
        for effort in ("low", "medium", "unknown")
    ]

    manual = output / "window.json"
    subprocess.run([
        *command, "--start", "2026-11-17T00:00:01Z", "--end", "2026-11-17T00:00:07Z",
        "--output", str(manual),
    ], check=True, capture_output=True)
    measured = json.loads(manual.read_text(encoding="utf-8"))
    assert measured["scope"] == "selected_window" and measured["total"]["total_tokens"] == 214

    write_log(logs / "root.jsonl", [*root[:3], row(
        5, "event_msg", type="item_completed", thread_id="root", turn_id="turn",
        item={"type": "UserMessage", "id": "follow-up"},
    ), *root[3:]])
    rejected = output / "mixed.json"
    mixed = subprocess.run([*command, "--completed-turn", "--output", str(rejected)],
                           capture_output=True)
    assert mixed.returncode == 2 and not rejected.exists()

    anchor = logs / "harness.jsonl"
    anchor_log = [
        row(10, "session_meta", id="harness", source={"subagent": {"thread_spawn": {
            "parent_thread_id": "root", "agent_path": "/root/edition_harness",
        }}}),
        row(10, "event_msg", type="task_started", turn_id="work", root_turn_id="turn",
            turn_attribution={"parent_turn_id": "turn"}),
        row(11, "inter_agent_communication_metadata", trigger_turn=True),
        row(18, "event_msg", type="item_completed", thread_id="harness", turn_id="work",
            item={"type": "AgentMessage", "phase": "final_answer", "id": "harness-reply"}),
        row(19, "token_usage_record", thread_id="harness", turn_id="work", root_turn_id="turn",
            response_id="harness-final", usage=usage),
        row(20, "event_msg", type="task_complete", turn_id="work", root_turn_id="turn"),
        row(21, "event_msg", type="task_started", turn_id="later", root_turn_id="turn",
            turn_attribution={"parent_turn_id": "turn"}),
        row(22, "event_msg", type="item_completed", thread_id="harness", turn_id="later",
            item=["malformed later item"]),
        row(23, "token_usage_record", thread_id="harness", turn_id="later", root_turn_id="turn",
            response_id="harness-later", usage=usage),
    ]
    write_log(anchor, anchor_log)
    for second, name, parent_turn in ((12, "author", "work"), (22, "later-author", "later")):
        write_log(logs / f"{name}.jsonl", [
            row(second, "session_meta", id=name, source={"subagent": {"thread_spawn": {
                "parent_thread_id": "harness",
            }}}),
            row(second, "event_msg", type="task_started", turn_id=name, root_turn_id="turn",
                turn_attribution={"parent_turn_id": parent_turn}),
            row(second + 1, "token_usage_record", thread_id=name, turn_id=name,
                root_turn_id="turn", response_id=name, usage=usage),
        ])
    subtree_command = [*command, "--completed-turn", "--subtree-thread-id", "harness"]
    subtree = output / "subtree.json"
    subprocess.run([*subtree_command, "--output", str(subtree)], check=True, capture_output=True)
    measured = json.loads(subtree.read_text(encoding="utf-8"))
    assert measured["scope"] == "completed_turn"
    assert measured["selection"] == "completed_subtree_turn"
    assert measured["dedicated_subtree"]["first_turn_id"] == "work"
    assert measured["wall_seconds"] == 8 and measured["total"]["total_tokens"] == 214
    assert measured["model_effort_response_counts"] == [
        {"model": "unknown", "effort": "unknown", "responses": 2},
    ]
    steering = row(15, "inter_agent_communication_metadata", trigger_turn=True)
    write_log(anchor, [*anchor_log[:3], steering, *anchor_log[3:]])
    steered = output / "steered.json"
    rejected = subprocess.run([*subtree_command, "--output", str(steered)], capture_output=True)
    assert rejected.returncode == 2 and not steered.exists()
    print(output)


if __name__ == "__main__":
    main()
