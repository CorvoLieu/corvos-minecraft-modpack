#!/usr/bin/env python3
"""
Pulls repo state (the "remote" source of truth) down into a local SKLauncher
instance (the "working copy") so it matches this repo's currently-checked-out
state -- the reverse of push_instance.py, which pushes FROM an instance INTO
the repo. This script copies FROM the repo INTO an instance.

Two use cases:

  1. Bootstrap: populate a fresh/empty SKLauncher instance for a new
     maintainer, instead of manually importing the latest release .mrpack.
  2. Branch-switch resync: after checking out a different branch/commit with
     a different mod set, re-run this script against your existing instance
     to converge it to whatever manifest is now checked out -- mods that are
     no longer in the manifest get PRUNED from the instance's mods/, not just
     left stale alongside newly-added ones.

What gets pulled INTO the instance, from repo state:
  manifest/creark.json  -> copied as-is into the instance's SKLauncher
                            manifest file (manifests/<id>.json in the
                            SKLauncher root), so SKLauncher's own UI reflects
                            the same enabled/disabled mod list.
  manifest/pack.json    -> minecraftVersion/loaderVersion written into the
                            matching entry in SKLauncher's instances.json.
  mods/                 -> reconciled to exactly match the manifest's mods/
                            entries (skipped if already present with a
                            matching sha1): Modrinth-sourced mods are
                            downloaded from the Modrinth CDN; CurseForge-
                            sourced mods are downloaded from CurseForge's CDN
                            unless the author disabled "Allow third-party
                            downloads" (probed the same way build_mrpack.py
                            does); everything else (local source, or
                            CurseForge with downloads disabled) is copied
                            from local-mods/ (matched by sha1, same
                            cross-check build_mrpack.py uses). Any jar
                            already in the instance's mods/ with NO
                            corresponding manifest entry is REMOVED.
  config/                - if config/ exists in the repo, reconciled the same
                            additive/subtractive way as mods/ (see "Design
                            decisions" below).
  servers.dat            - copied as-is (repo is always authoritative).

Instance must already exist in SKLauncher (created via its "New Instance"
UI) before running this script -- see "Design decisions" below for why.

Deleting files is destructive, so by default (no --yes) this script always
previews first -- it computes and PRINTS everything it would add/update/
remove, then interactively prompts for confirmation ([y/N]) before touching
anything. Pass --yes to skip the preview and prompt and apply immediately
(e.g. for non-interactive/scripted use).

Configure which SKLauncher instance directory to target, in priority order
(same resolution as push_instance.py):
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
  uv run pull_instance.py               # preview, then prompt to confirm
  uv run pull_instance.py --yes         # apply without prompting
  uv run pull_instance.py --instance-dir "/path/to/sklauncher/instances/creark"
  uv run pull_instance.py --instance-name my-other-instance
  SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" uv run pull_instance.py

Design decisions (flagged for review, see PR description):
  - Instance registration (instances.json) isn't reverse-engineered enough
    to safely CREATE a brand-new entry from scratch (icon, groups, java args,
    and other SKLauncher-internal fields are unknown/unverified). Instead,
    this script requires the instance to already exist -- create it once via
    SKLauncher's "New Instance" UI (any mod loader/version; this script
    overwrites minecraftVersion/loaderVersion to match manifest/pack.json).
    It then only ever *updates* fields it already knows the shape of, the
    same fields push_instance.py reads. This keeps the bootstrap workaround
    to "create an empty instance in the UI, then run this script" instead of
    "manually import the latest .mrpack".
  - config/ syncing defaults to ON if the repo has a config/ directory, even
    though config/ bundling into the .mrpack itself is currently disabled in
    build_mrpack.py/push_instance.py. Rationale: a maintainer's local dev
    instance benefits from matching config/ across branch switches even
    though the shipped pack doesn't bundle it (yet). Pass --skip-config to
    opt out.
"""

import argparse
import json
import shutil
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from build_mrpack import (
    curseforge_cdn_url,
    load_mod_entries,
    modrinth_cdn_url,
    sha1_of,
    url_is_downloadable,
)
from push_instance import resolve_instance_dir

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest" / "creark.json"
PACK_JSON_PATH = SCRIPT_DIR / "manifest" / "pack.json"
LOCAL_MODS_DIR = SCRIPT_DIR / "local-mods"
CONFIG_DIR = SCRIPT_DIR / "config"
SERVERS_DAT = SCRIPT_DIR / "servers.dat"


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
        "instances dir (overrides INSTANCE_NAME, default: creark). Ignored "
        "if --instance-dir/SK_INSTANCE_DIR is set.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="apply changes immediately without previewing/prompting first. "
        "Without this flag the script previews changes and asks for "
        "confirmation before applying (required to delete stale jars/files).",
    )
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="don't sync config/ into the instance even if the repo has one",
    )
    return parser.parse_args()


