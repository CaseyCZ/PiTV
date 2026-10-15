#!/usr/bin/env bash
set -euo pipefail
# Read-only readiness for a built HEVC-only overlay. Requires root only so it
# can mount current Waydroid images read-only and prove DT_NEEDED closure.
[ "$(id -u)" -eq 0 ] || { echo "run as root for read-only image preflight" >&2; exit 2; }
STAGE="$(readlink -f "${1:?staged HEVC payload required}")"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -d "$STAGE" ] || { echo "staged HEVC payload missing" >&2; exit 2; }

python3 "$HERE/check-ffmpeg-hevc-runtime-payload.py" "$STAGE"
python3 "$HERE/verify-staged-codec2-payload.py" "$STAGE"
python3 "$HERE/enforce-codec2-payload-scope.py" "$STAGE"
python3 "$HERE/check-codec2-manifest-closure.py" "$STAGE"
python3 "$HERE/check-codec2-payload-size.py" "$STAGE"
python3 "$HERE/verify-codec2-metadata.py" "$STAGE"

TARGET_REPORT="$(mktemp)"
TMP="$(mktemp -d /tmp/pitv-hevc-readiness.XXXXXX)"
SYS_MNT="$TMP/system"
VENDOR_MNT="$TMP/vendor"
mounted=0
cleanup(){
  if [ "$mounted" -eq 1 ]; then
    umount "$VENDOR_MNT" >/dev/null 2>&1 || true
    umount "$SYS_MNT" >/dev/null 2>&1 || true
  fi
  rm -f "$TARGET_REPORT"
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM
mkdir -p "$SYS_MNT" "$VENDOR_MNT"

"$HERE/probe-waydroid-codec2-target.sh" "$TARGET_REPORT" >/dev/null
cat "$TARGET_REPORT"
python3 "$HERE/evaluate-codec2-target.py" "$TARGET_REPORT"

find_image(){
  for p in "/etc/waydroid-extra/images/$1" "/var/lib/waydroid/images/$1" "/usr/share/waydroid-extra/images/$1"; do
    [ -s "$p" ] && { readlink -f "$p"; return; }
  done
  return 1
}
SYSTEM="$(find_image system.img || true)"
VENDOR="$(find_image vendor.img || true)"
[ -n "$SYSTEM" ] && [ -n "$VENDOR" ] || { echo "Waydroid system/vendor images not found" >&2; exit 5; }

mount -o loop,ro "$SYSTEM" "$SYS_MNT"
mount -o loop,ro "$VENDOR" "$VENDOR_MNT"
mounted=1
python3 "$HERE/audit-codec2-payload-deps.py" "$STAGE" "$SYS_MNT" "$VENDOR_MNT"

MAIN_XML="$VENDOR_MNT/etc/media_codecs.xml"
[ -f "$MAIN_XML" ] || { echo "target vendor media_codecs.xml missing" >&2; exit 6; }
BUILD_PROP="$VENDOR_MNT/build.prop"
[ -f "$BUILD_PROP" ] || BUILD_PROP="$VENDOR_MNT/default.prop"
[ -f "$BUILD_PROP" ] || { echo "target vendor build.prop/default.prop missing" >&2; exit 6; }

echo "FFMPEG_HEVC_TARGET_SYSTEM=$SYSTEM"
echo "FFMPEG_HEVC_TARGET_VENDOR=$VENDOR"
echo "FFMPEG_HEVC_DEPENDENCY_CLOSURE=OK"
echo "FFMPEG_HEVC_READY_TO_INSTALL=1"
