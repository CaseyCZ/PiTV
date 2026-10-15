#!/usr/bin/env bash
set -euo pipefail
# Experimental HEVC-only installer for the FFmpeg Codec2 service built by the
# narrow ARM64 workflow. Existing AVC/V4L2 Codec2 files are left untouched.
# The current vendor image is backed up and restored automatically on failure.
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
STAGE="$(readlink -f "${1:?verified HEVC stage required}")"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -d "$STAGE" ] || { echo "HEVC stage missing" >&2; exit 2; }

python3 "$HERE/check-ffmpeg-hevc-runtime-payload.py" "$STAGE" >/dev/null
python3 "$HERE/verify-staged-codec2-payload.py" "$STAGE" >/dev/null
python3 "$HERE/enforce-codec2-payload-scope.py" "$STAGE" >/dev/null
python3 "$HERE/check-codec2-manifest-closure.py" "$STAGE" >/dev/null
python3 "$HERE/check-codec2-payload-size.py" "$STAGE" >/dev/null
python3 "$HERE/verify-codec2-metadata.py" "$STAGE" >/dev/null

command -v waydroid >/dev/null
command -v mount >/dev/null
command -v umount >/dev/null
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in arm64|aarch64) ;; *) echo "ARM64 only" >&2; exit 3;; esac
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
case "$MODEL" in *"Raspberry Pi 4"*) ;; *) echo "Raspberry Pi 4 only" >&2; exit 3;; esac
compgen -G '/dev/video*' >/dev/null || { echo "missing /dev/video*" >&2; exit 4; }
compgen -G '/dev/media*' >/dev/null || { echo "missing /dev/media*" >&2; exit 4; }

STATE=/var/lib/pitv/codec2-experiment
EXTRA=/etc/waydroid-extra/images
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$STATE/backups/hevc-$STAMP"
TMP="$(mktemp -d /tmp/pitv-ffmpeg-hevc-overlay.XXXXXX)"
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
SYSTEM="$(find_image system.img || true)"
VENDOR="$(find_image vendor.img || true)"
[ -n "$SYSTEM" ] && [ -n "$VENDOR" ] || { echo "Waydroid images not found" >&2; exit 5; }
case "$VENDOR" in
  /etc/waydroid-extra/images/vendor.img|/var/lib/waydroid/images/vendor.img) ;;
  *) echo "refusing immutable/unsupported Waydroid vendor image path: $VENDOR" >&2; exit 5;;
esac

need=$(( $(stat -c %s "$SYSTEM") + $(stat -c %s "$VENDOR") * 2 ))
avail=$(df -PB1 "$STATE" 2>/dev/null | awk 'NR==2{print $4}' || true)
[ -n "$avail" ] && [ "$avail" -ge "$need" ] || { echo "insufficient free space for rollback-safe HEVC install" >&2; exit 6; }
mkdir -p "$STATE/backups" "$MNT" "$SYS_MNT" "$CUR_VENDOR_MNT" "$EXTRA"
mkdir "$BACKUP"
cp --reflink=auto --sparse=always "$SYSTEM" "$BACKUP/system.img"
cp --reflink=auto --sparse=always "$VENDOR" "$BACKUP/vendor.img"
sha256sum "$BACKUP/system.img" "$BACKUP/vendor.img" > "$BACKUP/SHA256SUMS"
printf '%s\n' "$VENDOR" > "$BACKUP/vendor.path"
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
  cp --reflink=auto --sparse=always "$BACKUP/vendor.img" "$VENDOR"
  if [ -x /usr/local/libexec/pitv-waydroid-device-patch ]; then
    /usr/local/libexec/pitv-waydroid-device-patch --remove >/dev/null 2>&1 || true
  fi
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
fail(){ echo "FFmpeg HEVC overlay failed: $*" >&2; restore; RESTORE=0; exit 20; }

# Prove the built service/libraries can resolve every DT_NEEDED name from this
# payload or the target Android 13 images before touching vendor.img.
mount -o loop,ro "$SYSTEM" "$SYS_MNT"
mount -o loop,ro "$VENDOR" "$CUR_VENDOR_MNT"
preflight_mounted=1
python3 "$HERE/audit-codec2-payload-deps.py" "$STAGE" "$SYS_MNT" "$CUR_VENDOR_MNT" || {
  echo "HEVC ELF dependency closure is incompatible with current Waydroid" >&2
  exit 10
}
MAIN_XML_RO="$CUR_VENDOR_MNT/etc/media_codecs.xml"
[ -f "$MAIN_XML_RO" ] || { echo "target vendor media_codecs.xml missing" >&2; exit 10; }
umount "$CUR_VENDOR_MNT"
umount "$SYS_MNT"
preflight_mounted=0

