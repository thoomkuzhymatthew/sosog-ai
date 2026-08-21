#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 TRACK_NAME COMMAND_PATH" >&2
  exit 2
fi
track=$1
command_path=$2
case "$track" in
  *[!A-Za-z0-9._-]* | "") echo "unsafe track name" >&2; exit 2 ;;
esac
if [[ ! -f "$command_path" ]]; then
  echo "track command does not exist: $command_path" >&2
  exit 2
fi

install -d /opt/sosog/track-commands
ln -sfn "$command_path" "/opt/sosog/track-commands/$track"
install -m 0644 /opt/sosog/sosog-ai/infra/aws/sosog-track@.service \
  /etc/systemd/system/sosog-track@.service
systemctl daemon-reload
systemctl enable "sosog-track@$track.service"
systemctl start "sosog-track@$track.service"
systemctl --no-pager --full status "sosog-track@$track.service" || true
