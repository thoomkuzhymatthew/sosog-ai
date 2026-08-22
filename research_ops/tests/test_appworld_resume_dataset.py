import pytest

from scripts.appworld_resume_dataset import select_resume_ids


def test_resume_expands_an_incomplete_scenario() -> None:
    task_ids = ["alpha_1", "alpha_2", "alpha_3", "beta_1", "beta_2", "beta_3"]
    completed = {"alpha_1", "beta_1", "beta_2", "beta_3"}

    assert select_resume_ids(task_ids, completed, 3) == [
        "alpha_1",
        "alpha_2",
        "alpha_3",
    ]


def test_resume_keeps_individual_smoke_tasks() -> None:
    task_ids = ["alpha_1", "beta_1"]

    assert select_resume_ids(task_ids, {"alpha_1"}, 1) == ["beta_1"]


def test_resume_rejects_partial_source_groups() -> None:
    with pytest.raises(ValueError, match="expected 3"):
        select_resume_ids(["alpha_1", "alpha_2"], set(), 3)
