#!/usr/bin/env bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive

# Bound accidental compute spend even if orchestration disconnects. Long
# SWE-bench runs can exceed six hours, so this is an emergency ceiling only.
# Instance-initiated shutdown behavior is also set to "stop" at launch time.
systemd-run \
  --unit=sosog-m15-autostop \
  --on-active=7d \
  /usr/sbin/shutdown -h now

apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  docker.io \
  git \
  git-lfs \
  jq \
  python3-pip \
  python3-venv

systemctl enable --now docker
systemctl enable --now snap.amazon-ssm-agent.amazon-ssm-agent.service \
  || systemctl enable --now amazon-ssm-agent
usermod -aG docker ubuntu

install -d -o ubuntu -g ubuntu /opt/sosog
git clone --filter=blob:none https://github.com/SWE-bench/SWE-bench.git \
  /opt/sosog/SWE-bench
git -C /opt/sosog/SWE-bench checkout 7a21e05772954cc81471ae19d56f436cecf43c54
chown -R ubuntu:ubuntu /opt/sosog

python3 -m venv /opt/sosog/swebench-venv
/opt/sosog/swebench-venv/bin/pip install --upgrade pip
/opt/sosog/swebench-venv/bin/pip install -e /opt/sosog/SWE-bench

python3 -m venv /opt/sosog/awscli-venv
/opt/sosog/awscli-venv/bin/pip install --upgrade pip awscli

docker info >/var/log/sosog-docker-info.txt
df -h >/var/log/sosog-disk.txt
printf 'ready\n' >/var/log/sosog-bootstrap.status
