# SOSOG — An Accessible Overview

Status: working brief, 23 August 2026

## The idea in one sentence

SOSOG helps companies understand what their AI agents are doing, identify work
that does not need an expensive AI model, and safely replace or improve that
work while measuring the savings.

## The problem

Companies are beginning to use AI agents as a digital workforce. These agents
answer customers, change bookings, update accounts, work with company systems
and write code.

The problem is that a company may use a powerful, expensive AI model for every
step of every task—even when parts of the work are routine and predictable. It
is similar to asking a highly paid expert to repeatedly complete a form or look
up the same information.

Existing monitoring tools can show how many tokens an agent used, how long it
took and which tools it called. That is useful, but it does not answer the most
important questions:

- Which tasks genuinely need a capable AI agent?
- Which tasks could be handled by ordinary software?
- Which parts of a task are predictable even if the whole task is not?
- Can we make unreliable agents better using examples of successful work?
- How much money would a safe change actually save?

SOSOG is intended to answer those questions and help implement the resulting
changes.

## A simple analogy

Think of SOSOG as a combination of:

- an accountant for the AI workforce;
- an operations consultant who finds inefficient work;
- and an engineer who turns repeatable work into reliable software.

It does not begin by assuming that every AI call should be made cheaper. It
first asks whether that call was necessary at all.

## What “crystallisation” means

An AI agent may solve the same kind of task many times. If successful runs
repeatedly follow the same safe structure, SOSOG can attempt to turn that
behaviour into a normal software procedure. We call this crystallisation.

For example, instead of asking a powerful AI model to reason through every
product return, a cheaper system might:

1. use a small AI model to turn the customer's message into a structured
   request;
2. check that the request is complete and unambiguous;
3. look up the correct customer, order, product and payment method;
4. confirm that the requested action is allowed;
5. execute the return using deterministic software;
6. send uncertain cases back to the full AI agent.

The small model is not trusted to make the final decision. It only interprets
the language. Ordinary software checks the result before any important action
is taken.

The generated procedure is expected to be specific to the customer's systems
and policies. The SOSOG platform should work across companies; the individual
procedures it creates should be fitted to each company.

## Not every task should be fully crystallised

SOSOG currently considers several possible treatments.

### Fully crystallise it

Replace the full agent workflow with a cheap language parser, safety checks and
deterministic software. Uncertain cases fall back to the agent.

### Decompose it

Automate only the predictable beginning of the task. For example, software can
identify the customer, collect the relevant records and prepare reliable
context. The AI agent then handles the uncertain decision-making and any
changes to company systems.

### Lift it

Keep the full AI agent, but improve its performance by giving it carefully
selected examples of successful previous work.

### Leave it alone, escalate it or stop early

Some tasks remain too ambiguous, risky or variable to change. Tasks that
almost always fail may need a different strategy or earlier human escalation
rather than more model spending.

## What has been demonstrated so far

The strongest evidence comes from a Retail benchmark containing customer
support tasks such as returns, exchanges, cancellations and order changes. The
outcome of each task could be checked by looking at the resulting database
state rather than asking another AI model to judge it.

### Repeated runs revealed stable and unstable work

SOSOG ran 74 Retail tasks ten times each, creating 740 completed runs. Under the
initial strict rules, 54 of the 74 tasks were possible crystallisation
candidates. Those candidates represented 67.3% of the cost of the original
single-run benchmark.

That does not mean every company can save 67.3%. It means a large part of this
particular benchmark was spent on tasks with highly repeatable successful
behaviour, making them worth investigating.

The repeated runs were important. Some tasks looked predictable after only a
few attempts but later failed or followed a different successful path. A
single trace is therefore not enough evidence for automation.

### Reusable procedures worked on new examples

SOSOG created return and exchange procedures that did not contain fixed
customer, order or product IDs. Given a structured request, they looked up the
correct records and performed the correct action.

They then worked on selected customers, orders and products that were not used
to create them. The resulting database states were correct, and the procedures
used no AI model at runtime.

This shows more than memorising and replaying one successful trace. It is still
a limited Retail result, not proof that the same procedure works for every
company or every possible return.

### Cheap language interpretation worked when combined with safety checks

A smaller, cheaper model was tested on 18 messy customer return requests. The
final gated system handled ten requests deterministically and safely sent eight
uncertain requests to the full-agent route. On this tested set, it made zero
wrong writes, and three additional dangerous test cases were all stopped
before any write occurred.

The estimated all-request cost reduction was 57.5% compared with using the
powerful agent for every request. Part of that comparison is estimated because
the powerful model was not rerun on every rewritten request.

### A new cancellation procedure was substantially generated from traces

SOSOG used traces and tool descriptions to derive a cancellation procedure for
a task family that had not previously been built by hand. It worked on two
held-out tasks and rejected three dangerous cases, with no AI model calls
during execution.

The procedure itself was derived automatically, but a person still reviewed
the most important safety rules. The honest interpretation is a largely
automated core with human safety review, not a fully autonomous system.

### Partial automation worked for some tasks and harmed another

The decomposition strategy preserved correctness and reduced cost on three
tested Retail tasks. On another task, however, performance fell from 20 correct
runs out of 20 to 14 out of 20. The automated beginning was correct, but the
handoff removed context the agent apparently needed later.

This is an important result: automating a predictable-looking step is not
automatically safe or economically useful. Every proposed change needs a fair
comparison against the original workflow.

### Successful examples dramatically improved one unreliable task

On one Retail task, the original agent succeeded in only 6 of 20 runs. When it
received two carefully selected examples of previous successful work, it
succeeded in all 20 runs, with no regressions in the paired comparison.

