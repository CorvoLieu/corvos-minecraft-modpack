#!/usr/bin/env bash
# Prints the release tag ("v<versionNumber>") derived from the manifest's
# modpackLink.versionNumber. Set MANIFEST_FILE to point at a different
# manifest (defaults to manifest/creark.json). Invoked by
# .github/workflows/release.yml's "Compute release tag" step.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

manifest_file="${MANIFEST_FILE:-manifest/creark.json}"

version=$(python3 -c "
import json, sys
print(json.load(open(sys.argv[1]))['modpackLink']['versionNumber'])
" "$manifest_file")

echo "v$version"
