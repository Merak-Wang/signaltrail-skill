from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from daily_intelligence.authoring import (
    _analysis_candidates,
    _analysis_output_schema,
    _brief_output_schema,
    _compact_json_bytes,
    _merge_briefs,
    _normalize_narrative,
    _project_analysis_state,
    validate_analysis_evidence,
    validate_authoring_batch,
)
from daily_intelligence.config import load_config
from daily_intelligence.context import build_context
from daily_intelligence.utils import read_json, write_json
from daily_intelligence.workflow import (
    RunStatus,
    accept_authoring_batch,
    accept_authoring_metrics,
    assemble_authoring,
    begin_authoring,
    get_authoring_status,
    prepare_authoring_analysis,
)


def _authoring_run(tmp_path: Path, item_count: int = 2) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    date = "2026-07-25"
    items = [
        {
            "item_id": f"bbc-{position}",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": f"Public headline {position}",
            "description": f"Public description {position}",
            "url": f"https://www.bbc.com/news/articles/{position}",
            "published_at": f"{date}T01:0{position}:00+08:00",
            "discovered_at": f"{date}T01:1{position}:00+08:00",
            "module": "information",
            "category": "international",
            "content_status": "not_fetched",
            "metadata": {"source_rank": position + 1},
        }
        for position in range(item_count)
    ]
    index_path = write_json(
        data_dir / "indexes" / date / "morning-r1.json",
        {
            "date": date,
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "sources": [
                {
                    "source_id": "bbc_world",
                    "source_name": "BBC",
                    "source_url": "https://www.bbc.com/news",
                    "status": "success",
                }
            ],
            "items": items,
            "source_policies": {
                "bbc_world": {"report_target": item_count, "report_max": 15}
            },
        },
    )
    context_path = build_context(
        index_path,
        load_config(),
        data_dir,
        "morning",
    )
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_path = write_json(
        data_dir / "runs" / date / "morning.json",
        {
            "schema_version": "1.0",
            "run_id": f"run-{date}-morning",
            "data_root": str(data_dir.resolve()),
            "date": date,
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "status": RunStatus.AWAITING_AUTHORING,
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "deadline_at": (now + timedelta(minutes=10)).isoformat(timespec="seconds"),
            "artifacts": {
                "index_path": str(index_path),
                "context_path": str(context_path),
            },
            "pending_sources": [],
        },
    )
    return data_dir, run_path


def _valid_batch_payload(packet: dict) -> dict:
    return {
        "briefs": [
            {
                "item_id": item_id,
                "title_zh": f"公开新闻标题 {position}",
                "tldr": f"这是第 {position} 条公开新闻的中文事实摘要。",
                "importance": 80 - position,
                "status": "NEW",
            }
            for position, item_id in enumerate(packet["author_item_ids"], start=1)
            for candidate in packet["candidates"]
            if candidate["item_id"] == item_id
        ]
    }


