#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Použij sudo ./uninstall.sh"; exit 1; }

rm -f /etc/systemd/system/getty@tty1.service.d/pitv-autologin.conf
rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
rm -f /etc/sudoers.d/pitv-power
rm -f /usr/local/bin/pitv-session /usr/local/bin/pitv-waydroid-launch /usr/local/bin/pitv-kodi-addon /usr/local/libexec/pitv-helper /usr/local/libexec/pitv-self-update /usr/local/libexec/pitv-install-waydroid /usr/local/libexec/pitv-cec-monitor
rm -rf /opt/pitv /etc/pitv /home/pitv/.config/labwc
rm -f /home/pitv/.bash_profile
systemctl daemon-reload
systemctl restart getty@tty1.service || true

echo "PiTV odstraněno. Uživatel 'pitv', jeho nastavení a APK data byly ponechány pro případnou reinstalaci."
