#!/usr/bin/env bash
set -euo pipefail

TREE="$(readlink -f "${1:?Android tree required}")"
SOURCES="$(readlink -f "${2:?Codec2 source directory required}")"
OUT="$(readlink -m "${3:?runtime payload output required}")"

[ -d "$TREE" ] || { echo "missing Android tree: $TREE" >&2; exit 2; }
[ -d "$SOURCES/ffmpeg_codec2" ] || { echo "missing pinned FFmpeg Codec2 source" >&2; exit 2; }
[ "$OUT" != "/" ] && [ "$OUT" != "$TREE" ] || { echo "unsafe runtime output path" >&2; exit 2; }
case "$OUT/" in "$TREE/"*) echo "runtime output must be outside Android tree" >&2; exit 2;; esac

NINJA="$TREE/prebuilts/build-tools/linux-x86/bin/ninja"
[ -x "$NINJA" ] || NINJA="$(command -v ninja)"
GRAPH="$TREE/out/soong/pitv-codec2.ninja"
PRODUCT="$TREE/out/soong/target/product/rpi4"
[ -s "$GRAPH" ] || { echo "missing narrow Soong graph: $GRAPH" >&2; exit 2; }

runtime_paths=(
  "vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg"
  "vendor/lib64/libavcodec.so"
  "vendor/lib64/libavutil.so"
  "vendor/lib64/libswresample.so"
  "vendor/lib64/libswscale.so"
  "vendor/lib64/libffmpeg_utils.so"
  "vendor/lib64/libudev.so"
  "vendor/lib64/libdrm.so"
  "vendor/lib64/libdav1d.so"
  "vendor/etc/media_codecs_ffmpeg_c2.xml"
  "vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy"
)

targets=()
for rel in "${runtime_paths[@]}"; do
  targets+=("$PRODUCT/$rel")
done

cd "$TREE"
"$NINJA" -d keepdepfile -f "$GRAPH" -j2 "${targets[@]}"

rm -rf "$OUT"
mkdir -p "$OUT"
for rel in "${runtime_paths[@]}"; do
  src="$PRODUCT/$rel"
  [ -f "$src" ] || { echo "missing runtime build output: $src" >&2; exit 3; }
  mkdir -p "$OUT/$(dirname "$rel")"
  cp -a "$src" "$OUT/$rel"
done

mkdir -p "$OUT/vendor/etc/init" "$OUT/vendor/etc/vintf/manifest"
cp -a \
  "$SOURCES/ffmpeg_codec2/android.hardware.media.c2@1.2-service-ffmpeg.rc" \
  "$OUT/vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc"
cp -a \
  "$SOURCES/ffmpeg_codec2/android.hardware.media.c2@1.2-service-ffmpeg.xml" \
  "$OUT/vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml"

manifest="$OUT/PITV-CODEC2-HEVC-RUNTIME.txt"
{
  printf '%s\n' "${runtime_paths[@]}"
  printf '%s\n' \
    "vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc" \
    "vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml"
} | sort -u > "$manifest"

metadata="$OUT/PITV-CODEC2-HEVC-ELF.txt"
: > "$metadata"
elf_paths=(
  "vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg"
  "vendor/lib64/libavcodec.so"
  "vendor/lib64/libavutil.so"
  "vendor/lib64/libswresample.so"
  "vendor/lib64/libswscale.so"
  "vendor/lib64/libffmpeg_utils.so"
  "vendor/lib64/libudev.so"
  "vendor/lib64/libdrm.so"
  "vendor/lib64/libdav1d.so"
)
for rel in "${elf_paths[@]}"; do
  elf="$OUT/$rel"
  file "$elf" >> "$metadata"
  readelf -h "$elf" | grep -E 'Class:|Type:|Machine:' >> "$metadata"
  readelf -d "$elf" | grep 'NEEDED' >> "$metadata" || true
  sha256sum "$elf" >> "$metadata"
  printf '\n' >> "$metadata"
  file "$elf" | grep -q 'ELF 64-bit'
  readelf -h "$elf" | grep -q 'Machine:.*AArch64'
done

codec_xml="$OUT/vendor/etc/media_codecs_ffmpeg_c2.xml"
mapfile -t codec_names < <(grep -oE 'c2\.ffmpeg\.[^"< ]+' "$codec_xml" | sort -u)
if [ "${#codec_names[@]}" -ne 1 ] || [ "${codec_names[0]}" != "c2.ffmpeg.hevc.decoder" ]; then
  printf 'unexpected FFmpeg Codec2 runtime components: %s\n' "${codec_names[*]:-none}" >&2
  exit 4
fi

test -s "$OUT/vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy"
test -s "$OUT/vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc"
test -s "$OUT/vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml"

echo "CODEC2_FFMPEG_HEVC_RUNTIME_READY=1"
echo "CODEC2_FFMPEG_HEVC_RUNTIME_FILES=$(wc -l < "$manifest")"
echo "CODEC2_FFMPEG_HEVC_RUNTIME_MANIFEST=$manifest"
echo "CODEC2_FFMPEG_HEVC_RUNTIME_METADATA=$metadata"
