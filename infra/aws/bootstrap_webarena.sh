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
# WebArena pins Playwright 1.37, whose Ubuntu dependency helper requests the
# obsolete `libasound2` package name on Ubuntu 24.04. The AMI already carries
# browser runtime libraries; install the pinned Chromium payload directly and
# prove it launches instead of relying on that stale helper.
"$venv/bin/python" -m playwright install chromium
"$venv/bin/python" - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("<title>webarena preflight</title>")
    assert page.title() == "webarena preflight"
    browser.close()
PY
docker info >/dev/null
df -BG / | awk 'NR==2 {if (($4+0) < 800) exit 1}'

# Website images and the map backend are installed as a separate gated phase;
# this preflight proves the official browser/evaluator stack before the large
# downloads begin.
printf '%s\n' "$commit" >"$status"
bash /opt/sosog/sosog-ai/infra/aws/install_track_service.sh \
  m16-webarena-sites /opt/sosog/sosog-ai/infra/aws/setup_webarena_sites.sh
