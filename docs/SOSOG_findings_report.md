# SOSOG Technical Findings Report

Date: 2026-08-19

Audience: investor, design partner, or collaborator evaluating whether to engage.

## Technical Summary

SOSOG is an engine concept for capturing AI-agent traces on repetitive workflows, identifying the traces that are stable, and crystallizing those stable paths into deterministic scripts that run at approximately zero model tokens. The agent remains available as a safety-net fallback for ambiguous, novel, or unstable cases. The thesis is simple: reason once, then reuse cheaply where the evidence says reuse is safe.

The strongest measured result is from M3: on the 74 DB-checkable Retail tasks in the local tau-bench setup, 54 tasks met the promotion bar of at least 9/10 DB passes with an identical passing write-action skeleton. The same M3 run found 19 flaky or unstable tasks and 1 stable-fail task. Across all 740 M3 simulations, the aggregate DB-pass rate was 669/740, or 90.4054%. The 54 promotable tasks accounted for $7.423410 of the measured $11.030292 M2 cached baseline cost, or 67.3% of that specific 74-task benchmark baseline. This is not a universal savings claim; it is the measured share of the filtered tau-bench Retail baseline that landed in the promotable bucket. Sources: `docs/M3.md`, `metrics/m3_final_summary.json`, `docs/M2.md`, and `metrics/m2_baseline_summary.json`.

The safety story is mixed but encouraging. The first cheap-parser pipeline in M5.5 showed the dangerous failure mode: 2/18 messy return requests produced confident wrong writes. M6 added a deterministic validation gate and converted those wrong writes to 0, but over-deferred 2 previously clean cases. M7 refined the gate and recovered those 2 cases: on the same 18-request set it handled 10/18 deterministically, deferred 8/18, kept wrong writes at 0, and deferred 3/3 synthetic dangerous cases. Sources: `docs/M5_5.md`, `metrics/m5_5_nl_boundary_results.json`, `docs/M6.md`, `metrics/m6_validation_gate_results.json`, `docs/M7.md`, and `metrics/m7_gate_precision_results.json`.

The automation story is also partial, not complete. M8 generated a cancel-family task environment for a family that had not been hand-built before. The executor was fully derived; the schema gate and consistency-safety gate were derived plus human-reviewed. The generated cancel environment passed 5/5 ladder runs, deferred 3/3 adversarial cases, made 0 model calls, and produced 0 wrong writes. The best honest interpretation from M8 is that SOSOG is not yet a fully self-scaling platform; it looks like an automated core with a human safety-review step per task family. Sources: `docs/M8.md`, `docs/M8_recipe.md`, and `metrics/m8_automation_results.json`.

## Why This Problem, And Why Tau-Bench Retail

The waste SOSOG targets is repeated reasoning. In M1, a single stock Retail task run consumed 71,134 total tokens and cost an ESTIMATED $0.231330. In M2, the full filtered Retail baseline used 1,392 LLM calls and cost $11.030292 with prompt caching enabled; the counterfactual uncached cost on the same measured token volume was $22.444386. The point is not that these exact dollar amounts are large in a benchmark. The point is that the same agent keeps re-deriving the same policies, entity lookups, and action sequences even when the task shape recurs. Sources: `docs/M1.md`, `docs/M2.md`, and `metrics/m2_baseline_summary.json`.

Tau-bench Retail was useful because it provides a ready-made task environment, tools, simulated users, and a built-in verifier. One important correction: it did not provide the SOSOG traces; SOSOG generated those traces by running the stock agent. The reason Retail was still the right test bed is that it provides a programmatic DB verifier for a substantial subset of tasks, which makes agreement checking free of an LLM judge. M2 filtered the 114 Retail tasks down to 74 DB-checkable tasks by excluding the 40 tasks with non-empty `nl_assertions`. Those 40 were left in the upstream task file but kept out of scope for this project phase. Sources: `docs/M1.md`, `docs/M2.md`, and `config/retail_db_checkable_task_ids.json`.

The baseline denominator is therefore narrow and explicit: 74 DB-checkable tau-bench Retail tasks, stock `llm_agent`, stock `user_simulator`, Claude Sonnet 4.6 on Bedrock on-demand, temperature 0, prompt caching enabled, and pass/fail measured by the programmatic DB verifier. M2 passed 68/74 tasks, for a 91.8919% pass rate, at $11.030292 cached benchmark cost, or $0.149058 average cached cost per task. Source: `docs/M2.md`.

