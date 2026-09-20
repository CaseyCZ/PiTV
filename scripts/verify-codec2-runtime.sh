#!/usr/bin/env bash
set -euo pipefail
command -v waydroid >/dev/null || { echo "Waydroid missing"; exit 2; }
release="$(printf 'getprop ro.build.version.release\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
boot="$(printf 'getprop sys.boot_completed\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
media="$(printf 'ls -1 /dev/media* 2>/dev/null\n' | waydroid shell 2>/dev/null || true)"
codecs="$(printf 'dumpsys media.codec\n' | waydroid shell 2>/dev/null || true)"
procs="$(printf "cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\000' '\\n'\n" | waydroid shell 2>/dev/null || true)"
rank="$(printf 'getprop persist.v4l2_codec2.rank.decoder\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
pool="$(printf 'getprop debug.stagefright.c2-poolmask\n' | waydroid shell 2>/dev/null | tr -d '\r' | tail -n1 || true)"
ok=1
[ "$release" = 13 ] || ok=0
[ "$boot" = 1 ] || ok=0
printf '%s\n' "$media" | grep -q '/dev/media' || ok=0
printf '%s\n' "$codecs" | grep -q 'c2.v4l2.avc.decoder' || ok=0
printf '%s\n' "$codecs" | grep -q 'c2.ffmpeg.hevc.decoder' || ok=0
printf '%s\n' "$procs" | grep -Eiq 'media\.c2.*v4l2|v4l2.*media\.c2' || ok=0
printf '%s\n' "$procs" | grep -Eiq 'media\.c2.*ffmpeg|ffmpeg.*media\.c2' || ok=0
[ "$rank" = 128 ] || ok=0
[ "$pool" = 0x350000 ] || ok=0
echo "android_release=$release"
echo "boot_completed=$boot"
echo "media_nodes=$([ -n "$media" ] && echo yes || echo no)"
echo "avc_codec=$(printf '%s\n' "$codecs" | grep -q 'c2.v4l2.avc.decoder' && echo yes || echo no)"
echo "hevc_codec=$(printf '%s\n' "$codecs" | grep -q 'c2.ffmpeg.hevc.decoder' && echo yes || echo no)"
echo "v4l2_rank=$rank"
echo "c2_poolmask=$pool"
echo "codec2_runtime=$([ "$ok" -eq 1 ] && echo healthy || echo failed)"
[ "$ok" -eq 1 ]
