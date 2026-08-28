#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
env_file="$repo_root/.env"
codex_bin='/opt/sosog/codex-cli/current/bin/codex'

if [[ ! -f $env_file ]]; then
  printf 'Missing AWS environment file: %s\n' "$env_file" >&2
  exit 1
fi

while IFS='=' read -r key value; do
  case "$key" in
    AWS_REGION|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|SOSOG_PRIMARY_WORKER_INSTANCE_ID)
      export "$key=$value"
      ;;
  esac
done <"$env_file"

instance_id=${SOSOG_PRIMARY_WORKER_INSTANCE_ID:-i-04320968dce0555ba}
region=${AWS_REGION:-us-east-1}

for command_name in aws jq session-manager-plugin ssh ssh-keygen; do
  command -v "$command_name" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    exit 1
  }
done

printf '%s\n' \
  'Opening a temporary SSH connection to EC2 through AWS Session Manager.' \
  'Copy the displayed URL/code into your browser and finish signing in.' \
  'Keep this terminal open until Codex reports success.'

wait_for_command() {
  local command_id=$1
  local command_status='Pending'
  for _ in $(seq 1 60); do
    command_status=$(aws ssm get-command-invocation \
      --region "$region" \
      --command-id "$command_id" \
      --instance-id "$instance_id" \
      --query 'Status' \
      --output text)
    case "$command_status" in
      Success|Failed|TimedOut|Cancelled) break ;;
    esac
    sleep 1
  done
  aws ssm get-command-invocation \
    --region "$region" \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' \
    --output json
  [[ $command_status == Success ]]
}

login_tmp=$(mktemp -d)
login_marker="sosog-codex-login-$(date -u +%Y%m%dT%H%M%SZ)-$$"
key_path="$login_tmp/id_ed25519"
chmod 0700 "$login_tmp"
ssh-keygen -q -t ed25519 -N '' -C "$login_marker" -f "$key_path"
# Some shared development environments apply a permissive default mode to new
# files. OpenSSH deliberately rejects private keys readable by group/others.
chmod 0600 "$key_path"
chmod 0644 "$key_path.pub"
public_key=$(<"$key_path.pub")

remote_setup=$(cat <<REMOTE_EOF
set -eu
if systemctl is-active --quiet ssh; then
  printf 'active\n' > /run/$login_marker.ssh-state
else
  printf 'inactive\n' > /run/$login_marker.ssh-state
  systemctl start ssh
fi
install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
touch /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
chmod 0600 /home/ubuntu/.ssh/authorized_keys
printf '%s\n' '$public_key' >> /home/ubuntu/.ssh/authorized_keys
REMOTE_EOF
)
setup_parameters=$(jq -cn --arg command "$remote_setup" '{commands:[$command],executionTimeout:["300"]}')
setup_id=$(aws ssm send-command \
  --region "$region" \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --parameters "$setup_parameters" \
  --query 'Command.CommandId' \
  --output text)
wait_for_command "$setup_id"

cleanup_login_access() {
  local cleanup_remote cleanup_parameters cleanup_id
  cleanup_remote=$(cat <<REMOTE_EOF
set -eu
if test -f /home/ubuntu/.ssh/authorized_keys; then
  sed -i '\|$login_marker|d' /home/ubuntu/.ssh/authorized_keys
fi
if test -f /run/$login_marker.ssh-state; then
  if test "\$(cat /run/$login_marker.ssh-state)" = inactive; then
    systemctl stop ssh
  fi
  rm -f /run/$login_marker.ssh-state
fi
REMOTE_EOF
)
  cleanup_parameters=$(jq -cn --arg command "$cleanup_remote" '{commands:[$command],executionTimeout:["300"]}')
  cleanup_id=$(aws ssm send-command \
    --region "$region" \
    --instance-ids "$instance_id" \
    --document-name AWS-RunShellScript \
    --parameters "$cleanup_parameters" \
    --query 'Command.CommandId' \
    --output text) || true
  if [[ -n ${cleanup_id:-} ]]; then
    wait_for_command "$cleanup_id" >/dev/null || true
  fi
  rm -f "$key_path" "$key_path.pub" "$login_tmp/known_hosts"
  rmdir "$login_tmp" 2>/dev/null || true
}
trap cleanup_login_access EXIT

ssh -tt \
  -i "$key_path" \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$login_tmp/known_hosts" \
  -o "ProxyCommand=aws ssm start-session --region $region --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p" \
  "ubuntu@$instance_id" \
  "$codex_bin logout >/dev/null 2>&1 || true; exec $codex_bin login --device-auth"

cleanup_login_access
trap - EXIT

printf '%s\n' 'Login flow closed. Verifying the stored login and resuming the paused repair job...'

remote_resume=$(cat <<'REMOTE_EOF'
set -eu
job=airline-flight-change-repair-v1
codex_bin=/opt/sosog/codex-cli/current/bin/codex
experiment_root=/opt/sosog/controller/experiments/m18-airline-flight-change-repair

sudo -u ubuntu -H "$codex_bin" login status

if test -f "$experiment_root/latest.txt"; then
  run_id=$(cat "$experiment_root/latest.txt")
  run_dir="$experiment_root/$run_id"
  if test "$(cat "$run_dir/status")" = awaiting_codex_reauthentication; then
    unit="sosog-airline-flight-repair-resume-$(date -u +%Y%m%dT%H%M%SZ | tr A-Z a-z)"
    systemctl reset-failed "codex-agent@$job.service" || true
    systemd-run --no-block \
      --unit="$unit" \
      --property=Type=oneshot \
      --property=TimeoutStartSec=25200 \
      /bin/bash "$run_dir/input/controller/run.sh" \
      "$run_dir" \
      "$job" \
      /opt/sosog/codex-agents \
      /opt/sosog/codex-repo \
      /opt/sosog/tau-bench \
      "$run_dir/input/controller/evaluator.py"
    printf 'repair_resume_unit=%s\n' "$unit"
  else
    printf 'repair_status=%s (no resume needed)\n' "$(cat "$run_dir/status")"
  fi
fi
REMOTE_EOF
)

resume_parameters=$(jq -cn --arg command "$remote_resume" '{commands:[$command],executionTimeout:["300"]}')
command_id=$(aws ssm send-command \
  --region "$region" \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --parameters "$resume_parameters" \
  --query 'Command.CommandId' \
  --output text)

if ! wait_for_command "$command_id"; then
  printf '%s\n' 'Login verification or repair resume failed.' >&2
  exit 1
fi

printf '%s\n' 'Done. Codex is logged in on EC2 and the paused repair controller has been resumed.'
