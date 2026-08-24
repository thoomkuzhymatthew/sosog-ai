You are an isolated SOSOG coding worker implementing the production bridge
between the generic repair loop and the existing Codex job substrate. Read
`docs/REPAIR_LOOP_DESIGN.md`, Components 4 and 5 of
`docs/V1_ARCHITECTURE_PLAN.md`, all `sosog/repair/` and
`sosog/orchestration/` code/tests, and `infra/aws/run_codex_agent.sh` before
editing. Preserve the existing reviewed-source `enqueue_jobs` API.

Build a dependency-injected `CodexRepairWorker` that implements the
`RepairWorker` protocol without gaining merge/deploy authority.

Requirements:

1. Extend the dispatcher with a secure API for one dynamically generated job
   whose prompt text and manifest mapping are supplied in memory. Apply the
   same root/base-commit/job-id/path/size/hash safety as `enqueue_jobs`;
   validate the manifest job ID, allowed paths, `require_changes`, file/diff
   limits, workspace-write sandbox, and hard-deny network, merge, deploy,
   commit, and push. Atomically freeze prompt, manifest, and queue evidence
   under `agent_root`, owned/mode-compatible with the existing runner. Validate
   everything before any write. Refactor shared private helpers rather than
   weakening the existing path-based API or tests.
2. Add `sosog/repair/codex_worker.py`. Its immutable config contains a safe
   run/job prefix, task rubric, visible-suite description, explicitly allowed
   changed paths, one candidate artifact relative path, roots/base commit,
   attempt/file/diff bounds, and injected enqueue/supervisor/cost-reader
   functions. Each `repair(candidate, feedback)` creates a unique bounded job
   from only the best candidate reference, visible context, allowed paths, and
   `feedback.to_dict()`. It must never accept a locked report, locked manifest
   payload, expected answer, case ID, or raw evaluator output.
3. Enqueue then supervise exactly one attempt. Require the supervisor's passed
   circuit/frozen output, require the configured candidate artifact to be a
   regular non-symlink file, hash its bytes into the returned
   `CandidateReference`, and return a `RepairWorkerResult` with cost supplied
   by a required injected measured-cost reader. Missing/invalid cost is an
   error, never silently zero. No merge, commit, push, deployment, or client
   repo mutation outside the isolated worktree/frozen artifact.
4. Avoid double-starting a worker: make the dispatcher/controller start
   boundary explicit and backwards compatible (existing callers still start
   by default).
5. Prompt generation must be deterministic and JSON-safe. Tests must prove
   secrets placed only in unavailable locked-report-shaped fixtures cannot
   appear in the generated prompt, while sanitized aggregate feedback does.

Use dependency-free `unittest` tests and no live systemd/network/database.
Cover dynamic-dispatch validation-before-write, permission denial, hashes and
atomic queue shape, compatibility of existing enqueue behavior, deterministic
prompt/job IDs, candidate hashing, symlink/missing artifact rejection,
supervisor failure, required measured cost, and zero merge/deploy calls. Run
focused tests and the available full suite.

Do not modify AWS shell/service files, economics, persistence, reporting,
vertical adapters, or architecture docs. Do not commit, merge, push, deploy,
access credentials, or enable network. This is a proposal requiring
independent review.
