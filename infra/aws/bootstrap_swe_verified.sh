#!/usr/bin/env bash
set -euxo pipefail

swebench_commit=7a21e05772954cc81471ae19d56f436cecf43c54
mini_commit=25941c89cfbc91eb40b3f8756348c91d9977d57e
swebench_dir=/opt/sosog/SWE-bench
mini_dir=/opt/sosog/mini-swe-agent
venv=/opt/sosog/swe-venv
status=/opt/sosog/state/swe-bootstrap.status

trap 'printf "failed\n" >"$status"' ERR
printf 'running\n' >"$status"

if [[ ! -d "$swebench_dir/.git" ]]; then
  git clone --filter=blob:none https://github.com/SWE-bench/SWE-bench.git "$swebench_dir"
fi
git -C "$swebench_dir" checkout "$swebench_commit"

if [[ ! -d "$mini_dir/.git" ]]; then
  git clone --filter=blob:none https://github.com/SWE-agent/mini-swe-agent.git "$mini_dir"
fi
git -C "$mini_dir" checkout "$mini_commit"

python3 -m venv "$venv"
"$venv/bin/pip" install --upgrade pip wheel
"$venv/bin/pip" install -e "$swebench_dir"
"$venv/bin/pip" install -e "$mini_dir"
docker info >/dev/null

printf 'swebench=%s mini=%s\n' "$swebench_commit" "$mini_commit" >"$status"
