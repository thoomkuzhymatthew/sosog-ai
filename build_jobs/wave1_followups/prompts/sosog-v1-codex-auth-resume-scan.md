You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. A prior job built `infra/aws/refresh_codex_auth.sh`
(already merged into this base commit — read it in full before starting) and
deliberately deferred one piece: automatically resuming jobs that were parked
in a `blocked_auth` state once authentication recovers. This job completes
that piece.

Your current directory is a detached SOSOG Git worktree.

## Background

`infra/aws/run_codex_agent.sh` now has a preflight check (read it — search
for where it reads `auth-status.json`) that puts a job into a `blocked_auth`
status instead of attempting execution when Codex's OAuth session is known to
be expired. `infra/aws/refresh_codex_auth.sh` runs on a timer, refreshes the
token, and writes `{"status":"valid",...}` or `{"status":"blocked_auth",...}`
to `${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}/auth-status.json`. Nothing
currently notices when that status flips from `blocked_auth` back to `valid`
and restarts the jobs that were waiting on it — they stay parked until a
human manually restarts each one.

## Task

Extend `infra/aws/refresh_codex_auth.sh`: after a successful refresh (status
written as `"valid"`), scan `${agent_root}/jobs/*/status` for any job whose
status file currently reads `blocked_auth`, and for each one run
`systemctl start codex-agent@<job_id>.service` (where `<job_id>` is the
directory name under `${agent_root}/jobs/`) to resume it. Do this scan **only**
on a transition into `"valid"` status (i.e., only meaningful right after a
successful refresh) — do not scan and restart on every single timer tick if
the previous check was already `"valid"`, since that would restart nothing
new but adds pointless systemctl calls; you may implement this either by
tracking the previous status or by making the restart idempotent/safe to
call repeatedly (starting an already-running or already-succeeded service is
harmless, so a simpler "always scan when status is valid" implementation is
acceptable if simpler — use your judgment and explain your choice in the
report).

Also handle: a job status file that reads `blocked_auth` but whose systemd
unit is already active (e.g., a race where it got restarted by something
else already) — starting an already-active unit is a systemd no-op, not an
error, so this does not need special handling, but confirm this assumption
by reading how `systemctl start` behaves on an already-active unit rather
than assuming.

Log each restart attempt (job ID and outcome) to stdout/the script's normal
log stream — this script already runs under a systemd service with journal
logging per the prior job's work, so a `printf`/`log` line matching the
existing logging convention in the file is sufficient; no new logging
infrastructure needed.

## Constraints

- Do not modify `infra/aws/run_codex_agent.sh`,
  `infra/aws/sosog-codex-auth-refresh.service`,
  `infra/aws/sosog-codex-auth-refresh.timer`,
  `infra/aws/codex_login_and_resume.sh`, or any file outside the one listed
  below.
- Do not change the script's existing behavior for the refresh/write-status
  logic itself — only add the new scan-and-restart behavior after a
  successful refresh.

You may change exactly this path:
- `infra/aws/refresh_codex_auth.sh`

The host will reject any other changed path, more than 1 changed file, or a
diff above 300000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

There is no live systemd or network access in this sandbox to test the
actual restart calls end to end — verify shell syntax
(`bash -n infra/aws/refresh_codex_auth.sh`) and, if practical, write a small
local test using fake status files and a stubbed-out `systemctl` command
(e.g., a fake `systemctl` shell function or script placed earlier in `PATH`
during the test) to verify the scanning logic identifies the right jobs
without needing real systemd. In your final report: describe exactly how you
tested the scan logic given no real systemd is available, list the change,
and note any risk a human reviewer should check before this runs for real
(especially: could this ever restart a job that should have stayed stopped
for a different reason, not just auth). Your work is a proposal and cannot
approve itself for merging.
