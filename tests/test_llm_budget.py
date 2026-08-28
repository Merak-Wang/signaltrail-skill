from pathlib import Path

from daily_intelligence.llm_budget import append_budget_receipt, evaluate_llm_budget
from daily_intelligence.llm_usage import UsageLedger


def test_budget_keeps_unmetered_usage_unknown_and_nonblocking(tmp_path: Path):
    run = {"budget": {"max_agent_tokens": 10_000_000}}

    receipt = evaluate_llm_budget(run, tmp_path, "brief_wave")

    assert receipt["allowed"] is True
    assert receipt["coverage"] == "unmetered"
    assert receipt["observed_accounted_tokens"] is None
    assert receipt["projected_tokens"] is None


def test_budget_blocks_when_measured_usage_exceeds_phase_capacity(tmp_path: Path):
    ledger = UsageLedger(tmp_path)
    task = ledger.start_task("hermes", task_id="budget-task")
    ledger.ingest_hook(
        task,
        "hermes",
        {
            "hook_event_name": "post_api_request",
            "extra": {
                "api_request_id": "request-1",
                "usage": {
                    "input_tokens": 70,
                    "output_tokens": 20,
                    "total_tokens": 90,
                },
            },
        },
        phase="evaluation",
    )
    run = {
        "budget": {"max_agent_tokens": 80},
        "llm_usage": {"tasks": [{"task_id": task.task_id}]},
    }

    receipt = evaluate_llm_budget(run, tmp_path, "evaluation")
    append_budget_receipt(run, receipt)

    assert receipt["coverage"] == "complete"
    assert receipt["observed_accounted_tokens"] == 90
    assert receipt["allowed"] is False
    assert receipt["reason"] == "observed_plus_reserve_exceeds_max_agent_tokens"
    assert run["budget_exhausted"] is True
    assert run["llm_budget"]["latest"] == receipt
