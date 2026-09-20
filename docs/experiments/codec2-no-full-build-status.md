# No-full-build Codec2 experiment status

## Completed gates
- isolated experiment branch; Master/full-image preparation untouched;
- pinned Android 13 ARM64 V4L2/FFmpeg Codec2 sources;
- donor extraction and dependency audit path;
- minimal payload collection and PiTV-owned config reuse;
- payload checksums, path-safety checks, staging and preflight;
- rollback planning and full vendor-image backup/restore safety net;
- RPi4, Android 13, /dev/video* and /dev/media* runtime guards;
- AVC c2.v4l2.avc.decoder and HEVC c2.ffmpeg.hevc.decoder acceptance checks;
- reduced-module build path that never runs repo init/sync;
- CI/static self-tests.

## Remaining before physical install
1. Obtain or build the actual pinned Android 13 ARM64 codec service payload.
2. Run ELF dependency audit against the exact PiTV Waydroid system/vendor.
3. Install only after the audit passes.
4. Validate SmartTube H.264 and HEVC playback, CPU load, A/V sync and reboot recovery.

The full ~300GB build remains a fallback only.
