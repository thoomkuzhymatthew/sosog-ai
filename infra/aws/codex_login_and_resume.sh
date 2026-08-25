#!/usr/bin/env bash
set -Eeuo pipefail

# Check immediately after a human login instead of waiting up to 12 hours.
# The refresh service also resumes any jobs currently marked blocked_auth.
configured_codex_bin=''
config_file=/etc/sosog/codex-agents.env
if [[ -f $config_file && ! -L $config_file ]]; then
  while IFS='=' read -r key value; do
    if [[ $key == CODEX_AGENT_CODEX_BIN ]]; then
      configured_codex_bin=$value
    fi
  done <"$config_file"
fi
codex_bin=${CODEX_AGENT_CODEX_BIN:-${configured_codex_bin:-/opt/sosog/codex-cli/current/bin/codex}}
if [[ $codex_bin != /* || ! $codex_bin =~ ^/[A-Za-z0-9._/-]+$ || ! -x $codex_bin ]]; then
  printf 'Codex CLI is not a safe executable path: %s\n' "$codex_bin" >&2
  exit 69
fi

"$codex_bin" login && sudo systemctl start sosog-codex-auth-refresh.service