def _valid_analysis_payload(packet: dict) -> dict:
    selected = packet["candidate_events"][:6]
    evidence_item_ids = [str(candidate["item_id"]) for candidate in selected]
    narrative = "\n\n".join(
        [
            "第一段说明当前公开事实共同指向的核心变化，并限定证据只来自本次已选择事件。",
            "第二段解释这些事实如何通过政策、技术与资金约束形成可以继续观察的传导机制。",
            "第三段讨论不同主体的利益分歧、主要反作用以及现有证据无法排除的替代解释。",
            "第四段给出后续可证伪的观察信号，说明出现哪些新事实时需要及时修正当前判断。",
        ]
    )
    analyses = []
    for domain in ("geopolitics", "ai_technology", "markets"):
        analyses.append(
            {
                "domain": domain,
                "claim": "公开事实正在形成一条需要持续验证的跨领域约束链条。",
                "narrative": narrative,
                "historical_context": (
                    "历史上类似变化往往先改变制度与资源约束，"
                    "再传导至技术选择和市场定价。"
                ),
                "dialectical_analysis": (
                    "推动因素来自规则与投入变化，"
                    "制约因素则是执行时滞、利益冲突和证据不完整。"
                ),
                "facts": ["本次精选事件提供了可以直接追溯的公开事实。"],
                "reasoning": "若约束持续存在，相关主体会调整行为并产生可观察的后续结果。",
                "causal_chain": [
                    "公开事实改变相关主体面临的约束。",
                    "约束变化进一步影响技术路径与市场预期。",
                ],
                "stakeholder_positions": [
                    {
                        "stakeholder": "相关决策主体",
                        "position": "倾向于在控制风险的同时保留调整空间。",
                        "interests": "维护制度稳定、资源效率与长期选择权。",
                    }
                ],
                "counter_evidence": ["现有公开材料尚不能证明传导已经完成。"],
                "scenarios": ["若后续信号持续增强，当前判断将得到进一步支持。"],
                "assumptions": ["公开材料能够代表当前约束的主要方向。"],
                "implications": ["后续研究应提高对跨领域传导信号的优先级。"],
                "actions": ["持续核验新的公开事实并记录判断变化。"],
                "watch_signals": ["观察规则、投入和主体行为是否同步变化。"],
                "invalidation_signals": ["若关键约束撤销且主体行为未变化，应下调判断。"],
                "time_horizon": "未来数周",
                "confidence": 0.7,
                "confidence_rationale": "当前证据可追溯但样本有限，因此保持中等置信度。",
                "evidence_gaps": ["仍缺少更多一手数据和独立交叉证据。"],
                "change_from_prior": "这是在当前报告窗口首次建立的可检验判断基线。",
                "decision_relevance": "该判断会改变后续核验顺序与研究资源配置。",
                "evidence_item_ids": evidence_item_ids,
                "state_change": "new",
            }
        )
    return {
        "title": "每日情报早报 — 2026年7月25日",
        "executive_summary": ["本版重点来自确定性合并后的新闻与研判。"],
        "featured_events": [
            {
                "section_id": candidate["section_id"],
                "title": candidate.get("title_zh") or candidate.get("title"),
                "tldr": candidate["tldr"],
                "why_it_matters": "该事件用于验证模型语义与确定性结构之间的职责边界。",
                "importance": candidate["importance"],
                "importance_reason": "该事件具有明确的跨领域观察价值。",
                "confidence": 0.7,
                "status": candidate["status"],
                "source_item_ids": [candidate["item_id"]],
                "evidence_notes": [],
                "tags": [],
            }
            for candidate in selected
        ],
        "analyses": analyses,
        "cross_perspective_synthesis": {
            "overall_judgment": "三个视角共同表明，约束变化可能沿制度、技术和市场路径逐步传导。",
            "consensus": ["当前判断必须持续绑定可追溯的精选事件证据。"],
            "tensions": [
                {
                    "issue": "传导发生的速度和强度",
                    "perspectives": ["地缘政治视角", "技术视角", "市场视角"],
                    "source_of_difference": "各视角采用的时间跨度、前提假设和利益主体不同。",
                }
            ],
            "transmission_chain": [
                "制度约束改变资源配置方式。",
                "资源变化影响技术路径并进入市场预期。",
            ],
            "shared_watch_signals": [
                "规则是否继续变化",
                "技术投入是否调整",
                "市场定价是否确认传导",
            ],
            "revision_triggers": ["若核心公开事实被撤回或出现相反的一手证据，应修正判断。"],
            "evidence_item_ids": evidence_item_ids,
        },
    }


def test_english_authoring_batch_requires_english_translation_and_summary():
    packet = {
        "output_language": "en",
        "author_item_ids": ["cn-1"],
        "candidates": [
            {
                "item_id": "cn-1",
                "title": "一条中文新闻标题",
                "source_language": "zh-CN",
            }
        ],
    }
    payload = {
        "briefs": [
            {
                "item_id": "cn-1",
                "title": "一条中文新闻标题",
                "title_en": "A Chinese-language public news headline",
                "tldr": "This is a substantive English summary of the observed facts.",
                "importance": 70,
                "status": "NEW",
            }
        ]
    }

    assert validate_authoring_batch(packet, payload) == []

    payload["briefs"][0]["tldr"] = "这是一条中文摘要。"
    errors = validate_authoring_batch(packet, payload)
    assert any("substantive English sentence" in error for error in errors)


