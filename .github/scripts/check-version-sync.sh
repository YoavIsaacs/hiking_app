#!/usr/bin/env bash
# Fails if the API's version (what /health reports) is not the released version.
#
#   check-version-sync.sh [repo-root]
#
# release-please bumps .release-please-manifest.json and, through extra-files in
# release-please-config.json, api/pyproject.toml and the project's entry in api/uv.lock. This is the guard
# against those drifting apart (a hand edit, or an extra-files path that stopped matching).
# Needs uv (it supplies the interpreter, which has tomllib).
set -euo pipefail

root="${1:-.}"

uv run --no-project --python 3.12 python -I - "$root" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))["."]
pyproject = tomllib.loads((root / "api/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
lock = tomllib.loads((root / "api/uv.lock").read_text(encoding="utf-8"))
entries = [p["version"] for p in lock["package"] if p["name"] == "hike-prep-api"]

print(f"manifest={manifest} api/pyproject.toml={pyproject} api/uv.lock={entries}")
if pyproject != manifest or entries != [manifest]:
    sys.exit(
        "::error::Version drift: .release-please-manifest.json, api/pyproject.toml and the hike-prep-api "
        "entry in api/uv.lock must all be equal (they set /health version). Fix api/pyproject.toml, "
        "run 'uv lock --directory api', and check extra-files in release-please-config.json."
    )
PY

uv lock --check --directory "$root/api"
echo "version sync OK"
