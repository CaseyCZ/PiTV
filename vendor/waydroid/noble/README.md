# PiTV Waydroid fallback snapshot

This directory is an automated fallback snapshot of the current ARM64 runtime
packages from the official Waydroid repository for Ubuntu 24.04 (Noble).

It is used only when the primary https://repo.waydro.id installation path
is unavailable.

Mirrored packages:

- libglibutil_1.0.80_arm64.deb
- libgbinder_1.1.43_arm64.deb
- python3-gbinder_1.3.1_arm64.deb
- waydroid_1.6.2_all.deb

Source: https://repo.waydro.id/dists/noble/

Updated by .github/workflows/waydroid-fallback-mirror.yml.
