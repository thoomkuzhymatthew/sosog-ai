#!/usr/bin/env bash
set -euo pipefail

repo_dir=${SOSOG_REPO_DIR:-/opt/sosog/sosog-ai}
source_dir=/opt/sosog/webarena
image_dir=/opt/sosog/webarena-images
status=/opt/sosog/state/webarena-sites.status
mkdir -p "$image_dir"
trap 'printf "failed\n" >"$status"' ERR
printf 'downloading\n' >"$status"

download() {
  local name=$1
  curl --fail --location --retry 12 --retry-delay 20 --continue-at - \
    "http://metis.lti.cs.cmu.edu/webarena-images/$name" --output "$image_dir/$name"
}

download shopping_final_0712.tar &
p1=$!
download shopping_admin_final_0719.tar &
p2=$!
download postmill-populated-exposed-withimg.tar &
p3=$!
download gitlab-populated-final-port8023.tar &
p4=$!
download wikipedia_en_all_maxi_2022-05.zim &
p5=$!
for pid in "$p1" "$p2" "$p3" "$p4" "$p5"; do wait "$pid"; done

printf 'loading-images\n' >"$status"
docker image inspect shopping_final_0712 >/dev/null 2>&1 \
  || docker load --input "$image_dir/shopping_final_0712.tar"
docker image inspect shopping_admin_final_0719 >/dev/null 2>&1 \
  || docker load --input "$image_dir/shopping_admin_final_0719.tar"
docker image inspect postmill-populated-exposed-withimg >/dev/null 2>&1 \
  || docker load --input "$image_dir/postmill-populated-exposed-withimg.tar"
docker image inspect gitlab-populated-final-port8023 >/dev/null 2>&1 \
  || docker load --input "$image_dir/gitlab-populated-final-port8023.tar"

bash "$repo_dir/infra/aws/reset_webarena_sites.sh"

homepage="$source_dir/environment_docker/webarena-homepage"
perl -pi -e 's|<your-server-hostname>|http://127.0.0.1|g' "$homepage"/templates/*.html
cat >/etc/systemd/system/webarena-homepage.service <<EOF
[Unit]
Description=WebArena local homepage
After=network-online.target
[Service]
WorkingDirectory=$homepage
ExecStart=/opt/sosog/webarena-venv/bin/python app.py
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now webarena-homepage.service

printf 'ready\n' >"$status"
bash "$repo_dir/infra/aws/install_track_service.sh" \
  m16-webarena "$repo_dir/infra/aws/run_m16_webarena.sh"
