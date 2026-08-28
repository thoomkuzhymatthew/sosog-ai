#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 RUN_DIR REPO_ROOT PACKAGE_ROOT EVALUATOR MODEL_ID" >&2
  exit 2
fi

run_dir=$1
repo_root=$2
package_root=$3
evaluator=$4
model_id=$5
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
write_status evaluating_locked_natural_language
install -d -m 0750 "$run_dir/output"

/usr/bin/python3 "$evaluator" \
  --repo-root "$repo_root" \
  --package-root "$package_root" \
  --output "$run_dir/output/results.json" \
  --model-id "$model_id" \
  >"$run_dir/output/evaluation.log" 2>&1

find "$run_dir/input" "$run_dir/output" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum >"$run_dir/sha256sums.txt"
printf '0\n' >"$run_dir/exit-code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ >"$run_dir/finished-at.txt"
write_status completed
finished=true
trap - EXIT
