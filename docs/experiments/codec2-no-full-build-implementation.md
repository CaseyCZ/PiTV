# PiTV RPi4 Codec2 without a full Android build

Status: experimental branch only. Master and the existing full-build path are
unchanged.

## What is implemented

The branch now contains the complete host-side pipeline:

```
Android 13 donor tree
  -> probe-codec2-prebuilt.py
  -> collect-codec2-prebuilt.py
  -> assemble-codec2-overlay.py
  -> validate-codec2-payload.py
  -> stage-codec2-payload.sh
  -> plan-codec2-overlay-install.sh
  -> install-codec2-overlay.sh
  -> Android boot + Codec2 validation
  -> automatic rollback on failure
```

The explicit rollback command is `rollback-codec2-overlay.sh`. The installer
never modifies the original vendor image in place: it backs up the current
system/vendor pair, patches a copy, installs that copy through
`/etc/waydroid-extra/images`, and restores the backup if Android 13 does not
boot or either hardware codec/service is missing.

## Expected codec roots

AVC must ultimately provide the Android 13 V4L2 Codec2 service that registers
`c2.v4l2.avc.decoder`.

HEVC must provide the Android 13 FFmpeg Codec2 service that registers
`c2.ffmpeg.hevc.decoder` and uses the RPi4 rpivid V4L2 Request API.

The exact service binary paths depend on the donor artifact. They are therefore
explicit arguments to `prepare-codec2-overlay.sh`; the collector follows their
non-platform ELF dependencies instead of copying an entire donor vendor tree.

## Safety gates

- ARM64 and Raspberry Pi 4 checks.
- Android 13 validation after boot.
- host `/dev/video*` and `/dev/media*` required.
- Android `/dev/media*` visibility required.
- both Codec2 names required in `dumpsys media.codec`.
- both Codec2 service processes required.
- payload SHA-256 manifest.
- complete system/vendor backup before activation.
- automatic rollback on every post-activation validation failure.
- full-build workspace is not used by this path.

## Remaining external input

The code path is complete, but a real payload cannot be produced from source
code alone: it needs either compatible Android 13 ARM64 donor artifacts or a
small module-only build output. Those binaries must be pinned by source commit
and checksum before physical installation.

Physical RPi4 validation is intentionally the final gate before any merge into
Master.

## Operator entry point

Use `scripts/codec2-no-full-build.sh` for the experiment lifecycle. It exposes
target probing, pinned source fetch, module-only build, donor preparation,
staging, dry-run planning, installation, rollback, status and static checks.

The module-only builder intentionally requires an existing Android 13 build
tree and never performs `repo init` or `repo sync`. This keeps the experiment
separate from the legacy full-source build and makes disk usage an explicit
operator choice guarded by `PITV_CODEC2_MAX_GB`.

Pinned source revisions are stored in
`android/waydroid-rpi4/minimal-codec2-sources.lock.json`.
