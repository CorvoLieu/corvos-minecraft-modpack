#!/usr/bin/env bash
# Syncs source-of-truth data from a local SKLauncher instance into repo-relative
# locations (manifest/, config/, servers.dat, local-mods/) so build_mrpack.py
# (and eventually CI) can build the modpack without needing access to the
# maintainer's machine.
#
# What gets synced:
#   manifest/creark.json  - copy of the SKLauncher manifest, as-is
#   manifest/pack.json    - just {minecraftVersion, loaderVersion}, extracted
#                            from SKLauncher's instances.json
#   config/                - recursive copy of the instance's config/ dir
#   servers.dat             - copy
#   local-mods/            - ONLY mod jars whose manifest entry has
#                            source != "modrinth" (curseforge/local), using the
#                            same source/sha1 cross-check build_mrpack.py uses.
#                            Modrinth-sourced jars are intentionally NOT copied
#                            here; they're fetched from Modrinth's CDN at build
#                            time so we don't commit ~600MB of jars to git.
#
# Configure which SKLauncher instance directory to sync from, in priority order:
#   1. --instance-dir <path> (or -i <path>) CLI flag
#   2. SK_INSTANCE_DIR environment variable
#   3. OS default:
#        macOS: ~/Library/Application Support/sklauncher/instances/creark
#        Windows/Linux: SKLauncher's install layout differs there and there's
#        no safe default -- set SK_INSTANCE_DIR or pass --instance-dir.
#
# Usage:
#   ./sync-instance.sh
#   ./sync-instance.sh --instance-dir "/path/to/sklauncher/instances/creark"
#   SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" ./sync-instance.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTANCE_DIR="${SK_INSTANCE_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --instance-dir|-i)
      INSTANCE_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$INSTANCE_DIR" ]]; then
  case "$(uname -s)" in
    Darwin)
      INSTANCE_DIR="$HOME/Library/Application Support/sklauncher/instances/creark"
      ;;
    *)
      echo "Error: no default SKLauncher instance path known for this OS." >&2
      echo "Set SK_INSTANCE_DIR or pass --instance-dir <path>." >&2
      exit 1
      ;;
  esac
fi

if [[ ! -d "$INSTANCE_DIR" ]]; then
  cat >&2 <<EOF
Error: SKLauncher instance directory not found: $INSTANCE_DIR

Point this script at your own local SKLauncher "creark" instance via:
  SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" ./sync-instance.sh
or:
  ./sync-instance.sh --instance-dir "/path/to/sklauncher/instances/creark"
EOF
  exit 1
fi

INSTANCE_ID="$(basename "$INSTANCE_DIR")"
SK_ROOT="$(cd "$INSTANCE_DIR/../.." && pwd)"
MANIFEST_SRC="$SK_ROOT/manifests/$INSTANCE_ID.json"
INSTANCES_JSON="$SK_ROOT/instances.json"

if [[ ! -f "$MANIFEST_SRC" ]]; then
  echo "Error: manifest not found: $MANIFEST_SRC" >&2
  exit 1
fi
if [[ ! -f "$INSTANCES_JSON" ]]; then
  echo "Error: instances.json not found: $INSTANCES_JSON" >&2
  exit 1
fi

MANIFEST_DIR="$SCRIPT_DIR/manifest"
LOCAL_MODS_DIR="$SCRIPT_DIR/local-mods"
CONFIG_DIR="$SCRIPT_DIR/config"

mkdir -p "$MANIFEST_DIR" "$LOCAL_MODS_DIR"

echo "Syncing from: $INSTANCE_DIR"

# manifest/creark.json
cp "$MANIFEST_SRC" "$MANIFEST_DIR/creark.json"
echo "Synced manifest/creark.json"

# manifest/pack.json + local-mods/ (needs manifest + on-disk mods cross-check)
INSTANCE_ID="$INSTANCE_ID" \
INSTANCE_DIR="$INSTANCE_DIR" \
INSTANCES_JSON="$INSTANCES_JSON" \
MANIFEST_SRC="$MANIFEST_SRC" \
MANIFEST_DIR="$MANIFEST_DIR" \
LOCAL_MODS_DIR="$LOCAL_MODS_DIR" \
python3 <<'PY'
import hashlib, json, os, shutil
from pathlib import Path

instance_id = os.environ["INSTANCE_ID"]
instance_dir = Path(os.environ["INSTANCE_DIR"])
instances_json = Path(os.environ["INSTANCES_JSON"])
manifest_src = Path(os.environ["MANIFEST_SRC"])
manifest_dir = Path(os.environ["MANIFEST_DIR"])
local_mods_dir = Path(os.environ["LOCAL_MODS_DIR"])


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# pack.json: just what build_mrpack.py needs from instances.json
instances = json.loads(instances_json.read_text())
instance_info = next((i for i in instances["instances"] if i["id"] == instance_id), None)
if instance_info is None:
    raise SystemExit(f"instance '{instance_id}' not found in {instances_json}")

pack = {
    "minecraftVersion": instance_info["minecraftVersion"],
    "loaderVersion": instance_info["loaderVersion"],
}
(manifest_dir / "pack.json").write_text(json.dumps(pack, indent=2) + "\n")
print(f"Synced manifest/pack.json: {pack}")

# local-mods/: only jars build_mrpack.py would bundle instead of referencing
# via Modrinth CDN -- i.e. source != modrinth, missing from the manifest, or
# drifted (sha1 mismatch).
manifest = json.loads(manifest_src.read_text())
by_path = {e["filePath"]: e for e in manifest.get("content", [])}

mods_dir = instance_dir / "mods"
all_mod_files = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.name != ".DS_Store")

# clear stale copies so removed/renamed mods don't linger
if local_mods_dir.exists():
    for p in local_mods_dir.iterdir():
        if p.is_file():
            p.unlink()

copied, referenced = 0, 0
for mod_path in all_mod_files:
    rel_path = f"mods/{mod_path.name}"
    entry = by_path.get(rel_path)

    if entry and entry.get("source") == "modrinth":
        actual_sha1 = sha1_of(mod_path)
        if actual_sha1 == entry.get("fileHash", {}).get("sha1"):
            referenced += 1
            continue

    shutil.copy2(mod_path, local_mods_dir / mod_path.name)
    copied += 1

print(f"Synced local-mods/: {copied} bundled (curseforge/local/drifted), {referenced} left to Modrinth CDN")
PY

# config/ (recursive), excluding OS cruft
rm -rf "$CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
if [[ -d "$INSTANCE_DIR/config" ]]; then
  (cd "$INSTANCE_DIR/config" && tar cf - --exclude='.DS_Store' .) | (cd "$CONFIG_DIR" && tar xf -)
fi
echo "Synced config/"

# servers.dat
if [[ -f "$INSTANCE_DIR/servers.dat" ]]; then
  cp "$INSTANCE_DIR/servers.dat" "$SCRIPT_DIR/servers.dat"
  echo "Synced servers.dat"
fi

echo "Done."
