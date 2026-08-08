#!/usr/bin/env python3
"""
Builds a .mrpack (or a mods-only zip) from the repo's synced modpack data.

Source of truth is manifest/creark.json (synced from SKLauncher via
sync_instance.py), not a local SKLauncher install -- this lets the script run
identically on a maintainer's machine or in CI.

For each mod entry in the manifest:
  - if source is "modrinth" -> reference it via Modrinth's CDN (keeps the
    .mrpack small; downloaded on install like a normal mrpack, or downloaded
    by this script itself in --mods-zip-only mode).
  - otherwise (curseforge/local source) -> the jar is expected to be
    committed under local-mods/, and gets bundled directly.

config/ and servers.dat are always bundled directly in overrides/ (server
config, per request), since there's no "online source" for local config state.

Pass --exclude <substring> (repeatable) and/or --exclude-file <path>
(newline-separated substrings) to drop mods by filename match, e.g. for a
server-only build that shouldn't ship client-only mods like freecam.

Pass --mods-zip-only to skip the .mrpack entirely and instead produce a flat
zip of every mod jar (downloading Modrinth-sourced ones, copying the rest
from local-mods/).

See the build-client/build-server/build-mods-zip targets in the Makefile
for the common preset invocations of this script.
"""

import argparse
import hashlib
import json
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST_PATH = SCRIPT_DIR / "manifest" / "creark.json"
DEFAULT_PACK_JSON_PATH = SCRIPT_DIR / "manifest" / "pack.json"
DEFAULT_LOCAL_MODS_DIR = SCRIPT_DIR / "local-mods"
DEFAULT_CONFIG_DIR = SCRIPT_DIR / "config"
DEFAULT_SERVERS_DAT_PATH = SCRIPT_DIR / "servers.dat"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "exports"


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


def load_pack_info(pack_json_path: Path) -> dict:
    return json.loads(pack_json_path.read_text())


def load_mod_entries(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text())
    # dedupe by filePath (last entry wins), same as SKLauncher's own semantics --
    # the manifest can carry stale duplicate entries when a mod's source changes
    # (e.g. re-added from CurseForge after originally coming from Modrinth).
    by_path: dict[str, dict] = {}
    for e in data.get("content", []):
        if e.get("filePath", "").startswith("mods/") and e.get("enabled", True):
            by_path[e["filePath"]] = e
    return list(by_path.values())


