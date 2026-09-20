# RPi4 Codec2 no-full-build experiment

This branch isolates Raspberry Pi 4 Android/Waydroid hardware-video decoding from Master and avoids the old full ~300 GB Android build.

## Safety contract

- Never merge to Master before physical Raspberry Pi 4 validation.
- Never silently create or sync a full Android source workspace.
- Accept only Android 13 / arm64 payloads with a closed, minimal vendor surface.
- Reject graphics, camera, audio, Wi-Fi, Bluetooth and unrelated donor HALs.
- Require checksums, inventory, rollback metadata, dependency closure and service metadata before activation.
- Modify a copy of vendor.img; keep system.img/vendor.img backups and automatically restore on activation failure.

## Intended hardware paths

- AVC/H.264: `c2.v4l2.avc.decoder` through the stateful Raspberry Pi V4L2 Codec2 service.
- HEVC/H.265: `c2.ffmpeg.hevc.decoder` through FFmpeg Codec2 + rpivid/V4L2 Request API.
- VP9/AV1 remain Android software fallbacks.

## Acquisition paths

The experiment supports two inputs. `prepare-donor` extracts the two codec services and their dependency closure from a compatible user-supplied Android 13 vendor image. `fetch-sources` + `build-modules` uses the pinned reduced source set and an existing Android 13 build tree; it does not run repo init/sync.

Pinned upstream revisions live in `android/waydroid-rpi4/minimal-codec2-sources.lock.json`.

## Flow

`target-check` checks RPi4/arm64/Android13 and V4L2 nodes. Build or collect a payload, then `install-readiness PAYLOAD`, `stage PAYLOAD`, `plan STAGE`, and finally `install STAGE` on the Pi. `rollback` restores the recorded images. `verify`, `accept`, and `evidence` provide post-install proof.

No installation should be attempted until a payload contains real AArch64 codec ELF binaries for both services and passes all readiness gates.

## Physical acceptance

A successful physical test must show Android 13 booted, `/dev/media*` visible inside Waydroid, both codec names in `dumpsys media.codec`, both codec services running, required PiTV Codec2 properties active, and successful runtime evidence capture. SmartTube playback must then confirm materially reduced CPU usage for H.264 and HEVC without audio-sync, launcher, Kodi, reboot, or session-recovery regressions.

## Current boundary

The safety, acquisition, staging, installation, rollback, runtime verification and evidence paths are implemented on this experiment branch. The remaining external prerequisite is a real compatible codec payload: either donor binaries or outputs from the reduced Android 13 module build. Master remains untouched.
