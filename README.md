# SOSOG AI

SOSOG is a proof of concept for trace-driven agent crystallization: capture repeated AI-agent workflows, identify the stable ones, and replace those stable paths with deterministic scripts that use approximately zero model tokens. The agent remains the fallback for ambiguous or unstable cases.

This repository contains the project artifacts from M0-M10:

- `docs/`: milestone reports and the consolidated technical findings report.
- `metrics/`: machine-readable summaries used by the reports.
- `traces/`: JSONL trace exports from the measured tau-bench runs.
- `crystallized/`: hand-built and generated deterministic proof scripts.
- `scripts/`: analysis and export harnesses.
- `config/`: the 74-task DB-checkable Retail working set.
- `patches/`: local tau2 changes needed to reproduce Bedrock prompt caching and cost accounting.

## Headline Findings

The best single summary is in `docs/SOSOG_findings_report.md`.

Key measured results from the local tau-bench Retail POC:

- M2 baseline: 68/74 DB-checkable Retail tasks passed with the stock Sonnet 4.6 agent; cached benchmark cost was $11.030292.
- M3 corpus: 740 valid simulations, 74 tasks at N=10, 0 infrastructure errors.
- M3 promotion screen: 54/74 tasks met the `>=9/10` DB-pass plus identical write-skeleton bar.
- M4 proof: task 5 replayed deterministically with 0 model calls, 0 tokens, and $0.000000 script cost.
- M7 safety gate: on the 18-request messy-return set, wrong writes stayed at 0 while 10/18 requests ran deterministically and 8/18 deferred.
- M8 automation probe: executor generation automated for the cancel family; schema and safety gates were derived but still required human review.

Savings percentages in the docs are benchmark- and task-set-specific; they should not be read as universal production claims.

## Tau-Bench Dependency

The upstream tau2 checkout is intentionally not vendored here because it is large and contains a virtualenv plus bundled benchmark result data. To reproduce from a clean machine:

```bash
git clone https://github.com/sierra-research/tau2-bench tau-bench
cd tau-bench
git checkout c3398666e6559e3a063da3fc04b5acf7f941464e
uv sync
uv pip install boto3
git apply ../patches/tau2-bedrock-prompt-cache.patch
```

The milestone docs include the exact commands used for each run.

## Bedrock Model Route

Batch inference was abandoned for this POC because the AWS account was not entitled for Bedrock batch jobs. Trace generation used on-demand Bedrock runtime calls with Claude Sonnet 4.6:

```text
us.anthropic.claude-sonnet-4-6
global.anthropic.claude-sonnet-4-6
```

Do not commit credentials. This repository excludes `.env`, virtualenvs, local tau-bench checkouts, and Python caches.
