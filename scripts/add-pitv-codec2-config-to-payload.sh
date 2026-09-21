#!/usr/bin/env bash
set -euo pipefail
# Copy the already-maintained PiTV Codec2 configuration into an experimental
# payload. Binary codec services/libraries are supplied separately.
OUT="${1:?payload directory required}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT/vendor/etc/seccomp_policy"
copy() {
  src="$1"; rel="$2"
  test -f "$ROOT/$src"
  mkdir -p "$OUT/$(dirname "$rel")"
  cp "$ROOT/$src" "$OUT/$rel"
}
copy android/waydroid-rpi4/media_codecs.xml vendor/etc/media_codecs_pitv_rpi4.xml
copy android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml vendor/etc/media_codecs_ffmpeg_c2.xml
copy android/waydroid-rpi4/vendor.prop vendor/etc/pitv-codec2.prop
copy android/waydroid-rpi4/hwdecode.env vendor/etc/pitv-hwdecode.env
copy android/waydroid-rpi4/codec2.vendor.ext.policy vendor/etc/seccomp_policy/codec2.vendor.ext.policy
python3 "$ROOT/scripts/register-pitv-codec2-config.py" "$OUT"
echo "CONFIG_REUSED=5"
