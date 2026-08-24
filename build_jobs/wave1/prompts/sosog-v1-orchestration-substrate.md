You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 5) — read that file's
"## 5. Job/worker orchestration substrate" section, including the "Codex
OAuth session-expiry fix" subsection, before starting. This job has two
objectives; **do the first one completely and correctly before spending time
on the second** — if you run short on budget, a fully-working auth fix with a
stubbed-out orchestration library is a better outcome than both done
partially.

Your current directory is a detached SOSOG Git worktree.

## Objective 1 (priority): fix the Codex OAuth session-expiry problem

**Root cause:** `infra/aws/run_codex_agent.sh` invokes `codex exec --sandbox
{read-only|workspace-write}` with no writable-root override. Codex's own
workspace-write sandbox restricts filesystem writes to the job's worktree
directory — it does not include `~/.codex/auth.json`, which lives outside
that tree. An in-sandbox token refresh therefore cannot persist back to disk,
so the on-disk OAuth token ages until it hard-expires (`401 token_expired`)
and never self-recovers. Switching to `OPENAI_API_KEY` auth is explicitly
ruled out (cost) — fix this by running the refresh outside the sandbox
instead, on its own schedule, centralized in one place (not per-worker —
concurrent workers each attempting their own refresh risks invalidating each
other's session, since OAuth providers commonly rotate the refresh token on
every use).

Build:

1. **`infra/aws/refresh_codex_auth.sh`** — a standalone script, run as
   `ubuntu`, that invokes the Codex CLI **without any `--sandbox` flag at
   all** (unsandboxed — this is safe because it only exercises the CLI's own
   trusted auth/login logic, never agent-generated code) to trigger a token
   validation/refresh and let the write-back to `~/.codex/auth.json` succeed
   normally. On success, atomically write
   `{"status":"valid","checked_at":"<ISO8601 UTC>"}` to
   `${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}/auth-status.json` (write to a
   `.tmp` file then `mv`, matching the atomic-write pattern already used
   throughout `run_codex_agent.sh` — read that file for the exact idiom). On
   failure (the refresh token itself is dead and needs a human to
   `codex login` again), write
   `{"status":"blocked_auth","checked_at":"<ISO8601 UTC>","detail":"<short reason>"}`
   instead and exit non-zero — do not retry-loop inside this script; retrying
   cannot fix a dead refresh token, and the timer below controls retry
   cadence.

2. **`infra/aws/sosog-codex-auth-refresh.service`** and
   **`infra/aws/sosog-codex-auth-refresh.timer`** — a systemd oneshot
   service + timer pair, modeled on the hardening style already used in
   `infra/aws/codex-agent@.service` (read it for the security-hardening
   directives to reuse — `NoNewPrivileges`, `ProtectSystem`, etc. — but this
   unit does **not** need the Codex-specific sandboxing directives, since it
   deliberately runs Codex CLI unsandboxed). `User=ubuntu`. Timer:
   `OnBootSec=5m`, `OnUnitActiveSec=12h`. Service: `ExecStart` runs
   `refresh_codex_auth.sh`.

3. **Preflight in `infra/aws/run_codex_agent.sh`:** before the block that
   invokes `timeout ... "$codex_bin" exec ...` (search for that invocation —
   it's wrapped in a `set +e` / `set -e` pair with `codex_status=$?`
   captured), add a check that reads
   `${agent_root}/auth-status.json` (this file may not exist yet on a fresh
   host — treat that the same as `blocked_auth`, fail closed). If its
   `status` field is not exactly `"valid"`, or the file's `checked_at`
   timestamp is more than 13 hours old (stale — the refresh timer itself may
   be down), **do not attempt the `codex exec` call at all.** Instead write a
   new distinct job status `blocked_auth` (reuse the existing
   `write_status` helper function already defined in this file) and exit
   cleanly with a non-zero status that will NOT count against
   `StartLimitBurst` the way a genuine execution failure should — read how
   `codex-agent@.service`'s `Restart=on-failure`/`StartLimitBurst=3`
   interacts with this file's exit codes and choose an exit code/mechanism
   consistent with "don't burn retry budget on a problem retrying can't
   fix" (the file already has a precedent for this kind of fail-closed,
   non-retriable exit — look for how it handles unrecoverable setup errors
   elsewhere in the file, e.g. exit code 73). Make sure this preflight runs
   early enough that it does not consume a worker concurrency slot for the
   full job timeout — it should fail fast, before or immediately after
   acquiring the slot lock, not after.

