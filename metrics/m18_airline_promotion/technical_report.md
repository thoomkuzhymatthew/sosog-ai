# Technical Promotion Report

Vertical: **airline**

## Evidence

Candidates assessed: **50**

Costs below are observed benchmark measurements, not production savings projections.

| Task | Pass rate | Actual runs | Mean observed cost/run | Confidence |
| --- | ---: | ---: | ---: | --- |
| 0 | 100.0% | 8 | $0.053577 | 51.1% |
| 1 | 100.0% | 7 | $0.083987 | 49.2% |
| 10 | 100.0% | 7 | $0.240823 | 49.2% |
| 11 | 100.0% | 7 | $0.125789 | 89.5% |
| 12 | 100.0% | 7 | $0.103479 | 89.5% |
| 13 | 100.0% | 7 | $0.047597 | 49.2% |
| 14 | 0.0% | 7 | $0.220363 | 89.5% |
| 15 | 100.0% | 7 | $0.232988 | 89.5% |
| 16 | 100.0% | 7 | $0.130887 | 89.5% |
| 17 | 57.1% | 7 | $0.192052 | 80.5% |
| 18 | 85.7% | 7 | $0.231914 | 49.2% |
| 19 | 100.0% | 7 | $0.065994 | 89.5% |
| 2 | 100.0% | 7 | $0.119877 | 49.2% |
| 20 | 0.0% | 7 | $0.163089 | 89.5% |
| 21 | 14.3% | 7 | $0.321647 | 89.5% |
| 22 | 100.0% | 7 | $0.203128 | 89.5% |
| 23 | 28.6% | 7 | $0.448936 | 49.2% |
| 24 | 100.0% | 7 | $0.209152 | 89.5% |
| 25 | 100.0% | 7 | $0.128469 | 49.2% |
| 26 | 100.0% | 7 | $0.068218 | 49.2% |
| 27 | 100.0% | 7 | $0.137308 | 49.2% |
| 28 | 100.0% | 6 | $0.079799 | 47.3% |
| 29 | 16.7% | 6 | $0.168774 | 86.0% |
| 3 | 100.0% | 8 | $0.057794 | 51.1% |
| 30 | 100.0% | 6 | $0.096532 | 86.0% |
| 31 | 100.0% | 6 | $0.058302 | 86.0% |
| 32 | 33.3% | 6 | $0.286090 | 73.1% |
| 33 | 100.0% | 6 | $0.221015 | 86.0% |
| 34 | 100.0% | 6 | $0.181649 | 47.3% |
| 35 | 83.3% | 6 | $0.285058 | 77.4% |
| 36 | 100.0% | 6 | $0.042556 | 86.0% |
| 37 | 100.0% | 6 | $0.150231 | 86.0% |
| 38 | 85.7% | 7 | $0.136599 | 76.1% |
| 39 | 71.4% | 7 | $0.134879 | 80.5% |
| 4 | 100.0% | 7 | $0.117334 | 49.2% |
| 40 | 100.0% | 7 | $0.046998 | 89.5% |
| 41 | 100.0% | 7 | $0.078800 | 89.5% |
| 42 | 100.0% | 6 | $0.145998 | 86.0% |
| 43 | 100.0% | 6 | $0.113967 | 86.0% |
| 44 | 16.7% | 6 | $0.415385 | 86.0% |
| 45 | 100.0% | 6 | $0.078757 | 86.0% |
| 46 | 100.0% | 6 | $0.031060 | 47.3% |
| 47 | 100.0% | 6 | $0.093225 | 86.0% |
| 48 | 100.0% | 6 | $0.054286 | 47.3% |
| 49 | 100.0% | 6 | $0.033765 | 86.0% |
| 5 | 100.0% | 7 | $0.112314 | 49.2% |
| 6 | 100.0% | 7 | $0.061745 | 49.2% |
| 7 | 0.0% | 8 | $0.191237 | 93.0% |
| 8 | 28.6% | 7 | $0.160779 | 80.5% |
| 9 | 100.0% | 7 | $0.084342 | 89.5% |

### Aggregate benchmark cost fields

- Observed benchmark cost recorded by the plan: **$48.505966**
- Observed mean cost per complete benchmark run: **$0.144794**

## Routes