@pytest.mark.parametrize(
    "tldr",
    [
        "原文未提供摘要，因此当前只能记录该新闻标题。",
        "packet 未提供摘要，暂时无法进一步概括相关事实。",
        "数据包未提供项目说明或简介，当前仅记录项目名称。",
        "The packet does not provide a summary or article body for this item.",
    ],
)
def test_authoring_batch_rejects_operational_placeholder_tldr(tldr: str):
    packet = {
        "output_language": "zh-CN",
        "author_item_ids": ["item-1"],
        "candidates": [
            {
                "item_id": "item-1",
                "title": "一条公开新闻标题",
                "source_language": "zh-CN",
            }
        ],
    }
    payload = {
        "briefs": [
            {
                "item_id": "item-1",
                "title": "一条公开新闻标题",
                "tldr": tldr,
                "importance": 70,
                "status": "NEW",
            }
        ]
    }

    errors = validate_authoring_batch(packet, payload)

    assert any("boilerplate" in error for error in errors)


def test_brief_output_schema_reports_safe_type_and_enum_errors():
    sentinel = "MODEL_VALUE_MUST_NOT_BE_ECHOED"
    packet = {
        "output_language": "zh-CN",
        "author_item_ids": ["item-1"],
        "candidates": [
            {
                "item_id": "item-1",
                "title": "一条公开新闻标题",
                "source_language": "zh-CN",
            }
        ],
        "output_schema": _brief_output_schema("zh-CN"),
    }
    payload = {
        "briefs": [
            {
                "item_id": "item-1",
                "tldr": "这是一条具有事实内容的中文摘要。",
                "importance": sentinel,
                "status": sentinel,
                sentinel: "untrusted generated value",
            }
        ]
    }

    errors = validate_authoring_batch(packet, payload)

    assert any("$.briefs[0].importance" in error and "integer" in error for error in errors)
    assert any("$.briefs[0].status" in error and "one of" in error for error in errors)
    assert any("unsupported field" in error for error in errors)
    assert sentinel not in "\n".join(errors)


def test_analysis_output_schema_exposes_nested_contract_without_echoing_values():
    sentinel = "MODEL_NESTED_VALUE_MUST_NOT_BE_ECHOED"
    packet = {
        "output_schema": _analysis_output_schema(),
        "candidate_events": [],
    }
    payload = {
        "title": "足够长的日报标题",
        "executive_summary": ["结构化摘要。"],
        "featured_events": [],
        "analyses": [
            {
                "domain": "geopolitics",
                "stakeholder_positions": [sentinel],
            }
        ],
        "cross_perspective_synthesis": {},
        sentinel: "untrusted generated value",
    }

    errors = validate_analysis_evidence(packet, payload)

    assert any(
        "$.analyses[0].stakeholder_positions[0]" in error
        and "object" in error
        for error in errors
    )
    assert any("$.featured_events" in error and "minItems" in error for error in errors)
    assert any("unsupported field" in error for error in errors)
    assert sentinel not in "\n".join(errors)


def test_analysis_evidence_must_come_from_selected_featured_events():
    packet = {
        "candidate_events": [
            {"item_id": "featured-item"},
            {"item_id": "brief-only-item"},
        ]
    }
    payload = {
        "featured_events": [{"source_item_ids": ["featured-item"]}],
        "analyses": [{"evidence_item_ids": ["brief-only-item"]}],
        "cross_perspective_synthesis": {
            "evidence_item_ids": ["featured-item", "unknown-item"]
        },
    }

    errors = validate_analysis_evidence(packet, payload)

    assert any("brief-only-item" in error for error in errors)
    assert any("unknown-item" in error for error in errors)


def test_analysis_evidence_enforces_available_freshness_quota():
    packet = {
        "featured_freshness_minimum": 2,
        "candidate_events": [
            {"item_id": "fresh-1", "fresh_for_report": True},
            {"item_id": "fresh-2", "fresh_for_report": True},
            {"item_id": "old-1", "fresh_for_report": False},
        ],
    }
    payload = {
        "featured_events": [
            {"source_item_ids": ["fresh-1"]},
            {"source_item_ids": ["old-1"]},
        ],
        "analyses": [],
        "cross_perspective_synthesis": {},
    }

    errors = validate_analysis_evidence(packet, payload)

    assert any("at least 2 fresh event" in error for error in errors)
    payload["featured_events"][1]["source_item_ids"] = ["fresh-2"]
    assert validate_analysis_evidence(packet, payload) == []


