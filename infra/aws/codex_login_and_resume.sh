#!/usr/bin/env bash
set -Eeuo pipefail

# Check immediately after a human login instead of waiting up to 12 hours.
# A future orchestration job will make refresh_codex_auth.sh scan jobs/*/status
# for blocked_auth jobs and restart them after authentication recovers.
codex login && sudo systemctl start sosog-codex-auth-refresh.service
