# M3 Flaky Task Analysis

Date: 2026-08-20

Status: offline corpus analysis only. No model calls, no new tau2 runs, no task or verifier changes. Stopped for review.

## Executive Summary

- **The 19 flaky tasks trap $3.406223 of the M2 cached baseline**, or 30.9% of the full $11.030292 baseline.
- **Potentially recoverable via follow-up work:** $2.694845, or 79.1% of the flaky bucket. This is split between $1.225408 in M11-style decomposition candidates and $1.469438 in M13-style lift candidates.
- **Genuinely stuck or unsafe to rescue:** $0.711377, or 20.9% of the flaky bucket. These are mostly verifier/user-simulator artifacts where forcing the expected DB state would train against a reasonable user branch.
- **No hard-fail tasks are inside the 19-task flaky bucket.** The only M3 `<=2/10` stable-fail task was task `91`, which is outside this analysis set.

I used M3's final summary for pass rates, distinct passing skeleton counts, and M2 costs, then inspected actual `messages[*].tool_calls` and user/assistant turns in `traces/m3/retail_db_checkable_n10_final_valid.jsonl` for the cause labels. I treated `reward_info.action_checks` as verifier/checklist evidence, not the actual executed call sequence.

## Route Precedence

Some tasks are both agent-wandered and stable-prefix/volatile-tail. For routing, I used the route that best matches the next useful experiment:

- **Leave on agent** when the failing branch is a genuine ambiguity or simulator/verifier artifact. These are flagged even when the early read prefix is stable, because forcing the tail would game the verifier.
- **Decompose (M11 candidate)** when the task already reaches valid DB states but misses promotion because late write order, redundant writes, or tail sequencing is volatile. The prefix is the reusable part.
- **Lift (M13 candidate)** when there is a single correct DB target and failures are wrong SKU, wrong payment method, missed write, or policy misunderstanding. Many have stable early reads, but the main opportunity is raising whole-task accuracy.
- **Drop** only for hard-fail tasks (`<=2/10` pass). None of the 19 qualify.

## Task Table

| Task ID | Pass rate | # passing skeletons | Failure-cause category | Recommended route | M2 baseline cost |
| --- | ---: | ---: | --- | --- | ---: |
| `0` | 7/10 | 1 | Genuine ambiguity + stable-prefix/volatile-tail | Leave on agent | $0.147604 |
| `1` | 8/10 | 1 | Genuine ambiguity + stable-prefix/volatile-tail | Leave on agent | $0.147832 |
| `12` | 9/10 | 2 | Genuine ambiguity / verifier artifact + stable-prefix/volatile-tail | Leave on agent | $0.112782 |
| `18` | 4/10 | 1 | Genuine ambiguity / user-simulator artifact + stable-prefix/volatile-tail | Leave on agent | $0.137900 |
| `30` | 10/10 | 2 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.339687 |
| `41` | 3/10 | 2 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.209657 |
| `49` | 4/10 | 1 | Agent-wandered | Lift (M13 candidate) | $0.167902 |
| `74` | 3/10 | 1 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.289736 |
| `78` | 10/10 | 2 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.218135 |
| `79` | 6/10 | 1 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.147953 |
| `82` | 3/10 | 1 | Genuine ambiguity / user-simulator artifact + stable-prefix/volatile-tail | Leave on agent | $0.165259 |
| `87` | 10/10 | 2 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.150929 |
| `94` | 8/10 | 1 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.137741 |
| `96` | 7/10 | 1 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.158819 |
| `97` | 10/10 | 2 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.106171 |
| `98` | 7/10 | 2 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.181713 |
| `99` | 6/10 | 1 | Agent-wandered + stable-prefix/volatile-tail | Lift (M13 candidate) | $0.175917 |
| `100` | 10/10 | 3 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.171306 |
| `112` | 10/10 | 2 | Stable-prefix / volatile-tail | Decompose (M11 candidate) | $0.239180 |

## Route Counts And Cost

| Route | Tasks | Count | M2 baseline cost | Share of flaky cost |
| --- | --- | ---: | ---: | ---: |
| Decompose (M11 candidate) | `30`, `78`, `87`, `97`, `100`, `112` | 6 | $1.225408 | 36.0% |
| Lift (M13 candidate) | `41`, `49`, `74`, `79`, `94`, `96`, `98`, `99` | 8 | $1.469438 | 43.1% |
| Leave on agent | `0`, `1`, `12`, `18`, `82` | 5 | $0.711377 | 20.9% |
| Drop | none | 0 | $0.000000 | 0.0% |
| **Total flaky bucket** | 19 tasks | 19 | **$3.406223** | **100.0%** |

**Headline:** M11 plus M13 targets cover $2.694845 of the $3.406223 flaky bucket. That is meaningful enough to justify follow-up, but the shape matters: M11 is mainly about reclaiming deterministic prefixes from already-successful volatile-tail tasks, while M13 is the accuracy play for single-correct tasks. The $0.711377 leave-on-agent slice should not be "fixed" by exemplar nudging because the failures are often reasonable branches that the verifier does not accept.

