import json
from copy import deepcopy
from pathlib import Path

import pytest

from daily_intelligence.config import OutputConfig
from daily_intelligence.narrative import (
    prepare_explainer,
    script_segments,
    submit_ledger,
    submit_script,
)
from daily_intelligence.narrative_store import load_artifact
from daily_intelligence.reports import save_report
from daily_intelligence.utils import write_json
from tests.report_helpers import load_sample_report, write_report_index


@pytest.fixture
def explainer_case(tmp_path):
    report = load_sample_report(Path(__file__).resolve().parents[1])
    index = write_report_index(report, tmp_path / "index.json")
    artifacts = save_report(
        write_json(tmp_path / "input.json", report),
        index,
        tmp_path,
        output_config=OutputConfig(formats=["html"]),
    )
    run = write_json(
        tmp_path / "run.json",
        {
            "status": "completed",
            "date": report["date"],
            "edition": report["edition"],
            "artifacts": {**artifacts, "index_path": str(index)},
        },
    )
    packet_path = prepare_explainer(run, tmp_path)
    packet = load_artifact(packet_path, tmp_path)["payload"]
    claim = {
        "key": "development",
        "text": "A source-attributed development.",
        "kind": "attributed_fact",
        "evidence_span_ids": [packet["evidence"][0]["spans"][0]["span_id"]],
        "analysis_ids": [],
        "event_ids": [packet["featured_events"][0]["event_id"]],
        "required": True,
        "temporal_scope": "snapshot",
        "event_time": None,
        "event_time_precision": "unknown",
        "attribution": "Example News",
        "qualifiers": [],
    }
    ledger_draft = {"claims": [claim]}
    ledger_path = submit_ledger(packet_path, ledger_draft, tmp_path)
    claim_id = load_artifact(ledger_path, tmp_path)["payload"]["claims"][0]["claim_id"]
    segment = {"text": "The source reports a development.", "claim_ids": [claim_id]}
    script_draft = {
        "language": "en",
        "title": deepcopy(segment),
        "introduction": deepcopy(segment),
        "closing": deepcopy(segment),
        "chapters": [
            {
                "title": deepcopy(segment),
                "question": deepcopy(segment),
                "beats": [
                    {
                        **deepcopy(segment),
                        "role": "change",
                        "visual": [deepcopy(segment)],
                        "visual_relation": "parallel",
                    }
                ],
            }
        ],
    }
    script_path = submit_script(ledger_path, script_draft, tmp_path, author_context="author")
    return {
        "root": tmp_path,
        "run": run,
        "packet": packet_path,
        "ledger": ledger_path,
        "ledger_draft": ledger_draft,
        "script_draft": script_draft,
        "script": script_path,
        "index": index,
        "report": Path(artifacts["json_path"]),
    }


def test_packet_uses_canonical_evidence_and_preserves_unknown_time(explainer_case):
    c = explainer_case
    p = load_artifact(c["packet"], c["root"])["payload"]
    assert p["evidence"][0]["event_time"] is None
    assert p["usage"]["input_tokens"] is None
    assert "output_schema" in p
    assert p["evidence"][0]["spans"][0]["field"] == "title"
    assert prepare_explainer(c["run"], c["root"]) == c["packet"]


@pytest.mark.parametrize("status", ["created", "awaiting_authoring", "failed", "completed_partial"])
def test_parent_completion_is_required(explainer_case, status):
    c = explainer_case
    run = json.loads(c["run"].read_text(encoding="utf-8"))
    run["status"] = status
    write_json(c["run"], run)
    with pytest.raises(ValueError, match="completed"):
        prepare_explainer(c["run"], c["root"])
    if status == "completed_partial":
        path = prepare_explainer(c["run"], c["root"], experimental=True)
        assert load_artifact(path, c["root"])["payload"]["experimental"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_span_ids", ["invented:title"]),
        ("event_ids", ["invented-event"]),
        ("analysis_ids", ["invented-analysis"]),
        ("event_time", "2026-09-08"),
        ("attribution", None),
        ("kind", "inference"),
        ("required", False),
    ],
)
def test_ledger_rejects_unauthorized_or_inconsistent_claims(explainer_case, field, value):
    c = explainer_case
    draft = deepcopy(c["ledger_draft"])
    draft["claims"][0][field] = value
    with pytest.raises(ValueError):
        submit_ledger(c["packet"], draft, c["root"])
    assert list(c["packet"].parent.glob("rejection-ledger-r*.json"))


def test_script_checks_headings_visuals_and_body_coverage(explainer_case):
    c = explainer_case
    draft = deepcopy(c["script_draft"])
    draft["title"]["claim_ids"] = ["unregistered"]
    with pytest.raises(ValueError, match="unregistered"):
        submit_script(c["ledger"], draft, c["root"], author_context="author")
    draft["title"]["claim_ids"] = c["script_draft"]["title"]["claim_ids"]
    draft["chapters"][0]["beats"][0]["claim_ids"] = []
    with pytest.raises(ValueError, match="budget exhausted"):
        submit_script(c["ledger"], draft, c["root"], author_context="author")
    assert (
        submit_script(c["ledger"], c["script_draft"], c["root"], author_context="author")
        == c["script"]
    )


@pytest.mark.parametrize("parent", ["packet", "ledger", "index", "report"])
def test_parent_mutation_invalidates_recursive_closure(explainer_case, parent):
    c = explainer_case
    with c[parent].open("a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="changed"):
        load_artifact(c["script"], c["root"])


def test_every_visible_label_is_a_reviewable_segment(explainer_case):
    c = explainer_case
    script = load_artifact(c["script"], c["root"])["payload"]["script"]
    ids = [s["segment_id"] for s in script_segments(script)]
    assert ids == [
        "title",
        "introduction",
        "chapter-1-title",
        "chapter-1-question",
        "chapter-1-beat-1",
        "chapter-1-beat-1-visual-1",
        "closing",
    ]


def test_policy_change_invalidates_old_packet(explainer_case, monkeypatch):
    from daily_intelligence.narrative_contracts import POLICY

    c = explainer_case
    monkeypatch.setitem(POLICY, "version", "changed")
    with pytest.raises(ValueError, match="policy changed"):
        load_artifact(c["script"], c["root"])
