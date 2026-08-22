import json

from scripts.export_swe_research import selected_task_ids


def test_selected_task_ids_excludes_stale_submissions(tmp_path) -> None:
    allowed = tmp_path / "allowed.json"
    allowed.write_text(json.dumps(["selected-b", "selected-a"]))
    report = {
        "submitted_ids": ["stale", "selected-a", "selected-b", "selected-a"]
    }

    assert selected_task_ids(report, allowed) == ["selected-a", "selected-b"]
