# Codec2 narrow Soong probe

This marker documents the first gated runtime probe of the V4L2/AVC-only Soong graph.

- Trigger: `[probe-codec2]`
- Reuses the known-good Android 13 Soong bootstrap checkpoint.
- Runs `PITV_CODEC2_PHASE=narrow-probe` only.
- Does not run the legacy global Codec2 graph or reduced module build.
- FFmpeg/HEVC remains on the separate Android.mk/Kati path.

The probe is intentionally isolated so a failure cannot be mistaken for a full Codec2 build result.


## Probe 2

Direct `soong_build` narrow AVC probe. Ninja command expansion is intentionally bypassed; `[probe-codec2]` gates only the narrow probe job.


## Probe 3

Retry direct Android 13 `soong_build` with corrected `--out` / `--soong_out` flags and no Ninja command expansion. `[probe-codec2]`


## Probe 4

Retry the direct AVC Soong graph with the minimal `external/golang-protobuf/` dependency closure added after Probe 3. `[probe-codec2]`


## Probe 5

Retry the direct AVC Soong graph with the minimal `kernel/configs/` Soong-rule dependency added after Probe 4. `[probe-codec2]`