## What Was Tested

M0 established the execution route. Bedrock batch inference was tested and abandoned because both the global and regional Sonnet 4.6 profiles failed before returning a `jobArn` with the same account-level `ValidationException`. The project then pivoted to on-demand Bedrock inference. A single `InvokeModel` call to `us.anthropic.claude-sonnet-4-6` returned `SOSOG M0 OK` with 18 input tokens, 10 output tokens, and ESTIMATED cost of $0.000204. Source: `docs/M0.md`.

M1 installed the maintained tau2 codebase locally under `sosog-ai/tau-bench`, package version 1.0.1 at commit `c3398666e6559e3a063da3fc04b5acf7f941464e`. It proved that one Retail task could run end to end with the stock agent and stock user simulator on `bedrock/us.anthropic.claude-sonnet-4-6`, and that the built-in evaluator returned reward `1.0` with `db_match=true`. Source: `docs/M1.md`.

M2 created the baseline. It filtered to the 74 DB-checkable tasks, enabled Bedrock prompt caching on the stable policy/system prefix without changing prompt text, ran the full set once, and exported traces. The baseline result was 68/74 DB passes and 6 failures: tasks `12`, `49`, `74`, `82`, `91`, and `98`. Cached benchmark cost was $11.030292. Prompt caching was behavior-neutral in intent: it changed the price path, not the prompt content, tool schemas, or generation parameters. Source: `docs/M2.md`.

M3 asked the key crystallization question at scale: which tasks remain stable over repeated runs? The final M3 corpus reached the full requested N=10: 740 valid behavioral simulations, 0 infrastructure errors, 74 tasks at N=10. It stayed model-pure: 493 simulations used `us.anthropic.claude-sonnet-4-6`, 247 used `global.anthropic.claude-sonnet-4-6`, and no other model IDs appeared in saved metadata. Both profiles were verified as Claude Sonnet 4.6 before use. The run cost $107.064918 for the full corpus, and total M3 benchmark spend including the dry run was $115.187481 against the $500 cap. Source: `docs/M3.md` and `metrics/m3_final_summary.json`.

One source discrepancy is worth calling out. The prompt for this report requested "55/57 held" for provisional retention, but the final M3 report and final metrics JSON say 54/57 provisional stable-pass tasks held the high DB-pass bar of at least 9/10, 52/57 also kept identical skeletons, 5/57 dropped from promotable status, and 2 non-provisional tasks became promotable. This report uses the sourced M3 values rather than the unsourced 55/57 figure.

## The Crystallization Mechanic Worked On One Task

M4 proved the core mechanic in the smallest possible form. Task `5` was selected because it was stable-looking in the partial M3 data, had passed 10/10 in the M3 dry run, and its passing write skeleton was a single call to `return_delivered_order_items`. A hand-authored Python script replayed the captured tool sequence through the tau2 Retail environment and then ran the built-in programmatic verifier. The script made 0 model calls, used 0 tokens, cost $0.000000, and passed with verifier reward `1.0`, `db_match=true`, and `db_reward=1.0`. Source: `docs/M4.md`.

The important honesty point is that M4 did not fake the DB state. It called Retail tools in sequence, including the real write call `return_delivered_order_items(order_id="#W6390527", item_ids=["8538875209"], payment_method_id="paypal_7644869")`. It was also hardcoded to a single task instance. The measured M2 benchmark baseline for task `5` was 114,951 total benchmark tokens and $0.1913814 cached cost. For that exact task instance, the deterministic script replaced that with 0 tokens and $0.000000. Source: `docs/M4.md` and `metrics/m2_per_task_costs.csv`.

M5 then tested whether this was just replay or actual generalization. The return-family script derived from task `5` passed held-out return tasks `13` and `48` with hand-fed parameters, then passed those same held-out tasks when it received only structured task-level intent and resolved order IDs, item IDs, and payment method through read tools. The exchange-family repeat used task `6` as source and task `8` as holdout; hand-fed and self-resolved exchange both passed. All M5 verifier checks used `EvaluationType.ENV`, all reported reward `1.0` and `db_match=true`, and all made 0 model calls. Source: `docs/M5.md`.

The boundary after M5 was not deterministic execution. For selected structured intents, deterministic execution and input resolution worked. The remaining unknown was the layer above it: raw human language into structured intent.

## The Natural-Language Boundary Was Useful But Unsafe Without A Gate

