#!/usr/bin/env bash
set -euo pipefail
DONOR="$(readlink -f "${1:?extracted vendor tree required}")"
OUT="$(readlink -m "${2:?payload output required}")"
[ -d "$DONOR" ] || { echo "donor tree missing" >&2; exit 2; }
[ "$OUT" != "/" ] && [ "$OUT" != "$DONOR" ] || { echo "unsafe output directory" >&2; exit 2; }
case "$OUT/" in "$DONOR/"*) echo "output must not be inside donor tree" >&2; exit 2;; esac
HERE="$(cd "$(dirname "$0")" && pwd)"
find_one(){
  mapfile -t hits < <(find "$DONOR" -type f -name "$1" | sort)
  [ "${#hits[@]}" -eq 1 ] || { echo "expected exactly one $1, found ${#hits[@]}" >&2; exit 3; }
  printf '%s\n' "${hits[0]}"
}
avc="$(find_one android.hardware.media.c2@1.0-service-v4l2-64)"
hevc="$(find_one android.hardware.media.c2@1.2-service-ffmpeg)"
python3 "$HERE/probe-codec2-prebuilt.py" "$DONOR" "$avc" "$hevc"
python3 "$HERE/collect-codec2-prebuilt.py" "$DONOR" "$OUT" "$avc" "$hevc"

# Include only service metadata associated with these codec services.
for pattern in \
  'android.hardware.media.c2@1.0-service-v4l2*.rc' \
  'android.hardware.media.c2@1.0-service-v4l2*.xml' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.rc' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.xml' \
  '*v4l2*policy*' '*ffmpeg*policy*' 'media_codecs_ffmpeg_c2.xml'
do
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    rel="${p#"$DONOR"/}"; mkdir -p "$OUT/$(dirname "$rel")"; cp -a "$p" "$OUT/$rel"
    printf '%s\n' "$rel" >>"$OUT/PITV-CODEC2-PAYLOAD.txt"
  done < <(find "$DONOR" -type f -name "$pattern" | sort)
done
sort -u "$OUT/PITV-CODEC2-PAYLOAD.txt" -o "$OUT/PITV-CODEC2-PAYLOAD.txt"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$HERE/.."
python3 "$HERE/validate-codec2-payload.py" "$OUT"
python3 "$HERE/verify-staged-codec2-payload.py" "$OUT"
python3 "$HERE/enforce-codec2-payload-scope.py" "$OUT"
python3 "$HERE/check-codec2-payload-size.py" "$OUT"
python3 "$HERE/inventory-codec2-payload.py" "$OUT"
python3 "$HERE/make-codec2-rollback-manifest.py" "$OUT"
python3 "$HERE/verify-codec2-metadata.py" "$OUT"
python3 "$HERE/codec2-payload-readiness.py" "$OUT"
python3 "$HERE/check-codec2-service-metadata.py" "$OUT"
echo "Codec2 donor payload ready: $OUT"
