"""Small report fixtures shared by integration tests."""

import json
from pathlib import Path

from daily_intelligence.utils import write_json


def load_sample_report(root: Path) -> dict:
    return json.loads((root / "examples" / "sample_report.json").read_text(encoding="utf-8"))


def first_report_item(report: dict) -> dict:
    return next(item for section in report["sections"] for item in section["items"])


def write_report_index(report: dict, path: Path) -> Path:
    section = next(section for section in report["sections"] if section["items"])
    event = section["items"][0]
    ref = event["source_refs"][0]
    source = event["primary_source"]
    payload = {
        "schema_version": "1.1",
        "index_id": "index-test",
        "date": report["date"],
        "edition": report["edition"],
        "revision": 1,
        "generated_at": report["generated_at"],
        "timezone": "Asia/Shanghai",
        "sources": [],
        "items": [
            {
                "item_id": ref["item_id"],
                "source_id": source["id"],
                "source_name": source["name"],
                "title": ref["title"],
                "url": ref["url"],
                "canonical_url": ref["url"],
                "discovered_at": report["generated_at"],
                "module": section["module"],
                "category": section["category"],
                "published_at": f"{report['date']}T01:00:00+08:00",
            }
        ],
    }
    return write_json(path, payload)