def test_analysis_candidates_reserve_diverse_fresh_rows_before_stale_high_scores():
    sections = [
        {
            "id": "technology.news",
            "briefs": [
                {
                    "item_id": f"fresh-{position}",
                    "importance": 35 + position,
                    "status": "NEW",
                    "tldr": f"新事件 {position}。",
                }
                for position in range(4)
            ]
            + [
                {
                    "item_id": f"old-{position}",
                    "importance": 95 - position,
                    "status": "WATCH",
                    "tldr": f"旧事件 {position}。",
                }
                for position in range(8)
            ],
        }
    ]
    context = {
        "collection_window": {"end": "2026-08-23T06:00:00+08:00"},
        "candidate_items": [
            {
                "item_id": f"fresh-{position}",
                "source_id": f"fresh-source-{position}",
                "source_name": f"Fresh {position}",
                "published_at": "2026-08-23T01:00:00+08:00",
            }
            for position in range(4)
        ]
        + [
            {
                "item_id": f"old-{position}",
                "source_id": f"old-source-{position % 2}",
                "source_name": f"Old {position}",
                "published_at": "2026-07-01T01:00:00+08:00",
            }
            for position in range(8)
        ],
    }

    selected = _analysis_candidates(sections, context, maximum=9)

    assert len(selected) == 9
    assert all(row["fresh_for_report"] for row in selected[:3])
    assert len({row["source_id"] for row in selected[:3]}) == 3
    assert all(row["freshness_age_days"] == 0 for row in selected[:3])


def test_single_paragraph_analysis_is_split_without_changing_sentence_text():
    original = "第一句说明判断。第二句给出事实。第三句解释机制。第四句讨论反作用。第五句列出观察。"

    normalized = _normalize_narrative(original)

    paragraphs = normalized.split("\n\n")
    assert len(paragraphs) == 5
    assert "".join(paragraphs) == original


def test_analysis_draft_rejects_compiler_owned_source_and_identity_fields():
    packet = {
        "candidate_events": [
            {"item_id": "authorized-item"},
            {"item_id": "different-item"},
        ]
    }
    payload = {
        "featured_events": [
            {
                "section_id": "information.international",
                "title": "授权事件",
                "tldr": "仅使用授权候选的事实摘要。",
                "why_it_matters": "用于验证证据边界。",
                "importance": 80,
                "importance_reason": "该事件具有测试价值。",
                "confidence": 0.7,
                "status": "UPD",
                "source_item_ids": ["authorized-item"],
                "source_refs": [{"item_id": "different-item"}],
                "event_id": "FORGED-HISTORICAL-EVENT",
                "evidence_notes": [],
                "tags": [],
            }
        ],
        "analyses": [
            {
                "domain": "geopolitics",
                "analysis_id": "FORGED-ANALYSIS",
                "evidence_item_ids": ["authorized-item"],
                "evidence_event_ids": ["FORGED-HISTORICAL-EVENT"],
            }
        ],
        "cross_perspective_synthesis": {
            "evidence_item_ids": ["authorized-item"]
        },
    }

    errors = validate_analysis_evidence(packet, payload)

    assert any("source_refs" in error and "event_id" in error for error in errors)
    assert any("analysis_id" in error and "evidence_event_ids" in error for error in errors)


