# SOSOG

SOSOG turns repeated AI-agent work into safer, cheaper execution paths. It
ingests agent traces, identifies recurring task families, classifies the right
intervention, generates bounded proposals, evaluates them against visible and
locked cases, and stops at human review before any merge or deployment.

This repository contains two deliberately distinct bodies of work:

1. **The V1 product core** — the current implementation under `sosog/`, with
   persistence, ingestion, task identification, orchestration, repair,
   economics, and reporting.
2. **The research evidence archive** — the experiments, traces, metrics, and
   milestone reports that established the product thesis. These remain in
   their original paths so historical commands and evidence references stay
   reproducible.

No benchmark result or projected saving in this repository should be treated
as a universal production claim.

## Start here

- [Accessible product overview](docs/SOSOG_ACCESSIBLE_BRIEF.md)
- [V1 architecture and current build status](docs/V1_ARCHITECTURE_PLAN.md)
- [Repair and robustness design](docs/REPAIR_LOOP_DESIGN.md)
- [Technical findings and evidence boundaries](docs/SOSOG_findings_report.md)
- [Documentation and repository map](docs/README.md)
- [External repository research brief](docs/EXTERNAL_REPOSITORY_RESEARCH_BRIEF.md)

## Current status

The V1 path currently covers:

```text
trace ingestion
  → task-family identification
  → treatment classification
  → bounded proposal/repair
  → visible + locked evaluation
  → economics and reporting
  → human safety review
```

Generated repair candidates execute in fresh, networkless Bubblewrap
sandboxes. Locked evaluator data is not included in worker feedback, and a
perfect automated score advances only to human safety review. The latest EC2
validation passed the full 123-test suite. Event-triggered re-investigation
and the thin human-review console remain future product components; neither
blocks external repository validation.

## Repository map

### Current product and shared runtime

| Path | Purpose |
|---|---|
| `sosog/` | V1 product packages and tests |
| `promotion_engine/` | Shared treatment taxonomy, workflow contracts, and reporting used by V1 |
| `predictor/` | Shared trace features plus the earlier routing/regret prototype |
| `crystallized/` | Deterministic executor contracts and the Airline reference adapter |
| `infra/aws/` | EC2 runtime, worker, auth-refresh, database, and deployment infrastructure |
| `build_jobs/` | Immutable prompts/manifests used to build V1 in isolated workers; retained as build provenance |

### Research evidence archive

| Path | Purpose |
|---|---|
| `docs/M*.md` | Chronological milestone reports |
| `docs/SOSOG_findings_report.md` | Consolidated technical findings |
| `docs/vertical_investigation_progress_2026-08-22.md` | Cross-vertical investigation status |
| `metrics/` | Machine-readable experiment summaries |
| `traces/` | Redacted/measured benchmark trace exports |
| `scripts/` | Experiment, analysis, compatibility, and export harnesses |
| `research_ops/` | Earlier research persistence utilities |
| `config/` | Frozen experiment/task-set configuration |
| `patches/` | Reproduction patches for upstream benchmark dependencies |

Some shared modules intentionally straddle these sections because V1 imports
validated contracts and features that originated in the research phase. The
[documentation map](docs/README.md) identifies the authoritative current
documents and the historical evidence trail.

## Safety boundary

- Generated-job manifests deny network, commit, merge, push, and deployment;
  the supervisor freezes only explicitly allowed changed files.
- Generated candidate execution is isolated from the evaluator process,
  filesystem, environment, network, and other test cases.
- Unsafe cases must defer without writes; normal locked cases must complete
  correctly.
- Cost and savings reports distinguish measured, estimated, and scenario-only
  inputs. Realized savings are never inferred.
- Promotion remains a human decision.

## Development validation

The pinned EC2 runtime is built by `infra/aws/bootstrap_v1_runtime.sh`. From an
equivalent configured environment, run:

```bash
python -m unittest discover
```

The candidate-isolation tests require a trusted, root-owned Bubblewrap binary
and therefore skip on development machines that do not provide one.

## Historical benchmark reproduction

The upstream tau2 checkout is intentionally not vendored. Historical Retail
and Airline reproduction details, exact revisions, model routes, and commands
are recorded in the milestone documents. Start with the
[research archive index](docs/research/README.md) rather than treating those
experiments as the current product entry point.

Do not commit credentials, raw customer traces, virtual environments, or
local benchmark checkouts.