| Route | Candidate count |
| --- | ---: |
| FULL_CRYSTALLIZE | 12 |
| RESPONSE_CRYSTALLIZE | 8 |
| DECOMPOSE | 4 |
| LIFT | 2 |
| RETAIN | 18 |
| DROP | 6 |

### Candidate rationale

| Task | Route | Evidence-based reason |
| --- | --- | --- |
| 0 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 1 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 10 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 11 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 12 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 13 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 14 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 15 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 16 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 17 | DECOMPOSE | a common read prefix ends at a volatile write-tail boundary |
| 18 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 19 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 2 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 20 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 21 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 22 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 23 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 24 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 25 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 26 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 27 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 28 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 29 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 3 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 30 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 31 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 32 | LIFT | mid-band pass rate reflects a bounded genuine action inconsistency |
| 33 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 34 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 35 | DECOMPOSE | a common read prefix ends at a volatile write-tail boundary |
| 36 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 37 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 38 | LIFT | mid-band pass rate reflects a bounded genuine action inconsistency |
| 39 | DECOMPOSE | a common read prefix ends at a volatile write-tail boundary |
| 4 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 40 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 41 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 42 | FULL_CRYSTALLIZE | pass rate is at least 0.90 with exactly one passing write skeleton |
| 43 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 44 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 45 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 46 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 47 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 48 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 49 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |
| 5 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 6 | RETAIN | trace evidence does not cross an automatic treatment boundary |
| 7 | DROP | complete-run pass rate is at or below the 0.20 drop boundary |
| 8 | DECOMPOSE | a common read prefix ends at a volatile write-tail boundary |
| 9 | RESPONSE_CRYSTALLIZE | all complete runs pass with one stable read/response trace and no writes |

## Safety and Review Boundaries

Classifications are advisory. Held-out verification and the stated review boundary must pass before any generated change is promoted.

| Task | Review boundary | Observed write-name patterns |
| --- | --- | --- |
| 0 | Required before promotion | None recorded |
| 1 | Required before promotion | None recorded |
| 10 | Required before promotion | None recorded |
| 11 | Required before promotion | ['update_reservation_flights'] |
| 12 | Required before promotion | ['update_reservation_baggages'] |
| 13 | Required before promotion | None recorded |
| 14 | Required before promotion | ['book_reservation'], ['cancel_reservation', 'book_reservation', 'book_reservation'] |
| 15 | Required before promotion | ['update_reservation_flights'] |
| 16 | Required before promotion | ['update_reservation_flights'] |
| 17 | Required before promotion | ['update_reservation_flights', 'update_reservation_baggages', 'update_reservation_passengers'], ['update_reservation_flights', 'update_reservation_passengers', 'update_reservation_baggages'], ['update_reservation_passengers', 'update_reservation_flights', 'update_reservation_baggages'] |
| 18 | Required before promotion | ['update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights'] |
| 19 | Required before promotion | ['cancel_reservation'] |
| 2 | Required before promotion | None recorded |
| 20 | Required before promotion | ['book_reservation'] |
| 21 | Required before promotion | ['update_reservation_flights', 'update_reservation_baggages'], ['update_reservation_flights', 'update_reservation_flights', 'update_reservation_baggages'] |
| 22 | Required before promotion | ['update_reservation_passengers', 'update_reservation_flights', 'update_reservation_baggages'] |
| 23 | Required before promotion | ['book_reservation', 'book_reservation', 'book_reservation'], ['cancel_reservation', 'book_reservation', 'book_reservation', 'book_reservation'], ['cancel_reservation', 'book_reservation'] |
| 24 | Required before promotion | ['book_reservation'] |
| 25 | Required before promotion | ['book_reservation', 'book_reservation'], ['book_reservation'] |
| 26 | Required before promotion | None recorded |
| 27 | Required before promotion | None recorded |
| 28 | Required before promotion | None recorded |
| 29 | Required before promotion | ['cancel_reservation', 'book_reservation'], ['update_reservation_flights', 'update_reservation_baggages'] |
| 3 | Required before promotion | None recorded |
| 30 | Required before promotion | ['update_reservation_flights'] |
| 31 | Required before promotion | None recorded |
| 32 | Required before promotion | ['update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights'], ['update_reservation_flights', 'update_reservation_flights'], ['update_reservation_flights'] |
| 33 | Required before promotion | ['update_reservation_flights', 'update_reservation_baggages'] |
| 34 | Required before promotion | ['update_reservation_flights', 'update_reservation_flights'], ['update_reservation_flights'] |
| 35 | Required before promotion | ['book_reservation'] |
| 36 | Required before promotion | None recorded |
| 37 | Required before promotion | ['update_reservation_flights'] |
| 38 | Required before promotion | ['cancel_reservation', 'send_certificate'] |
| 39 | Required before promotion | ['cancel_reservation', 'cancel_reservation', 'cancel_reservation'], ['cancel_reservation', 'cancel_reservation'] |
| 4 | Required before promotion | None recorded |
| 40 | Required before promotion | ['update_reservation_passengers'] |
| 41 | Required before promotion | None recorded |
| 42 | Required before promotion | ['cancel_reservation', 'cancel_reservation'] |
| 43 | Required before promotion | None recorded |
| 44 | Required before promotion | ['cancel_reservation'], ['update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights'], ['update_reservation_flights', 'update_reservation_flights', 'update_reservation_flights'] |
| 45 | Required before promotion | None recorded |
| 46 | Required before promotion | None recorded |
| 47 | Required before promotion | None recorded |
| 48 | Required before promotion | None recorded |
| 49 | Required before promotion | None recorded |
| 5 | Required before promotion | None recorded |
| 6 | Required before promotion | None recorded |
| 7 | Required before promotion | ['cancel_reservation'], ['update_reservation_flights', 'cancel_reservation', 'cancel_reservation'] |
| 8 | Required before promotion | ['book_reservation'] |
| 9 | Required before promotion | None recorded |

