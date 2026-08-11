#!/usr/bin/env bash
# Fails loudly if a GitHub Release already exists for the given tag, so CI
# stops rather than silently skipping or overwriting it. Invoked by
# .github/workflows/release.yml's "Check for existing release" step.
#
# Usage: check-release-exists.sh <tag> <owner/repo>
set -euo pipefail

tag="${1:?usage: check-release-exists.sh <tag> <owner/repo>}"
repo="${2:?usage: check-release-exists.sh <tag> <owner/repo>}"

if gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
    echo "error: release $tag already exists for $repo." >&2
    echo "Bump versionNumber in the manifest (manifest/<PACK_NAME>.json, or \$MANIFEST_FILE) before merging to main." >&2
    exit 1
fi

echo "Release $tag does not exist yet; proceeding." >&2
