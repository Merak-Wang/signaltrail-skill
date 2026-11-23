"""按 Codex 逐请求记录汇总单轮及其子线程的用量。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
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


def rows(path: Path, damaged: Counter[Path] | None = None):
    """逐行读取 JSON 对象，按需计数且不回显所选会话的损坏记录。"""
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                row = None
            if (
                isinstance(row, dict) and isinstance(row.get("type"), str)
                and isinstance(row.get("payload", {}), dict)
            ):
                yield row
            elif damaged is not None:
                damaged[path] += 1


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
    task = path.rsplit("/", 1)[-1]
    if re.fullmatch(r"author\d+", task) or any(
        name in path for name in ("brief", "slide", "analysis", "daily_run")
    ):
        return "generation_agents"
    if task in {"review", "visual_review", "review_audit"}:
        return "editorial_review"
    return "other_agents"


def summarize(records: list[dict], *, incomplete: bool = False) -> dict:
    """合计已知值，任一请求缺失字段时保留未知状态。"""
    result = {"responses": len(records)}
    for field in FIELDS:
        values = [item.get(field) for item in records]
        observed = [
            value
            for value in values
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        ]
        known = sum(observed) if observed else None
        complete = bool(observed) and len(observed) == len(values) and not incomplete
        result[field] = known if complete else None
        result[f"{field}_known"] = known
    inp, cached = result["input_tokens"], result["cached_input_tokens"]
    result["uncached_input_tokens"] = (
        inp - cached if inp is not None and cached is not None and inp >= cached else None
    )
    return result


def completed_turn_bounds(paths: list[Path], root: str, turn: str) -> tuple[datetime, datetime]:
    """读取原生用户指令和最终回复事件，只接受独立且已完成的根轮次。"""
    starts, instructions, replies, completions = (set() for _ in range(4))
    for path in paths:
        for row in rows(path):
            payload = row.get("payload", {})
            if row["type"] != "event_msg" or payload.get("turn_id") != turn:
                continue
            kind = payload.get("type")
            if kind == "task_started" and payload.get("root_turn_id") == turn:
                if (payload.get("turn_attribution") or {}).get("turn_trigger") == "composer":
                    starts.add(timestamp(row["timestamp"]))
            elif kind == "task_complete" and payload.get("root_turn_id") == turn:
                completions.add(timestamp(row["timestamp"]))
            elif kind == "item_completed" and payload.get("thread_id") == root:
                item = payload.get("item") or {}
                if item.get("type") == "UserMessage":
                    instructions.add((item["id"], timestamp(row["timestamp"])))
                elif item.get("type") == "AgentMessage" and item.get("phase") == "final_answer":
                    replies.add((item["id"], timestamp(row["timestamp"])))
    if any(len(events) != 1 for events in (starts, instructions, replies, completions)):
        raise ValueError("A completed turn requires one composer start, user instruction, "
                         "final reply and native completion. Use a manual window for diagnostics.")
    start, (_, instruction), (_, reply), complete = (
        next(iter(events)) for events in (starts, instructions, replies, completions)
    )
    if not start <= instruction <= reply <= complete:
        raise ValueError("Completed turn has inconsistent native event order")
    return instruction, reply


def completed_subtree_bounds(paths: list[Path], root_turn: str) -> tuple[str, datetime, datetime]:
    """以专用子任务首次启动到最终回复为边界，后续复用属于其他工作。"""
    events = [
        (timestamp(row["timestamp"]), row["type"], row["payload"])
        for path in paths for row in rows(path)
        if row["type"] in {"event_msg", "inter_agent_communication_metadata"}
        and (row["type"] != "event_msg" or row.get("payload", {}).get("type") in {
            "task_started", "task_complete", "item_completed",
        })
    ]
    starts = [(stamp, event) for stamp, _, event in events if event.get("type") == "task_started"]
    if not starts:
        raise ValueError("Dedicated generation subtree has no native start")
    start, opening = min(starts, key=lambda pair: pair[0])
    turn = opening["turn_id"]
    if opening.get("root_turn_id") != root_turn:
        raise ValueError("Dedicated generation subtree was already used in a different root turn")
    native = [(stamp, event) for stamp, _, event in events if event.get("turn_id") == turn]
    done = {stamp for stamp, event in native if event.get("type") == "task_complete"}
    replies = {
        (stamp, item["id"]) for stamp, event in native
        if event.get("type") == "item_completed"
        and (item := event.get("item") or {}).get("type") == "AgentMessage"
        and item.get("phase") == "final_answer"
    }
    user_inputs = [event for _, event in native
                   if (event.get("item") or {}).get("type") == "UserMessage"]
    if len(done) != 1 or len(replies) != 1 or user_inputs:
        raise ValueError("Dedicated subtree needs one unsteered first turn and final reply")
    end, _ = next(iter(replies))
    complete = next(iter(done))
    triggers = {
        stamp for stamp, event_type, event in events
        if event_type == "inter_agent_communication_metadata" and event.get("trigger_turn")
        and start <= stamp <= complete
    }
    if len(triggers) != 1 or not start <= next(iter(triggers)) <= end <= complete:
        raise ValueError("Dedicated generation subtree needs exactly one native instruction")
    return turn, start, end


def subtree_turns(paths: list[Path], anchor_turn: str, root_turn: str) -> set[str]:
    """沿原生父轮次关系收集首次任务及其全部子轮次。"""
    parents = {}
    for path in paths:
        for row in rows(path):
            payload = row.get("payload", {})
            if (row["type"] == "event_msg" and payload.get("type") == "task_started"
                    and payload.get("root_turn_id") == root_turn):
                parents[payload["turn_id"]] = (
                    (payload.get("turn_attribution") or {}).get("parent_turn_id")
                )
    turns = {anchor_turn}
    while True:
        expanded = turns | {turn for turn, parent in parents.items() if parent in turns}
        if expanded == turns:
            return turns
        turns = expanded


def measure(
    log_root: Path, root: str, turn: str, start: datetime | None, end: datetime | None,
    *, per_request: bool = False, include_agent_paths: list[str] | None = None,
    subtree_thread_id: str | None = None, run_path: Path | None = None,
    completed: bool = False,
) -> dict:
    """以首条会话元数据建立血缘，再筛选和去重逐请求计量。"""
    files = []
    for path in sorted(log_root.rglob("*.jsonl")):
        for row in rows(path):
            meta = row.get("payload", {})
            if row.get("type") == "session_meta" and isinstance(meta.get("id"), str):
                source = meta.get("source")
                subagent = source.get("subagent") if isinstance(source, dict) else None
                spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
                spawn = spawn if isinstance(spawn, dict) else {}
                files.append(
                    (
                        path,
                        meta.get("id"),
                        spawn.get("parent_thread_id"),
                        spawn.get("agent_path", ""),
                    )
                )
                break
    def descendants_of(thread: str) -> set[str]:
        """从已记录的父子关系计算给定任务及其全部后代。"""
        descendants = {thread}
        while True:
            expanded = descendants | {
                tid for _, tid, parent, _ in files if parent in descendants and tid
            }
            if expanded == descendants:
                return descendants
            descendants = expanded

    descendants = descendants_of(root)
    if subtree_thread_id:
        if subtree_thread_id not in descendants:
            raise ValueError("Requested generation subtree does not belong to this root thread")
        descendants = descendants_of(subtree_thread_id)
    anchor = subtree_thread_id or root
    anchor_turn = turn
    bound_turns = None
    if completed:
        if any(value is not None for value in (start, end, include_agent_paths)):
            raise ValueError("A completed turn uses native bounds and excludes path filters")
        anchor_paths = [path for path, tid, _, _ in files if tid == anchor]
        if subtree_thread_id:
            anchor_turn, start, end = completed_subtree_bounds(anchor_paths, turn)
            bound_turns = subtree_turns(
                [path for path, tid, _, _ in files if tid in descendants], anchor_turn, turn,
            )
        else:
            start, end = completed_turn_bounds(anchor_paths, root, turn)
    elif start is None or end is None or end < start:
        raise ValueError("A manual window requires ordered start and end timestamps")
    damaged: Counter[Path] = Counter()
    conflicts: set[str] = set()
    conflict_files: set[Path] = set()
    seen = {}
    scoped = []
    all_usage = []
    agents = []
    requests = []
    model_effort_counts: Counter[tuple[str, str]] = Counter()
    for path, tid, _, agent_path in files:
        if tid not in descendants:
            continue
        if (include_agent_paths is not None and tid != anchor
                and agent_path not in include_agent_paths):
            continue
        contexts = {}
        efforts = {}
        selected = []
        for row in rows(path, damaged):
            payload = row.get("payload", {})
            if row.get("type") == "turn_context":
                model = payload.get("model")
                context_id = payload.get("turn_id")
                if not isinstance(context_id, str):
                    damaged[path] += 1
                    continue
                contexts[context_id] = (
                    model
                    if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model)
                    else "unknown"
                )
                effort = payload.get("effort")
                if isinstance(effort, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,20}", effort):
                    efforts[context_id] = effort
            if (
                row.get("type") != "token_usage_record"
                or payload.get("thread_id") != tid
                or payload.get("root_turn_id") != turn
                or (tid == root and payload.get("turn_id") != turn)
                or (bound_turns is not None and payload.get("turn_id") not in bound_turns)
            ):
                continue
            raw_stamp = row.get("timestamp")
            try:
                stamp = timestamp(raw_stamp) if isinstance(raw_stamp, str) else None
            except ValueError:
                stamp = None
            if stamp is None:
                damaged[path] += 1
                continue
            if not completed and not start <= stamp <= end:
                continue
            response = payload.get("response_id")
            usage = payload.get("usage")
            valid_usage = {
                field: value
                for field in FIELDS
                if isinstance(usage, dict)
                and isinstance(value := usage.get(field), int)
                and not isinstance(value, bool) and value >= 0
            }
            # 宿主 input 已包含缓存部分，output 已包含其中的推理输出。
            valid_usage.pop("total_tokens", None)
            if "input_tokens" in valid_usage and "output_tokens" in valid_usage:
                valid_usage["total_tokens"] = (
                    valid_usage["input_tokens"] + valid_usage["output_tokens"]
                )
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or (
                response is not None and not isinstance(response, str)
            ) or (
                completed and not response
            ):
                damaged[path] += 1
                continue
            if response is not None:
                # 重复写入的日志时标可能不同，响应的归属和用量才决定是否冲突。
                identity = (tid, turn_id, valid_usage)
                prior = seen.get(response)
                if prior is not None:
                    prior_path, prior_identity = prior
                    if prior_identity != identity:
                        conflicts.add(response)
                        conflict_files.update((path, prior_path))
                    continue
                seen[response] = (path, identity)
            selected.append((turn_id, valid_usage, stamp, response))
        scoped.append((path, tid, agent_path, contexts, efforts, selected))

    for path, tid, agent_path, contexts, efforts, entries in scoped:
        selected = [
            (turn_id, usage, stamp) for turn_id, usage, stamp, response in entries
            if response not in conflicts
        ]
        if selected:
            incomplete = path in damaged or path in conflict_files
            by_model = defaultdict(list)
            agent_category = category(agent_path or "", tid == anchor)
            for turn_id, usage, stamp in selected:
                model = contexts.get(turn_id, "unknown")
                model_effort_counts[model, efforts.get(turn_id, "unknown")] += 1
                by_model[model].append(usage)
                if per_request:
                    request_usage = summarize([usage])
                    requests.append({
                        "timestamp_utc": stamp.isoformat(),
                        "agent_path": agent_path or "/root",
                        "category": agent_category,
                        "model": model if model != "unknown" else None,
                        "usage": {field: request_usage[field] for field in FIELDS},
                    })
            usages = [usage for _, usage, _ in selected]
            all_usage.extend(usages)
            agents.append(
                {
                    "agent_path": agent_path or "/root",
                    "category": agent_category,
                    "turn_count": len({t for t, _, _ in selected if t is not None}),
                    "reasoning_efforts": sorted({
                        efforts[t] for t, _, _ in selected if t in efforts
                    }),
                    "models": {
                        model: summarize(values, incomplete=incomplete)
                        for model, values in sorted(by_model.items())
                    },
                    "usage": summarize(usages, incomplete=incomplete),
                }
            )
    anchor_found = any(tid == anchor for _, tid, *_ in scoped)
    total = summarize(all_usage, incomplete=bool(damaged or conflicts or not anchor_found))
    unknown_fields = [field for field in FIELDS if total[field] is None]
    # 最终回复落盘后仍可能记录该请求的用量，计量范围按归属而非回复时标裁剪。
    post_reply = sum(stamp > end for _, _, _, _, _, entries in scoped
                     for _, _, stamp, response in entries if response not in conflicts)
    result = {
        "root_thread_id": root,
        "root_turn_id": turn,
        "subtree_thread_id": subtree_thread_id,
        "include_agent_paths": include_agent_paths,
        "selection": (
            ("completed_subtree_turn" if subtree_thread_id else "completed_root_turn")
            if completed else "subtree" if subtree_thread_id else "root_turn"
        ),
        "scope": (
            "partial" if include_agent_paths is not None or total["total_tokens"] is None
            else "completed_turn" if completed else "selected_window"
        ),
        "token_basis": "input_tokens_plus_output_tokens",
        "integrity": {
            "selected_session_files": len(scoped),
            "anchor_session_found": anchor_found,
            "damaged_selected_rows": sum(damaged.values()),
            "conflicting_response_ids_excluded": len(conflicts),
            "response_records_after_final_reply": post_reply if completed else None,
            "fields_with_unknown_total": unknown_fields,
        },
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "wall_seconds": round((end - start).total_seconds(), 3),
        "cost_usd": None,
        "total": total,
        "agents": agents,
        "model_effort_response_counts": [
            {"model": model, "effort": effort, "responses": count}
            for (model, effort), count in sorted(model_effort_counts.items())
        ],
    }
    if completed and subtree_thread_id:
        result["dedicated_subtree"] = {
            "thread_id": anchor, "first_turn_id": anchor_turn,
            "agent_path": next((path for _, tid, _, path in files if tid == anchor), None),
        }
    if run_path is not None:
        run = run_path.read_bytes()
        if not isinstance(json.loads(run), dict):
            raise ValueError("Run manifest must be a JSON object")
        result["run_sha256"] = hashlib.sha256(run).hexdigest()
    if per_request:
        result["requests"] = sorted(requests, key=lambda request: request["timestamp_utc"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure request usage for one Codex turn and its child threads."
    )
    parser.add_argument("--log-root", type=Path, required=True)
    parser.add_argument("--root-thread-id", required=True)
    parser.add_argument("--root-turn-id", required=True)
    parser.add_argument("--start", type=timestamp)
    parser.add_argument("--end", type=timestamp)
    parser.add_argument("--completed-turn", action="store_true",
                        help="Measure one completed root instruction or first subtree task")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-request", action="store_true")
    parser.add_argument("--include-agent-path", action="append", default=None,
                        help="Include root and only these exact descendant task paths; repeatable")
    parser.add_argument("--subtree-thread-id",
                        help="Measure a dedicated generation coordinator and its descendants")
    parser.add_argument("--run", type=Path, help="Bind the receipt to a run manifest by SHA-256")
    args = parser.parse_args()
    try:
        result = measure(
            args.log_root, args.root_thread_id, args.root_turn_id, args.start, args.end,
            per_request=args.per_request, include_agent_paths=args.include_agent_path,
            subtree_thread_id=args.subtree_thread_id, run_path=args.run,
            completed=args.completed_turn,
        )
    except ValueError as exc:
        parser.error(str(exc))
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
