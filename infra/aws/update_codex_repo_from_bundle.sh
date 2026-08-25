#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'usage: %s ABSOLUTE_BUNDLE_PATH EXPECTED_COMMIT\n' "$0" >&2
}

if (( $# != 2 )); then
  usage
  exit 2
fi

bundle=$1
expected_commit=$2
repo=${CODEX_AGENT_REPO:-/opt/sosog/codex-repo}

for configured_path in "$bundle" "$repo"; do
  if [[ $configured_path != /* || ! $configured_path =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    printf 'paths must be safe absolute paths: %s\n' "$configured_path" >&2
    exit 2
  fi
done
if [[ ! $expected_commit =~ ^[0-9a-f]{40}$ ]]; then
  printf 'EXPECTED_COMMIT must be a full lowercase SHA-1 commit ID\n' >&2
  exit 2
fi
if [[ -L $bundle || ! -f $bundle ]]; then
  printf 'bundle must be a regular non-symlink file: %s\n' "$bundle" >&2
  exit 2
fi
if [[ -L $repo || ! -d $repo ]]; then
  printf 'repository must be a non-symlink directory: %s\n' "$repo" >&2
  exit 2
fi

bundle_resolved=$(realpath -e -- "$bundle")
repo_resolved=$(realpath -e -- "$repo")
if [[ $bundle != "$bundle_resolved" || $repo != "$repo_resolved" ]]; then
  printf 'bundle and repository paths must be canonical\n' >&2
  exit 2
fi
if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'configured repository is not a Git worktree: %s\n' "$repo" >&2
  exit 2
fi
if [[ -n $(git -C "$repo" status --porcelain) ]]; then
  printf 'refusing to update a dirty repository: %s\n' "$repo" >&2
  exit 3
fi

git -C "$repo" bundle verify "$bundle"
git -C "$repo" fetch --no-tags "$bundle" \
  'refs/heads/main:refs/remotes/sosog-bundle/main'
fetched_commit=$(git -C "$repo" rev-parse refs/remotes/sosog-bundle/main)
if [[ $fetched_commit != "$expected_commit" ]]; then
  printf 'bundle main mismatch: expected %s, found %s\n' \
    "$expected_commit" "$fetched_commit" >&2
  exit 4
fi
if ! git -C "$repo" merge-base --is-ancestor HEAD "$expected_commit"; then
  printf 'bundle update is not a fast-forward from the current checkout\n' >&2
  exit 4
fi

git -C "$repo" merge --ff-only "$expected_commit"
current_commit=$(git -C "$repo" rev-parse HEAD)
if [[ $current_commit != "$expected_commit" ]]; then
  printf 'repository did not reach the expected commit\n' >&2
  exit 4
fi
if [[ -n $(git -C "$repo" status --porcelain) ]]; then
  printf 'repository became dirty during update\n' >&2
  exit 4
fi

printf 'SOSOG repository updated by verified bundle to %s\n' "$current_commit"
