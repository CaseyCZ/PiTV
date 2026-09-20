#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Spusť instalaci přes: sudo ./install.sh"
  exit 1
fi

echo "== PiTV v1.5.0 TV Shell installer =="

. /etc/os-release || true
case "${ID:-}" in
  ubuntu|debian) ;;
  *) echo "Upozornění: instalační skript je testovaný pro Ubuntu/Debian." ;;
esac

ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
echo "Architektura: $ARCH"

# Ubuntu can start unattended-upgrades in the background shortly after boot.
# Never fail a PiTV update just because APT/DPKG is temporarily busy. apt-get waits
# safely for the existing package transaction to finish instead of killing it or
# deleting package-manager lock files.
APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
apt_run() {
  apt-get -o "DPkg::Lock::Timeout=$APT_LOCK_TIMEOUT" "$@"
}

apt_run update
apt_run install -y software-properties-common
add-apt-repository -y --no-update universe >/dev/null 2>&1 || true
apt_run update
apt_run install -y \
  python3 python3-pygame python3-evdev \
  labwc cage wtype cec-utils v4l-utils \
  dbus-user-session pipewire pipewire-pulse wireplumber pulseaudio-utils flatpak \
  fonts-dejavu-core \
  iproute2 sudo alsa-utils openssh-server util-linux \
  aapt apktool

# PiTV's on-screen Wi-Fi UI uses nmcli. Ubuntu Server boots the cloud-init
# network through networkd first; after NetworkManager is installed, a later
# Netplan override deliberately hands the same persistent Netplan definitions
# to NetworkManager. Netplan supports this renderer switch and merges later
# YAML files over earlier cloud-init files.
apt_run install -y network-manager

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

# Detect a live pre-1.5 TV session before replacing its boot mechanism.
# Never stop it from inside the installer: this script may itself be a child of
# that session during an in-UI self-update.
PITV_LEGACY_LIVE=0
if systemctl is-active --quiet getty@tty1.service &&
   pgrep -u pitv -f '/opt/pitv/pitv/pitv.py' >/dev/null 2>&1; then
  PITV_LEGACY_LIVE=1
fi

# Keep the pitv per-user systemd manager alive independently of the visual
# shell. D-Bus, PipeWire and WirePlumber then survive a TV-shell recovery.
loginctl enable-linger pitv >/dev/null 2>&1 || true

install -d -m 0755 /opt/pitv /etc/pitv/apps.d /etc/pitv/store /etc/pitv/kodi
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
install -m 0644 system/kodi/appliance.xml /etc/pitv/kodi-appliance.xml

# /etc/pitv/apps.d is PiTV-managed. User custom launchers belong in
# ~/.config/pitv/apps.d and are preserved across updates.
rm -rf /etc/pitv/apps.d
install -d -m 0755 /etc/pitv/apps.d
cp -a config/apps.d/. /etc/pitv/apps.d/
install -m 0755 system/pitv-session /usr/local/bin/pitv-session
install -m 0755 system/pitv-session-run /usr/local/bin/pitv-session-run
install -m 0755 system/pitv-launcher-run /usr/local/bin/pitv-launcher-run
install -m 0755 system/pitv-waydroid-launch /usr/local/bin/pitv-waydroid-launch
install -m 0755 system/pitv-kodi-launch /usr/local/bin/pitv-kodi-launch
install -m 0755 system/pitv-kodi-addon /usr/local/bin/pitv-kodi-addon
install -d -m 0755 /usr/local/libexec
install -m 0755 system/pitv-helper /usr/local/libexec/pitv-helper
install -m 0755 system/pitv-self-update /usr/local/libexec/pitv-self-update
install -m 0755 system/pitv-android-warm /usr/local/libexec/pitv-android-warm
install -m 0755 system/pitv-inputd /usr/local/libexec/pitv-inputd
install -m 0755 system/pitv-cec-control /usr/local/libexec/pitv-cec-control
install -m 0755 system/pitv-global-action /usr/local/libexec/pitv-global-action
install -m 0644 system/pitv.target /etc/systemd/system/pitv.target
install -m 0644 system/pitv-shell.service /etc/systemd/system/pitv-shell.service
install -m 0644 system/pitv-android-warm.service /etc/systemd/system/pitv-android-warm.service
install -m 0644 system/pitv-inputd.service /etc/systemd/system/pitv-inputd.service

# The virtual PiTV TV Remote uses Linux uinput. Load it during every boot
# before pitv-inputd and load it now as well for an in-place upgrade.
install -d -m 0755 /etc/modules-load.d
printf '%s\n' "uinput" >/etc/modules-load.d/pitv-uinput.conf
modprobe uinput >/dev/null 2>&1 || true

