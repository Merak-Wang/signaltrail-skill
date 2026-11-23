"""按 Codex 逐请求记录汇总单轮及其子线程的用量。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable
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


def valid_token(value: object) -> bool:
    """识别原生用量行中的非负整数。"""
    return type(value) is int and value >= 0


def summarize_fields(
    records: list[dict], fields: tuple[str, ...], *, known_default: int | None = None,
    countable: Callable[[object], bool] = valid_token, incomplete: bool = False,
) -> dict:
    """合计各字段可观测部分，仅在每条请求都有该字段时给出完整总量。"""
    result = {}
    for field in fields:
        observed = [value for record in records if countable(value := record.get(field))]
        known = sum(observed) if observed else known_default
        result[field] = known if len(observed) == len(records) and not incomplete else None
        result[f"{field}_known"] = known
    return result


def summarize(records: list[dict], *, incomplete: bool = False) -> dict:
    """补齐逐请求数和未缓存输入，作为会话、模型及整轮的同一口径。"""
    result = summarize_fields(records, FIELDS, incomplete=incomplete)
    inp, cached = result["input_tokens"], result["cached_input_tokens"]
    return {
        "responses": len(records), **result,
        "uncached_input_tokens": (
            inp - cached if inp is not None and cached is not None and inp >= cached else None
        ),
    }


def completed_turn_bounds(events: list[dict], root: str, turn: str) -> tuple[datetime, datetime]:
    """读取原生用户指令和最终回复事件，只接受独立且已完成的根轮次。"""
    starts, instructions, replies, completions = (set() for _ in range(4))
    for row in events:
        payload = row.get("payload", {})
        if payload.get("turn_id") != turn:
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


def completed_subtree_bounds(rows: list[dict], root_turn: str) -> tuple[str, datetime, datetime]:
    """以专用子任务首次启动到最终回复为边界，后续复用属于其他工作。"""
    events = [(timestamp(row["timestamp"]), row["type"], row["payload"]) for row in rows]
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


def descendants_of(anchor: str, links: Iterable[tuple[str, str | None]]) -> set[str]:
    """沿父子索引遍历可达会话或轮次，每个节点最多处理一次。"""
    children = defaultdict(list)
    for child, parent in links:
        children[parent].append(child)
    descendants = {anchor}
    pending = deque([anchor])
    while pending:
        new = set(children[pending.popleft()]) - descendants
        descendants.update(new)
        pending.extend(new)
    return descendants


def model_effort_rows(counts: Counter[tuple[str, str]]) -> list[dict]:
    """按模型和推理力度排序，供两种计量回执共用。"""
    return [
        {"model": model, "effort": effort, "responses": count}
        for (model, effort), count in sorted(counts.items())
    ]


def write_receipt(path: Path, receipt: dict, *, newline: bool = True) -> None:
    """排他保存用量或资源回执，保留原有的 JSON 文本格式。"""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        if newline:
            stream.write("\n")


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
    thread_links = [(tid, parent) for _, tid, parent, _ in files if tid]
    descendants = descendants_of(root, thread_links)
    if subtree_thread_id:
        if subtree_thread_id not in descendants:
            raise ValueError("Requested generation subtree does not belong to this root thread")
        descendants = descendants_of(subtree_thread_id, thread_links)
    anchor = subtree_thread_id or root
    scoped_files = [
        (path, tid, agent_path) for path, tid, _, agent_path in files
        if tid in descendants and (
            include_agent_paths is None or tid == anchor or agent_path in include_agent_paths
        )
    ]
    if completed and any(value is not None for value in (start, end, include_agent_paths)):
        raise ValueError("A completed turn uses native bounds and excludes path filters")
    if not completed and (start is None or end is None or end < start):
        raise ValueError("A manual window requires ordered start and end timestamps")

    damaged: Counter[Path] = Counter()
    parents = {}
    anchor_rows = []
    scoped = []
    for path, tid, agent_path in scoped_files:
        contexts, efforts, recorded = {}, {}, []
        scoped.append((path, tid, agent_path, contexts, efforts, recorded))
        for row in rows(path, damaged):
            kind, payload = row["type"], row.get("payload", {})
            if completed:
                event = payload.get("type")
                if (subtree_thread_id and kind == "event_msg" and event == "task_started"
                        and payload.get("root_turn_id") == turn):
                    parents[payload["turn_id"]] = (
                        (payload.get("turn_attribution") or {}).get("parent_turn_id")
                    )
                if tid == anchor:
                    if subtree_thread_id and (
                        kind == "inter_agent_communication_metadata"
                        or kind == "event_msg" and event == "item_completed"
                    ):
                        timestamp(row["timestamp"])
                    if kind == "event_msg" and event in {"task_started", "task_complete"}:
                        anchor_rows.append(row)
                    elif kind == "event_msg" and event == "item_completed" and (
                        subtree_thread_id or (
                            payload.get("turn_id") == turn and payload.get("thread_id") == root
                        )
                    ):
                        item = payload.get("item") or {}
                        if isinstance(item, dict):
                            item_type = item.get("type")
                            if item_type != "UserMessage" and (
                                item_type != "AgentMessage" or item.get("phase") != "final_answer"
                            ):
                                continue
                            item = {key: item[key] for key in ("id", "type", "phase")
                                    if key in item}
                        elif isinstance(item, str):
                            item = "?"
                        elif isinstance(item, list):
                            item = [None]
                        boundary = {key: payload.get(key) for key in (
                            "type", "thread_id", "turn_id",
                        )}
                        anchor_rows.append({
                            key: row[key] for key in ("type", "timestamp") if key in row
                        } | {"payload": boundary | {"item": item}})
                    elif (kind == "inter_agent_communication_metadata" and subtree_thread_id
                          and payload.get("trigger_turn")):
                        anchor_rows.append({"type": kind, "timestamp": row["timestamp"],
                                            "payload": {"trigger_turn": True}})
            if kind == "turn_context":
                model, context_id, effort = (payload.get(k) for k in ("model", "turn_id", "effort"))
                if not isinstance(context_id, str):
                    damaged[path] += 1
                    continue
                contexts[context_id] = (
                    model if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model)
                    else "unknown"
                )
                if isinstance(effort, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,20}", effort):
                    efforts[context_id] = effort
            elif (kind == "token_usage_record" and payload.get("thread_id") == tid
                  and payload.get("root_turn_id") == turn
                  and (tid != root or payload.get("turn_id") == turn)):
                raw_usage = payload["usage"] if isinstance(payload.get("usage"), dict) else {}
                usage = {field: value for field in FIELDS[:-1]
                         if valid_token(value := raw_usage.get(field))}
                recorded.append((row.get("timestamp"), payload.get("turn_id"),
                                 payload.get("response_id"), usage))

    anchor_turn = turn
    bound_turns = None
    if completed:
        if subtree_thread_id:
            anchor_turn, start, end = completed_subtree_bounds(anchor_rows, turn)
            bound_turns = descendants_of(anchor_turn, parents.items())
        else:
            start, end = completed_turn_bounds(anchor_rows, root, turn)
    conflicts: set[str] = set()
    conflict_files: set[Path] = set()
    seen = {}
    all_usage, agents, requests = [], [], []
    model_effort_counts: Counter[tuple[str, str]] = Counter()
    for path, tid, _, _, _, recorded in scoped:
        selected = []
        for raw_stamp, turn_id, response, valid_usage in recorded:
            if bound_turns is not None and turn_id not in bound_turns:
                continue
            try:
                stamp = timestamp(raw_stamp) if isinstance(raw_stamp, str) else None
            except ValueError:
                stamp = None
            if stamp is None:
                damaged[path] += 1
                continue
            if not completed and not start <= stamp <= end:
                continue
            # 宿主 input 已包含缓存部分，output 已包含其中的推理输出。
            if "input_tokens" in valid_usage and "output_tokens" in valid_usage:
                valid_usage["total_tokens"] = (
                    valid_usage["input_tokens"] + valid_usage["output_tokens"]
                )
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
        recorded[:] = selected

    post_reply = 0
    for path, tid, agent_path, contexts, efforts, entries in scoped:
        selected = [
            (turn_id, usage, stamp) for turn_id, usage, stamp, response in entries
            if response not in conflicts
        ]
        if not selected:
            continue
        incomplete = path in damaged or path in conflict_files
        by_model = defaultdict(list)
        agent_category = category(agent_path or "", tid == anchor)
        for turn_id, usage, stamp in selected:
            model = contexts.get(turn_id, "unknown")
            model_effort_counts[model, efforts.get(turn_id, "unknown")] += 1
            by_model[model].append(usage)
            # 最终回复落盘后仍可能记录该请求的用量。
            post_reply += stamp > end
            if per_request:
                requests.append({
                    "timestamp_utc": stamp.isoformat(),
                    "agent_path": agent_path or "/root",
                    "category": agent_category,
                    "model": model if model != "unknown" else None,
                    "usage": {field: usage.get(field) for field in FIELDS},
                })
        usages = [usage for _, usage, _ in selected]
        all_usage.extend(usages)
        agents.append({
            "agent_path": agent_path or "/root",
            "category": agent_category,
            "turn_count": len({t for t, _, _ in selected}),
            "reasoning_efforts": sorted({
                efforts[t] for t, _, _ in selected if t in efforts
            }),
            "models": {
                model: summarize(values, incomplete=incomplete)
                for model, values in sorted(by_model.items())
            },
            "usage": summarize(usages, incomplete=incomplete),
        })
    anchor_found = any(tid == anchor for _, tid, _ in scoped_files)
    total = summarize(all_usage, incomplete=bool(damaged or conflicts or not anchor_found))
    unknown_fields = [field for field in FIELDS if total[field] is None]
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
            "selected_session_files": len(scoped_files),
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
        "model_effort_response_counts": model_effort_rows(model_effort_counts),
    }
    if completed and subtree_thread_id:
        result["dedicated_subtree"] = {
            "thread_id": anchor, "first_turn_id": anchor_turn,
            "agent_path": next((path for _, tid, path in scoped_files if tid == anchor), None),
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
    write_receipt(args.output, result)
    print(
        json.dumps(
            {"total": result["total"], "output": str(args.output.resolve())}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
