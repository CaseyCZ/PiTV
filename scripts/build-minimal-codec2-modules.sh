#!/usr/bin/env bash
set -euo pipefail
# Build only the PiTV Codec2 modules inside an existing Android 13 build tree.
# This script never runs repo init/sync and therefore cannot create the old
# full ~300GB workspace by itself.
TREE="${1:?Android 13 build tree required}"
SOURCES="${2:?directory from fetch-minimal-codec2-sources.py required}"
OUT="${3:?output payload directory required}"
JOBS="${PITV_CODEC2_JOBS:-$(nproc)}"
[ -f "$TREE/build/envsetup.sh" ] || { echo "not an Android build tree" >&2; exit 2; }
for d in v4l2_codec2 ffmpeg ffmpeg_codec2 libudev_zero; do [ -d "$SOURCES/$d" ] || { echo "missing $d" >&2; exit 2; }; done
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/guard-codec2-build-workspace.sh" "$TREE"
release_file="$TREE/build/make/core/version_defaults.mk"
if [ -f "$release_file" ] && ! grep -Eq 'PLATFORM_VERSION.*13|PLATFORM_VERSION_LAST_STABLE.*13' "$release_file"; then
  echo "build tree does not look like Android 13" >&2; exit 3
fi

install_src(){
  src="$1"; dst="$2"
  rm -rf "$TREE/$dst"
  mkdir -p "$(dirname "$TREE/$dst")"
  cp -a "$SOURCES/$src" "$TREE/$dst"
}
install_src v4l2_codec2 external/v4l2_codec2
install_src ffmpeg external/ffmpeg
install_src ffmpeg_codec2 external/ffmpeg_codec2
install_src libudev_zero external/libudev-zero

cd "$TREE"
# shellcheck disable=SC1091
source build/envsetup.sh
lunch "${PITV_CODEC2_LUNCH:-lineage_waydroid_arm64-userdebug}"
m -j"$JOBS"   android.hardware.media.c2@1.0-service-v4l2   libc2plugin_store   android.hardware.media.c2@1.2-service-ffmpeg

rm -rf "$OUT"; mkdir -p "$OUT"
PRODUCT_OUT="${ANDROID_PRODUCT_OUT:?ANDROID_PRODUCT_OUT missing after lunch/build}"
copy_match(){
  base="$1"; required="${2:-yes}"
  mapfile -t hits < <(find "$PRODUCT_OUT/vendor" -type f -name "$base" 2>/dev/null | sort -u)
  if [ "${#hits[@]}" -eq 0 ]; then
    [ "$required" = no ] && return 0
    echo "missing build output: $base" >&2; exit 10
  fi
  for p in "${hits[@]}"; do
    rel="${p#"$PRODUCT_OUT/"}"; mkdir -p "$OUT/$(dirname "$rel")"; cp -a "$p" "$OUT/$rel"
  done
}
copy_match 'android.hardware.media.c2@1.0-service-v4l2'
copy_match 'libc2plugin_store.so'
copy_match 'android.hardware.media.c2@1.2-service-ffmpeg'
copy_match 'libffmpeg_utils.so'
copy_match 'libavcodec.so'
copy_match 'libavutil.so'
copy_match 'libswresample.so'
copy_match 'libswscale.so'
copy_match 'android.hardware.media.c2@1.0-service-v4l2.rc' no
copy_match 'android.hardware.media.c2@1.0-service-v4l2.xml' no
copy_match 'android.hardware.media.c2@1.2-service-ffmpeg.rc' no
copy_match 'android.hardware.media.c2@1.2-service-ffmpeg.xml' no
copy_match '*v4l2*policy*' no
copy_match '*ffmpeg*policy*' no
find "$OUT" -type f -printf '%P\n' | sort >"$OUT/PITV-CODEC2-PAYLOAD.txt"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$HERE/.."
python3 "$HERE/validate-codec2-payload.py" "$OUT"
echo "Minimal Codec2 build payload: $OUT"
