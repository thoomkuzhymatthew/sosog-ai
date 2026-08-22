# Vertical Investigation Progress Update

Date: 2026-08-22

Snapshot time: approximately 10:42 UTC

Audience: founder, technical collaborator, design partner, or investor evaluating what the current investigation says about product and GTM direction.

## Executive verdict

The investigation is **promising enough to continue, but not yet sufficient to claim a production savings rate or a finished prediction engine**.

The strongest new signal is not simply that the agents sometimes succeed. It is that outcomes and costs differ systematically by task:

- In Airline, the one-run baseline result predicted the outcome of subsequent valid runs **87.9%** of the time.
- In SWE Verified, the corresponding same-task prediction rate is **94.1%** across tasks with a valid baseline result.
- Failed valid runs cost **1.79 times** successful runs in Airline and **2.28 times** successful runs in SWE Verified.
- Failed outcomes consumed **28.6%** of valid Airline corpus cost and **38.2%** of valid SWE corpus cost.
- Five SWE tasks that failed on every valid repetition consumed **31.7%** of all valid SWE corpus cost through the first three trials.

This supports the central premise that an outcome-aware system could identify materially different execution classes: reliably successful, reliably unsuccessful, and genuinely variable. It also supports an initial audit product that attributes spend to successful, failed, retried, and escalated work.

However, these are repeated executions of known benchmark tasks. They prove within-task repeatability, not that SOSOG can predict the correct route for a previously unseen customer task. The cheaper-model probes, final cross-vertical labels, and held-out M17 evaluation are not complete. No new vertical has yet produced a measured customer-like percentage saving.

The current commercial verdict is therefore **yellow-green**:

- Green enough to begin design-partner outreach now.
- Green enough to finish the remaining lean, high-information experiments.
- Not green enough to sell an autonomous optimizer or advertise a universal savings percentage.
- Not a reason to return to the original exhaustive $5,500 benchmark plan.

## Current track status

| Track | Current state | Usable result | Main limitation |
| --- | --- | --- | --- |
| M13 Airline | Repaired; safely paused on daily quota; automatic resume at 00:05 UTC | Full 50-task baseline and 224 valid repeated executions across all 50 tasks | 276 of 500 planned corpus rows remain infrastructure/quota errors; only missing eligible rows will be retried |
| M14 AppWorld | Repaired; safely paused on daily quota; automatic resume at 00:15 UTC | Valid five-task smoke test, nine baseline task markers, and a 5/5 golden replay | Behavioral evidence remains too small; the repaired resume selected 54 tasks in complete scenario groups |
| M15 SWE Verified | Repaired; safely paused on daily quota; automatic resume at 00:30 UTC | Filtered 30-task baseline, three corpus trials, and a 3/3 golden replay | Trial 2 still has one error; trials 3–4 and the Haiku probe remain |
| M16 WebArena | Harness repaired; 3/3 golden replay; paid run remains gated; EC2 stopped | Five sites prepared and 40 tasks selected without paid inference | No browser-agent model result exists until a paid-inference budget is explicitly approved |

M17 remains frozen. It should not be presented as a cross-vertical prediction engine until the retained tracks are complete or formally dropped and an immutable snapshot is evaluated.

## Repair and resume update

The morning audit found four distinct checkpoint or harness faults. All four are now repaired in repository release `8e24c3c01cda402ca6ef2ef33c02f64072bdbdc1`, pushed to `main`, packaged in S3, and deployed to the relevant instances.

