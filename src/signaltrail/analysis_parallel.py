from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .authoring import (
    _ANALYSIS_DOMAIN_ORDER,
    _contract_schema_errors,
    _normalize_analysis_narratives,
    _write_analysis_input,
    validate_analysis_evidence,
)
from .runtime import require_data_root_path
from .utils import read_json


def _base_packet(run: dict[str, Any], data_dir: Path) -> tuple[dict[str, Any], Path]:
    """处理：读取当前会话的原始分析包，确定并行文件所在目录。
    输入：运行清单中的分析包路径和当前数据根。
    输出：原始证据包与同会话目录，供分阶段裁剪和汇编。
    """
    path = require_data_root_path(
        Path(run["artifacts"]["authoring"]["analysis_packet_path"]), data_dir,
        "Analysis packet",
    )
    return read_json(path), path.parent


def _check(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    """处理：复用分析契约检查分阶段模型输出。
    输入：当前阶段的输出结构与模型返回内容。
    输出：合法内容继续流转，结构错误附具体字段位置抛出。
    """
    errors = _contract_schema_errors(schema, payload)
    if errors:
        raise ValueError("; ".join(errors))


def _write_packet(
    base: dict[str, Any], directory: Path, name: str, task: str,
    schema: dict[str, Any], **evidence: Any,
) -> dict[str, str]:
    """处理：保存独立阶段输入，并固定其模型输出位置。
    输入：原包公共语言和规范、阶段任务、输出结构及裁剪后的证据。
    输出：幂等保存的任务包与结果路径，供协调者分派。
    """
    packet_path = directory / f"analysis-{name}-packet.json"
    result_path = directory / f"analysis-{name}-draft.json"
    packet = {
        key: base[key]
        for key in ("output_language", "untrusted_data_notice")
    }
    protocol = base["analysis_protocol"]
    if name == "selection":
        protocol = {key: protocol[key] for key in ("featured_event_target", "shared_dossier_rule")
                    if key in protocol}
    elif name == "synthesis":
        protocol = {key: protocol[key] for key in ("shared_dossier_rule", "token_rule")
                    if key in protocol}
    else:
        protocol = {key: value for key, value in protocol.items()
                    if key not in {"featured_event_target", "domains", "per_lens_required_fields",
                                   "cross_perspective_synthesis_required", "synthesis_fields"}}
    packet["analysis_protocol"] = protocol
    packet.update(
        task=task, output_schema=schema, analysis_result_path=str(result_path.resolve()),
        usage_correlation={**base["usage_correlation"], "agent_role": f"analysis-{name}"},
        **evidence,
    )
    if base.get("user_feedback"):
        packet["user_feedback"] = base["user_feedback"]
    _write_analysis_input(packet_path, packet)
    return {"packet_path": str(packet_path), "result_path": str(result_path)}


def prepare_analysis_selection(run: dict[str, Any], data_dir: Path) -> dict[str, str]:
    """处理：把事件选取从长篇研判中分离，冻结三域共享的证据分配。
    输入：已经合并简报并生成原分析包的运行清单。
    输出：只选精选事件和三域引用集合的短协调任务包。
    """
    base, directory = _base_packet(run, data_dir)
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["featured_events", "domain_evidence_item_ids"],
        "properties": {
            "featured_events": base["output_schema"]["properties"]["featured_events"],
            "domain_evidence_item_ids": {
                "type": "object", "additionalProperties": False,
                "required": list(_ANALYSIS_DOMAIN_ORDER),
                "properties": {
                    domain: {"type": "array", "minItems": 1, "uniqueItems": True,
                             "items": {"type": "string"}}
                    for domain in _ANALYSIS_DOMAIN_ORDER
                },
            },
        },
    }
    return _write_packet(
        base, directory, "selection",
        "Select featured events under output_schema and featured_freshness_minimum. "
        "Assign a coherent evidence subset to each domain; reuse IDs across domains when "
        "useful. Every assigned ID must belong to a featured event and the three subsets "
        "together must cover at least 60% of featured events. Keep each domain coherent. "
        "Write reader-facing text in output_language. "
        "Return only featured_events and domain_evidence_item_ids; do not write analyses.",
        schema, candidate_events=base["candidate_events"],
        featured_freshness_minimum=base["featured_freshness_minimum"],
    )


def _selection(base: dict[str, Any], directory: Path) -> dict[str, Any]:
    """处理：核对冻结事件与领域分配，确保并行作者共享同一证据边界。
    输入：原包以及已完成选择的会话目录。
    输出：通过结构、新鲜度及引用覆盖检查的选择结果。
    """
    packet = read_json(directory / "analysis-selection-packet.json")
    selection = read_json(directory / "analysis-selection-draft.json")
    _check(packet["output_schema"], selection)
    errors = validate_analysis_evidence(
        {**base, "output_schema": {"type": "object"}},
        {"featured_events": selection["featured_events"]},
    )
    featured = {item for event in selection["featured_events"] for item in event["source_item_ids"]}
    assignments = selection["domain_evidence_item_ids"]
    assigned = set().union(*(set(ids) for ids in assignments.values()))
    covered = sum(bool(assigned.intersection(event["source_item_ids"]))
                  for event in selection["featured_events"])
    if assigned - featured or covered * 5 < len(selection["featured_events"]) * 3:
        errors.append("Domain evidence must use featured item IDs and cover at least 60% of events")
    if errors:
        raise ValueError("; ".join(errors))
    _write_analysis_input(directory / "analysis-selection-accepted.json", selection)
    return selection


