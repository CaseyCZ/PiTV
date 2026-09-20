#!/usr/bin/env bash
set -euo pipefail

# Build a LineageOS 20 / Android 13 Waydroid ARM64 vendor image with the
# Raspberry Pi V4L2 Codec2 decoder enabled.
#
# Usage:
#   scripts/build-waydroid-rpi4-v4l2.sh /path/to/android-work
#
# The Android source tree is intentionally kept outside the PiTV repository.
# A full Lineage/Waydroid checkout is very large.

PITV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANDROID_ROOT="${1:-${PITV_WAYDROID_ANDROID_ROOT:-$HOME/pitv-waydroid-lineage20}}"
JOBS="${PITV_ANDROID_JOBS:-$(nproc --all)}"
DIST="$PITV_ROOT/dist/waydroid-rpi4-v4l2"
WAYDROID_BRANCH="lineage-20"
LINEAGE_BRANCH="lineage-20.0"
V4L2_REPO="https://github.com/lineage-rpi/android_external_v4l2_codec2.git"
V4L2_BRANCH="lineage-20.0"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing build dependency: $1" >&2
    exit 2
  }
}

for cmd in repo git curl python3 make sha256sum xz; do
  need "$cmd"
done

mkdir -p "$ANDROID_ROOT"
cd "$ANDROID_ROOT"

if [ ! -d .repo ]; then
  echo "Initializing LineageOS $LINEAGE_BRANCH source tree..."
  repo init -u https://github.com/LineageOS/android.git -b "$LINEAGE_BRANCH" --git-lfs
  repo sync build/make -j"$JOBS"

  echo "Adding Waydroid $WAYDROID_BRANCH manifests..."
  curl --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 -fsSL \
    "https://raw.githubusercontent.com/waydroid/android_vendor_waydroid/$WAYDROID_BRANCH/manifest_scripts/generate-manifest.sh" \
    | bash
fi

echo "Resetting reusable Android workspace..."
# Waydroid's patch helper and the PiTV product injection intentionally modify
# repo-managed projects. A self-hosted builder reuses this large checkout, so
# restore every project before sync; otherwise a second build would inherit the
# previous run's device.mk/BoardConfig edits.
repo forall -c 'git reset --hard HEAD >/dev/null 2>&1 || true; git clean -fd >/dev/null 2>&1 || true'

echo "Syncing Android/Waydroid sources..."
repo sync -c -d --force-sync -j"$JOBS"

# shellcheck disable=SC1091
source build/envsetup.sh
apply-waydroid-patches

# Keep the repo-managed worktree, but temporarily detach this one project at
# the Raspberry-Pi-maintained Android 13 implementation. This avoids replacing
# a repo worktree with an unrelated nested .git directory and remains safe for
# the next repo sync --force-sync.
test -e external/v4l2_codec2/.git || {
  echo "Waydroid source tree is missing external/v4l2_codec2" >&2
  exit 3
}
git -C external/v4l2_codec2 fetch --depth 1 "$V4L2_REPO" "$V4L2_BRANCH"
git -C external/v4l2_codec2 checkout --detach FETCH_HEAD
git -C external/v4l2_codec2 clean -fd

rm -rf vendor/pitv/rpi4
mkdir -p vendor/pitv/rpi4
cp -a "$PITV_ROOT/android/waydroid-rpi4/." vendor/pitv/rpi4/

python3 - <<'PY'
from pathlib import Path

device = Path("device/waydroid/waydroid/device.mk")
board = Path("device/waydroid/waydroid/BoardConfig.mk")

src = device.read_text(encoding="utf-8")
old = (
    "$(LOCAL_PATH)/configs/media_codecs.xml:"
    "$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs.xml"
)
new = (
    "vendor/pitv/rpi4/media_codecs.xml:"
    "$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs.xml"
)
if old not in src and new not in src:
    raise SystemExit("Waydroid media_codecs.xml build rule was not found")
if old in src:
    src = src.replace(old, new, 1)

marker = "# PiTV Raspberry Pi 4 V4L2 Codec2"
inherit = (
    "\n"
    + marker
    + "\n$(call inherit-product, vendor/pitv/rpi4/pitv-rpi4-v4l2.mk)\n"
)
if marker not in src:
    src += inherit
device.write_text(src, encoding="utf-8")

src = board.read_text(encoding="utf-8")
sepolicy = "BOARD_VENDOR_SEPOLICY_DIRS += vendor/pitv/rpi4/sepolicy"
if sepolicy not in src:
    src += "\n# PiTV Raspberry Pi 4 V4L2 Codec2 SELinux labels\n" + sepolicy + "\n"
board.write_text(src, encoding="utf-8")
PY

echo "Building Waydroid ARM64 vendor image..."
lunch lineage_waydroid_arm64-userdebug
make vendorimage -j"$JOBS"

OUT="$ANDROID_ROOT/out/target/product/waydroid_arm64"
test -s "$OUT/vendor.img"
test -x "$OUT/vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64"
test -s "$OUT/vendor/etc/seccomp_policy/codec2.vendor.ext.policy"
grep -q 'c2.v4l2.avc.decoder' "$OUT/vendor/etc/media_codecs.xml"

rm -rf "$DIST"
mkdir -p "$DIST"
cp "$OUT/vendor.img" "$DIST/vendor.img"

V4L2_REV="$(git -C external/v4l2_codec2 rev-parse HEAD)"
WAYDROID_DEVICE_REV="$(git -C device/waydroid/waydroid rev-parse HEAD)"
{
  echo "PITV_WAYDROID_IMAGE_FORMAT=1"
  echo "ANDROID_RELEASE=13"
  echo "LINEAGE_BRANCH=$LINEAGE_BRANCH"
  echo "WAYDROID_BRANCH=$WAYDROID_BRANCH"
  echo "WAYDROID_DEVICE_REV=$WAYDROID_DEVICE_REV"
  echo "V4L2_CODEC2_REV=$V4L2_REV"
  echo "TARGET=lineage_waydroid_arm64-userdebug"
  echo "HW_DECODER=c2.v4l2.avc.decoder"
} > "$DIST/build-info.env"

(
  cd "$DIST"
  sha256sum vendor.img build-info.env > SHA256SUMS
  xz -T0 -9 -f -k vendor.img
  sha256sum vendor.img.xz >> SHA256SUMS
)

echo
echo "PiTV RPi4 V4L2 Waydroid vendor image built:"
echo "  $DIST/vendor.img"
echo "  $DIST/vendor.img.xz"
echo
cat "$DIST/build-info.env"
