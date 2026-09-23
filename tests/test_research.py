import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from daily_intelligence.narrative import script_segments, submit_script
from daily_intelligence.narrative_store import load_artifact, parent_path
from daily_intelligence.narrative_verification import prepare_review, submit_review
from daily_intelligence.research import (
    evaluate_research,
    prepare_research_snapshot,
    search_research,
    select_research_evidence,
    submit_research_memo,
    update_research_questions,
)
from daily_intelligence.research_delivery import bind_research_to_report, render_composite_view
from daily_intelligence.story_stream import build_story_stream, render_story
from daily_intelligence.utils import write_json
from tests.test_narrative import explainer_case as explainer_case


def question(key="cost", text="算力账单成本", domain="ai_technology"):
    return {
        "key": key,
        "domain": domain,
        "question": text,
        "weight": 1,
        "state": "not_evidenced",
        "evidence_span_ids": [],
        "gap": "缺同口径材料",
    }


@pytest.fixture
def research_case(tmp_path):
    items = []
    for n, body in enumerate(
        [
            "算力账单成本下降需要同业务量、同质量，不能把单位成本当成总成本。",
            "同一声明的转载：算力单价下降；准入规则没有给出更多材料。",
            "合同说明了成本传导与利润分配的条件。",
        ]
    ):
        blocks = write_json(
            tmp_path / f"blocks-{n}.json",
            {"blocks": [{"block_id": "b1", "text": body, "type": "paragraph"}]},
        )
        items.append(
            {
                "item_id": f"i{n}",
                "source_id": f"s{n}",
                "source_name": f"来源{n}",
                "title": f"研究材料 {n}",
                "url": f"https://example.org/{n}",
                "published_at": None,
                "discovered_at": "2026-09-20T08:00:00+08:00",
                "content_status": "full_text",
                "metadata": {
                    "content_blocks_path": str(blocks),
                    "language": "zh-CN",
                    "original_record_id": "statement-A" if n < 2 else "contract-B",
                },
            }
        )
    index = write_json(
        tmp_path / "index.json",
        {
            "date": "2026-09-20",
            "edition": "morning",
            "items": items,
            "sources": [{"source_id": "blocked", "status": "rate_limited"}],
        },
    )
    questions = [
        question(),
        question("rules", "准入规则", "geopolitics"),
        question("profit", "合同利润分配", "markets"),
    ]
    snapshot = prepare_research_snapshot(
        index, [i["item_id"] for i in items], "2026-09-20T09:00:00+08:00", questions, tmp_path
    )
    return {
        "root": tmp_path,
        "index": index,
        "items": items,
        "questions": questions,
        "snapshot": snapshot,
    }


def memo_draft(c):
    snapshot = load_artifact(c["snapshot"], c["root"])["payload"]
    span = snapshot["evidence"][0]["spans"][-1]["span_id"]
    claim = {
        "key": "cost",
        "text": "算力单价变化不等于同幅度账单变化。",
        "kind": "inference",
        "evidence_span_ids": [span],
        "analysis_keys": ["mechanism"],
        "question_keys": ["cost"],
        "required": True,
        "temporal_scope": "conditional",
        "event_time": None,
        "event_time_precision": "unknown",
        "attribution": None,
        "qualifiers": ["同业务量、同质量"],
    }
    return {
        "memo": "先比较同业务量、同质量的账单，再判断成本传导。",
        "analyses": [
            {
                "key": "mechanism",
                "domain": "ai_technology",
                "text": claim["text"],
                "evidence_span_ids": [span],
                "conditions": ["同业务量、同质量"],
                "counterargument": "用量可能变化",
                "watch": "下一期同口径账单",
            }
        ],
        "claims": [claim],
    }


