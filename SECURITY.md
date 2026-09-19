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

## Reporting a security issue

Do not publish passwords, auth keys, Tailscale credentials or other secrets in an
issue. Remove sensitive data from logs before sharing diagnostics.
