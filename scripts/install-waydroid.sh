#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Použij: sudo ./scripts/install-waydroid.sh"
  exit 1
fi

OFFICIAL_BOOTSTRAP_URL="https://repo.waydro.id"
FALLBACK_BASE="https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/vendor/waydroid/noble"

apt-get update
apt-get install -y curl ca-certificates

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
  apt-get update || return 1
  apt-get install -y waydroid || return 1
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
  apt-get update

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

  apt-get install -y \
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

printf '\nWaydroid + Google Play je inicializovaný.\n'
printf 'Při prvním spuštění může Google Play vyžadovat certifikaci zařízení.\n'
printf 'PiTV Store pak může otevřít YouTube, Spotify a Plex přímo v Google Play.\n\n'
