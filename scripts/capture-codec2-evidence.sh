#!/usr/bin/env bash
set -euo pipefail
# Capture reproducible post-install evidence without modifying Android.
OUT="${1:-/var/lib/pitv/codec2-experiment/evidence/$(date -u +%Y%m%dT%H%M%SZ)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
"$HERE/probe-waydroid-codec2-target.sh" "$OUT/target.env" >/dev/null
"$HERE/verify-codec2-runtime.sh" | tee "$OUT/runtime.txt"
"$HERE/accept-codec2-overlay-runtime.sh" | tee "$OUT/acceptance.txt"
if [ -f /var/lib/pitv/codec2-experiment/active-vendor.sha256 ]; then
  cp /var/lib/pitv/codec2-experiment/active-vendor.sha256 "$OUT/"
fi
uname -a >"$OUT/uname.txt"
printf '%s\n' "$OUT" > /var/lib/pitv/codec2-experiment/last-evidence
echo "EVIDENCE=$OUT"
