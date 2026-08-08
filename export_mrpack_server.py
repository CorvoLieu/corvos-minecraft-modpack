#!/usr/bin/env python3
"""
Builds a server-only .mrpack from the repo's synced modpack data.
Same as export_mrpack.py but drops client-only mods listed in
server-excludes.txt (e.g. freecam) so it's safe to run on the dedicated server.
"""

from pathlib import Path

from build_mrpack import main

SCRIPT_DIR = Path(__file__).resolve().parent

if __name__ == "__main__":
    main(
        [
            "--pack-name",
            "Creark-Server",
            "--exclude-file",
            str(SCRIPT_DIR / "server-excludes.txt"),
        ]
    )