M5.5 tested that boundary with Claude Haiku, not Sonnet. The setup used 6 return tasks (`5`, `13`, `48`, `51`, `53`, `73`) and 18 messy requests: 3 phrasings per task, including deliberately ambiguous language. Haiku made 18 parser calls; Sonnet made 0 calls; the deterministic script made 0 model calls. The parser plus deterministic executor produced 10 clean passes out of 18, 6 correct deferrals out of 18, and 2 parse failures out of 18. Both parse failures led to wrong writes. Parser cost was $0.025973 total, or $0.001443 average per request. Source: `docs/M5_5.md` and `metrics/m5_5_nl_boundary_results.json`.

That result is informative because it separates two kinds of failure. Haiku correctly deferred all 6 deliberately ambiguous requests, which is the safe failure mode. But it also produced 2 confident wrong writes: `48_b`, where both return and keep lists were populated and the executor returned an extra item, and `73_a`, where "coffee machine" was mapped to the wrong catalog product. A cheap parser is promising only if confident wrong writes are caught before the deterministic executor acts. Source: `docs/M5_5.md`.

M6 added that validation layer without changing the parser or the executor. Replaying the exact saved M5.5 Haiku outputs, the gate reduced wrong writes from 2 to 0 and converted both danger cases to deferrals. The blunt version handled 8/18 deterministically, deferred 10/18, and over-deferred 2 of the 10 M5.5 clean passes. It made 0 new model calls and executed no write on any deferred case. Source: `docs/M6.md` and `metrics/m6_validation_gate_results.json`.

M7 refined the gate with an order-aware equivalence normalizer. On the same 18 saved parser outputs, it recovered the 2 harmless over-defers while keeping wrong writes at 0. Final M7 outcomes were 10 clean passes, 8 correct deferrals, 0 wrong writes, and 0 over-defers. The three focal checks held: `48_b` still deferred, `13_b` recovered to clean pass, and `73_b` recovered to clean pass. The adversarial gate-only checks deferred 3/3 dangerous synthetic cases with 0 writes and 0 model calls. Source: `docs/M7.md` and `metrics/m7_gate_precision_results.json`.

The cost comparison for M7 is useful but must stay labeled. The live measured cheap-layer cost was the reused M5.5 Haiku parse cost of $0.025973 plus $0.000000 gate/executor token cost. The end-to-end fallback economics are ESTIMATED because Sonnet was not actually run on the rewritten messy tickets: the report estimates a tiered M7 path at $0.675660 against an all-Sonnet agent-only baseline of $1.590372 for the 18 request slots, or 57.5% ESTIMATED savings in that specific return-ticket test. On the benchmark-total framing, M7 estimates $0.828687 versus $1.962252, or 57.8% ESTIMATED savings. Source: `docs/M7.md` and `metrics/m7_gate_precision_results.json`.

## Automation Reached The Executor, But Not Fully The Safety Review

M8 tested whether a task environment could be generated for a family that had not already been hand-built. The target was `cancel`, with training tasks `66` and `88` and held-out tasks `69` and `90`. The recipe was written first in `docs/M8_recipe.md`, then applied to the target family. That order matters: otherwise the result would risk being reverse-engineered from the answer. Source: `docs/M8.md` and `docs/M8_recipe.md`.

The generated cancel environment passed the held-out ladder: 5/5 ladder runs passed the programmatic DB verifier with reward `1.0` and `db_match=true`. The adversarial checks also passed: 3/3 dangerous cases deferred before any write, with 0 wrong writes and 0 model calls. Source: `docs/M8.md` and `metrics/m8_automation_results.json`.

But the component classification is the actual M8 finding. The executor was fully derived from aligned traces: one write skeleton, `cancel_pending_order(order_id, reason)`. The schema gate was "Derived + human-reviewed"; lookup and reason fields were mechanically available, but the supported self-resolution selector needed human review. The consistency-safety gate was also "Derived + human-reviewed"; ownership, pending status, and exactly-one-candidate checks came from tool docs, traces, and pre-write state, but confirming them as the right safety boundary was a human safety-review step. Source: `docs/M8.md`.

The honest interpretation is not "fully automated platform." It is closer to "automated core plus human safety review per family." That is still product-shaped if the review burden is small, but it is not yet proof of a self-serve platform.

## The Assistance Tier Was Marginal And Behavior-Perturbing

