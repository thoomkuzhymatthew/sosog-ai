#!/usr/bin/env bash
set -euo pipefail

repo_dir=${SOSOG_REPO_DIR:-/opt/sosog/sosog-ai}
root_dir=/opt/sosog/appworld-root
source_dir=/opt/sosog/appworld-v013
venv=/opt/sosog/appworld-venv
artifact_dir=/opt/sosog/artifacts/m14-appworld
run_stamp=${SOSOG_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
primary_model=bedrock/us.anthropic.claude-sonnet-4-6
fallback_model=bedrock/global.anthropic.claude-sonnet-4-6
haiku_model=bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0

export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export APPWORLD_ROOT=$root_dir
export SOSOG_ARTIFACT_BUCKET=${SOSOG_ARTIFACT_BUCKET:-sosog-bedrock-batch-769377363988}
export SOSOG_ARTIFACT_PREFIX=${SOSOG_ARTIFACT_PREFIX:-vertical-expansion}
mkdir -p "$artifact_dir" "$source_dir/experiments/configs/sosog_m14"
source "$repo_dir/infra/aws/load_research_env.sh"
export SOSOG_BEDROCK_FALLBACK_MODEL=$fallback_model
site_packages=$("$venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')
patch_file="$repo_dir/patches/recoma-bedrock-converse.patch"
patch_sha=$(sha256sum "$patch_file" | awk '{print $1}')
patch_stamp=$venv/.sosog-recoma-bedrock-patch
installed_patch_sha=$(cat "$patch_stamp" 2>/dev/null || true)
if [[ $installed_patch_sha != "$patch_sha" ]]; then
  "$venv/bin/pip" install --force-reinstall --no-deps 'recoma==0.0.4' >/dev/null
  if ! patch --dry-run -s -p1 -d "$site_packages" <"$patch_file"; then
    echo "Recoma Bedrock patch does not apply cleanly" >&2
    exit 1
  fi
  patch -s -p1 -d "$site_packages" <"$patch_file"
  printf '%s\n' "$patch_sha" >"$patch_stamp"
fi
mkdir -p "$root_dir/experiments"
# `appworld verify tasks` creates experiments/outputs under the data root before
# the baseline runner starts. Add the three source-only trees individually so
# those verification outputs remain intact and the v0.1.3 CLI can find agents.
for component in code configs prompts; do
  if [[ ! -e "$root_dir/experiments/$component" ]]; then
    ln -s "$source_dir/experiments/$component" "$root_dir/experiments/$component"
  fi
done

sync_artifacts() {
  /opt/sosog/runtime/bin/aws s3 sync "$artifact_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/m14-appworld-${run_stamp}/" \
    --no-progress --only-show-errors || true
}
trap sync_artifacts EXIT

"$venv/bin/pip" install --upgrade boto3 'psycopg[binary]' >/dev/null
"$venv/bin/appworld" download experiment-outputs --root "$root_dir"
"$venv/bin/python" "$repo_dir/scripts/verify_appworld_golden.py" \
  --root "$root_dir" --output "$artifact_dir/GOLDEN_REPLAY.json"
"$venv/bin/python" "$repo_dir/scripts/select_appworld_tasks.py" \
  --root "$root_dir" --output "$artifact_dir/appworld_dev_task_ids.json"
sync_artifacts

write_config() {
  local dataset=$1 model=$2 path=$3 tasks_per_gen=$4
  jq --arg dataset "$dataset" --arg model "$model" \
    --arg prompt "$root_dir/experiments/prompts/react.txt" \
    --argjson tasks_per_gen "$tasks_per_gen" \
    '.config.reader.dataset_name=$dataset
     | .config.models.action.generator_params.model=$model
     | .config.models.action.prompt_file=$prompt
     | .config.reader.tasks_per_gen=$tasks_per_gen' \
    "$repo_dir/config/appworld_sonnet46.jsonnet" >"$path"
}

run_phase() {
  local phase=$1 dataset=$2 trial=$3 workers=$4 model=${5:-$primary_model}
  local experiment="sosog_m14/${phase}_t${trial}"
  local config_path="$source_dir/experiments/configs/${experiment}.jsonnet"
  local output_dir="$root_dir/experiments/outputs/$experiment"
  local log="$artifact_dir/${phase}_t${trial}_us.log"
  local route_map="$artifact_dir/${phase}_t${trial}_model_routes.json"
  local marker_dir="$output_dir/recoma_output"
  local tasks_per_gen=3
  [[ $dataset == sosog_m14_smoke ]] && tasks_per_gen=1
  write_config "$dataset" "$model" "$config_path" "$tasks_per_gen"

  set +e
  "$venv/bin/appworld" run "$experiment" --root "$root_dir" 2>&1 | tee "$log"
  local primary_rc=${PIPESTATUS[0]}
  set -e

  "$venv/bin/python" - "$output_dir" "$dataset" "$model" "$route_map" <<'PY'
import json, sys
from pathlib import Path
output, dataset, model, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
dataset_file = Path("/opt/sosog/appworld-root/data/datasets") / f"{dataset}.txt"
routes = {}
for task_id in dataset_file.read_text().split():
    marker = output / "recoma_output" / f"{task_id}_data.json"
    if not marker.exists():
        continue
    usage = json.loads(marker.read_text()).get("metadata", {})
    observed = sorted(
        key[len("litellm."):-len(".calls")]
        for key, value in usage.items()
        if key.startswith("litellm.") and key.endswith(".calls") and float(value or 0) > 0
    )
    routes[task_id] = next(
        (route for route in observed if "/global." in route),
        observed[0] if observed else model,
    )
target.write_text(json.dumps(routes, indent=2, sort_keys=True) + "\n")
PY

  if (( primary_rc != 0 )); then
    if [[ $model != "$primary_model" ]] || ! grep -Eqi \
      'RateLimitError|ThrottlingException|Too many tokens|ServiceUnavailable' "$log"; then
      echo "non-quota AppWorld failure in $phase trial $trial" >&2
      return "$primary_rc"
    fi
    fallback_dataset="sosog_m14_${phase}_t${trial}_fallback"
    fallback_dataset_path="$root_dir/data/datasets/${fallback_dataset}.txt"
    "$venv/bin/python" - "$root_dir" "$experiment" "$dataset" "$fallback_dataset_path" <<'PY'
import sys
from pathlib import Path
root, experiment, dataset, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
markers = root / "experiments" / "outputs" / experiment / "recoma_output"
ids = (root / "data" / "datasets" / f"{dataset}.txt").read_text().split()
missing = [task_id for task_id in ids if not (markers / f"{task_id}_data.json").exists()]
target.write_text("\n".join(missing) + ("\n" if missing else ""))
print(len(missing))
PY
    if [[ -s $fallback_dataset_path ]]; then
      write_config "$fallback_dataset" "$fallback_model" "$config_path" "$tasks_per_gen"
      "$venv/bin/appworld" run "$experiment" --root "$root_dir" 2>&1 \
        | tee "$artifact_dir/${phase}_t${trial}_global.log"
    fi
    "$venv/bin/python" - "$root_dir" "$experiment" "$dataset" "$fallback_model" "$route_map" <<'PY'
import json, sys
from pathlib import Path
root, experiment, dataset, model, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])
routes = json.loads(target.read_text())
for task_id in (root / "data" / "datasets" / f"{dataset}.txt").read_text().split():
    marker = root / "experiments" / "outputs" / experiment / "recoma_output" / f"{task_id}_data.json"
    if task_id not in routes and marker.exists():
        routes[task_id] = model
target.write_text(json.dumps(routes, indent=2, sort_keys=True) + "\n")
PY
  fi

  write_config "$dataset" "$model" "$config_path" "$tasks_per_gen"
  "$venv/bin/appworld" evaluate "$experiment" "$dataset" --root "$root_dir"

  local run_id="m14-appworld-${phase}-t${trial}-${run_stamp}"
  "$venv/bin/python" "$repo_dir/scripts/export_appworld_research.py" \
    --root "$root_dir" --experiment "$experiment" --dataset "$dataset" \
    --run-id "$run_id" --phase "$phase" --trial "$trial" \
    --route-map "$route_map" --output-jsonl "$artifact_dir/${phase}_t${trial}.jsonl" \
    --summary "$artifact_dir/${phase}_t${trial}_summary.json"
  /opt/sosog/runtime/bin/aws s3 sync "$output_dir" \
    "s3://${SOSOG_ARTIFACT_BUCKET}/${SOSOG_ARTIFACT_PREFIX}/${run_id}/raw/" \
    --no-progress --only-show-errors
  sync_artifacts
}

run_phase smoke sosog_m14_smoke 0 1
run_phase baseline sosog_m14_dev 0 1
for trial in $(seq 0 9); do
  workers=1
  if /opt/sosog/runtime/bin/aws s3api head-object --bucket "$SOSOG_ARTIFACT_BUCKET" \
    --key "${SOSOG_ARTIFACT_PREFIX}/m13-airline-20260821T164841Z/baseline_summary.json" \
    >/dev/null 2>&1; then
    workers=2
  fi
  run_phase corpus sosog_m14_dev "$trial" "$workers"
done
run_phase haiku sosog_m14_smoke 0 1 "$haiku_model"

total_cost=$(jq -s '[.[].cost_usd] | add // 0' "$artifact_dir"/*_summary.json)
if awk -v cost="$total_cost" 'BEGIN {exit !(cost > 1200)}'; then
  echo "AppWorld track exceeded its $1200 budget: $total_cost" >&2
  exit 1
fi
printf 'complete cost_usd=%s\n' "$total_cost" >"$artifact_dir/status.txt"
sync_artifacts
