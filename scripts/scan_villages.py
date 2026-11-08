#!/usr/bin/env python3
"""
Finds the villages within --radius blocks of x=0, z=0 on a running server and
stores them in the world for the season-onboarding datapack (see the
creativeworld:onboarding functions in local-datapacks/). New players are then
placed above a random one of these villages on first join.

How it works: from a grid of points covering the radius, it runs
`execute positioned <x> 64 <z> run locate structure #minecraft:village`
through the itzg container's built-in rcon-cli, parses the coordinates each
locate reports, and keeps the unique villages inside the radius. It then
replaces `storage creativeworld:onboarding villages` with that list. The
storage is saved with the world, so this runs once per season (after the new
world is generated, ideally after pre-generating it with Chunky) -- no rebuild
or redeploy needed. Re-running it replaces the list.

Usage:
  uv run python scripts/scan_villages.py                       # prod container
  uv run python scripts/scan_villages.py --container minecraft-server-s3
  uv run python scripts/scan_villages.py --dry-run             # scan, don't write
"""

import argparse
import math
import re
import subprocess
import sys

LOCATE_RE = re.compile(r"\[(-?\d+), ~, (-?\d+)\]")


def rcon(container: str, command: str) -> str:
    result = subprocess.run(
        ["docker", "exec", container, "rcon-cli", command],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise SystemExit(f"rcon-cli failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def grid(radius: int, step: int):
    n = math.ceil(radius / step)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, z = i * step, j * step
            if math.hypot(x, z) <= radius + step:
                yield x, z


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--container", default="minecraft-server", help="server container name (default: minecraft-server)")
    parser.add_argument("--radius", type=int, default=1500, help="keep villages within this many blocks of 0,0 (default: 1500)")
    parser.add_argument("--step", type=int, default=400, help="grid spacing between locate points (default: 400)")
    parser.add_argument("--dry-run", action="store_true", help="only print the villages found; don't write them to the world")
    args = parser.parse_args()

    points = list(grid(args.radius, args.step))
    villages: set[tuple[int, int]] = set()
    print(f"Locating villages from {len(points)} points (radius {args.radius}, step {args.step})...")
    for n, (x, z) in enumerate(points, 1):
        out = rcon(args.container, f"execute positioned {x} 64 {z} run locate structure #minecraft:village")
        m = LOCATE_RE.search(out)
        if m:
            vx, vz = int(m.group(1)), int(m.group(2))
            if math.hypot(vx, vz) <= args.radius:
                villages.add((vx, vz))
        print(f"  [{n}/{len(points)}] from {x},{z}: {out[:90]}")

    found = sorted(villages, key=lambda v: math.hypot(*v))
    print(f"\nFound {len(found)} unique villages within {args.radius} blocks:")
    for vx, vz in found:
        print(f"  {vx}, {vz}  ({round(math.hypot(vx, vz))} blocks from 0,0)")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    if not found:
        print("\nNo villages found -- leaving the world's list untouched.", file=sys.stderr)
        sys.exit(1)

    rcon(args.container, "data modify storage creativeworld:onboarding villages set value []")
    for vx, vz in found:
        rcon(args.container, f"data modify storage creativeworld:onboarding villages append value {{x:{vx},z:{vz}}}")
    print("\n" + rcon(args.container, "data get storage creativeworld:onboarding villages")[:300])
    # Command storage only reaches disk on a world save; save now so a crash or
    # hard stop before the next autosave doesn't lose the list.
    print(rcon(args.container, "save-all flush"))
    print(f"Wrote {len(found)} villages to storage creativeworld:onboarding villages.")


if __name__ == "__main__":
    main()
