"""用固定的 50 页图文稿评估真实派发、批量接收和渲染链路。"""

from __future__ import annotations

import json
import multiprocessing
import os
import wave
from collections import Counter
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from scripts.run_signaltrail import (
    advance_dispatch,
    compact_dispatch,
    coordinator_dispatch,
    run_command,
)
from signaltrail.analysis_repair import apply_stakeholder_repair, stakeholder_repair
from signaltrail.narrative_store import load_artifact, save_artifact
from signaltrail.news_slides import prepare_slides, render_slides
from signaltrail.slide_video import _export_lock, prefetch_speech
from signaltrail.utils import read_json, write_json
from signaltrail.voice_synthesis import VoiceSynthesizer

from .report import _frozen_report_inputs
from .slides import PAGE_COUNT, _make_fixture, _rendered_pages

AUTHOR_LIMIT = 3
BATCH_SIZE = 4


def _hold_video_lock(work: Path, ready) -> None:
    """在子进程中持有正式导出锁，等待父进程强制终止。"""
    with _export_lock(work):
        ready.send(True)
        ready.recv()


def _lock_contended(work: Path) -> bool:
    """检查正式导出锁是否报告路径被其他活动进程占用。"""
    try:
        with _export_lock(work):
            return False
    except RuntimeError as error:
        return str(error).startswith("Another video export holds")


def _check_video_lock(work: Path) -> dict:
    """验证活动导出互斥、异常退出恢复，以及旧版存活锁的兼容边界。"""
    spawn = multiprocessing.get_context("spawn")
    receive, send = spawn.Pipe()
    owner = spawn.Process(target=_hold_video_lock, args=(work, send))
    owner.start()
    send.close()
    try:
        if not receive.poll(15) or not receive.recv():
            raise RuntimeError("Video lock child did not acquire the lock")
        contended = _lock_contended(work)
    finally:
        owner.kill()
        owner.join(15)
        receive.close()
    with _export_lock(work):
        recovered = owner.exitcode not in (None, 0) and (work / ".export.os-lock").is_file()

    legacy = work / "legacy"
    legacy_path = write_json(legacy / ".export.lock", {"pid": os.getpid(), "output": "old.mp4"})
    legacy_contended = _lock_contended(legacy)
    write_json(legacy_path, {"pid": owner.pid, "output": "old.mp4"})
    with _export_lock(legacy):
        legacy_recovered = read_json(legacy_path) == {"kind": "os-lock-migration"}
    owner.close()
    return {
        "video_export_holds_cross_process_lock": contended,
        "video_export_retries_after_owner_killed": recovered,
        "video_export_preserves_live_legacy_lock": legacy_contended,
        "video_export_recovers_dead_legacy_lock": legacy_recovered,
    }


def _author_payload(ticket: dict, drafts: dict, data_dir: Path) -> tuple[dict, bool]:
    """按作者票据读入全部分块，并核对它们逐字节还原生产写作包。"""
    directory = Path(ticket["input_parts_dir"])
    complete = b"".join((directory / name).read_bytes() for name in ticket["input_parts"])
    packet_path = Path(ticket["packet_path"])
    packet = load_artifact(packet_path, data_dir)["payload"]["model_input"]
    encoded_packet = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()
    recovered = json.loads(complete)
    result = {"slides": [drafts[news["event_id"]] for news in recovered["news"]]}
    if "video_title" in recovered["output_schema"]["properties"]:
        result["video_title"] = "社区公共服务试点公报"
    return result, complete == encoded_packet