- **Airline:** the runner now recovers the original run stamp, skips completed smoke and baseline phases, retries only eligible missing corpus rows, and refuses to write a completion marker while errors remain.
- **AppWorld:** resume selection is now scenario-aware. If any member of a three-task scenario is missing, the complete triplet is supplied to AppWorld. The live repair passed its 5/5 golden replay and selected 54 tasks covering the 48 missing task IDs before AWS returned the daily quota limit.
- **SWE Verified:** exports are restricted to the immutable 30-task selection; summary files containing errors no longer count as complete; retries target only incomplete IDs. The live repair passed its 3/3 golden replay and correctly narrowed the contaminated baseline directory to the seven incomplete selected tasks rather than rerunning 500 tasks.
- **WebArena:** the pinned verifier now works with the installed OpenAI/LiteLLM stack. The golden replay passed 3/3, 40 tasks were selected, artifacts were synced to S3, and the instance stopped at the paid-inference gate.

The quota-limited retries were stopped once AWS returned `Too many tokens per day`; continuing them could not produce evidence and would only consume EC2 time. No false completion marker was left behind. Airline, AppWorld, and SWE remain on running instances because their local systemd timers cannot wake a stopped EC2 instance. Their benchmark services are parked, their checkpoints are preserved, and their next automatic attempts are staggered at 00:05, 00:15, and 00:30 UTC on 2026-08-23. WebArena is stopped and will make no paid model calls without explicit budget approval.

Verification completed before deployment:

- Shell syntax checks passed for all repaired runners.
- `PYTHONPATH=. pytest -q research_ops/tests predictor/tests` passed: 28 tests plus 5 subtests.
- The WebArena compatibility patch was applied and replayed idempotently against the pinned upstream revision.
- The deployed instances reproduced the intended checkpoint filters and golden-verifier results.

## M13 Airline

### Measured result

The clean baseline completed all 50 selected tasks:

- Passes: **42/50 (84.0%)**
- Recorded cost: **$7.116698**
- Mean cost per task: **$0.1423**

The N=10 corpus attempted 500 executions. Daily token limits and fallback exhaustion produced 276 infrastructure-error rows. Those rows should not be treated as behavioral failures.

Among the 224 valid executions:

- Passes: **183/224 (81.7%)**
- Recorded cost: **$33.049606**
- Mean cost: **$0.1475**
- Median cost: **$0.1185**
- 90th-percentile cost: **$0.2622**
- Maximum cost: **$0.7162**
- Top 10% of valid runs by cost consumed **27.1%** of valid corpus cost

The exported summary reports 36.6% because it divides 183 passes by all 500 planned rows. That number is operationally accurate for the interrupted run but is not the model's behavioral pass rate. The correct behavioral estimate from completed rows is 81.7%.

### Repeatability signal

Every task has four or five valid corpus repetitions:

- **36/50** tasks passed every valid repetition.
- **3/50** failed every valid repetition.
- **11/50** produced mixed outcomes.
- The baseline pass/fail label matched **197/224 (87.9%)** subsequent valid outcomes.

This is useful cross-vertical evidence that a substantial part of a structured support workload can be separated into stable and unstable task classes. It does not yet prove that the stable Airline paths are safe to compile. Promotion still requires an audited action-skeleton and state-change analysis, not pass rate alone.

### Cost-by-outcome signal

- Successful valid run mean: **$0.1290**
- Failed valid run mean: **$0.2305**
- Failed/successful cost ratio: **1.79x**
- Cost consumed by failed valid runs: **$9.450886**, or **28.6%** of valid corpus cost

This is commercially relevant: the expensive tail is not merely a few long successful conversations. Failure itself is associated with more inference. A production audit should therefore measure cost per verified resolution and cost per escalation, not average tokens per ticket.

### Interpretation

Airline strengthens the earlier Retail evidence that structured, tool-using support and operations workflows are a credible initial market. Absolute benchmark cost is not directly transferable to a customer because tau2 also pays for a model-based simulated user. The important transferable evidence is recurrence, outcome stability, state-based verification, and more expensive failures.

## M14 AppWorld

### Measured result

The valid five-task smoke test produced:

- Passes: **2/5 (40%)**
- Recorded cost: **$0.929577**
- Mean cost: **$0.1859**
- Calls: 8–10 per task
- All five tasks used the global Sonnet 4.6 fallback after the regional quota interruption

