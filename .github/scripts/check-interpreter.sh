#!/usr/bin/env bash
# Fails early and clearly if the API would run on anything but the pinned uv-managed CPython.
# ADR 0004 section 3.11: the system python3.12 on ubuntu-latest (3.12.3) has no expat allocation tracker.
#
#   check-interpreter.sh <api-dir> [--import-app]
#
# Checks, in <api-dir>'s environment (the one `uv run` uses): the version equals <api-dir>/.python-version
# when that file exists, else $EXPECTED_PYTHON; the interpreter is under uv's managed Python directory,
# not /usr/bin; with --import-app, `import app.routes.parse` succeeds (its import guard
# require_alloc_tracker raises on an expat without the tracker).
set -euo pipefail

dir="$1"
import_app="${2:-}"
if [ -f "$dir/.python-version" ]; then
  expected="$(tr -d '[:space:]' <"$dir/.python-version")"
else
  expected="${EXPECTED_PYTHON:?no $dir/.python-version and EXPECTED_PYTHON is unset}"
fi
managed_dir="$(uv python dir)"

cd "$dir"
uv run --frozen python -I -c '
import sys, pyexpat
expected, managed = sys.argv[1], sys.argv[2]
version = "%d.%d.%d" % sys.version_info[:3]
print(f"python {version} at {sys.executable}, expat {pyexpat.EXPAT_VERSION}")
if version != expected:
    sys.exit(f"::error::interpreter is {version}, expected {expected}")
if not sys.executable.startswith(managed) and not sys.base_prefix.startswith(managed):
    sys.exit(f"::error::interpreter {sys.base_prefix} is not uv-managed ({managed}); the system python must not be used")
' "$expected" "$managed_dir"

if [ "$import_app" = "--import-app" ]; then
  uv run --frozen python -c "import app.routes.parse"
  echo "import app.routes.parse: ok (expat allocation tracker present)"
fi