M10 tested a lower tier for unpromoted tasks: leave Sonnet as the decision-maker, but assist it with trace-derived scaffolding and pre-resolved read-only context. The target was a flaky compound pending-order modification cluster: tasks `41`, `71`, `78`, and `97`. Promotion was unsafe because the cluster had DB failures and multiple passing write skeletons. Source: `docs/M10.md`.

The measured same-seed comparison covered 12 raw M3 partial runs and 12 assisted M10 runs. Raw passed 9/12; assisted passed 10/12. Cached benchmark cost fell from $1.939581 to $1.786394, a 7.8979% reduction. Agent calls fell from 137 to 125, and in-trajectory read tool calls fell from 69 to 44. But total tokens rose from 1,171,051 to 1,374,350, a 17.3604% increase, because the assistance packet added prompt tokens and prompt caching made part of that larger prompt cheaper. Source: `docs/M10.md` and `metrics/m10_assistance_results.json`.

M10 preserved the most important safety sanity check: no writes were pre-executed, all prefetch calls were read-only, no deterministic write script was used, and the agent made every trajectory write decision. But it did not prove assistance is harmless. There were 2 same-seed regressions, and the bias test on task `71` was not clean: assisted passed 2/3, the same count as raw, but one assisted run failed after honoring the simulated user's final wording while the DB verifier expected the address change. The best reading is that assistance did not act like a hard rail, but it can perturb borderline decisions. Source: `docs/M10.md`.

For now, value concentrates in promotion. Assistance produced a modest cached-dollar reduction in this specific 12-run compound-task comparison, while Type 1 promotion eliminates runtime agent tokens for tasks that clear the stability and safety bar.

## What The Project Proves, And What It Does Not

The project proves the mechanism works in this controlled setting. A stable agent trace can be turned into a deterministic script, run with 0 model calls, and pass the same programmatic verifier as the agent. The mechanism generalized from one hardcoded return instance to selected held-out return and exchange instances using structured intents. The safety gate converted the observed confident wrong writes to deferrals and survived a small adversarial check. The full M3 corpus found that 54/74 DB-checkable Retail tasks met the strict N=10 promotion criterion. Within the measured M2 74-task cached baseline, those promotable tasks accounted for $7.423410 of $11.030292, or 67.3% of cost.

It also proves that the product is not "just use a smaller model." The Haiku parse layer was cheap and useful, but by itself it produced 2 wrong writes in 18 requests. The deterministic gate, not the model, made the tiered path safe on the tested return set. That distinction matters for any production design: the cheap model can interpret, but deterministic validation decides whether execution is safe.

It does not prove transfer to real customer traffic. Tau-bench Retail is a clean environment with simulated users, known tools, synthetic task definitions, and a programmatic verifier. It does not contain the messiness of production integrations, incomplete CRM/order data, adversarial customers, policy drift, human-agent handoff constraints, or compliance requirements. It also does not prove correctness beyond agreement with the tau-bench verifier and the baseline agent. Crystallization optimizes for repeatable agreement with validated traces; if the agent or verifier is wrong, a deterministic script can faithfully preserve that wrong behavior.

It does not prove full automation on hard families. M8 used `cancel`, a relatively simple one-write family. Return and exchange were hand-built earlier. The evidence says executor derivation can automate, and gate drafts can automate, but human safety review was still needed for the generated gates. Harder multi-write families may require substantially more review.

It does not prove production-grade unattended promotion. N=10 was enough to expose instability and establish a useful benchmark signal, but unattended production promotion would likely want more runs, broader input variation, regression tests, drift monitoring, and demotion criteria. The M3 promotion bar is an experimental filter, not a production certification standard.

## Prior Art

