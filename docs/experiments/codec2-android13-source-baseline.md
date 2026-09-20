# Pinned Android 13 source baseline for the minimal Codec2 path

This experiment avoids a full Android checkout. If compatible prebuilts are not
available, the fallback is to compile only the media modules and their minimal
Soong dependency closure.

## AVC
- Project: android-rpi/external_v4l2_codec2
- Branch: arpi-13
- Target family: Android 13 / ARM64
- Required outputs: V4L2 Codec2 service + libc2plugin_store and runtime policy.

## HEVC
- Projects: raspberry-vanilla/android_external_ffmpeg,
  raspberry-vanilla/android_external_ffmpeg_codec2 and
  raspberry-vanilla/android_external_libudev-zero
- Branch family: android-13.0
- Target: HEVC-only FFmpeg Codec2 service using RPi4 rpivid V4L2 Request API.

## Build strategy
1. Prefer verified prebuilts extracted from a matching Android 13 RPi image.
2. If unavailable/incompatible, construct a reduced Android 13 build workspace
   containing only Soong/bootstrap/platform headers and the required media
   dependency closure.
3. Never silently fall back to the existing full LineageOS checkout.
4. The reduced builder must enforce a configurable disk ceiling and stop before
   downloading/building if it would exceed it.

Exact source commit SHAs and artifact checksums must be recorded before any
payload is considered reproducible or installable.
