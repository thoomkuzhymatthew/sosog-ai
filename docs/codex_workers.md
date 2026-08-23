# Codex workers on one EC2 machine

This is a prototype runner for several named Codex coding workers on one
trusted EC2 host. A controller writes one explicit queue manifest per worker
and starts the matching systemd instance. Each job gets a detached Git
worktree and immutable, per-attempt evidence.

It deliberately does **not** authenticate, merge, push, deploy, enable a
service, or grant unrestricted host access.

## Safety model

- The service runs as the unprivileged `ubuntu` user.
- A queue manifest may select only `read-only` or `workspace-write`.
- The runner invokes `codex exec` with the versioned configuration override
  `approval_policy="never"`. Anything outside the selected sandbox therefore
  fails closed instead of waiting for an unattended approval.
- Network access for commands executed by the agent is disabled. Codex can
  still contact its model provider, but repository code and tests cannot make
  outbound connections through the Codex workspace sandbox.
- `danger-full-access`, `--yolo`, and sandbox bypass flags are not accepted.
- Jobs are pinned to the commit resolved on their first attempt. Agents work
  in detached worktrees and cannot commit, merge, push, or modify the shared
  repository's Git metadata through the workspace sandbox.
- systemd limits each worker to 4 GiB, 512 tasks, six hours of agent execution,
  and at most three starts within 30 minutes. It restarts only after failure.
- A machine-wide lock pool enforces the configured maximum number of active
  Codex invocations even when more systemd instances are started.

