#!/usr/bin/env bash
set -euxo pipefail

commit=66ad8099e12188ece0d3fe45e661dbc01880813b
source_dir=/opt/sosog/appworld-v013
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
# Match the official 0.1.3.post1 source tag to its PyPI wheel; upstream main's
# agent package now requires an unreleased Pydantic-v2 AppWorld core.
"$venv/bin/pip" install 'appworld==0.1.3.post1' 'litellm==1.37.20' \
  'click<8.3.0' 'pydantic<2' diskcache tiktoken jinja2 jsonnet filelock
# Recoma 0.0.4 pins a yanked LiteLLM 1.37.19 build. Its next patch release is
# API-compatible, so install Recoma without that now-unresolvable exact pin.
"$venv/bin/pip" install --no-deps 'recoma==0.0.4'
"$venv/bin/appworld" install

install -d -o ubuntu -g ubuntu "$root_dir"
"$venv/bin/appworld" download data --root "$root_dir"
"$venv/bin/appworld" verify tasks --root "$root_dir"

printf '%s\n' "$commit" >"$status"
bash /opt/sosog/sosog-ai/infra/aws/install_track_service.sh \
  m14-appworld /opt/sosog/sosog-ai/infra/aws/run_m14_appworld.sh