Nine baseline task markers were subsequently completed:

- Calls recorded: **86**
- Marker-reported cost: **$1.667895**
- No baseline pass rate is available because the phase did not reach evaluation

The overnight resume did not consume another meaningful task batch. It generated a dataset containing only missing individual tasks, but AppWorld's reader requires all three task variants for each scenario. That defect is now repaired: the live resume generated complete scenario triplets and reached inference, where it paused on the AWS daily token limit.

### Interpretation

Five tasks are too few to judge the back-office/enterprise-app vertical. The 40% smoke result is neither a rejection nor an endorsement. It does show that these tasks can require multiple expensive steps, but there is no repeated-outcome or cheaper-route evidence yet.

The failure is also a product lesson. Production integrations will have resumability, state, grouping, and partial-completion constraints. The initial consultancy/FDE model is appropriate because robust integration work is material rather than incidental.

## M15 SWE Verified

### Data-quality correction

The latest `baseline_t0_all` export contains 55 rows because it reused an output directory containing 25 trajectories from the earlier broad run. The lean selection contains exactly 30 task IDs. All baseline figures below are recomputed by filtering the export to those 30 IDs.

The filtered baseline has:

- 30 selected tasks
- 23 complete evaluations and 7 quota/error rows
- 20 passes
- **66.7%** pass rate against all selected tasks
- **87.0%** pass rate among completed evaluations
- **$8.517759** recorded cost including partial/error trajectories

### Corpus result through trial 2

| Trial | Complete rows | Errors | Passes | Behavioral pass rate | Recorded cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 30 | 0 | 23 | 76.7% | $15.125592 |
| 1 | 30 | 0 | 24 | 80.0% | $12.229513 |
| 2 | 29 | 1 | 23 | 79.3% of valid rows | $13.931104 |
| **Combined** | **89** | **1** | **70** | **78.7% of valid rows** | **$41.286209** |

Trial 3 has no completed summary and will resume after the quota reset. Trial 4 and the five-task Haiku probe remain pending.

### Repeatability signal

Across the first three corpus trials:

- **22/30** tasks passed every valid repetition.
- **5/30** failed every valid repetition.
- **3/30** produced mixed outcomes.
- Therefore **27/30 (90%)** currently have stable observed outcomes.
- For the 23 tasks with a valid filtered baseline, the baseline label matched **64/68 (94.1%)** subsequent valid outcomes.

This is a strong within-task signal. It suggests that repeated software-engineering work contains persistent easy, hard, and variable classes. It does not prove generalization to a new repository or issue description; M17 must earn that through held-out feature-based prediction.

### Cost-by-outcome signal

Across the 89 valid corpus executions:

- Successful mean cost: **$0.3521**
- Failed mean cost: **$0.8011**
- Failed/successful cost ratio: **2.28x**
- Median cost: **$0.2591**
- 90th-percentile cost: **$1.0709**
- Maximum cost: **$2.322938**
- Top 10% of runs consumed **35.4%** of valid corpus cost
- Failed outcomes consumed **$15.221143**, or **38.2%** of valid corpus cost

The five always-failing tasks consumed **$12.641831**, or **31.7%** of all valid corpus cost. This does not mean that all of that cost is immediately avoidable: the customer may still require a solution, and an early abort without an alternative would reduce task completion. It does mean that predicting failure early, switching strategy, or escalating directly has meaningful economic potential.

### Interpretation

Coding is the strongest new evidence for the prediction/routing layer because tests provide a precise outcome verifier and the cost of failure is concentrated. It is less direct evidence for deterministic trace compilation than Retail or Airline. A coding-agent design partner would therefore test a slightly different initial wedge: predicting expensive failure, choosing model/agent depth, and escalating or changing strategy earlier.

## M16 WebArena

The expensive setup work and harness repair completed:

- Site status is `ready`.
- Shopping, shopping-admin, forum, GitLab, and Wikipedia containers were verified during setup.
- The paid-inference approval file is absent, so no paid WebArena model run was authorized or executed.
- The repaired golden replay passed all three verifier cases and selected 40 benchmark tasks.

The original runner failed because installing the current LiteLLM stack upgraded the OpenAI package while the pinned WebArena verifier imported the removed `openai.error` module. The compatibility repair now supports the installed exception interface and reaches the approval gate. Consequently:

- A 3/3 golden replay and the 40-task selection were written and synced to S3.
- No smoke or baseline tasks ran.
- No WebArena model conclusion is possible.
- The EC2 instance is stopped, so idle browser infrastructure is no longer accruing instance time.

The infrastructure blocker is resolved. The remaining blocker is an intentional commercial decision: browser agents remain unranked by our own measurements until paid inference is explicitly approved.

## Spend position

The current vertical artifacts account for at least **$99.80** of recorded model usage:

- Airline smoke, baseline, and corpus: **$40.878280**
- AppWorld smoke and preserved partial baseline markers: **$2.597472**
- SWE accumulated baseline trajectories and corpus trials 0–2: **$56.322115**
- WebArena paid inference: **$0**

This is a lower bound rather than an AWS invoice. It excludes the in-progress SWE trial, any failed request not represented in final trajectory cost, EC2, EBS, S3, and RDS. Exact billed cost remains unavailable to this IAM user because it lacks Cost Explorer access.

Airline, AppWorld, and SWE are quota-paused with staggered automatic-resume timers; their EC2 instances must remain running for those local timers to fire. WebArena is stopped at the paid-inference gate. Persisted artifacts and release archives are also synced to S3.

## Commercial implications

### 1. The best initial promise is an audit, not autonomous routing

The evidence supports this offer:

> We connect model spend to verified task outcomes, identify stable, variable, and consistently failing workload classes, and shadow-test cheaper or safer execution policies.

It does not yet support:

> We will automatically reduce every agent bill by a fixed percentage.

The audit can already produce defensible ledgers for successful-task cost, failed-task cost, retry cost, escalation cost, model mix, and task-class concentration. Cash savings should still be separated from economic savings when credits or committed-spend discounts apply.

### 2. Structured support and transactional operations remain the best beachhead

Retail has the strongest completed mechanism evidence: 54/74 tasks met the strict M3 promotion bar, deterministic execution was demonstrated at zero model calls, and the filtered benchmark placed 67.3% of baseline cost in the promotable bucket. Airline now adds cross-domain evidence of substantial repeated-outcome stability.

The best initial targets are therefore likely AI-native support, voice, BPO, travel, retail, fintech, and vertical-SaaS vendors whose agents take structured actions. The platform vendor is often a better prospect than one conventional enterprise because it owns the inference bill, has high volume, and exposes many downstream workflows.

### 3. Coding agents are the strongest adjacent opportunity

SWE Verified currently has the clearest expensive-failure signal. Coding-agent vendors, automated remediation products, and agentic developer-tool companies have exact verifiers and direct inference COGS. They may value failure prediction and adaptive effort even before deterministic compilation is available.

This market is technically sophisticated and may already build internal routing, so SOSOG would need to demonstrate superior outcome attribution or prediction rather than generic token dashboards.

### 4. Back-office and browser-agent targeting should remain provisional

AppWorld has only five evaluated tasks. WebArena has none. These categories should stay on the GTM research list, but our current evidence should not be used to rank them above support/operations or coding.

### 5. The benchmark results sharpen the ideal customer profile

Prioritize companies with:

- Direct model or inference cost, ideally £25k–£250k+ per month
- Repeated task families rather than mostly one-off prompts
- A programmatic or business-owned success signal
- Material failed, retried, or escalated task volume
- Existing trace and cost telemetry
- Near-term credit exhaustion or actual cash inference spend
- A buyer who owns AI gross margin, reliability, or infrastructure

