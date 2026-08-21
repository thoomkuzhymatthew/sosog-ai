#!/usr/bin/env bash
set -euo pipefail

image_dir=/opt/sosog/webarena-images
for container in shopping shopping_admin forum gitlab wikipedia; do
  docker rm -f "$container" >/dev/null 2>&1 || true
done
docker run --name shopping -p 7770:80 -d shopping_final_0712 >/dev/null
docker run --name shopping_admin -p 7780:80 -d shopping_admin_final_0719 >/dev/null
docker run --name forum -p 9999:80 -d postmill-populated-exposed-withimg >/dev/null
docker run --name gitlab -p 8023:8023 -d gitlab-populated-final-port8023 \
  /opt/gitlab/embedded/bin/runsvdir-start >/dev/null
docker run --name wikipedia --volume "$image_dir:/data" -p 8888:80 -d \
  ghcr.io/kiwix/kiwix-serve:3.3.0 wikipedia_en_all_maxi_2022-05.zim >/dev/null

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:7770/ >/dev/null \
    && curl -fsS http://127.0.0.1:7780/ >/dev/null \
    && curl -fsS http://127.0.0.1:9999/ >/dev/null; then
    break
  fi
  sleep 10
done
docker exec shopping /var/www/magento2/bin/magento setup:store-config:set \
  --base-url=http://127.0.0.1:7770 >/dev/null
docker exec shopping mysql -u magentouser -pMyPassword magentodb -e \
  "UPDATE core_config_data SET value='http://127.0.0.1:7770/' WHERE path='web/secure/base_url';"
docker exec shopping /var/www/magento2/bin/magento cache:flush >/dev/null
docker exec shopping_admin /var/www/magento2/bin/magento setup:store-config:set \
  --base-url=http://127.0.0.1:7780 >/dev/null
docker exec shopping_admin mysql -u magentouser -pMyPassword magentodb -e \
  "UPDATE core_config_data SET value='http://127.0.0.1:7780/' WHERE path='web/secure/base_url';"
docker exec shopping_admin /var/www/magento2/bin/magento cache:flush >/dev/null

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8023/users/sign_in >/dev/null; then break; fi
  sleep 10
done
docker exec gitlab update-permissions || true
docker exec gitlab sed -i \
  "s|^external_url.*|external_url 'http://127.0.0.1:8023'|" /etc/gitlab/gitlab.rb
docker exec gitlab gitlab-ctl reconfigure >/dev/null
