#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  printf 'run this launcher as root\n' >&2
  exit 2
fi
if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
  printf 'usage: %s BASE_COMMIT\n' "$0" >&2
  exit 2
fi

readonly base_commit=$1
readonly agent_root=${CODEX_AGENT_ROOT:-/opt/sosog/codex-agents}
readonly repo=${CODEX_AGENT_REPO:-/opt/sosog/codex-repo}

cd "$repo"
python3 - "$repo/build_jobs/wave4b/jobs.json" "$agent_root" "$repo" "$base_commit" <<'PY'
import json
import sys
from pathlib import Path

from sosog.orchestration.dispatcher import enqueue_jobs

jobs_path, agent_root, repo, base_commit = sys.argv[1:]
jobs = json.loads(Path(jobs_path).read_text())
if len(jobs) != 1:
    raise SystemExit("expected exactly one reviewed wave-4b job")
enqueue_jobs(jobs, agent_root, repo, base_commit)
print(f"started codex-agent@{jobs[0]['job_id']}.service")
PY
