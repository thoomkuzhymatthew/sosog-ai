# Failure Determinism Probe

Date: 2026-08-17

## Scope

This is a quick probe of the six M2 failed Retail tasks only. I did not start M3, did not change task configs, and did not attempt to fix failures.

Run setup:

```text
Run name: sosog_probe_m2_failed_5x_cached
Model: bedrock/us.anthropic.claude-sonnet-4-6
User simulator model: bedrock/us.anthropic.claude-sonnet-4-6
Tasks: 12, 49, 74, 82, 91, 98
Trials per task: 5
Concurrency/retries/timeout/logging: same as M2 baseline
Prompt caching: TAU2_BEDROCK_PROMPT_CACHE=1
```

## Headline

| Task | Pass/fail | Classification | First failed action-check stability |
| --- | --- | --- | --- |
| 12 | 5/5 | flaky-pass | differs/no failed runs |
| 49 | 1/5 | flaky-pass | same on failed runs |
| 74 | 2/5 | flaky-pass | differs/no failed runs |
| 82 | 3/5 | flaky-pass | same on failed runs |
| 91 | 0/5 | deterministic-fail | same on failed runs |
| 98 | 3/5 | flaky-pass | same on failed runs |

Interpretation: only task `91` was a deterministic fail in this 5x probe. The other five M2 failures passed at least once under the same setup, so they are `flaky-pass` by the requested taxonomy.

## Cost And Tokens

| Metric | Measured value |
| --- | --- |
| Total probe simulations | 30 |
| Total DB/pass successes | 14 |
| Total DB/pass failures | 16 |
| Cached benchmark total | $5.136135 |
| Cached avg/run | $0.171204 |
| Counterfactual uncached total | $9.864159 |
| Counterfactual uncached avg/run | $0.328805 |
| LLM calls | 580 |
| Prompt tokens | 2,985,493 |
| Completion tokens | 60,512 |
| Cache creation input tokens | 10,080 |
| Cache read input tokens | 1,753,920 |
| Non-cached input tokens | 1,221,493 |
| Cache write calls | 2 |
| Cache read calls | 348 |

Dollar values are calculated from measured response usage tokens using the same instrumentation/rates as M2. The uncached number is a counterfactual over the same measured prompt/completion token volume.

## Per-Task Details

### Task 12 - flaky-pass

Pass/fail count: 5/5 final DB/pass.

First failed action-check on failed runs: none, because all runs passed.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | pass | `none` | `none` |
| 1 | pass | `none` | `none` |
| 2 | pass | `none` | `none` |
| 3 | pass | `none` | `none` |
| 4 | pass | `none` | `none` |

### Task 49 - flaky-pass

Pass/fail count: 1/5 final DB/pass.

First failed action-check on failed runs: same signature, `calculate(expression=258.97 - 232.49)`.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | fail | `exchange_delivered_order_items(item_ids=[2757705742], new_item_ids=[8555936349], order_id=#W3470184, payment_method_id=gift_card_7245904)` | `8: calculate(expression=258.97 - 232.49)` |
| 1 | pass | `exchange_delivered_order_items(item_ids=[2757705742], new_item_ids=[1646531091], order_id=#W3470184, payment_method_id=gift_card_7245904)` | `7: get_product_details(product_id=9924732112)` |
| 2 | fail | `exchange_delivered_order_items(item_ids=[2757705742], new_item_ids=[8555936349], order_id=#W3470184, payment_method_id=gift_card_7245904)` | `8: calculate(expression=258.97 - 232.49)` |
| 3 | fail | `exchange_delivered_order_items(item_ids=[2757705742], new_item_ids=[8555936349], order_id=#W3470184, payment_method_id=gift_card_7245904)` | `8: calculate(expression=258.97 - 232.49)` |
| 4 | fail | `exchange_delivered_order_items(item_ids=[2757705742], new_item_ids=[8555936349], order_id=#W3470184, payment_method_id=gift_card_7245904)` | `8: calculate(expression=258.97 - 232.49)` |