def test_authoring_batches_are_validated_and_python_assembled(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)

    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context = read_json(Path(run["artifacts"]["context_path"]))
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    assert packet["input_projection"]["policy"] == "brief_packet_allowlist_v1"
    assert packet["usage_correlation"] == {
        "phase": "brief",
        "batch_id": batch["batch_id"],
        "agent_role": "brief-worker",
        "repair_attempt": 0,
    }
    assert all("url" not in candidate for candidate in packet["candidates"])
    assert all("image_url" not in candidate for candidate in packet["candidates"])
    assert all(
        "semantic_fingerprint" not in candidate
        for candidate in packet["candidates"]
    )
    assert set(packet["brief_plan"][0]) == {
        "source_id",
        "section_id",
        "author_item_ids",
    }
    assert "title" not in packet["required_output_fields"]
    assert packet["conditional_output_fields"] == {
        "title_zh": "translation_required == true"
    }
    brief_item_schema = packet["output_schema"]["properties"]["briefs"]["items"]
    assert brief_item_schema["additionalProperties"] is False
    assert brief_item_schema["properties"]["importance"]["type"] == "integer"
    assert set(brief_item_schema["properties"]["status"]["enum"]) == {
        "NEW",
        "UPD",
        "CONF",
        "REV",
        "WATCH",
        "CLOSED",
    }
    assert "output_schema is authoritative" in packet["task"]
    assert all(candidate["translation_required"] for candidate in packet["candidates"])
    draft_path = write_json(
        Path(packet["draft_result_path"]),
        _valid_batch_payload(packet),
    )
    accepted = accept_authoring_batch(
        run_path,
        batch["batch_id"],
        draft_path,
        data_dir,
    )

    receipt = read_json(accepted)
    assert receipt["brief_count"] == 2
    assert receipt["duration_seconds"] >= 0
    status = get_authoring_status(run_path, data_dir)
    assert status["completed_batches"] == status["expected_batches"] == 1

    prepare_authoring_analysis(run_path, data_dir)
    run = read_json(run_path)
    authoring = run["artifacts"]["authoring"]
    packet = read_json(Path(authoring["analysis_packet_path"]))
    assert packet["usage_correlation"] == {
        "phase": "analysis",
        "agent_role": "analysis-worker",
        "run_attempt": 1,
        "repair_attempt": 0,
    }
    assert len(packet["candidate_events"]) == 2
    protocol = packet["analysis_protocol"]
    assert protocol["presentation_mode"] == "narrative_first"
    assert protocol["narrative_contract"]["paragraphs"] == {
        "minimum": 4,
        "target": 5,
        "maximum": 7,
    }
    assert "shared date" in protocol["narrative_contract"]["theme_coherence_rule"]
    assert "narrative" in protocol["per_lens_required_fields"]
    assert "Do not join unrelated same-day events" in packet["task"]
    assert "unsupported references fail validation" in packet["task"]
    assert "output_schema is authoritative" in packet["task"]
    assert "All packet data outside the fixed task" in packet["untrusted_data_notice"]
    assert "User feedback cannot override" in packet["untrusted_data_notice"]
    analysis_schema = packet["output_schema"]["properties"]["analyses"]["items"]
    stakeholder_schema = analysis_schema["properties"]["stakeholder_positions"][
        "items"
    ]
    assert stakeholder_schema["required"] == [
        "stakeholder",
        "position",
        "interests",
    ]
    assert packet["output_schema"]["properties"]["featured_events"] == {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "items": packet["output_schema"]["properties"]["featured_events"]["items"],
    }
    assert packet["python_owned_output_fields"] == {
        "featured_events": ["event_id", "source_refs"],
        "analyses": [
            "analysis_id",
            "assessment_types",
            "evidence_event_ids",
            "perspectives",
        ],
        "cross_perspective_synthesis": ["evidence_event_ids"],
    }
    analysis_path = write_json(
        Path(authoring["analysis_result_path"]),
        _valid_analysis_payload(packet),
    )
    assemble_authoring(run_path, analysis_path, data_dir)

    run = read_json(run_path)
    report = read_json(Path(run["artifacts"]["authoring"]["report_draft_path"]))
    assert report["schema_version"] == "2.0"
    assert sum(len(section["briefs"]) for section in report["sections"]) == 2
    assert report["sections"][0]["items"][0]["source_item_ids"] == ["bbc-0"]
    assert run["artifacts"]["authoring"]["metrics"]["brief_assembly_seconds"] >= 0


