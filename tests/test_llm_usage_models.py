from __future__ import annotations

import json
from pathlib import Path

import pytest

from daily_intelligence.llm_usage import TokenRelation, TokenUsage, UsageLedger, exact
from daily_intelligence.llm_usage.models import (
    CostMeasurement,
    Measurement,
    ObservationQuality,
    safe_label,
    validate_id,
)


def test_inconsistent_reported_zero_falls_back_to_known_non_overlapping_tokens():
    usage = TokenUsage(
        input=exact(10, "test"),
        output=exact(5, "test"),
        reported_total=exact(0, "test"),
        cached_input_relation=TokenRelation.SUBSET,
        cache_write_input_relation=TokenRelation.SUBSET,
    )

    total = usage.accounted_total()

    assert total.value == 15
    assert total.quality == "exact"
    assert total.method == "inconsistent_reported_total_fallback_v1"


def test_secret_shaped_labels_and_timestamps_are_not_persisted(tmp_path: Path):
    secret = "sk-proj-DEADBEEF123456"
    assert safe_label(secret) is None
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="secret-fields")

    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "post_api_request",
            "provider": secret,
            "completed_at": secret,
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        },
    )

    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (task.path / "events").glob("*.json")
    )
    assert secret not in persisted


def test_unobservable_metadata_rejects_free_text_and_partial_cost_values():
    with pytest.raises(ValueError, match="bounded safe reason"):
        Measurement(
            None,
            ObservationQuality.UNOBSERVABLE,
            "not_exposed",
            reason="raw provider error contains private text",
        )
    with pytest.raises(ValueError, match="currency=None"):
        CostMeasurement(
            None,
            "USD",
            ObservationQuality.UNOBSERVABLE,
            "not_exposed",
            reason="host_cost_not_exposed",
        )
    with pytest.raises(ValueError, match="bounded safe label"):
        CostMeasurement(
            "1.00",
            "USD",
            ObservationQuality.EXACT,
            "provider",
            method="raw private billing note",
        )


@pytest.mark.parametrize("value", ["CON", "nul.json", "task."])
def test_usage_ids_reject_windows_reserved_or_ambiguous_names(value: str):
    with pytest.raises(ValueError):
        validate_id(value, "task_id")


def test_hermes_api_duration_is_recorded_in_milliseconds(tmp_path: Path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="hermes-latency")

    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "post_api_request",
            "extra": {
                "api_request_id": "request-1",
                "api_duration": 1.25,
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            },
        },
    )

    observation = ledger.summarize_task(task)["observations"][0]
    assert observation["latency"]["wall_ms"]["value"] == 1250


def test_partial_latency_coverage_does_not_become_an_exact_subtotal(tmp_path: Path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="partial-latency")
    for request_id, duration in (("request-1", 1.0), ("request-2", None)):
        extra = {
            "api_request_id": request_id,
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }
        if duration is not None:
            extra["api_duration"] = duration
        ledger.ingest_hook(
            task,
            "hermes",
            {"hook_event_name": "post_api_request", "extra": extra},
        )

    wall = ledger.summarize_task(task)["latency_ms"]["wall_ms"]
    assert wall == {
        "value": None,
        "quality": "unobservable",
        "reason": "one_or_more_observations_unobservable",
        "known_value": 1000,
        "unobservable_observations": 1,
    }


def test_hermes_pre_hook_keeps_host_input_estimate_without_claiming_total(
    tmp_path: Path,
):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="pre-estimate")
    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "pre_api_request",
            "api_request_id": "request-1",
            "approx_input_tokens": 123,
        },
    )

    summary = ledger.summarize_task(task)

    assert summary["tokens"]["input"]["value"] == 123
    assert summary["tokens"]["input"]["quality"] == "estimated"
    assert summary["tokens"]["accounted_total"]["value"] is None


def test_official_hermes_pre_and_post_hooks_share_top_level_request_identity(
    tmp_path: Path,
):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="official-hook-correlation")
    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "pre_api_request",
            "api_request_id": "request-1",
            "approx_input_tokens": 123,
        },
    )
    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "post_api_request",
            "api_request_id": "request-1",
            "usage": {"input_tokens": 120, "output_tokens": 5, "total_tokens": 125},
        },
    )

    summary = ledger.summarize_task(task)

    assert summary["raw_observation_count"] == 2
    assert summary["observation_count"] == 1
    assert summary["covered_call_count"]["value"] == 1
    assert summary["tokens"]["reported_total"]["value"] == 125


def test_hermes_request_identity_is_namespaced_by_session(tmp_path: Path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="session-scoped-hooks")
    for session_id in ("parent-session", "child-session"):
        ledger.ingest_hook(
            task,
            "hermes",
            {
                "hook_event_name": "post_api_request",
                "api_request_id": "request-1",
                "session_id": session_id,
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            },
        )

    summary = ledger.summarize_task(task)

    assert summary["observation_count"] == 2
    assert summary["covered_call_count"]["value"] == 2
    assert len({row["session_id_hash"] for row in summary["observations"]}) == 2


def test_hermes_nested_usage_rows_use_token_content_in_identity(tmp_path: Path):
    ledger = UsageLedger(tmp_path / "data")
    task = ledger.start_task("hermes", task_id="nested-usage")
    paths = []
    for position, total in enumerate((3, 7), start=1):
        receipt = tmp_path / f"receipt-{position}.json"
        receipt.write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "usage": {
                                "input_tokens": total - 1,
                                "output_tokens": 1,
                                "total_tokens": total,
                            }
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        paths.extend(ledger.import_usage_file(task, "hermes", receipt))

    assert len(paths) == 2
    summary = ledger.summarize_task(task)
    assert summary["observation_count"] == 2
    assert summary["tokens"]["reported_total"]["value"] == 10