def research_script(c):
    paths = submit_research_memo(c["snapshot"], memo_draft(c), c["root"])
    ledger = Path(paths["ledger_path"])
    claim = load_artifact(ledger, c["root"])["payload"]["claims"][0]["claim_id"]
    seg = {"text": "同业务量、同质量时，算力单价变化不等于同幅度账单变化。", "claim_ids": [claim]}
    label = {"text": "比较条件", "claim_ids": []}
    table = {
        "headers": [deepcopy(label), {"text": "结论", "claim_ids": []}],
        "rows": [[deepcopy(seg), deepcopy(seg)]],
        "publisher_caption": None,
        "editorial_caption": deepcopy(seg),
    }
    draft = {
        "language": "zh-CN",
        "title": deepcopy(seg),
        "introduction": deepcopy(seg),
        "closing": deepcopy(seg),
        "chapters": [
            {
                "title": deepcopy(seg),
                "question": deepcopy(seg),
                "beats": [
                    {
                        **deepcopy(seg),
                        "role": "mechanism",
                        "visual": [],
                        "visual_relation": "parallel",
                        "table": table,
                    }
                ],
            }
        ],
    }
    script = submit_script(ledger, draft, c["root"], author_context="research-author")
    return script, draft, paths


def review_script(script, root, *, table_verdict="supported"):
    packet_path = prepare_review(script, root)
    packet = load_artifact(packet_path, root)["payload"]
    claims = {c["claim_id"]: c for c in packet["claims"]}
    review = {
        "segment_reviews": [],
        "missing_required_claims": [],
        "findings": [],
        "quality": {"clarity": 4, "narrative": 4, "explanation": 4, "note": "Test fixture"},
    }
    for segment in packet["segments"]:
        assertions = []
        if segment["claim_ids"]:
            assertions.append(
                {
                    "quote": segment["text"],
                    "claim_ids": segment["claim_ids"],
                    "evidence_span_ids": sorted(
                        {s for c in segment["claim_ids"] for s in claims[c]["evidence_span_ids"]}
                    ),
                    "verdict": table_verdict if "table" in segment["segment_id"] else "supported",
                    "note": "Fixture assertion",
                }
            )
        review["segment_reviews"].append(
            {
                "segment_id": segment["segment_id"],
                "assertions": assertions,
                "no_assertion_reason": None if assertions else "Column label",
            }
        )
    return submit_review(packet_path, review, root, reviewer_context="isolated-reviewer")


def test_snapshot_starts_without_report_and_survives_upstream_updates(research_case):
    c = research_case
    before = c["snapshot"].read_bytes()
    write_json(c["index"], {"status": "now extracting"})
    write_json(c["root"] / "blocks-0.json", {"blocks": []})
    snapshot = load_artifact(c["snapshot"], c["root"])["payload"]
    assert "同业务量" in snapshot["evidence"][0]["spans"][-1]["text"]
    assert snapshot["source_health"][0]["status"] == "rate_limited"
    assert c["snapshot"].read_bytes() == before
    assert not (c["root"] / "runs").exists()


def test_approved_discovery_feed_bridges_without_expanding_daily_index(research_case):
    c = research_case
    before = c["index"].read_bytes()
    feed = write_json(
        c["root"] / "feed.json",
        {
            "blocks": [
                {"block_id": "feed-1", "text": "机构材料的完整限定来自 Feed，但未验证正文完整度。"}
            ]
        },
    )
    item = {
        "item_id": "discovered",
        "source_id": "institution",
        "source_name": "机构",
        "url": "https://example.org/feed-item",
        "title": "发现材料",
        "metadata": {"feed_content_path": str(feed)},
    }
    monitor = write_json(
        c["root"] / "monitor.json",
        {"items": [item], "sources": [{"source_id": "institution", "status": "partial"}]},
    )
    path = prepare_research_snapshot(
        c["index"],
        ["discovered"],
        "2026-09-20T10:00:00+08:00",
        c["questions"],
        c["root"],
        discovery_path=monitor,
    )
    frozen = load_artifact(path, c["root"])["payload"]
    assert len(frozen["evidence"]) == 1
    assert frozen["evidence"][0]["spans"][-1]["field"] == "feed-1"
    assert frozen["evidence"][0]["content_status"] == "not_fetched"
    assert frozen["input_discovery"]["path"] == "monitor.json"
    assert c["index"].read_bytes() == before