def download(url: str, dest: Path):
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def reconcile_dir(
    label: str,
    instance_subdir: Path,
    wanted: dict[str, Path],
    apply: bool,
) -> tuple[list[str], list[str], list[str]]:
    """Reconciles instance_subdir to exactly contain the files described by
    `wanted` (relative filename -> source path to copy from). Matches by
    sha1 to skip up-to-date files. Returns (added, updated, removed) names.
    """
    instance_subdir.mkdir(parents=True, exist_ok=True)

    existing = {
        str(p.relative_to(instance_subdir)): p
        for p in instance_subdir.rglob("*")
        if p.is_file() and p.name != ".DS_Store"
    }

    added, updated, removed = [], [], []

    for name, src in wanted.items():
        dest = instance_subdir / name
        if dest.exists() and sha1_of(dest) == sha1_of(src):
            continue
        action = "Updating" if dest.exists() else "Adding"
        print(f"  [{label}] {action}: {name}")
        if apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        (updated if dest.exists() else added).append(name)

    for name, path in existing.items():
        if name not in wanted:
            print(f"  [{label}] Removing (not in manifest): {name}")
            removed.append(name)
            if apply:
                path.unlink()

    return added, updated, removed


def sync_mods(instance_dir: Path, mod_entries: list[dict], apply: bool):
    mods_dir = instance_dir / "mods"
    mods_dir.mkdir(exist_ok=True)

    existing = {p.name: p for p in mods_dir.iterdir() if p.is_file() and p.name != ".DS_Store"}
    wanted_names = {e["filename"] for e in mod_entries}

    added, updated, skipped, removed = 0, 0, 0, 0

    for entry in mod_entries:
        filename = entry["filename"]
        dest = mods_dir / filename
        expected_sha1 = entry.get("fileHash", {}).get("sha1")

        if dest.exists() and expected_sha1 and sha1_of(dest) == expected_sha1:
            skipped += 1
            continue

        is_new = not dest.exists()
        source = entry.get("source")
        cdn_url = None
        if source == "modrinth":
            cdn_url = modrinth_cdn_url(entry["projectId"], entry["versionId"], filename)
        elif source == "curseforge":
            candidate_url = curseforge_cdn_url(entry["versionId"], filename)
            if url_is_downloadable(candidate_url):
                cdn_url = candidate_url

        if cdn_url is not None:
            print(f"  [mods] {'Downloading' if is_new else 'Updating'}: {filename}")
            if apply:
                download(cdn_url, dest)
        else:
            # local source, or curseforge with third-party downloads disabled
            local_path = LOCAL_MODS_DIR / filename
            if not local_path.exists():
                raise SystemExit(
                    f"Missing local mod file: {local_path} "
                    f"(source={source}, expected from manifest)"
                )
            if expected_sha1 and sha1_of(local_path) != expected_sha1:
                raise SystemExit(f"sha1 mismatch for {local_path} vs manifest entry")
            print(f"  [mods] {'Copying' if is_new else 'Updating'}: {filename}")
            if apply:
                shutil.copy2(local_path, dest)

        if is_new:
            added += 1
        else:
            updated += 1

    for name, path in existing.items():
        if name not in wanted_names:
            print(f"  [mods] Removing (not in manifest): {name}")
            removed += 1
            if apply:
                path.unlink()

    print(
        f"mods/: {added} added, {updated} updated, {skipped} already up to date, {removed} removed"
    )
    return added, updated, removed


def sync_config(instance_dir: Path, apply: bool) -> tuple[int, int, int]:
    if not CONFIG_DIR.exists():
        print("config/: repo has no config/ dir, skipping")
        return (0, 0, 0)

    wanted = {
        str(p.relative_to(CONFIG_DIR)): p
        for p in CONFIG_DIR.rglob("*")
        if p.is_file() and p.name != ".DS_Store"
    }
    added, updated, removed = reconcile_dir("config", instance_dir / "config", wanted, apply)
    print(f"config/: {len(added)} added, {len(updated)} updated, {len(removed)} removed")
    return (len(added), len(updated), len(removed))


def sync_servers_dat(instance_dir: Path, apply: bool) -> bool:
    dest = instance_dir / "servers.dat"
    if dest.exists() and SERVERS_DAT.exists() and sha1_of(dest) == sha1_of(SERVERS_DAT):
        print("servers.dat: already up to date")
        return False
    print("servers.dat: copying (repo-authoritative)")
    if apply:
        shutil.copy2(SERVERS_DAT, dest)
    return True


