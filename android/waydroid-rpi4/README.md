# PiTV Waydroid RPi4 V4L2 Codec2

This directory contains the PiTV vendor additions used to build a Waydroid
LineageOS 20 / Android 13 ARM64 vendor image with Raspberry Pi 4 V4L2 hardware
H.264 decoding.

## Why this exists

The generic Waydroid ARM64 image exposes the Raspberry Pi host `/dev/video*`
nodes inside the Android container, but its media registry advertises only
software codecs such as `OMX.google.h264.decoder` and
`c2.android.avc.decoder`.  PiTV therefore adds the Raspberry-Pi-maintained
V4L2 Codec2 service so Android can expose `c2.v4l2.avc.decoder`.

The first PiTV profile intentionally enables only H.264/AVC.  VP8, VP9 and HEVC
must not be advertised until they are physically verified against the exact
Raspberry Pi kernel/driver combination used by PiTV.

## Build

A full LineageOS/Waydroid build needs a Linux x86-64 Android build host with a
large amount of storage and memory.

Install the normal LineageOS build dependencies plus Google's `repo` tool,
then run:

```bash
scripts/build-waydroid-rpi4-v4l2.sh /path/to/large/android-work
```

The script:

1. initializes LineageOS 20;
2. generates the official Waydroid Lineage 20 manifests and applies Waydroid
   patches;
3. replaces the generic `external/v4l2_codec2` tree with the Raspberry Pi
   Lineage 20 fork;
4. injects the PiTV media profile, seccomp policy and SELinux file context;
5. builds `lineage_waydroid_arm64-userdebug` vendor image;
6. verifies that the V4L2 service and `c2.v4l2.avc.decoder` are present;
7. writes `vendor.img`, `vendor.img.xz`, `build-info.env` and
   `SHA256SUMS` to `dist/waydroid-rpi4-v4l2/`.

## Physical acceptance test

After the image is installed on the Pi 4, the Android codec registry must show
`c2.v4l2.avc.decoder`.  SmartTube should then be tested with a fixed
1080p AVC / 30 fps stream while checking that the previous continuous
`dropOutputBuffer` pattern is gone or materially reduced.

Do not mark VP9/HEVC as hardware accelerated solely because `/dev/video*`
exists in the container; the Android Codec2 service and the specific driver
capability both have to be proven.
