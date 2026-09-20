#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Použij sudo ./uninstall.sh"; exit 1; }

# Stop the appliance units before removing their definitions.
systemctl disable --now pitv-android-warm.service >/dev/null 2>&1 || true
systemctl disable --now pitv-inputd.service >/dev/null 2>&1 || true
systemctl disable --now pitv-shell.service >/dev/null 2>&1 || true

# Only change the default target when PiTV currently owns it.
if [ "$(basename "$(readlink -f /etc/systemd/system/default.target 2>/dev/null || true)")" = "pitv.target" ]; then
  systemctl set-default multi-user.target >/dev/null 2>&1 || true
fi

systemctl unmask getty@tty1.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/pitv-launcher.service
rm -f /etc/systemd/system/pitv-shell.service
rm -f /etc/systemd/system/pitv-android-warm.service
rm -f /etc/systemd/system/pitv-inputd.service
rm -f /etc/systemd/system/pitv.target
rm -f /etc/modules-load.d/pitv-uinput.conf
rm -f /etc/systemd/system/getty@tty1.service.d/pitv-autologin.conf
rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
rm -f /etc/sudoers.d/pitv-power
rm -f /usr/local/bin/pitv-session /usr/local/bin/pitv-session-run /usr/local/bin/pitv-launcher-run /usr/local/bin/pitv-waydroid-launch /usr/local/bin/pitv-kodi-launch /usr/local/bin/pitv-kodi-addon /usr/local/libexec/pitv-helper /usr/local/libexec/pitv-self-update /usr/local/libexec/pitv-install-waydroid /usr/local/libexec/pitv-cec-monitor /usr/local/libexec/pitv-cec-control /usr/local/libexec/pitv-android-warm /usr/local/libexec/pitv-inputd /usr/local/libexec/pitv-global-action
rm -rf /opt/pitv /etc/pitv /home/pitv/.config/labwc
rm -f /home/pitv/.bash_profile
rm -f /var/lib/pitv/cec-disabled
loginctl disable-linger pitv >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl restart getty@tty1.service || true

echo "PiTV odstraněno. Uživatel 'pitv', jeho nastavení a APK data byly ponechány pro případnou reinstalaci."
