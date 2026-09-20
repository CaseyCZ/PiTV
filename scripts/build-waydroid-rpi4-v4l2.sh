#!/usr/bin/env bash
set -euo pipefail

# Build a LineageOS 20 / Android 13 Waydroid ARM64 vendor image with Raspberry
# Pi 4 hardware video decoding:
#   H.264/AVC -> stateful V4L2 Codec2 (bcm2835-codec)
#   HEVC/H.265 -> FFmpeg Codec2 + stateless V4L2 Request API (rpivid)
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
FFMPEG_REPO="https://github.com/raspberry-vanilla/android_external_ffmpeg.git"
FFMPEG_CODEC2_REPO="https://github.com/raspberry-vanilla/android_external_ffmpeg_codec2.git"
LIBUDEV_ZERO_REPO="https://github.com/raspberry-vanilla/android_external_libudev-zero.git"
RPI_ANDROID_BRANCH="android-13.0"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing build dependency: $1" >&2
    exit 2
  }
}

for cmd in repo git curl python3 make sha256sum xz; do
  need "$cmd"
done

checkout_external() {
  local path="$1" url="$2" branch="$3"

  if [ -e "$path/.git" ]; then
    git -C "$path" reset --hard HEAD >/dev/null 2>&1 || true
    git -C "$path" clean -fdx >/dev/null 2>&1 || true
    git -C "$path" fetch --depth 1 "$url" "$branch"
    git -C "$path" checkout --detach FETCH_HEAD
    git -C "$path" clean -fdx
  else
    rm -rf "$path"
    git clone --depth 1 --branch "$branch" "$url" "$path"
  fi
}

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
repo forall -c 'git reset --hard HEAD >/dev/null 2>&1 || true; git clean -fd >/dev/null 2>&1 || true'

echo "Syncing Android/Waydroid sources..."
repo sync -c -d --force-sync -j"$JOBS"

# shellcheck disable=SC1091
source build/envsetup.sh
apply-waydroid-patches

echo "Selecting Raspberry Pi Android 13 media implementations..."
checkout_external external/v4l2_codec2 "$V4L2_REPO" "$V4L2_BRANCH"
checkout_external external/ffmpeg "$FFMPEG_REPO" "$RPI_ANDROID_BRANCH"
checkout_external external/ffmpeg_codec2 "$FFMPEG_CODEC2_REPO" "$RPI_ANDROID_BRANCH"
checkout_external external/libudev-zero "$LIBUDEV_ZERO_REPO" "$RPI_ANDROID_BRANCH"

# Raspberry Pi 4 only has a useful stateful V4L2 hardware path for H.264 in
# this Codec2 implementation. The upstream component store also advertises
# VP8/VP9 unconditionally, which could make Android try non-existent Pi 4 HW
# decoders. Keep the V4L2 store deliberately AVC-only; HEVC is provided by the
# separate FFmpeg/rpivid Request-API path below.
python3 - <<'PYV4L2STORE'
from pathlib import Path

store = Path("external/v4l2_codec2/components/V4L2ComponentStore.cpp")
src = store.read_text(encoding="utf-8")
old = """    std::vector<std::shared_ptr<const C2Component::Traits>> ret;
    ret.push_back(GetTraits(V4L2ComponentName::kH264Encoder));
    ret.push_back(GetTraits(V4L2ComponentName::kH264Decoder));
    ret.push_back(GetTraits(V4L2ComponentName::kH264SecureDecoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP8Encoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP8Decoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP8SecureDecoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP9Encoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP9Decoder));
    ret.push_back(GetTraits(V4L2ComponentName::kVP9SecureDecoder));
    return ret;
"""
new = """    std::vector<std::shared_ptr<const C2Component::Traits>> ret;
    // PiTV/RPi4: advertise only the stateful H.264 decoder. VP8/VP9 are not
    // hardware-decoded by the Pi 4 through this Codec2 backend, and HEVC uses
    // the separate stateless FFmpeg/rpivid Request API service.
    ret.push_back(GetTraits(V4L2ComponentName::kH264Decoder));
    return ret;
"""
if old not in src:
    raise SystemExit("Unexpected V4L2ComponentStore::listComponents layout")
store.write_text(src.replace(old, new, 1), encoding="utf-8")
PYV4L2STORE

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

marker = "# PiTV Raspberry Pi 4 hardware video decode"
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
vendor_prop = "TARGET_VENDOR_PROP += vendor/pitv/rpi4/vendor.prop"
if sepolicy not in src:
    src += "\n# PiTV Raspberry Pi 4 media HAL SELinux labels\n" + sepolicy + "\n"
if vendor_prop not in src:
    src += "\n# PiTV Raspberry Pi 4 hardware media properties\n" + vendor_prop + "\n"
board.write_text(src, encoding="utf-8")
PY

echo "Building Waydroid ARM64 vendor image..."
lunch lineage_waydroid_arm64-userdebug
make vendorimage -j"$JOBS"

OUT="$ANDROID_ROOT/out/target/product/waydroid_arm64"
test -s "$OUT/vendor.img"
test -x "$OUT/vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64"
test -x "$OUT/vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg"
test -s "$OUT/vendor/etc/seccomp_policy/codec2.vendor.ext.policy"
grep -q 'c2.v4l2.avc.decoder' "$OUT/vendor/etc/media_codecs.xml"
grep -q 'c2.ffmpeg.hevc.decoder' "$OUT/vendor/etc/media_codecs.xml"
! grep -q 'c2.v4l2.vp9.decoder' "$OUT/vendor/etc/media_codecs.xml"

rm -rf "$DIST"
mkdir -p "$DIST"
cp "$OUT/vendor.img" "$DIST/vendor.img"

V4L2_REV="$(git -C external/v4l2_codec2 rev-parse HEAD)"
FFMPEG_REV="$(git -C external/ffmpeg rev-parse HEAD)"
FFMPEG_CODEC2_REV="$(git -C external/ffmpeg_codec2 rev-parse HEAD)"
LIBUDEV_ZERO_REV="$(git -C external/libudev-zero rev-parse HEAD)"
WAYDROID_DEVICE_REV="$(git -C device/waydroid/waydroid rev-parse HEAD)"
{
  echo "PITV_WAYDROID_IMAGE_FORMAT=2"
  echo "ANDROID_RELEASE=13"
  echo "LINEAGE_BRANCH=$LINEAGE_BRANCH"
  echo "WAYDROID_BRANCH=$WAYDROID_BRANCH"
  echo "WAYDROID_DEVICE_REV=$WAYDROID_DEVICE_REV"
  echo "V4L2_CODEC2_REV=$V4L2_REV"
  echo "FFMPEG_REV=$FFMPEG_REV"
  echo "FFMPEG_CODEC2_REV=$FFMPEG_CODEC2_REV"
  echo "LIBUDEV_ZERO_REV=$LIBUDEV_ZERO_REV"
  echo "TARGET=lineage_waydroid_arm64-userdebug"
  echo "HW_DECODER_AVC=c2.v4l2.avc.decoder"
  echo "HW_DECODER_HEVC=c2.ffmpeg.hevc.decoder"
} > "$DIST/build-info.env"

(
  cd "$DIST"
  sha256sum vendor.img build-info.env > SHA256SUMS
  xz -T0 -9 -f -k vendor.img
  sha256sum vendor.img.xz >> SHA256SUMS
)

echo
echo "PiTV RPi4 AVC+HEVC Waydroid vendor image built:"
echo "  $DIST/vendor.img"
echo "  $DIST/vendor.img.xz"
echo
cat "$DIST/build-info.env"
