local experiment_prompts_path = std.extVar("APPWORLD_EXPERIMENT_PROMPTS_PATH");
{
    "type": "simplified",
    "config": {
        "agent": {
            "type": "simplified_react_code_agent",
            "model_config": {
                "client_name": "litellm",
                "api_type": "chat_completions",
                "name": "bedrock/us.anthropic.claude-sonnet-4-6",
                "temperature": 0.0,
                "drop_reasoning_content": false,
                "cost_per_token": {
                    "input_cache_hit": 0.0000003,
                    "input_cache_miss": 0.000003,
                    "input_cache_write": 0.00000375,
                    "output": 0.000015
                },
                "retry_after_n_seconds": 15,
                "use_cache": false,
                "max_retries": 2
            },
            "appworld_config": {
                "random_seed": 100,
                "raise_on_extra_parameters": true
            },
            "logger_config": {"color": false, "verbose": true},
            "usage_tracker_config": {
                "max_cost_overall": 200,
                "max_cost_per_task": 1.8,
                "max_output_tokens_per_task": 80000
            },
            "prompt_file_path": experiment_prompts_path + "/react_code_agent/instructions.txt",
            "ignore_multiple_calls": true,
            "max_prompt_length": null,
            "max_output_length": null,
            "max_steps": 50,
            "log_lm_calls": true,
            "skip_if_finished": true
        },
        "dataset": "sosog_m14_60"
    },
    "metadata": {
        "model": {
            "file_name": "bedrock-sonnet-4-6",
            "humanized_name": "Claude Sonnet 4.6 on Bedrock",
            "precise_name": "bedrock/us.anthropic.claude-sonnet-4-6",
            "creator": "anthropic",
            "provider": "bedrock"
        },
        "agent": {
            "file_name": "simplified_react_code_agent",
            "humanized_name": "ReAct Code Agent"
        }
    }
}
