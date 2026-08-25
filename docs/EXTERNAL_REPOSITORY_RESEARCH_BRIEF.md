# Research brief: first external repository and starting environment

Copy the prompt below into a web-enabled Claude research session. The task is
selection and evidence gathering only: it does not authorize contacting
maintainers, spending money, downloading large datasets, running untrusted
code, or modifying SOSOG.

---

You are conducting source-driven technical research for SOSOG, a system that
ingests real AI-agent execution traces, identifies recurring task families,
classifies the appropriate intervention, and tests whether selected stable
work can be replaced or assisted by bounded deterministic software. Generated
changes are evaluated against visible and locked cases and stop at human
safety review; they are never autonomously merged or deployed.

Your objective is to identify the best first **external, non-SOSOG repository
and trace environment** for a validity-focused end-to-end pilot. This is not a
search for the most famous agent benchmark. Find an environment that can
genuinely test—and potentially disconfirm—the product thesis.

## Research rules

1. Browse the current web and cite primary sources for every material factual
   claim: official repositories, documentation, dataset cards, papers, release
   notes, and licenses. Record access dates and distinguish verified facts from
   your inference.
2. Do not rely on search-result snippets, promotional summaries, or benchmark
   leaderboards when the underlying source is available.
3. Verify that each candidate still exists, is accessible, and has the claimed
   data fields as of the research date.
4. Do not contact anyone, create accounts, use credentials, accept licenses,
   spend money, download large corpora, or execute repository code. Provide
   exact proposed acquisition/reproduction commands, but do not run them.
5. Treat final patches without their agent trajectory as outcome data, not as
   trace data. Treat synthetic benchmark trajectories as a useful comparator,
   not sufficient external validation by themselves.
6. Prefer a paired recommendation when appropriate: a trace/session dataset
   plus the corresponding replayable repositories or execution harness.

## What an ideal starting environment contains

- Genuine coding-agent sessions from work not generated specifically for
  SOSOG.
- Inputs, timestamps, model/agent events, tool calls, command/test activity,
  and a durable final outcome such as an accepted commit, CI result, test
  state, or explicit human acceptance/rejection.
- Multiple executions of recurring task shapes, not merely many unrelated
  one-off requests.
- A reliable mapping from a session to repository, base revision, resulting
  patch/commit, and outcome.
- A permissive and unambiguous license for both code and session data.
- A deterministic local or containerized test path that can run without
  credentials or production services after dependencies are acquired.
- Fast enough feedback for a one-week pilot: ideally a focused test completes
  in under ten minutes on an ordinary EC2 machine.
- Moderate setup and storage requirements, documented schemas, and an active
  or at least reproducible upstream project.
- Enough heterogeneity to test generalization: held-out cases should differ by
  issue, time, or repository—not be superficial variants of the training
  examples.

Python and TypeScript repositories are operationally convenient but must not
receive a high score solely for language familiarity.

## Candidates to investigate

Start by verifying, not assuming, the suitability of sources such as
Entire/SWE-chat, SpecStory session exports, and other open coding-agent trace
datasets. Expand beyond these names. Also investigate self-hostable agent
projects that retain replayable session histories linked to tests or commits.
Do not force a named source into the shortlist if its current schema, license,
availability, or outcome linkage is inadequate.

Explicitly reject candidates that provide only final diffs, lack independently
checkable outcomes, have unclear redistribution terms, require private
credentials for core tests, contain unmanaged sensitive data, or are so large
that a narrow pilot cannot be sampled reproducibly.

## Evaluate two distinct layers

For every serious candidate, separately assess:

1. **Trace source:** whether the trajectories are real, sufficiently complete,
   legally usable, and linked to outcomes.
2. **Execution environment:** whether the associated repositories can be
   checked out at exact revisions and tested safely, deterministically, and at
   reasonable cost.

A strong trace dataset with irreproducible repositories is not a strong pilot.
Likewise, a clean benchmark repository without real session traces does not
test SOSOG's ingestion and discovery thesis.

## Scoring rubric

Score each shortlisted candidate out of 100 using this fixed weighting:

| Criterion | Weight |
|---|---:|
| Real trace completeness and provenance | 20 |
| Recurring task-family density | 15 |
| Independently verifiable outcomes | 15 |
| Repository/base-revision linkage | 10 |
| Safe deterministic replay/testability | 15 |
| Licensing, privacy, and redistribution clarity | 10 |
| Pilot-sized compute/storage/setup burden | 5 |
| Relevance to a plausible customer workflow | 5 |
| Ability to construct non-leaking held-out evaluation | 5 |

Do not silently adjust the weighting. Explain uncertainty and provide a score
range when evidence is incomplete.

## Required output

Produce one Markdown report with:

1. **Executive recommendation:** the best source/environment pair, why it is
   the right first test, and the strongest reason it might fail.
2. **Longlist:** at least 10 candidates with source links and a one-sentence
   accept/reject rationale.
3. **Shortlist comparison:** the top three scored with the rubric above,
   including verified license, approximate size, schema fields, repository
   linkage, outcome signal, reproduction path, compute needs, and unresolved
   questions.
4. **Recommended sample:** exact inclusion/exclusion rules and a reproducible
   sampling method. Avoid cherry-picking successful or obviously repetitive
   sessions.
5. **One-week pilot plan:** acquisition, schema mapping, redaction review,
   ingestion, clustering/classification, one candidate task-family selection,
   baseline evaluation, locked split, and go/no-go review.
6. **Pre-registered validity tests:** quantitative thresholds and qualitative
   checks set before examining final results.
7. **Disconfirmation criteria:** results that would count against SOSOG—for
   example, no stable recurring families, unavailable outcome truth,
   interventions that fail held-out cases, or evaluation/maintenance cost that
   dominates plausible savings.
8. **Security and legal risks:** untrusted code, dependency execution, secrets,
   personal data, prompt content, licensing, and data-retention concerns.
9. **Acquisition appendix:** proposed read-only commands, expected download
   size, required tools, exact revisions/releases where possible, and a list of
   facts that still require manual confirmation.
10. **Machine-readable table:** finish with CSV in a fenced block using these
    columns:

```text
candidate,trace_source_url,repository_url,license,real_sessions,tool_calls,base_revision_link,outcome_signal,replayable,estimated_size,setup_burden,score,confidence,decision,largest_risk
```

## Validity standard

The preferred pilot must be capable of producing a negative answer. Do not
select an environment merely because it resembles SOSOG's existing Airline or
Retail demonstrations. Prefer genuine traces, temporal or repository-level
holdouts, independently computed outcomes, and task families whose boundaries
must be discovered from the data.

The final recommendation is research input, not approval to ingest, execute,
or publish third-party data. End with a short list of decisions the SOSOG team
must make before any acquisition begins.

---