def _check_speech_prefetch(plan_path: Path, data_dir: Path, *, follow: bool = False) -> dict:
    """用已接受和未接受批次验证真实缓存身份，替换成本机固定波形合成。"""
    model = data_dir / "offline-speech-model"
    model.mkdir(exist_ok=True)
    for name in ("model.int8.onnx", "tokens.txt", "lexicon.txt"):
        (model / name).write_bytes(b"offline-fixture")
    invoked = []

    def fake_page(_voice, title, brief, destination, *, language):
        """仅替换原生推理与后处理，保留生产缓存校验。"""
        invoked.append((title, brief, language))
        for path in (destination, destination.with_suffix(".raw.wav")):
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 2400)
        return {"duration": .1, "provider": "cpu", "segments": []}

    output = data_dir / "preview.mp4"
    runtime = {"provider": "cpu", "tts_executable": Path(__file__), "model_dir": model}
    with (
        patch("signaltrail.video_runtime.ensure_video_runtime", return_value=runtime) as setup,
        patch.object(VoiceSynthesizer, "_page", fake_page),
    ):
        if follow:
            accepted = sorted(plan_path.parent.glob("slides-result-*-r*.json"))[-1]
            hidden = accepted.with_suffix(".fixture-pending")
            accepted.rename(hidden)

            def publish(_seconds):
                """在首次空闲等待期间让有效接收回执出现。"""
                hidden.rename(accepted)

            try:
                with patch("signaltrail.slide_video.time", SimpleNamespace(
                    perf_counter=perf_counter, sleep=publish,
                )):
                    receipt = prefetch_speech(
                        plan_path, data_dir / "follow.mp4", None, data_dir, follow_seconds=30
                    )
            finally:
                if hidden.exists():
                    hidden.rename(accepted)
            return {"video_prefetch_follows_newly_accepted_batch": (
                not receipt["pending_batches"] and not receipt["timed_out"]
                and receipt["tts_pages_generated"] == len(invoked) == PAGE_COUNT
                and setup.call_count == 1
            )}
        first = prefetch_speech(plan_path, output, None, data_dir)
        repeat = prefetch_speech(plan_path, output, None, data_dir)

    return {
        "video_prefetch_reads_only_accepted_batches": (
            0 < first["ready_pages"] < PAGE_COUNT and bool(first["pending_batches"])
            and len(invoked) == first["tts_pages_generated"] == first["ready_pages"]
            and not output.exists()
        ),
        "video_prefetch_reuses_verified_audio_cache": (
            repeat["tts_pages_generated"] == 0
            and repeat["tts_page_cache_hits"] == first["ready_pages"]
        ),
    }


