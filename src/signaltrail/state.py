from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from .storage import exclusive_lock, next_revision, write_immutable_json
from .utils import read_json, write_json

_STABLE_ANALYSIS_DOMAINS = {"geopolitics", "ai_technology", "markets"}


def stable_analysis_id(domain: object) -> str:
    """处理：为三个固定分析栏目生成跨日期、版本和评估修订稳定的栏目身份。
    输入：
    - ``domain``：报告编译器已验证的 geopolitics、ai_technology 或 markets 域名。
    输出：ANALYSIS-{DOMAIN} 形式的稳定 ID；未知域明确失败而不回退到日期 ID。
    """

    normalized = str(domain or "").strip().casefold()
    if normalized not in _STABLE_ANALYSIS_DOMAINS:
        raise ValueError(f"Unsupported stable analysis domain: {normalized!r}")
    return f"ANALYSIS-{normalized.upper()}"


def _items(path: Path) -> list[dict[str, Any]]:
    """处理：展开报告全部栏目中的事件或简报条目。
    输入：
    - ``path``：当前函数要读取、校验或写入的本地文件路径。
    输出：“展开报告全部栏目中的事件或简报条目”得到的有序结构化记录；
      每项承载处理说明所定义的身份、证据或状态字段，可直接交给下一阶段。
    """
    if not path.exists():
        return []
    raw = read_json(path)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return [item for item in raw["items"] if isinstance(item, dict)]
    raise ValueError(f"State file must contain a list or an object with items: {path}")


def _identity_text(value: str) -> str:
    """处理：消除身份文本的排版差异，不猜测改写句子的语义等价性。
    输入：报告中已验证的论点或观察信号文字。
    输出：Unicode 规范化并压缩空白的稳定文本键，保留大小写与标点含义。
    """
    return " ".join(unicodedata.normalize("NFC", value).split())


def thesis_identity(analysis: dict[str, Any]) -> str:
    """处理：把领域、具体判断和证据集合绑定为保守的论点身份。
    输入：已编译分析中的 domain、claim 与 Python 拥有的事件 ID。
    输出：可重复构建的 THESIS 标识；改写或换证据不会自动覆盖已有论点。
    """
    key = [
        stable_analysis_id(analysis["domain"]), _identity_text(analysis["claim"]),
        sorted(set(analysis.get("evidence_event_ids", []))),
    ]
    digest = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:24]
    return f"THESIS-{digest}"


def _watch_id(thesis_id: str, signal: str) -> str:
    """处理：将观察项绑定到具体论点，避免同领域的不同议题共用身份。
    输入：论点 ID 与报告观察文字；文字只做保守的排版规范化。
    输出：相同论点和规范信号下稳定的观察 ID，语义改写保持独立记录。
    """
    key = json.dumps([thesis_id, _identity_text(signal)], ensure_ascii=False)
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return f"WATCH-{digest}"


def update_continuity_state(
    report: dict[str, Any],
    data_dir: Path,
) -> dict[str, str]:
    """处理：串行更新跨报告共享状态，避免不同日期评估覆盖彼此结果。
    输入：已通过连续性门槛的报告与绑定数据根。
    输出：当前状态文件路径；并发占用时明确失败，供评估流程重试。
    """
    with exclusive_lock(data_dir / "state" / ".continuity.lock", {
        "report_id": report["report_id"],
    }):
        return _update_continuity_state(report, data_dir)


