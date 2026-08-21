import pytest

from research_ops.persistence import ResearchStore, StoreConfig


def test_safe_segment_accepts_identifiers():
    assert ResearchStore._safe_segment("m13-airline_20260821.1") == "m13-airline_20260821.1"


@pytest.mark.parametrize("value", ["", "../escape", "a/b", "spaces fail"])
def test_safe_segment_rejects_unsafe_paths(value):
    with pytest.raises(ValueError):
        ResearchStore._safe_segment(value)


def test_store_config_requires_bucket(monkeypatch):
    monkeypatch.delenv("SOSOG_ARTIFACT_BUCKET", raising=False)
    with pytest.raises(ValueError):
        StoreConfig.from_env()