OpenAI's documentation describes `codex exec` as the non-interactive interface
for scripts and CI, recommends the least-permissive sandbox needed, and supports
JSONL event output plus a separate final-message file. See [Non-interactive
mode](https://learn.chatgpt.com/docs/non-interactive-mode) and [agent approvals
and security](https://learn.chatgpt.com/docs/agent-approvals-security).

## Install without starting anything

Prerequisites:

- a trusted Linux EC2 host with systemd, Git, `flock`, `jq`, `realpath`,
  `sha256sum`, and `timeout`;
- this repository available at `/opt/sosog/codex-repo` as a real Git worktree;
- the Codex CLI executable at `/usr/local/bin/codex` and its matching
  `codex-code-mode-host` executable in the same resolved `bin` directory;
- an existing `ubuntu` user and group.

The standalone installer is a package, not a single binary. If you copy the
CLI into `/usr/local/bin`, copy its matching host too:

```bash
release_bin=/home/ubuntu/.codex/packages/standalone/current/bin
sudo install -m 0755 "$release_bin/codex" /usr/local/bin/codex
sudo install -m 0755 "$release_bin/codex-code-mode-host" \
  /usr/local/bin/codex-code-mode-host
```

Keeping `/home/ubuntu/.local/bin/codex` as the configured executable is also
valid because the installer-managed symlink resolves into the complete
standalone package.

Review the scripts and then run:

```bash
sudo env CODEX_AGENT_REPO=/opt/sosog/codex-repo \
  /opt/sosog/codex-repo/infra/aws/bootstrap_codex_agents.sh
```

The bootstrap creates `/opt/sosog/codex-agents`, installs the runner and unit,
and reloads systemd. It does not start or enable any worker. It also preserves
an existing `/etc/sosog/codex-agents.env` instead of overwriting it.

To use different absolute paths on the first installation:

```bash
sudo env \
  CODEX_AGENT_ROOT=/srv/sosog/codex-agents \
  CODEX_AGENT_REPO=/srv/sosog/sosog-ai \
  CODEX_AGENT_CODEX_BIN=/usr/local/bin/codex \
  /srv/sosog/sosog-ai/infra/aws/bootstrap_codex_agents.sh
```

If `CODEX_AGENT_ROOT` changes, add a systemd drop-in that sets
`WorkingDirectory` to that root. The paths used by queue manifests must also
match it exactly.

## Authentication boundary

The runner never performs a login and contains no credential.

For the trusted prototype, Codex automatically reuses the cached login owned by
the `ubuntu` user. If that user has already completed `codex login`, no key is
added to a manifest or repository file. Confirm the account outside the worker:

```bash
sudo -u ubuntu -H codex login status
```

Treat `/home/ubuntu/.codex/auth.json`, when file-backed credential storage is
used, as a password. Do not copy it into the repository, queue, job artifacts,
or logs.

For genuinely unattended automation, use an API key, enterprise Codex access
token, or preferably short-lived workload identity supplied through a proper
secret boundary. OpenAI's [authentication documentation](https://learn.chatgpt.com/docs/auth)
recommends API-key authentication for programmatic Codex CLI workflows, and its
[non-interactive guidance](https://learn.chatgpt.com/docs/non-interactive-mode#authenticate-in-automation)
says API keys are the normal default for automation. Do not put
`OPENAI_API_KEY`, `CODEX_API_KEY`, or any other secret in
`/etc/sosog/codex-agents.env`: agent-run repository code must not inherit a
long-lived key. Use a dedicated credential broker/proxy or workload identity
before turning this prototype into a continuous service.

## Configure concurrency and resource use

`/etc/sosog/codex-agents.env` contains non-secret settings:

```dotenv
CODEX_AGENT_ROOT=/opt/sosog/codex-agents
CODEX_AGENT_REPO=/opt/sosog/codex-repo
CODEX_AGENT_CODEX_BIN=/usr/local/bin/codex
CODEX_AGENT_MAX_CONCURRENCY=3
CODEX_AGENT_SLOT_WAIT_SECONDS=21600
CODEX_AGENT_TIMEOUT_SECONDS=21600
```

Three workers is the conservative default for a 16 GiB host: each unit has a
4 GiB hard limit, leaving roughly 4 GiB for the OS and controller. Start at two
when jobs run memory-heavy integration tests. Increasing the lock-pool number
does not change the systemd memory limit, account rate limits, or subscription
allowance.

After changing the environment file, restart only the affected workers. To
change per-worker memory or runtime limits, create a reviewed systemd drop-in
and reduce concurrency correspondingly.

## Queue and start a job

Worker and job identifiers may contain letters, numbers, dots, underscores,
and hyphens. A worker reads only this exact queue path:

```text
/opt/sosog/codex-agents/queue/<worker>.job
```

The prompt must be a non-empty file below
`/opt/sosog/codex-agents/prompts`. Queue files use literal `KEY=VALUE` lines;
they are parsed as data and never sourced as shell.

Example for a write-enabled crystallisation worker:

```bash
worker=airline-crystallise-1
job=airline-policy-001
root=/opt/sosog/codex-agents

sudo -u ubuntu install -m 0600 /path/to/reviewed-prompt.md \
  "$root/prompts/$job.md"
sudo -u ubuntu install -m 0600 /path/to/reviewed-manifest.json \
  "$root/manifests/$job.json"

manifest=$(mktemp)
trap 'rm -f -- "$manifest"' EXIT
printf '%s\n' \
  "JOB_ID=$job" \
  "PROMPT_FILE=$root/prompts/$job.md" \
  "JOB_MANIFEST=$root/manifests/$job.json" \
  "JOB_DIR=$root/jobs/$job" \
  "WORKTREE_DIR=$root/worktrees/$job" \
  'BASE_REF=main' \
  'SANDBOX=workspace-write' >"$manifest"
sudo -u ubuntu install -m 0600 "$manifest" "$root/queue/$worker.job"
rm -f -- "$manifest"
trap - EXIT

sudo systemctl start "codex-agent@$worker.service"
```

Use `SANDBOX=read-only` for classification, analysis, and reporting jobs that
should not edit the repository. Use `workspace-write` only for script creation,
tests, or proposed code changes.

Do not reuse a `JOB_ID`. A failed systemd attempt may reuse its existing
worktree, but the runner rejects changed prompts, base references, workers, or
sandbox modes for an initialized job. To revise a task, create a new job ID.

## Monitor and review

```bash
systemctl --no-pager --full status codex-agent@airline-crystallise-1.service
journalctl -u codex-agent@airline-crystallise-1.service -f
find /opt/sosog/codex-agents/jobs/airline-policy-001 -maxdepth 3 -type f -print
```

Every attempt writes a new trace under:

```text
jobs/<job-id>/traces/<attempt-number>/
```

The runner never reuses or overwrites an attempt number. At finalization it
makes every trace file read-only and the trace directory non-writable. The
directory contains:

- `trace.jsonl`: a runner start record, the complete Codex JSONL event stream,
  and a runner finish record with outcome, duration, hashes, and any usage
  fields that Codex exposed;
- `events.jsonl`: the unmodified machine-readable Codex event stream;
- `progress.log`: Codex progress and diagnostic output;
- `final.md`: the final agent response;
- `command-evidence.jsonl`: completed command records, including test commands
  and their output when Codex exposed them;
- `git-status.txt`, `git-diff.stat`, `tracked-changes.patch`,
  `untracked-files.txt`, and `changed-files.txt`;
- `circuit-breaker.json`, recording whether the manifest's exact file and
  diff budgets passed;
- `runner.log`, timestamps, slot number, and exit code.

The start record identifies the job, prompt, manifest and queue paths and
SHA-256 hashes, base reference and commit, detached worktree/branch state,
sandbox, worker, attempt, and start time. The finish record includes elapsed seconds, exit
status, final-output hash, diff hash, and `turn.completed` usage objects. Token
and cost fields are recorded only when the installed Codex CLI exposes them;
the runner does not estimate missing usage or prices.

The detached worktree remains the authoritative result for human or controller
review. The runner does not stage or commit untracked files. It also never
deletes or moves the prompt or queue file: hash-locked copies live in
`jobs/<job-id>/input`, and the originals stay at their explicit paths. Restarting
a successful job is idempotent and exits without another Codex invocation.

Before a job can succeed, the runner enforces the manifest's exact changed-file
allowlist, changed-file count, diff-size budget, non-empty-change requirement,
unchanged base commit and prohibition on changed symlinks. Passing these checks
permits independent verification; it is not a promotion decision.

On failure, systemd performs bounded retries and each retry creates another
trace. After the start limit is reached, inspect the last trace before manually
running `systemctl reset-failed` and starting the worker again.

## Launch the reviewed Airline family jobs

The Airline launch uses three family-level derivation packs rather than one
job per benchmark task. Controller-owned evaluation hashes are pinned in each
manifest without exposing held-out task IDs in the worker prompt.

```bash
revision=$(git -C /opt/sosog/codex-repo rev-parse HEAD)
sudo env \
  CODEX_AGENT_REPO=/opt/sosog/codex-repo \
  /opt/sosog/codex-repo/infra/aws/launch_codex_family_jobs.sh "$revision"
```

The launcher verifies prompt and manifest hashes, pins every worktree to the
supplied full commit and starts exactly three systemd instances. It never
merges or deploys worker output.

## Trace retention

There is intentionally no automatic trace, queue, prompt, or worktree cleanup.
Retain traces at least through technical review, customer-report sign-off, and
the measurement window for realized savings. Before routine host cleanup, copy
the complete `jobs/<job-id>` directory to the investigation artifact store with
checksums and a defined retention policy. If customer code or inputs are
sensitive, apply that customer's deletion and access policy instead of a global
default. Only a separate, explicitly approved retention process should remove
local artifacts.

## Controller responsibilities

The initial controller can be a small deterministic process that:

1. validates and atomically installs reviewed prompt and queue files;
2. starts a named systemd instance;
3. watches `status` and the unit state;
4. parses `events.jsonl` and `final.md` into investigation records;
5. reviews the worktree and runs independent held-out verification;
6. creates a branch or PR only after deterministic checks pass.

Do not let a coding worker decide that its own transformation is correct. The
classification, generated code, business report, and technical report are
proposals; the separate verification engine owns promotion.
