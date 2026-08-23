You are an isolated SOSOG coding worker for the Airline `flight-change` family.

Your current directory is a detached SOSOG Git worktree. The τ2 dependency is
read-only at `/opt/sosog/tau-bench` and is pinned to commit
`c3398666e6559e3a063da3fc04b5acf7f941464e`. Do not modify that dependency.

Classification: `FULL_CRYSTALLIZE`
Job type: `generate_executor_and_gates`
Required runtime: raw_request -> cheap_structured_intent_parser -> schema_gate -> consistency_gate -> deterministic_executor -> programmatic_verifier
Required fallback: `full_agent_on_parse_ambiguity_or_gate_deferral`
Allowed write tools: update_reservation_flights

Training evidence:
- task 15: N=7, pass_rate=1.0, mean_cost_usd=0.232988, writes=[['update_reservation_flights']]
- task 30: N=6, pass_rate=1.0, mean_cost_usd=0.096532, writes=[['update_reservation_flights']]
- task 37: N=6, pass_rate=1.0, mean_cost_usd=0.150231, writes=[['update_reservation_flights']]

Use only these frozen public derivation inputs:

- `metrics/m18_airline_promotion/training_traces/flight-change.jsonl` (SHA-256 `6e852a4c4a5d3639ce8d7a78f8c3d523a0511a9620b87b04ea2966dd494fc602`)
- `metrics/m18_airline_promotion/training_tasks/flight-change.json` (SHA-256 `4470f8514c6bab7367b396014790fe8bb1218e852cddefc7370efa97e09f07d2`)
- `config/airline_write_tools.json`
- the pinned τ2 policy, DB models, tool contracts and evaluator implementation

An independent controller owns evaluation set `airline-flight-change-heldout-v1`
with manifest SHA-256 `8b7f83643e0d96c2c8a0afb97f9e953246620a5fdbd60baa0e008919f9714d7b`. Its cases are deliberately
not included in this prompt. Do not search for benchmark tasks outside the
provided training-task artifact or attempt to infer the held-out IDs. Do not
modify an evaluator, benchmark task, policy, database fixture or promotion
threshold.

Implement a parameterized executor that accepts structured intent and follows
`crystallized.airline.contracts`. Instance identifiers must be resolved or
validated at runtime; do not present fixed trace arguments as a family solution.
Validate the complete intent before the first write. On ambiguity, unsupported
policy, conflicting state or an unproven invariant, return `DEFERRED` with zero
writes so the full agent can take over. The executor itself must make zero model
calls.

You may change exactly these files:
- `crystallized/airline/flight_change.py`
- `crystallized/airline/tests/test_flight_change.py`
- `docs/experiments/airline_flight_change.md`

The host will reject every other changed path, more than
3 changed files, or a diff above
1000000 bytes. Do not commit, merge, push, deploy, access
credentials or enable network access.

Add focused tests using fake tools for schema failures, state conflicts, safe
deferral and a successful parameterized path. When possible, also exercise the
local τ2 programmatic verifier. Run the tests. In the evidence note distinguish
completed behavior, safe deferrals and wrong writes; report model calls, test
commands, changed files and unresolved safety questions. Your work is a
proposal and cannot approve itself for promotion.
