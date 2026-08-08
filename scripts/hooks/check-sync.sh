#!/usr/bin/env bash
# Verifies manifest/config/local-mods/servers.dat staged for commit match
# what the contributor's local SKLauncher instance would produce via
# sync_instance.py. Invoked by .githooks/pre-commit; see that file and the
# README's "Pre-commit sync check" section for the full picture.
#
# Exit codes:
#   0 - nothing to check, or staged data matches a fresh sync
#   1 - staged data disagrees with a fresh sync (commit should be blocked)
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

tracked_paths_re='^(manifest/|config/|local-mods/|servers\.dat$)'
staged_files=$(git diff --cached --name-only)

if ! grep -qE "$tracked_paths_re" <<<"$staged_files"; then
    # Commit doesn't touch synced modpack data -- nothing to check.
    exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "warning: pre-commit sync check skipped (uv not found on PATH)" >&2
    exit 0
fi

sync_output=$(mktemp)
trap 'rm -f "$sync_output"' EXIT

if ! uv run sync_instance.py >"$sync_output" 2>&1; then
    if grep -qE 'instance directory not found|no default SKLauncher instance path known' "$sync_output"; then
        echo "warning: pre-commit sync check skipped (no local SKLauncher instance found)" >&2
        echo "  set SK_INSTANCE_DIR or pass --instance-dir to sync_instance.py to enable this check" >&2
    else
        echo "warning: pre-commit sync check skipped (sync_instance.py failed):" >&2
        sed 's/^/  /' "$sync_output" >&2
    fi
    exit 0
fi

if ! git diff --quiet -- manifest/ config/ local-mods/ servers.dat; then
    {
        echo "----------------------------------------------------------------"
        echo "pre-commit: staged manifest/config/local-mods/servers.dat data is"
        echo "out of sync with your local SKLauncher instance."
        echo
        echo "Re-running sync_instance.py produced different content than what's"
        echo "currently staged for this commit. This usually means mods were"
        echo "changed in SKLauncher but sync_instance.py wasn't (re-)run before"
        echo "staging, or was run but the results weren't staged."
        echo
        echo "sync_instance.py has already regenerated the files below in your"
        echo "working tree -- review the diff and 'git add' what's correct:"
        echo
        git diff --stat -- manifest/ config/ local-mods/ servers.dat | sed 's/^/  /'
        echo
        echo "If sync_instance.py disagrees because your local instance is"
        echo "stale/wrong, fix that instead of forcing the commit."
        echo
        echo "To bypass this check: git commit --no-verify"
        echo "----------------------------------------------------------------"
    } >&2
    exit 1
fi

exit 0
