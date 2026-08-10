#!/usr/bin/env python3
"""
Pushes state from a local SKLauncher instance (the "working copy") up into
repo-relative locations (manifest/, config/, servers.dat, local-mods/) --
the repo is the "remote" source of truth -- so build_mrpack.py (and
eventually CI) can build the modpack without needing access to the
maintainer's machine.

What gets pushed:
  manifest/creark.json  - copy of the SKLauncher manifest, as-is
  manifest/pack.json    - just {minecraftVersion, loaderVersion}, extracted
                           from SKLauncher's instances.json
  config/                - recursive copy of the instance's config/ dir
  servers.dat             - copy
  local-mods/            - mod jars that build_mrpack.py can't reference from
                           an online CDN: local-sourced mods, drifted files
                           (sha1 no longer matches the manifest), and
                           CurseForge-sourced mods whose author disabled
                           "Allow third-party downloads". Modrinth-sourced
                           jars and downloadable CurseForge-sourced jars are
                           intentionally NOT copied here; they're fetched
                           from their CDN at build time instead, so we don't
                           commit hundreds of MB of jars to git.

Configure which SKLauncher instance directory to push from, in priority order:
  1. --instance-dir <path> (or -i <path>) CLI flag -- full path override
  2. SK_INSTANCE_DIR environment variable (also read from .env, see
     .env.example) -- full path override, same as --instance-dir
  3. OS default directory with a custom instance name:
       --instance-name <name> (or -n <name>) CLI flag, or the INSTANCE_NAME
       environment variable (also read from .env). Defaults to "creark".
       macOS: ~/Library/Application Support/sklauncher/instances/<name>
       Windows/Linux: SKLauncher's install layout differs there and there's
       no safe default -- set SK_INSTANCE_DIR or pass --instance-dir.

Usage:
  uv run push_instance.py
  uv run push_instance.py --instance-dir "/path/to/sklauncher/instances/creark"
  uv run push_instance.py --instance-name my-other-instance
  SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" uv run push_instance.py
  INSTANCE_NAME="my-other-instance" uv run push_instance.py
"""

import argparse
import json
import os
import platform
import shutil
from pathlib import Path

from dotenv import load_dotenv

from build_mrpack import curseforge_cdn_url, sha1_of, url_is_downloadable

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_DIR = SCRIPT_DIR / "manifest"
LOCAL_MODS_DIR = SCRIPT_DIR / "local-mods"
# CONFIG_DIR = SCRIPT_DIR / "config"
SERVERS_DAT = SCRIPT_DIR / "servers.dat"
DEFAULT_INSTANCE_NAME = "creark"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-dir",
        "-i",
        default=None,
        help="path to the SKLauncher instance dir (overrides SK_INSTANCE_DIR and --instance-name)",
    )
    parser.add_argument(
        "--instance-name",
        "-n",
        default=None,
        help="instance name to look up under the OS default SKLauncher "
        f"instances dir (overrides INSTANCE_NAME, default: {DEFAULT_INSTANCE_NAME}). "
        "Ignored if --instance-dir/SK_INSTANCE_DIR is set.",
    )
    return parser.parse_args()


def default_instance_dir(instance_name: str) -> Path | None:
    if platform.system() == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "sklauncher"
            / "instances"
            / instance_name
        )
    return None


def resolve_instance_dir(cli_arg: str | None, cli_instance_name: str | None = None) -> Path:
    if cli_arg:
        return Path(cli_arg)

    env_value = os.environ.get("SK_INSTANCE_DIR")
    if env_value:
        return Path(env_value)

    instance_name = cli_instance_name or os.environ.get("INSTANCE_NAME") or DEFAULT_INSTANCE_NAME
    default = default_instance_dir(instance_name)
    if default is not None:
        return default

    raise SystemExit(
        "Error: no default SKLauncher instance path known for this OS.\n"
        "Set SK_INSTANCE_DIR or pass --instance-dir <path>."
    )


