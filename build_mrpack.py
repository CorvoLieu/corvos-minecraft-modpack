#!/usr/bin/env python3
"""
Builds a .mrpack (or a mods-only zip) from the repo's synced modpack data.

Source of truth is manifest/<PACK_NAME>.json (pushed from SKLauncher via
push_instance.py), not a local SKLauncher install -- this lets the script run
identically on a maintainer's machine or in CI. PACK_NAME is read from the
environment (also read from .env, see .env.example), defaulting to "minecraft-modded".

For each mod entry in the manifest:
  - if source is "modrinth" -> reference it via Modrinth's CDN (keeps the
    .mrpack small; downloaded on install like a normal mrpack, or downloaded
    by this script itself in --mods-zip-only mode).
  - if source is "curseforge" -> reference it via CurseForge's forgecdn.net
    CDN the same way, unless the mod author disabled "Allow third-party
    downloads" (detected by probing the URL), in which case it falls back
    to being bundled like a local mod.
  - otherwise (local source, or curseforge with third-party downloads off)
    -> the jar is expected to be committed under local-mods/, and gets
    bundled directly.

Datapack entries (filePath under datapacks/) are handled the same way, with
one difference: datapacks are per-world, not instance-root, so they can't be
installed at their manifest filePath ("datapacks/foo.zip") the way mods can.
They're placed at <DATAPACK_WORLD_NAME>/datapacks/foo.zip instead, matching
the world/level name this pack's server always runs as (LEVEL defaults to
PACK_NAME in the Dockerfile/docker-compose.dev.yml/.env.example) -- that's
the path the itzg server image's overrides/ extraction (and mrpack "files"
downloads) actually land at world-load time. Datapacks are marked
client-"unsupported" in the built index since they're server/world-
authoritative content a client install has no use for. If LEVEL is ever
overridden to something other than PACK_NAME, DATAPACK_WORLD_NAME must be
updated to match (i.e. PACK_NAME must track it too), or datapacks will
silently stop taking effect again.

servers.dat are always bundled directly in overrides/ (server per request),
since there's no "online source" for local config state.

Pass --exclude <substring> (repeatable) and/or --exclude-file <path>
(newline-separated substrings) to drop mods/datapacks by filename match,
e.g. for a server-only build that shouldn't ship client-only mods like
freecam.

Pass --mods-zip-only to skip the .mrpack entirely and instead produce a flat
zip of every mod jar (downloading Modrinth-sourced ones, copying the rest
from local-mods/).

Output filenames are stable (exports/client.mrpack, exports/server.mrpack,
exports/mods-only.zip via --output-name), not versioned -- build steps and
the Dockerfile reference them directly. Version info still lives inside the
build (the mrpack's versionId); GitHub Releases apply a versioned name only
when staging the upload (see release.yml).

See the build-client/build-server/build-mods-zip targets in the Makefile
for the common preset invocations of this script.
"""

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent

# Name of the modpack/instance -- the single value that renaming the pack
# requires changing (see .env.example). Everything below derives from it.
PACK_NAME = os.environ.get("PACK_NAME") or "minecraft-modded"

DEFAULT_MANIFEST_PATH = SCRIPT_DIR / "manifest" / f"{PACK_NAME}.json"
DEFAULT_PACK_JSON_PATH = SCRIPT_DIR / "manifest" / "pack.json"
DEFAULT_LOCAL_MODS_DIR = SCRIPT_DIR / "local-mods"
DEFAULT_LOCAL_DATAPACKS_DIR = SCRIPT_DIR / "local-datapacks"
# DEFAULT_CONFIG_DIR = SCRIPT_DIR / "config"
DEFAULT_SERVERS_DAT_PATH = SCRIPT_DIR / "servers.dat"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "exports"

# World/level name this pack's server always runs as (see docstring above).
# Datapacks must land at <DATAPACK_WORLD_NAME>/datapacks/ to actually load.
DATAPACK_WORLD_NAME = PACK_NAME


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


def curseforge_cdn_url(file_id: str, filename: str) -> str:
    # forgecdn.net serves files at /files/{fileId // 1000}/{fileId % 1000}/{name},
    # the same deterministic layout MultiMC/Prism use for CurseForge mods.
    fid = int(file_id)
    return (
        f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{urllib.parse.quote(filename)}"
    )


