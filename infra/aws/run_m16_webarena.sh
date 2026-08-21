#!/usr/bin/env bash
set -euo pipefail

repo_dir=${SOSOG_REPO_DIR:-/opt/sosog/sosog-ai}
source_dir=/opt/sosog/webarena
venv=/opt/sosog/webarena-venv
artifact_dir=/opt/sosog/artifacts/m16-webarena
results_root=/opt/sosog/webarena-results
run_stamp=${SOSOG_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
primary_model=bedrock/us.anthropic.claude-sonnet-4-6
fallback_model=bedrock/global.anthropic.claude-sonnet-4-6
haiku_model=bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0

export AWS_DEFAULT_REGION=us-east-1 AWS_REGION=us-east-1
export SHOPPING=http://127.0.0.1:7770
export SHOPPING_ADMIN=http://127.0.0.1:7780/admin
export REDDIT=http://127.0.0.1:9999
export GITLAB=http://127.0.0.1:8023
export MAP=http://127.0.0.1:3000
export WIKIPEDIA=http://127.0.0.1:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing
export HOMEPAGE=http://127.0.0.1:4399
export SOSOG_BEDROCK_FALLBACK_MODEL=$fallback_model
export SOSOG_ARTIFACT_BUCKET=${SOSOG_ARTIFACT_BUCKET:-sosog-bedrock-batch-769377363988}
export SOSOG_ARTIFACT_PREFIX=${SOSOG_ARTIFACT_PREFIX:-vertical-expansion}
mkdir -p "$artifact_dir" "$results_root"
source "$repo_dir/infra/aws/load_research_env.sh"

sync_artifacts() {
  /opt/sosog/runtime/bin/aws s3 sync "$artifact_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/m16-webarena-${run_stamp}/" \
    --no-progress --only-show-errors || true
  /opt/sosog/runtime/bin/aws s3 sync "$results_root" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/m16-webarena-${run_stamp}/raw/" \
    --no-progress --only-show-errors || true
}
trap sync_artifacts EXIT

cd "$source_dir"
git apply --check "$repo_dir/patches/webarena-bedrock-litellm.patch" \
  && git apply "$repo_dir/patches/webarena-bedrock-litellm.patch" || true
"$venv/bin/pip" install --upgrade litellm boto3 'psycopg[binary]' >/dev/null
"$venv/bin/python" scripts/generate_test_data.py
"$venv/bin/python" "$repo_dir/scripts/verify_webarena_golden.py" \
  config_files/test.raw.json --output "$artifact_dir/GOLDEN_REPLAY.json"
"$venv/bin/python" "$repo_dir/scripts/select_webarena_tasks.py" \
  config_files/test.raw.json --output "$artifact_dir/webarena_40_task_ids.json"
mkdir -p .auth
"$venv/bin/python" browser_env/auto_login.py
sync_artifacts

run_phase() {
  local phase=$1 trial=$2 ids_query=$3 model=${4:-$primary_model}
  local run_id="m16-webarena-${phase}-t${trial}-${run_stamp}"
  local result_dir="$results_root/${phase}-t${trial}"
  local usage_log="$artifact_dir/${phase}_t${trial}_usage.jsonl"
  mkdir -p "$result_dir" "$artifact_dir/${phase}_t${trial}_rows"
  mapfile -t task_ids < <(jq -r "$ids_query" "$artifact_dir/webarena_40_task_ids.json")
  for task_id in "${task_ids[@]}"; do
    task_log="$artifact_dir/${phase}_t${trial}_task${task_id}.log"
    export SOSOG_WEB_TASK_ID=$task_id SOSOG_LLM_USAGE_LOG=$usage_log
    set +e
    "$venv/bin/python" run.py --instruction_path agent/prompts/jsons/p_cot_id_actree_2s.json \
      --test_start_idx "$task_id" --test_end_idx "$((task_id + 1))" \
      --provider openai --mode chat --model "$model" --temperature 0 \
      --max_steps 30 --max_tokens 384 --result_dir "$result_dir" \
      2>&1 | tee "$task_log"
    runner_rc=${PIPESTATUS[0]}
    set -e
    "$venv/bin/python" "$repo_dir/scripts/store_webarena_task.py" \
      --run-id "$run_id" --phase "$phase" --trial "$trial" --task-id "$task_id" \
      --log "$task_log" --usage-log "$usage_log" --result-dir "$result_dir" \
      --output "$artifact_dir/${phase}_t${trial}_rows/${task_id}.json"
    [[ $runner_rc -eq 0 ]] || echo "task $task_id runner exit=$runner_rc" >&2
    spent=$(jq -s '[.[].cost_usd] | add // 0' "$artifact_dir"/*_rows/*.json)
    if awk -v cost="$spent" 'BEGIN {exit !(cost > 800)}'; then
      echo "WebArena track exceeded its $800 budget: $spent" >&2
      return 1
    fi
    sync_artifacts
  done
  jq -s '{schema_version:1,run_id:$run_id,milestone:"M16",vertical:"webarena",phase:$phase,trial:$trial,rows:length,passes:(map(select(.passed))|length),pass_rate:((map(select(.passed))|length)/length),cost_usd:((map(.cost_usd)|add)//0),models_seen:(map(.models_seen[])|unique)}' \
    --arg run_id "$run_id" --arg phase "$phase" --argjson trial "$trial" \
    "$artifact_dir/${phase}_t${trial}_rows"/*.json \
    >"$artifact_dir/${phase}_t${trial}_summary.json"
  sync_artifacts
}

paid_gate=/opt/sosog/state/webarena-paid-run.approved
if [[ ! -f $paid_gate ]]; then
  printf 'paused-before-paid-inference\n' >"$artifact_dir/status.txt"
  sync_artifacts
  echo "WebArena sites are ready; paid inference is paused pending explicit approval."
  exit 0
fi

run_phase smoke 0 '.smoke_task_ids[]'
bash "$repo_dir/infra/aws/reset_webarena_sites.sh"
"$venv/bin/python" browser_env/auto_login.py
run_phase baseline 0 '.task_ids[]'
for trial in $(seq 0 4); do
  bash "$repo_dir/infra/aws/reset_webarena_sites.sh"
  "$venv/bin/python" browser_env/auto_login.py
  run_phase corpus "$trial" '.task_ids[]'
done
bash "$repo_dir/infra/aws/reset_webarena_sites.sh"
"$venv/bin/python" browser_env/auto_login.py
run_phase haiku 0 '.smoke_task_ids[]' "$haiku_model"
printf 'complete\n' >"$artifact_dir/status.txt"
sync_artifacts
