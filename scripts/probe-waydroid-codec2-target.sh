#!/usr/bin/env bash
set -euo pipefail
# Non-destructive host + Waydroid compatibility inventory for the no-full-build
# Codec2 experiment. This script only reads state.
OUT="${1:-/tmp/pitv-codec2-compat.env}"
q(){ printf '%s=%q\n' "$1" "$2"; }
{
  echo "PITV_CODEC2_COMPAT=1"
  q ARCH "$(dpkg --print-architecture 2>/dev/null || uname -m)"
  q MODEL "$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
  q KERNEL "$(uname -r)"
  q VIDEO_NODES "$(printf '%s ' /dev/video* 2>/dev/null || true)"
  q MEDIA_NODES "$(printf '%s ' /dev/media* 2>/dev/null || true)"
  if command -v waydroid >/dev/null 2>&1; then
    q WAYDROID_VERSION "$(waydroid --version 2>/dev/null || true)"
    for prop in ro.build.version.release ro.build.version.sdk ro.product.cpu.abi ro.vndk.version; do
      val="$(printf 'getprop %s\n' "$prop" | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
      q "ANDROID_${prop//./_}" "$val"
    done
    q ANDROID_VIDEO_NODES "$(printf '%s\n' 'ls -1 /dev/video* 2>/dev/null' | waydroid shell 2>/dev/null | tr '\n' ' ' || true)"
    q ANDROID_MEDIA_NODES "$(printf '%s\n' 'ls -1 /dev/media* 2>/dev/null' | waydroid shell 2>/dev/null | tr '\n' ' ' || true)"
  fi
} >"$OUT"
cat "$OUT"
