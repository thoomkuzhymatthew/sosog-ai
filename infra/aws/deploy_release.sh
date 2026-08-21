#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 GIT_REVISION" >&2
  exit 2
fi
revision=$1
case "$revision" in
  *[!0-9a-f]* | "") echo "revision must be hexadecimal" >&2; exit 2 ;;
esac

bucket=${SOSOG_ARTIFACT_BUCKET:-sosog-bedrock-batch-769377363988}
release=/opt/sosog/releases/$revision
archive=s3://$bucket/vertical-expansion/control/releases/sosog-ai-$revision.tar.gz

if [[ ! -f "$release/.sosog-release-ready" ]]; then
  install -d "$release"
  /opt/sosog/runtime/bin/aws s3 cp "$archive" - --only-show-errors \
    | tar -xzf - -C "$release"
  touch "$release/.sosog-release-ready"
  chown -R ubuntu:ubuntu "$release"
fi
if [[ -e /opt/sosog/sosog-ai && ! -L /opt/sosog/sosog-ai ]]; then
  mv /opt/sosog/sosog-ai "/opt/sosog/sosog-ai.pre-release-$(date -u +%s)"
fi
ln -sfn "$release" /opt/sosog/sosog-ai
echo "$revision"
