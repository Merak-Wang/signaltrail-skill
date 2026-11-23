"""汇总同一日报调用的所有 Codex CLI 写作会话与重试。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from measure_codex_turn import rows, timestamp


def invocation(log: Path, sessions: dict[str, Path]) -> dict:
    """读取原生请求记录，并用 CLI 完成事件的总量检查请求明细。"""
    metadata = json.loads(log.with_suffix(".meta.json").read_bytes())
    thread, aggregate = None, {}
    for event in rows(log):
        if event["type"] == "thread.started":
            thread = event["thread_id"]
        elif event["type"] == "turn.completed":
            aggregate = event["usage"]
    context = {}
    requests = {}
    for row in rows(sessions[thread]) if thread in sessions else ():
        if row["type"] == "turn_context":
            context[row["payload"]["turn_id"]] = row["payload"]
        elif row["type"] == "token_usage_record":
            record = row["payload"]
            if record.get("response_id"):
                requests[record["response_id"]] = record
    counts = Counter(
        (
            context.get(record["turn_id"], {}).get("model", "unknown"),
            context.get(record["turn_id"], {}).get("effort", "unknown"),
        )
        for record in requests.values()
    )
    usage = {}
    for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
        values = [record["usage"].get(field) for record in requests.values()]
        native_total = (
            sum(values) if values and all(isinstance(value, int) for value in values) else None
        )
        cli_total = aggregate.get(field)
        if native_total is not None and cli_total is not None and native_total != cli_total:
            raise ValueError(f"{log.name}: {field} differs between native and CLI receipts")
        usage[field] = native_total if native_total is not None else cli_total
    return {
        "agent_path": log.stem,
        "thread_id": thread,
        "category": metadata["role"],
        "metadata": metadata,
        "usage": usage,
        "responses": len(requests) or None,
        "models": {
            model: sum(value for (name, _), value in counts.items() if name == model)
            for model, _ in counts
        },
        "reasoning_efforts": sorted({effort for _, effort in counts}),
        "model_effort_response_counts": [
            {"model": model, "effort": effort, "responses": count}
            for (model, effort), count in sorted(counts.items())
        ],
    }


def main() -> None:
    """按一次独立生成的开始、成片完成与写作记录产出宿主回执。"""
    parser = argparse.ArgumentParser(
        description="Measure all Codex CLI author sessions and retries for one edition."
    )
    for key in ("jobs", "start", "done", "run", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--session-root", type=Path, default=Path.home() / ".codex/sessions")
    args = parser.parse_args()
    start = timestamp(json.loads(args.start.read_bytes())["start_utc"])
    end = timestamp(json.loads(args.done.read_bytes())["end_utc"])
    sessions = {path.stem[-36:]: path for path in args.session_root.rglob("rollout-*.jsonl")}
    agents = [invocation(log, sessions) for log in sorted(args.jobs.glob("*.jsonl"))]
    if not agents:
        parser.error("No CLI invocations were recorded")
    totals = {}
    for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
        values = [a["usage"][field] for a in agents]
        observed = [value for value in values if isinstance(value, int)]
        totals[f"{field}_known"] = sum(observed)
        totals[field] = sum(observed) if len(observed) == len(values) else None
    known = totals["input_tokens_known"] + totals["output_tokens_known"]
    complete = totals["input_tokens"] is not None and totals["output_tokens"] is not None
    totals["total_tokens_known"] = known
    totals["total_tokens"] = known if complete else None
    counts = Counter()
    for agent in agents:
        for row in agent["model_effort_response_counts"]:
            counts[row["model"], row["effort"]] += row["responses"]
    totals["responses"] = (
        sum(counts.values()) if all(a["responses"] is not None for a in agents) else None
    )
    receipt = {
        "selection": "completed_invocation",
        "scope": "completed_turn" if complete else "partial",
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "wall_seconds": (end - start).total_seconds(),
        "run_sha256": sha256(args.run.read_bytes()).hexdigest(),
        "token_basis": "input_tokens_plus_output_tokens",
        "total": totals,
        "model_effort_response_counts": [
            {"model": model, "effort": effort, "responses": count}
            for (model, effort), count in sorted(counts.items())
        ],
        "agents": agents,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
