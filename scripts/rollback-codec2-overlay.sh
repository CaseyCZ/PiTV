#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
STATE=/var/lib/pitv/codec2-experiment
mkdir -p "$STATE"
BACKUP="${1:-}"
if [ -z "$BACKUP" ] && [ -f "$STATE/last-backup" ]; then BACKUP="$(cat "$STATE/last-backup")"; fi
BACKUP="$(readlink -f "$BACKUP" 2>/dev/null || true)"
case "$BACKUP/" in "$STATE/backups/"*) ;; *) echo "backup must be inside $STATE/backups" >&2; exit 3;; esac
[ -n "$BACKUP" ] && [ -s "$BACKUP/system.img" ] && [ -s "$BACKUP/vendor.img" ] || {
  echo "valid backup not found" >&2; exit 3;
}
(cd "$BACKUP" && sha256sum -c SHA256SUMS)
[ -s "$BACKUP/vendor.path" ] || { echo "backup vendor path missing" >&2; exit 3; }
VENDOR="$(cat "$BACKUP/vendor.path")"
case "$VENDOR" in /etc/waydroid-extra/images/vendor.img|/var/lib/waydroid/images/vendor.img|/usr/share/waydroid-extra/images/vendor.img) ;; *) echo "unsafe backup vendor path" >&2; exit 3;; esac
systemctl stop pitv-android-warm.service >/dev/null 2>&1 || true
timeout 20s waydroid session stop >/dev/null 2>&1 || true
timeout 20s waydroid container stop >/dev/null 2>&1 || true
systemctl stop waydroid-container.service >/dev/null 2>&1 || true
cp --reflink=auto --sparse=always "$BACKUP/vendor.img" "$VENDOR"
cmp -s "$BACKUP/vendor.img" "$VENDOR" || { echo "restored vendor image mismatch" >&2; exit 4; }
if [ -x /usr/local/libexec/pitv-waydroid-device-patch ]; then
  /usr/local/libexec/pitv-waydroid-device-patch --remove || true
elif command -v pitv-waydroid-device-patch >/dev/null 2>&1; then
  pitv-waydroid-device-patch --remove || true
fi
systemctl start waydroid-container.service
systemctl start pitv-android-warm.service >/dev/null 2>&1 || true
rm -f "$STATE/active-stage" "$STATE/active-vendor.sha256" "$STATE/active-vendor-path"
printf '%s\n' "$BACKUP" >"$STATE/last-rollback"
echo "Codec2 overlay rolled back: $BACKUP"
