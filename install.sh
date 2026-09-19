#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Spusť instalaci přes: sudo ./install.sh"
  exit 1
fi

echo "== PiTV v1.4 installer =="

. /etc/os-release || true
case "${ID:-}" in
  ubuntu|debian) ;;
  *) echo "Upozornění: instalační skript je testovaný pro Ubuntu/Debian." ;;
esac

ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
echo "Architektura: $ARCH"

apt-get update
apt-get install -y software-properties-common
add-apt-repository -y universe >/dev/null 2>&1 || true
apt-get update
apt-get install -y \
  python3 python3-pygame \
  labwc wtype cec-utils \
  dbus-user-session \
  fonts-dejavu-core \
  iproute2 sudo alsa-utils \
  aapt apktool

# PiTV uses HDMI audio. ALSA utilities provide speaker-test.
# NetworkManager is optional: PiTV will use it only if it is already active.
apt-get install -y network-manager 2>/dev/null || true

if ! id pitv >/dev/null 2>&1; then
  adduser --disabled-password --gecos "PiTV" pitv
fi

for g in video render input audio tty; do
  getent group "$g" >/dev/null && usermod -aG "$g" pitv || true
done

install -d -m 0755 /opt/pitv /etc/pitv/apps.d /etc/pitv/store
install -d -m 0775 -o pitv -g pitv /var/lib/pitv/apks
install -d -m 0775 -o pitv -g pitv /home/pitv/PiTV/APKs

# Replace only the PiTV runtime tree. User settings live in /home/pitv/.config
# and are intentionally preserved across updates.
rm -rf /opt/pitv/pitv.new
cp -a pitv /opt/pitv/pitv.new
rm -rf /opt/pitv/pitv
mv /opt/pitv/pitv.new /opt/pitv/pitv

install -m 0644 config/config.json /etc/pitv/config.json
install -m 0644 store/catalog.json /etc/pitv/store/catalog.json
install -m 0644 store/server_catalog.json /etc/pitv/store/server_catalog.json

# /etc/pitv/apps.d is PiTV-managed. User custom launchers belong in
# ~/.config/pitv/apps.d and are preserved across updates.
rm -rf /etc/pitv/apps.d
install -d -m 0755 /etc/pitv/apps.d
cp -a config/apps.d/. /etc/pitv/apps.d/
install -m 0755 system/pitv-session /usr/local/bin/pitv-session
install -m 0755 system/pitv-waydroid-launch /usr/local/bin/pitv-waydroid-launch
install -d -m 0755 /usr/local/libexec
install -m 0755 system/pitv-helper /usr/local/libexec/pitv-helper
install -m 0755 system/pitv-self-update /usr/local/libexec/pitv-self-update
install -m 0755 scripts/install-waydroid.sh /usr/local/libexec/pitv-install-waydroid

install -d -o pitv -g pitv /home/pitv/.config/pitv
install -d -o pitv -g pitv /home/pitv/.config/labwc
cp -a system/labwc/. /home/pitv/.config/labwc/
chown -R pitv:pitv /home/pitv/.config/labwc
install -m 0644 -o pitv -g pitv system/bash_profile /home/pitv/.bash_profile

# Let PiTV perform only these two privileged TV actions.
cat >/etc/sudoers.d/pitv-power <<'EOF'
pitv ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/local/libexec/pitv-helper *
EOF
chmod 0440 /etc/sudoers.d/pitv-power

# tty1 becomes the dedicated local TV session. SSH sessions are unaffected.
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat >/etc/systemd/system/getty@tty1.service.d/pitv-autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pitv --noclear %I $TERM
Type=idle
EOF

systemctl daemon-reload
systemctl enable getty@tty1.service

echo
echo "PiTV je nainstalováno."
echo "Po restartu se na HDMI automaticky spustí PiTV."
echo
echo "Test bez restartu (z lokální tty): sudo systemctl restart getty@tty1"
echo "SSH zůstává normálně dostupné."
echo
echo "TV aplikace instaluj z PiTV Store; Homebridge, Tailscale, Docker a ATVLoadly ze Server Store."
echo
echo "Pak restartuj:"
echo "  sudo reboot"
