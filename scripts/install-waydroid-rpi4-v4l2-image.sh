#!/usr/bin/env bash
set -euo pipefail

# Install a locally built PiTV Raspberry Pi 4 V4L2 Waydroid vendor image while
# preserving the currently working Waydroid system image.
#
# Usage:
#   sudo scripts/install-waydroid-rpi4-v4l2-image.sh /path/to/vendor.img
#   sudo scripts/install-waydroid-rpi4-v4l2-image.sh /path/to/vendor.img.xz

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo/root." >&2
  exit 2
fi

SOURCE="${1:-}"
if [ -z "$SOURCE" ] || [ ! -f "$SOURCE" ]; then
  echo "Usage: sudo $0 /path/to/vendor.img[.xz]" >&2
  exit 2
fi

if [ "$(dpkg --print-architecture 2>/dev/null || true)" != "arm64" ]; then
  echo "PiTV RPi4 V4L2 Waydroid image is ARM64-only." >&2
  exit 3
fi

MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
case "$MODEL" in
  *"Raspberry Pi 4"*) ;;
  *)
    echo "Refusing RPi4-specific Waydroid vendor on: ${MODEL:-unknown device}" >&2
    exit 3
    ;;
esac

command -v waydroid >/dev/null 2>&1 || {
  echo "Waydroid is not installed." >&2
  exit 4
}
command -v xz >/dev/null 2>&1 || {
  echo "xz is required." >&2
  exit 4
}

STATE="/var/lib/pitv"
BACKUP_ROOT="$STATE/waydroid-image-backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$BACKUP_ROOT/$STAMP"
EXTRA="/etc/waydroid-extra/images"
TMP="$(mktemp -d /tmp/pitv-waydroid-v4l2.XXXXXX)"
RESTORE_NEEDED=0

find_current_image() {
  local name="$1"
  local path
  for path in \
    "$EXTRA/$name" \
    "/var/lib/waydroid/images/$name" \
    "/usr/share/waydroid-extra/images/$name"
  do
    if [ -s "$path" ]; then
      readlink -f "$path"
      return 0
    fi
  done
  return 1
}

CURRENT_SYSTEM="$(find_current_image system.img || true)"
CURRENT_VENDOR="$(find_current_image vendor.img || true)"
if [ -z "$CURRENT_SYSTEM" ] || [ -z "$CURRENT_VENDOR" ]; then
  echo "Could not locate the current Waydroid system/vendor images." >&2
  exit 5
fi

mkdir -p "$BACKUP"
echo "Backing up the currently working Waydroid images to $BACKUP"
cp --reflink=auto --sparse=always "$CURRENT_SYSTEM" "$BACKUP/system.img"
cp --reflink=auto --sparse=always "$CURRENT_VENDOR" "$BACKUP/vendor.img"
sha256sum "$BACKUP/system.img" "$BACKUP/vendor.img" > "$BACKUP/SHA256SUMS"

if [[ "$SOURCE" == *.xz ]]; then
  xz -dc "$SOURCE" > "$TMP/vendor.img"
else
  cp --reflink=auto --sparse=always "$SOURCE" "$TMP/vendor.img"
fi
test -s "$TMP/vendor.img"

# A vendor image should be an ext4 filesystem image. file(1) is useful when
# available, but do not make it a hard dependency.
if command -v file >/dev/null 2>&1; then
  FILE_DESC="$(file -b "$TMP/vendor.img" || true)"
  case "$FILE_DESC" in
    *ext4*|*filesystem*) ;;
    *)
      echo "The supplied file does not look like a vendor filesystem image: $FILE_DESC" >&2
      exit 6
      ;;
  esac
fi

restore_previous() {
  echo "Restoring previous Waydroid images..."
  systemctl stop pitv-android-warm.service >/dev/null 2>&1 || true
  timeout 20s waydroid session stop >/dev/null 2>&1 || true
  timeout 20s waydroid container stop >/dev/null 2>&1 || true
  mkdir -p "$EXTRA"
  cp --reflink=auto --sparse=always "$BACKUP/system.img" "$EXTRA/system.img"
  cp --reflink=auto --sparse=always "$BACKUP/vendor.img" "$EXTRA/vendor.img"
  waydroid init -f
  systemctl start waydroid-container.service
  systemctl start pitv-android-warm.service >/dev/null 2>&1 || true
}

fail_and_restore() {
  local message="$1"
  echo "V4L2 vendor validation failed: $message" >&2
  RESTORE_NEEDED=0
  restore_previous
  echo "Previous Waydroid images restored." >&2
  exit 20
}

cleanup() {
  local rc=$?
  if [ "$RESTORE_NEEDED" -eq 1 ]; then
    echo "V4L2 vendor installation aborted; restoring previous Waydroid images." >&2
    RESTORE_NEEDED=0
    set +e
    restore_previous
    set -e
  fi
  rm -rf "$TMP"
  return "$rc"
}
trap cleanup EXIT

echo "Stopping the persistent Android runtime..."
systemctl stop pitv-android-warm.service >/dev/null 2>&1 || true
timeout 20s waydroid session stop >/dev/null 2>&1 || true
timeout 20s waydroid container stop >/dev/null 2>&1 || true

mkdir -p "$EXTRA"
cp --reflink=auto --sparse=always "$BACKUP/system.img" "$EXTRA/system.img"
cp --reflink=auto --sparse=always "$TMP/vendor.img" "$EXTRA/vendor.img"
sync
RESTORE_NEEDED=1

echo "Re-initializing Waydroid with PiTV RPi4 V4L2 vendor image..."
waydroid init -f || fail_and_restore "waydroid init -f failed"
systemctl start waydroid-container.service \
  || fail_and_restore "waydroid-container.service failed to start"
systemctl start pitv-android-warm.service >/dev/null 2>&1 || true

# The PiTV warm service owns the Waydroid user session. Give it enough time for
# the first Android boot after a vendor image replacement.
ready=0
for _ in $(seq 1 240); do
  status="$(waydroid status 2>/dev/null || true)"
  if printf '%s\n' "$status" | grep -qE '^Session:[[:space:]]+RUNNING'; then
    boot="$(printf '%s\n' 'getprop sys.boot_completed' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
    if [ "$boot" = "1" ]; then
      ready=1
      break
    fi
  fi
  sleep 0.5
done
[ "$ready" -eq 1 ] || fail_and_restore "Android did not reach boot_completed=1"

codec_xml="$(printf '%s\n' 'cat /vendor/etc/media_codecs.xml' | waydroid shell 2>/dev/null || true)"
printf '%s\n' "$codec_xml" | grep -q 'c2.v4l2.avc.decoder' \
  || fail_and_restore "c2.v4l2.avc.decoder is missing from /vendor/etc/media_codecs.xml"

svc="$(printf '%s\n' 'getprop init.svc.android-hardware-media-c2-v4l2-hal-1-0' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
[ "$svc" = "running" ] \
  || fail_and_restore "V4L2 Codec2 HAL service is not running (state: ${svc:-missing})"

RESTORE_NEEDED=0
sha256sum "$EXTRA/vendor.img" > "$STATE/waydroid-rpi4-v4l2-vendor.sha256"
printf '%s\n' "$BACKUP" > "$STATE/waydroid-rpi4-v4l2-last-backup"

echo
echo "PiTV RPi4 V4L2 Waydroid vendor installed successfully."
echo "Codec: c2.v4l2.avc.decoder"
echo "HAL:   $svc"
echo "Backup: $BACKUP"