### Task 74 - flaky-pass

Pass/fail count: 2/5 final DB/pass.

First failed action-check on failed runs: differs run-to-run.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | fail | `modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=paypal_5914760) -> cancel_pending_order(order_id=#W3189752, reason=no longer needed)` | `1: modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=credit_card_4466831)` |
| 1 | pass | `modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=credit_card_4466831) -> cancel_pending_order(order_id=#W3189752, reason=no longer needed)` | `none` |
| 2 | pass | `modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=credit_card_4466831) -> cancel_pending_order(order_id=#W3189752, reason=no longer needed)` | `none` |
| 3 | fail | `modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=credit_card_4466831)` | `0: cancel_pending_order(order_id=#W3189752, reason=no longer needed)` |
| 4 | fail | `modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=paypal_5914760) -> cancel_pending_order(order_id=#W3189752, reason=no longer needed)` | `1: modify_pending_order_items(item_ids=[3334537816], new_item_ids=[3265035808], order_id=#W5166363, payment_method_id=credit_card_4466831)` |

### Task 82 - flaky-pass

Pass/fail count: 3/5 final DB/pass.

First failed action-check on failed runs: same signature, `return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)`.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | pass | `return_delivered_order_items(item_ids=[9973034634,5952720925,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` | `0: return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` |
| 1 | pass | `return_delivered_order_items(item_ids=[9973034634,5952720925,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` | `0: return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` |
| 2 | pass | `return_delivered_order_items(item_ids=[9973034634,5952720925,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` | `0: return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` |
| 3 | fail | `return_delivered_order_items(item_ids=[6065192424], order_id=#W9571698, payment_method_id=credit_card_1565124) -> return_delivered_order_items(item_ids=[8551474201], order_id=#W3069600, payment_method_id=credit_card_1565124) -> return_delivered_order_items(item_ids=[6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` | `0: return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` |
| 4 | fail | `return_delivered_order_items(item_ids=[6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692) -> return_delivered_order_items(item_ids=[8551474201], order_id=#W3069600, payment_method_id=gift_card_7250692)` | `0: return_delivered_order_items(item_ids=[5952720925,9973034634,7381052709,6065192424], order_id=#W9571698, payment_method_id=gift_card_7250692)` |

### Task 91 - deterministic-fail

Pass/fail count: 0/5 final DB/pass.

First failed action-check on failed runs: same signature, `exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)`.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | fail | `return_delivered_order_items(item_ids=[4545791457,3098764622,1631806422], order_id=#W7553978, payment_method_id=credit_card_5902940) -> exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[9494281769], order_id=#W3239882, payment_method_id=credit_card_5902940)` | `1: exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)` |
| 1 | fail | `return_delivered_order_items(item_ids=[4545791457,3098764622,1631806422], order_id=#W7553978, payment_method_id=credit_card_5902940) -> exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[9494281769], order_id=#W3239882, payment_method_id=credit_card_5902940)` | `1: exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)` |
| 2 | fail | `return_delivered_order_items(item_ids=[4545791457,3098764622,1631806422], order_id=#W7553978, payment_method_id=credit_card_5902940) -> exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[9494281769], order_id=#W3239882, payment_method_id=credit_card_5902940)` | `1: exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)` |
| 3 | fail | `return_delivered_order_items(item_ids=[4545791457,3098764622,1631806422], order_id=#W7553978, payment_method_id=credit_card_5902940) -> exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[9494281769], order_id=#W3239882, payment_method_id=credit_card_5902940)` | `1: exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)` |
| 4 | fail | `return_delivered_order_items(item_ids=[4545791457,3098764622,1631806422], order_id=#W7553978, payment_method_id=credit_card_5902940) -> exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[9494281769], order_id=#W3239882, payment_method_id=credit_card_5902940)` | `1: exchange_delivered_order_items(item_ids=[9494281769], new_item_ids=[7609274509], order_id=#W3239882, payment_method_id=credit_card_5902940)` |

