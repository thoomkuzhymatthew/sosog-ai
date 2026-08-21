#!/usr/bin/env bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive

# Backstop only: benchmark services own their normal completion/idle shutdown.
# Seven days covers the slow SWE-bench track while bounding accidental spend.
systemd-run \
  --unit=sosog-emergency-autostop \
  --on-active=7d \
  /usr/sbin/shutdown -h now

for attempt in 1 2 3 4 5; do
  apt-get update && break
  sleep $((attempt * 10))
done

apt-get install -y \
  ca-certificates \
  curl \
  docker.io \
  git \
  git-lfs \
  jq \
  postgresql-client \
  python3-pip \
  python3-venv \
  unzip

systemctl enable --now docker
systemctl enable --now snap.amazon-ssm-agent.amazon-ssm-agent.service \
  || systemctl enable --now amazon-ssm-agent
usermod -aG docker ubuntu

install -d -o ubuntu -g ubuntu \
  /opt/sosog/artifacts \
  /opt/sosog/checkpoints \
  /opt/sosog/logs \
  /opt/sosog/state

python3 -m venv /opt/sosog/runtime
/opt/sosog/runtime/bin/pip install --upgrade pip awscli

docker info >/var/log/sosog-docker-info.txt
df -h >/var/log/sosog-disk.txt
printf 'ready\n' >/var/log/sosog-bootstrap.status