SOSOG is not a novel discovery in the abstract. It is a general, framework-agnostic implementation of a pattern that Arun Malik calls "Progressive Crystallization" in a 2026 Microsoft Azure Networking paper. That paper frames agent exploration as a discovery phase that can promote repeated, validated behavior into deterministic workflows, with the agent still available for novel cases. It reports production evidence from cloud network operations: deterministic execution grew from 0% to 45% over eight months, per-incident agent cost fell by more than 70% while incident volume roughly doubled, and the promotion criteria include human review of deterministic logic. Source: [Progressive Crystallization: Turning Agent Exploration into Deterministic, Lower-Cost Workflows in Production](https://arxiv.org/abs/2607.07052).

The useful positioning is therefore not "we discovered crystallization." It is: SOSOG is testing whether that lifecycle can be made more general across task environments, with trace capture, stability classification, deterministic execution, validation gates, and fallback routing as reusable product primitives.

## Honest Limitations

The benchmark scope is narrow. All substantive results are from tau-bench Retail, scoped to 74 DB-checkable tasks. The 40 Retail tasks with non-empty `nl_assertions` were explicitly excluded because they require an LLM judge in the installed upstream evaluator. This made the agreement metric free and programmatic, but narrowed the task universe. Source: `docs/M2.md`.

Some savings are measured and some are ESTIMATED. The measured M2 baseline cost is $11.030292. The measured M3 full-run cost is $107.064918, with total M3 benchmark spend of $115.187481 including the dry run. The M4 one-task replacement from $0.1913814 to $0.000000 is measured for task `5`. The M7 end-to-end fallback savings of 57.5% agent-only and 57.8% benchmark-total are ESTIMATED because the Sonnet fallback was not actually run on the rewritten messy requests. Sources: `docs/M2.md`, `docs/M3.md`, `docs/M4.md`, and `docs/M7.md`.

Crystallization inherits mistakes. A deterministic script that reproduces a stable trace is only as good as the trace and verifier used to promote it. M2 already showed that action diagnostics can disagree with DB pass/fail, and M10 exposed a case where a simulated user's final wording conflicted with what the DB verifier expected. Source: `docs/M2.md` and `docs/M10.md`.

The method pays off only when tasks recur. If a deployment is dominated by one-off tasks or policy exceptions, the agent remains the main workhorse and SOSOG has less to amortize. The M3 result is promising precisely because many Retail task shapes repeated enough to produce stable skeletons.

## Future Work, Untested

**Task decomposition is untested.** Some flaky tasks may contain stable sub-sequences even when the whole task cannot promote. Splitting workflows into deterministic read/validation/write sub-steps and leaving only the unstable step with the agent could rescue part of the workload that M3 classed as flaky. This was not built or measured.

**Exemplar lifting is untested.** Feeding a flaky task its own successful traces might raise consistency enough to become promotable. That would be a reliability experiment, not just a cost experiment. It is only likely to help inconsistency-type failures; on genuinely ambiguous tasks it could overfit the verifier or bias the agent into unsafe behavior. This was not run.

**Real-world validation is the critical next test.** A design partner should provide a small, permissioned workflow with real historical tickets, real tool calls, and a business-owned verifier or acceptance test. The first design-partner study should measure recurrence, stability, safety deferral rate, review burden per family, and cost on that partner's actual traffic. None of the current tau-bench results prove customer adoption, willingness to pay, or integration effort.

## Direction

The north star is an engine that predicts the minimum intelligence a task requires and routes accordingly: deterministic script when a task is proven stable and gated, cheap parser plus deterministic executor when language understanding is the only uncertain layer, and full agent when the task is novel, ambiguous, or unsafe to crystallize. The compounding asset is not just scripts; it is a timestamped, task-shape-indexed dataset of crystallization outcomes showing which workflows promoted, which deferred, which regressed, and why.

That is the decision-relevant finding from this project. SOSOG has evidence of a real mechanism, a real safety boundary, and a partially automatable construction path. It does not yet have evidence that the approach transfers cleanly to production data or fully automates safety gates. A good next engagement is therefore not a broad platform rollout. It is a focused design-partner pilot on one high-recurrence workflow family, with explicit promotion criteria, deterministic gates, fallback routing, and measured review burden.

## Source Inventory

Local source reports and artifacts used for this report:

- `docs/M0.md`
- `docs/M1.md`
- `docs/M2.md`
- `docs/M3.md`
- `docs/M4.md`
- `docs/M5.md`
- `docs/M5_5.md`
- `docs/M6.md`
- `docs/M7.md`
- `docs/M8.md`
- `docs/M8_recipe.md`
- `docs/M10.md`
- `docs/M5_feasibility.md`
- `metrics/m2_baseline_summary.json`
- `metrics/m2_per_task_costs.csv`
- `metrics/m3_final_summary.json`
- `metrics/m5_5_nl_boundary_results.json`
- `metrics/m6_validation_gate_results.json`
- `metrics/m7_gate_precision_results.json`
- `metrics/m8_automation_results.json`
- `metrics/m10_assistance_results.json`

External source used only for prior-art context:

- Arun Malik, "Progressive Crystallization: Turning Agent Exploration into Deterministic, Lower-Cost Workflows in Production," arXiv:2607.07052, 2026: https://arxiv.org/abs/2607.07052