Only one task has been validated at this depth, so this is evidence that the
method can work—not a promise that examples solve every unreliable task.

## What is happening now

SOSOG is applying the investigation method to additional kinds of work.

In Airline, the latest dataset contains 335 completed runs across 50 tasks.
The current system classified them into:

- 12 possible full crystallisations;
- 8 possible deterministic response paths;
- 4 decomposition candidates;
- 2 lifting experiments;
- 18 tasks requiring more evidence or human review;
- and 6 very-low-success tasks requiring a different strategy or early-exit
  study.

These are recommendations for what to test next, not completed Airline cost
savings. The next step is to generate the proposed changes and test them on
held-out and difficult examples.

Software-engineering benchmarks are producing a different but related signal:
failed coding-agent tasks can cost much more than successful ones, while tests
provide a clear measure of success. That may create an opportunity to predict
expensive failure, change approach or escalate earlier—even where replacing
the coding agent with deterministic software is unrealistic.

Evidence from back-office application tasks is still too small to support a
conclusion. Paid browser-agent experiments remain intentionally paused.

## How the proposed system works

The complete system is intended to:

1. collect existing agent traces, costs and outcomes;
2. group the traces into recurring business tasks;
3. identify stable, unstable and consistently failing work;
4. recommend full crystallisation, decomposition, lifting or another route;
5. use isolated coding agents to propose the necessary software changes;
6. test those changes on held-out, adversarial and matched cases;
7. require independent verification and human safety review before promotion;
8. measure real quality, fallback and cost outcomes;
9. produce clear technical and business reports.

A coding agent can propose a change, but it cannot approve, merge or deploy its
own work.

## Keeping customer-specific procedures valid

A deterministic procedure may stop being safe if the customer's repository,
database schema, tools or policies change. Each customer therefore needs a
logical monitoring worker.

This should not be an expensive AI model constantly reading the entire
repository. It should mostly use code changes, dependency maps, schemas,
contract checks and automated tests. A coding agent is called only when a
relevant change requires investigation or repair.

Each promoted procedure carries a record of the code, tools, policies and tests
under which it was approved. When one of those dependencies changes, the
system revalidates the affected procedure.

If the checks fail:

1. the deterministic path is temporarily disabled;
2. affected work falls back to the full AI agent or a human;
3. a repair agent proposes a change;
4. the repaired procedure is tested independently;
5. it is restored only after the required approval.

Initially, this is what “self-healing” means: automatically detecting a
problem, falling back safely and proposing a repair. It does not mean silently
rewriting and deploying production systems.

## The system will also optimise itself

SOSOG plans to record the traces, costs, failures, tests and review outcomes of
its own investigation and coding agents.

It can then apply the same questions to its internal work:

- Can trace processing become deterministic?
- Can classification become deterministic?
- Can reports be generated from structured evidence?
- Can repeated coding work be partly automated?
- Which tasks still require capable agents or human judgement?

The most important internal metric is not simply tokens saved. It is the total
model, infrastructure and human-review cost required to produce one accepted,
reliable transformation—and the verified lifetime savings that transformation
creates.

This creates a potentially valuable dataset connecting:

> observed agent behaviour → recommended change → implementation attempt →
> verified result → real cost and quality outcome

Over time, that evidence could allow SOSOG to predict the correct treatment
without repeating the full investigation for every new task.

## The commercial path

### 1. AI implementation and cost audit

Initially, SOSOG operates like a technology and implementation consultancy
supported by its own software. It analyses customer traces, identifies
opportunities, implements selected changes and produces evidence-based reports.

### 2. Productised design-partner engagement

The first engagement begins read-only. SOSOG connects spend to outcomes and
ranks the best opportunities. It then selects one narrow, high-volume task
family for a safely controlled shadow test.

### 3. Continuous audit product

SOSOG maintains a live view of cost per outcome, failure concentration,
fallbacks, drift and the validity of existing transformations.

### 4. Controlled optimisation platform

The system proposes new transformations and repairs while keeping deployment
and high-risk changes behind customer review.

### 5. Prediction engine

With enough evidence from real interventions, SOSOG may predict the minimum
level of intelligence and autonomy a new task requires before paying for a
full investigation.

## Likely early customers

The strongest early customer is likely to have:

- a meaningful and direct AI inference bill;
- many repeated task families;
- existing traces and cost information;
- a trustworthy success, correction or escalation signal;
- expensive failures, retries or escalations;
- and a technical owner responsible for AI reliability or gross margin.

Promising categories include AI-native support and operations platforms,
voice and BPO systems, transactional vertical software and coding-agent
companies.

## Why this is exciting

The opportunity is larger than showing companies another token dashboard.
SOSOG has early evidence that it can:

- identify repeated AI work that may not need a full agent;
- replace selected verified model loops with ordinary software;
- preserve a safe agent fallback for uncertain cases;
- partly generate new procedures from traces;
- automate useful portions of tasks that cannot be fully replaced;
- improve an unreliable agent using successful examples;
- and connect these interventions to quality and cost outcomes.

The long-term advantage would not be a static set of scripts. It would be the
growing evidence showing which kinds of agent behaviour should receive which
treatment, how to implement that treatment, and whether it actually worked.

## What is not yet proven

SOSOG has not yet demonstrated:

- a universal customer savings percentage;
- reliable prediction on previously unseen customer work;
- fully automatic generation of every safety rule;
- safe autonomous deployment or repair;
- generalisation across every industry or agent type;
- or that each new customer will require little bespoke engineering.

The decisive next test is not another large benchmark. It is whether SOSOG can
work with a real design partner, identify one expensive and predictable task
segment, safely improve it, measure the result, and repeat the process more
efficiently for the next customer.
