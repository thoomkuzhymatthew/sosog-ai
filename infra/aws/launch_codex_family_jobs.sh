#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  printf 'run this launcher as root\n' >&2
  exit 2
fi
if [[ $# -ne 1 ]]; then
  printf 'usage: %s BASE_COMMIT\n' "$0" >&2
  exit 2
fi

readonly base_commit=$1
readonly agent_user='ubuntu'
readonly agent_group='ubuntu'
readonly agent_root=${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}
readonly repo=${CODEX_AGENT_REPO:-/opt/sosog/codex-repo}
readonly jobs_file="${repo}/metrics/m18_airline_promotion/coding_jobs/jobs.json"

if [[ ! $base_commit =~ ^[0-9a-f]{40}$ ]]; then
  printf 'BASE_COMMIT must be a full hexadecimal Git commit\n' >&2
  exit 2
fi
for command_name in git jq sha256sum systemctl; do
  command -v "$command_name" >/dev/null || {
    printf 'required command is unavailable: %s\n' "$command_name" >&2
    exit 69
  }
done
if [[ $(git -C "$repo" rev-parse --verify "${base_commit}^{commit}") != "$base_commit" ]]; then
  printf 'base commit is unavailable in %s: %s\n' "$repo" "$base_commit" >&2
  exit 65
fi
if [[ ! -f $jobs_file ]]; then
  printf 'jobs file is missing: %s\n' "$jobs_file" >&2
  exit 66
fi
if [[ $(jq 'length' "$jobs_file") -ne 3 ]]; then
  printf 'expected exactly three reviewed family jobs\n' >&2
  exit 65
fi

while IFS= read -r job; do
  job_id=$(jq -r '.job_id' <<<"$job")
  prompt_rel=$(jq -r '.prompt_path' <<<"$job")
  prompt_sha256=$(jq -r '.prompt_sha256' <<<"$job")
  manifest_rel=$(jq -r '.manifest_path' <<<"$job")
  manifest_sha256=$(jq -r '.manifest_sha256' <<<"$job")
  if [[ ! $job_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    printf 'unsafe job id: %s\n' "$job_id" >&2
    exit 65
  fi
  for relative_path in "$prompt_rel" "$manifest_rel"; do
    if [[ $relative_path == /* || $relative_path == *..* || ! $relative_path =~ ^[A-Za-z0-9._/-]+$ ]]; then
      printf 'unsafe job artifact path: %s\n' "$relative_path" >&2
      exit 65
    fi
  done
  prompt_source="${repo}/${prompt_rel}"
  manifest_source="${repo}/${manifest_rel}"
  if [[ $(sha256sum -- "$prompt_source" | awk '{print $1}') != "$prompt_sha256" ]]; then
    printf 'prompt hash mismatch: %s\n' "$job_id" >&2
    exit 65
  fi
  if [[ $(sha256sum -- "$manifest_source" | awk '{print $1}') != "$manifest_sha256" ]]; then
    printf 'manifest hash mismatch: %s\n' "$job_id" >&2
    exit 65
  fi

  prompt_target="${agent_root}/prompts/${job_id}.md"
  manifest_target="${agent_root}/manifests/${job_id}.json"
  queue_target="${agent_root}/queue/${job_id}.job"
  install -m 0600 -o "$agent_user" -g "$agent_group" "$prompt_source" "$prompt_target"
  install -m 0600 -o "$agent_user" -g "$agent_group" "$manifest_source" "$manifest_target"

  queue_tmp=$(mktemp "${agent_root}/queue/${job_id}.job.XXXXXX")
  {
    printf 'JOB_ID=%s\n' "$job_id"
    printf 'PROMPT_FILE=%s\n' "$prompt_target"
    printf 'JOB_MANIFEST=%s\n' "$manifest_target"
    printf 'JOB_DIR=%s/jobs/%s\n' "$agent_root" "$job_id"
    printf 'WORKTREE_DIR=%s/worktrees/%s\n' "$agent_root" "$job_id"
    printf 'BASE_REF=%s\n' "$base_commit"
    printf 'SANDBOX=workspace-write\n'
  } >"$queue_tmp"
  chmod 0600 "$queue_tmp"
  chown "$agent_user:$agent_group" "$queue_tmp"
  mv -- "$queue_tmp" "$queue_target"
done < <(jq -c '.[]' "$jobs_file")

while IFS= read -r job_id; do
  systemctl start "codex-agent@${job_id}.service"
  printf 'started codex-agent@%s.service\n' "$job_id"
done < <(jq -r '.[].job_id' "$jobs_file")
