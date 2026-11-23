"""比较宿主实测用量，并按显式任务依赖估算目标输出速率下的关键路径。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measure_codex_turn import write_receipt


def read_json(path: Path) -> dict:
    """读取测量或场景文件，交给同一比较入口。"""
    return json.loads(path.read_text(encoding="utf-8"))


def measured_run(path: Path) -> dict:
    """保留原始宿主累计用量、覆盖规模和阶段时间，作为实测比较行。"""
    data = read_json(path)
    total = data["total"]
    artifacts = data.get("artifacts", {})
    return {
        "source": str(path.resolve()), "kind": "measured",
        "wall_seconds": data["wall_seconds"],
        "responses": total["responses"],
        "total_tokens": total["total_tokens"],
        "cached_input_tokens": total.get("cached_input_tokens"),
        "uncached_input_tokens": total.get("uncached_input_tokens"),
        "output_tokens": total.get("output_tokens"),
        "delivered_briefs": artifacts.get("delivered_briefs", data.get("run_briefs")),
        "by_role": data.get("by_role"),
        "stages": data.get("stages"),
        "videos": artifacts.get("videos", [data["video"]] if data.get("video") else []),
    }


def simulate(scenario: dict) -> dict:
    """按依赖和共享作者槽位调度任务，输出生成时间与固定阶段时间共同决定结束点。"""
    rate = scenario["output_tokens_per_second"]
    workers = scenario["workers"]
    tasks = {task["id"]: task for task in scenario["tasks"]}
    pending = list(tasks)
    pools = {name: [0.0] * count for name, count in
             scenario.get("resources", {"authors": workers}).items()}
    done = {}
    rows = []
    while pending:
        ready = [key for key in pending
                 if all(parent in done for parent in tasks[key].get("depends_on", []))]
        if not ready:
            raise ValueError("Task dependencies contain a cycle or unknown task")
        # 优先调度最早可运行的任务；同一时刻按输入清单顺序保持可复查。
        def earliest(key: str) -> float:
            """从已完成前置和可用作者槽位得到最早启动时刻。"""
            task = tasks[key]
            dependency = max((done[parent] for parent in task.get("depends_on", [])),
                             default=0.0)
            slots = pools[task.get("resource", "authors")] if task.get("model") else []
            return max(dependency, min(slots)) if slots else dependency

        key = min(ready, key=earliest)
        task = tasks[key]
        started = earliest(key)
        fixed = task.get("fixed_seconds", 0.0)
        generated = task.get("output_tokens", 0) / rate if task.get("model") else 0.0
        duration = fixed + generated
        finished = started + duration
        if task.get("model"):
            slots = pools[task.get("resource", "authors")]
            slot = min(range(len(slots)), key=slots.__getitem__)
            slots[slot] = finished
        else:
            slot = None
        done[key] = finished
        pending.remove(key)
        rows.append({"id": key, "worker": slot, "start_seconds": round(started, 3),
                     "end_seconds": round(finished, 3),
                     "generated_seconds": round(generated, 3), "fixed_seconds": fixed})
    model_tasks = [task for task in tasks.values() if task.get("model")]
    token_values = [task.get("total_tokens") for task in model_tasks]
    total = sum(token_values) if all(value is not None for value in token_values) else None
    wall = max(done.values(), default=0.0)
    return {
        "kind": "projection", "name": scenario["name"],
        "output_tokens_per_second": rate, "workers": workers,
        "resources": {name: len(slots) for name, slots in pools.items()},
        "wall_seconds": round(wall, 3), "total_tokens": total,
        "within_30_minutes": wall <= 1800,
        "within_25_million_tokens": total <= 25_000_000 if total is not None else None,
        "assumptions": scenario.get("assumptions", []), "schedule": rows,
    }


def compare(measurements: list[Path], scenarios: list[Path]) -> dict:
    """将原始实测行与显式假设下的场景并列，计算相对最后一次实测的变化。"""
    measured = [measured_run(path) for path in measurements]
    projected = [simulate(read_json(path)) | {"source": str(path.resolve())}
                 for path in scenarios]
    reference = measured[-1] if measured else None
    if reference:
        for row in projected:
            row["versus_last_measured"] = {
                "wall_seconds_change": round(row["wall_seconds"] - reference["wall_seconds"], 3),
                "total_tokens_change": (row["total_tokens"] - reference["total_tokens"]
                                        if row["total_tokens"] is not None else None),
            }
    return {
        "measured": measured, "projected": projected,
        "interpretation": [
            "Measured total_tokens includes cached input; coverage is shown for each run.",
            "Projection changes output generation time only. Input, tool, network and local "
            "processing time must be represented in fixed_seconds or task dependencies.",
            "Workers denotes independent requests each sustaining the stated output rate; "
            "an account-wide shared rate requires a different scenario.",
            "Projected total_tokens must be supplied per model task from a stated estimate "
            "or measurement; unknown values remain null.",
        ],
    }


def main() -> None:
    """解析重复测量和场景路径，将完整比较写到新的输出文件。"""
    parser = argparse.ArgumentParser(
        description="Compare host usage and estimate the workflow critical path."
    )
    parser.add_argument("--measurement", type=Path, action="append", default=[])
    parser.add_argument("--scenario", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.measurement, args.scenario)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_receipt(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()),
                      "measured_runs": len(result["measured"]),
                      "projected": [{key: row[key] for key in (
                          "name", "wall_seconds", "total_tokens", "within_30_minutes",
                          "within_25_million_tokens")} for row in result["projected"]]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
