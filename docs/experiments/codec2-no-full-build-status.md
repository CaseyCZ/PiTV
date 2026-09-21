# No-full-build Codec2 experiment status

## Completed gates
- isolated experiment branch; Master and Alpha remain untouched;
- exact pinned Android 13 ARM64 Raspberry Vanilla V4L2/FFmpeg Codec2 source lock, commit/origin/dirty-tree verification;
- source stack now matches the Raspberry Vanilla Android 13 RPi4 manifest (including V4L2 instance `IComponentStore/v4l2`);
- verified FFmpeg HEVC V4L2 Request support and the upstream V4L2 seccomp contract;
- exact 64-bit V4L2 service plus FFmpeg HEVC service metadata/VINTF validation;
- H.264-only V4L2 store and HEVC-only reduced FFmpeg store for the reduced-build path;
- canonical vendor-root payload layout with DT_NEEDED closure and ambiguity checks;
- upstream FFmpeg codec registry preserved; PiTV AVC registry is merged without replacing the target registry;
- base, extension and FFmpeg seccomp policies required;
- payload checksum, inventory, manifest, symlink, size and path-safety gates;
- donor extraction supports raw/sparse/partitioned/dynamic-super images with bounded decompression;
- reduced-module build never runs repo init/sync and restores every Android source directory it temporarily replaces;
- rollback-safe staging, preflight, free-space check, exact active vendor-image backup/activation/rollback;
- no forced `waydroid init -f` during overlay activation or rollback;
- RPi4, Android 13, /dev/video*, /dev/media*, Codec2 service and runtime-property acceptance;
- FFmpeg HEVC Request API runtime property is explicitly enabled and verified;
- CI/static self-tests green at the current branch tip.

## External gate before physical install
1. Produce the actual ARM64 payload from the pinned sources in an existing compatible Android 13 build tree, or supply a compatible Android 13 RPi4 donor image.
2. Run the dependency audit against the exact PiTV Waydroid system/vendor on the Raspberry Pi.
3. Install the staged overlay only after those checks pass.
4. Validate SmartTube H.264/HEVC playback, CPU load, A/V sync, reboot/session recovery and rollback.

The previously published KonstaKANG Android 13 RPi4 builds explicitly documented H.264 V4L2 Codec2 plus FFmpeg HEVC `hevc_v4l2request`, but the Android 13 download is discontinued. The experiment therefore does not depend on that donor being available and keeps the pinned reduced-source build as the reproducible path.

A full Android image build is not part of this experiment path.