def sync_manifest_and_pack_json(
    instance_id: str, manifest_dest: Path, instances_json: Path, apply: bool
) -> bool:
    changed = False

    manifest_content = MANIFEST_PATH.read_text()
    if manifest_dest.exists() and manifest_dest.read_text() == manifest_content:
        print("manifest: instance's SKLauncher manifest already up to date")
    else:
        print(f"manifest: writing {manifest_dest}")
        changed = True
        if apply:
            manifest_dest.parent.mkdir(parents=True, exist_ok=True)
            manifest_dest.write_text(manifest_content)

    pack = json.loads(PACK_JSON_PATH.read_text())
    instances = json.loads(instances_json.read_text())
    instance_info = next((i for i in instances["instances"] if i["id"] == instance_id), None)
    if instance_info is None:
        raise SystemExit(
            f"Error: instance '{instance_id}' not found in {instances_json}.\n\n"
            "pull_instance.py only ever populates/resyncs an EXISTING SKLauncher\n"
            "instance -- it won't guess at instances.json's full schema to create\n"
            "one from scratch. Create the instance once via SKLauncher's "
            '"New Instance"\nUI (any loader/version is fine, this script will '
            "overwrite minecraftVersion/loaderVersion), then re-run this script."
        )

    if (
        instance_info.get("minecraftVersion") == pack["minecraftVersion"]
        and instance_info.get("loaderVersion") == pack["loaderVersion"]
    ):
        print(f"instances.json: already up to date ({pack})")
    else:
        print(f"instances.json: updating version fields to {pack}")
        changed = True
        if apply:
            instance_info["minecraftVersion"] = pack["minecraftVersion"]
            instance_info["loaderVersion"] = pack["loaderVersion"]
            instances_json.write_text(json.dumps(instances, indent=2) + "\n")

    return changed


def main():
    load_dotenv()
    args = parse_args()

    instance_dir = resolve_instance_dir(args.instance_dir, args.instance_name)
    if not instance_dir.is_dir():
        raise SystemExit(
            f"Error: SKLauncher instance directory not found: {instance_dir}\n\n"
            'Create the instance once via SKLauncher\'s "New Instance" UI first,\n'
            "then point this script at it via:\n"
            '  SK_INSTANCE_DIR="/path/to/sklauncher/instances/creark" uv run pull_instance.py\n'
            "or:\n"
            '  uv run pull_instance.py --instance-dir "/path/to/sklauncher/instances/creark"'
        )

    instance_id = instance_dir.name
    sk_root = instance_dir.parent.parent
    manifest_dest = sk_root / "manifests" / f"{instance_id}.json"
    instances_json = sk_root / "instances.json"

    if not instances_json.is_file():
        raise SystemExit(f"Error: instances.json not found: {instances_json}")
    if not MANIFEST_PATH.is_file():
        raise SystemExit(f"Error: repo manifest not found: {MANIFEST_PATH}")
    if not PACK_JSON_PATH.is_file():
        raise SystemExit(f"Error: repo pack.json not found: {PACK_JSON_PATH}")

    mod_entries = load_mod_entries(MANIFEST_PATH)

    def run(apply: bool) -> tuple[int, bool]:
        """Runs every sync step in the given mode. Returns (removed mod jar
        count, whether anything changed) -- used to decide the confirmation
        prompt and the final summary."""
        mods_added, mods_updated, removed = sync_mods(instance_dir, mod_entries, apply)
        changed = bool(mods_added or mods_updated or removed)

        if not args.skip_config:
            cfg_added, cfg_updated, cfg_removed = sync_config(instance_dir, apply)
            changed = changed or bool(cfg_added or cfg_updated or cfg_removed)
        else:
            print("config/: --skip-config passed, skipping")

        changed = sync_servers_dat(instance_dir, apply) or changed
        changed = (
            sync_manifest_and_pack_json(instance_id, manifest_dest, instances_json, apply)
            or changed
        )
        return removed, changed

    print(f"Target instance: {instance_dir}\n")

    if args.yes:
        run(True)
        print("\nDone.")
        return

    print("Previewing changes (dry run)...\n")
    removed, changed = run(False)

    if not changed:
        print("\nAlready up to date -- nothing to do.")
        return

    prompt = "\nApply these changes?"
    if removed:
        prompt += f" This will DELETE {removed} mod jar(s) not in the manifest."
    answer = input(prompt + " [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted -- no changes made.")
        return

    print()
    run(True)
    print("\nDone.")


if __name__ == "__main__":
    main()
