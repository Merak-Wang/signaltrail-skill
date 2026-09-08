from pathlib import Path

import pytest

from daily_intelligence.storage import next_revision, write_immutable_json


def test_immutable_artifacts_and_revision_allocation(tmp_path: Path):
    directory = tmp_path / "indexes"
    first = directory / "morning-r1.json"
    write_immutable_json(first, {"revision": 1})

    assert next_revision(directory, "morning") == 2
    with pytest.raises(FileExistsError, match="immutable artifact"):
        write_immutable_json(first, {"revision": 2})
