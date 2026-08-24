#!/usr/bin/env bash
set -Eeuo pipefail

readonly agent_user="ubuntu"
readonly agent_group="ubuntu"
readonly default_agent_root="/opt/sosog/codex-agents"
readonly default_repo="/opt/sosog/codex-repo"
readonly default_codex_bin="/opt/sosog/codex-cli/current/bin/codex"

if [[ ${EUID} -ne 0 ]]; then
  printf 'run this bootstrap script as root\n' >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
service_source="${script_dir}/codex-agent@.service"
runner_source="${script_dir}/run_codex_agent.sh"
runtime_bootstrap="${script_dir}/bootstrap_v1_runtime.sh"
config_file="/etc/sosog/codex-agents.env"

for source_file in "$service_source" "$runner_source" "$runtime_bootstrap"; do
  if [[ ! -f $source_file ]]; then
    printf 'required source file does not exist: %s\n' "$source_file" >&2
    exit 2
  fi
done

"$runtime_bootstrap"

if ! getent passwd "$agent_user" >/dev/null; then
  printf 'required service user does not exist: %s\n' "$agent_user" >&2
  exit 2
fi
if ! getent group "$agent_group" >/dev/null; then
  printf 'required service group does not exist: %s\n' "$agent_group" >&2
  exit 2
fi

agent_root=${CODEX_AGENT_ROOT:-$default_agent_root}
repo=${CODEX_AGENT_REPO:-$default_repo}
codex_bin=${CODEX_AGENT_CODEX_BIN:-$default_codex_bin}

case "$agent_root" in
  /*) ;;
  *) printf 'CODEX_AGENT_ROOT must be an absolute path\n' >&2; exit 2 ;;
esac
case "$repo" in
  /*) ;;
  *) printf 'CODEX_AGENT_REPO must be an absolute path\n' >&2; exit 2 ;;
esac
case "$codex_bin" in
  /*) ;;
  *) printf 'CODEX_AGENT_CODEX_BIN must be an absolute path\n' >&2; exit 2 ;;
esac
for path_value in "$agent_root" "$repo" "$codex_bin"; do
  if [[ ! $path_value =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    printf 'configured paths contain unsupported characters: %s\n' "$path_value" >&2
    exit 2
  fi
done

install -d -m 0755 /etc/sosog /usr/local/libexec/sosog
install -d -m 0700 -o "$agent_user" -g "$agent_group" \
  "$agent_root" \
  "$agent_root/jobs" \
  "$agent_root/locks" \
  "$agent_root/manifests" \
  "$agent_root/outcomes" \
  "$agent_root/prompts" \
  "$agent_root/queue" \
  "$agent_root/worktrees"

install -m 0755 -o root -g root "$runner_source" \
  /usr/local/libexec/sosog/run_codex_agent.sh
install -m 0644 -o root -g root "$service_source" \
  /etc/systemd/system/codex-agent@.service

if [[ ! -e $config_file ]]; then
  config_tmp=$(mktemp /etc/sosog/codex-agents.env.XXXXXX)
  trap 'rm -f -- "${config_tmp:-}"' EXIT
  {
    printf 'CODEX_AGENT_ROOT=%s\n' "$agent_root"
    printf 'CODEX_AGENT_REPO=%s\n' "$repo"
    printf 'CODEX_AGENT_CODEX_BIN=%s\n' "$codex_bin"
    printf 'CODEX_AGENT_MAX_CONCURRENCY=3\n'
    printf 'CODEX_AGENT_SLOT_WAIT_SECONDS=21600\n'
    printf 'CODEX_AGENT_TIMEOUT_SECONDS=21600\n'
  } >"$config_tmp"
  chmod 0644 "$config_tmp"
  chown root:root "$config_tmp"
  mv -- "$config_tmp" "$config_file"
  trap - EXIT
else
  printf 'preserving existing configuration: %s\n' "$config_file"
fi

systemctl daemon-reload

if [[ ! -x $codex_bin ]]; then
  printf 'warning: Codex CLI is not executable at %s; install it before starting a worker\n' \
    "$codex_bin" >&2
else
  codex_realpath=$(realpath -e -- "$codex_bin")
  codex_bin_dir="${codex_realpath%/*}"
  codex_package_root="${codex_bin_dir%/bin}"
  for codex_support_file in \
    "${codex_bin_dir}/codex-code-mode-host" \
    "${codex_package_root}/codex-resources/bwrap" \
    "${codex_package_root}/codex-path/rg"; do
    if [[ ! -x $codex_support_file ]]; then
      printf 'warning: Codex standalone support executable is unavailable: %s\n' \
        "$codex_support_file" >&2
    fi
  done
fi
if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'warning: configured repository is not currently a Git worktree: %s\n' \
    "$repo" >&2
fi

printf 'Codex worker infrastructure installed; no worker was enabled, started, or authenticated.\n'
printf 'Configuration: %s\n' "$config_file"
printf 'Queue root: %s/queue\n' "$agent_root"
