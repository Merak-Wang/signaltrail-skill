"""绑定当前源码入口，并为宿主生成独立作者任务清单。"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from heapq import heapify, heapreplace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_MAX_AUTHOR_BUNDLE_TOKENS = 24_000
_MAX_AUTHOR_SECOND_BATCH_TOKENS = 10_000
_SHARED_CANDIDATE_FIELDS = {
    "source_name", "module", "category", "source_language", "translation_required",
    "content_status", "content_observations", "feed_content_status", "published_precision",
    "previously_reported", "suggested_status", "first_discovered_at",
}


def cli_prefix(data_dir: Path | None = None) -> list[str]:
    """将当前解释器、源码入口和数据根绑定为可交给独立作者的命令。"""
    command = [sys.executable, str(Path(__file__).resolve()), "--compact"]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir.resolve())])
    return command


def run_command(data_dir: Path, arguments: list[str]) -> dict:
    """在程序内执行确定性阶段，只把解析后的 JSON 交给调度流程。"""
    from signaltrail.cli import main
    from signaltrail.commands.common import JSON_RECEIPTS

    receipts = []
    token = JSON_RECEIPTS.set(receipts)
    try:
        status = main(["--compact", "--data-dir", str(data_dir.resolve()), *arguments])
    except (Exception, SystemExit) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        raise RuntimeError(f"{arguments[0]} exited with code {code}: {detail}") from exc
    finally:
        JSON_RECEIPTS.reset(token)
    if len(receipts) != 1:
        raise RuntimeError(f"{arguments[0]} returned {len(receipts)} receipts (exit {status})")
    result = receipts[0]
    if status:
        detail = result.get("error") or result.get("errors") or result
        raise RuntimeError(f"{arguments[0]} exited with code {status}: {detail}")
    return result


def _author_input(kind: str, packet: str) -> list[str]:
    """生成作者正常读取完整证据的命令参数。"""
    if kind == "brief":
        return ["brief-input", "--packet", packet, "--include-evidence"]
    return ["slides", "input", "--packet", packet]


def _author_check(kind: str, packet: str, draft: str, batch_id: str | int | None,
                  run: Path | None) -> list[str]:
    """统一直接派发和物化票据的单批预检。"""
    if kind == "brief":
        return ["submit-authoring-batch", "--run", str(run), "--batch-id", str(batch_id),
                "--result", draft, "--check-only"]
    return ["slides", "submit", "--packet", packet, "--input", draft, "--check-only"]


def _author_input_file(packet: Path, kind: str) -> Path:
    """已派发的简报继续读取冻结的 v2，新批次使用按来源共享字段的 v3。"""
    directory = packet.parent / "author-inputs"
    if kind == "brief":
        previous = directory / (packet.stem + "-author-input-v2.json")
        if previous.is_file():
            return previous
        return directory / (packet.stem + "-author-input-v3.json")
    return directory / (packet.stem + "-author-input.json")


def _share_candidate_fields(payload: dict) -> None:
    """同一来源在本批完全相同的背景信息只写一次，文章顺序、正文和差异仍逐条呈现。"""
    groups = {}
    for row in payload.get("candidates", []):
        if source := row.get("source_id"):
            groups.setdefault(source, []).append(row)
    defaults = {}
    for source, rows in groups.items():
        if len(rows) < 2:
            continue
        shared = {key: value for key, value in rows[0].items()
                  if key in _SHARED_CANDIDATE_FIELDS
                  and all(key in row and row[key] == value for row in rows[1:])}
        if shared:
            defaults[source] = shared
            for row in rows:
                for key in shared:
                    del row[key]
    if defaults:
        payload["authoring_scope"] += (
            " Each candidate inherits all fields in candidate_defaults_by_source for its "
            "source_id, including any shared evidence qualifications."
        )
        # 先展示共同字段，再读逐条差异，长篇原文放在最后。
        candidates = payload.pop("candidates")
        evidence = payload.pop("evidence_by_item_id")
        payload.update(candidate_defaults_by_source=defaults, candidates=candidates,
                       evidence_by_item_id=evidence)


def _materialize_task(task: dict, data_dir: Path, *, split_input: bool) -> None:
    """替换作者票据的读取方式，保留证据内容与原校验规则。"""
    from signaltrail.author_inputs import materialize_input_parts

    kind = task["kind"]
    if kind == "analysis":
        task.update(materialize_input_parts(Path(task["input_file"]), split_input=split_input))
        return

    packet = Path(task["packet_path"])
    source = json.loads(packet.read_bytes())
    target = _author_input_file(packet, kind)
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        if kind == "brief":
            from signaltrail.authoring import brief_authoring_input

            payload = brief_authoring_input(packet, data_dir, include_evidence=True)
            _share_candidate_fields(payload)
            # 校验和提交由协调程序完成，避免作者为同一批次重复携带材料调用模型。
            payload.pop("preflight_command", None)
            payload.pop("submission_command", None)
        else:
            payload = source["payload"]["model_input"]
        with target.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))

    task.update(materialize_input_parts(target, split_input=split_input))
    for key in ("input_args", "input_command", "preflight_command", "prompt"):
        task.pop(key, None)
    run = None
    if kind == "brief":
        task.setdefault("batch_id", source["batch_id"])
        run = data_dir / "runs" / source["date"] / f"{source['edition']}.json"
    else:
        task.setdefault("batch_id", source["payload"]["batch_id"])
    task["check_command"] = cli_prefix(data_dir) + _author_check(
        kind, task["packet_path"], task["draft_result_path"], task["batch_id"], run)


def materialize_inputs(plan: dict, data_dir: Path, *, split_input: bool = True) -> dict:
    """把待写批次投影到独立文件，协调者仅接收路径，作者一次读取完整材料。"""
    for task in plan["tasks"]:
        _materialize_task(task, data_dir, split_input=split_input)
    plan["tasks"].sort(key=lambda task: task.get("input_bytes", 0), reverse=True)
    plan["author_instruction"] = (
        "Use a fresh author per assignment. Read every ordered input_parts file in full, "
        "one per tool result. Set both the outer functions.exec pragma and the inner "
        "exec_command max_output_tokens to read_max_output_tokens. Use the evidence and "
        "schema for that task only. Preserve names, actors, quantities, units, baselines "
        "and qualifications. Save at draft_result_path, run any check_command in the same "
        "execution, and repair reported errors. Return draft paths and compact checks."
    ) if split_input else "Use each complete input_file with its own draft and repair errors."
    return plan


def input_size_hint(task: dict) -> int:
    """优先按已有投影的字节数排序，首次派发用原包大小估计。"""
    packet = Path(task["packet_path"])
    projected = _author_input_file(packet, task["kind"])
    return (projected if projected.is_file() else packet).stat().st_size


def estimated_schedule_finish(active: list[int], pending: list[int]) -> int:
    """用输入字节量估计当前空槽处理队列所需的最长累计负载。"""
    queue = active.copy()
    heapify(queue)
    for size in pending:
        heapreplace(queue, queue[0] + size)
    return max(queue)


def author_groups(plan: dict, selected: list[dict], data_dir: Path, limit: int,
                  bundle_size: int, *, split_input: bool = True) -> tuple[dict, list[list[dict]]]:
    """保留大任务先派发，为空槽内的正常写作补入证据总量受限的小包。"""
    size = {task["packet_path"]: input_size_hint(task) for task in selected}
    ordered = sorted(selected, key=lambda task: size[task["packet_path"]], reverse=True)
    plan = materialize_inputs({**plan, "tasks": ordered[:limit]}, data_dir, split_input=split_input)
    groups = [[task] for task in plan["tasks"]]
    if bundle_size == 1:
        return plan, groups
    pending = ordered[limit:]
    workloads = [size[group[0]["packet_path"]] for group in groups]
    maximum = estimated_schedule_finish(workloads, [size[task["packet_path"]] for task in pending])
    for number in reversed(range(len(groups))):
        group = groups[number]
        anchor = group[0]
        if anchor.get("action") != "write" or anchor["kind"] not in {"brief", "slides"}:
            continue
        room = min(_MAX_AUTHOR_SECOND_BATCH_TOKENS,
                   _MAX_AUTHOR_BUNDLE_TOKENS - anchor["input_tokens"])
        if room <= 0:
            continue
        candidates = [task for task in pending if task.get("action") == "write"
                      and task["kind"] == anchor["kind"] and size[task["packet_path"]] <= room * 5]
        for extra in candidates[:3]:
            updated_workloads = workloads.copy()
            updated_workloads[number] += size[extra["packet_path"]]
            remaining = [task for task in pending if task is not extra]
            if estimated_schedule_finish(updated_workloads, [
                size[task["packet_path"]] for task in remaining
            ]) > maximum:
                continue
            _materialize_task(extra, data_dir, split_input=split_input)
            if extra["input_tokens"] <= room:
                # 先读较小的包，缩短后来写作步骤携带的前一包历史。
                group.append(extra)
                group.sort(key=lambda task: task["input_tokens"])
                pending = remaining
                workloads = updated_workloads
                break
    return plan, groups


def compact_dispatch(plan: dict, *, limit: int = 3, in_flight: tuple[str, ...] = (),
                     data_dir: Path | None = None, bundle_size: int = 1,
                     split_input: bool = True) -> dict:
    """把完整任务和错误写到作者侧文件，协调者仅接收空槽所需的短任务票据。"""
    tasks = plan.get("tasks", [])
    active = set(in_flight)
    selected = [
        task for task in tasks
        if str(task.get("batch_id") or task["kind"]) not in active
        and task["packet_path"] not in active
    ] if limit > 0 else []
    if data_dir is not None and selected:
        # 先选定空槽使用的批次，再读取完整输入、切块并生成票据。
        plan, groups = author_groups(
            plan, selected, data_dir, limit, bundle_size, split_input=split_input,
        )
    else:
        groups = [[task] for task in selected[:limit]]
    receipt = {key: value for key, value in plan.items() if key not in {
        "tasks", "issues", "cli_prefix", "coordinator_commands", "execution", "delivery"}}
    receipt.update(pending_task_count=plan.get("pending_task_count", len(tasks)),
                   dispatched_task_count=sum(map(len, groups)),
                   issue_count=len(plan.get("issues", [])))
    tickets = []
    for group in groups:
        files = []
        for task in group:
            path = Path(task["draft_result_path"]).with_suffix(".dispatch-task.json")
            path.write_text(json.dumps(task, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
            files.append(str(path))
        if bundle_size > 1:
            tickets.append({"in_flight": [str(t.get("batch_id") or t["kind"]) for t in group],
                            "task_files": files})
            continue
        task, = group
        path, = files
        ticket = {key: task[key] for key in (
            "kind", "batch_id", "action", "draft_result_path", "packet_path",
            "read_max_output_tokens", "input_bytes", "check_command", "input_parts_dir",
            "input_parts", "input_part_tokens", "input_tokens", "reader_instruction",
        ) if key in task}
        ticket.update(task_file=path, error_count=len(task.get("errors", [])))
        if task.get("errors"):
            ticket["repair_errors_file"] = path
        tickets.append(ticket)
    if bundle_size == 1:
        receipt["tasks"] = tickets
    else:
        receipt.update(author_assignments=tickets, dispatched_author_count=len(tickets))
        if tickets:
            receipt["author_instruction"] += (
                " Read the assigned task files in order. Finish each draft before opening "
                "the next file. Use each file's own repair errors and evidence."
            )
    if "background_commands" in receipt:
        receipt["background_commands"] = [command for command in receipt["background_commands"]
                                           if command["id"] not in active]
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
                         in_flight: tuple[str, ...] = (), bundle_size: int = 1) -> dict:
    """为单层协调保留恢复命令；旧交接标记兼容读取，不再强制更换协调者。"""
    command = [sys.executable, str(Path(__file__).resolve()), "--advance-edition",
               str(run.resolve()), "--data-dir", str(data_dir.resolve())]
    if slides_review is not None:
        command.extend(["--slides-review", str(slides_review.resolve())])
    if bundle_size > 1:
        command.extend(["--author-bundle-size", str(bundle_size)])
    plan["continue_command"] = command
    plan["coordination"] = {"mode": "single", "max_authors": 3}
    return plan


def dispatch_plan(session: Path, data_dir: Path | None = None,
                  run: Path | None = None, *, repair_analysis: bool = False) -> dict:
    """将简报会话、分析包或图文计划转换为宿主独立作者清单。"""
    session = session.resolve()
    source = json.loads(session.read_text(encoding="utf-8"))
    prefix = cli_prefix(data_dir)
    tasks = []
    coordinator = []

    def task(kind, packet, draft, batch_id=None, run=None):
        """在原有计划中登记作者命令和结果路径。"""
        packet, draft = str(packet), str(draft)
        analysis = kind == "analysis"
        row = {"kind": kind, "packet_path": packet, "draft_result_path": draft,
               "fresh_context": True, "inherit_history": False, "cli_prefix": prefix,
               "input_command": None if analysis else prefix + _author_input(kind, packet),
               "preflight_command": None if analysis else
               prefix + _author_check(kind, packet, draft, batch_id, run),
               "prompt": (
                   "Read input_file and any listed evidence needed for the analysis. "
                   "Write the declared draft and return its path and status."
                   if analysis else
                   "Run input_command once and use its complete embedded evidence throughout "
                   "writing and preflight; reread only targeted evidence if the tool explicitly "
                   "truncates output or evidence is missing. Write the declared draft, run "
                   "preflight_command, and return status and draft path.")}
        if analysis:
            row["input_file"] = packet
        else:
            row["batch_id"] = batch_id
        tasks.append(row)

    if source.get("kind") == "slides-plan":
        from signaltrail.news_slides import slide_batch_paths

        results = slide_batch_paths(session, "result")
        packets = slide_batch_paths(session, "packet")
        for number in range(1, len(source["payload"]["batches"]) + 1):
            if str(number) in results:
                continue
            packet = packets.get(str(number))
            if packet is None:
                raise ValueError(f"Missing packet for batch {number}")
            draft = session.parent / f"batch-{number}-draft.json"
            task("slides", packet, draft, number)
        submit = prefix + ["slides", "submit", "--plan", str(session),
                           "--draft-dir", str(session.parent)]
        coordinator = [submit + ["--check-only"], submit]
    else:
        analysis = "analysis_result_path" in source
        manifest = (json.loads((session.parent / "session.json").read_text(encoding="utf-8"))
                    if analysis else source)
        if analysis and not repair_analysis and manifest.get("analysis_completed_at"):
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
            task("analysis", session, draft)
            coordinator = [prefix + ["assemble-authoring", "--run", str(run),
                                     "--analysis", str(draft)]]
        else:
            for batch in source["batches"]:
                if Path(batch["result_path"]).exists():
                    continue
                packet = Path(batch["packet_path"])
                draft = Path(batch["draft_result_path"])
                task("brief", packet, draft, batch["batch_id"], run)
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
    from signaltrail.commands.editions import submit_brief_batches
    from signaltrail.commands.slides import submit_slide_batches
    from signaltrail.config import resolve_data_dir

    prefix = cli_prefix(data_dir)
    root = resolve_data_dir(data_dir)
    if slides:
        result = submit_slide_batches(root, plan_path=session, draft_dir=session.parent,
                                      skip_batch=in_flight)
    else:
        if run is None:
            if data_dir is None:
                raise ValueError("Brief dispatch requires --run or --data-dir")
            run = root / "runs" / source["date"] / f"{source['edition']}.json"
        result = submit_brief_batches(run.resolve(), root, skip_batch=in_flight)

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
        kind = "slides" if slides else "brief"
        packet = row["packet_path"] if slides else batches[str(number)]["packet_path"]
        draft_exists = draft.is_file()
        tasks.append({"kind": kind, "batch_id": number, "packet_path": packet,
                      "draft_result_path": str(draft),
                      "action": "repair" if draft_exists else "write",
                      "errors": errors if draft_exists else [],
                      "input_args": _author_input(kind, packet), "fresh_context": True,
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

    def finalize(report: str) -> None:
        """使用当前写作草稿或已发布 JSON 完成报告与图文的绑定。"""
        command = ["finalize-edition", "--run", str(run), "--report", report, "--defer-tail"]
        if slides_review is not None:
            command.extend(["--slides-review", str(slides_review.resolve())])
        run_command(data_dir, command)

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
        def analysis_dispatch(error: str | None = None) -> dict:
            """交还当前分析任务，并把确定性阶段的失败诊断交给同一作者。"""
            plan = dispatch_plan(analysis_packet, data_dir, run, repair_analysis=True)
            if error is not None:
                for task in plan["tasks"]:
                    task.update(action="repair", errors=[error])
            return {"stage": "analysis", "run_path": str(run),
                    "accepted_count": brief_accepted_count, **plan}

        if ("analysis" in in_flight or str(analysis_packet) in in_flight
                or not analysis.is_file()):
            return analysis_dispatch()
        try:
            run_command(data_dir, ["assemble-authoring", "--run", str(run),
                                   "--analysis", str(analysis)])
            finalize(manifest()["artifacts"]["authoring"]["report_draft_path"])
        except RuntimeError as exc:
            if manifest()["status"] != "awaiting_authoring":
                raise
            return analysis_dispatch(str(exc))
        saved = manifest()
        artifacts = saved["artifacts"]
    if saved["status"] not in {"completed", "completed_partial"}:
        return {"stage": "collection", "run_path": str(run), "tasks": [],
                "next_action": saved.get("next_action")}
    if slides_review is not None and not artifacts.get("slides", {}).get("plan_path"):
        finalize(artifacts["json_path"])
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


def advance_author_queue(run: Path, data_dir: Path, *, slides_review: Path | None = None,
                         in_flight: tuple[str, ...] = (), limit: int = 3,
                         bundle_size: int = 1, split_input: bool = True) -> dict:
    """按正式阶段推进一次，在同一进程复用分词器并返回可派发的作者任务。"""
    result = advance_edition(run, data_dir, slides_review=slides_review, in_flight=in_flight)
    coordinator_dispatch(result, run, data_dir, slides_review=slides_review,
                         bundle_size=bundle_size)
    return compact_dispatch(result, limit=limit, in_flight=in_flight,
                            data_dir=data_dir, bundle_size=bundle_size, split_input=split_input)


def main() -> None:
    """优先当前源码，并保留各派发入口的参数与输出格式。"""
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    if mode not in {"--dispatch-plan", "--advance-dispatch", "--advance-edition",
                    "--prepare-input-parts"}:
        runpy.run_module("signaltrail.cli", run_name="__main__")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument(mode, type=Path, required=True,
                        dest="path", metavar=mode[2:].replace("-", "_").upper())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--slides-review", type=Path)
    parser.add_argument("--materialize-inputs", action="store_true")
    parser.add_argument("--task-limit", type=int, default=3)
    parser.add_argument("--author-bundle-size", type=int, choices=(1, 2), default=1)
    parser.add_argument("--in-flight", action="append", default=[])
    parser.add_argument("--compact-dispatch", action="store_true")
    parser.add_argument("--coordinator-start",
                        help="Legacy checkpoint marker; accepted without forcing a handoff")
    args = parser.parse_args()
    if args.author_bundle_size > 1 and mode != "--advance-edition":
        parser.error("--author-bundle-size requires --advance-edition")

    if mode == "--prepare-input-parts":
        from signaltrail.author_inputs import materialize_input_parts

        result = materialize_input_parts(args.path)
    elif mode == "--advance-edition":
        result = advance_author_queue(
            args.path, args.data_dir or args.path.resolve().parents[2],
            slides_review=args.slides_review, in_flight=tuple(args.in_flight),
            limit=args.task_limit, bundle_size=args.author_bundle_size,
        )
    else:
        result = (advance_dispatch(args.path, args.data_dir, args.run, in_flight=args.in_flight)
                  if mode == "--advance-dispatch"
                  else dispatch_plan(args.path, args.data_dir, args.run))
        if args.materialize_inputs and args.data_dir is None:
            parser.error("--materialize-inputs requires --data-dir")
        if args.compact_dispatch:
            result = compact_dispatch(result, limit=args.task_limit, in_flight=args.in_flight,
                                      data_dir=args.data_dir if args.materialize_inputs else None)
        elif args.materialize_inputs:
            result = materialize_inputs(result, args.data_dir)

    separators = (",", ":") if mode in {"--prepare-input-parts", "--advance-edition"} else None
    print(json.dumps(result, ensure_ascii=mode == "--advance-dispatch", separators=separators))


if __name__ == "__main__":
    main()
