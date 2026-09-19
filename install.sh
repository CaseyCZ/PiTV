#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Spusť instalaci přes: sudo ./install.sh"
  exit 1
fi

echo "== PiTV v1.4.15 installer =="

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
  labwc wtype wlrctl cec-utils v4l-utils \
  dbus-user-session pipewire pipewire-pulse wireplumber flatpak \
  fonts-dejavu-core \
  iproute2 sudo alsa-utils openssh-server \
  aapt apktool

# PiTV's on-screen Wi-Fi UI uses nmcli. Ubuntu Server boots the cloud-init
# network through networkd first; after NetworkManager is installed, a later
# Netplan override deliberately hands the same persistent Netplan definitions
# to NetworkManager. Netplan supports this renderer switch and merges later
# YAML files over earlier cloud-init files.
apt-get install -y network-manager

cat >/etc/netplan/90-pitv-network-manager.yaml <<'EOF'
network:
  version: 2
  renderer: NetworkManager
EOF
chmod 0600 /etc/netplan/90-pitv-network-manager.yaml
systemctl enable --now NetworkManager.service
netplan generate
netplan apply

# Remote administration is a supported PiTV recovery path.
systemctl enable --now ssh.service

# Once NetworkManager owns the configured interfaces, the old networkd
# wait-online gate must not delay TV startup. Do not disable networkd itself.
systemctl disable systemd-networkd-wait-online.service >/dev/null 2>&1 || true
systemctl mask systemd-networkd-wait-online.service >/dev/null 2>&1 || true

if ! id pitv >/dev/null 2>&1; then
  adduser --disabled-password --gecos "PiTV" pitv
fi

for g in video render input audio tty; do
  getent group "$g" >/dev/null && usermod -aG "$g" pitv || true
done

install -d -m 0755 /opt/pitv /etc/pitv/apps.d /etc/pitv/store
install -d -m 0775 -o pitv -g pitv /var/lib/pitv /var/lib/pitv/apks /var/lib/pitv/backups
install -d -m 0775 -o pitv -g pitv /home/pitv/PiTV /home/pitv/PiTV/APKs

# Persistent user/media data. These paths are never replaced by a PiTV update.
# The shared Media tree is deliberately writable by TV apps (Kodi and Android/
# Waydroid apps after bridging) while program files stay read-only/system-owned.
install -d -m 0777 -o pitv -g pitv /srv/pitv/Media
for name in Movies TV Music Downloads USB; do
  install -d -m 0777 -o pitv -g pitv "/srv/pitv/Media/$name"
done

# Friendly path for Kodi/file pickers. Never replace a real existing folder,
# because it may already contain user data from an older installation.
if [ -L /home/pitv/PiTV/Media ]; then
  ln -sfn /srv/pitv/Media /home/pitv/PiTV/Media
elif [ ! -e /home/pitv/PiTV/Media ]; then
  ln -s /srv/pitv/Media /home/pitv/PiTV/Media
fi

# Replace only the PiTV runtime tree. User settings, Kodi, Waydroid and Media
# live outside /opt/pitv and are intentionally preserved across updates.
# Keep one previous runtime so a failed update still has a rollback copy.
rm -rf /opt/pitv/pitv.new
cp -a pitv /opt/pitv/pitv.new
rm -rf /opt/pitv/pitv.prev
if [ -d /opt/pitv/pitv ]; then
  mv /opt/pitv/pitv /opt/pitv/pitv.prev
fi
if ! mv /opt/pitv/pitv.new /opt/pitv/pitv; then
  [ -d /opt/pitv/pitv.prev ] && mv /opt/pitv/pitv.prev /opt/pitv/pitv
  exit 1
fi

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
install -m 0755 system/pitv-kodi-addon /usr/local/bin/pitv-kodi-addon
install -d -m 0755 /usr/local/libexec
install -m 0755 system/pitv-helper /usr/local/libexec/pitv-helper
install -m 0755 system/pitv-self-update /usr/local/libexec/pitv-self-update
cat >/usr/local/libexec/pitv-cec-monitor <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DEV="${1:-}"
MODE="${2:-monitor}"
[[ "$DEV" =~ ^/dev/cec[0-9]+$ ]] || exit 2
[ -c "$DEV" ] || exit 2
case "$MODE" in
  register)
    exec /usr/bin/cec-ctl -d "$DEV" --no-rc-passthrough --playback -o PiTV
    ;;
  monitor)
    exec /usr/bin/cec-ctl -d "$DEV" --monitor --show-raw
    ;;
  on)
    exec /usr/bin/cec-ctl -d "$DEV" -s --to 0 --image-view-on
    ;;
  standby)
    exec /usr/bin/cec-ctl -d "$DEV" -s --to 0 --standby
    ;;
  active)
    PA="$(/usr/bin/cec-ctl -d "$DEV" 2>/dev/null |
      sed -n 's/^[[:space:]]*Physical Address[[:space:]]*:[[:space:]]*//p' |
      head -n1 | tr -d '[:space:]')"
    [[ "$PA" =~ ^[0-9A-Fa-f]\.[0-9A-Fa-f]\.[0-9A-Fa-f]\.[0-9A-Fa-f]$ ]] || exit 4
    exec /usr/bin/cec-ctl -d "$DEV" -s --to 0 --active-source "phys-addr=$PA"
    ;;
  volup|voldown|mute)
    case "$MODE" in
      volup) UI_CMD="volume-up" ;;
      voldown) UI_CMD="volume-down" ;;
      mute) UI_CMD="mute" ;;
    esac
    /usr/bin/cec-ctl -d "$DEV" -s --to 0 --user-control-pressed "ui-cmd=$UI_CMD"
    sleep 0.05
    exec /usr/bin/cec-ctl -d "$DEV" -s --to 0 --user-control-released
    ;;
  *) exit 2 ;;
esac
EOF
chmod 0755 /usr/local/libexec/pitv-cec-monitor
install -m 0755 scripts/install-waydroid.sh /usr/local/libexec/pitv-install-waydroid

install -d -o pitv -g pitv /home/pitv/.config/pitv
install -d -o pitv -g pitv /home/pitv/.config/labwc
cp -a system/labwc/. /home/pitv/.config/labwc/
chown -R pitv:pitv /home/pitv/.config/labwc
install -m 0644 -o pitv -g pitv system/bash_profile /home/pitv/.bash_profile

# PiTV privileged boundary: power, the validated root helper, and kernel CEC.
# cec-ctl monitor mode needs CAP_NET_ADMIN; expose only the fixed cec-ctl binary
# to the dedicated local pitv account, never a shell.
cat >/etc/sudoers.d/pitv-power <<'EOF'
pitv ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/local/libexec/pitv-helper *, /usr/local/libexec/pitv-cec-monitor *
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

# Older/manual PiTV repair sessions could leave duplicate vc4-kms-v3d overlays.
# Keep the first vc4-kms-v3d line only; duplicate KMS overlays can confuse HDMI/CEC.
BOOTCFG=""
for p in /boot/firmware/config.txt /boot/config.txt; do
  [ -f "$p" ] && BOOTCFG="$p" && break
done
if [ -n "$BOOTCFG" ]; then
  awk 'BEGIN{seen=0} /^dtoverlay=vc4-kms-v3d([,].*)?$/ {if(seen++) next} {print}' "$BOOTCFG" >"$BOOTCFG.pitv"
  cat "$BOOTCFG.pitv" >"$BOOTCFG"
  rm -f "$BOOTCFG.pitv"
fi

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
