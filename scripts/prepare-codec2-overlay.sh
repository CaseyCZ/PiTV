#!/usr/bin/env bash
set -euo pipefail
# End-to-end preparation from an extracted Android 13 donor tree.
# Does not install anything into Waydroid.
DONOR="${1:?donor tree required}"
OUT="${2:?output directory required}"
shift 2
[ "$#" -gt 0 ] || { echo "at least one service/root file is required" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
rm -rf "$OUT"
python3 "$HERE/probe-codec2-prebuilt.py" "$DONOR" "$@"
python3 "$HERE/collect-codec2-prebuilt.py" "$DONOR" "$OUT" "$@"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$REPO"
python3 "$HERE/validate-codec2-payload.py" "$OUT"
python3 "$HERE/verify-staged-codec2-payload.py" "$OUT"
echo "Codec2 payload ready: $OUT"
