#!/usr/bin/env bash
set -euo pipefail
# Experimental minimal Codec2 overlay installer for PiTV/RPi4 Waydroid.
# It patches a COPY of the current vendor.img, validates Android boot/codecs,
# and automatically restores the original image on any failure.
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
STAGE="${1:?verified staged payload required}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/verify-staged-codec2-payload.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/check-codec2-payload-contract.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/enforce-codec2-payload-scope.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/inventory-codec2-payload.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/codec2-payload-readiness.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/make-codec2-rollback-manifest.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/verify-codec2-metadata.py" "$STAGE" >/dev/null
command -v waydroid >/dev/null
command -v mount >/dev/null
command -v umount >/dev/null
ARCH="$(dpkg --print-architecture 2>/dev/null || true)"
[ "$ARCH" = arm64 ] || { echo "ARM64 only" >&2; exit 3; }
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
case "$MODEL" in *"Raspberry Pi 4"*) ;; *) echo "Raspberry Pi 4 only" >&2; exit 3;; esac
compgen -G '/dev/video*' >/dev/null || { echo "missing /dev/video*" >&2; exit 4; }
compgen -G '/dev/media*' >/dev/null || { echo "missing /dev/media*" >&2; exit 4; }

STATE=/var/lib/pitv/codec2-experiment
EXTRA=/etc/waydroid-extra/images
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$STATE/backups/$STAMP"
TMP="$(mktemp -d /tmp/pitv-codec2-overlay.XXXXXX)"
MNT="$TMP/vendor"
SYS_MNT="$TMP/system-ro"
CUR_VENDOR_MNT="$TMP/vendor-ro"
RESTORE=0
mounted=0
preflight_mounted=0

find_image(){
  for p in "$EXTRA/$1" "/var/lib/waydroid/images/$1" "/usr/share/waydroid-extra/images/$1"; do
    [ -s "$p" ] && { readlink -f "$p"; return; }
  done
  return 1
}
SYSTEM="$(find_image system.img || true)"; VENDOR="$(find_image vendor.img || true)"
[ -n "$SYSTEM" ] && [ -n "$VENDOR" ] || { echo "Waydroid images not found" >&2; exit 5; }
mkdir -p "$BACKUP" "$MNT" "$SYS_MNT" "$CUR_VENDOR_MNT" "$EXTRA"
cp --reflink=auto --sparse=always "$SYSTEM" "$BACKUP/system.img"
cp --reflink=auto --sparse=always "$VENDOR" "$BACKUP/vendor.img"
sha256sum "$BACKUP/system.img" "$BACKUP/vendor.img" >"$BACKUP/SHA256SUMS"
cp --reflink=auto --sparse=always "$VENDOR" "$TMP/vendor.img"

stop_android(){
  systemctl stop pitv-android-warm.service >/dev/null 2>&1 || true
  timeout 20s waydroid session stop >/dev/null 2>&1 || true
  timeout 20s waydroid container stop >/dev/null 2>&1 || true
  systemctl stop waydroid-container.service >/dev/null 2>&1 || true
}
restore(){
  [ "$mounted" -eq 0 ] || { umount "$MNT" >/dev/null 2>&1 || true; mounted=0; }
  stop_android
  cp --reflink=auto --sparse=always "$BACKUP/system.img" "$EXTRA/system.img"
  cp --reflink=auto --sparse=always "$BACKUP/vendor.img" "$EXTRA/vendor.img"
  waydroid init -f >/dev/null 2>&1 || true
  systemctl start waydroid-container.service >/dev/null 2>&1 || true
  systemctl start pitv-android-warm.service >/dev/null 2>&1 || true
}
cleanup(){
  rc=$?
  [ "$mounted" -eq 0 ] || { umount "$MNT" >/dev/null 2>&1 || true; mounted=0; }
  if [ "$preflight_mounted" -eq 1 ]; then
    umount "$CUR_VENDOR_MNT" >/dev/null 2>&1 || true
    umount "$SYS_MNT" >/dev/null 2>&1 || true
    preflight_mounted=0
  fi
  if [ "$RESTORE" -eq 1 ]; then restore; fi
  rm -rf "$TMP"
  exit "$rc"
}
trap cleanup EXIT INT TERM
fail(){ echo "Codec2 overlay failed: $*" >&2; restore; RESTORE=0; exit 20; }

