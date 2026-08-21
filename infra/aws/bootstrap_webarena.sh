#!/usr/bin/env bash
set -euxo pipefail

commit=dce04686a56253aefba7b18a4fa0937cf1dc987b
source_dir=/opt/sosog/webarena
venv=/opt/sosog/webarena-venv
status=/opt/sosog/state/webarena-bootstrap.status

trap 'printf "failed\n" >"$status"' ERR
printf 'running\n' >"$status"

if [[ ! -d "$source_dir/.git" ]]; then
  git clone --filter=blob:none https://github.com/web-arena-x/webarena.git "$source_dir"
fi
git -C "$source_dir" checkout "$commit"

/opt/sosog/runtime/bin/pip install --upgrade uv
/opt/sosog/runtime/bin/uv python install 3.11
/opt/sosog/runtime/bin/uv venv --clear --seed --python 3.11 "$venv"
"$venv/bin/pip" install --upgrade pip wheel setuptools
"$venv/bin/pip" install -r "$source_dir/requirements.txt"
"$venv/bin/pip" install -e "$source_dir"
"$venv/bin/python" -m playwright install chromium --with-deps
docker info >/dev/null
df -BG / | awk 'NR==2 {if (($4+0) < 800) exit 1}'

# Website images and the map backend are installed as a separate gated phase;
# this preflight proves the official browser/evaluator stack before the large
# downloads begin.
printf '%s\n' "$commit" >"$status"
