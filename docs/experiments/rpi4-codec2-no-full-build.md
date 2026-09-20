# RPi4 Codec2 no-full-build experiment

This branch isolates the experiment to enable Raspberry Pi 4 Android/Waydroid hardware video decoding without requiring a full AOSP/LineageOS build workspace.

## Safety rules

- Do not merge experimental changes into Master until hardware validation passes.
- Keep the existing full-build preparation untouched.
- Work in small, independently committed checkpoints.
- Prefer reuse of Android 13 / LineageOS 20 compatible Codec2/V4L2 artifacts.
- Any runtime installer must be rollback-safe before it is allowed to modify Waydroid vendor files.

## Goal

Evaluate and prototype a minimal Codec2/V4L2 integration for PiTV/Waydroid using compatible prebuilt artifacts where legally and technically possible. Fall back to building only the required codec components if prebuilts are not ABI-compatible. A full Android build is the last resort.

## Checkpoints

1. Branch isolation and experiment contract. (done)
2. Inventory current PiTV Waydroid/vendor integration.
3. Map Android 13 V4L2 Codec2 runtime dependencies.
4. Add a non-destructive compatibility probe.
5. Prototype rollback-safe codec overlay/package.
6. CI/static validation.
7. Hardware validation on Raspberry Pi 4.