# Prove that every candidate ELF dependency is already in the payload or in
# the currently working Android system/vendor before activating anything.
mount -o loop,ro "$SYSTEM" "$SYS_MNT"
mount -o loop,ro "$VENDOR" "$CUR_VENDOR_MNT"
preflight_mounted=1
python3 "$SCRIPT_DIR/preflight-codec2-overlay.py" "$STAGE" "$CUR_VENDOR_MNT" >/dev/null
python3 "$SCRIPT_DIR/plan-codec2-backup.py" "$STAGE" >/dev/null
python3 "$SCRIPT_DIR/audit-codec2-payload-deps.py" "$STAGE" "$SYS_MNT" "$CUR_VENDOR_MNT" || {
  echo "ELF dependency closure is incompatible with current Waydroid" >&2
  exit 10
}
umount "$CUR_VENDOR_MNT"; umount "$SYS_MNT"; preflight_mounted=0

stop_android
mount -o loop,rw "$TMP/vendor.img" "$MNT"; mounted=1
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  case "$rel" in vendor/*) dstrel="${rel#vendor/}";; *) dstrel="$rel";; esac
  src="$STAGE/$rel"; dst="$MNT/$dstrel"
  [ -f "$src" ] || fail "payload file disappeared: $rel"
  mkdir -p "$(dirname "$dst")"; cp -a "$src" "$dst"
done <"$STAGE/PITV-CODEC2-PAYLOAD.txt"
# Android 13 V4L2 Codec2 properties required by the selected service.
# Replace existing keys rather than accumulating duplicates across experiments.
BUILD_PROP="$MNT/build.prop"
[ -f "$BUILD_PROP" ] || BUILD_PROP="$MNT/default.prop"
[ -f "$BUILD_PROP" ] || fail "vendor build.prop/default.prop missing"
for kv in \
  'debug.stagefright.c2-poolmask=0x350000' \
  'persist.v4l2_codec2.rank.decoder=128' \
  'ro.vendor.v4l2_codec2.decode_concurrent_instances=4'
do
  key="${kv%%=*}"
  sed -i "/^${key//./\\.}=/d" "$BUILD_PROP"
  printf '%s\n' "$kv" >>"$BUILD_PROP"
done
sync
umount "$MNT"; mounted=0
cp --reflink=auto --sparse=always "$BACKUP/system.img" "$EXTRA/system.img"
cp --reflink=auto --sparse=always "$TMP/vendor.img" "$EXTRA/vendor.img"
RESTORE=1

if [ -x /usr/local/libexec/pitv-waydroid-device-patch ]; then
  PITV_WAYDROID_PATCH_STRICT=1 /usr/local/libexec/pitv-waydroid-device-patch || fail "media-node passthrough patch"
fi
waydroid init -f || fail "waydroid init"
systemctl start waydroid-container.service || fail "container start"
systemctl start pitv-android-warm.service >/dev/null 2>&1 || true

ready=0
for _ in $(seq 1 240); do
  boot="$(printf 'getprop sys.boot_completed\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
  [ "$boot" = 1 ] && { ready=1; break; }
  sleep .5
done
[ "$ready" -eq 1 ] || fail "Android boot timeout"
release="$(printf 'getprop ro.build.version.release\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
[ "$release" = 13 ] || fail "expected Android 13, got $release"
instances="$(printf 'getprop ro.vendor.v4l2_codec2.decode_concurrent_instances\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
[ "$instances" = 4 ] || fail "V4L2 Codec2 vendor properties not active"
media="$(printf 'ls -1 /dev/media* 2>/dev/null\n' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$media" | grep -q '/dev/media' || fail "/dev/media not visible in Android"
dump="$(printf 'dumpsys media.codec\n' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$dump" | grep -q 'c2.v4l2.avc.decoder' || fail "AVC Codec2 not registered"
printf '%s\n' "$dump" | grep -q 'c2.ffmpeg.hevc.decoder' || fail "HEVC Codec2 not registered"
procs="$(printf "cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\000' '\\n'\n" | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$procs" | grep -Eiq 'media\.c2.*v4l2|v4l2.*media\.c2' || fail "AVC service missing"
printf '%s\n' "$procs" | grep -Eiq 'media\.c2.*ffmpeg|ffmpeg.*media\.c2' || fail "HEVC service missing"

RESTORE=0
sha256sum "$EXTRA/vendor.img" >"$STATE/active-vendor.sha256"
printf '%s\n' "$BACKUP" >"$STATE/last-backup"
printf '%s\n' "$STAGE" >"$STATE/active-stage"
echo "Codec2 overlay installed and validated"
