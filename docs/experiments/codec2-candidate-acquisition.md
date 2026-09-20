# Candidate payload acquisition contract

The no-full-build experiment must consume an extracted Android 13 ARM64 donor
artifact, never a live donor installation and never the complete donor vendor.

Expected input layout is any extracted tree containing the selected Codec2
service binaries and their libraries. Acquisition is deliberately separate from
installation.

## Pipeline

1. Acquire an Android 13 ARM64 donor artifact from the matching open-source
   RPi media implementation/build.
2. Verify provenance and checksum before extraction.
3. Run `scripts/probe-codec2-prebuilt.py` against the extracted tree.
4. Run `scripts/collect-codec2-prebuilt.py` with explicit AVC/HEVC service
   roots. It follows only the required non-platform ELF dependency closure.
5. Review `PITV-CODEC2-PAYLOAD.txt`.
6. Only a payload that passes those gates may be handed to a future
   rollback-safe installer.

No script in this experiment downloads arbitrary binaries or installs them
automatically. That remains intentional until exact donor artifacts and their
licenses/checksums are pinned.