def _check_finalize_diagnostic(data_dir: Path) -> tuple[dict, dict]:
    """通过正式定稿命令复现字段校验失败，并核对修正草稿后可恢复发布。"""
    draft, index, item_plan = _frozen_report_inputs()
    date = draft["date"]
    position = draft["analyses"][1]["stakeholder_positions"][1]
    original = position["stakeholder"]
    position["stakeholder"] = "OpenAI"
    draft_path = write_json(data_dir / "draft.json", draft)
    index_path = write_json(data_dir / "index.json", index)
    context_path = write_json(data_dir / "context.json", {
        "schema_version": draft["schema_version"],
        "brief_plan": [
            {"source_id": source, "default_item_ids": items}
            for source, items in item_plan.items()
        ],
    })
    run_path = write_json(data_dir / "runs" / date / "daily.json", {
        "date": date, "edition": "daily", "status": "awaiting_authoring",
        "data_root": str(data_dir),
        "artifacts": {"index_path": str(index_path), "context_path": str(context_path)},
    })
    command = ["finalize-edition", "--run", str(run_path), "--report",
               str(draft_path), "--defer-tail"]
    started = perf_counter()
    diagnostic = ""
    try:
        run_command(data_dir, command)
    except (RuntimeError, json.JSONDecodeError) as error:
        diagnostic = str(error)
    failed_at = perf_counter()
    rejected = read_json(run_path)
    field = "analyses[1].stakeholder_positions[1].stakeholder"
    reported_error = rejected.get("error", "")
    visible_field_error = (
        field in reported_error and reported_error in diagnostic
        and "finalize-edition exited with code" in diagnostic
        and rejected["status"] == "awaiting_authoring"
        and not (data_dir / "reports").exists()
    )

    original_analysis_order = deepcopy(draft)
    original_analysis_order["analyses"].append(original_analysis_order["analyses"].pop(0))
    ticket = {"kind": "analysis", "errors": [diagnostic]}
    local = stakeholder_repair(ticket, original_analysis_order)
    assert local is not None
    prompt, paths = local
    patched = apply_stakeholder_repair(original_analysis_order, paths, {"values": [original]})
    expected = deepcopy(draft)
    expected["analyses"][1]["stakeholder_positions"][1]["stakeholder"] = original
    expected["analyses"].append(expected["analyses"].pop(0))
    preserves_other_fields = patched == expected and "OpenAI" in prompt
    full_fallback = stakeholder_repair(
        {"kind": "analysis", "errors": [diagnostic + "; unrelated structural error"]}, draft,
    ) is None
    patched["analyses"].insert(0, patched["analyses"].pop())
    write_json(draft_path, patched)
    result = run_command(data_dir, command)
    saved_path = Path(result["artifacts"]["json_path"])
    bound_index = Path(result["artifacts"]["index_path"])
    resumed_delivery = _check_delivered_slide_plan(run_path, saved_path, bound_index, data_dir)
    return ({
        "finalize_reports_child_field_validation_error": visible_field_error,
        "field_repair_preserves_other_values_and_supports_unsorted_draft": preserves_other_fields,
        "mixed_report_validation_errors_use_full_repair": full_fallback,
        "finalize_succeeds_after_correcting_field": (
            result["status"] == "completed" and saved_path.name == "daily-r1.json"
            and read_json(saved_path)["analyses"][1]["stakeholder_positions"][1]["stakeholder"]
            == original
        ),
        "finalize_adopts_delivered_slide_plan_without_regeneration": resumed_delivery,
    }, {
        "finalize_rejection_seconds": failed_at - started,
        "finalize_recovery_seconds": perf_counter() - failed_at,
    })


def _check_delivered_slide_plan(
    run_path: Path, report_path: Path, index_path: Path, data_dir: Path,
) -> bool:
    """用存档的图文投影验证正式定稿能接续已经交付的计划。"""
    review = {"selected_event_ids": ["fixed-story"], "exclude_event_ids": [], "merge_groups": []}
    review_path = write_json(data_dir / "review-delivered.json", review)
    payload = {
        "selection_policy": "edition-day-reviewed-v1", "candidate_review": review,
        "budget": {"max_news": 50}, "news": [{"event_id": "fixed-story"}],
        "batches": [], "reused_slides": [{"event_id": "fixed-story"}],
    }
    plan_path = save_artifact(data_dir, "slides-delivered", "slides-plan", payload,
                              {"report": report_path, "index": index_path}, "冻结图文计划")
    deck = save_artifact(data_dir, "slides-delivered", "slides-deck", {"slides": payload["news"]},
                         {"plan": plan_path}, "已交付图文")
    report_sidecar = report_path.with_name(report_path.stem + "-slides.html")
    content = b"<main>Fixed delivered slide projection</main>"
    report_sidecar.write_bytes(content)
    deck.with_suffix(".html").write_bytes(content)
    before = report_path.read_bytes()
    result = run_command(data_dir, [
        "finalize-edition", "--run", str(run_path), "--report", str(report_path), "--defer-tail",
        "--slides-review", str(review_path), "--slides-reuse-plan", str(plan_path),
    ])
    slides = result["artifacts"]["slides"]
    retry = run_command(data_dir, [
        "finalize-edition", "--run", str(run_path), "--report", str(report_path), "--defer-tail",
    ])
    return (
        slides["plan_path"] == str(plan_path.resolve()) and slides["status"] == "rendered"
        and retry["artifacts"]["slides"] == slides
        and report_path.read_bytes() == before and report_sidecar.read_bytes() == content
        and list(plan_path.parent.glob("slides-plan-r*.json")) == [plan_path]
    )