4. **`infra/aws/codex_login_and_resume.sh`** — a one-line-to-run wrapper:
   `codex login && sudo systemctl start sosog-codex-auth-refresh.service`
   (as an actual script, with a comment explaining why: this exists so a
   human completing a manual re-login also immediately triggers the refresh
   check, instead of waiting up to 12 hours for the timer's next tick — the
   refresh service in turn is what un-blocks any `blocked_auth` jobs; you do
   not need to build the resume-scanning logic itself in this job, only this
   entry-point script — document in a code comment that a future job adds
   the "scan `agent_root/jobs/*/status` for `blocked_auth` and restart them"
   logic to `refresh_codex_auth.sh` once more of the orchestration layer
   exists).

## Objective 2 (secondary, do after objective 1 is solid): orchestration library skeleton

5. **`sosog/__init__.py`** — minimal package marker (module docstring only).
   Note: a sibling job running concurrently may also create this same file
   independently from the same base commit — expected, a human resolves the
   trivial overlap by keeping either copy when applying diffs.

6. **`sosog/orchestration/dispatcher.py`** — a Python function
   `enqueue_jobs(jobs, agent_root, repo, base_commit)` that generalizes what
   `infra/aws/launch_codex_family_jobs.sh` does (read that file in full — it
   validates job IDs, verifies prompt/manifest SHA-256 hashes against a
   frozen source, writes queue files in the exact `KEY=VALUE` format
   `infra/aws/run_codex_agent.sh` expects, and starts each
   `codex-agent@<job_id>.service`), except: accept an arbitrary list of job
   specs (not read from one hardcoded `jobs.json` path) and don't hardcode a
   count of exactly 3. Keep every safety check the bash version has (path
   traversal rejection, hash verification, job-id format validation) — port
   the logic faithfully, this is a generalization, not a rewrite of the
   safety properties. It's acceptable for this function to shell out to
   `systemctl start codex-agent@<job_id>.service` via `subprocess` rather
   than reimplementing systemd interaction.

7. **`sosog/orchestration/controller.py`** — for this job, a minimal stub is
   sufficient: define the function signature
   `run_repair_controller(job_id, agent_root, repo_root, vertical_adapter, allowed_changed_paths) -> ControllerResult`
   (a small dataclass or similar for `ControllerResult` is fine) with a
   clear docstring describing the intended behavior (start worker, poll
   `agent_root/jobs/<job_id>/status` until `succeeded`/`failed`/timeout,
   verify the circuit breaker passed, freeze only the manifest-allowed
   changed files into an isolated directory) referencing
   `scripts/run_airline_flight_change_repair_controller.sh` as the bash
   version this will eventually replace — read that script to make sure the
   docstring accurately describes its actual behavior. A full implementation
   is explicitly out of scope for this job; a future job (component 4) fills
   this in once it exists to call it.

## Constraints

- Do not modify `infra/aws/codex-agent@.service`,
  `infra/aws/launch_codex_family_jobs.sh`, `infra/aws/bootstrap_codex_agents.sh`,
  or any `sosog-m1{3,4,5}-*-resume.service`/`.timer` file — the resume-timer
  collapse is separate, later work, not part of this job.
- Do not change any behavior of `run_codex_agent.sh` other than adding the
  auth preflight described above — every other line should be untouched.

You may change exactly these paths:
- `infra/aws/run_codex_agent.sh`
- `infra/aws/sosog-codex-auth-refresh.service`
- `infra/aws/sosog-codex-auth-refresh.timer`
- `infra/aws/refresh_codex_auth.sh`
- `infra/aws/codex_login_and_resume.sh`
- `sosog/__init__.py`
- `sosog/orchestration/__init__.py`
- `sosog/orchestration/dispatcher.py`
- `sosog/orchestration/controller.py`
- `sosog/orchestration/tests/__init__.py`
- `sosog/orchestration/tests/test_dispatcher.py`

The host will reject any other changed path, more than 11 changed files, or a
diff above 1200000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Add focused tests for `dispatcher.py`'s validation logic (job-id format,
path-traversal rejection, hash mismatch detection) using fake inputs — no
live systemd or network access is available to you. Run the tests. In your
final report: state clearly whether objective 1 and/or objective 2 were
completed, list changed files, test commands run and their results, and any
risks a human reviewer should check — especially around the auth preflight's
interaction with `StartLimitBurst`, since a mistake there could either mask a
real failure as `blocked_auth` or burn retries on an unrecoverable auth
problem. Your work is a proposal and cannot approve itself for merging.
