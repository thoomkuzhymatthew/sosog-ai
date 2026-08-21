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
# The source repository's Git LFS quota is not a reliable installation path.
# The official wheel contains the same encrypted runtime bundle and unpacks it
# with `appworld install`, while the pinned checkout supplies experiment code.
"$venv/bin/pip" install 'appworld==0.1.3'
"$venv/bin/appworld" install
"$venv/bin/pip" install -e "$source_dir/experiments[simplified]"

install -d -o ubuntu -g ubuntu "$root_dir"
"$venv/bin/appworld" download data --root "$root_dir" --with-setup
"$venv/bin/appworld" verify tasks --root "$root_dir" \
  --include-only-first-n-tasks 5 --num-processes 2

printf '%s\n' "$commit" >"$status"
