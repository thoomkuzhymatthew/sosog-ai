# M8 Recipe - Trace To Task Environment

Date: 2026-08-18

Status: recipe written before applying it to the M8 target family. Target family selected: `cancel`, using candidate Retail tasks `66`, `69`, `88`, and `90`. I selected `cancel` because it is not one of the previously hand-built families (`return`, `exchange`) and it should have a narrower write surface than address modification.

## 1. Goal

This recipe describes a family-agnostic procedure for deriving a small task environment from passing traces. The output environment has three components:

1. A parameterized deterministic executor.
2. A schema gate.
3. A consistency/safety gate.

The test is whether the procedure can generate those components for a family that has not already been hand-built.

## 2. Inputs

Required inputs:

- At least two passing traces from the same task family.
- Task definitions for those traces, including user instructions and programmatic verifier expectations.
- Tool signatures for every read and write tool appearing in the traces.
- Initial database state used by the verifier.

Optional inputs:

- Additional failed traces from the same family, used only to identify unsafe variations.
- Held-out tasks from the same family, used only after generation for a generalization ladder.

## 3. Family-Agnostic Generation Procedure

### Step A - Align Passing Traces

1. Extract each trace's ordered tool-call sequence.
2. Split tool calls into read calls and write calls. A write call is any tool call whose result mutates the database state checked by the verifier.
3. Keep only traces that pass the programmatic DB verifier.
4. Compare write-call skeletons across passing traces:
   - Same tool names in the same order means the family has a candidate deterministic procedure.
   - Different write order or different write tools means the family is not yet one procedure; split into subfamilies or stop.
5. Compare read-call skeletons across passing traces:
   - Common read calls before the first write become the resolver plan.
   - Arguments that differ by instance become parameters.
   - Arguments that are identical and not user/task-specific may remain constants.

Output of Step A:

- A write skeleton such as `write_tool(order_id, item_ids, payment_method_id)`.
- A resolver skeleton such as `find_user -> get_user -> get_order(s)`.
- A parameter map from task/user evidence to tool arguments.

Classification rule:

- `Fully derived` if the skeletons and parameter map are inferred mechanically from aligned traces and tool signatures.
- `Derived + human-reviewed` if the procedure emits a draft but a human chooses among multiple plausible subfamilies or validates a non-obvious parameter.
- `Hand-authored` if a human writes family-specific logic that was not implied by aligned traces/tool signatures.

### Step B - Derive The Parameterized Executor

1. Create a deterministic function that accepts a structured intent object.
2. Run the resolver skeleton using read tools only.
3. Bind write arguments by dataflow:
   - Values produced by read tools are bound by matching field names and observed trace use.
   - Values present in task/user intent are bound from the structured intent.
   - Values constant across traces remain constants only if they are not customer- or item-specific.
4. Execute the aligned write skeleton.
5. Run the programmatic verifier.

The executor must not call a model. It must not shortcut the database to the final state. It must use the same domain tools that the trace used.

### Step C - Derive The Schema Gate

1. Inspect the generated executor's structured-intent contract.
2. Require fields that are needed to execute the resolver skeleton and bind write arguments.
3. Validate field types directly from tool signatures:
   - String identifiers must be strings.
   - Enumerated values must match tool schema enum values when the tool exposes them.
   - Item selectors must be nonempty when a write requires items.
4. Reject unsupported optional fields rather than guessing.
5. If the parser/status layer can emit `AMBIGUOUS/INSUFFICIENT`, defer without resolving.

Classification rule:

- `Fully derived` if required fields and type checks come from tool signatures plus trace dataflow.
- `Derived + human-reviewed` if a human approves field naming or a conservative enum interpretation.
- `Hand-authored` if a human designs family-specific schema rules not recoverable from signatures/dataflow.

### Step D - Derive The Consistency/Safety Gate

The consistency gate is the hardest part. Its job is to prove that the structured intent and read-tool results identify exactly one safe write before any write happens.

Generic safety recipe:

1. Execute the resolver skeleton with read tools only.
2. Build candidate write arguments from the read results.
3. Require exactly one candidate write. Zero candidates defer; multiple candidates defer.
4. Validate all write arguments against the pre-write database state:
   - Referenced records must exist.
   - Referenced records must belong to the resolved customer/account/order.
   - Referenced records must be in a state where the write is allowed.
   - Any item or record set selected by natural-language fields must resolve unambiguously.
5. Add a family-specific invariant only when it can be generated from observed write preconditions, tool docs/signatures, or verifier expectations.
   - For returns, the generated shape would be "selected returned items plus kept items must form a complete, disjoint partition of one delivered order."
   - For cancellation, the analogous generated shape should be "the selected order must be exactly one customer order whose pre-write state permits cancellation, and the write must affect that order only."
6. If any check cannot prove safety, defer.

Classification rule:

- `Fully derived` if the candidate uniqueness and state checks come from tool signatures, trace write preconditions, and observed verifier expectations without hand-written family semantics.
- `Derived + human-reviewed` if the candidate checks are generated but a human validates that they are the right safety boundary for the family.
- `Hand-authored` if a human writes the family-specific safety logic directly.

## 4. Generalization Ladder

After generating the environment, run a ladder analogous to M5:

1. Same instance, structured parameters from its own trace.
2. Held-out instance, parameters hand-fed from the task definition or trace evidence.
3. Held-out instance, parameters self-resolved from a task-level structured intent using read tools only.
4. Adversarial safety checks that should defer before any write.

Pass criteria:

- The generated executor passes the programmatic verifier on at least one held-out instance with zero model calls.
- The generated gate defers all adversarial cases with zero wrong writes.
- Any component that needed human family-specific intervention is classified honestly.

## 5. Reporting Standard

The M8 report must classify each generated component:

| Component | Classification | Evidence required |
| --- | --- | --- |
| Executor | Fully derived / Derived + human-reviewed / Hand-authored | Trace alignment, generated procedure, ladder outcome |
| Schema gate | Fully derived / Derived + human-reviewed / Hand-authored | Contract derived from tool signatures and trace dataflow |
| Consistency-safety gate | Fully derived / Derived + human-reviewed / Hand-authored | Pre-write uniqueness/state checks and adversarial outcome |

Interpretation rule:

- Executor plus both gates mostly derived means SOSOG looks like a scalable engine.
- Executor derived but safety gate human-reviewed or hand-authored means SOSOG is about 80% automated with human safety-review per family.
- Most components hand-authored means the construction is closer to consulting.

Honesty checks:

- Confirm the target family was not previously hand-built.
- Confirm this recipe existed before applying it to target-family traces.
- For every `derived` label, state whether the component could honestly have been generated without already knowing the answer.
