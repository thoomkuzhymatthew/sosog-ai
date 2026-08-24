#!/usr/bin/env bash
set -Eeuo pipefail

umask 077
agent_root=${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}
codex_bin=${CODEX_AGENT_CODEX_BIN:-/opt/sosog/codex-cli/current/bin/codex}
status_file="${agent_root}/auth-status.json"
status_tmp="${status_file}.tmp.$$"
refresh_output=$(mktemp)
trap 'rm -f -- "$refresh_output" "$status_tmp"' EXIT

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