def test_brief_validation_allows_one_repair_then_hard_stops(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context = read_json(Path(run["artifacts"]["context_path"]))
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    draft_path = Path(packet["draft_result_path"])

    first_invalid = _valid_batch_payload(packet)
    first_invalid["briefs"] = first_invalid["briefs"][:-1]
    write_json(draft_path, first_invalid)
    with pytest.raises(ValueError, match="structured rejection receipt"):
        accept_authoring_batch(run_path, batch["batch_id"], draft_path, data_dir)

    rejection_dir = Path(batch["packet_path"]).with_name(
        f"{Path(batch['packet_path']).stem}-rejections"
    )
    first_receipt = read_json(rejection_dir / "attempt-1.json")
    assert first_receipt["repair_authorized"] is True
    assert first_receipt["validation_errors"][0]["path"]
    assert first_receipt["draft_sha256"].startswith("sha256:")

    second_invalid = _valid_batch_payload(packet)
    second_invalid["briefs"][0]["status"] = "INVALID"
    write_json(draft_path, second_invalid)
    with pytest.raises(ValueError, match="repair_authorized=false"):
        accept_authoring_batch(run_path, batch["batch_id"], draft_path, data_dir)
    second_receipt = read_json(rejection_dir / "attempt-2.json")
    assert second_receipt["repair_authorized"] is False

    write_json(draft_path, _valid_batch_payload(packet))
    with pytest.raises(RuntimeError, match="repair limit exhausted"):
        accept_authoring_batch(run_path, batch["batch_id"], draft_path, data_dir)


def test_analysis_validation_allows_one_repair_then_hard_stops(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context = read_json(Path(run["artifacts"]["context_path"]))
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    brief_path = write_json(
        Path(packet["draft_result_path"]),
        _valid_batch_payload(packet),
    )
    accept_authoring_batch(run_path, batch["batch_id"], brief_path, data_dir)
    prepare_authoring_analysis(run_path, data_dir)
    run = read_json(run_path)
    analysis_path = Path(run["artifacts"]["authoring"]["analysis_result_path"])

    write_json(
        analysis_path,
        {
            "featured_events": [
                {
                    "section_id": "information.international",
                    "source_item_ids": ["outside-authorized-packet"],
                }
            ],
            "analyses": [],
            "cross_perspective_synthesis": {},
        },
    )
    with pytest.raises(ValueError, match="structured rejection receipt"):
        assemble_authoring(run_path, analysis_path, data_dir)

    rejection_dir = analysis_path.parent / "analysis-rejections"
    first = read_json(rejection_dir / "attempt-1.json")
    assert first["scope"] == "analysis"
    assert first["repair_authorized"] is True
    assert first["validation_errors"]

    write_json(
        analysis_path,
        {
            "featured_events": "not-an-array",
            "analyses": [],
            "cross_perspective_synthesis": {},
        },
    )
    with pytest.raises(ValueError, match="repair_authorized=false"):
        assemble_authoring(run_path, analysis_path, data_dir)
    second = read_json(rejection_dir / "attempt-2.json")
    assert second["repair_authorized"] is False

    write_json(
        analysis_path,
        {"featured_events": [], "analyses": [], "cross_perspective_synthesis": {}},
    )
    with pytest.raises(RuntimeError, match="repair limit exhausted"):
        assemble_authoring(run_path, analysis_path, data_dir)


def test_analysis_state_projection_is_bounded_and_does_not_mutate_source():
    theses = [
        {
            "analysis_id": f"thesis-{domain}-{position}",
            "domain": domain,
            "claim": f"Measured claim {position}",
            "confidence": 0.6,
            "status": "active",
            "updated_at": f"2026-08-{position + 1:02d}T00:00:00+08:00",
            "first_seen_at": "2026-07-01T00:00:00+08:00",
            "history": ["large historical text" * 100],
        }
        for domain in ("geopolitics", "ai_technology", "markets")
        for position in range(8)
    ]
    watchlist = [
        {
            "watch_id": f"watch-{position}",
            "analysis_id": theses[position % len(theses)]["analysis_id"],
            "signal": f"Observable signal {position}",
            "status": "active",
            "updated_at": f"2026-08-{(position % 28) + 1:02d}T00:00:00+08:00",
            "first_seen_at": "2026-07-02T00:00:00+08:00",
        }
        for position in range(80)
    ]
    context = {
        "active_theses": theses,
        "active_watchlist": watchlist,
        "open_predictions": [],
        "user_feedback": [
            {
                "feedback_id": "feedback-1",
                "page_id": "page-1",
                "captured_at": "2026-08-22T18:00:00+08:00",
                "scores": {"coverage": 4, "readability": 5},
                "comment": "增加国内市场覆盖。",
                "internal_note": "must be omitted",
            },
            {
                "feedback_id": "feedback-2",
                "page_id": "page-2",
                "captured_at": "2026-08-23T18:00:00+08:00",
                "scores": {"coverage": 5},
                "comment": "保持来源可追溯。",
            },
        ],
    }

    projection = _project_analysis_state(context)

    assert len(projection["active_theses"]) == 12
    assert len(projection["active_watchlist"]) == 30
    domains = Counter(row["domain"] for row in projection["active_theses"])
    assert domains == {
        "geopolitics": 4,
        "ai_technology": 4,
        "markets": 4,
    }
    assert all("history" not in row for row in projection["active_theses"])
    assert all("first_seen_at" in row for row in projection["active_theses"])
    assert all("status" not in row for row in projection["active_watchlist"])
    assert all("first_seen_at" in row for row in projection["active_watchlist"])
    assert projection["user_feedback"] == [
        {
            "feedback_id": "feedback-2",
            "page_id": "page-2",
            "captured_at": "2026-08-23T18:00:00+08:00",
            "scores": {"coverage": 5},
            "comment": "保持来源可追溯。",
        },
        {
            "feedback_id": "feedback-1",
            "page_id": "page-1",
            "captured_at": "2026-08-22T18:00:00+08:00",
            "scores": {"coverage": 4, "readability": 5},
            "comment": "增加国内市场覆盖。",
        }
    ]
    metadata = projection["state_projection"]
    projected_rows = {
        key: projection[key]
        for key in (
            "active_theses",
            "active_watchlist",
            "open_predictions",
            "user_feedback",
        )
    }
    assert metadata["selected_row_bytes"] == _compact_json_bytes(projected_rows)
    assert metadata["selected_row_bytes"] <= metadata["row_byte_limit"]
    assert metadata["source_counts"] == {
        "active_theses": 24,
        "active_watchlist": 80,
        "open_predictions": 0,
        "user_feedback": 2,
    }
    assert len(context["active_theses"][0]["history"]) == 1

    tiny = _project_analysis_state(context, row_byte_limit=256)
    assert tiny["state_projection"]["selected_row_bytes"] <= 256


def test_prepare_analysis_recovers_a_valid_assigned_draft_without_a_receipt(
    tmp_path: Path,
):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context = read_json(Path(run["artifacts"]["context_path"]))
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    write_json(Path(packet["draft_result_path"]), _valid_batch_payload(packet))

    prepare_authoring_analysis(run_path, data_dir)

    recovered_run = read_json(run_path)
    authoring = recovered_run["artifacts"]["authoring"]
    assert Path(packet["accepted_result_path"]).is_file()
    assert authoring["recovered_batches"] == [batch["batch_id"]]
    assert authoring["missing_batches"] == []
    assert authoring["brief_count"] == len(packet["author_item_ids"])


def test_degraded_coverage_only_lowers_sources_from_the_missing_batch(tmp_path: Path):
    completed_path = write_json(
        tmp_path / "completed.json",
        {"briefs": [{"item_id": "complete-1"}]},
    )
    context = {
        "reusable_briefs": [],
        "brief_plan": [
            {
                "source_id": "complete_source",
                "section_id": "information.international",
                "batch_id": "batch-complete",
                "target_count": 2,
                "default_item_ids": ["complete-1"],
            },
            {
                "source_id": "missing_source",
                "section_id": "information.domestic",
                "batch_id": "batch-missing",
                "target_count": 2,
                "default_item_ids": ["missing-1", "missing-2"],
            },
        ],
    }
    session = {
        "batches": [
            {"batch_id": "batch-complete", "result_path": str(completed_path)},
            {
                "batch_id": "batch-missing",
                "result_path": str(tmp_path / "missing.json"),
            },
        ]
    }

    _sections, missing_batches, coverage_targets = _merge_briefs(
        context,
        session,
        allow_degraded=True,
    )

    assert missing_batches == ["batch-missing"]
    assert coverage_targets == {"complete_source": 2, "missing_source": 0}


def test_authoring_batch_rejects_missing_assigned_items(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context = read_json(Path(run["artifacts"]["context_path"]))
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    payload = _valid_batch_payload(packet)
    payload["briefs"].pop()
    draft_path = write_json(Path(packet["draft_result_path"]), payload)

    with pytest.raises(ValueError, match="missing assigned item IDs"):
        accept_authoring_batch(
            run_path,
            batch["batch_id"],
            draft_path,
            data_dir,
        )

    assert not Path(packet["accepted_result_path"]).exists()


def test_authoring_metrics_keep_only_bounded_delegate_observability(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    session = read_json(Path(run["artifacts"]["authoring"]["session_path"]))
    metrics_draft = write_json(
        Path(session["paths"]["delegation_metrics_draft"]),
        {
            "results": [
                {
                    "task_index": 0,
                    "status": "completed",
                    "summary": "This potentially large child response is not retained.",
                    "tool_trace": [{"tool": "terminal"}],
                    "api_calls": 4,
                    "duration_seconds": 12.5,
                    "model": "fast-model",
                    "exit_reason": "completed",
                    "tokens": {"input": 1200, "output": 340},
                }
            ],
            "total_duration_seconds": 12.8,
        },
    )

    accepted_path = accept_authoring_metrics(run_path, metrics_draft, data_dir)
    accepted = read_json(accepted_path)

    assert accepted["totals"]["wall_seconds"] == 12.8
    assert accepted["totals"]["child_compute_seconds"] == 12.5
    assert accepted["totals"]["api_calls"] == 4
    assert accepted["totals"]["input_tokens"] == 1200
    assert accepted["totals"]["output_tokens"] == 340
    assert accepted["totals"]["reasoning_tokens"] is None
    assert accepted["coverage"]["reasoning_tokens"] == {
        "known_batches": 0,
        "missing_batches": 1,
        "known_subtotal": None,
    }
    assert accepted["batch_metrics"][0]["batch_id"] == "brief-batch-1"
    assert "summary" not in accepted["batch_metrics"][0]
    assert "tool_trace" not in accepted["batch_metrics"][0]
    status = get_authoring_status(run_path, data_dir)
    assert status["batches"][0]["duration_source"] == "delegate_result"
    assert status["batches"][0]["output_tokens"] == 340


def test_authoring_metrics_never_turn_unknown_usage_into_zero(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    session = read_json(Path(run["artifacts"]["authoring"]["session_path"]))
    metrics_draft = write_json(
        Path(session["paths"]["delegation_metrics_draft"]),
        {
            "results": [
                {
                    "task_index": 0,
                    "status": "completed",
                    "duration_seconds": 1.5,
                    "tokens": {"output": 8},
                }
            ]
        },
    )

    accepted = read_json(accept_authoring_metrics(run_path, metrics_draft, data_dir))

    assert accepted["totals"]["wall_seconds"] is None
    assert accepted["coverage"]["wall_seconds"] == {
        "quality": "unobservable",
        "source": "missing_total_duration",
    }
    assert accepted["totals"]["child_compute_seconds"] == 1.5
    assert accepted["coverage"]["child_compute_seconds"] == {
        "quality": "exact",
        "known_batches": 1,
        "missing_batches": 0,
    }
    assert accepted["totals"]["api_calls"] is None
    assert accepted["totals"]["input_tokens"] is None
    assert accepted["totals"]["output_tokens"] == 8
    assert accepted["coverage"]["input_tokens"]["missing_batches"] == 1
    assert accepted["batch_metrics"][0]["api_calls"] is None


def test_authoring_metrics_count_unsubmitted_session_batches_as_unobserved(
    tmp_path: Path,
):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    session_path = Path(run["artifacts"]["authoring"]["session_path"])
    session = read_json(session_path)
    session["batches"].append(
        {
            **session["batches"][0],
            "batch_id": "brief-batch-2",
            "result_path": str(tmp_path / "unsubmitted-result.json"),
        }
    )
    write_json(session_path, session)
    metrics_draft = write_json(
        Path(session["paths"]["delegation_metrics_draft"]),
        {
            "results": [
                {
                    "batch_id": "brief-batch-1",
                    "status": "completed",
                    "duration_seconds": 2.0,
                    "api_calls": 3,
                    "tokens": {"input": 100, "output": 20},
                }
            ]
        },
    )

    accepted = read_json(accept_authoring_metrics(run_path, metrics_draft, data_dir))

    assert accepted["coverage"]["batches"] == {
        "expected_batches": 2,
        "submitted_batches": 1,
        "unobserved_batches": 1,
    }
    assert accepted["totals"]["api_calls"] is None
    assert accepted["coverage"]["api_calls"] == {
        "known_batches": 1,
        "missing_batches": 1,
        "known_subtotal": 3,
    }
    assert accepted["totals"]["child_compute_seconds"] == 2.0
    assert accepted["coverage"]["child_compute_seconds"]["quality"] == "partial"
    assert accepted["batch_metrics"][1]["status"] == "unobserved"


def test_authoring_session_rejects_context_change_after_dispatch(tmp_path: Path):
    data_dir, run_path = _authoring_run(tmp_path)
    begin_authoring(run_path, data_dir)
    run = read_json(run_path)
    context_path = Path(run["artifacts"]["context_path"])
    context = read_json(context_path)
    context["context_warnings"] = ["context changed after workers were dispatched"]
    write_json(context_path, context)

    with pytest.raises(RuntimeError, match="context changed after dispatch"):
        begin_authoring(run_path, data_dir)