def test_snapshot_fingerprint_describes_bytes_read_before_parallel_update(
    research_case, monkeypatch
):
    from daily_intelligence import research

    c = research_case
    before = c["index"].read_bytes()
    freeze = research._freeze_evidence

    def concurrent_update(*args):
        write_json(c["index"], {"items": [], "revision": "next"})
        return freeze(*args)

    monkeypatch.setattr(research, "_freeze_evidence", concurrent_update)
    path = prepare_research_snapshot(
        c["index"], ["i0"], "2026-09-20T10:00:00+08:00", c["questions"], c["root"]
    )
    frozen = load_artifact(path, c["root"])["payload"]
    assert frozen["input_index"]["sha256"] == sha256(before).hexdigest()
    assert frozen["evidence"][0]["index_item_id"] == "i0"


def test_bm25_chinese_retrieves_exact_blocks_and_preserves_unknown_time(research_case):
    c = research_case
    hits = search_research(c["snapshot"], "合同利润", c["root"])
    assert hits[0]["field"] == "b1"
    assert "利润分配" in hits[0]["text"]
    assert search_research(c["snapshot"], "xylophone", c["root"]) == []
    row = load_artifact(c["snapshot"], c["root"])["payload"]["evidence"][0]
    assert row["event_time"] is row["published_at"] is None
    assert row["time_findings"] == ["unknown_publication"]


def test_greedy_selection_does_not_count_republication_as_new_material(research_case):
    c = research_case
    result = select_research_evidence(c["snapshot"], c["root"])
    ids = [r["item_id"] for r in result["candidates"]]
    evidence = load_artifact(c["snapshot"], c["root"])["payload"]["evidence"]
    assert len(ids) == 2
    assert len({e["origin_id"] for e in evidence if e["item_id"] in ids}) == 2
    assert evaluate_research(c["snapshot"], c["root"])["independent_confirmations"] is None


def test_question_updates_preserve_omissions_and_never_modify_dispatch(research_case):
    c = research_case
    paths = submit_research_memo(c["snapshot"], memo_draft(c), c["root"])
    old = Path(paths["packet_path"]).read_bytes()
    q = deepcopy(c["questions"][0])
    q.update(
        state="answered",
        evidence_span_ids=memo_draft(c)["claims"][0]["evidence_span_ids"],
        gap=None,
    )
    updated = update_research_questions(c["snapshot"], [q], c["root"])
    metrics = evaluate_research(updated, c["root"])
    assert metrics["questions"] == 3
    assert metrics["declared_answered_fraction"] == pytest.approx(1 / 3)
    assert metrics["usage"]["tokens"] is None
    assert Path(paths["packet_path"]).read_bytes() == old
    assert evaluate_research(c["snapshot"], c["root"])["declared_answered_fraction"] == 0


def test_new_evidence_version_reopens_affected_questions(research_case):
    c = research_case
    q = deepcopy(c["questions"][0])
    q.update(
        state="answered",
        evidence_span_ids=memo_draft(c)["claims"][0]["evidence_span_ids"],
        gap=None,
    )
    updated = update_research_questions(c["snapshot"], [q], c["root"])
    write_json(
        c["root"] / "blocks-0.json", {"blocks": [{"block_id": "b1", "text": "更正后的数据"}]}
    )
    new = prepare_research_snapshot(
        c["index"], ["i0"], "2026-09-20T10:00:00+08:00", [], c["root"], previous_path=updated
    )
    snapshot = load_artifact(new, c["root"])["payload"]
    assert len(snapshot["evidence"]) == 3
    assert snapshot["questions"][0]["state"] == "not_evidenced"
    assert snapshot["questions"][0]["evidence_span_ids"] == []
    assert evaluate_research(updated, c["root"])["question_states"]["answered"] == 1


