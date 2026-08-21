#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 RUN_ID LOCAL_ARTIFACT_DIRECTORY" >&2
  exit 2
fi

run_id=$1
artifact_directory=$2
case "$run_id" in
  *[!A-Za-z0-9._-]* | "")
    echo "RUN_ID may contain only letters, numbers, dot, underscore, and dash" >&2
    exit 2
    ;;
esac
if [[ ! -d "$artifact_directory" ]]; then
  echo "artifact directory does not exist: $artifact_directory" >&2
  exit 2
fi

artifact_uri="s3://sosog-bedrock-batch-769377363988/vertical-expansion/${run_id}/"
/opt/sosog/awscli-venv/bin/aws s3 sync \
  "$artifact_directory" \
  "$artifact_uri" \
  --no-progress \
  --only-show-errors

echo "$artifact_uri"
