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
python3 "$HERE/check-codec2-xml-contract.py"
rm -rf "$OUT"
python3 "$HERE/probe-codec2-prebuilt.py" "$DONOR" "$@"
python3 "$HERE/collect-codec2-prebuilt.py" "$DONOR" "$OUT" "$@"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$REPO"
bash "$HERE/add-pitv-codec2-config-to-payload.sh" "$OUT"
python3 "$HERE/validate-codec2-payload.py" "$OUT"
python3 "$HERE/check-codec2-payload-contract.py" "$OUT"
python3 "$HERE/enforce-codec2-payload-scope.py" "$OUT"
python3 "$HERE/check-codec2-manifest-closure.py" "$OUT"
python3 "$HERE/check-codec2-payload-size.py" "$OUT"
python3 "$HERE/inventory-codec2-payload.py" "$OUT"
python3 "$HERE/make-codec2-rollback-manifest.py" "$OUT"
python3 "$HERE/verify-codec2-metadata.py" "$OUT"
python3 "$HERE/codec2-payload-readiness.py" "$OUT"
python3 "$HERE/verify-staged-codec2-payload.py" "$OUT"
echo "Codec2 payload ready: $OUT"
