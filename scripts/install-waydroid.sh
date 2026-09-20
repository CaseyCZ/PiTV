#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Použij: sudo ./scripts/install-waydroid.sh"
  exit 1
fi

OFFICIAL_BOOTSTRAP_URL="https://repo.waydro.id"
FALLBACK_BASE="https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/vendor/waydroid/noble"

APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
apt_run() {
  apt-get -o "DPkg::Lock::Timeout=$APT_LOCK_TIMEOUT" "$@"
}

# Raspberry Pi-specific checks before downloading images. PiTV currently
# targets Pi 4 first. A 4 KiB page-size kernel is the compatible baseline used
# by working Raspberry Pi Waydroid setups; PSI is required by Android's memory
# pressure handling. Do not rewrite boot files automatically here.
if [ "$(dpkg --print-architecture 2>/dev/null || true)" = "arm64" ]; then
  PAGE_SIZE="$(getconf PAGESIZE 2>/dev/null || true)"
  if [ -n "$PAGE_SIZE" ] && [ "$PAGE_SIZE" != "4096" ]; then
    echo "Waydroid na Raspberry Pi vyžaduje 4 KiB page-size kernel; nalezeno: $PAGE_SIZE." >&2
    echo "Změň kernel na 4 KiB variantu, restartuj a instalaci spusť znovu." >&2
    exit 3
  fi
  if [ ! -d /proc/pressure ]; then
    echo "Waydroid vyžaduje PSI (/proc/pressure), ale kernel ho teď neposkytuje." >&2
    echo "Zapni psi=1 v kernel command line, restartuj a instalaci spusť znovu." >&2
    exit 4
  fi
fi

apt_run update
apt_run install -y curl ca-certificates

TMP_DIR="$(mktemp -d /tmp/pitv-waydroid.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl_get() {
  curl --proto '=https' --tlsv1.2 --retry 3 --retry-delay 2 --connect-timeout 15 -fL "$@"
}

install_official() {
  local bootstrap="$TMP_DIR/waydroid-repo.sh"

  echo "Zkouším oficiální Waydroid repository…"
  curl_get "$OFFICIAL_BOOTSTRAP_URL" -o "$bootstrap" || return 1
  chmod 0700 "$bootstrap"
  bash "$bootstrap" || return 1
  apt_run update || return 1
  apt_run install -y waydroid || return 1
}

manifest_value() {
  local key="$1" file="$2"
  sed -n "s/^${key}=//p" "$file" | head -n 1
}

install_fallback() {
  local arch manifest sums
  arch="$(dpkg --print-architecture 2>/dev/null || true)"
  if [ "$arch" != "arm64" ]; then
    echo "PiTV fallback snapshot je určený pro Raspberry Pi / ARM64, nalezeno: ${arch:-unknown}" >&2
    return 1
  fi

  echo "Oficiální Waydroid repository není dostupné nebo instalace selhala."
  echo "Používám PiTV fallback snapshot z GitHubu…"

  rm -f /etc/apt/sources.list.d/waydroid.list
  apt_run update

  manifest="$TMP_DIR/packages.env"
  sums="$TMP_DIR/SHA256SUMS"
  curl_get "$FALLBACK_BASE/packages.env" -o "$manifest"
  curl_get "$FALLBACK_BASE/SHA256SUMS" -o "$sums"

  local libglibutil libgbinder pygbinder waydroid_pkg
  libglibutil="$(manifest_value LIBGLIBUTIL_FILE "$manifest")"
  libgbinder="$(manifest_value LIBGBINDER_FILE "$manifest")"
  pygbinder="$(manifest_value PYGBINDER_FILE "$manifest")"
  waydroid_pkg="$(manifest_value WAYDROID_FILE "$manifest")"

  for name in "$libglibutil" "$libgbinder" "$pygbinder" "$waydroid_pkg"; do
    if [ -z "$name" ] || [[ "$name" == */* ]] || [[ "$name" != *.deb ]]; then
      echo "Neplatný Waydroid fallback manifest." >&2
      return 1
    fi
    curl_get "$FALLBACK_BASE/$name" -o "$TMP_DIR/$name"
  done

  (
    cd "$TMP_DIR"
    sha256sum -c SHA256SUMS
  )

  apt_run install -y \
    "$TMP_DIR/$libglibutil" \
    "$TMP_DIR/$libgbinder" \
    "$TMP_DIR/$pygbinder" \
    "$TMP_DIR/$waydroid_pkg"
}

if [ "${PITV_WAYDROID_FORCE_FALLBACK:-0}" = "1" ]; then
  install_fallback
elif ! install_official; then
  install_fallback
fi

if ! command -v waydroid >/dev/null 2>&1; then
  echo "Instalace Waydroidu nebyla dokončena." >&2
  exit 1
fi

if [ "${PITV_WAYDROID_SKIP_INIT:-0}" = "1" ]; then
  echo "Waydroid balíčky jsou nainstalované; inicializace byla přeskočena."
  exit 0
fi

echo "Inicializuji Waydroid s GAPPS / Google Play…"
waydroid init -s GAPPS

# Official systemd integration: keep only the root container-manager daemon
# enabled. Android/LXC itself starts on demand when the pitv user opens an app.
systemctl enable --now waydroid-container.service

printf '\nWaydroid + Google Play je inicializovaný.\n'
printf 'Při prvním spuštění může Google Play vyžadovat certifikaci zařízení.\n'
printf 'PiTV Store pak může otevřít YouTube, Spotify a Plex přímo v Google Play.\n\n'