The most important new discovery question is:

> What percentage of your inference bill is spent on tasks that ultimately fail, retry, or escalate—and can you identify those tasks before the spend occurs?

## What is and is not proven

### Supported so far

- Repeated structured agent tasks can have stable outcome classes.
- Task-level cost is concentrated rather than uniform.
- Failed agent executions can cost materially more than successful ones.
- Programmatic outcome attribution is possible in support/transaction and coding environments.
- The earlier Retail crystallization mechanism is not obviously isolated from all other verticals.
- A productized audit can generate commercially useful information before the prediction engine is complete.

### Not supported yet

- A universal customer savings percentage
- Prediction on previously unseen customer tasks
- Safe cheaper-model routing across the new verticals
- A cross-vertical M17 result
- Production transfer without integration and safety-review work
- AppWorld or WebArena commercial attractiveness based on our own runs
- A fully self-serve product with negligible forward-deployed engineering

## Recommended decisions

1. **Continue the lean investigation.** The Airline and SWE signals justify finishing the remaining high-information work, not restoring exhaustive benchmark scope.
2. **Allow SWE to finish trials 3–4 and the Haiku probe**, then freeze and audit the 30-task corpus.
3. **Let the repaired Airline, AppWorld, and SWE timers make their staggered post-reset attempts.** Checkpoint filters now prevent broad reruns; stop any track whose residual evidence has low marginal value.
4. **Keep AppWorld bounded after its successful harness repair.** Its structured back-office workflows are commercially relevant, but the next run must earn its place through usable evaluated rows.
5. **Keep WebArena paid inference paused.** Site preparation is preserved, but browser-agent evidence has lower marginal GTM value than a real design-partner conversation.
6. **Audit Airline action/state-change stability before assigning promotion labels.** Pass consistency alone is not a safe compilation criterion.
7. **Do not unfreeze or retune M17 on partial labels.** Either complete or formally drop each retained track, build one immutable snapshot, and report held-out regret and unsafe promotions.
8. **Begin targeted outreach now.** Lead with support/operations platforms and coding-agent vendors, asking for anonymized traces and outcome signals rather than selling an autonomous optimizer.

## Near-term go/no-go criteria

The next stage should be considered validated only if at least one design partner can provide:

- A meaningful sample of repeated production tasks
- Per-task model cost or reconstructable token usage
- A trustworthy success, escalation, or correction label
- Permission to run read-only analysis and shadow policies
- A plausible path to cash savings after credits and discounts

The decisive startup test is no longer another benchmark pass rate. It is whether SOSOG can ingest one customer's traces, identify a costly and predictable task segment, and verify a safe economic improvement with less bespoke work on the next customer.

## Evidence and calculation notes

Primary persisted sources:

- `s3://sosog-bedrock-batch-769377363988/vertical-expansion/m13-airline-20260821T164841Z/`
- `s3://sosog-bedrock-batch-769377363988/vertical-expansion/m14-appworld-20260822T001511Z/`
- `s3://sosog-bedrock-batch-769377363988/vertical-expansion/m15-swe-verified-20260822T062212Z/`
- PostgreSQL schema `sosog_research`, where completed exports report `database_indexed=true`

Derived metrics in this update use only `status=COMPLETE` rows when describing behavioral pass rates, outcome repeatability, and valid cost distributions. Planned-row pass rates retain error rows only when explicitly labelled. Baseline-label accuracy is a same-task recurrence measure: the single baseline label is compared with later valid executions of that same task. It is not a held-out prediction metric.

Evidence revision audited: `724996b34f87487498c37c30deb514404174af6b`.

Repair release deployed: `8e24c3c01cda402ca6ef2ef33c02f64072bdbdc1`.

Repair archive: `s3://sosog-bedrock-batch-769377363988/vertical-expansion/control/releases/sosog-ai-8e24c3c01cda402ca6ef2ef33c02f64072bdbdc1.tar.gz`.