### Task 98 - flaky-pass

Pass/fail count: 3/5 final DB/pass.

First failed action-check on failed runs: same signature, `exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988)`.

| Trial | Result | Write-action skeleton | First failed action_check |
| --- | --- | --- | --- |
| 0 | fail | `exchange_delivered_order_items(item_ids=[7758198585,4068787148], new_item_ids=[5606522780,6245746168], order_id=#W3916020, payment_method_id=credit_card_3951670) -> exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_3951670) -> cancel_pending_order(order_id=#W8855135, reason=no longer needed)` | `0: exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988)` |
| 1 | pass | `exchange_delivered_order_items(item_ids=[7758198585,4068787148], new_item_ids=[5606522780,6245746168], order_id=#W3916020, payment_method_id=credit_card_8105988) -> exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988) -> cancel_pending_order(order_id=#W8855135, reason=no longer needed)` | `none` |
| 2 | pass | `exchange_delivered_order_items(item_ids=[7758198585,4068787148], new_item_ids=[5606522780,6245746168], order_id=#W3916020, payment_method_id=credit_card_8105988) -> exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988) -> cancel_pending_order(order_id=#W8855135, reason=no longer needed)` | `none` |
| 3 | pass | `exchange_delivered_order_items(item_ids=[7758198585,4068787148], new_item_ids=[5606522780,6245746168], order_id=#W3916020, payment_method_id=credit_card_8105988) -> exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988) -> cancel_pending_order(order_id=#W8855135, reason=no longer needed)` | `none` |
| 4 | fail | `exchange_delivered_order_items(item_ids=[7758198585,4068787148], new_item_ids=[5606522780,4572024853], order_id=#W3916020, payment_method_id=credit_card_3951670) -> cancel_pending_order(order_id=#W8855135, reason=no longer needed) -> exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_3951670)` | `0: exchange_delivered_order_items(item_ids=[5996159312], new_item_ids=[8363011723], order_id=#W4689314, payment_method_id=credit_card_8105988)` |

## Verification

The saved trajectories were re-evaluated with tau2's built-in verifier after the run.

```text
Computed rewards for 30 simulation(s)
Average Reward 0.4667
Pass^1 0.467
DB Match 14 / 16 (46.7%)
```

No Bedrock throttling, auth, or validation errors were found in the probe artifact logs.

## Artifacts

```text
sosog-ai/tau-bench/data/simulations/sosog_probe_m2_failed_5x_cached/results.json
sosog-ai/metrics/probe_failures_summary.json
sosog-ai/docs/probe_failures.md
```

## Reproduce

```bash
cd sosog-ai/tau-bench
set -a; source ../../.env; set +a
export AWS_DEFAULT_REGION=us-east-1
export TAU2_BEDROCK_PROMPT_CACHE=1
uv run tau2 run \
  --domain retail \
  --agent llm_agent \
  --agent-llm bedrock/us.anthropic.claude-sonnet-4-6 \
  --agent-llm-args '{"temperature": 0.0}' \
  --user user_simulator \
  --user-llm bedrock/us.anthropic.claude-sonnet-4-6 \
  --user-llm-args '{"temperature": 0.0}' \
  --num-trials 5 \
  --task-ids 12 49 74 82 91 98 \
  --max-concurrency 2 \
  --max-retries 1 \
  --retry-delay 5 \
  --timeout 900 \
  --save-to sosog_probe_m2_failed_5x_cached \
  --verbose-logs \
  --llm-log-mode all \
  --log-level INFO

uv run tau2 evaluate-trajs data/simulations/sosog_probe_m2_failed_5x_cached/results.json
cd ../..
python3 sosog-ai/scripts/analyze_probe_failures.py
```
