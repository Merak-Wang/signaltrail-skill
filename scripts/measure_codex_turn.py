"""按 Codex 逐请求记录汇总单轮及其子线程的用量。"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def rows(path: Path):
    """逐行读取日志，只向调用方提供 JSON 记录。"""
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(UTC)


def category(path: str, root: bool) -> str:
    if root:
        return "root_coordination"
    if "accept_fix" in path:
        return "fault_recovery_code_fix"
    if any(name in path for name in ("brief", "slides", "analysis")):
        return "generation_agents"
    return "other_agents"


def summarize(records: list[dict]) -> dict:
    """合计已知值，任一请求缺失字段时保留未知状态。"""
    result = {"responses": len(records)}
    for field in FIELDS:
        values = [item.get(field) for item in records]
        known = sum(
            value
            for value in values
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        )
        complete = bool(values) and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in values
        )
        result[field] = known if complete else None
        result[f"{field}_known"] = known if values else None
    inp, cached = result["input_tokens"], result["cached_input_tokens"]
    result["uncached_input_tokens"] = (
        inp - cached if inp is not None and cached is not None and inp >= cached else None
    )
    return result


def measure(log_root: Path, root: str, turn: str, start: datetime, end: datetime) -> dict:
    """以首条会话元数据建立血缘，再筛选和去重逐请求计量。"""
    files = []
    for path in sorted(log_root.rglob("*.jsonl")):
        for row in rows(path):
            if row.get("type") == "session_meta":
                meta = row.get("payload", {})
                source = meta.get("source") or {}
                spawn = (
                    source.get("subagent", {}).get("thread_spawn", {})
                    if isinstance(source, dict)
                    else {}
                )
                files.append(
                    (
                        path,
                        meta.get("id"),
                        spawn.get("parent_thread_id"),
                        spawn.get("agent_path", ""),
                    )
                )
                break
    descendants = {root}
    while True:
        expanded = descendants | {
            tid for _, tid, parent, _ in files if parent in descendants and tid
        }
        if expanded == descendants:
            break
        descendants = expanded
    seen = set()
    all_usage = []
    agents = []
    for path, tid, _, agent_path in files:
        if tid not in descendants:
            continue
        contexts = {}
        selected = []
        for row in rows(path):
            payload = row.get("payload", {})
            if row.get("type") == "turn_context":
                model = payload.get("model")
                contexts[payload.get("turn_id")] = (
                    model
                    if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model)
                    else "unknown"
                )
            if (
                row.get("type") != "token_usage_record"
                or payload.get("thread_id") != tid
                or payload.get("root_turn_id") != turn
                or (tid == root and payload.get("turn_id") != turn)
            ):
                continue
            stamp = timestamp(row["timestamp"])
            if not start <= stamp <= end:
                continue
            response = payload.get("response_id")
            if response is not None and response in seen:
                continue
            if response is not None:
                seen.add(response)
            usage = payload.get("usage")
            selected.append((payload.get("turn_id"), usage if isinstance(usage, dict) else {}))
        if selected:
            by_model = defaultdict(list)
            for turn_id, usage in selected:
                by_model[contexts.get(turn_id, "unknown")].append(usage)
            usages = [usage for _, usage in selected]
            all_usage.extend(usages)
            agents.append(
                {
                    "category": category(agent_path or "", tid == root),
                    "turn_count": len({t for t, _ in selected if t is not None}),
                    "models": {
                        model: summarize(values) for model, values in sorted(by_model.items())
                    },
                    "usage": summarize(usages),
                }
            )
    return {
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "wall_seconds": round((end - start).total_seconds(), 3),
        "cost_usd": None,
        "total": summarize(all_usage),
        "agents": agents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", type=Path, required=True)
    parser.add_argument("--root-thread-id", required=True)
    parser.add_argument("--root-turn-id", required=True)
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be at or after --start")
    result = measure(args.log_root, args.root_thread_id, args.root_turn_id, args.start, args.end)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {"total": result["total"], "output": str(args.output.resolve())}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
