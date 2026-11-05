import json
from datetime import UTC, datetime

from scripts.measure_codex_turn import FIELDS, measure


def test_lineage_deduplication_and_unknown_usage(tmp_path):
    def write(name, thread, parent, records, agent_path=""):
        meta = {
            "type": "session_meta",
            "payload": {
                "id": thread,
                "source": {"subagent": {"thread_spawn": {
                    "parent_thread_id": parent, "agent_path": agent_path,
                }}},
            },
        }
        (tmp_path / name).write_text(
            "\n".join(json.dumps(row) for row in [meta, *records]), encoding="utf-8"
        )

    def usage(thread, turn, response, values, root_turn="target"):
        return {
            "type": "token_usage_record",
            "timestamp": "2026-01-01T00:00:01Z",
            "payload": {
                "thread_id": thread,
                "root_turn_id": root_turn,
                "turn_id": turn,
                "response_id": response,
                "usage": values,
            },
        }

    values = {
        "input_tokens": 10,
        "cached_input_tokens": 3,
        "output_tokens": 5,
        "reasoning_output_tokens": 2,
        "total_tokens": 15,
        "response_text": "must never leave the log",
    }
    write(
        "root.jsonl",
        "root",
        None,
        [
            {"type": "turn_context", "payload": {"turn_id": "target", "model": "gpt-6.1-sol"}},
            usage("root", "target", "a", values),
            usage("root", "target", "a", values),
            usage("root", "other", "b", values),
        ],
    )
    child_usage = usage("child", "child-turn", "c", {})
    child_usage["timestamp"] = "2026-01-01T00:00:02Z"
    write("child.jsonl", "child", "root", [child_usage],
          agent_path="/root/daily_run")
    write("unrelated.jsonl", "unrelated", None, [usage("unrelated", "other", "d", values)])
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result = measure(tmp_path, "root", "target", start, start.replace(second=2))
    assert result["total"]["responses"] == 2
    assert result["total"]["input_tokens"] is None
    assert result["total"]["input_tokens_known"] == 10
    assert result["total"]["total_tokens_known"] == 15
    assert result["wall_seconds"] == 2
    assert len(result["agents"]) == 2
    assert "requests" not in result

    detailed = measure(tmp_path, "root", "target", start, start.replace(second=2), per_request=True)
    assert detailed["total"] == result["total"]
    assert len(detailed["requests"]) == 2
    assert [row["category"] for row in detailed["requests"]] == [
        "root_coordination", "generation_agents",
    ]
    assert [row["timestamp_utc"] for row in detailed["requests"]] == [
        "2026-01-01T00:00:01+00:00", "2026-01-01T00:00:02+00:00",
    ]
    assert [row["model"] for row in detailed["requests"]] == ["gpt-6.1-sol", None]
    for row in detailed["requests"]:
        assert set(row) == {"timestamp_utc", "category", "model", "usage"}
        assert set(row["usage"]) == set(FIELDS)
    assert all(value is None for value in detailed["requests"][1]["usage"].values())
    assert detailed["requests"][0]["usage"]["input_tokens"] == 10
