#!/usr/bin/env bash
# Builds a full .mrpack from the SKLauncher "creark" instance, including
# config/server settings as overrides. See build_mrpack.py for the details.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/build_mrpack.py"