def url_is_downloadable(url: str) -> bool:
    """Checks a CDN URL actually resolves -- CurseForge mod authors can
    disable "Allow third-party downloads", which 403s the forgecdn.net URL
    even though the file exists."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError, urllib.error.URLError:
        return False


def load_pack_info(pack_json_path: Path) -> dict:
    return json.loads(pack_json_path.read_text(encoding="utf-8"))


def load_content_entries(manifest_path: Path, path_prefix: str) -> list[dict]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    # dedupe by filePath (last entry wins), same as SKLauncher's own semantics --
    # the manifest can carry stale duplicate entries when a mod's source changes
    # (e.g. re-added from CurseForge after originally coming from Modrinth).
    by_path: dict[str, dict] = {}
    for e in data.get("content", []):
        if e.get("filePath", "").startswith(path_prefix) and e.get("enabled", True):
            by_path[e["filePath"]] = e
    return list(by_path.values())


def load_mod_entries(manifest_path: Path) -> list[dict]:
    return load_content_entries(manifest_path, "mods/")


def load_datapack_entries(manifest_path: Path) -> list[dict]:
    return load_content_entries(manifest_path, "datapacks/")


def load_excludes(exclude: list[str], exclude_file: Path | None) -> list[str]:
    excludes = list(exclude)
    if exclude_file is not None:
        for line in exclude_file.read_text(encoding="utf-8").splitlines():
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
        "--local-datapacks-dir",
        type=Path,
        default=DEFAULT_LOCAL_DATAPACKS_DIR,
        help=f"dir with non-Modrinth datapack zips (default: {DEFAULT_LOCAL_DATAPACKS_DIR})",
    )
    # parser.add_argument(
    #     "--config-dir",
    #     type=Path,
    #     default=DEFAULT_CONFIG_DIR,
    #     help=f"config/ dir to bundle as overrides (default: {DEFAULT_CONFIG_DIR})",
    # )
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
        default=PACK_NAME.capitalize(),
        help="pack name recorded inside the build (modrinth.index.json "
        f"name/summary); does not affect the output filename (default: "
        f"{PACK_NAME.capitalize()}, derived from the PACK_NAME env var)",
    )
    parser.add_argument(
        "--mods-zip-only",
        action="store_true",
        help="skip the .mrpack and produce a flat zip of every mod jar instead",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="output filename stem, written as exports/<name>.mrpack (or "
        ".zip with --mods-zip-only). Default: 'mods-only' with "
        "--mods-zip-only, else 'client'. Stable/unversioned by design -- "
        "build steps reference it directly; version info lives inside the "
        "build (versionId) and gets applied to the filename only when "
        "staging a GitHub Release upload.",
    )
    return parser.parse_args(argv)


def build_content_lists(
    entries: list[dict],
    excludes: list[str],
    dest_path_fn,
    env: dict,
):
    """Returns (online_files, bundled, excluded_names) where bundled is a
    list of (dest_path, filename, entry) for non-Modrinth content.
    dest_path_fn(entry) computes where the file needs to end up (instance-
    root-relative for mods, world-relative for datapacks)."""
    online_files = []
    bundled = []
    excluded_names = []

    for entry in entries:
        filename = entry["filename"]
        if any(e in filename.lower() for e in excludes):
            excluded_names.append(filename)
            continue

        dest_path = dest_path_fn(entry)
        if entry.get("source") == "modrinth":
            url = modrinth_cdn_url(entry["projectId"], entry["versionId"], filename)
            online_files.append(
                {
                    "path": dest_path,
                    "hashes": {
                        "sha1": entry["fileHash"]["sha1"],
                        "sha512": entry["fileHash"]["sha512"],
                    },
                    "env": env,
                    "downloads": [url],
                    "fileSize": entry["size"],
                }
            )
        elif entry.get("source") == "curseforge":
            url = curseforge_cdn_url(entry["versionId"], filename)
            if url_is_downloadable(url):
                online_files.append(
                    {
                        "path": dest_path,
                        "hashes": {
                            "sha1": entry["fileHash"]["sha1"],
                            "sha512": entry["fileHash"]["sha512"],
                        },
                        "env": env,
                        "downloads": [url],
                        "fileSize": entry["size"],
                    }
                )
            else:
                print(
                    f"  {filename}: third-party downloads disabled on CurseForge, "
                    "bundling locally instead"
                )
                bundled.append((dest_path, filename, entry))
        else:
            bundled.append((dest_path, filename, entry))

    return online_files, bundled, excluded_names


def build_mod_lists(mod_entries: list[dict], excludes: list[str]):
    return build_content_lists(
        mod_entries,
        excludes,
        dest_path_fn=lambda entry: entry["filePath"],
        env={"client": "required", "server": "required"},
    )


def datapack_dest_path(filename: str) -> str:
    return f"{DATAPACK_WORLD_NAME}/datapacks/{filename}"


def build_datapack_lists(datapack_entries: list[dict], excludes: list[str]):
    return build_content_lists(
        datapack_entries,
        excludes,
        dest_path_fn=lambda entry: datapack_dest_path(entry["filename"]),
        # Datapacks are server/world-authoritative -- a client install has no
        # use for the file itself (only the server's world needs it).
        env={"client": "unsupported", "server": "required"},
    )


def resolve_bundled_content_paths(bundled: list[tuple], content_dir: Path, label: str):
    """Resolves each (dest_path, filename, entry) to (dest_path, abs_path),
    verifying the file exists locally and its hash matches the manifest."""
    resolved = []
    for dest_path, filename, entry in bundled:
        local_path = content_dir / filename
        if not local_path.exists():
            raise SystemExit(
                f"Missing local {label} file: {local_path} "
                f"(source={entry.get('source')}, expected from manifest)"
            )
        expected_sha1 = entry.get("fileHash", {}).get("sha1")
        if expected_sha1 and sha1_of(local_path) != expected_sha1:
            raise SystemExit(f"sha1 mismatch for {local_path} vs manifest entry")
        resolved.append((dest_path, local_path))
    return resolved


def build_server_overrides(servers_dat: Path):
    overrides = []
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
    bundled_resolved = resolve_bundled_content_paths(bundled, args.local_mods_dir, "mod")

    args.output_dir.mkdir(exist_ok=True)
    output_name = args.output_name or "mods-only"
    out_path = args.output_dir / f"{output_name}.zip"

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in online_files:
            url = entry["downloads"][0]
            filename = Path(entry["path"]).name
            print(f"Downloading {filename} ...")
            with tempfile.NamedTemporaryFile() as tmp:
                tmp = tempfile.NamedTemporaryFile(delete=False)
                tmp.close()
            try:
                download(url, Path(tmp.name))
                zf.write(tmp.name, arcname=entry["path"])
            finally:
                os.unlink(tmp.name)

        for rel_path, abs_path in bundled_resolved:
            zf.write(abs_path, arcname=rel_path)

    total = len(online_files) + len(bundled_resolved)
    print(f"Exported: {out_path}")
    print(f"  {total} mod file(s): {len(online_files)} downloaded, {len(bundled_resolved)} local")


def build_mrpack(args, mod_entries, datapack_entries, excludes, pack_info, version_id):
    online_mods, bundled_mods, excluded_mod_names = build_mod_lists(mod_entries, excludes)
    online_datapacks, bundled_datapacks, excluded_datapack_names = build_datapack_lists(
        datapack_entries, excludes
    )
    excluded_names = excluded_mod_names + excluded_datapack_names
    if excluded_names:
        print(f"Excluding {len(excluded_names)} file(s): {', '.join(excluded_names)}")

    bundled_resolved = resolve_bundled_content_paths(bundled_mods, args.local_mods_dir, "mod")
    bundled_resolved += resolve_bundled_content_paths(
        bundled_datapacks, args.local_datapacks_dir, "datapack"
    )
    bundled_resolved += build_server_overrides(args.servers_dat)

    print(
        f"Mods: {len(online_mods)} referenced online, "
        f"{len(bundled_mods)} bundled directly (local, or curseforge "
        "with third-party downloads disabled)"
    )
    print(
        f"Datapacks: {len(online_datapacks)} referenced online, "
        f"{len(bundled_datapacks)} bundled directly, "
        f"landing at {DATAPACK_WORLD_NAME}/datapacks/"
    )

    online_files = online_mods + online_datapacks

    args.output_dir.mkdir(exist_ok=True)
    output_name = args.output_name or "client"
    out_path = args.output_dir / f"{output_name}.mrpack"

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
        datapack_entries = load_datapack_entries(args.manifest)
        build_mrpack(args, mod_entries, datapack_entries, excludes, pack_info, version_id)


if __name__ == "__main__":
    main()
