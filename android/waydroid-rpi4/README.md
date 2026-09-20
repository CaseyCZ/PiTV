# PiTV Waydroid RPi4 hardware video decode

This directory contains the PiTV vendor additions used to build a Waydroid
LineageOS 20 / Android 13 ARM64 vendor image with Raspberry Pi 4 hardware video
decoding.

PiTV deliberately uses two different Android Codec2 paths because the Pi 4
hardware exposes its two useful decoders through different Linux V4L2 APIs:

- **H.264 / AVC** — `c2.v4l2.avc.decoder` through the stateful
  `android.hardware.media.c2@1.0-service-v4l2` service.
- **HEVC / H.265** — `c2.ffmpeg.hevc.decoder` through Raspberry Vanilla's
  FFmpeg Codec2 service and the stateless V4L2 Media Request API used by
  `rpivid`.

VP9 and AV1 remain software fallbacks on Raspberry Pi 4; PiTV does not advertise
them as hardware accelerated.

## Why this exists

The generic Waydroid ARM64 image exposes the Raspberry Pi host `/dev/video*`
nodes inside the Android container, but its media registry advertises only
software codecs such as `OMX.google.h264.decoder` and
`c2.android.avc.decoder`.

For HEVC there is an additional host/container requirement: stateless rpivid
decoding submits controls through `/dev/media*`. Upstream Waydroid currently
passes `/dev/video*` but not those media-controller request nodes, so PiTV
installs a small reversible Waydroid extension that exposes both.

## Build

A full LineageOS/Waydroid build needs a Linux x86-64 Android build host with a
large amount of storage and memory.

Install the normal LineageOS build dependencies plus Google's `repo` tool,
then run:

```bash
scripts/build-waydroid-rpi4-v4l2.sh /path/to/large/android-work
```

The script:

1. initializes LineageOS 20 and the official Waydroid Lineage 20 source tree;
2. applies the Waydroid patches;
3. selects the Raspberry Pi Android media implementations:
   - `lineage-rpi/android_external_v4l2_codec2` for AVC;
   - `raspberry-vanilla/android_external_ffmpeg` for stateless HEVC;
   - `raspberry-vanilla/android_external_ffmpeg_codec2`;
   - `raspberry-vanilla/android_external_libudev-zero`;
4. injects the PiTV media profile, properties, seccomp policy and SELinux labels;
5. builds `lineage_waydroid_arm64-userdebug` vendor image;
6. verifies both Codec2 services and both advertised decoder components;
7. writes `vendor.img`, `vendor.img.xz`, `build-info.env` and
   `SHA256SUMS` to `dist/waydroid-rpi4-v4l2/`.

## Installation safety

`scripts/install-waydroid-rpi4-v4l2-image.sh` backs up the currently working
Waydroid system/vendor images before replacing the vendor image.

The new image is accepted only when Android 13 reaches `boot_completed=1` and
all of these are true:

- `c2.v4l2.avc.decoder` is registered;
- the V4L2 AVC Codec2 HAL is running;
- `c2.ffmpeg.hevc.decoder` is registered;
- the FFmpeg Codec2 HAL is running;
- `persist.ffmpeg_codec2.v4l2.h265=true`;
- `/dev/video*` and `/dev/media*` are visible inside Android.

If validation fails, the installer restores the previous images automatically.

## Physical acceptance test

After installation run:

```bash
sudo /usr/local/libexec/pitv-helper waydroid-hw-codec-status
```

A complete hardware-decode setup must report both decoders/HALs as active and
at least one media request node.

For AVC, reproduce the existing SmartTube test with a fixed 1080p AVC / 30 fps
stream and compare `dropOutputBuffer` frequency.

HEVC should be tested separately with a known H.265 file/stream in an Android
player. SmartTube/YouTube commonly uses VP9 or AV1 for higher resolutions, so a
4K YouTube selection is not proof of HEVC acceleration.
