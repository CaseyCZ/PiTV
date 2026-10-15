#!/usr/bin/env bash
set -euo pipefail
# Convert the HEVC-only runtime emitted by codec2-ffmpeg-hevc-graph.yml into
# the normal rollback/inventory/checksum payload shape used by PiTV installers.
# This is read-only with respect to Waydroid and never installs anything.
RUNTIME="$(readlink -f "${1:?built HEVC runtime directory required}")"
OUT="$(readlink -m "${2:?staged output directory required}")"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -d "$RUNTIME" ] || { echo "runtime directory missing: $RUNTIME" >&2; exit 2; }
[ -f "$RUNTIME/PITV-CODEC2-HEVC-RUNTIME.txt" ] || { echo "missing built HEVC runtime manifest" >&2; exit 2; }
[ "$OUT" != "/" ] && [ "$OUT" != "$RUNTIME" ] || { echo "unsafe stage output path" >&2; exit 2; }
case "$OUT/" in "$RUNTIME/"*) echo "stage output must be outside runtime directory" >&2; exit 2;; esac

expected=(
  vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg
  vendor/lib64/libavcodec.so
  vendor/lib64/libavutil.so
  vendor/lib64/libswresample.so
  vendor/lib64/libswscale.so
  vendor/lib64/libffmpeg_utils.so
  vendor/lib64/libudev.so
  vendor/lib64/libdrm.so
  vendor/lib64/libdav1d.so
  vendor/etc/media_codecs_ffmpeg_c2.xml
  vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy
  vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc
  vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml
)

want="$(printf '%s\n' "${expected[@]}" | sort)"
got="$(sed '/^[[:space:]]*$/d' "$RUNTIME/PITV-CODEC2-HEVC-RUNTIME.txt" | sort -u)"
[ "$got" = "$want" ] || {
  echo "built runtime manifest does not match the HEVC-only contract" >&2
  diff -u <(printf '%s\n' "$want") <(printf '%s\n' "$got") || true
  exit 3
}

rm -rf "$OUT"
mkdir -p "$OUT"
for rel in "${expected[@]}"; do
  src="$RUNTIME/$rel"
  [ -f "$src" ] && [ ! -L "$src" ] || { echo "missing/unsafe built runtime file: $rel" >&2; exit 3; }
  mkdir -p "$OUT/$(dirname "$rel")"
  cp -a "$src" "$OUT/$rel"
done
printf '%s\n' "${expected[@]}" | sort -u > "$OUT/PITV-CODEC2-PAYLOAD.txt"

python3 "$HERE/check-ffmpeg-hevc-runtime-payload.py" "$OUT"
python3 "$HERE/validate-codec2-payload.py" "$OUT"
python3 "$HERE/enforce-codec2-payload-scope.py" "$OUT"
python3 "$HERE/check-codec2-manifest-closure.py" "$OUT"
python3 "$HERE/check-codec2-payload-size.py" "$OUT"
python3 "$HERE/inventory-codec2-payload.py" "$OUT"
python3 "$HERE/make-codec2-rollback-manifest.py" "$OUT"
python3 "$HERE/verify-codec2-metadata.py" "$OUT"
python3 "$HERE/verify-staged-codec2-payload.py" "$OUT"
python3 "$HERE/check-ffmpeg-hevc-runtime-payload.py" "$OUT"

echo "FFMPEG_HEVC_STAGE_READY=1"
echo "FFMPEG_HEVC_STAGE=$OUT"
