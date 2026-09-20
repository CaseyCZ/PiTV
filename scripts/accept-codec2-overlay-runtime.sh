#!/usr/bin/env bash
set -euo pipefail
# Read-only runtime acceptance probe derived from the proven full-image installer.
fail=0
check(){ if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }
check arm64 '[ "$(dpkg --print-architecture 2>/dev/null || uname -m)" = arm64 ]'
model="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
check rpi4 '[[ "$model" == *"Raspberry Pi 4"* ]]'
check host_video "compgen -G '/dev/video*' >/dev/null"
check host_media "compgen -G '/dev/media*' >/dev/null"
command -v waydroid >/dev/null 2>&1 || { echo "FAIL waydroid"; exit 30; }
shell(){ printf '%s\n' "$1" | waydroid shell 2>/dev/null | tr -d '\r'; }
release="$(shell 'getprop ro.build.version.release' | tail -n1 || true)"
check android13 '[ "$release" = 13 ]'
boot="$(shell 'getprop sys.boot_completed' | tail -n1 || true)"
check boot_completed '[ "$boot" = 1 ]'
codecs="$(shell 'dumpsys media.codec 2>/dev/null' || true)"
check avc_registry 'grep -q "c2.v4l2.avc.decoder" <<<"$codecs"'
check hevc_registry 'grep -q "c2.ffmpeg.hevc.decoder" <<<"$codecs"'
video="$(shell 'ls -1 /dev/video* 2>/dev/null' || true)"
check android_video_nodes 'grep -q "^/dev/video" <<<$video'
media="$(shell 'ls -1 /dev/media* 2>/dev/null' || true)"
check android_media_nodes 'grep -q "^/dev/media" <<<"$media"'
procs="$(shell "cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\000' '\\n'" || true)"
check avc_service 'grep -Eiq "media\.c2.*v4l2|v4l2.*media\.c2" <<<"$procs"'
check hevc_service 'grep -Eiq "media\.c2.*ffmpeg|ffmpeg.*media\.c2" <<<"$procs"'
exit "$fail"