def load_excludes(exclude: list[str], exclude_file: Path | None) -> list[str]:
    excludes = list(exclude)
    if exclude_file is not None:
        for line in exclude_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                excludes.append(line)
    return [e.lower() for e in excludes]


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=f"path to the SKLauncher manifest json (default: {DEFAULT_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--pack-json",
        type=Path,
        default=DEFAULT_PACK_JSON_PATH,
        help=f"pack.json with minecraftVersion/loaderVersion (default: {DEFAULT_PACK_JSON_PATH})",
    )
    parser.add_argument(
        "--local-mods-dir",
        type=Path,
        default=DEFAULT_LOCAL_MODS_DIR,
        help=f"dir with non-Modrinth mod jars (default: {DEFAULT_LOCAL_MODS_DIR})",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help=f"config/ dir to bundle as overrides (default: {DEFAULT_CONFIG_DIR})",
    )
    parser.add_argument(
        "--servers-dat",
        type=Path,
        default=DEFAULT_SERVERS_DAT_PATH,
        help=f"servers.dat to bundle as an override (default: {DEFAULT_SERVERS_DAT_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"dir to write the built zip/mrpack into (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="drop mods whose filename contains this (case-insensitive); repeatable",
    )
    parser.add_argument(
        "--exclude-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="file of newline-separated filename substrings to exclude (# comments allowed)",
    )
    parser.add_argument(
        "--pack-name",
        default="Creark",
        help="pack name / output filename prefix (default: Creark)",
    )
    parser.add_argument(
        "--mods-zip-only",
        action="store_true",
        help="skip the .mrpack and produce a flat zip of every mod jar instead",
    )
    return parser.parse_args(argv)


def build_mod_lists(mod_entries: list[dict], excludes: list[str]):
    """Returns (online_files, bundled, excluded_names) where bundled is a
    list of (arcname, source_path) for non-Modrinth mods."""
    online_files = []
    bundled = []
    excluded_names = []

    for entry in mod_entries:
        filename = entry["filename"]
        if any(e in filename.lower() for e in excludes):
            excluded_names.append(filename)
            continue

        rel_path = entry["filePath"]
        if entry.get("source") == "modrinth":
            url = modrinth_cdn_url(entry["projectId"], entry["versionId"], filename)
            online_files.append(
                {
                    "path": rel_path,
                    "hashes": {
                        "sha1": entry["fileHash"]["sha1"],
                        "sha512": entry["fileHash"]["sha512"],
                    },
                    "env": {"client": "required", "server": "required"},
                    "downloads": [url],
                    "fileSize": entry["size"],
                }
            )
        else:
            bundled.append((rel_path, filename, entry))

    return online_files, bundled, excluded_names


def resolve_bundled_mod_paths(bundled: list[tuple], local_mods_dir: Path):
    """Resolves each (rel_path, filename, entry) to (arcname, abs_path),
    verifying the file exists locally and its hash matches the manifest."""
    resolved = []
    for rel_path, filename, entry in bundled:
        local_path = local_mods_dir / filename
        if not local_path.exists():
            raise SystemExit(
                f"Missing local mod file: {local_path} "
                f"(source={entry.get('source')}, expected from manifest)"
            )
        expected_sha1 = entry.get("fileHash", {}).get("sha1")
        if expected_sha1 and sha1_of(local_path) != expected_sha1:
            raise SystemExit(f"sha1 mismatch for {local_path} vs manifest entry")
        resolved.append((rel_path, local_path))
    return resolved


def build_config_and_server_overrides(config_dir: Path, servers_dat: Path):
    overrides = []
    if config_dir.exists():
        for p in config_dir.rglob("*"):
            if p.is_file() and p.name != ".DS_Store":
                rel = p.relative_to(config_dir.parent)
                overrides.append((rel.as_posix(), p))
    if servers_dat.exists():
        overrides.append(("servers.dat", servers_dat))
    return overrides


def download(url: str, dest: Path):
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def build_mods_zip_only(args, mod_entries, excludes, version_id):
    online_files, bundled, excluded_names = build_mod_lists(mod_entries, excludes)
    if excluded_names:
        print(f"Excluding {len(excluded_names)} mod(s): {', '.join(excluded_names)}")
    bundled_resolved = resolve_bundled_mod_paths(bundled, args.local_mods_dir)

    args.output_dir.mkdir(exist_ok=True)
    out_path = args.output_dir / f"{args.pack_name}-Mods-Only-{version_id}.zip"

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in online_files:
            url = entry["downloads"][0]
            filename = Path(entry["path"]).name
            print(f"Downloading {filename} ...")
            with tempfile.NamedTemporaryFile() as tmp:
                download(url, Path(tmp.name))
                zf.write(tmp.name, arcname=entry["path"])
        for rel_path, abs_path in bundled_resolved:
            zf.write(abs_path, arcname=rel_path)

    total = len(online_files) + len(bundled_resolved)
    print(f"Exported: {out_path}")
    print(f"  {total} mod file(s): {len(online_files)} downloaded, {len(bundled_resolved)} local")


def build_mrpack(args, mod_entries, excludes, pack_info, version_id):
    online_files, bundled, excluded_names = build_mod_lists(mod_entries, excludes)
    if excluded_names:
        print(f"Excluding {len(excluded_names)} mod(s): {', '.join(excluded_names)}")
    bundled_resolved = resolve_bundled_mod_paths(bundled, args.local_mods_dir)
    bundled_resolved += build_config_and_server_overrides(args.config_dir, args.servers_dat)

    print(
        f"Mods: {len(online_files)} referenced online, "
        f"{len(bundled_resolved)} bundled directly (local/curseforge/config)"
    )

    args.output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = args.output_dir / f"{args.pack_name}-{timestamp}.mrpack"

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version_id,
        "name": args.pack_name,
        "summary": f"{args.pack_name} modpack export ({version_id})",
        "files": online_files,
        "dependencies": {
            "minecraft": pack_info["minecraftVersion"],
            "neoforge": pack_info["loaderVersion"],
        },
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2))
        for rel_path, abs_path in bundled_resolved:
            zf.write(abs_path, arcname=f"overrides/{rel_path}")

    print(f"Exported: {out_path}")
    print(
        f"  {len(online_files)} files referenced online, "
        f"{len(bundled_resolved)} files bundled in overrides/"
    )


def main(argv: list[str] | None = None):
    args = parse_args(argv)

    if not args.manifest.exists():
        raise SystemExit(f"Manifest not found: {args.manifest}")
    if not args.pack_json.exists():
        raise SystemExit(f"pack.json not found: {args.pack_json}")

    excludes = load_excludes(args.exclude, args.exclude_file)
    mod_entries = load_mod_entries(args.manifest)
    version_id = datetime.now().strftime("%Y.%m.%d-%H%M")

    if args.mods_zip_only:
        build_mods_zip_only(args, mod_entries, excludes, version_id)
    else:
        pack_info = load_pack_info(args.pack_json)
        build_mrpack(args, mod_entries, excludes, pack_info, version_id)


if __name__ == "__main__":
    main()
