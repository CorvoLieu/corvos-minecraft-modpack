#!/usr/bin/env python3
"""
Builds a .mrpack from the SKLauncher "creark" instance.

Cross-checks SKLauncher's manifest (manifests/creark.json) against the actual
files on disk in mods/, since the two can drift (e.g. a mod manually disabled
by renaming to *.disabled outside the app won't be reflected in the manifest).

For each mod file:
  - if the manifest has a matching filePath, source is "modrinth", and the
    file's sha1 matches the manifest's -> reference it via Modrinth's CDN
    (keeps the .mrpack small; downloaded on install like a normal mrpack).
  - otherwise (curseforge/local source, hash mismatch, missing from
    manifest, or disabled) -> bundle the actual file directly in overrides/,
    so the export always matches what's really installed.

config/ and servers.dat are always bundled directly in overrides/ (server
config, per request), since there's no "online source" for local config state.

Pass --exclude <substring> (repeatable) to drop mods by filename match, e.g.
for a server-only build that shouldn't ship client-only mods like freecam.
"""
import argparse
import hashlib
import json
import sys
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

SK_ROOT = Path("/Users/haolieu/Library/Application Support/sklauncher")
INSTANCE_DIR = SK_ROOT / "instances" / "creark"
MANIFEST_PATH = SK_ROOT / "manifests" / "creark.json"
INSTANCES_JSON = SK_ROOT / "instances.json"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "exports"


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def modrinth_cdn_url(project_id: str, version_id: str, filename: str) -> str:
    return (
        f"https://cdn.modrinth.com/data/{project_id}/versions/{version_id}/"
        f"{urllib.parse.quote(filename)}"
    )


def load_instance_info() -> dict:
    data = json.loads(INSTANCES_JSON.read_text())
    for inst in data["instances"]:
        if inst["id"] == "creark":
            return inst
    raise SystemExit("creark instance not found in instances.json")


def load_manifest_by_path() -> dict:
    data = json.loads(MANIFEST_PATH.read_text())
    by_path = {}
    for entry in data.get("content", []):
        by_path[entry["filePath"]] = entry
    return by_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="drop mods whose filename contains this (case-insensitive); repeatable",
    )
    parser.add_argument(
        "--pack-name",
        default="Creark",
        help="pack name / output filename prefix (default: Creark)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    pack_name = args.pack_name
    excludes = [s.lower() for s in args.exclude]

    if not INSTANCE_DIR.exists():
        raise SystemExit(f"Instance dir not found: {INSTANCE_DIR}")

    instance_info = load_instance_info()
    manifest_by_path = load_manifest_by_path()

    mods_dir = INSTANCE_DIR / "mods"
    all_mod_files = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.name != ".DS_Store")

    excluded_names = [p.name for p in all_mod_files if any(e in p.name.lower() for e in excludes)]
    mod_files = [p for p in all_mod_files if p.name not in excluded_names]
    if excluded_names:
        print(f"Excluding {len(excluded_names)} mod(s): {', '.join(excluded_names)}")

    online_files = []  # for modrinth.index.json "files"
    bundled_paths = []  # relative paths (within instance dir) to copy into overrides/

    referenced, bundled = 0, 0
    for mod_path in mod_files:
        rel_path = f"mods/{mod_path.name}"
        entry = manifest_by_path.get(rel_path)

        if entry and entry.get("source") == "modrinth":
            actual_sha1 = sha1_of(mod_path)
            if actual_sha1 == entry.get("fileHash", {}).get("sha1"):
                url = modrinth_cdn_url(entry["projectId"], entry["versionId"], mod_path.name)
                online_files.append(
                    {
                        "path": rel_path,
                        "hashes": {
                            "sha1": actual_sha1,
                            "sha512": entry["fileHash"]["sha512"],
                        },
                        "env": {"client": "required", "server": "required"},
                        "downloads": [url],
                        "fileSize": mod_path.stat().st_size,
                    }
                )
                referenced += 1
                continue

        # fallback: bundle the real file directly (curseforge/local/disabled/drifted)
        bundled_paths.append(Path("mods") / mod_path.name)
        bundled += 1

    print(f"Mods: {referenced} referenced online, {bundled} bundled directly (drift/local/curseforge)")

    # server config: always bundled directly, no online source for these
    if (INSTANCE_DIR / "config").exists():
        for p in (INSTANCE_DIR / "config").rglob("*"):
            if p.is_file() and p.name != ".DS_Store":
                bundled_paths.append(p.relative_to(INSTANCE_DIR))
    if (INSTANCE_DIR / "servers.dat").exists():
        bundled_paths.append(Path("servers.dat"))

    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_id = datetime.now().strftime("%Y.%m.%d-%H%M")
    out_path = OUTPUT_DIR / f"{pack_name}-{timestamp}.mrpack"

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version_id,
        "name": pack_name,
        "summary": f"{pack_name} modpack export ({version_id})",
        "files": online_files,
        "dependencies": {
            "minecraft": instance_info["minecraftVersion"],
            "neoforge": instance_info["loaderVersion"],
        },
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2))
        for rel in bundled_paths:
            src = INSTANCE_DIR / rel
            zf.write(src, arcname=f"overrides/{rel.as_posix()}")

    print(f"Exported: {out_path}")
    print(f"  {len(online_files)} files referenced online, {len(bundled_paths)} files bundled in overrides/")


if __name__ == "__main__":
    main()
