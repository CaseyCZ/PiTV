#!/usr/bin/env bash
set -euo pipefail
# Read-only end-to-end readiness report. It does not modify Waydroid.
STAGE="${1:?prepared payload required}"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/verify-staged-codec2-payload.py" "$STAGE"
python3 "$HERE/enforce-codec2-payload-scope.py" "$STAGE"
python3 "$HERE/check-codec2-payload-size.py" "$STAGE"
python3 "$HERE/verify-codec2-metadata.py" "$STAGE"
python3 "$HERE/codec2-payload-readiness.py" "$STAGE"
python3 "$HERE/check-codec2-service-metadata.py" "$STAGE"
TARGET_REPORT="$(mktemp)"
trap 'rm -f "$TARGET_REPORT"' EXIT
"$HERE/probe-waydroid-codec2-target.sh" >"$TARGET_REPORT"
cat "$TARGET_REPORT"
python3 "$HERE/evaluate-codec2-target.py" "$TARGET_REPORT"
echo "CODEC2_READY_TO_INSTALL=1"
