#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 RUN_DIR JOB_ID AGENT_ROOT REPO_ROOT TAU_ROOT EVALUATOR" >&2
  exit 2
fi

run_dir=$1
job_id=$2
agent_root=$3
repo_root=$4
tau_root=$5
evaluator=$6
worker_unit="codex-agent@${job_id}.service"
status_file="$run_dir/status"
finished=false

umask 027
exec >>"$run_dir/controller.log" 2>&1

write_status() {
  printf '%s\n' "$1" >"$status_file.tmp"
  mv "$status_file.tmp" "$status_file"
}

finish_on_exit() {
  exit_code=$?
  if [[ $finished != true ]]; then
    printf '%s\n' "$exit_code" >"$run_dir/exit-code.txt"
    date -u +%Y-%m-%dT%H:%M:%SZ >"$run_dir/finished-at.txt"
    write_status failed
  fi
}
trap finish_on_exit EXIT

date -u +%Y-%m-%dT%H:%M:%SZ >"$run_dir/started-at.txt"
write_status worker_running
printf '%s starting worker %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$worker_unit"
systemctl start "$worker_unit"

deadline=$((SECONDS + 21600))
while :; do
  worker_status='not_started'
  if [[ -f "$agent_root/jobs/$job_id/status" ]]; then
    worker_status=$(<"$agent_root/jobs/$job_id/status")
  fi
  active_state=$(systemctl show "$worker_unit" --property=ActiveState --value)
  if [[ $worker_status == succeeded ]]; then
    break
  fi
  if [[ $active_state == failed ]]; then
    printf '%s worker exhausted retries with status=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$worker_status"
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    printf '%s worker/controller deadline exceeded\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 124
  fi
  sleep 10
done

trace=$(find "$agent_root/jobs/$job_id/traces" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)
test "$(jq -r .status "$trace/circuit-breaker.json")" = passed
write_status freezing_proposal
install -d -m 0750 "$run_dir/frozen-proposal" "$run_dir/worker-trace"
tar -C "$agent_root/worktrees/$job_id" -cf - -T "$trace/changed-files.txt" \
  | tar -C "$run_dir/frozen-proposal" -xf -
cp -a "$trace/." "$run_dir/worker-trace/"

write_status evaluating_locked_final
install -d -m 0750 "$run_dir/output"
"$tau_root/.venv/bin/python" "$evaluator" \
  --repo-root "$repo_root" \
  --tau-root "$tau_root" \
  --proposal "$run_dir/frozen-proposal/crystallized/airline/flight_change.py" \
  --output "$run_dir/output/results.json" \
  --report "$run_dir/output/report.md" \
  >"$run_dir/output/evaluation.log" 2>&1

find "$run_dir/input" "$run_dir/frozen-proposal" "$run_dir/worker-trace" "$run_dir/output" \
  -type f -print0 | sort -z | xargs -0 sha256sum >"$run_dir/sha256sums.txt"
printf '0\n' >"$run_dir/exit-code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ >"$run_dir/finished-at.txt"
write_status completed
finished=true
trap - EXIT
printf '%s controller completed\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
