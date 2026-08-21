from scripts.export_appworld_research import observed_model_routes


def test_observed_model_routes_uses_positive_call_counters() -> None:
    usage = {
        "litellm.bedrock/us.anthropic.claude-sonnet-4-6.calls": 0,
        "litellm.bedrock/global.anthropic.claude-sonnet-4-6.calls": 8,
        "litellm.bedrock/global.anthropic.claude-sonnet-4-6.cost": 0.15,
    }

    assert observed_model_routes(usage) == [
        "bedrock/global.anthropic.claude-sonnet-4-6"
    ]
