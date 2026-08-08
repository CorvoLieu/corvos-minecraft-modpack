#!/usr/bin/env python3
"""
Packages ONLY the mod jars into a distributable zip, from the repo's synced
modpack data (downloading Modrinth-sourced jars, copying the rest from
local-mods/). For quick mod-only updates (e.g. dropping straight into the
docker server's ./mods mount). Run export_mrpack.py instead if you also
need config/server settings bundled.
"""

from build_mrpack import main

if __name__ == "__main__":
    main(["--mods-zip-only"])
