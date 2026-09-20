#!/usr/bin/env bash
set -euo pipefail
# Prepare a rollback-safe staging area only. This does NOT mount, modify, or
# restart Waydroid. A later installer must consume this staged package.
PAYLOAD="${1:?payload directory required}"
STATE="${2:-/var/lib/pitv/codec2-experiment}"
test -f "$PAYLOAD/PITV-CODEC2-PAYLOAD.txt"
test -f "$PAYLOAD/PITV-CODEC2-SHA256.json"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/verify-staged-codec2-payload.py" "$PAYLOAD" >/dev/null
python3 "$HERE/enforce-codec2-payload-scope.py" "$PAYLOAD" >/dev/null
python3 "$HERE/check-codec2-manifest-closure.py" "$PAYLOAD" >/dev/null
python3 "$HERE/check-codec2-payload-size.py" "$PAYLOAD" >/dev/null
python3 "$HERE/codec2-payload-readiness.py" "$PAYLOAD" >/dev/null
python3 "$HERE/verify-codec2-metadata.py" "$PAYLOAD" >/dev/null
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$STATE/staged/$stamp"
mkdir -p "$dest"
cp -a "$PAYLOAD/." "$dest/"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/verify-staged-codec2-payload.py" "$dest" >/dev/null
python3 "$HERE/make-codec2-rollback-manifest.py" "$dest" >/dev/null
python3 "$HERE/verify-codec2-metadata.py" "$dest" >/dev/null
python3 "$HERE/check-codec2-manifest-closure.py" "$dest" >/dev/null
printf '%s\n' "$dest" > "$STATE/current-stage"
echo "STAGED=$dest"
