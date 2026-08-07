#!/usr/bin/env bash
# Packages ONLY mods/ from the SKLauncher "creark" instance into a distributable zip.
# For quick mod-only updates (e.g. dropping straight into the docker server's ./mods mount).
# Run export-mrpack.sh instead if you also need config/server settings bundled.
set -euo pipefail

SOURCE_DIR="/Users/haolieu/Library/Application Support/sklauncher/instances/creark"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/exports"
# TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_ZIP="$OUTPUT_DIR/Creark Mods-ONLY.zip"

if [ ! -d "$SOURCE_DIR/mods" ]; then
  echo "Error: expected mods/ under $SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

cd "$SOURCE_DIR"
zip -qr -X "$OUTPUT_ZIP" mods -x "*.DS_Store"

echo "Exported: $OUTPUT_ZIP"
echo "$(unzip -l "$OUTPUT_ZIP" | tail -1)"
