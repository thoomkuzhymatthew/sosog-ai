# Business Promotion Report

Vertical: **airline**

## Decision Snapshot

The benchmark produced **50 candidate promotion decisions**.

| Route | Candidate count |
| --- | ---: |
| FULL_CRYSTALLIZE | 12 |
| RESPONSE_CRYSTALLIZE | 8 |
| DECOMPOSE | 4 |
| LIFT | 2 |
| RETAIN | 18 |
| DROP | 6 |

## Observed Benchmark Cost

- Observed benchmark cost recorded by the plan: **$48.505966**
- Observed mean cost per complete benchmark run: **$0.144794**

These figures describe the measured benchmark only. They are not projected customer savings and are not annualised.

| Task | Recommended route | Observed pass rate | Observed mean cost/run | Next evidence stage |
| --- | --- | ---: | ---: | --- |
| 0 | RETAIN | 100.0% | $0.053577 | HUMAN_REVIEW |
| 1 | RETAIN | 100.0% | $0.083987 | HUMAN_REVIEW |
| 10 | RETAIN | 100.0% | $0.240823 | HUMAN_REVIEW |
| 11 | FULL_CRYSTALLIZE | 100.0% | $0.125789 | GENERATE_FULL_EXECUTOR |
| 12 | FULL_CRYSTALLIZE | 100.0% | $0.103479 | GENERATE_FULL_EXECUTOR |
| 13 | RETAIN | 100.0% | $0.047597 | HUMAN_REVIEW |
| 14 | DROP | 0.0% | $0.220363 | ARCHIVE_CANDIDATE |
| 15 | FULL_CRYSTALLIZE | 100.0% | $0.232988 | GENERATE_FULL_EXECUTOR |
| 16 | FULL_CRYSTALLIZE | 100.0% | $0.130887 | GENERATE_FULL_EXECUTOR |
| 17 | DECOMPOSE | 57.1% | $0.192052 | GENERATE_PREFIX_AND_TAIL_BOUNDARY |
| 18 | RETAIN | 85.7% | $0.231914 | HUMAN_REVIEW |
| 19 | FULL_CRYSTALLIZE | 100.0% | $0.065994 | GENERATE_FULL_EXECUTOR |
| 2 | RETAIN | 100.0% | $0.119877 | HUMAN_REVIEW |
| 20 | DROP | 0.0% | $0.163089 | ARCHIVE_CANDIDATE |
| 21 | DROP | 14.3% | $0.321647 | ARCHIVE_CANDIDATE |
| 22 | FULL_CRYSTALLIZE | 100.0% | $0.203128 | GENERATE_FULL_EXECUTOR |
| 23 | RETAIN | 28.6% | $0.448936 | HUMAN_REVIEW |
| 24 | FULL_CRYSTALLIZE | 100.0% | $0.209152 | GENERATE_FULL_EXECUTOR |
| 25 | RETAIN | 100.0% | $0.128469 | HUMAN_REVIEW |
| 26 | RETAIN | 100.0% | $0.068218 | HUMAN_REVIEW |
| 27 | RETAIN | 100.0% | $0.137308 | HUMAN_REVIEW |
| 28 | RETAIN | 100.0% | $0.079799 | HUMAN_REVIEW |
| 29 | DROP | 16.7% | $0.168774 | ARCHIVE_CANDIDATE |
| 3 | RETAIN | 100.0% | $0.057794 | HUMAN_REVIEW |
| 30 | FULL_CRYSTALLIZE | 100.0% | $0.096532 | GENERATE_FULL_EXECUTOR |
| 31 | RESPONSE_CRYSTALLIZE | 100.0% | $0.058302 | GENERATE_RESPONSE_EXECUTOR |
| 32 | LIFT | 33.3% | $0.286090 | RUN_LIFTING_EXPERIMENT |
| 33 | FULL_CRYSTALLIZE | 100.0% | $0.221015 | GENERATE_FULL_EXECUTOR |
| 34 | RETAIN | 100.0% | $0.181649 | HUMAN_REVIEW |
| 35 | DECOMPOSE | 83.3% | $0.285058 | GENERATE_PREFIX_AND_TAIL_BOUNDARY |
| 36 | RESPONSE_CRYSTALLIZE | 100.0% | $0.042556 | GENERATE_RESPONSE_EXECUTOR |
| 37 | FULL_CRYSTALLIZE | 100.0% | $0.150231 | GENERATE_FULL_EXECUTOR |
| 38 | LIFT | 85.7% | $0.136599 | RUN_LIFTING_EXPERIMENT |
| 39 | DECOMPOSE | 71.4% | $0.134879 | GENERATE_PREFIX_AND_TAIL_BOUNDARY |
| 4 | RETAIN | 100.0% | $0.117334 | HUMAN_REVIEW |
| 40 | FULL_CRYSTALLIZE | 100.0% | $0.046998 | GENERATE_FULL_EXECUTOR |
| 41 | RESPONSE_CRYSTALLIZE | 100.0% | $0.078800 | GENERATE_RESPONSE_EXECUTOR |
| 42 | FULL_CRYSTALLIZE | 100.0% | $0.145998 | GENERATE_FULL_EXECUTOR |
| 43 | RESPONSE_CRYSTALLIZE | 100.0% | $0.113967 | GENERATE_RESPONSE_EXECUTOR |
| 44 | DROP | 16.7% | $0.415385 | ARCHIVE_CANDIDATE |
| 45 | RESPONSE_CRYSTALLIZE | 100.0% | $0.078757 | GENERATE_RESPONSE_EXECUTOR |
| 46 | RETAIN | 100.0% | $0.031060 | HUMAN_REVIEW |
| 47 | RESPONSE_CRYSTALLIZE | 100.0% | $0.093225 | GENERATE_RESPONSE_EXECUTOR |
| 48 | RETAIN | 100.0% | $0.054286 | HUMAN_REVIEW |
| 49 | RESPONSE_CRYSTALLIZE | 100.0% | $0.033765 | GENERATE_RESPONSE_EXECUTOR |
| 5 | RETAIN | 100.0% | $0.112314 | HUMAN_REVIEW |
| 6 | RETAIN | 100.0% | $0.061745 | HUMAN_REVIEW |
| 7 | DROP | 0.0% | $0.191237 | ARCHIVE_CANDIDATE |
| 8 | DECOMPOSE | 28.6% | $0.160779 | GENERATE_PREFIX_AND_TAIL_BOUNDARY |
| 9 | RESPONSE_CRYSTALLIZE | 100.0% | $0.084342 | GENERATE_RESPONSE_EXECUTOR |

## Customer Savings Projection

**Not calculated.** A defensible projection requires customer workload volume, the production baseline cost, replacement-path cost, achieved quality, and fallback rate. None is inferred from benchmark route classifications.

## Recommended Commercial Next Step

Validate the proposed changes on held-out cases, then measure them in shadow traffic. Report customer savings only from the resulting production workload and cost measurements.
