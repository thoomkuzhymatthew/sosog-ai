#!/usr/bin/env bash
set -uo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 RUN_DIR REPO_ROOT TAU_ROOT PROPOSAL_ROOT EVALUATOR_DIR" >&2
  exit 2
fi

run_dir=$1
repo_root=$2
tau_root=$3
proposal_root=$4
evaluator_dir=$5
python_bin="$tau_root/.venv/bin/python"
evaluator="$run_dir/input/evaluator/evaluate_airline_generated.py"

umask 027
mkdir -p "$run_dir/output"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/started-at.txt"
printf 'running\n' > "$run_dir/status.tmp"
mv "$run_dir/status.tmp" "$run_dir/status"

"$python_bin" "$evaluator" \
  --repo-root "$repo_root" \
  --tau-root "$tau_root" \
  --proposal-root "$proposal_root" \
  --evaluator-dir "$evaluator_dir" \
  --output "$run_dir/output/results.json" \
  --report "$run_dir/output/report.md" \
  > "$run_dir/output/evaluation.log" 2>&1
exit_code=$?

printf '%s\n' "$exit_code" > "$run_dir/exit-code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/finished-at.txt"
find "$run_dir/input" "$proposal_root" "$run_dir/output" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > "$run_dir/sha256sums.txt"

if [[ $exit_code -eq 0 ]]; then
  printf 'succeeded\n' > "$run_dir/status.tmp"
else
  printf 'failed\n' > "$run_dir/status.tmp"
fi
mv "$run_dir/status.tmp" "$run_dir/status"
exit "$exit_code"