def evaluate(work_dir: Path) -> dict:
    """用固定外部草稿驱动生产协调器，检查在途保护、修复回派和最终成品。"""
    data_dir = work_dir.resolve()
    index, drafts, evidence = _make_fixture(data_dir)
    index_path = write_json(data_dir / "indexes" / "fixture-r1.json", index)
    selected = list(reversed(drafts))
    started = perf_counter()
    prepared = prepare_slides(None, index_path, data_dir, batch_size=BATCH_SIZE,
                              review={"selected_event_ids": selected})
    prepared_at = perf_counter()
    plan_path = Path(prepared["plan_path"])
    batch_count = len(prepared["packet_paths"])
    active: list[dict[str, tuple[Path, dict]]] = []
    dispatches: Counter[str] = Counter()
    accepted = []
    full_inputs = True
    slots_respected = True
    partial_protected = True
    valid_repair = False
    forced_handoffs = 0
    peak_authors = 0
    invalid_batch = None
    partial_batch = None
    turns = 0
    paired_assignments = author_assignments = 0
    bundle_boundaries = True
    prefetch_checks = {}
    # 票据沿用历史跨阶段标记，以覆盖从简报进入图文和接收超过十批的调度。
    while not accepted or accepted[-1] < batch_count:
        if turns > batch_count + 4:
            raise RuntimeError("Slides orchestration did not finish accepting the fixed drafts")
        in_flight = tuple(batch_id for assignment in active for batch_id in assignment)
        plan = advance_dispatch(plan_path, data_dir, in_flight=in_flight)
        accepted.append(plan["accepted_count"])
        if not prefetch_checks and 0 < accepted[-1] < batch_count:
            prefetch_checks = _check_speech_prefetch(plan_path, data_dir)
        turns += 1
        if partial_batch is not None and partial_batch in in_flight:
            partial_task = next((task for task in plan["tasks"]
                                 if str(task["batch_id"]) == partial_batch), None)
            partial_protected &= partial_task is not None and not partial_task["errors"]
        plan = coordinator_dispatch(
            {**plan, "stage": "slides"}, data_dir / "run.json", data_dir,
            started="briefs:0", in_flight=in_flight, bundle_size=2,
        )
        forced_handoffs += plan.get("stage") == "handoff" or "handoff" in plan
        free_slots = AUTHOR_LIMIT - len(active)
        receipt = compact_dispatch(plan, limit=free_slots, in_flight=in_flight,
                                   data_dir=data_dir, bundle_size=2)
        assignments = receipt["author_assignments"]
        author_assignments += len(assignments)
        slots_respected &= len(assignments) <= free_slots
        for assignment in assignments:
            tickets = [read_json(Path(path)) for path in assignment["task_files"]]
            paired_assignments += len(tickets) == 2
            bundle_boundaries &= (
                assignment["in_flight"] == [str(ticket["batch_id"]) for ticket in tickets]
                and 1 <= len(tickets) <= 2
                and (len(tickets) == 1 or (
                    sum(ticket["input_tokens"] for ticket in tickets) <= 24_000
                    and tickets[0]["input_tokens"] <= min(10_000, tickets[1]["input_tokens"])
                    and all(ticket["action"] == "write" for ticket in tickets)
                ))
            )
            work = {}
            for ticket in tickets:
                batch_id = str(ticket["batch_id"])
                slots_respected &= all(batch_id not in other for other in active)
                dispatches[batch_id] += 1
                payload, input_matches = _author_payload(ticket, drafts, data_dir)
                full_inputs &= input_matches
                draft_path = Path(ticket["draft_result_path"])
                work[batch_id] = (draft_path, payload)
                if turns == 1 and partial_batch is None:
                    partial_batch = batch_id
                    draft_path.write_bytes(b'{"slides": [')
                if ticket["action"] == "repair":
                    valid_repair |= batch_id == invalid_batch and bool(ticket["errors"])
            active.append(work)
        peak_authors = max(peak_authors, len(active))

        for assignment in active.copy():
            if turns == 1 and partial_batch in assignment:
                continue
            for batch_id, (draft_path, payload) in assignment.items():
                # 完整 JSON 中一页遗漏必填稿件，触发正式校验和下一轮修复。
                if invalid_batch is None:
                    invalid_batch = batch_id
                    payload = {**payload, "slides": [
                        {key: value for key, value in payload["slides"][0].items()
                         if key != "narration"}, *payload["slides"][1:],
                    ]}
                write_json(draft_path, payload)
            active.remove(assignment)

    submitted_at = perf_counter()
    rendered = render_slides(plan_path, data_dir, refresh_images=False)
    rendered_at = perf_counter()
    html_path = Path(rendered["html_path"])
    deck = load_artifact(Path(rendered["json_path"]), data_dir, kind="slides-deck")["payload"]
    pages = _rendered_pages(deck, html_path, selected, drafts, evidence)
    finalize_checks, finalize_metrics = _check_finalize_diagnostic(data_dir / "finalize-diagnostic")

    return {
        "workload": {
            "target_pages": PAGE_COUNT, "pages_per_batch": BATCH_SIZE,
            "expected_batches": (PAGE_COUNT + BATCH_SIZE - 1) // BATCH_SIZE,
            "author_slots": AUTHOR_LIMIT, "drafts": "fixed", "images": "local",
            "finalize_failure": "invalid report stakeholder language",
        },
        "checks": {
            **finalize_checks,
            **prefetch_checks,
            **_check_speech_prefetch(plan_path, data_dir, follow=True),
            "video_prefetch_partial_plan_checked": bool(prefetch_checks),
            **_check_video_lock(data_dir / "export-lock"),
            "full_author_input_parts_restore_packet_bytes": full_inputs,
            "bundled_assignments_keep_independent_inputs_and_reduce_author_starts": (
                bundle_boundaries and paired_assignments > 0
                and author_assignments < sum(dispatches.values())
            ),
            "fills_three_slots_and_excludes_in_flight": (
                slots_respected and peak_authors == AUTHOR_LIMIT
            ),
            "in_flight_partial_draft_not_read_or_dispatched": (
                partial_protected and partial_batch is not None and dispatches[partial_batch] == 1
            ),
            "single_invalid_draft_repaired_and_accepted": (
                valid_repair and invalid_batch is not None and dispatches[invalid_batch] == 2
                and sum(dispatches.values()) == batch_count + 1
            ),
            "all_batches_accepted_without_forced_handoff": (
                batch_count == (PAGE_COUNT + BATCH_SIZE - 1) // BATCH_SIZE
                and len(dispatches) == accepted[-1] == batch_count and forced_handoffs == 0
            ),
            "all_pages_preserve_order_text_sources_and_images": (
                pages["ordered"] and pages["text_pages"] == pages["source_pages"] == PAGE_COUNT
            ),
        },
        "metrics": {
            **finalize_metrics,
            "dispatch_rounds": turns, "dispatched_tickets": sum(dispatches.values()),
            "author_assignments": author_assignments, "paired_assignments": paired_assignments,
            "forced_handoffs": forced_handoffs, "max_active_authors": peak_authors,
            "accepted_counts_by_round": accepted,
            "prepare_seconds": prepared_at - started,
            "dispatch_and_submit_seconds": submitted_at - prepared_at,
            "render_seconds": rendered_at - submitted_at,
            "elapsed_seconds": rendered_at - started,
            "pages_per_second": len(deck["slides"]) / (rendered_at - started),
        },
        "artifacts": {
            "plan": str(plan_path), "deck": rendered["json_path"], "html": str(html_path),
        },
        "limitations": ["计量固定草稿的图文调度与交付，作者完成事件由评估负载驱动。"],
    }
