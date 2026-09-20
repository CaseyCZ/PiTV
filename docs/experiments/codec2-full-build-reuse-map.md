# Reuse map from the existing full-image RPi4 preparation

The experiment may reuse configuration and validation contracts already present
in PiTV. It must not require or overwrite the full-build workflow.

## Reuse directly
- `android/waydroid-rpi4/media_codecs.xml`: AVC Codec2 registration and FFmpeg
  include.
- `android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml`: HEVC registration.
- `android/waydroid-rpi4/vendor.prop`: V4L2 Codec2 ranking/pool properties.
- `android/waydroid-rpi4/hwdecode.env`: expected backend markers.
- `android/waydroid-rpi4/codec2.vendor.ext.policy`: existing seccomp extension.
- `system/pitv-waydroid-device-patch`: reversible /dev/media* passthrough.

## Reuse as validation contract
From `scripts/install-waydroid-rpi4-v4l2-image.sh`:
- ARM64 + Raspberry Pi 4 guard.
- Android 13 guard.
- host /dev/video* and /dev/media* checks.
- Android boot_completed check.
- AVC and HEVC XML registration checks.
- /dev/media* visibility inside Android.
- running V4L2 and FFmpeg Codec2 process checks.
- HEVC_V4L2_REQUEST=compiled marker.

## Do not reuse for this experiment
- complete vendor.img replacement;
- full LineageOS repo sync;
- 300GB self-hosted build workspace;
- any action that changes Master/full-build preparation.

The overlay path will consume the same known-good PiTV configuration while
replacing only the minimum codec service/library files.
