#!/usr/bin/env bash
set -euo pipefail
# Prepare a rollback-safe staging area only. This does NOT mount, modify, or
# restart Waydroid. A later installer must consume this staged package.
PAYLOAD="${1:?payload directory required}"
STATE="${2:-/var/lib/pitv/codec2-experiment}"
test -f "$PAYLOAD/PITV-CODEC2-PAYLOAD.txt"
test -f "$PAYLOAD/PITV-CODEC2-SHA256.json"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$STATE/staged/$stamp"
mkdir -p "$dest"
cp -a "$PAYLOAD/." "$dest/"
printf '%s\n' "$dest" > "$STATE/current-stage"
echo "STAGED=$dest"
