#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'usage: %s WORKER_NAME\n' "$0" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

worker_name=$1
if [[ ! $worker_name =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  printf 'unsafe worker name: %s\n' "$worker_name" >&2
  exit 2
fi

agent_root=${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}
repo=${CODEX_AGENT_REPO:-/opt/sosog/codex-repo}
codex_bin=${CODEX_AGENT_CODEX_BIN:-/opt/sosog/codex-cli/current/bin/codex}
max_concurrency=${CODEX_AGENT_MAX_CONCURRENCY:-3}
slot_wait_seconds=${CODEX_AGENT_SLOT_WAIT_SECONDS:-21600}
job_timeout_seconds=${CODEX_AGENT_TIMEOUT_SECONDS:-21600}

for path_value in "$agent_root" "$repo" "$codex_bin"; do
  if [[ $path_value != /* ]]; then
    printf 'configured paths must be absolute: %s\n' "$path_value" >&2
    exit 2
  fi
done
for integer_value in "$max_concurrency" "$slot_wait_seconds" "$job_timeout_seconds"; do
  if [[ ! $integer_value =~ ^[1-9][0-9]*$ ]]; then
    printf 'concurrency and timeout values must be positive integers\n' >&2
    exit 2
  fi
done
if (( max_concurrency > 32 )); then
  printf 'CODEX_AGENT_MAX_CONCURRENCY cannot exceed 32\n' >&2
  exit 2
fi
if [[ ! -x $codex_bin ]]; then
  printf 'Codex CLI is not executable: %s\n' "$codex_bin" >&2
  exit 69
fi
for required_command in cmp flock git jq realpath sha256sum stat tar timeout; do
  if ! command -v "$required_command" >/dev/null; then
    printf 'required command is unavailable: %s\n' "$required_command" >&2
    exit 69
  fi
done
codex_realpath=$(realpath -e -- "$codex_bin")
codex_bin_dir="${codex_realpath%/*}"
codex_package_root="${codex_bin_dir%/bin}"
codex_bwrap="${codex_package_root}/codex-resources/bwrap"
for codex_runtime_path in \
  "$codex_package_root" \
  "$codex_realpath" \
  "${codex_bin_dir}/codex-code-mode-host" \
  "$codex_bwrap" \
  "${codex_package_root}/codex-path/rg"; do
  if [[ ! -x $codex_runtime_path ]]; then
    printf 'Codex standalone support executable is unavailable: %s\n' \
      "$codex_runtime_path" >&2
    exit 69
  fi
  runtime_owner=$(stat -c '%u:%g' -- "$codex_runtime_path")
  runtime_mode=$(stat -c '%a' -- "$codex_runtime_path")
  if [[ $runtime_owner != '0:0' ]] || (( (8#$runtime_mode & 8#022) != 0 )); then
    printf 'Codex runtime path is not root-owned and non-writable: %s\n' \
      "$codex_runtime_path" >&2
    exit 69
  fi
done
if ! "$codex_bin" sandbox -- /bin/true >/dev/null 2>&1; then
  printf 'Codex Bubblewrap sandbox preflight failed\n' >&2
  exit 69
fi

queue_dir="${agent_root}/queue"
prompt_root="${agent_root}/prompts"
jobs_root="${agent_root}/jobs"
worktrees_root="${agent_root}/worktrees"
locks_root="${agent_root}/locks"
queue_file="${queue_dir}/${worker_name}.job"

for required_dir in "$queue_dir" "$prompt_root" "$jobs_root" "$worktrees_root" "$locks_root"; do
  if [[ ! -d $required_dir ]]; then
    printf 'required agent directory does not exist: %s\n' "$required_dir" >&2
    exit 69
  fi
done
if [[ ! -f $queue_file || -L $queue_file ]]; then
  printf 'worker queue file must be a regular, non-symlink file: %s\n' "$queue_file" >&2
  exit 66
fi

job_id=''
prompt_file=''
job_manifest=''
job_dir=''
worktree_dir=''
base_ref=''
sandbox='workspace-write'
declare -A seen_keys=()

while IFS= read -r line || [[ -n $line ]]; do
  if [[ -z $line || $line == \#* ]]; then
    continue
  fi
  if [[ $line != *=* ]]; then
    printf 'invalid queue line (expected KEY=VALUE): %s\n' "$line" >&2
    exit 65
  fi
  key=${line%%=*}
  value=${line#*=}
  if [[ -n ${seen_keys[$key]:-} ]]; then
    printf 'duplicate queue key: %s\n' "$key" >&2
    exit 65
  fi
  seen_keys[$key]=1
  case "$key" in
    JOB_ID) job_id=$value ;;
    PROMPT_FILE) prompt_file=$value ;;
    JOB_MANIFEST) job_manifest=$value ;;
    JOB_DIR) job_dir=$value ;;
    WORKTREE_DIR) worktree_dir=$value ;;
    BASE_REF) base_ref=$value ;;
    SANDBOX) sandbox=$value ;;
    *) printf 'unknown queue key: %s\n' "$key" >&2; exit 65 ;;
  esac
done <"$queue_file"

if [[ ! $job_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]]; then
  printf 'unsafe or missing JOB_ID\n' >&2
  exit 65
fi
if [[ -z $prompt_file || $prompt_file != /* ]]; then
  printf 'PROMPT_FILE must be an absolute path\n' >&2
  exit 65
fi
if [[ -z $job_manifest || $job_manifest != /* ]]; then
  printf 'JOB_MANIFEST must be an absolute path\n' >&2
  exit 65
fi
if [[ -z $base_ref ]]; then
  printf 'BASE_REF is required\n' >&2
  exit 65
fi
if [[ $sandbox != 'read-only' && $sandbox != 'workspace-write' ]]; then
  printf 'SANDBOX must be read-only or workspace-write\n' >&2
  exit 65
fi

expected_job_dir="${jobs_root}/${job_id}"
expected_worktree_dir="${worktrees_root}/${job_id}"
if [[ $job_dir != "$expected_job_dir" ]]; then
  printf 'JOB_DIR must equal %s\n' "$expected_job_dir" >&2
  exit 65
fi
if [[ $worktree_dir != "$expected_worktree_dir" ]]; then
  printf 'WORKTREE_DIR must equal %s\n' "$expected_worktree_dir" >&2
  exit 65
fi

resolved_prompt=$(realpath -e -- "$prompt_file")
resolved_prompt_root=$(realpath -e -- "$prompt_root")
manifest_root="${agent_root}/manifests"
resolved_manifest=$(realpath -e -- "$job_manifest")
resolved_manifest_root=$(realpath -e -- "$manifest_root")
case "$resolved_prompt" in
  "$resolved_prompt_root"/*) ;;
  *) printf 'PROMPT_FILE must resolve below %s\n' "$resolved_prompt_root" >&2; exit 65 ;;
esac
if [[ ! -f $resolved_prompt ]]; then
  printf 'PROMPT_FILE is not a regular file: %s\n' "$resolved_prompt" >&2
  exit 66
fi
if [[ ! -s $resolved_prompt ]]; then
  printf 'PROMPT_FILE is empty: %s\n' "$resolved_prompt" >&2
  exit 65
fi
case "$resolved_manifest" in
  "$resolved_manifest_root"/*) ;;
  *) printf 'JOB_MANIFEST must resolve below %s\n' "$resolved_manifest_root" >&2; exit 65 ;;
esac
if [[ ! -f $resolved_manifest || -L $resolved_manifest ]]; then
  printf 'JOB_MANIFEST must be a regular, non-symlink file: %s\n' "$resolved_manifest" >&2
  exit 66
fi
if ! jq -e \
  --arg job_id "$job_id" \
  '.schema_version == 2 and .job_id == $job_id and
   (.allowed_changed_paths | type == "array" and length > 0) and
   (.allowed_changed_paths | all(type == "string" and length > 0)) and
   (.max_changed_files | type == "number" and . >= 1) and
   (.max_diff_bytes | type == "number" and . >= 1) and
   (.require_changes | type == "boolean") and
   .permissions.may_commit == false and
   .permissions.may_merge == false and
   .permissions.may_push == false and
   .permissions.may_deploy == false and
   .permissions.network_access == false' \
  "$resolved_manifest" >/dev/null; then
  printf 'JOB_MANIFEST failed schema or permission validation: %s\n' "$resolved_manifest" >&2
  exit 65
fi

repo=$(realpath -e -- "$repo")
if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'configured repository is not a Git worktree: %s\n' "$repo" >&2
  exit 69
fi

queue_sha256=$(sha256sum -- "$queue_file" | awk '{print $1}')
prompt_sha256=$(sha256sum -- "$resolved_prompt" | awk '{print $1}')
manifest_sha256=$(sha256sum -- "$resolved_manifest" | awk '{print $1}')

exec {job_lock_fd}>"${locks_root}/job-${job_id}.lock"
if ! flock -n "$job_lock_fd"; then
  printf 'job is already running: %s\n' "$job_id" >&2
  exit 75
fi

mkdir -p -- "$job_dir/input" "$job_dir/traces"
for job_path in "$job_dir" "$job_dir/input" "$job_dir/traces"; do
  if [[ -L $job_path ]]; then
    printf 'job artifact paths cannot be symlinks: %s\n' "$job_path" >&2
    exit 73
  fi
done
status_file="${job_dir}/status"
write_status() {
  local status_value=$1
  local status_tmp="${status_file}.tmp.$$"
  printf '%s\n' "$status_value" >"$status_tmp"
  mv -- "$status_tmp" "$status_file"
}

auth_status_file="${agent_root}/auth-status.json"
auth_checked_epoch=''
if [[ -f $auth_status_file && ! -L $auth_status_file ]] &&
  jq -e '.status == "valid" and (.checked_at | type == "string")' \
    "$auth_status_file" >/dev/null 2>&1; then
  auth_checked_at=$(jq -r '.checked_at' "$auth_status_file")
  auth_checked_epoch=$(date -u -d "$auth_checked_at" +%s 2>/dev/null || true)
fi
current_epoch=$(date -u +%s)
if [[ -z $auth_checked_epoch ]] || (( auth_checked_epoch > current_epoch )) ||
  (( current_epoch - auth_checked_epoch > 13 * 60 * 60 )); then
  write_status 'blocked_auth'
  printf 'Codex authentication is missing, invalid, or stale; job blocked: %s\n' \
    "$job_id" >&2
  # Restart=on-failure retries every nonzero exit and consumes StartLimitBurst.
  # blocked_auth is a job-level failure but a successful service invocation;
  # only the centralized auth recovery path should start this unit again.
  exit 0
fi

queue_snapshot="${job_dir}/input/queue.job"
prompt_snapshot="${job_dir}/input/prompt.md"
manifest_snapshot="${job_dir}/input/manifest.json"
queue_hash_file="${job_dir}/input/queue.sha256"
prompt_hash_file="${job_dir}/input/prompt.sha256"
manifest_hash_file="${job_dir}/input/manifest.sha256"
base_ref_file="${job_dir}/input/base-ref.txt"
base_commit_file="${job_dir}/input/base-commit.txt"
worker_file="${job_dir}/input/worker.txt"
sandbox_file="${job_dir}/input/sandbox.txt"

if [[ -e $prompt_snapshot || -e $queue_snapshot ]]; then
  for input_file in \
    "$queue_snapshot" "$prompt_snapshot" "$manifest_snapshot" "$queue_hash_file" "$prompt_hash_file" "$manifest_hash_file" \
    "$base_ref_file" "$base_commit_file" "$worker_file" "$sandbox_file"; do
    if [[ ! -f $input_file ]]; then
      printf 'job input snapshot is incomplete: %s\n' "$input_file" >&2
      exit 73
    fi
  done
  if ! cmp -s -- "$queue_file" "$queue_snapshot"; then
    printf 'queue changed after job initialization: %s\n' "$job_id" >&2
    exit 65
  fi
  if ! cmp -s -- "$resolved_prompt" "$prompt_snapshot"; then
    printf 'prompt changed after job initialization: %s\n' "$job_id" >&2
    exit 65
  fi
  if ! cmp -s -- "$resolved_manifest" "$manifest_snapshot"; then
    printf 'manifest changed after job initialization: %s\n' "$job_id" >&2
    exit 65
  fi
  if [[ $(<"$queue_hash_file") != "$queue_sha256" || $(<"$prompt_hash_file") != "$prompt_sha256" || $(<"$manifest_hash_file") != "$manifest_sha256" ]]; then
    printf 'job input hash mismatch: %s\n' "$job_id" >&2
    exit 65
  fi
  if [[ $(<"$base_ref_file") != "$base_ref" || $(<"$worker_file") != "$worker_name" || $(<"$sandbox_file") != "$sandbox" ]]; then
    printf 'queue metadata changed after job initialization: %s\n' "$job_id" >&2
    exit 65
  fi
  base_commit=$(<"$base_commit_file")
  if [[ -f $status_file && $(<"$status_file") == 'succeeded' ]]; then
    printf 'job already succeeded; queue retained unchanged: %s\n' "$job_id"
    exit 0
  fi
else
  if ! base_commit=$(git -C "$repo" rev-parse --verify --end-of-options "${base_ref}^{commit}"); then
    printf 'BASE_REF does not resolve to a commit: %s\n' "$base_ref" >&2
    exit 65
  fi
  cp -- "$queue_file" "$queue_snapshot"
  cp -- "$resolved_prompt" "$prompt_snapshot"
  cp -- "$resolved_manifest" "$manifest_snapshot"
  printf '%s\n' "$queue_sha256" >"$queue_hash_file"
  printf '%s\n' "$prompt_sha256" >"$prompt_hash_file"
  printf '%s\n' "$manifest_sha256" >"$manifest_hash_file"
  printf '%s\n' "$base_ref" >"$base_ref_file"
  printf '%s\n' "$base_commit" >"$base_commit_file"
  printf '%s\n' "$worker_name" >"$worker_file"
  printf '%s\n' "$sandbox" >"$sandbox_file"
  chmod 0400 "$queue_snapshot" "$prompt_snapshot" "$manifest_snapshot" "$queue_hash_file" \
    "$prompt_hash_file" "$manifest_hash_file" "$base_ref_file" "$base_commit_file" "$worker_file" \
    "$sandbox_file"
  chmod 0500 "${job_dir}/input"
fi

slot_fd=''
slot_number=''
slot_deadline=$((SECONDS + slot_wait_seconds))
while [[ -z $slot_fd ]]; do
  for ((candidate = 1; candidate <= max_concurrency; candidate += 1)); do
    exec {candidate_fd}>"${locks_root}/slot-${candidate}.lock"
    if flock -n "$candidate_fd"; then
      slot_fd=$candidate_fd
      slot_number=$candidate
      break
    fi
    exec {candidate_fd}>&-
  done
  if [[ -z $slot_fd ]]; then
    if (( SECONDS >= slot_deadline )); then
      printf 'no worker slot became available within %s seconds\n' "$slot_wait_seconds" >&2
      exit 75
    fi
    sleep 2
  fi
done

if [[ -e $worktree_dir ]]; then
  if [[ ! -d $worktree_dir || ! -e $worktree_dir/.git ]]; then
    printf 'refusing to reuse unexpected worktree path: %s\n' "$worktree_dir" >&2
    exit 73
  fi
  worktree_commit=$(git -C "$worktree_dir" rev-parse --verify HEAD)
  if [[ $worktree_commit != "$base_commit" ]]; then
    printf 'existing worktree is based on %s, expected %s\n' "$worktree_commit" "$base_commit" >&2
    exit 73
  fi
else
  git -C "$repo" worktree add --detach "$worktree_dir" "$base_commit"
fi
branch_name=$(git -C "$worktree_dir" symbolic-ref --short -q HEAD || printf 'DETACHED')

attempt_number=1
while :; do
  attempt_name=$(printf '%03d' "$attempt_number")
  trace_dir="${job_dir}/traces/${attempt_name}"
  if mkdir -- "$trace_dir" 2>/dev/null; then
    break
  fi
  ((attempt_number += 1))
  if (( attempt_number > 999 )); then
    printf 'too many recorded attempts for job: %s\n' "$job_id" >&2
    exit 75
  fi
done

runner_log="${trace_dir}/runner.log"
events_file="${trace_dir}/events.jsonl"
trace_file="${trace_dir}/trace.jsonl"
progress_file="${trace_dir}/progress.log"
final_file="${trace_dir}/final.md"
command_evidence_file="${trace_dir}/command-evidence.jsonl"
changed_files_file="${trace_dir}/changed-files.txt"
circuit_breaker_file="${trace_dir}/circuit-breaker.json"
untracked_bundle_file="${trace_dir}/untracked-files.tar.gz"
start_epoch=$(date -u +%s)
started_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
trace_finalized=false
events_appended=false

log() {
  local message=$1
  local timestamp
  timestamp=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
  printf '%s %s\n' "$timestamp" "$message" | tee -a "$runner_log" >&2
}

append_codex_events() {
  if [[ $events_appended == false && -f $events_file ]]; then
    cat -- "$events_file" >>"$trace_file"
    events_appended=true
  fi
}

enforce_circuit_breakers() {
  local changed_count max_changed_files max_diff_bytes require_changes
  local tracked_bytes untracked_bytes total_diff_bytes path path_size
  local violation=''

  if [[ $(git -C "$worktree_dir" rev-parse --verify HEAD) != "$base_commit" ]]; then
    violation='worker changed the Git commit'
  fi
  {
    git -C "$worktree_dir" diff --name-only --no-ext-diff HEAD
    git -C "$worktree_dir" ls-files --others --exclude-standard
  } | LC_ALL=C sort -u >"$changed_files_file"
  changed_count=$(awk 'NF {count += 1} END {print count + 0}' "$changed_files_file")
  max_changed_files=$(jq -r '.max_changed_files' "$manifest_snapshot")
  max_diff_bytes=$(jq -r '.max_diff_bytes' "$manifest_snapshot")
  require_changes=$(jq -r '.require_changes' "$manifest_snapshot")

  if [[ -z $violation && $require_changes == true && $changed_count -eq 0 ]]; then
    violation='job produced no changed files'
  fi
  if [[ -z $violation && $changed_count -gt $max_changed_files ]]; then
    violation="changed file count ${changed_count} exceeds ${max_changed_files}"
  fi

  tracked_bytes=$(git -C "$worktree_dir" diff --binary --no-ext-diff HEAD | wc -c)
  untracked_bytes=0
  while IFS= read -r path; do
    [[ -n $path ]] || continue
    if [[ ! $path =~ ^[A-Za-z0-9._/-]+$ || $path == /* || $path == *..* ]]; then
      violation="unsafe changed path: ${path}"
      break
    fi
    if ! jq -e --arg path "$path" '.allowed_changed_paths | index($path) != null' \
      "$manifest_snapshot" >/dev/null; then
      violation="changed path is outside the manifest: ${path}"
      break
    fi
    if [[ -L "$worktree_dir/$path" ]]; then
      violation="changed path is a symbolic link: ${path}"
      break
    fi
    if [[ ! -e "$worktree_dir/$path" ]]; then
      violation="deleting an allowed path is not permitted: ${path}"
      break
    fi
    if ! git -C "$worktree_dir" ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
      path_size=$(stat -c '%s' -- "$worktree_dir/$path")
      untracked_bytes=$((untracked_bytes + path_size))
    fi
  done <"$changed_files_file"
  total_diff_bytes=$((tracked_bytes + untracked_bytes))
  if [[ -z $violation && $total_diff_bytes -gt $max_diff_bytes ]]; then
    violation="diff size ${total_diff_bytes} exceeds ${max_diff_bytes}"
  fi

  if [[ -n $violation ]]; then
    jq -cn \
      --arg status 'failed' \
      --arg violation "$violation" \
      --argjson changed_files "$changed_count" \
      --argjson diff_bytes "$total_diff_bytes" \
      '{status:$status,violation:$violation,changed_files:$changed_files,diff_bytes:$diff_bytes}' \
      >"$circuit_breaker_file"
    log "circuit breaker rejected job=${job_id}: ${violation}"
    return 1
  fi
  jq -cn \
    --arg status 'passed' \
    --argjson changed_files "$changed_count" \
    --argjson diff_bytes "$total_diff_bytes" \
    '{status:$status,changed_files:$changed_files,diff_bytes:$diff_bytes}' \
    >"$circuit_breaker_file"
}

finalize_trace() {
  local exit_status=$1
  local finished_at end_epoch duration_seconds final_sha256 diff_sha256
  local status_value outcome_status usage_events untracked_bundle_sha256 trace_sha256 outcome_file

  if [[ $trace_finalized == true ]]; then
    return
  fi
  trace_finalized=true
  trap - EXIT
  set +e

  append_codex_events
  finished_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
  end_epoch=$(date -u +%s)
  duration_seconds=$((end_epoch - start_epoch))
  printf '%s\n' "$finished_at" >"${trace_dir}/finished-at.txt"
  printf '%s\n' "$exit_status" >"${trace_dir}/exit-code.txt"

  git -C "$worktree_dir" status --short --untracked-files=all >"${trace_dir}/git-status.txt"
  git -C "$worktree_dir" diff --binary --no-ext-diff >"${trace_dir}/tracked-changes.patch"
  git -C "$worktree_dir" diff --stat --no-ext-diff >"${trace_dir}/git-diff.stat"
  git -C "$worktree_dir" ls-files --others --exclude-standard >"${trace_dir}/untracked-files.txt"
  if [[ -s "${trace_dir}/untracked-files.txt" && -f $circuit_breaker_file ]] &&
    jq -e '.status == "passed"' "$circuit_breaker_file" >/dev/null 2>&1; then
    tar -czf "$untracked_bundle_file" -C "$worktree_dir" \
      --verbatim-files-from -T "${trace_dir}/untracked-files.txt"
  fi
  jq -c \
    'select(.type == "item.completed" and .item.type == "command_execution") | .item' \
    "$events_file" >"$command_evidence_file" 2>/dev/null

  final_sha256=''
  if [[ -s $final_file ]]; then
    final_sha256=$(sha256sum -- "$final_file" | awk '{print $1}')
  fi
  diff_sha256=$(sha256sum -- "${trace_dir}/tracked-changes.patch" | awk '{print $1}')
  untracked_bundle_sha256=''
  if [[ -f $untracked_bundle_file ]]; then
    untracked_bundle_sha256=$(sha256sum -- "$untracked_bundle_file" | awk '{print $1}')
  fi
  usage_events=$(jq -cs \
    '[.[] | select(.type == "turn.completed" and .usage != null) | .usage]' \
    "$events_file" 2>/dev/null)
  if [[ -z $usage_events ]]; then
    usage_events='[]'
  fi
  if (( exit_status == 0 )) && [[ -n $final_sha256 ]]; then
    status_value='succeeded'
    outcome_status='PASSED'
  else
    status_value='failed'
    outcome_status='FAILED'
  fi

  jq -cn \
    --arg type 'sosog.job.finished' \
    --arg job_id "$job_id" \
    --arg worker "$worker_name" \
    --arg attempt "$attempt_name" \
    --arg timestamp "$finished_at" \
    --arg status "$status_value" \
    --arg final_sha256 "$final_sha256" \
    --arg diff_sha256 "$diff_sha256" \
    --arg untracked_bundle_sha256 "$untracked_bundle_sha256" \
    --argjson exit_status "$exit_status" \
    --argjson duration_seconds "$duration_seconds" \
    --argjson usage_events "$usage_events" \
    '{type:$type,job_id:$job_id,worker:$worker,attempt:$attempt,timestamp:$timestamp,status:$status,exit_status:$exit_status,duration_seconds:$duration_seconds,final_sha256:$final_sha256,tracked_diff_sha256:$diff_sha256,untracked_bundle_sha256:$untracked_bundle_sha256,usage_events:$usage_events}' \
    >>"$trace_file"

  write_status "$status_value"
  trace_sha256=$(sha256sum -- "$trace_file" | awk '{print $1}')
  outcome_file="${agent_root}/outcomes/${job_id}-${attempt_name}.json"
  if [[ ! -e $outcome_file ]]; then
    jq -cn \
      --arg job_id "$job_id" \
      --arg attempt "$attempt_name" \
      --arg recorded_at "$finished_at" \
      --arg status "$outcome_status" \
      --arg trace_path "$trace_file" \
      --arg trace_sha256 "$trace_sha256" \
      --arg manifest_sha256 "$manifest_sha256" \
      --arg base_commit "$base_commit" \
      '{schema_version:1,stage:"AGENT_ATTEMPT",job_id:$job_id,attempt:$attempt,recorded_at:$recorded_at,status:$status,trace:{path:$trace_path,sha256:$trace_sha256},manifest_sha256:$manifest_sha256,base_commit:$base_commit}' \
      >"$outcome_file"
    chmod 0400 "$outcome_file"
  fi
  log "finalized trace=${trace_dir} status=${status_value} exit=${exit_status} duration_seconds=${duration_seconds}"
  find "$trace_dir" -type f -exec chmod 0400 {} +
  find "$trace_dir" -type d -exec chmod 0500 {} +
  set -e
}

on_exit() {
  local exit_status=$?
  finalize_trace "$exit_status"
}
trap on_exit EXIT

printf '%s\n' "$started_at" >"${trace_dir}/started-at.txt"
printf '%s\n' "$slot_number" >"${trace_dir}/slot.txt"
jq -cn \
  --arg type 'sosog.job.started' \
  --arg job_id "$job_id" \
  --arg worker "$worker_name" \
  --arg attempt "$attempt_name" \
  --arg timestamp "$started_at" \
  --arg prompt_file "$resolved_prompt" \
  --arg prompt_sha256 "$prompt_sha256" \
  --arg manifest_file "$resolved_manifest" \
  --arg manifest_sha256 "$manifest_sha256" \
  --arg queue_file "$queue_file" \
  --arg queue_sha256 "$queue_sha256" \
  --arg base_ref "$base_ref" \
  --arg base_commit "$base_commit" \
  --arg worktree "$worktree_dir" \
  --arg branch "$branch_name" \
  --arg sandbox "$sandbox" \
  '{type:$type,job_id:$job_id,worker:$worker,attempt:$attempt,timestamp:$timestamp,prompt:{path:$prompt_file,sha256:$prompt_sha256},manifest:{path:$manifest_file,sha256:$manifest_sha256},queue:{path:$queue_file,sha256:$queue_sha256},git:{base_ref:$base_ref,base_commit:$base_commit,worktree:$worktree,branch:$branch},sandbox:$sandbox}' \
  >"$trace_file"
write_status 'running'
log "starting job=${job_id} worker=${worker_name} attempt=${attempt_name} slot=${slot_number} sandbox=${sandbox}"

set +e
(
  cd -- "$worktree_dir"
  timeout --signal=INT --kill-after=120 "$job_timeout_seconds" \
    "$codex_bin" exec \
      --ephemeral \
      --ignore-user-config \
      --sandbox "$sandbox" \
      -c 'approval_policy="never"' \
      -c 'sandbox_workspace_write.network_access=false' \
      --json \
      --output-last-message "$final_file" \
      - <"$prompt_snapshot"
) >"$events_file" 2>"$progress_file"
codex_status=$?
set -e
append_codex_events

if (( codex_status != 0 )); then
  log "Codex exited with status ${codex_status}; queue retained for bounded systemd retry"
  exit "$codex_status"
fi
if [[ ! -s $final_file ]]; then
  log 'Codex reported success without a final message'
  exit 70
fi
if ! enforce_circuit_breakers; then
  exit 65
fi

log "completed job=${job_id}; queue retained; review worktree=${worktree_dir} trace=${trace_dir}"
finalize_trace 0
exit 0
