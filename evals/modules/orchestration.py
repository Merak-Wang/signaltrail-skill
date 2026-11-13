"""用固定的 50 页图文稿评估真实派发、批量接收和渲染链路。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from scripts.run_signaltrail import advance_dispatch, compact_dispatch, coordinator_dispatch
from signaltrail.narrative_store import load_artifact
from signaltrail.news_slides import prepare_slides, render_slides
from signaltrail.utils import write_json

from .slides import PAGE_COUNT, _make_fixture, _rendered_pages

AUTHOR_LIMIT = 3
BATCH_SIZE = 4


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
    active: dict[str, tuple[Path, dict]] = {}
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
    # 票据沿用历史跨阶段标记，以覆盖从简报进入图文和接收超过十批的调度。
    while not accepted or accepted[-1] < batch_count:
        if turns > batch_count + 4:
            raise RuntimeError("Slides orchestration did not finish accepting the fixed drafts")
        in_flight = tuple(active)
        plan = advance_dispatch(plan_path, data_dir, in_flight=in_flight)
        accepted.append(plan["accepted_count"])
        turns += 1
        if partial_batch is not None and partial_batch in active:
            partial_task = next((task for task in plan["tasks"]
                                 if str(task["batch_id"]) == partial_batch), None)
            partial_protected &= partial_task is not None and not partial_task["errors"]
        plan = coordinator_dispatch({**plan, "stage": "slides"}, data_dir / "run.json", data_dir,
                                    started="briefs:0", in_flight=in_flight)
        forced_handoffs += plan.get("stage") == "handoff" or "handoff" in plan
        free_slots = AUTHOR_LIMIT - len(active)
        tickets = compact_dispatch(plan, limit=free_slots, in_flight=in_flight,
                                   data_dir=data_dir)["tasks"]
        slots_respected &= len(tickets) <= free_slots
        for ticket in tickets:
            batch_id = str(ticket["batch_id"])
            slots_respected &= batch_id not in active
            dispatches[batch_id] += 1
            payload, input_matches = _author_payload(ticket, drafts, data_dir)
            full_inputs &= input_matches
            draft_path = Path(ticket["draft_result_path"])
            active[batch_id] = (draft_path, payload)
            if turns == 1 and partial_batch is None:
                partial_batch = batch_id
                draft_path.write_bytes(b'{"slides": [')
            if ticket["action"] == "repair":
                valid_repair |= batch_id == invalid_batch and ticket["error_count"] > 0
        peak_authors = max(peak_authors, len(active))

        for batch_id, (draft_path, payload) in list(active.items()):
            if turns == 1 and batch_id == partial_batch:
                continue
            # 完整 JSON 中一页遗漏必填稿件，触发正式校验和下一轮修复。
            if invalid_batch is None:
                invalid_batch = batch_id
                payload = {**payload, "slides": [
                    {key: value for key, value in payload["slides"][0].items()
                     if key != "narration"}, *payload["slides"][1:],
                ]}
            write_json(draft_path, payload)
            del active[batch_id]

    submitted_at = perf_counter()
    rendered = render_slides(plan_path, data_dir, refresh_images=False)
    rendered_at = perf_counter()
    html_path = Path(rendered["html_path"])
    deck = load_artifact(Path(rendered["json_path"]), data_dir, kind="slides-deck")["payload"]
    pages = _rendered_pages(deck, html_path, selected, drafts, evidence)

    return {
        "workload": {
            "target_pages": PAGE_COUNT, "pages_per_batch": BATCH_SIZE,
            "expected_batches": (PAGE_COUNT + BATCH_SIZE - 1) // BATCH_SIZE,
            "author_slots": AUTHOR_LIMIT, "drafts": "fixed", "images": "local",
        },
        "checks": {
            "full_author_input_parts_restore_packet_bytes": full_inputs,
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
            "dispatch_rounds": turns, "dispatched_tickets": sum(dispatches.values()),
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