stop_android
mount -o loop,rw "$TMP/vendor.img" "$MNT"
mounted=1
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  case "$rel" in vendor/*) dstrel="${rel#vendor/}";; *) fail "unexpected payload path: $rel";; esac
  src="$STAGE/$rel"
  dst="$MNT/$dstrel"
  [ -f "$src" ] || fail "payload file disappeared: $rel"
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
done < "$STAGE/PITV-CODEC2-PAYLOAD.txt"

# Preserve the existing registry and add only the HEVC FFmpeg include.
MAIN_XML="$MNT/etc/media_codecs.xml"
[ -f "$MAIN_XML" ] || fail "vendor media_codecs.xml missing"
python3 - "$MAIN_XML" <<'PY'
import sys, xml.etree.ElementTree as ET
p=sys.argv[1]
tree=ET.parse(p); root=tree.getroot(); href="media_codecs_ffmpeg_c2.xml"
if href not in {x.get("href") for x in root.findall("Include")}:
    root.append(ET.Element("Include", {"href": href}))
tree.write(p, encoding="utf-8", xml_declaration=True)
PY

BUILD_PROP="$MNT/build.prop"
[ -f "$BUILD_PROP" ] || BUILD_PROP="$MNT/default.prop"
[ -f "$BUILD_PROP" ] || fail "vendor build.prop/default.prop missing"
for kv in \
  'debug.stagefright.c2-poolmask=0x350000' \
  'persist.ffmpeg_codec2.v4l2.h265=1'
do
  key="${kv%%=*}"
  sed -i "/^${key//./\\.}=/d" "$BUILD_PROP"
  printf '%s\n' "$kv" >> "$BUILD_PROP"
done

while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  dstrel="${rel#vendor/}"
  src="$STAGE/$rel"
  dst="$MNT/$dstrel"
  [ -f "$dst" ] || fail "installed HEVC file missing: $rel"
  cmp -s "$src" "$dst" || fail "installed HEVC file hash mismatch: $rel"
done < "$STAGE/PITV-CODEC2-PAYLOAD.txt"
sync
umount "$MNT"
mounted=0
cp --reflink=auto --sparse=always "$TMP/vendor.img" "$VENDOR"
RESTORE=1

if [ -x /usr/local/libexec/pitv-waydroid-device-patch ]; then
  PITV_WAYDROID_PATCH_STRICT=1 /usr/local/libexec/pitv-waydroid-device-patch || fail "media-node passthrough patch"
fi
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
ffmpeg_hw="$(printf 'getprop persist.ffmpeg_codec2.v4l2.h265\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
[ "$ffmpeg_hw" = 1 ] || fail "FFmpeg HEVC V4L2 Request property not active"
pool="$(printf 'getprop debug.stagefright.c2-poolmask\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
[ "$pool" = 0x350000 ] || fail "Codec2 poolmask property not active"
video="$(printf 'ls -1 /dev/video* 2>/dev/null\n' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$video" | grep -q '/dev/video' || fail "/dev/video not visible in Android"
media="$(printf 'ls -1 /dev/media* 2>/dev/null\n' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$media" | grep -q '/dev/media' || fail "/dev/media not visible in Android"
dump="$(printf 'dumpsys media.codec\n' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$dump" | grep -q 'c2.ffmpeg.hevc.decoder' || fail "HEVC Codec2 not registered"
procs="$(printf "cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\000' '\\n'\n" | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$procs" | grep -Eiq 'media\.c2.*ffmpeg|ffmpeg.*media\.c2' || fail "HEVC FFmpeg service missing"

RESTORE=0
mkdir -p "$STATE"
sha256sum "$VENDOR" > "$STATE/active-vendor.sha256"
printf '%s\n' "$VENDOR" > "$STATE/active-vendor-path"
printf '%s\n' "$BACKUP" > "$STATE/last-backup"
printf '%s\n' "$STAGE" > "$STATE/active-stage"
echo "FFMPEG_HEVC_OVERLAY_INSTALLED=1"
echo "FFMPEG_HEVC_CODEC_REGISTERED=1"
echo "HEVC service is installed and registered; hardware rpivid/V4L2 Request decode still requires playback evidence."
