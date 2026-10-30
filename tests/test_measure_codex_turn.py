import json
from datetime import UTC, datetime

from scripts.measure_codex_turn import measure


def test_lineage_deduplication_and_unknown_usage(tmp_path):
    def write(name, thread, parent, records):
        meta = {
            "type": "session_meta",
            "payload": {
                "id": thread,
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent}}},
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
    }
    write(
        "root.jsonl",
        "root",
        None,
        [
            usage("root", "target", "a", values),
            usage("root", "target", "a", values),
            usage("root", "other", "b", values),
        ],
    )
    write("child.jsonl", "child", "root", [usage("child", "child-turn", "c", {})])
    write("unrelated.jsonl", "unrelated", None, [usage("unrelated", "other", "d", values)])
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result = measure(tmp_path, "root", "target", start, start.replace(second=2))
    assert result["total"]["responses"] == 2
    assert result["total"]["input_tokens"] is None
    assert result["total"]["input_tokens_known"] == 10
    assert result["total"]["total_tokens_known"] == 15
    assert result["wall_seconds"] == 2
    assert len(result["agents"]) == 2
