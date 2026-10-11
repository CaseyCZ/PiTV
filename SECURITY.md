# Security

PiTV is designed to run on a Raspberry Pi that may also host 24/7 server services.

## Privileged operations

The TV UI itself does not run as root. Privileged operations are routed through
`/usr/local/libexec/pitv-helper`, which exposes explicit actions and allowlists
instead of a general-purpose root shell.

Examples include:
- approved Store APT packages,
- approved Google Play package IDs,
- Wi-Fi actions,
- PiTV self-update,
- system package updates,
- Server Store installers.

## Self-update trust model

PiTV 1.3 currently downloads `Master` from this repository and runs its installer
as root. This is acceptable for the current development/testing phase, but public
release builds should move to immutable GitHub Releases with a checksum or signature.

## Waydroid fallback supply chain

Waydroid installation prefers the official `https://repo.waydro.id` repository.

For Raspberry Pi / Ubuntu 24.04 ARM64, PiTV also keeps a small fallback snapshot
under `vendor/waydroid/noble/`. The snapshot contains only the runtime packages
required by PiTV and a `SHA256SUMS` file. It is refreshed automatically from the
official Waydroid repository by GitHub Actions and verified by the regular PiTV CI.

The fallback reduces dependence on a single Waydroid package endpoint. It does not
make the full Android first-boot process completely offline: `waydroid init` still
needs access to its Android image sources unless those images are already cached.

## Reporting a security issue

Do not publish passwords, auth keys, Tailscale credentials or other secrets in an
issue. Remove sensitive data from logs before sharing diagnostics.
