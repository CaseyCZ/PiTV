# No-full-build Codec2 dependency map

This checkpoint maps what PiTV must provide at runtime if we avoid the full LineageOS/Waydroid build.

## Compatibility baseline

Target remains ARM64 LineageOS 20 / Android 13. The no-full-build path must not replace the complete Waydroid vendor image with a Raspberry Pi Android vendor image.

## AVC / H.264 path

Target component: `c2.v4l2.avc.decoder`.

Required payload classes:
- `/vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2`
- `libc2plugin_store.so` in the matching vendor ABI location
- every non-platform shared-library dependency required by those binaries
- Codec2 media XML advertising only the RPi4 AVC decoder we intend to use
- Codec2 extended seccomp policy
- service init/VINTF material if not already satisfied by the target vendor
- matching SELinux file labels/policy where required

Host/runtime prerequisites:
- stateful V4L2 H.264 decoder exposed by the RPi4 kernel
- `/dev/video*` visible and permitted inside Waydroid
- compatible gralloc / Codec2 buffer allocation

## HEVC / H.265 path

Target component: `c2.ffmpeg.hevc.decoder`.

Required payload classes:
- Android 13 FFmpeg Codec2 service binary
- FFmpeg Codec2 component/store libraries
- matching Android 13 FFmpeg shared libraries and transitive non-platform dependencies
- HEVC-only media codec XML
- service init/VINTF/seccomp/SELinux material required by that service

Host/runtime prerequisites:
- RPi4 `rpivid` stateless V4L2 Request API
- both relevant `/dev/video*` and `/dev/media*` nodes visible in Waydroid
- kernel/userspace request-API compatibility

PiTV already contains a reversible `/dev/media*` Waydroid extension, so that part can be reused.

## What can be copied vs. what must be checked

Do not assume a binary is portable merely because both systems are Android 13 ARM64. Every candidate prebuilt must pass:

1. ELF architecture check (AArch64).
2. `DT_NEEDED` dependency closure against the actual PiTV Waydroid system/vendor.
3. Android linker namespace accessibility.
4. symbol/version resolution against Android 13 platform/vendor libraries.
5. service registration and VINTF compatibility.
6. SELinux/seccomp compatibility.
7. Codec2 registry visibility without replacing generic software fallbacks.

If any required private/vendor dependency pulls in the donor Raspberry Pi graphics or device HAL stack, reject that prebuilt rather than recursively transplanting the donor vendor.

## Preferred artifact sources

For AVC, prefer Android 13 / LineageOS 20 outputs built from the lineage-rpi `lineage-20.0` or android-rpi `arpi-13` V4L2 Codec2 trees.

For HEVC, prefer Android 13 Raspberry Vanilla FFmpeg + FFmpeg Codec2 outputs matching the source revisions already pinned by PiTV's full-build prototype.

Do not use current Android 16/17 APEX/AIDL media HAL binaries for this Android 13 experiment.

## Decision gate

A prebuilt-only package is feasible only if its complete dependency closure can be satisfied by:
- files already present in PiTV Waydroid Android 13, plus
- a small self-contained codec payload.

If satisfying the closure requires replacing core graphics, libc, VNDK, binder, or broad Raspberry Pi vendor HALs, stop the transplant attempt and move to a targeted Android-13 codec build instead.

The full ~300 GB LineageOS build remains the last-resort reference path, not the default path.
