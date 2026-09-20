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
# Android envsetup/lunch scripts are not guaranteed to be nounset-clean.
set +u
# shellcheck disable=SC1091
source build/envsetup.sh
lunch "${PITV_CODEC2_LUNCH:-lineage_waydroid_arm64-userdebug}"
m -j"$JOBS"   android.hardware.media.c2@1.0-service-v4l2   libc2plugin_store   android.hardware.media.c2@1.2-service-ffmpeg

rm -rf "$OUT"; mkdir -p "$OUT"
PRODUCT_OUT="${ANDROID_PRODUCT_OUT:?ANDROID_PRODUCT_OUT missing after lunch/build}"
VENDOR_OUT="$PRODUCT_OUT/vendor"
mapfile -t avc_roots < <(find "$VENDOR_OUT" -type f -name 'android.hardware.media.c2@1.0-service-v4l2' | sort)
mapfile -t hevc_roots < <(find "$VENDOR_OUT" -type f -name 'android.hardware.media.c2@1.2-service-ffmpeg' | sort)
[ "${#avc_roots[@]}" -eq 1 ] || { echo "expected one AVC service output" >&2; exit 10; }
[ "${#hevc_roots[@]}" -eq 1 ] || { echo "expected one HEVC service output" >&2; exit 10; }
roots=("${avc_roots[0]#"$VENDOR_OUT"/}" "${hevc_roots[0]#"$VENDOR_OUT"/}")
python3 "$HERE/collect-codec2-prebuilt.py" "$VENDOR_OUT" "$OUT" "${roots[@]}"

# ELF DT_NEEDED does not carry init/VINTF/seccomp metadata. Copy only metadata
# installed by the two selected services, never the rest of donor vendor.
for pattern in \
  'android.hardware.media.c2@1.0-service-v4l2*.rc' \
  'android.hardware.media.c2@1.0-service-v4l2*.xml' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.rc' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.xml' \
  '*v4l2*policy*' '*ffmpeg*policy*'
do
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    rel="${p#"$VENDOR_OUT"/}"
    mkdir -p "$OUT/$(dirname "$rel")"
    cp -a "$p" "$OUT/$rel"
    printf '%s\n' "$rel" >>"$OUT/PITV-CODEC2-PAYLOAD.txt"
  done < <(find "$VENDOR_OUT" -type f -name "$pattern" | sort)
done
sort -u "$OUT/PITV-CODEC2-PAYLOAD.txt" -o "$OUT/PITV-CODEC2-PAYLOAD.txt"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$HERE/.."
python3 "$HERE/validate-codec2-payload.py" "$OUT"
echo "Minimal Codec2 build payload: $OUT"
