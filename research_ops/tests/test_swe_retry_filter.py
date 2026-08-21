import json
import sys

from scripts import swe_retry_filter


def test_retry_filter_limits_cleanup_to_selected_ids(tmp_path, monkeypatch) -> None:
    output = tmp_path / "output"
    selected = output / "selected"
    unrelated = output / "unrelated"
    selected.mkdir(parents=True)
    unrelated.mkdir()
    retryable = {
        "info": {
            "exit_status": "error",
            "exception_str": "RateLimitError: Too many tokens per day",
        },
        "messages": [],
    }
    (selected / "selected.traj.json").write_text(
        json.dumps({"instance_id": "selected", **retryable})
    )
    (unrelated / "unrelated.traj.json").write_text(
        json.dumps({"instance_id": "unrelated", **retryable})
    )
    (output / "preds.json").write_text(
        json.dumps({"selected": {"model_patch": ""}, "unrelated": {"model_patch": ""}})
    )
    allowed = tmp_path / "allowed.json"
    allowed.write_text(json.dumps(["selected"]))
    retry_ids = tmp_path / "retry.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "swe_retry_filter.py",
            str(output),
            "--ids-output",
            str(retry_ids),
            "--only-ids",
            str(allowed),
        ],
    )

    swe_retry_filter.main()

    assert json.loads(retry_ids.read_text()) == ["selected"]
    assert json.loads((output / "preds.json").read_text()) == {
        "unrelated": {"model_patch": ""}
    }
