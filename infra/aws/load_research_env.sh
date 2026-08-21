#!/usr/bin/env bash
# Source this file inside a benchmark service. Values are decrypted into the
# process environment and are never written to the repository or command log.
set -euo pipefail

parameter_root=${SOSOG_PARAMETER_ROOT:-/sosog/research/db}
aws_cli=${SOSOG_AWS_CLI:-/opt/sosog/runtime/bin/aws}
secret_uri=${SOSOG_DB_SECRET_URI:-s3://sosog-bedrock-batch-769377363988/vertical-expansion/control/research-db.json}

read_parameter() {
  "$aws_cli" ssm get-parameter \
    --region us-east-1 \
    --name "$1" \
    --with-decryption \
    --query Parameter.Value \
    --output text
}

export DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD
if DB_HOST=$(read_parameter "$parameter_root/host" 2>/dev/null); then
  DB_PORT=$(read_parameter "$parameter_root/port")
  DB_NAME=$(read_parameter "$parameter_root/name")
  DB_USER=$(read_parameter "$parameter_root/user")
  DB_PASSWORD=$(read_parameter "$parameter_root/password")
else
  secret_json=$("$aws_cli" s3 cp "$secret_uri" - --only-show-errors)
  DB_HOST=$(jq -er '.DB_HOST' <<<"$secret_json")
  DB_PORT=$(jq -er '.DB_PORT' <<<"$secret_json")
  DB_NAME=$(jq -er '.DB_NAME' <<<"$secret_json")
  DB_USER=$(jq -er '.DB_USER' <<<"$secret_json")
  DB_PASSWORD=$(jq -er '.DB_PASSWORD' <<<"$secret_json")
  unset secret_json
fi