def sync_manifest_and_pack_json(
    instance_id: str,
    manifest_src: Path,
    instances_json: Path,
):
    MANIFEST_DIR.mkdir(exist_ok=True)
    shutil.copy2(manifest_src, MANIFEST_DIR / "creark.json")
    print("Synced manifest/creark.json")

    instances = json.loads(instances_json.read_text())
    instance_info = next((i for i in instances["instances"] if i["id"] == instance_id), None)
    if instance_info is None:
        raise SystemExit(f"instance '{instance_id}' not found in {instances_json}")

    pack = {
        "minecraftVersion": instance_info["minecraftVersion"],
        "loaderVersion": instance_info["loaderVersion"],
    }
    (MANIFEST_DIR / "pack.json").write_text(json.dumps(pack, indent=2) + "\n")
    print(f"Synced manifest/pack.json: {pack}")


def sync_local_mods(instance_dir: Path, manifest_src: Path):
    manifest = json.loads(manifest_src.read_text())
    by_path = {e["filePath"]: e for e in manifest.get("content", [])}

    mods_dir = instance_dir / "mods"
    all_mod_files = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.name != ".DS_Store")

    LOCAL_MODS_DIR.mkdir(exist_ok=True)
    # clear stale copies so removed/renamed mods don't linger
    for p in LOCAL_MODS_DIR.iterdir():
        if p.is_file():
            p.unlink()

    copied, referenced = 0, 0
    for mod_path in all_mod_files:
        rel_path = f"mods/{mod_path.name}"
        entry = by_path.get(rel_path)

        if entry and sha1_of(mod_path) == entry.get("fileHash", {}).get("sha1"):
            source = entry.get("source")
            if source == "modrinth":
                referenced += 1
                continue
            if source == "curseforge" and url_is_downloadable(
                curseforge_cdn_url(entry["versionId"], mod_path.name)
            ):
                referenced += 1
                continue

        shutil.copy2(mod_path, LOCAL_MODS_DIR / mod_path.name)
        copied += 1

    print(
        f"Synced local-mods/: {copied} bundled (local/drifted/curseforge "
        f"with third-party downloads disabled), {referenced} left to CDN"
    )


# def sync_config(instance_dir: Path):
#     src = instance_dir / "config"
#     if CONFIG_DIR.exists():
#         shutil.rmtree(CONFIG_DIR)
#     if src.exists():
#         shutil.copytree(src, CONFIG_DIR, ignore=shutil.ignore_patterns(".DS_Store"))
#     else:
#         CONFIG_DIR.mkdir()
#     print("Synced config/")


def sync_servers_dat(instance_dir: Path):
    src = instance_dir / "servers.dat"
    if src.exists():
        shutil.copy2(src, SERVERS_DAT)
        print("Synced servers.dat")


def main():
    load_dotenv()
    args = parse_args()

    instance_dir = resolve_instance_dir(args.instance_dir, args.instance_name)
    if not instance_dir.is_dir():
        raise SystemExit(
            f"Error: SKLauncher instance directory not found: {instance_dir}\n\n"
            'Point this script at your own local SKLauncher "creark" instance via:\n'
            '  SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" uv run push_instance.py\n'
            "or:\n"
            '  uv run push_instance.py --instance-dir "/path/to/sklauncher/instances/creark"'
        )

    instance_id = instance_dir.name
    sk_root = instance_dir.parent.parent
    manifest_src = sk_root / "manifests" / f"{instance_id}.json"
    instances_json = sk_root / "instances.json"

    if not manifest_src.is_file():
        raise SystemExit(f"Error: manifest not found: {manifest_src}")
    if not instances_json.is_file():
        raise SystemExit(f"Error: instances.json not found: {instances_json}")

    print(f"Syncing from: {instance_dir}")
    sync_manifest_and_pack_json(instance_id, manifest_src, instances_json)
    sync_local_mods(instance_dir, manifest_src)
    # sync_config(instance_dir)
    sync_servers_dat(instance_dir)
    print("Done.")


if __name__ == "__main__":
    main()