def _update_continuity_state(
    report: dict[str, Any], data_dir: Path,
) -> dict[str, str]:
    """处理：从已评估报告更新论点、观察列表和预测状态。
    输入：
    - ``report``：当前报告结构；包含栏目、简报或事件、来源引用及质量元数据。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：“从已评估报告更新论点、观察列表和预测状态”形成的结构化字典；
      典型键包括 analysis_id、category、claim、confidence、counter_evidence、domain、event_id、e
      vents、evidence_event_ids、first_seen_at、generated_at、history。
    """
    state_dir = data_dir / "state"
    generated_at = report["generated_at"]
    report_id = report["report_id"]
    evaluation = report.get("quality_evaluation", {})
    excluded = set(evaluation.get("exclude_from_continuity", []))
    skip_analyses = bool(excluded & {"analyses", "all"})
    skip_events = bool(excluded & {"event_summaries", "all"})

    theses_path = state_dir / "theses.json"
    theses = {
        item.get("thesis_id") or item["analysis_id"]: item
        for item in _items(theses_path) if item.get("thesis_id") or item.get("analysis_id")
    }
    domains = {
        item["analysis_id"]: item
        for item in _items(state_dir / "analysis-domains.json") if item.get("analysis_id")
    }
    for legacy in theses.values():
        if not legacy.get("thesis_id"):
            # 旧栏目状态可能已混合多个议题；只标记歧义，不伪造迁移关系或关闭原观察项。
            legacy.setdefault("identity_scope", "legacy_unresolved")
    for analysis in [] if skip_analyses else report["analyses"]:
        analysis_id = stable_analysis_id(analysis["domain"])
        thesis_id = thesis_identity(analysis)
        previous = theses.get(thesis_id, {})
        history = list(previous.get("history", []))
        if not any(item.get("report_id") == report_id for item in history):
            history.append(
                {
                    "report_id": report_id,
                    "generated_at": generated_at,
                    "state_change": analysis["state_change"],
                    "confidence": analysis["confidence"],
                    "evidence_event_ids": analysis["evidence_event_ids"],
                }
            )
        status = "closed" if analysis["state_change"] in {"closed", "invalidated"} else "active"
        record = {
            "analysis_id": analysis_id,
            "thesis_id": thesis_id,
            "identity_scope": "claim_and_evidence",
            "domain": analysis["domain"],
            "claim": analysis["claim"],
            "confidence": analysis["confidence"],
            "status": status,
            "state_change": analysis["state_change"],
            "evidence_event_ids": analysis["evidence_event_ids"],
            "counter_evidence": analysis["counter_evidence"],
            "implications": analysis["implications"],
            "watch_signals": analysis["watch_signals"],
            "first_seen_at": previous.get("first_seen_at", generated_at),
            "updated_at": generated_at,
            "last_report_id": report_id,
            "history": history,
        }
        # 迟到评估可以补全历史，不能把同一论点或栏目倒退到旧报告状态。
        if str(previous.get("updated_at", "")) > generated_at:
            previous["history"] = history
        else:
            theses[thesis_id] = record
        if str(domains.get(analysis_id, {}).get("updated_at", "")) <= generated_at:
            domains[analysis_id] = {**record, "identity_scope": "analysis_domain"}

    watchlist_path = state_dir / "watchlist.json"
    watchlist = {item["watch_id"]: item for item in _items(watchlist_path) if item.get("watch_id")}
    for legacy in watchlist.values():
        if not legacy.get("thesis_id"):
            legacy.setdefault("identity_scope", "legacy_unresolved")
    closed_thesis_ids: set[str] = set()
    for analysis in [] if skip_analyses else report["analyses"]:
        thesis_id = thesis_identity(analysis)
        if str(theses[thesis_id].get("updated_at", "")) > generated_at:
            continue
        if analysis["state_change"] in {"closed", "invalidated"}:
            closed_thesis_ids.add(thesis_id)
            continue
        analysis_id = stable_analysis_id(analysis["domain"])
        for signal in analysis["watch_signals"]:
            watch_id = _watch_id(thesis_id, signal)
            previous = watchlist.get(watch_id, {})
            watchlist[watch_id] = {
                "watch_id": watch_id,
                "analysis_id": analysis_id,
                "thesis_id": thesis_id,
                "identity_scope": "thesis_and_signal_text",
                "signal": signal,
                "status": "active",
                "first_seen_at": previous.get("first_seen_at", generated_at),
                "updated_at": generated_at,
                "last_report_id": report_id,
            }
    for item in watchlist.values():
        # 未提及不等于关闭；仅同一具体论点的明确终止能关闭其观察项。
        if item.get("thesis_id") in closed_thesis_ids:
            item["status"] = "closed"
            item["updated_at"] = generated_at
            item["last_report_id"] = report_id
            item["closure_reason"] = "thesis_closed"

    events_path = state_dir / "events.json"
    events = {item["event_id"]: item for item in _items(events_path) if item.get("event_id")}
    for section in [] if skip_events else report["sections"]:
        for event in section["items"]:
            event_id = event["event_id"]
            previous = events.get(event_id, {})
            report_ids = list(previous.get("report_ids", []))
            if report_id not in report_ids:
                report_ids.append(report_id)
            events[event_id] = {
                "event_id": event_id,
                "module": section["module"],
                "category": section["category"],
                "title": event["title"],
                "status": event["status"],
                "importance": event["importance"],
                "confidence": event["confidence"],
                "source_item_ids": [ref["item_id"] for ref in event["source_refs"]],
                "tags": event["tags"],
                "first_seen_at": previous.get("first_seen_at", generated_at),
                "updated_at": generated_at,
                "last_report_id": report_id,
                "report_ids": report_ids,
            }

    payloads = {
        "theses": {
            "schema_version": "1.2",
            "updated_at": generated_at,
            "items": sorted(theses.values(), key=lambda item: (
                item.get("thesis_id") or item["analysis_id"]
            )),
        },
        "analysis-domains": {
            "schema_version": "1.0",
            "updated_at": generated_at,
            "items": sorted(domains.values(), key=lambda item: item["analysis_id"]),
        },
        "watchlist": {
            "schema_version": "1.2",
            "updated_at": generated_at,
            "items": sorted(watchlist.values(), key=lambda item: item["watch_id"]),
        },
        "events": {
            "schema_version": "1.0",
            "updated_at": generated_at,
            "items": sorted(events.values(), key=lambda item: item["event_id"]),
        },
    }
    outputs: dict[str, str] = {}
    for name, payload in payloads.items():
        current_path = state_dir / f"{name}.json"
        write_json(current_path, payload)
        history_dir = state_dir / "history" / name
        revision = next_revision(history_dir, report["date"])
        history_path = history_dir / f"{report['date']}-r{revision}.json"
        write_immutable_json(history_path, payload)
        outputs[name] = str(current_path)
    return outputs
