#!/usr/bin/env bash
# Prints the release tag ("v<versionNumber>") derived from the manifest's
# modpackLink.versionNumber. Set MANIFEST_FILE to point at a different
# manifest (defaults to manifest/<PACK_NAME>.json, PACK_NAME defaulting to
# "minecraft-modded" -- see .env.example). Invoked by .github/workflows/release.yml's
# "Compute release tag" step.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# Local/maintainer convenience: pick up PACK_NAME from .env if present and
# not already exported (CI sets it via the workflow's `env:` block instead;
# .env isn't sourced wholesale since its other values aren't guaranteed to be
# valid shell -- e.g. unquoted values containing spaces).
if [ -z "${PACK_NAME:-}" ] && [ -f .env ]; then
    PACK_NAME="$(sed -n 's/^PACK_NAME=//p' .env | tail -n1)"
fi

manifest_file="${MANIFEST_FILE:-manifest/${PACK_NAME:-minecraft-modded}.json}"

version=$(python3 -c "
import json, sys
print(json.load(open(sys.argv[1]))['modpackLink']['versionNumber'])
" "$manifest_file")

echo "v$version"
