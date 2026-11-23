"""核对全分、对称扣分与缺测分值区间。"""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_edition import host_measurement, joint_score  # noqa: E402


def main() -> None:
    """用已知标准答案的整期数据覆盖三种计量边界。"""
    host = {
        "scope": "full", "responses": 2,
        "model_effort_response_counts": [
            {"model": "gpt-6.1-terra", "effort": "low", "responses": 2}],
        "wall_seconds": {"absolute_distance_to_target": 0, "ceiling": 1800},
        "total_tokens": {"absolute_distance_to_target": 0, "ceiling": 20_000_000},
    }
    editorial = {
        "brief_accuracy_concision": {"scores_out_of_10": {
            "title": 10, "tldr": 10, "visible_publication_time": 10}},
        "image_clarity_relevance": {"scores_out_of_10": dict.fromkeys((
            "image_richness", "image_relevance", "desktop_readability", "mobile_readability",
            "writing_concision", "writing_liveliness", "writing_directness"), 10)},
    }
    device = {"scope": "edition", "cpu_percent_normalized": {"mean": 100},
              "gpu_busy_percent": {"mean": 100}}
    sources = {"configured_enabled": 40, "enabled_with_output": 40}
    assert joint_score(host, sources, editorial, device, True)["points"] == 100
    assisted = joint_score(host, sources, editorial, device, True, assisted_recovery=True)
    assert assisted["points"] == 95
    assert assisted["components"]["low_model_independence"]["points"] == 5
    host["total_tokens"]["absolute_distance_to_target"] = 2_000_000
    sources["enabled_with_output"] -= 4
    assert joint_score(host, sources, editorial, device, True)["points"] == 97
    host["scope"] = "partial"
    partial = joint_score(host, sources, editorial, device, True)
    assert partial["points"] is None and partial["possible_points"] == [58.5, 98.5]
    run = {"created_at": "2026-11-18T01:01:00+00:00", "updated_at": "2026-11-18T01:02:00+00:00"}
    receipt = {
        "start_utc": run["created_at"], "end_utc": run["updated_at"], "wall_seconds": 60,
        "run_sha256": "run", "scope": "selected_window", "selection": "subtree",
        "total": {"input_tokens": 100, "cached_input_tokens": 75,
                  "output_tokens": 30, "total_tokens": 999},
    }
    args = Namespace(host_receipt=Path("receipt"), expected_host_subtree_id=None,
                     full_host_measurement=True, max_wall_seconds=1800, max_tokens=20_000_000)
    with patch("evaluate_edition.json_with_digest", return_value=(receipt, "receipt-sha256")):
        observed = host_measurement(args, run, "run", True, "report")
        assert observed["scope"] == "partial" and observed["total_tokens"]["observed"] == 130
        receipt.update(scope="completed_turn", selection="completed_invocation")
        assert host_measurement(args, run, "run", True, "report")["scope"] == "full"
    print("Edition scoring cases passed")


if __name__ == "__main__":
    main()
