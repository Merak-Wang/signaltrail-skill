from copy import deepcopy

import pytest

from daily_intelligence.narrative import submit_script
from daily_intelligence.narrative_store import load_artifact
from daily_intelligence.narrative_verification import (
    explainer_status,
    prepare_bilingual,
    prepare_review,
    submit_bilingual,
    submit_review,
)
from tests.test_narrative import explainer_case as explainer_case


def supported_review(packet_path, root):
    packet = load_artifact(packet_path, root)["payload"]
    span = packet["evidence"][0]["spans"][0]["span_id"]
    return {
        "segment_reviews": [
            {
                "segment_id": s["segment_id"],
                "assertions": [
                    {
                        "quote": s["text"],
                        "claim_ids": s["claim_ids"],
                        "evidence_span_ids": [span],
                        "verdict": "supported",
                        "note": "Supported",
                    }
                ],
                "no_assertion_reason": None,
            }
            for s in packet["segments"]
        ],
        "missing_required_claims": [],
        "findings": [],
        "quality": {"clarity": 4, "narrative": 4, "explanation": 4, "note": "Fixture opinion"},
    }


def test_review_requires_separate_context_and_exact_coverage(explainer_case):
    c = explainer_case
    p = prepare_review(c["script"], c["root"])
    review = supported_review(p, c["root"])
    with pytest.raises(ValueError, match="Independent"):
        submit_review(p, review, c["root"], reviewer_context="author")
    missing = deepcopy(review)
    missing["segment_reviews"].pop(0)
    with pytest.raises(ValueError, match="every segment"):
        submit_review(p, missing, c["root"], reviewer_context="reviewer")
    path = submit_review(p, review, c["root"], reviewer_context="reviewer")
    receipt = load_artifact(path, c["root"])["payload"]
    assert receipt["status"] == "verified_snapshot"
    assert receipt["current_admission"] == "blocked_current"


@pytest.mark.parametrize("defect", ["unsupported", "unmapped", "critical", "omission", "empty"])
def test_review_findings_cannot_be_offset_by_quality_score(explainer_case, defect):
    c = explainer_case
    p = prepare_review(c["script"], c["root"])
    review = supported_review(p, c["root"])
    assertion = review["segment_reviews"][0]["assertions"][0]
    if defect == "unsupported":
        assertion["verdict"] = "insufficient"
    elif defect == "unmapped":
        assertion["claim_ids"] = []
        assertion["evidence_span_ids"] = []
    elif defect == "critical":
        review["findings"] = [{"segment_id": "title", "severity": "critical", "note": "Wrong"}]
    elif defect == "omission":
        review["missing_required_claims"] = assertion["claim_ids"]
    else:
        review["segment_reviews"][0]["assertions"] = []
        review["segment_reviews"][0]["no_assertion_reason"] = "Pretended no assertion"
    result = submit_review(p, review, c["root"], reviewer_context="reviewer")
    assert load_artifact(result, c["root"])["payload"]["status"] == "draft"


def test_review_rejects_invented_quotes_and_spans(explainer_case):
    c = explainer_case
    p = prepare_review(c["script"], c["root"])
    review = supported_review(p, c["root"])
    review["segment_reviews"][0]["assertions"][0]["quote"] = "Never said this"
    with pytest.raises(ValueError, match="quote"):
        submit_review(p, review, c["root"], reviewer_context="reviewer")
    review = supported_review(p, c["root"])
    review["segment_reviews"][0]["assertions"][0]["evidence_span_ids"] = ["outside"]
    with pytest.raises(ValueError, match="unauthorized"):
        submit_review(p, review, c["root"], reviewer_context="reviewer")


def bilingual_case(c):
    en_packet = prepare_review(c["script"], c["root"])
    en_review = submit_review(
        en_packet, supported_review(en_packet, c["root"]), c["root"], reviewer_context="reviewer"
    )
    draft = deepcopy(c["script_draft"])
    draft["language"] = "zh-CN"
    zh_script = submit_script(c["ledger"], draft, c["root"], author_context="zh-author")
    zh_packet = prepare_review(zh_script, c["root"])
    zh_review = submit_review(
        zh_packet, supported_review(zh_packet, c["root"]), c["root"], reviewer_context="zh-reviewer"
    )
    bilingual_packet = prepare_bilingual(zh_review, en_review, c["root"])
    claim = c["script_draft"]["title"]["claim_ids"][0]
    bilingual = submit_bilingual(
        bilingual_packet,
        {"claim_reviews": [{"claim_id": claim, "verdict": "equivalent", "note": "Same meaning"}]},
        c["root"],
        reviewer_context="bilingual-reviewer",
    )
    return zh_script, bilingual, bilingual_packet


def test_bilingual_drift_blocks_bundle(explainer_case):
    c = explainer_case
    _, bilingual, packet = bilingual_case(c)
    assert load_artifact(bilingual, c["root"])["payload"]["status"] == "verified_snapshot"
    claim = c["script_draft"]["title"]["claim_ids"][0]
    result = submit_bilingual(
        packet,
        {
            "claim_reviews": [
                {"claim_id": claim, "verdict": "drift", "note": "English omits planned qualifier"}
            ]
        },
        c["root"],
        reviewer_context="bilingual-reviewer",
    )
    assert load_artifact(result, c["root"])["payload"]["status"] == "draft"


def test_status_does_not_claim_unknown_usage_or_current_admission(explainer_case):
    c = explainer_case
    status = explainer_status(c["script"], c["root"])
    assert status["usage"]["tokens"] is None
    assert status["current_admission"] == "blocked_current"
    assert status["covered_events"] == 1
