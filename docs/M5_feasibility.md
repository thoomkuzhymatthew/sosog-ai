# M5 Feasibility - Retail Task Generalization Evidence

Date: 2026-08-18

Status: offline feasibility analysis only. No model calls, no new tau2 runs, no trace-to-script converter, no crystallized script, and no engine work.

## 1. Technical Summary

The existing tau2 Retail task set can support an M5 generalization proof. The 74 DB-checkable tasks contain repeated instances of the same procedure categories, with different users, order IDs, item IDs, replacement item IDs, addresses, reasons, and payment methods.

The largest broad family is `compound` at 29 tasks, but it is heterogeneous and should not be treated as one reusable procedure. The largest homogeneous exact write procedure is `exchange-delivered-items`, with 16 distinct task instances. Those 16 tasks share the same write procedure, `exchange_delivered_order_items(...)`, while varying the concrete inputs enough to test parameter extraction.

There is also a strong lower-risk path from M4: the single `return-delivered-items` procedure has 10 task instances, 9 of which are PROVISIONAL stable-pass-looking in the M3 partial data. That family is smaller than exchange but closer to the M4 proof script.

Conclusion: M5 does not require synthetic instance generation. We can test generalization inside the existing Retail tasks by training/deriving from one captured trace in a repeated procedure family and verifying on a different task instance from the same family.

## 2. Scope And Source Data

Working set:

```text
sosog-ai/config/retail_db_checkable_task_ids.json
```

Source task definitions:

```text
sosog-ai/tau-bench/data/tau2/domains/retail/tasks.json
```

Working-set size:

| Metric | Count |
| --- | ---: |
| Retail tasks total | 114 |
| DB-checkable working set | 74 |
| Excluded non-empty `nl_assertion` tasks | 40 |

Procedure grouping method:

- I used only the 74 locked DB-checkable task IDs from `kept_task_ids`.
- I grouped each task by the sequence of Retail write tools in `evaluation_criteria.actions`.
- Retail write tools were taken from `sosog-ai/tau-bench/src/tau2/domains/retail/tools.py`: `cancel_pending_order`, `exchange_delivered_order_items`, `modify_pending_order_address`, `modify_pending_order_items`, `modify_pending_order_payment`, `modify_user_address`, and `return_delivered_order_items`.
- Read tools were inspected separately to check whether repeated write procedures also have repeated full action-name shapes.

This is a task-definition analysis, not a trace-diff analysis. It does not attempt to infer parameters automatically.

## 3. Broad Category Counts

The broad view answers whether Retail contains repeated examples of the obvious procedure families.

| Broad category | Task count | Task IDs |
| --- | ---: | --- |
| Compound multi-write | 29 | `11`, `14`, `22`, `23`, `30`, `31`, `32`, `35`, `41`, `42`, `55`, `64`, `71`, `72`, `74`, `78`, `81`, `86`, `87`, `91`, `92`, `96`, `97`, `98`, `99`, `100`, `101`, `102`, `112` |
| Single exchange-delivered-items | 16 | `0`, `1`, `6`, `7`, `8`, `9`, `18`, `27`, `49`, `52`, `58`, `75`, `77`, `80`, `93`, `94` |
| Single return-delivered-items | 10 | `5`, `13`, `26`, `48`, `51`, `53`, `73`, `82`, `83`, `84` |
| No-write / no DB change | 6 | `10`, `12`, `25`, `50`, `57`, `65` |
| Single modify-pending-items | 6 | `15`, `20`, `56`, `61`, `79`, `85` |
| Single cancel | 4 | `66`, `69`, `88`, `90` |
| Single modify-order-address | 2 | `17`, `34` |
| Single modify-user-address | 1 | `33` |

Interpretation: yes, there are multiple examples of return, exchange, cancel, modify-address, and modify-items workflows. The dataset is not one instance per category.

## 4. Exact Procedure Shapes

The exact write-procedure view is the better M5 planning unit because a parameterized deterministic script needs a stable call sequence.