@pytest.mark.parametrize("change", ["span", "analysis", "question", "scope"])
def test_research_cannot_borrow_unauthorized_original_analysis(research_case, change):
    c = research_case
    draft = memo_draft(c)
    if change == "span":
        draft["claims"][0]["evidence_span_ids"] = ["invented:0"]
    elif change == "analysis":
        draft["claims"][0]["analysis_keys"] = ["ANALYSIS-MARKETS"]
    elif change == "question":
        draft["claims"][0]["question_keys"] = ["missing"]
    else:
        snapshot = load_artifact(c["snapshot"], c["root"])["payload"]
        draft["claims"][0]["evidence_span_ids"] = [snapshot["evidence"][0]["spans"][0]["span_id"]]
    with pytest.raises(ValueError):
        submit_research_memo(c["snapshot"], draft, c["root"])


def test_tables_receive_full_semantic_review_and_single_language_admission(research_case):
    c = research_case
    script, draft, _ = research_script(c)
    record = load_artifact(script, c["root"])["payload"]["script"]
    assert len([s for s in script_segments(record) if "table" in s["segment_id"]]) == 5
    failed = review_script(script, c["root"], table_verdict="insufficient")
    story = build_story_stream([script], c["root"], review_path=failed)
    assert load_artifact(story, c["root"])["payload"]["status"] == "draft"
    passed = review_script(script, c["root"])
    story = build_story_stream([script], c["root"], review_path=passed)
    assert load_artifact(story, c["root"])["payload"]["status"] == "verified_snapshot"
    rendered = render_story(story, c["root"])
    soup = BeautifulSoup(Path(rendered["html_path"]).read_text(encoding="utf-8"), "html.parser")
    assert soup.select_one("table td").get_text() == draft["chapters"][0]["beats"][0]["text"]
    assert not soup.select("img")
    markdown = (
        story.parent / f"story-r{load_artifact(story, c['root'])['revision']}" / "artifact.md"
    ).read_text(encoding="utf-8")
    assert "| 比较条件 | 结论 |" in markdown


def test_single_language_receipt_cannot_admit_another_revision(research_case):
    c = research_case
    script, draft, paths = research_script(c)
    review = review_script(script, c["root"])
    draft["title"]["text"] = "新标题"
    changed = submit_script(Path(paths["ledger_path"]), draft, c["root"], author_context="author")
    with pytest.raises(ValueError, match="another script"):
        build_story_stream([changed], c["root"], review_path=review)


def test_late_binding_preserves_final_report_and_places_research_below_analysis(explainer_case):
    c = explainer_case
    index = json.loads(c["index"].read_text(encoding="utf-8"))
    report = json.loads(c["report"].read_text(encoding="utf-8"))
    c["snapshot"] = prepare_research_snapshot(
        c["index"], [index["items"][0]["item_id"]], report["generated_at"], [question()], c["root"]
    )
    script, _, _ = research_script(c)
    review = review_script(script, c["root"])
    story = build_story_stream([script], c["root"], review_path=review)
    before = {name: c[name].read_bytes() for name in ("report", "index", "run")}
    binding = bind_research_to_report(story, c["run"], [], c["root"])
    result = render_composite_view(binding, c["root"])
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert html.index('id="analysis-markets"') < html.index('id="illustrated-research"')
    assert html.index('id="illustrated-research"') < html.index('id="evaluation"')
    assert render_composite_view(binding, c["root"]) == result
    assert all(c[name].read_bytes() == value for name, value in before.items())
    assert parent_path(load_artifact(binding, c["root"]), "report", c["root"]) == c["report"]
    with pytest.raises(ValueError, match="Current admission blocked"):
        render_composite_view(binding, c["root"], mode="current")


@pytest.mark.parametrize("defect", ["empty_answer", "unknown_span", "duplicate_key"])
def test_invalid_question_findings_do_not_publish(research_case, defect):
    c = research_case
    q = deepcopy(c["questions"][0])
    findings = [q]
    if defect == "empty_answer":
        q["state"] = "answered"
    elif defect == "unknown_span":
        q["evidence_span_ids"] = ["unknown"]
    else:
        findings.append(deepcopy(q))
    with pytest.raises(ValueError):
        update_research_questions(c["snapshot"], findings, c["root"])
