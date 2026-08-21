#!/usr/bin/env bash
set -euxo pipefail

commit=a072b7a86e7c1d5b1d7175659d750ebb9b79f10a
source_dir=/opt/sosog/appworld
root_dir=/opt/sosog/appworld-root
venv=/opt/sosog/appworld-venv
status=/opt/sosog/state/appworld-bootstrap.status

trap 'printf "failed\n" >"$status"' ERR
printf 'running\n' >"$status"

if [[ ! -d "$source_dir/.git" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone --filter=blob:none \
    https://github.com/StonyBrookNLP/appworld.git "$source_dir"
fi
git -C "$source_dir" checkout "$commit"

python3 -m venv "$venv"
"$venv/bin/pip" install --upgrade pip wheel
"$venv/bin/pip" install -e "$source_dir"
"$venv/bin/pip" install -e "$source_dir/experiments[simplified]"

cd "$source_dir"
"$venv/bin/appworld" install --repo
install -d -o ubuntu -g ubuntu "$root_dir"
"$venv/bin/appworld" download data --root "$root_dir" --with-setup
"$venv/bin/appworld" verify tasks --root "$root_dir" \
  --include-only-first-n-tasks 5 --num-processes 2

printf '%s\n' "$commit" >"$status"