| Exact write procedure | Count | Task IDs |
| --- | ---: | --- |
| `exchange-delivered-items` | 16 | `0`, `1`, `6`, `7`, `8`, `9`, `18`, `27`, `49`, `52`, `58`, `75`, `77`, `80`, `93`, `94` |
| `return-delivered-items` | 10 | `5`, `13`, `26`, `48`, `51`, `53`, `73`, `82`, `83`, `84` |
| `no-write/no-db-change` | 6 | `10`, `12`, `25`, `50`, `57`, `65` |
| `modify-pending-items` | 6 | `15`, `20`, `56`, `61`, `79`, `85` |
| `cancel` | 4 | `66`, `69`, `88`, `90` |
| `modify-order-address -> modify-pending-items` | 4 | `71`, `72`, `96`, `97` |
| `return-delivered-items -> return-delivered-items` | 3 | `11`, `14`, `92` |
| `modify-order-address` | 2 | `17`, `34` |
| `modify-order-address -> modify-order-address -> modify-user-address -> modify-pending-items` | 2 | `41`, `42` |
| `modify-user-address -> modify-order-address -> modify-user-address` | 1 | `22` |
| `exchange-delivered-items -> exchange-delivered-items -> modify-pending-items` | 1 | `23` |
| `return-delivered-items -> cancel -> return-delivered-items` | 1 | `30` |
| `cancel -> return-delivered-items` | 1 | `31` |
| `cancel -> cancel -> return-delivered-items` | 1 | `32` |
| `modify-user-address` | 1 | `33` |
| `return-delivered-items -> modify-pending-items` | 1 | `35` |
| `cancel -> cancel -> return-delivered-items -> return-delivered-items` | 1 | `55` |
| `exchange-delivered-items -> modify-pending-items` | 1 | `64` |
| `cancel -> modify-pending-items` | 1 | `74` |
| `modify-order-address -> modify-pending-items -> cancel` | 1 | `78` |
| `cancel -> cancel` | 1 | `81` |
| `modify-pending-items -> modify-user-address` | 1 | `86` |
| `modify-order-address -> modify-order-address -> modify-order-address -> modify-user-address` | 1 | `87` |
| `return-delivered-items -> exchange-delivered-items` | 1 | `91` |
| `exchange-delivered-items -> exchange-delivered-items -> cancel` | 1 | `98` |
| `exchange-delivered-items -> exchange-delivered-items` | 1 | `99` |
| `modify-pending-items -> return-delivered-items` | 1 | `100` |
| `modify-order-address -> modify-pending-items -> modify-pending-items` | 1 | `101` |
| `modify-order-address -> modify-pending-items -> exchange-delivered-items` | 1 | `102` |
| `modify-pending-items -> modify-order-address -> modify-pending-items` | 1 | `112` |

Interpretation: M5 should target one of the repeated exact procedure shapes, not the broad compound bucket. Good candidates are `exchange-delivered-items`, `return-delivered-items`, `modify-pending-items`, `cancel`, or `modify-order-address -> modify-pending-items`.

## 5. Largest Homogeneous Category: Exchange

`exchange-delivered-items` is the largest exact procedure with 16 instances. All 16 share the same mutating tool call shape:

```text
exchange_delivered_order_items(order_id, item_ids, new_item_ids, payment_method_id)
```

The concrete inputs vary materially:

| Input field | Distinct values across 16 exchange tasks |
| --- | ---: |
| Customer lookup pattern | 8 |
| Explicit `user_id` values or direct-order cases | 7 |
| Write `order_id` values | 12 |
| `item_ids` sets | 13 |
| `new_item_ids` sets | 15 |
| `payment_method_id` values | 11 |

Example variation inside the same procedure:

| Task | Customer / lookup | Write order | Old item IDs | New item IDs | Payment |
| --- | --- | --- | --- | --- | --- |
| `1` | Yusuf Rossi, zip `19122` | `#W2378156` | `["4983901480"]` | `["7747408585"]` | `credit_card_9513926` |
| `6` | Mei Kovacs, zip `28236` | `#W6390527` | `["8384507844"]` | `["7453605304"]` | `paypal_7644869` |
| `8` | Mei Kovacs, zip `28236` | `#W6390527` | `["8384507844"]` | `["9083642334"]` | `paypal_7644869` |
| `52` | Sofia Li, zip `78260` | `#W4689314` | `["5996159312"]` | `["9228757377"]` | `paypal_8194385` |
| `58` | Ivan Hernandez, zip `92133` | `#W5838674` | `["7441167885", "3478699712"]` | `["3815173328", "6017636844"]` | `gift_card_9368765` |
| `80` | Direct order task | `#W7209932` | `["5047954489"]` | `["9354168549"]` | `gift_card_2611937` |

This is exactly the kind of structure M5 needs: the procedure is the same, while constants differ enough to test whether a derived parameterized script separates operation shape from instance-specific values.

The full read/action paths vary within the exchange category:

| Full action-name shape within exchange | Count | Task IDs |
| --- | ---: | --- |
| `find_user_id_by_name_zip -> get_user_details -> get_order_details -> get_product_details -> get_product_details -> exchange_delivered_order_items` | 5 | `6`, `7`, `8`, `9`, `58` |
| `exchange_delivered_order_items` | 5 | `75`, `77`, `80`, `93`, `94` |
| `find_user_id_by_name_zip -> get_order_details -> get_product_details -> get_product_details -> exchange_delivered_order_items` | 2 | `0`, `1` |
| `find_user_id_by_name_zip -> get_user_details -> get_order_details -> get_product_details -> exchange_delivered_order_items` | 2 | `18`, `52` |
| Other exchange full paths | 2 | `27`, `49` |

Interpretation: exchange is feasible for M5, but the cleanest test should pick two tasks from the same full action-name subgroup if we want to minimize read-path confounds. The `6`, `7`, `8`, `9`, `58` subgroup is the best candidate pool because it has five tasks with the same full action-name sequence and varying parameters.

## 6. Return Category: Closest To M4

The M4 proof used task `5`, a single `return_delivered_order_items` workflow. The Retail set has 10 single-return tasks:

```text
5, 13, 26, 48, 51, 53, 73, 82, 83, 84
```

Their write inputs also vary:

| Input field | Distinct values across 10 single-return tasks |
| --- | ---: |
| Customer lookup pattern | 6 |
| Explicit `user_id` values or direct-order cases | 6 |
| Write `order_id` values | 8 |
| `item_ids` sets | 9 |
| `payment_method_id` values | 7 |

M3 partial status for these tasks:

| Task | M3 partial status |
| --- | --- |
| `5` | PROVISIONAL stable-pass-looking |
| `13` | PROVISIONAL stable-pass-looking |
| `26` | PROVISIONAL stable-pass-looking |
| `48` | PROVISIONAL stable-pass-looking |
| `51` | PROVISIONAL stable-pass-looking |
| `53` | PROVISIONAL stable-pass-looking |
| `73` | PROVISIONAL stable-pass-looking |
| `82` | PROVISIONAL flaky-looking |
| `83` | PROVISIONAL stable-pass-looking |
| `84` | PROVISIONAL stable-pass-looking |

Interpretation: return is also feasible and probably the easiest conceptual continuation from M4. However, task `5`'s exact full read/action path is not broadly repeated in the task definitions. If M5 wants the narrowest possible generalization proof, it can either:

- stay in the return family and generalize the essential write procedure to another single-return stable task, or
- switch to exchange and choose two tasks from a repeated full action-name subgroup.

## 7. Feasibility Decision

M5 can be tested within the existing tau2 Retail tasks. Synthetic variations are not required.

Best M5 paths:

| Path | Why it works | Main caveat |
| --- | --- | --- |
| Return-family M5 from M4 | Closest to the existing proof; 10 single-return tasks; 9 are provisionally stable-pass-looking. | Task `5`'s exact full read path is mostly unique, so the proof should define procedure shape around the return workflow rather than the whole M4 read trace. |
| Exchange-family M5 | Largest homogeneous exact procedure; 16 instances; strong input variability; repeated full action-name subgroups exist. | Slightly more complex than return because some tasks exchange multiple items and read-path patterns vary. |
| Direct-action subgroup | Some task groups have full action shape equal to just the write call, e.g. exchange tasks `75`, `77`, `80`, `93`, `94` and return tasks `73`, `82`, `83`, `84`. | These may be less representative of the original conversational agent workflow because the task gives enough direct identifiers to skip lookup/read discovery. |

Recommendation for M5 when approved: use existing tasks, pick one repeated exact procedure family, and hold out a different task from the same family as the generalization target. Do not synthesize task variations unless the desired M5 claim becomes stricter than "same Retail procedure category with different constants."

## 8. Limitations And Further Questions

This report uses task-definition golden actions and M3 partial status only. It does not analyze every captured trace for each task, does not infer parameters, and does not test any generated or parameterized script.

Open decision before M5:

- Should M5 extend M4's return workflow specifically, or choose the larger exchange family for a stronger repeated-instance proof?
- Should "same procedure shape" mean the same write-call sequence only, or the same full read-plus-write action-name sequence?
- Should M5 require the source and target tasks to both be PROVISIONAL stable-pass-looking now, or wait until M3 finishes N=10 before choosing the final pair?

My technical read: the data is sufficient now to design an M5 feasibility proof, but the cleanest final task pair should be selected after M3 completes if we want the M5 claim to inherit the final stable-pass classification rather than the current provisional one.
