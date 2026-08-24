#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  printf 'run this bootstrap script as root\n' >&2
  exit 2
fi

readonly script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly requirements="${script_dir}/requirements-v1-runtime.txt"
readonly runtime=${SOSOG_RUNTIME_VENV:-/opt/sosog/runtime-venv}
readonly python_bin=${SOSOG_RUNTIME_PYTHON:-/usr/bin/python3}

if [[ ! -f $requirements ]]; then
  printf 'runtime requirements are missing: %s\n' "$requirements" >&2
  exit 2
fi
for configured_path in "$runtime" "$python_bin"; do
  if [[ $configured_path != /* || ! $configured_path =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    printf 'runtime paths must be safe absolute paths: %s\n' "$configured_path" >&2
    exit 2
  fi
done
runtime_canonical=$(realpath -m -- "$runtime")
if [[ $runtime != "$runtime_canonical" || $runtime != /opt/sosog/* || -L $runtime ]]; then
  printf 'runtime venv must be a non-symlink canonical path below /opt/sosog: %s\n' \
    "$runtime" >&2
  exit 2
fi
if [[ ! -x $python_bin ]]; then
  printf 'runtime Python is not executable: %s\n' "$python_bin" >&2
  exit 2
fi

install -d -m 0755 "${runtime%/*}"
if [[ ! -x ${runtime}/bin/python ]]; then
  "$python_bin" -m venv "$runtime"
fi

PIP_DISABLE_PIP_VERSION_CHECK=1 \
  "${runtime}/bin/python" -m pip install \
    --require-virtualenv \
    --only-binary=:all: \
    --requirement "$requirements"

"${runtime}/bin/python" - "$requirements" <<'PY'
import importlib
import importlib.metadata
import sys
from pathlib import Path

requirements = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if line and not line.startswith("#"):
        name, version = line.split("==", 1)
        requirements[name] = version

if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"SOSOG V1 runtime requires Python 3.12, found {sys.version}")

for name, expected in requirements.items():
    actual = importlib.metadata.version(name)
    if actual != expected:
        raise SystemExit(f"{name}: expected {expected}, found {actual}")

for module in ("boto3", "hdbscan", "psycopg", "sklearn"):
    importlib.import_module(module)

print(f"SOSOG V1 runtime verified: {len(requirements)} pinned distributions")
PY
