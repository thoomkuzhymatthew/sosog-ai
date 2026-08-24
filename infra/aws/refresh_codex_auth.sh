#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
agent_root=${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}
codex_bin=${CODEX_AGENT_CODEX_BIN:-/opt/sosog/codex-cli/current/bin/codex}
status_file="${agent_root}/auth-status.json"
status_tmp="${status_file}.tmp.$$"
refresh_output=$(mktemp)
trap 'rm -f -- "$refresh_output" "$status_tmp"' EXIT

resume_blocked_jobs() {
  local job_status_file job_id unit

  if [[ ! -f $status_file || -L $status_file ]] ||
    ! jq -e '.status == "valid"' "$status_file" >/dev/null 2>&1; then
    printf 'Refusing to resume jobs without a valid authentication status\n' >&2
    return 1
  fi

  for job_status_file in "$agent_root"/jobs/*/status; do
    [[ -f $job_status_file && ! -L $job_status_file ]] || continue
    [[ $(<"$job_status_file") == blocked_auth ]] || continue

    job_id=${job_status_file%/status}
    job_id=${job_id##*/}
    if [[ ! $job_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]]; then
      printf 'Skipping authentication-blocked job with unsafe ID: %s\n' "$job_id" >&2
      continue
    fi
    unit="codex-agent@${job_id}.service"
    printf 'Restarting authentication-blocked job %s (%s)\n' "$job_id" "$unit"
    if systemctl start "$unit"; then
      printf 'Restart succeeded for authentication-blocked job %s (%s)\n' \
        "$job_id" "$unit"
    else
      printf 'Restart failed for authentication-blocked job %s (%s)\n' \
        "$job_id" "$unit" >&2
    fi
  done
}

if [[ ${1:-} == --resume-blocked && $# -eq 1 ]]; then
  resume_blocked_jobs
  exit 0
fi
if (( $# != 0 )); then
  printf 'usage: %s [--resume-blocked]\n' "$0" >&2
  exit 2
fi

checked_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
if "$codex_bin" exec --skip-git-repo-check --json \
  'Do not use tools. Reply with the single word OK.' >"$refresh_output" 2>&1; then
  jq -cn --arg checked_at "$checked_at" \
    '{status:"valid",checked_at:$checked_at}' >"$status_tmp"
  mv -- "$status_tmp" "$status_file"
  exit 0
fi

detail=$(tail -n 1 -- "$refresh_output" | tr '\r\n' ' ' | cut -c 1-240)
if [[ -z $detail ]]; then
  detail='Codex authentication refresh failed; run codex login'
fi
jq -cn --arg checked_at "$checked_at" --arg detail "$detail" \
  '{status:"blocked_auth",checked_at:$checked_at,detail:$detail}' >"$status_tmp"
mv -- "$status_tmp" "$status_file"
exit 1
