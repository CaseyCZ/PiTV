#!/usr/bin/env bash
set -euo pipefail
# Read-only evidence capture for the FFmpeg HEVC Codec2 experiment.
# Run once before playback and once while an HEVC stream is actively playing.
LABEL="${1:-sample}"
case "$LABEL" in *[!A-Za-z0-9._-]*|'') echo "invalid evidence label" >&2; exit 2;; esac
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${2:-/var/lib/pitv/codec2-experiment/evidence/hevc-${STAMP}-${LABEL}}"
mkdir -p "$OUT"

capture(){
  name="$1"; shift
  { "$@"; } >"$OUT/$name" 2>&1 || true
}
waydroid_cmd(){
  printf '%s\n' "$1" | waydroid shell 2>/dev/null || true
}

{
  echo "LABEL=$LABEL"
  echo "UTC=$STAMP"
  echo "HOST_ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)"
  echo "KERNEL=$(uname -r)"
  printf 'MODEL='
  tr -d '\0' </proc/device-tree/model 2>/dev/null || true
  echo
} >"$OUT/summary.env"

capture host-devices.txt bash -lc "ls -l /dev/video* /dev/media* 2>/dev/null || true"
capture host-processes.txt ps -eo pid,ppid,pcpu,pmem,comm,args
capture host-dmesg-rpivid-v4l2.txt bash -lc "dmesg 2>/dev/null | grep -Eai 'rpivid|v4l2|hevc|codec2|media request' | tail -400 || true"

if command -v media-ctl >/dev/null 2>&1; then
  capture media-ctl.txt media-ctl -p
fi
if command -v v4l2-ctl >/dev/null 2>&1; then
  capture v4l2-devices.txt v4l2-ctl --list-devices
  for dev in /dev/video*; do
    [ -e "$dev" ] || continue
    safe="${dev#/dev/}"
    capture "v4l2-${safe}.txt" v4l2-ctl -d "$dev" --all
  done
fi

# Host-side open device FDs are useful corroborating evidence that media/video
# nodes are actually in use while playback is running.
find /proc/[0-9]*/fd -maxdepth 1 -type l -lname '/dev/video*' -o -lname '/dev/media*' 2>/dev/null \
  | while read -r fd; do
      target="$(readlink "$fd" 2>/dev/null || true)"
      pid="${fd#/proc/}"; pid="${pid%%/*}"
      cmd="$(tr '\0' ' ' </proc/$pid/cmdline 2>/dev/null || true)"
      printf '%s -> %s | pid=%s | %s\n' "$fd" "$target" "$pid" "$cmd"
    done >"$OUT/host-open-media-fds.txt" || true

if command -v waydroid >/dev/null 2>&1; then
  waydroid_cmd 'getprop ro.build.version.release; getprop ro.build.version.sdk; getprop persist.ffmpeg_codec2.v4l2.h265; getprop debug.stagefright.c2-poolmask' >"$OUT/android-properties.txt"
  waydroid_cmd 'dumpsys media.codec' >"$OUT/android-media-codec.txt"
  grep -Eai 'c2\.ffmpeg\.hevc\.decoder|c2\.v4l2\.avc\.decoder|video/hevc' "$OUT/android-media-codec.txt" \
    >"$OUT/android-media-codec-relevant.txt" || true
  waydroid_cmd "cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\000' '\\n' | grep -Eai 'media\.c2|codec2|ffmpeg|v4l2'" \
    >"$OUT/android-codec-processes.txt"
  waydroid_cmd "logcat -d -v threadtime 2>/dev/null | grep -Eai 'c2\.ffmpeg|CCodec|Codec2|ffmpeg|hevc|v4l2|rpivid' | tail -1200" \
    >"$OUT/android-logcat-hevc.txt"
  waydroid_cmd 'top -b -n 1 2>/dev/null | head -120' >"$OUT/android-top.txt"
  waydroid_cmd "for p in /proc/[0-9]*; do for f in \"\$p\"/fd/*; do t=\$(readlink \"\$f\" 2>/dev/null || true); case \"\$t\" in /dev/video*|/dev/media*) c=\$(tr '\\000' ' ' <\"\$p/cmdline\" 2>/dev/null || true); echo \"\$f -> \$t | \$c\";; esac; done; done" \
    >"$OUT/android-open-media-fds.txt"
fi

# Concise flags for quick comparison between before/during captures.
grep -q 'c2.ffmpeg.hevc.decoder' "$OUT/android-media-codec-relevant.txt" 2>/dev/null \
  && echo 'HEVC_CODEC_REGISTERED=1' >>"$OUT/summary.env" \
  || echo 'HEVC_CODEC_REGISTERED=0' >>"$OUT/summary.env"
grep -Eqi 'c2\.ffmpeg\.hevc\.decoder|component.*ffmpeg.*hevc|ffmpeg.*hevc' "$OUT/android-logcat-hevc.txt" 2>/dev/null \
  && echo 'HEVC_CODEC_LOG_EVIDENCE=1' >>"$OUT/summary.env" \
  || echo 'HEVC_CODEC_LOG_EVIDENCE=0' >>"$OUT/summary.env"
[ -s "$OUT/android-open-media-fds.txt" ] || [ -s "$OUT/host-open-media-fds.txt" ] \
  && echo 'MEDIA_NODE_FD_ACTIVITY=1' >>"$OUT/summary.env" \
  || echo 'MEDIA_NODE_FD_ACTIVITY=0' >>"$OUT/summary.env"

cat "$OUT/summary.env"
echo "FFMPEG_HEVC_EVIDENCE=$OUT"
