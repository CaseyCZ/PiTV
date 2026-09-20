#!/usr/bin/env bash
set -euo pipefail
# Extract only a donor vendor filesystem from a user-supplied Android image.
# The donor is mounted read-only. Nothing is downloaded or redistributed.
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
IMAGE="${1:?Android image/vendor.img required}"
OUT="${2:?output directory required}"
[ -f "$IMAGE" ] || { echo "image not found" >&2; exit 2; }
TMP="$(mktemp -d /tmp/pitv-codec2-donor.XXXXXX)"
MNT="$TMP/mnt"; mkdir -p "$MNT"
loop=""; mounted=0
cleanup(){
  rc=$?
  [ "$mounted" -eq 0 ] || umount "$MNT" >/dev/null 2>&1 || true
  [ -z "$loop" ] || losetup -d "$loop" >/dev/null 2>&1 || true
  rm -rf "$TMP"
  exit "$rc"
}
trap cleanup EXIT INT TERM
source_dev=""
if file -b "$IMAGE" 2>/dev/null | grep -qi 'ext[234] filesystem'; then
  loop="$(losetup --find --show --read-only "$IMAGE")"; source_dev="$loop"
else
  loop="$(losetup --find --show --read-only --partscan "$IMAGE")"
  udevadm settle 2>/dev/null || true
  while read -r dev partlabel label; do
    case "${partlabel,,}:${label,,}" in
      *vendor*) source_dev="$dev"; break;;
    esac
  done < <(lsblk -nrpo NAME,PARTLABEL,LABEL "$loop")
  [ -n "$source_dev" ] || { echo "vendor partition not found in donor image" >&2; exit 3; }
fi
mount -o ro "$source_dev" "$MNT"; mounted=1
test -d "$MNT/etc" || { echo "selected filesystem is not Android vendor" >&2; exit 4; }
rm -rf "$OUT"; mkdir -p "$OUT"
cp -a "$MNT/." "$OUT/"
echo "DONOR_VENDOR=$OUT"