# Preserve an existing user's CEC choice across upgrades. The service stays
# enabled as part of the appliance target; a persistent condition marker keeps
# it intentionally inactive when Settings says HDMI-CEC is off.
if [ -f /home/pitv/.config/pitv/config.json ] &&
   /usr/bin/python3 - /home/pitv/.config/pitv/config.json <<'PYCEC'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    raise SystemExit(0 if data.get("cec_enabled", True) is False else 1)
except Exception:
    raise SystemExit(1)
PYCEC
then
  touch /var/lib/pitv/cec-disabled
else
  rm -f /var/lib/pitv/cec-disabled
fi

# Kodi's upstream Linux default disables the DRM PRIME decoder. Physical Pi 4
# testing proved that PiTV needs DRM PRIME enabled for smooth playback. Apply
# the Kodi-supported appliance defaults on every PiTV update when Kodi already
# exists; future Store installs do the same inside pitv-helper apt-install.
if command -v kodi >/dev/null 2>&1; then
  # Existing PiTV devices may already have Kodi but not kodi-send (confirmed
  # on the physical Pi 4). Bring upgraded devices to the same contract as a
  # fresh Store install before the next physical regression test.
  apt_run install -y kodi-eventclients-kodi-send
  echo '{}' | /usr/local/libexec/pitv-helper kodi-appliance-defaults
fi
# PiTV 1.5 input is owned only by pitv-inputd. Remove the old 1.4 monitor
# helper during upgrades; CEC output uses the static output-only helper.
rm -f /usr/local/libexec/pitv-cec-monitor
install -m 0755 scripts/install-waydroid.sh /usr/local/libexec/pitv-install-waydroid

install -d -o pitv -g pitv /home/pitv/.config/pitv
install -d -o pitv -g pitv /home/pitv/.config/labwc
cp -a system/labwc/. /home/pitv/.config/labwc/
chown -R pitv:pitv /home/pitv/.config/labwc

# PiTV 1.5 is a supervised TV appliance service, not a tty autologin shell.
# Remove the old boot hook on upgrades so a manual console login can never
# start a second compositor/session.
rm -f /home/pitv/.bash_profile

# PiTV privileged boundary: power, the validated root helper, and the fixed
# output-only CEC helper. Remote input itself runs as pitv-inputd system service
# and is never started through sudo from the GUI.
cat >/etc/sudoers.d/pitv-power <<'EOF'
pitv ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/local/libexec/pitv-helper *, /usr/local/libexec/pitv-cec-control *
EOF
chmod 0440 /etc/sudoers.d/pitv-power

# LibreELEC-style appliance boot:
# - pitv.target is the TV-oriented default target above multi-user.target;
# - pitv-shell.service owns tty1/Wayland and is supervised by systemd;
# - no getty/autologin/.bash_profile trampoline is involved.
rm -f /etc/systemd/system/getty@tty1.service.d/pitv-autologin.conf
rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true

# Prevent the generic console getty from racing the TV shell for tty1 on the
# next boot. This does not affect SSH or any server/background service.
systemctl mask getty@tty1.service >/dev/null 2>&1 || true

# Compatibility/recovery command retained for existing documentation and SSH
# habits: restarting "pitv-launcher" now restarts the whole supervised TV shell,
# equivalent to LibreELEC restarting its mediacenter service.
cat >/etc/systemd/system/pitv-launcher.service <<'EOF'
[Unit]
Description=PiTV TV-shell restart helper
After=pitv-shell.service

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl restart pitv-shell.service
EOF

systemctl daemon-reload
systemctl disable pitv-launcher.service >/dev/null 2>&1 || true
systemctl enable pitv-inputd.service pitv-shell.service pitv-android-warm.service
systemctl set-default pitv.target

# A 1.4.x in-UI updater is still running inside getty@tty1 at this point.
# Queue the hand-over in an independent transient systemd unit so the installer
# can return successfully before the old session is stopped. Starting the new
# shell automatically stops the conflicting getty and takes ownership of tty1.
if [ "$PITV_LEGACY_LIVE" -eq 1 ]; then
  systemd-run --quiet --collect     --unit="pitv-shell-migration-$$"     --on-active=3s     /usr/bin/systemctl restart pitv-shell.service >/dev/null 2>&1 || true
fi

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
echo "TV shell spravuje systemd: sudo systemctl restart pitv-shell.service"
echo "SSH zůstává normálně dostupné."
echo
echo "TV aplikace instaluj z PiTV Store; Homebridge, Tailscale, Docker a ATVLoadly ze Server Store."
echo
echo "Pak restartuj:"
echo "  sudo reboot"
