"""绑定当前源码入口，并为宿主生成独立作者任务清单。"""
from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path


def cli_prefix(data_dir: Path | None = None) -> list[str]:
    """将当前解释器、源码入口和数据根绑定为可交给独立作者的命令。"""
    command = [sys.executable, str(Path(__file__).resolve()), "--compact"]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir.resolve())])
    return command


def run_command(data_dir: Path, arguments: list[str]) -> dict:
    """在程序内执行确定性阶段，只把解析后的 JSON 交给调度流程。"""
    process = subprocess.run(cli_prefix(data_dir) + arguments, capture_output=True,
                             text=True, encoding="utf-8",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    result = json.loads(process.stdout)
    if process.returncode:
        raise RuntimeError(result.get("error") or result.get("errors") or process.stderr or result)
    return result


def materialize_inputs(plan: dict, data_dir: Path) -> dict:
    """把待写批次投影到独立文件，协调者仅接收路径，作者一次读取完整材料。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from signaltrail.author_inputs import materialize_input_parts
    from signaltrail.authoring import brief_authoring_input

    for task in plan["tasks"]:
        if task["kind"] == "analysis":
            task.update(materialize_input_parts(Path(task["input_file"])))
            continue
        packet = Path(task["packet_path"])
        source = json.loads(packet.read_text(encoding="utf-8"))
        suffix = "-author-input-v2.json" if task["kind"] == "brief" else "-author-input.json"
        target = packet.parent / "author-inputs" / (packet.stem + suffix)
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            if task["kind"] == "brief":
                payload = brief_authoring_input(packet, data_dir, include_evidence=True)
                # 校验和提交由协调程序完成，避免作者为同一批次重复携带材料调用模型。
                payload.pop("preflight_command", None)
                payload.pop("submission_command", None)
            else:
                payload = source["payload"]["model_input"]
            with target.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        task.update(materialize_input_parts(target))
        task.pop("input_args", None)
        for key in ("input_command", "preflight_command", "prompt"):
            task.pop(key, None)
        if task["kind"] == "brief":
            task.setdefault("batch_id", source["batch_id"])
            run = data_dir / "runs" / source["date"] / f"{source['edition']}.json"
            check = ["submit-authoring-batch", "--run", str(run), "--batch-id",
                     str(task["batch_id"]), "--result", task["draft_result_path"], "--check-only"]
        else:
            task.setdefault("batch_id", source["payload"]["batch_id"])
            check = ["slides", "submit", "--packet", task["packet_path"],
                     "--input", task["draft_result_path"], "--check-only"]
        task["check_command"] = cli_prefix(data_dir) + check
    plan["tasks"].sort(key=lambda task: task.get("input_bytes", 0), reverse=True)
    plan["author_instruction"] = (
        "Follow reader_instruction: read EVERY ordered input_parts file under input_parts_dir, "
        "one part per tool result. Do not print or reread the large input_file. "
        "Use the complete evidence and declared schema, write the draft "
        "to draft_result_path, and return only that path. The coordinator validates and submits. "
        "For numeric comparisons, retain decisive workloads, per-user rates, baselines and scope. "
        "Use only evidence-supported identities and keep each partner matched to its own action. "
        "If a technical translation is uncertain, retain the original name. "
        "Preserve substantive content and delivery quality when optimizing time or tokens. "
        "For functions.exec, set BOTH its outer pragma max_output_tokens and the nested "
        "tools.exec_command max_output_tokens to read_max_output_tokens. Example: "
        "// @exec: {\"max_output_tokens\": READ_LIMIT}\n"
        "const r = await tools.exec_command({cmd: READ_FILE_COMMAND, "
        "max_output_tokens: READ_LIMIT}); text(r.output); "
        "Write the draft and run check_command when present in the SAME tool execution; print "
        "only the validation summary, then repair actual content errors if present. "
        "For repairs, read errors from repair_errors_file before rewriting. "
        "Use a new agent with no inherited history for every task; do not reuse author sessions.")
    return plan


def input_size_hint(task: dict) -> int:
    """优先按已有投影的字节数排序，首次派发用原包大小估计。"""
    packet = Path(task["packet_path"])
    suffix = "-author-input-v2.json" if task["kind"] == "brief" else "-author-input.json"
    projected = packet.parent / "author-inputs" / (packet.stem + suffix)
    if projected.is_file():
        return projected.stat().st_size
    return packet.stat().st_size


def compact_dispatch(plan: dict, *, limit: int = 3, in_flight: tuple[str, ...] = (),
                     data_dir: Path | None = None) -> dict:
    """把完整任务和错误写到作者侧文件，协调者仅接收空槽所需的短任务票据。"""
    tasks = plan.get("tasks", [])
    in_flight = set(in_flight)
    selected = [
        task for task in tasks
        if str(task.get("batch_id") or task["kind"]) not in in_flight
        and task["packet_path"] not in in_flight
    ] if limit > 0 else []
    if data_dir is not None and selected:
        # 先选定空槽使用的批次，再读取完整输入、切块并生成票据。
        plan = materialize_inputs({
            **plan, "tasks": sorted(selected, key=input_size_hint, reverse=True)[:limit],
        }, data_dir)
        selected = plan["tasks"]
    else:
        selected = selected[:limit] if limit > 0 else []
    tickets = []
    for task in selected:
        task_file = Path(task["draft_result_path"]).with_suffix(".dispatch-task.json")
        task_file.write_text(json.dumps(task, ensure_ascii=False, separators=(",", ":")),
                             encoding="utf-8")
        ticket = {key: task[key] for key in (
            "kind", "batch_id", "action", "draft_result_path", "packet_path",
            "read_max_output_tokens", "input_bytes", "check_command", "input_parts_dir",
            "input_parts", "input_part_tokens", "input_tokens", "reader_instruction",
        ) if key in task}
        ticket.update(task_file=str(task_file), error_count=len(task.get("errors", [])))
        if task.get("errors"):
            ticket["repair_errors_file"] = str(task_file)
        tickets.append(ticket)
    receipt = {key: value for key, value in plan.items() if key not in {
        "tasks", "issues", "cli_prefix", "coordinator_commands", "execution", "delivery"}}
    receipt.update(tasks=tickets, pending_task_count=plan.get("pending_task_count", len(tasks)),
                   dispatched_task_count=len(tickets), issue_count=len(plan.get("issues", [])))
    if "background_commands" in receipt:
        receipt["background_commands"] = [command for command in receipt["background_commands"]
                                           if command["id"] not in in_flight]
    if plan.get("issues"):
        directory = (Path(tasks[0]["draft_result_path"]).parent if tasks else
                     Path(plan.get("run_path") or plan["session_path"]).parent)
        issue_file = directory / "dispatch-issues.json"
        issue_file.write_text(json.dumps(plan["issues"], ensure_ascii=False), encoding="utf-8")
        receipt["issues_file"] = str(issue_file)
    if delivery := plan.get("delivery"):
        receipt["delivery"] = {key: delivery[key] for key in (
            "report_status", "delivery_complete", "pending_steps", "report_path", "tail_status"
        ) if key in delivery}
        receipt["delivery"]["slides"] = {key: value for key, value in
            delivery.get("slides", {}).items() if key in {
                "status", "news_count", "html_path", "next_action", "error"}}
    return receipt


def coordinator_dispatch(plan: dict, run: Path, data_dir: Path, *,
                         started: str | None = None, slides_review: Path | None = None,
                         in_flight: tuple[str, ...] = ()) -> dict:
    """为单层协调保留恢复命令；旧交接标记兼容读取，不再强制更换协调者。"""
    command = [sys.executable, str(Path(__file__).resolve()), "--advance-edition",
               str(run.resolve()), "--data-dir", str(data_dir.resolve())]
    if slides_review is not None:
        command.extend(["--slides-review", str(slides_review.resolve())])
    plan["continue_command"] = command
    plan["coordination"] = {"mode": "single", "max_authors": 3}
    return plan


def dispatch_plan(session: Path, data_dir: Path | None = None,
                  run: Path | None = None) -> dict:
    """将简报会话、分析包或图文计划转换为宿主独立作者清单。"""
    session = session.resolve()
    source = json.loads(session.read_text(encoding="utf-8"))
    prefix = [sys.executable, str(Path(__file__).resolve()), "--compact"]
    if data_dir is not None:
        prefix.extend(["--data-dir", str(data_dir.resolve())])
    tasks = []
    coordinator = []

    def task(kind, packet, draft, input_args, preflight):
        return {"kind": kind, "packet_path": str(packet),
                "draft_result_path": str(draft), "fresh_context": True,
                "inherit_history": False, "cli_prefix": prefix,
                "input_command": prefix + input_args,
                "preflight_command": preflight,
                "prompt": (
                    "Read input_file and any listed evidence needed for the analysis. "
                    "Write the declared draft and return its path and status."
                    if kind == "analysis" else
                    "Run input_command once and use its complete embedded evidence throughout "
                    "writing and preflight; reread only targeted evidence if the tool explicitly "
                    "truncates output or evidence is missing. Write the declared draft, run "
                    "preflight_command, and return status and draft path.")}

    if source.get("kind") == "slides-plan":
        for number in range(1, len(source["payload"]["batches"]) + 1):
            if list(session.parent.glob(f"slides-result-{number}-r*.json")):
                continue
            packet = sorted(path for path in session.parent.glob(f"slides-packet-{number}-r*.json")
                            if re.fullmatch(rf"slides-packet-{number}-r\d+\.json", path.name))[0]
            draft = session.parent / f"batch-{number}-draft.json"
            check = prefix + ["slides", "submit", "--packet", str(packet),
                              "--input", str(draft), "--check-only"]
            tasks.append(task("slides", packet, draft,
                              ["slides", "input", "--packet", str(packet)], check))
            tasks[-1]["batch_id"] = number
        submit = prefix + ["slides", "submit", "--plan", str(session),
                           "--draft-dir", str(session.parent)]
        coordinator = [submit + ["--check-only"], submit]
    else:
        analysis = "analysis_result_path" in source
        manifest = (json.loads((session.parent / "session.json").read_text(encoding="utf-8"))
                    if analysis else source)
        if analysis and manifest.get("analysis_completed_at"):
            return {"max_workers": 3, "cli_prefix": prefix, "tasks": [],
                    "coordinator_commands": [],
                    "execution": "Analysis already accepted; no author work remains."}
        if run is None:
            if data_dir is None:
                raise ValueError("Brief and analysis dispatch require --run or --data-dir")
            run = data_dir / "runs" / manifest["date"] / f"{manifest['edition']}.json"
        run = run.resolve()
        if analysis:
            draft = Path(source["analysis_result_path"])
            tasks.append(task("analysis", session, draft, [], None))
            tasks[-1]["input_command"] = None
            tasks[-1]["input_file"] = str(session)
            coordinator = [prefix + ["assemble-authoring", "--run", str(run),
                                     "--analysis", str(draft)]]
        else:
            for batch in source["batches"]:
                if Path(batch["result_path"]).exists():
                    continue
                packet = Path(batch["packet_path"])
                draft = Path(batch["draft_result_path"])
                check = prefix + ["submit-authoring-batch", "--run", str(run),
                                  "--batch-id", batch["batch_id"],
                                  "--result", str(draft), "--check-only"]
                tasks.append(task("brief", packet, draft,
                                  ["brief-input", "--packet", str(packet),
                                   "--include-evidence"], check))
                tasks[-1]["batch_id"] = batch["batch_id"]
            coordinator = [prefix + ["submit-authoring-batch", "--run", str(run), "--all"]]
    return {"max_workers": 3, "cli_prefix": prefix, "tasks": tasks,
            "coordinator_commands": coordinator,
            "execution": ("Host starts fresh-context authors and fills free slots; "
                          "this command only emits a plan.")}


def advance_dispatch(session: Path, data_dir: Path | None = None,
                     run: Path | None = None, *, in_flight: tuple[str, ...] = ()) -> dict:
    """批量接收合格草稿，只将缺失和校验失败的批次交给作者。"""
    session = session.resolve()
    source = json.loads(session.read_text(encoding="utf-8"))
    if "analysis_result_path" in source:
        raise ValueError("Analysis uses --dispatch-plan and assemble-authoring")
    slides = source.get("kind") == "slides-plan"
    prefix = [sys.executable, str(Path(__file__).resolve()), "--compact"]
    if data_dir is not None:
        prefix.extend(["--data-dir", str(data_dir.resolve())])
    if slides:
        command = ["slides", "submit", "--plan", str(session),
                   "--draft-dir", str(session.parent)]
    else:
        if run is None:
            if data_dir is None:
                raise ValueError("Brief dispatch requires --run or --data-dir")
            run = data_dir / "runs" / source["date"] / f"{source['edition']}.json"
        run = run.resolve()
        command = ["submit-authoring-batch", "--run", str(run), "--all"]
    for identity in in_flight:
        command.extend(["--skip-batch", identity])
    process = subprocess.run(prefix + command, capture_output=True, text=True,
                             encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(process.stderr or process.stdout or "Batch submission failed") from exc
    if "batches" not in result:
        raise RuntimeError(result.get("error", "Batch submission failed"))

    batches = {str(batch["batch_id"]): batch for batch in source.get("batches", [])}
    tasks, issues = [], []
    for row in result["batches"]:
        if row.get("accepted_path"):
            continue
        number = row["batch_id"]
        draft = Path(row["draft_path"])
        errors = row.get("errors", [])
        if row.get("expected_path") and Path(row["expected_path"]).exists():
            issues.append({"batch_id": number, "errors": errors})
            continue
        if slides:
            packet = row["packet_path"]
            input_args = ["slides", "input", "--packet", packet]
        else:
            packet = batches[str(number)]["packet_path"]
            input_args = ["brief-input", "--packet", packet, "--include-evidence"]
        tasks.append({"kind": "slides" if slides else "brief", "batch_id": number,
                      "packet_path": packet, "draft_result_path": str(draft),
                      "action": "repair" if draft.is_file() else "write",
                      "errors": errors if draft.is_file() else [],
                      "input_args": input_args, "fresh_context": True,
                      "inherit_history": False})
    return {"status": "partial" if tasks or issues else "ready", "max_workers": 3,
            "session_path": str(session),
            "cli_prefix": prefix, "accepted_count": len(result["accepted"]),
            "author_instruction": ("Run cli_prefix + input_args once; use the complete evidence. "
                                   "Write or repair the draft and return its path. The coordinator "
                                   "will validate and submit it."),
            "execution": ("Exclude batch IDs already in flight before filling free worker slots; "
                          "rerun this command when authors return."),
            "tasks": tasks, "issues": issues}


def advance_edition(run: Path, data_dir: Path | None = None, *,
                    slides_review: Path | None = None,
                    in_flight: tuple[str, ...] = ()) -> dict:
    """推进确定性步骤，返回待写清单，由派发入口按空槽物化作者输入。"""
    run = run.resolve()
    data_dir = (data_dir or run.parents[2]).resolve()

    def manifest():
        """每次阶段完成后读取运行清单，继续使用实际保存的产物路径。"""
        return json.loads(run.read_text(encoding="utf-8"))

    saved = manifest()
    artifacts = saved.get("artifacts", {})
    if saved["status"] == "awaiting_authoring" and not artifacts.get("authoring", {}).get(
            "session_path"):
        return {"stage": "begin_authoring", "run_path": str(run), "tasks": [],
                "next_command": cli_prefix(data_dir) + ["begin-authoring", "--run", str(run)]}
    if saved["status"] == "awaiting_authoring":
        authoring = artifacts["authoring"]
        plan = advance_dispatch(Path(authoring["session_path"]), data_dir, run,
                                in_flight=in_flight)
        if plan["tasks"] or plan["issues"]:
            return {"stage": "briefs", "run_path": str(run),
                    **plan}
        if not authoring.get("analysis_packet_path"):
            run_command(data_dir, ["prepare-analysis", "--run", str(run)])
            authoring = manifest()["artifacts"]["authoring"]
        brief_accepted_count = plan["accepted_count"]
        analysis = Path(authoring["analysis_result_path"])
        analysis_packet = Path(authoring["analysis_packet_path"])
        if ("analysis" in in_flight or str(analysis_packet) in in_flight
                or not analysis.is_file()):
            plan = dispatch_plan(analysis_packet, data_dir, run)
            return {"stage": "analysis", "run_path": str(run),
                    "accepted_count": brief_accepted_count,
                    **plan}
        try:
            run_command(data_dir, ["assemble-authoring", "--run", str(run),
                                   "--analysis", str(analysis)])
        except RuntimeError as exc:
            plan = dispatch_plan(analysis_packet, data_dir, run)
            for task in plan["tasks"]:
                task.update(action="repair", errors=[str(exc)])
            return {"stage": "analysis", "run_path": str(run),
                    "accepted_count": brief_accepted_count,
                    **plan}
        authoring = manifest()["artifacts"]["authoring"]
        command = ["finalize-edition", "--run", str(run), "--report",
                   authoring["report_draft_path"], "--defer-tail"]
        if slides_review is not None:
            command.extend(["--slides-review", str(slides_review.resolve())])
        run_command(data_dir, command)
        saved = manifest()
        artifacts = saved["artifacts"]
    if saved["status"] not in {"completed", "completed_partial"}:
        return {"stage": "collection", "run_path": str(run), "tasks": [],
                "next_action": saved.get("next_action")}
    if slides_review is not None and not artifacts.get("slides", {}).get("plan_path"):
        run_command(data_dir, ["finalize-edition", "--run", str(run), "--report",
                               artifacts["json_path"], "--defer-tail", "--slides-review",
                               str(slides_review.resolve())])
        artifacts = manifest()["artifacts"]
    slides = artifacts.get("slides", {})
    if slides.get("plan_path"):
        plan = advance_dispatch(Path(slides["plan_path"]), data_dir, run,
                                in_flight=in_flight)
        if plan["tasks"] or plan["issues"]:
            slide_plan = Path(slides["plan_path"])
            plan["background_commands"] = []
            if saved.get("tail", {}).get("status") not in {None, "completed"}:
                plan["background_commands"].append({"id": "edition-tail",
                    "command": cli_prefix(data_dir) + ["complete-edition-tail", "--run", str(run)]})
            receipt_path = slide_plan.with_name("images-" + slide_plan.name)
            if not receipt_path.is_file():
                plan["background_commands"].append({"id": "slides-images",
                    "command": cli_prefix(data_dir) + ["slides", "prefetch-images", "--plan",
                                                       str(slide_plan)],
                    "receipt_path": str(receipt_path)})
            return {"stage": "slides", "run_path": str(run),
                    **plan}
        if any(job in in_flight for job in ("edition-tail", "slides-images")):
            return {"stage": "slides", "run_path": str(run), **plan}
    delivery = run_command(data_dir, ["edition-status", "--run", str(run)])
    if "tail" in delivery["pending_steps"]:
        run_command(data_dir, ["complete-edition-tail", "--run", str(run)])
    deck = None
    if "slides_render" in delivery["pending_steps"]:
        deck = run_command(data_dir, ["slides", "render", "--plan", slides["plan_path"]])
    if "tail" in delivery["pending_steps"] or deck:
        delivery = run_command(data_dir, ["edition-status", "--run", str(run)])
    return {"stage": "complete" if delivery["delivery_complete"] else "delivery",
            "run_path": str(run), "tasks": [], "delivery": delivery,
            **({"deck_path": deck["json_path"]} if deck else {})}


def main() -> None:
    """在导入 CLI 前优先当前 src，避免已安装技能副本覆盖工作区。"""
    if sys.argv[1:2] in (["--dispatch-plan"], ["--advance-dispatch"], ["--advance-edition"],
                         ["--prepare-input-parts"]):
        parser = argparse.ArgumentParser()
        parser.add_argument(sys.argv[1], type=Path, required=True)
        parser.add_argument("--data-dir", type=Path)
        parser.add_argument("--run", type=Path)
        parser.add_argument("--slides-review", type=Path)
        parser.add_argument("--materialize-inputs", action="store_true")
        parser.add_argument("--task-limit", type=int, default=3)
        parser.add_argument("--in-flight", action="append", default=[])
        parser.add_argument("--compact-dispatch", action="store_true")
        parser.add_argument("--coordinator-start",
                            help="Legacy checkpoint marker; accepted without forcing a handoff")
        args = parser.parse_args()
        if sys.argv[1] == "--prepare-input-parts":
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
            from signaltrail.author_inputs import materialize_input_parts

            print(json.dumps(materialize_input_parts(args.prepare_input_parts),
                             ensure_ascii=False, separators=(",", ":")))
            return
        if sys.argv[1] == "--advance-edition":
            result = advance_edition(args.advance_edition, args.data_dir,
                                     slides_review=args.slides_review, in_flight=args.in_flight)
            data_dir = args.data_dir or args.advance_edition.resolve().parents[2]
            result = coordinator_dispatch(
                result, args.advance_edition, data_dir,
                started=args.coordinator_start, slides_review=args.slides_review,
                in_flight=tuple(args.in_flight),
            )
            result = compact_dispatch(result, limit=args.task_limit, in_flight=args.in_flight,
                                      data_dir=data_dir)
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return
        advance = sys.argv[1] == "--advance-dispatch"
        session = args.advance_dispatch if advance else args.dispatch_plan
        result = (advance_dispatch(session, args.data_dir, args.run, in_flight=args.in_flight)
                  if advance else dispatch_plan(session, args.data_dir, args.run))
        if args.materialize_inputs and args.data_dir is None:
            parser.error("--materialize-inputs requires --data-dir")
        if args.compact_dispatch:
            result = compact_dispatch(result, limit=args.task_limit, in_flight=args.in_flight,
                                      data_dir=args.data_dir if args.materialize_inputs else None)
        elif args.materialize_inputs:
            result = materialize_inputs(result, args.data_dir)
        print(json.dumps(result, ensure_ascii=advance))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    runpy.run_module("signaltrail.cli", run_name="__main__")


if __name__ == "__main__":
    main()
