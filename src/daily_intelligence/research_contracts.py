"""Compact question, memo and report-link contracts for parallel research."""

from copy import deepcopy

from .narrative_contracts import LEDGER_SCHEMA, NULL_TEXT, REFS, TEXT, array, obj

DOMAINS = ["geopolitics", "ai_technology", "markets"]
QUESTION_SCHEMA = obj(
    {
        "key": TEXT,
        "domain": {"enum": DOMAINS},
        "question": TEXT,
        "weight": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
        "state": {"enum": ["not_evidenced", "partial", "answered", "contested"]},
        "evidence_span_ids": REFS,
        "gap": NULL_TEXT,
    }
)
QUESTIONS_SCHEMA = obj({"questions": array(QUESTION_SCHEMA, 1, 12)})
ANALYSIS_SCHEMA = obj(
    {
        "key": TEXT,
        "domain": {"enum": DOMAINS},
        "text": TEXT,
        "evidence_span_ids": {**REFS, "minItems": 1},
        "conditions": array(TEXT),
        "counterargument": TEXT,
        "watch": TEXT,
    }
)
_claim = deepcopy(LEDGER_SCHEMA["properties"]["claims"]["items"]["properties"])
del _claim["analysis_ids"]
del _claim["event_ids"]
_claim["analysis_keys"] = REFS
_claim["question_keys"] = {**REFS, "minItems": 1}
MEMO_SCHEMA = obj(
    {
        "memo": TEXT,
        "analyses": array(ANALYSIS_SCHEMA, 0, 12),
        "claims": array(obj(_claim), 1, 100),
    }
)
RELATIONS_SCHEMA = obj(
    {
        "relations": array(
            obj(
                {
                    "research_analysis_id": TEXT,
                    "report_analysis_id": TEXT,
                    "relation": {"enum": ["extends", "qualifies", "disputes"]},
                }
            ),
            0,
            36,
        )
    }
)