def prepare_analysis_domains(run: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    """处理：按已分配证据生成三个可同时执行的完整研判任务。
    输入：原分析包和协调者完成的精选事件、三域证据集合。
    输出：保留原单域写作规范与结构、裁剪无关证据和历史的三个包。
    """
    base, directory = _base_packet(run, data_dir)
    selection = _selection(base, directory)
    packets = []
    for domain in _ANALYSIS_DOMAIN_ORDER:
        ids = set(selection["domain_evidence_item_ids"][domain])
        schema = deepcopy(base["output_schema"]["properties"]["analyses"]["items"])
        schema["properties"]["domain"] = {"const": domain}
        # 历史投影已有限量；无可辨识领域的旧记录保留，避免观察链条被静默切断。
        state = {
            field: [row for row in base[field] if not row.get("domain")
                    and not row.get("analysis_id")
                    or row.get("domain") == domain
                    or domain in str(row.get("analysis_id", "")).casefold()
                    or row.get("identity_scope") == "legacy_unresolved"]
            for field in ("active_theses", "active_watchlist", "open_predictions")
        }
        state["continuity_reports"] = [
            {**report, "analyses": [row for row in report.get("analyses", [])
                                   if row.get("domain") == domain]}
            for report in base.get("continuity_reports", [])
        ]
        packets.append({"domain": domain, **_write_packet(
            base, directory, domain,
            f"Write exactly one {domain} analysis using only assigned evidence_item_ids. "
            "Follow analysis_protocol in full: complete the reasoning ledger, then write "
            "a standalone narrative of 4-7 natural paragraphs. Keep one coherent causal "
            "question and concentrate material caveats in a closing Limitations paragraph. "
            "For each watch signal name the observation target, any review time available "
            "in the evidence, and the direction in which it would change the judgment. "
            "Preserve thesis identity and existing open watch signals in continuity history. "
            "Write reader-facing text in output_language. Return the analysis object only.",
            schema, evidence_item_ids=sorted(ids),
            candidate_events=[row for row in base["candidate_events"] if row["item_id"] in ids],
            featured_events=[row for row in selection["featured_events"]
                             if ids.intersection(row["source_item_ids"])], **state,
        )})
    return {"domain_packets": packets}


def _domain_results(base: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
    """处理：接收三个领域结果并限制引用范围，交给综合作者读取。
    输入：原分析包及当前会话下的三个任务包和草稿。
    输出：按稳定领域顺序排列、保留完整论证的研判数组。
    """
    analyses = []
    for domain in _ANALYSIS_DOMAIN_ORDER:
        packet = read_json(directory / f"analysis-{domain}-packet.json")
        analysis = read_json(directory / f"analysis-{domain}-draft.json")
        _check(packet["output_schema"], analysis)
        if set(analysis["evidence_item_ids"]) - set(packet["evidence_item_ids"]):
            raise ValueError(f"{domain}: evidence references exceed assigned item IDs")
        analysis = _normalize_analysis_narratives({"analyses": [analysis]})["analyses"][0]
        errors = validate_analysis_evidence(
            {**base, "output_schema": {"type": "object"}, "featured_freshness_minimum": 0},
            {"featured_events": packet["featured_events"], "analyses": [analysis]},
        )
        if errors:
            raise ValueError("; ".join(errors))
        _write_analysis_input(directory / f"analysis-{domain}-accepted.json", analysis)
        analyses.append(analysis)
    return analyses


def prepare_analysis_synthesis(run: dict[str, Any], data_dir: Path) -> dict[str, str]:
    """处理：用三个完整研判生成短综合任务，避免再次传入全量候选和历史。
    输入：已完成的三域输出与冻结精选事件。
    输出：只需标题、摘要和跨视角综合的任务包。
    """
    base, directory = _base_packet(run, data_dir)
    selection = _selection(base, directory)
    analyses = _domain_results(base, directory)
    schema = deepcopy(base["output_schema"])
    for field in ("featured_events", "analyses"):
        schema["required"].remove(field)
        del schema["properties"][field]
    return _write_packet(
        base, directory, "synthesis",
        "Write the report title, executive_summary and cross_perspective_synthesis from "
        "the accepted analyses and frozen featured events. Preserve disagreements, separate "
        "independent mechanisms, and cite selected source_item_ids only. "
        "Do not rewrite domain articles or repeat their reasoning ledgers. "
        "Explain concrete cross-domain transmission only where evidence supports a link; "
        "keep unrelated domains independent. Watch signals identify the observation target, "
        "any evidence-supported review time, and the resulting direction of judgment change. "
        "Write in output_language.",
        schema, featured_events=selection["featured_events"],
        analyses=[{key: value for key, value in analysis.items() if key in {
            "domain", "claim", "narrative", "counter_evidence", "confidence",
            "watch_signals", "invalidation_signals", "evidence_item_ids",
        }} for analysis in analyses],
    )


def assemble_parallel_analysis(run: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    """处理：确定性合并精选、三域和综合，沿用原报告编译与质量门槛。
    输入：当前会话完成的选择、领域研判和综合草稿。
    输出：原格式分析草稿及原汇编器的报告结果，兼容后续发布流程。
    """
    base, directory = _base_packet(run, data_dir)
    selection = _selection(base, directory)
    analyses = _domain_results(base, directory)
    packet = read_json(directory / "analysis-synthesis-packet.json")
    synthesis = read_json(directory / "analysis-synthesis-draft.json")
    _check(packet["output_schema"], synthesis)
    payload = {**synthesis, "featured_events": selection["featured_events"], "analyses": analyses}
    errors = validate_analysis_evidence(base, payload)
    if errors:
        raise ValueError("; ".join(errors))
    path = Path(base["analysis_result_path"])
    _write_analysis_input(path, payload)
    return {"analysis_result_path": str(path)}
