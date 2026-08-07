#!/usr/bin/env bash
# Builds a server-only .mrpack from the SKLauncher "creark" instance.
# Same as export-mrpack.sh but drops client-only mods (currently: freecam)
# so it's safe to run on the dedicated server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/build_mrpack.py" \
  --pack-name Creark-Server \
  --exclude freecam \
  --exclude wakes
