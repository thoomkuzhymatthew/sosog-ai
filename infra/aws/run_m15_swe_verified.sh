#!/usr/bin/env bash
set -euo pipefail

repo_dir=${SOSOG_REPO_DIR:-/opt/sosog/sosog-ai}
swe_dir=/opt/sosog/SWE-bench
venv=/opt/sosog/swe-venv
artifact_dir=/opt/sosog/artifacts/m15-swe-verified
run_stamp=${SOSOG_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
primary_model=bedrock/us.anthropic.claude-sonnet-4-6
fallback_model=bedrock/global.anthropic.claude-sonnet-4-6
haiku_model=bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0
selection="$artifact_dir/swe_verified_30_task_ids.json"

export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export SOSOG_ARTIFACT_BUCKET=${SOSOG_ARTIFACT_BUCKET:-sosog-bedrock-batch-769377363988}
export SOSOG_ARTIFACT_PREFIX=${SOSOG_ARTIFACT_PREFIX:-vertical-expansion}
export MSWEA_GLOBAL_COST_LIMIT=650
export MSWEA_COST_TRACKING=ignore_errors
mkdir -p "$artifact_dir"
source "$repo_dir/infra/aws/load_research_env.sh"

sync_artifacts() {
  /opt/sosog/runtime/bin/aws s3 sync "$artifact_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/m15-swe-verified-${run_stamp}/" \
    --no-progress --only-show-errors || true
}
trap sync_artifacts EXIT

"$venv/bin/pip" install --upgrade boto3 'psycopg[binary]' >/dev/null
"$venv/bin/python" "$repo_dir/scripts/select_swe_tasks.py" \
  --count 30 --output "$selection"
mapfile -t golden_ids < <(jq -r '.golden_task_ids[]' "$selection")
golden_id="m15-golden-${run_stamp}"
cd "$swe_dir"
"$venv/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench_Verified --split test \
  --instance_ids "${golden_ids[@]}" --predictions_path gold --max_workers 3 \
  --run_id "$golden_id" --report_dir "$artifact_dir"
golden_report=$(find "$artifact_dir" -maxdepth 1 -name "*.$golden_id.json" -print -quit)
jq -e --argjson expected "${#golden_ids[@]}" \
  '.resolved_instances == $expected and .error_instances == 0' "$golden_report" >/dev/null
cp "$golden_report" "$artifact_dir/GOLDEN_REPLAY.json"
sync_artifacts

workers_now() {
  if /opt/sosog/runtime/bin/aws s3api head-object --bucket "$SOSOG_ARTIFACT_BUCKET" \
    --key "${SOSOG_ARTIFACT_PREFIX}/m13-airline-20260821T164841Z/baseline_summary.json" \
    >/dev/null 2>&1; then
    echo 2
  else
    echo 1
  fi
}

run_generation() {
  local phase=$1 trial=$2 output_dir=$3 filter=$4 slice=$5 model=${6:-$primary_model}
  local workers
  workers=$(workers_now)
  local args=(swebench --subset verified --split test --output "$output_dir" \
    --workers "$workers" --model "$model" \
    -c swebench.yaml -c agent.cost_limit=3 -c model.model_kwargs.temperature=0 \
    -c model.cost_tracking=ignore_errors -c model.set_cache_control=default_end)
  [[ -n $filter ]] && args+=(--filter "$filter")
  [[ -n $slice ]] && args+=(--slice "$slice")
  "$venv/bin/mini-extra" "${args[@]}" 2>&1 \
    | tee "$artifact_dir/${phase}_t${trial}_${slice//:/-}_${model#bedrock/}.log"
}

retry_quota_failures() {
  local phase=$1 trial=$2 output_dir=$3 route_map=$4 allowed_ids=$5
  local retry_ids="$artifact_dir/${phase}_t${trial}_retry_ids.json"
  local retry_filter
  retry_filter=$("$venv/bin/python" "$repo_dir/scripts/swe_retry_filter.py" \
    "$output_dir" --ids-output "$retry_ids" --only-ids "$allowed_ids")
  "$venv/bin/python" "$repo_dir/scripts/mark_swe_routes.py" \
    "$output_dir/preds.json" "$route_map" "$primary_model"
  if [[ -n $retry_filter ]]; then
    run_generation "$phase" "$trial" "$output_dir" "$retry_filter" "" "$fallback_model"
    "$venv/bin/python" "$repo_dir/scripts/mark_swe_routes.py" \
      "$output_dir/preds.json" "$route_map" "$fallback_model" --only "$retry_ids"
  fi
}

evaluate_and_export() {
  local phase=$1 trial=$2 output_dir=$3 route_map=$4 ids_json=$5 suffix=$6
  mapfile -t eval_ids < <(jq -r '.[]' "$ids_json")
  local eval_id="m15-${phase}-t${trial}-${suffix}-${run_stamp}"
  "$venv/bin/python" -m swebench.harness.run_evaluation \
    --dataset_name SWE-bench/SWE-bench_Verified --split test \
    --instance_ids "${eval_ids[@]}" --predictions_path "$output_dir/preds.json" \
    --max_workers 4 --run_id "$eval_id" --report_dir "$artifact_dir"
  local report
  report=$(find "$artifact_dir" -maxdepth 1 -name "*.$eval_id.json" -print -quit)
  "$venv/bin/python" "$repo_dir/scripts/export_swe_research.py" \
    --output-dir "$output_dir" --report "$report" --route-map "$route_map" \
    --run-id "$eval_id" --phase "$phase" --trial "$trial" --only-ids "$ids_json" \
    --output-jsonl "$artifact_dir/${phase}_t${trial}_${suffix}.jsonl" \
    --summary "$artifact_dir/${phase}_t${trial}_${suffix}_summary.json"
  /opt/sosog/runtime/bin/aws s3 sync "$output_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/${eval_id}/raw/" \
    --no-progress --only-show-errors
  sync_artifacts
}

baseline_output="$artifact_dir/baseline-output"
baseline_routes="$artifact_dir/baseline_model_routes.json"
baseline_ids="$artifact_dir/baseline_ids.json"
jq '.task_ids' "$selection" >"$baseline_ids"
baseline_filter=$(jq -r '.task_ids | "^(" + join("|") + ")$"' "$selection")
if [[ ! -f $artifact_dir/baseline_t0_selected30_summary.json ]]; then
  if [[ ! -f $baseline_output/preds.json || ! -f $baseline_routes ]]; then
    run_generation baseline 0 "$baseline_output" "$baseline_filter" ""
    retry_quota_failures baseline 0 "$baseline_output" "$baseline_routes" "$baseline_ids"
  fi
  evaluate_and_export baseline 0 "$baseline_output" "$baseline_routes" \
    "$baseline_ids" selected30
fi

corpus_filter=$(jq -r '.task_ids | "^(" + join("|") + ")$"' "$selection")
jq '.task_ids' "$selection" >"$artifact_dir/corpus_ids.json"
for trial in $(seq 0 4); do
  corpus_output="$artifact_dir/corpus-t${trial}-output"
  corpus_routes="$artifact_dir/corpus_t${trial}_model_routes.json"
  if [[ ! -f $artifact_dir/corpus_t${trial}_all_summary.json ]]; then
    run_generation corpus "$trial" "$corpus_output" "$corpus_filter" ""
    retry_quota_failures corpus "$trial" "$corpus_output" "$corpus_routes" \
      "$artifact_dir/corpus_ids.json"
    evaluate_and_export corpus "$trial" "$corpus_output" "$corpus_routes" \
      "$artifact_dir/corpus_ids.json" all
  fi
done

haiku_filter=$(jq -r '.haiku_task_ids | "^(" + join("|") + ")$"' "$selection")
haiku_output="$artifact_dir/haiku-output"
haiku_routes="$artifact_dir/haiku_model_routes.json"
jq '.haiku_task_ids' "$selection" >"$artifact_dir/haiku_ids.json"
if [[ ! -f $artifact_dir/haiku_t0_all_summary.json ]]; then
  run_generation haiku 0 "$haiku_output" "$haiku_filter" "" "$haiku_model"
  "$venv/bin/python" "$repo_dir/scripts/mark_swe_routes.py" \
    "$haiku_output/preds.json" "$haiku_routes" "$haiku_model"
  evaluate_and_export haiku 0 "$haiku_output" "$haiku_routes" \
    "$artifact_dir/haiku_ids.json" all
fi

summary_paths=("$artifact_dir/baseline_t0_selected30_summary.json")
for trial in $(seq 0 4); do
  summary_paths+=("$artifact_dir/corpus_t${trial}_all_summary.json")
done
summary_paths+=("$artifact_dir/haiku_t0_all_summary.json")
total_cost=$(jq -s '[.[].cost_usd] | add // 0' "${summary_paths[@]}")
if awk -v cost="$total_cost" 'BEGIN {exit !(cost > 650)}'; then
  echo "SWE Verified track exceeded its $650 budget: $total_cost" >&2
  exit 1
fi
printf 'complete cost_usd=%s\n' "$total_cost" >"$artifact_dir/status.txt"
sync_artifacts
/usr/sbin/shutdown -h +1 || true
