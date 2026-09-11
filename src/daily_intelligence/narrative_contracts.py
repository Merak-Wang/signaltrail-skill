"""Bounded author/reviewer schemas and versioned admission policy."""

from __future__ import annotations

from enum import StrEnum

from jsonschema import Draft202012Validator

POLICY = {
    "version": "explainer-1.0",
    "languages": ["zh-CN", "en"],
    "max_repairs": 1,
    "min_events": 6,
    "max_events": 10,
    "min_featured_coverage": 0.6,
    "max_evidence_characters": 8000,
    "current_admission": "requires_external_freshness_adapter",
    "assets": "original_explanatory_diagrams_only",
    "usage_acceptance": "unknown_is_not_zero",
}


class Admission(StrEnum):
    """处理：区分语义稿件、历史实验和实时新闻准入。
    输入：程序门禁判定的状态，不接受作者自行声称通过。
    输出：稳定状态供命令、页面及回执显示。
    """

    DRAFT = "draft"
    VERIFIED = "verified_snapshot"
    BLOCKED = "blocked_current"


def obj(properties: dict) -> dict:
    """处理：构造禁止额外字段的完整对象契约。
    输入：接收器声明的字段 Schema。
    输出：要求全部字段的对象 Schema，防止作者注入身份或通过标签。
    """
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(items: dict, minimum: int = 0, maximum: int = 200) -> dict:
    """处理：限定模型输出列表的大小。
    输入：元素 Schema 与业务数量上下限。
    输出：供离线校验和模型 packet 共用的数组契约。
    """
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
REFS = {**array(TEXT), "uniqueItems": True}
NULL_TEXT = {"anyOf": [TEXT, {"type": "null"}]}
SEGMENT = obj({"text": TEXT, "claim_ids": REFS})
LEDGER_SCHEMA = obj(
    {
        "claims": array(
            obj(
                {
                    "key": TEXT,
                    "text": TEXT,
                    "kind": {
                        "enum": [
                            "attributed_fact",
                            "background",
                            "inference",
                            "uncertainty",
                            "watch",
                        ]
                    },
                    "evidence_span_ids": REFS,
                    "analysis_ids": REFS,
                    "event_ids": REFS,
                    "required": {"type": "boolean"},
                    "temporal_scope": {
                        "enum": ["snapshot", "historical", "planned", "conditional"]
                    },
                    "event_time": NULL_TEXT,
                    "event_time_precision": {"enum": ["unknown", "date", "timestamp"]},
                    "attribution": NULL_TEXT,
                    "qualifiers": array(TEXT),
                }
            ),
            1,
            100,
        )
    }
)
SCRIPT_SCHEMA = obj(
    {
        "language": {"enum": POLICY["languages"]},
        "title": SEGMENT,
        "introduction": SEGMENT,
        "chapters": array(
            obj(
                {
                    "title": SEGMENT,
                    "question": SEGMENT,
                    "beats": array(
                        obj(
                            {
                                "text": TEXT,
                                "claim_ids": REFS,
                                "visual": array(SEGMENT, 0, 4),
                                "visual_relation": {
                                    "enum": ["parallel", "sequence", "conditional"]
                                },
                                "role": {
                                    "enum": ["change", "background", "mechanism", "limit", "watch"]
                                },
                            }
                        ),
                        1,
                        12,
                    ),
                }
            ),
            1,
            10,
        ),
        "closing": SEGMENT,
    }
)
REVIEW_SCHEMA = obj(
    {
        "segment_reviews": array(
            obj(
                {
                    "segment_id": TEXT,
                    "assertions": array(
                        obj(
                            {
                                "quote": TEXT,
                                "claim_ids": REFS,
                                "evidence_span_ids": REFS,
                                "verdict": {
                                    "enum": [
                                        "supported",
                                        "contradicted",
                                        "insufficient",
                                        "conflicted",
                                    ]
                                },
                                "note": TEXT,
                            }
                        )
                    ),
                    "no_assertion_reason": NULL_TEXT,
                }
            )
        ),
        "missing_required_claims": REFS,
        "findings": array(
            obj(
                {
                    "segment_id": TEXT,
                    "severity": {"enum": ["critical", "major", "minor"]},
                    "note": TEXT,
                }
            )
        ),
        "quality": obj(
            {
                "clarity": {"type": "integer", "minimum": 1, "maximum": 5},
                "narrative": {"type": "integer", "minimum": 1, "maximum": 5},
                "explanation": {"type": "integer", "minimum": 1, "maximum": 5},
                "note": TEXT,
            }
        ),
    }
)
BILINGUAL_SCHEMA = obj(
    {
        "claim_reviews": array(
            obj(
                {
                    "claim_id": TEXT,
                    "verdict": {"enum": ["equivalent", "drift", "missing"]},
                    "note": TEXT,
                }
            )
        ),
    }
)
VISUAL_SCHEMA = obj(
    {
        "cards": array(
            obj(
                {
                    "card_id": TEXT,
                    "desktop": {"enum": ["pass", "fail", "unavailable"]},
                    "mobile": {"enum": ["pass", "fail", "unavailable"]},
                    "note": TEXT,
                }
            )
        ),
        "projection_sha256": TEXT,
        "screenshots": array(TEXT, 1),
    }
)


def validate_schema(payload: dict, schema: dict) -> None:
    """处理：按注入模型的同一契约拒绝非法输出。
    输入：模型 JSON 与阶段 Schema；只报告路径和规则，不回显不可信正文。
    输出：合法时无返回值，非法时抛出可定位异常以记录拒绝尝试。
    """
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda error: str(error.json_path)
    )
    if errors:
        raise ValueError("; ".join(f"{e.json_path}: {e.validator}" for e in errors[:12]))