## Suggested Code-Change Stage

Suggested stages are proposals only; generated changes should remain isolated until tests and review pass.

- **0** — `RETAIN`: HUMAN_REVIEW
- **1** — `RETAIN`: HUMAN_REVIEW
- **10** — `RETAIN`: HUMAN_REVIEW
- **11** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **12** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **13** — `RETAIN`: HUMAN_REVIEW
- **14** — `DROP`: ARCHIVE_CANDIDATE
- **15** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **16** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **17** — `DECOMPOSE`: GENERATE_PREFIX_AND_TAIL_BOUNDARY
- **18** — `RETAIN`: HUMAN_REVIEW
- **19** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **2** — `RETAIN`: HUMAN_REVIEW
- **20** — `DROP`: ARCHIVE_CANDIDATE
- **21** — `DROP`: ARCHIVE_CANDIDATE
- **22** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **23** — `RETAIN`: HUMAN_REVIEW
- **24** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **25** — `RETAIN`: HUMAN_REVIEW
- **26** — `RETAIN`: HUMAN_REVIEW
- **27** — `RETAIN`: HUMAN_REVIEW
- **28** — `RETAIN`: HUMAN_REVIEW
- **29** — `DROP`: ARCHIVE_CANDIDATE
- **3** — `RETAIN`: HUMAN_REVIEW
- **30** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **31** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **32** — `LIFT`: RUN_LIFTING_EXPERIMENT
- **33** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **34** — `RETAIN`: HUMAN_REVIEW
- **35** — `DECOMPOSE`: GENERATE_PREFIX_AND_TAIL_BOUNDARY
- **36** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **37** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **38** — `LIFT`: RUN_LIFTING_EXPERIMENT
- **39** — `DECOMPOSE`: GENERATE_PREFIX_AND_TAIL_BOUNDARY
- **4** — `RETAIN`: HUMAN_REVIEW
- **40** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **41** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **42** — `FULL_CRYSTALLIZE`: GENERATE_FULL_EXECUTOR
- **43** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **44** — `DROP`: ARCHIVE_CANDIDATE
- **45** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **46** — `RETAIN`: HUMAN_REVIEW
- **47** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **48** — `RETAIN`: HUMAN_REVIEW
- **49** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
- **5** — `RETAIN`: HUMAN_REVIEW
- **6** — `RETAIN`: HUMAN_REVIEW
- **7** — `DROP`: ARCHIVE_CANDIDATE
- **8** — `DECOMPOSE`: GENERATE_PREFIX_AND_TAIL_BOUNDARY
- **9** — `RESPONSE_CRYSTALLIZE`: GENERATE_RESPONSE_EXECUTOR
