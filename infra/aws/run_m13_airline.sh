#!/usr/bin/env bash
set -euo pipefail

repo_dir=${SOSOG_REPO_DIR:-/opt/sosog/sosog-ai}
tau2_dir=/opt/sosog/tau2-bench
artifact_dir=/opt/sosog/artifacts/m13-airline
run_stamp=${SOSOG_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
primary_model=bedrock/us.anthropic.claude-sonnet-4-6
fallback_model=bedrock/global.anthropic.claude-sonnet-4-6
tau2_commit=c3398666e6559e3a063da3fc04b5acf7f941464e

export AWS_DEFAULT_REGION=us-east-1
export TAU2_BEDROCK_PROMPT_CACHE=1
export SOSOG_ARTIFACT_BUCKET=${SOSOG_ARTIFACT_BUCKET:-sosog-bedrock-batch-769377363988}
export SOSOG_ARTIFACT_PREFIX=${SOSOG_ARTIFACT_PREFIX:-vertical-expansion}
export SOSOG_TRACK_BUDGET_USD=150

mkdir -p "$artifact_dir" /opt/sosog/logs

sync_artifacts() {
  /opt/sosog/runtime/bin/aws s3 sync \
    "$artifact_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/m13-airline-${run_stamp}/" \
    --no-progress --only-show-errors || true
}
trap sync_artifacts EXIT

if [[ ! -f "$repo_dir/config/vertical_expansion.json" ]]; then
  echo "pinned SOSOG release is not deployed at $repo_dir" >&2
  exit 1
fi

source "$repo_dir/infra/aws/load_research_env.sh"

if [[ ! -d "$tau2_dir/.git" ]]; then
  git clone --filter=blob:none https://github.com/sierra-research/tau2-bench "$tau2_dir"
fi
git -C "$tau2_dir" checkout "$tau2_commit"
git -C "$tau2_dir" apply --check "$repo_dir/patches/tau2-bedrock-prompt-cache.patch" \
  && git -C "$tau2_dir" apply "$repo_dir/patches/tau2-bedrock-prompt-cache.patch" \
  || true

/opt/sosog/runtime/bin/pip install --upgrade uv boto3 'psycopg[binary]'
cd "$tau2_dir"
/opt/sosog/runtime/bin/uv sync
/opt/sosog/runtime/bin/uv pip install boto3 'psycopg[binary]'

golden_ids=(0 3 10 20 30)
/opt/sosog/runtime/bin/uv run python "$repo_dir/scripts/verify_tau2_golden.py" \
  "$tau2_dir/data/tau2/results/final/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json" \
  --task-ids "${golden_ids[@]}" \
  --output "$artifact_dir/GOLDEN_REPLAY.json"
sync_artifacts

task_ids=()
while IFS= read -r task_id; do task_ids+=("$task_id"); done < <(
  jq -r '.task_ids[]' "$repo_dir/config/airline_verifiable_task_ids.json"
)

run_phase() {
  local phase=$1
  local trials=$2
  local ids_name=$3
  local -n ids=$ids_name
  local save_to="sosog_m13_airline_${phase}_${run_stamp}"
  local results="$tau2_dir/data/simulations/$save_to/results.json"
  local route_map="$artifact_dir/${phase}_model_routes.json"
  local args='{"temperature":0.0}'

  set +e
  /opt/sosog/runtime/bin/uv run tau2 run \
    --domain airline --agent llm_agent --agent-llm "$primary_model" \
    --agent-llm-args "$args" --user user_simulator --user-llm "$primary_model" \
    --user-llm-args "$args" --num-trials "$trials" --task-ids "${ids[@]}" \
    --max-concurrency 2 --max-retries 1 --retry-delay 15 --timeout 900 \
    --auto-resume --save-to "$save_to" --verbose-logs --llm-log-mode all \
    --log-level INFO 2>&1 | tee "$artifact_dir/${phase}_us.log"
  local primary_rc=${PIPESTATUS[0]}
  set -e
  if [[ -f "$results" ]]; then
    /opt/sosog/runtime/bin/uv run python "$repo_dir/scripts/mark_tau2_model_route.py" \
      "$results" "$primary_model" "$route_map"
  fi

  local infra_errors=0
  if [[ -f "$results" ]]; then
    infra_errors=$(jq '[.simulations[] | select(.termination_reason=="infrastructure_error")] | length' "$results")
  fi
  if (( primary_rc != 0 || infra_errors > 0 )); then
    if ! grep -Eqi 'RateLimitError|ThrottlingException|Too many tokens|ServiceUnavailable' \
      "$artifact_dir/${phase}_us.log"; then
      echo "non-quota primary failure in $phase" >&2
      return 1
    fi
    /opt/sosog/runtime/bin/uv run tau2 run \
      --domain airline --agent llm_agent --agent-llm "$fallback_model" \
      --agent-llm-args "$args" --user user_simulator --user-llm "$fallback_model" \
      --user-llm-args "$args" --num-trials "$trials" --task-ids "${ids[@]}" \
      --max-concurrency 2 --max-retries 1 --retry-delay 30 --timeout 900 \
      --auto-resume --save-to "$save_to" --verbose-logs --llm-log-mode all \
      --log-level INFO 2>&1 | tee "$artifact_dir/${phase}_global.log"
    /opt/sosog/runtime/bin/uv run python "$repo_dir/scripts/mark_tau2_model_route.py" \
      "$results" "$fallback_model" "$route_map"
  fi

  /opt/sosog/runtime/bin/uv run python "$repo_dir/scripts/export_tau2_research.py" \
    "$results" --run-id "m13-airline-${phase}-${run_stamp}" --milestone M13 \
    --vertical airline --phase "$phase" --harness-commit "$tau2_commit" \
    --route-map "$route_map" --output-jsonl "$artifact_dir/${phase}.jsonl" \
    --summary "$artifact_dir/${phase}_summary.json"
  sync_artifacts
}

smoke_ids=("${golden_ids[@]}")
run_phase smoke 1 smoke_ids
if [[ $(jq -r '.rows' "$artifact_dir/smoke_summary.json") != 5 ]]; then
  echo "live smoke did not produce exactly five rows" >&2
  exit 1
fi

run_phase baseline 1 task_ids
run_phase corpus 10 task_ids
printf 'complete\n' >"$artifact_dir/status.txt"
sync_artifacts