## Classification Notes

| Task ID | Evidence from final JSONL |
| --- | --- |
| `0` | All runs share the same auth/order/product lookup prefix. Failures happen when the simulator/agent treats Google Home as not equivalent to Google Assistant and proceeds with only the keyboard or only the thermostat. The expected DB assumes the Google Assistant thermostat is acceptable. Artifact/ambiguity. |
| `1` | Same Google Home vs Google Assistant issue as task `0`. The two failed runs end with no write because the simulated user declines both exchanges after the agent says no exact Google Home thermostat exists. Artifact/ambiguity. |
| `12` | The stable prefix finds Mia and reads both orders. Expected behavior is human transfer after PayPal refund is rejected. The lone DB failure occurs when the simulated user eventually accepts the Visa refund and the agent processes it. That follows the conversation but violates the fixed task expectation. Artifact. |
| `18` | Failures exchange the broken chair for the exact same chair after the user confirms that path. Passing runs occur when the simulator asks for the gray fixed-armrest chair. Since the exact same chair is actually available, the expected gray-chair branch depends on simulator behavior, not a clean single correct outcome. Artifact. |
| `30` | All runs pass DB. The two passing skeletons differ by a late redundant exchange-same-item attempt before the tablet return. The read/discovery work and final required effects are stable enough for prefix decomposition. |
| `41` | The agent consistently identifies the user, two orders, and puzzle product, but failures omit one or more required address writes or apply only the user address plus item modification. Single correct target; lift is appropriate. |
| `49` | Correct target is the cheapest wireless earbud from the rest of the same order. Failures query the full product catalog and choose a cheaper available IPX4 variant not from the order. This is a real selection error. |
| `74` | Failures use the original PayPal instead of the requested credit card for the pending laptop modification, miss the pending-order cancellation, or drift into returning the delivered five-item order. Single intended outcome; lift. |
| `78` | All runs pass DB. The only promotion blocker is late write-order variance: address -> item -> cancel in 9 runs versus address -> cancel -> item in 1 run. Good M11 decomposition candidate. |
| `79` | The agent finds the right customer/orders/product, but failures select a black 1000ml bottle from the catalog instead of the red 1000ml replacement implied by the user's other 1L bottle. Single correct target; lift. |
| `82` | Expected DB is return all items on the more expensive tablet order to gift card. Failed runs follow simulator drift into returning both tablet orders, or only the tablet, after the user asks for that. Artifact/ambiguity. |
| `87` | All runs pass DB. The only skeleton difference is whether `modify_user_address` happens before or after the three pending-order address writes. Prefix and final state are stable. |
| `94` | Failures choose the closest same-color laptop variant with 32GB RAM after the agent overconstrains color. The task's fixed target is the i7/8GB/1TB item. Real agent selection error; lift. |
| `96` | Failures update only the address because the agent says the Bluetooth speaker cannot be exchanged until delivery. The policy allows pending item modification, and passing runs do that. Real policy/procedure error; lift. |
| `97` | All runs pass DB. The two skeletons are the same address and item writes in opposite order. This is a clean volatile-tail decomposition case. |
| `98` | Failures include wrong payment card, missing the camera exchange, or skipping the puzzle after misreading "1000 more pieces" as "1000 pieces." Single correct multi-write outcome; lift. |
| `99` | Failures mostly use the original Mastercard instead of the user's preferred Visa for exchange refunds, or cancel the skateboard order despite the task saying the user will handle that themselves if item-level cancel is impossible. Single target; lift. |
| `100` | All runs pass DB. Skeletons differ by redundant hiking-boot return attempts or an extra payment-method modification, while the expected final DB state is still reached. Decompose stable prefix and leave tail guarded. |
| `112` | All runs pass DB. The volatile part is only the order of the watch item modification versus laptop item/address writes. Stable decomposition candidate. |

## Artifact Flags

These should not be "fixed" by teaching the agent to force the verifier's branch:

- `0` and `1`: Google Home vs Google Assistant compatibility is under-specified; the simulator sometimes reasonably refuses the expected thermostat exchange.
- `12`: the simulator can abandon the "ask for human" instruction and accept the Visa refund, which the verifier scores wrong.
- `18`: the simulator sometimes confirms exchanging for the exact same available chair even though the expected DB wants the gray fixed-armrest variant.
- `82`: the simulator sometimes asks to return both tablet orders or only one tablet after learning more order details; the verifier expects all items in one specific order only.

## Sources

- M3 final task buckets, pass rates, skeleton counts, and costs: `docs/M3.md`, `metrics/m3_final_summary.json`
- M2 per-task baseline costs: `metrics/m2_per_task_costs.csv`
- Final M3 traces inspected: `traces/m3/retail_db_checkable_n10_final_valid.jsonl`
- Task specs and Retail policy used to interpret ambiguity: `tau-bench/data/tau2/domains/retail/tasks.json`, `tau-bench/data/tau2/domains/retail/policy.md`
