#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

step() {
  printf '\n== %s ==\n' "$1"
}

fail() {
  printf '\nCHYBA: %s\n' "$1" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || fail "Chybí příkaz: $1"
}

find_imager() {
  if command -v rpi-imager >/dev/null 2>&1; then
    command -v rpi-imager
    return
  fi
  if command -v rpi-imager-cli >/dev/null 2>&1; then
    command -v rpi-imager-cli
    return
  fi

  if [[ "$(uname -s)" == "Darwin" ]]; then
    local app="/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager"
    if [[ -x "$app" ]]; then
      printf '%s\n' "$app"
      return
    fi
    if command -v brew >/dev/null 2>&1; then
      step "Instaluji oficiální Raspberry Pi Imager"
      brew install --cask raspberry-pi-imager
      [[ -x "$app" ]] && { printf '%s\n' "$app"; return; }
    fi
    fail "Raspberry Pi Imager nebyl nalezen. Nainstaluj ho z https://www.raspberrypi.com/software/"
  fi

  if [[ "$(uname -s)" == "Linux" ]]; then
    need curl
    local arch url tmp
    case "$(uname -m)" in
      x86_64) arch="amd64" ;;
      aarch64|arm64) arch="arm64" ;;
      *) fail "Automatická instalace Raspberry Pi Imager CLI nepodporuje tuto architekturu." ;;
    esac

    step "Instaluji oficiální Raspberry Pi Imager CLI"
    url="$(curl -fsSL https://api.github.com/repos/raspberrypi/rpi-imager/releases/latest \
      | grep -oE '"browser_download_url":[[:space:]]*"[^"]*rpi-imager-cli_[^"]*-1_'"$arch"'\.deb"' \
      | head -n1 | cut -d'"' -f4)"
    [[ -n "$url" ]] || fail "Nelze najít aktuální Raspberry Pi Imager CLI balíček."
    tmp="$(mktemp --suffix=.deb)"
    curl -fL "$url" -o "$tmp"
    sudo apt-get update
    sudo apt-get install -y "$tmp"
    rm -f "$tmp"

    if command -v rpi-imager-cli >/dev/null 2>&1; then
      command -v rpi-imager-cli
      return
    fi
    if command -v rpi-imager >/dev/null 2>&1; then
      command -v rpi-imager
      return
    fi
  fi

  fail "Raspberry Pi Imager nebyl nalezen."
}

ensure_ssh_key() {
  if ! command -v ssh-keygen >/dev/null 2>&1; then
    if [[ "$(uname -s)" == "Linux" ]]; then
      sudo apt-get update
      sudo apt-get install -y openssh-client
    else
      fail "Chybí ssh-keygen."
    fi
  fi

  mkdir -p "$HOME/.ssh"
  KEY_PATH="$HOME/.ssh/pitv_ed25519"
  if [[ ! -f "$KEY_PATH" ]]; then
    step "Vytvářím recovery SSH klíč"
    ssh-keygen -q -t ed25519 -f "$KEY_PATH" -N "" -C "pitv-flasher"
  fi
  PUB_KEY="$(cat "$KEY_PATH.pub")"
}

get_ubuntu_image() {
  step "Hledám aktuální Ubuntu Server 24.04 LTS ARM64 image"
  UBUNTU_BASE="https://cdimage.ubuntu.com/releases/24.04/release"
  local line
  line="$(curl -fsSL "$UBUNTU_BASE/SHA256SUMS" \
    | grep 'preinstalled-server-arm64+raspi\.img\.xz$' \
    | head -n1)"
  [[ -n "$line" ]] || fail "V Ubuntu SHA256SUMS nebyl nalezen Raspberry Pi Server ARM64 image."
  IMAGE_SHA="$(printf '%s\n' "$line" | awk '{print $1}')"
  IMAGE_FILE="$(printf '%s\n' "$line" | awk '{print $2}' | sed 's/^\*//')"
  IMAGE_URL="$UBUNTU_BASE/$IMAGE_FILE"
}

list_devices_linux() {
  local root_src root_parent
  root_src="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
  root_parent="$(lsblk -no PKNAME "$root_src" 2>/dev/null | head -n1 || true)"

  DEVICES=()
  while read -r name size tran rm type; do
    [[ "$type" == "disk" ]] || continue
    [[ "$tran" == "usb" || "$rm" == "1" ]] || continue
    [[ -n "$root_parent" && "$name" == "/dev/$root_parent" ]] && continue
    DEVICES+=("$name")
    printf '  [%d] %s  %s  %s\n' "${#DEVICES[@]}" "$name" "$size" "${tran:-removable}"
  done < <(lsblk -dpno NAME,SIZE,TRAN,RM,TYPE)
}

list_devices_macos() {
  DEVICES=()
  while read -r dev; do
    [[ -n "$dev" ]] || continue
    DEVICES+=("$dev")
    local size
    size="$(diskutil info "$dev" | awk -F': *' '/Disk Size/ {print $2; exit}')"
    printf '  [%d] %s  %s\n' "${#DEVICES[@]}" "$dev" "${size:-external disk}"
  done < <(diskutil list external physical | awk '/^\/dev\/disk/ {print $1}')
}

select_device() {
  step "Dostupné výměnné disky"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    list_devices_macos
  else
    list_devices_linux
  fi

  ((${#DEVICES[@]} > 0)) || fail "Nebyla nalezena SD karta ani výměnný USB disk."

  local choice
  read -r -p "Vyber číslo SD karty: " choice
  [[ "$choice" =~ ^[0-9]+$ ]] || fail "Neplatná volba."
  (( choice >= 1 && choice <= ${#DEVICES[@]} )) || fail "Neplatná volba."
  TARGET_DEVICE="${DEVICES[$((choice-1))]}"

  printf '\nPOZOR: CELÝ DISK %s BUDE SMAZÁN.\n' "$TARGET_DEVICE"
  local expected confirm
  expected="SMAZAT $TARGET_DEVICE"
  read -r -p "Pro potvrzení napiš přesně: $expected : " confirm
  [[ "$confirm" == "$expected" ]] || fail "Zápis zrušen."
}

yaml_quote() {
  local v="${1//\'/\'\'}"
  printf "'%s'" "$v"
}

prepare_boot_linux() {
  sudo partprobe "$TARGET_DEVICE" 2>/dev/null || true
  sleep 2
  local part
  part="$(lsblk -lnpo NAME,LABEL,FSTYPE "$TARGET_DEVICE" \
    | awk '$2=="system-boot" || $3 ~ /vfat|fat/ {print $1; exit}')"
  [[ -n "$part" ]] || fail "Nelze najít system-boot partition."
  BOOT_MOUNT="$(mktemp -d)"
  sudo mount "$part" "$BOOT_MOUNT"
  BOOT_NEEDS_UNMOUNT=1
}

prepare_boot_macos() {
  diskutil mountDisk "$TARGET_DEVICE" >/dev/null
  sleep 2
  local part="${TARGET_DEVICE}s1"
  BOOT_MOUNT="$(diskutil info "$part" | awk -F': *' '/Mount Point/ {print $2; exit}')"
  [[ -d "$BOOT_MOUNT" ]] || {
    BOOT_MOUNT="/Volumes/system-boot"
  }
  [[ -d "$BOOT_MOUNT" ]] || fail "Nelze najít připojenou system-boot partition."
  BOOT_NEEDS_UNMOUNT=0
}

cleanup() {
  if [[ "${BOOT_NEEDS_UNMOUNT:-0}" == "1" && -n "${BOOT_MOUNT:-}" ]]; then
    sudo umount "$BOOT_MOUNT" 2>/dev/null || true
    rmdir "$BOOT_MOUNT" 2>/dev/null || true
  elif [[ "$(uname -s)" == "Darwin" && -n "${TARGET_DEVICE:-}" ]]; then
    diskutil unmountDisk "$TARGET_DEVICE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

printf '\nPiTV Flasher 0.1 (Linux / macOS)\n'
printf 'Ubuntu Server 24.04 LTS ARM64 + automatická instalace PiTV\n\n'

if (( DRY_RUN )); then
  printf 'DRY RUN OK\n'
  exit 0
fi

need curl
IMAGER="$(find_imager)"
ensure_ssh_key
get_ubuntu_image
select_device

step "Nastavení první instalace"
read -r -p "Wi-Fi SSID: " WIFI_SSID
[[ -n "$WIFI_SSID" ]] || fail "Wi-Fi SSID nesmí být prázdné."
read -r -s -p "Wi-Fi heslo: " WIFI_PASSWORD
printf '\n'
read -r -p "Hostname [pitv]: " HOSTNAME_VALUE
HOSTNAME_VALUE="${HOSTNAME_VALUE:-pitv}"
[[ "$HOSTNAME_VALUE" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$ ]] || fail "Neplatný hostname."
read -r -p "Recovery SSH uživatel [pitvadmin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-pitvadmin}"
[[ "$ADMIN_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fail "Neplatné Linux uživatelské jméno."

step "Zapisuji oficiální Ubuntu image"
printf '%s\nSHA256: %s\n' "$IMAGE_URL" "$IMAGE_SHA"

if [[ "$(uname -s)" == "Darwin" ]]; then
  diskutil unmountDisk "$TARGET_DEVICE" >/dev/null 2>&1 || true
else
  while read -r p; do sudo umount "$p" 2>/dev/null || true; done < <(lsblk -lnpo NAME "$TARGET_DEVICE" | tail -n +2)
fi

sudo "$IMAGER" --cli --sha256 "$IMAGE_SHA" "$IMAGE_URL" "$TARGET_DEVICE"

step "Připravuji Wi-Fi, SSH a automatickou instalaci PiTV"
if [[ "$(uname -s)" == "Darwin" ]]; then
  prepare_boot_macos
else
  prepare_boot_linux
fi

tmpdir="$(mktemp -d)"
network_file="$tmpdir/network-config"
userdata_file="$tmpdir/user-data"

cat >"$network_file" <<EOF
version: 2
wifis:
  wlan0:
    dhcp4: true
    optional: true
    access-points:
      $(yaml_quote "$WIFI_SSID"):
        password: $(yaml_quote "$WIFI_PASSWORD")
EOF

cat >"$userdata_file" <<EOF
#cloud-config
hostname: $HOSTNAME_VALUE
manage_etc_hosts: true
ssh_pwauth: false
disable_root: true

users:
  - default
  - name: $ADMIN_USER
    gecos: PiTV recovery administrator
    groups: [adm, sudo]
    shell: /bin/bash
    lock_passwd: true
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - $PUB_KEY

package_update: true
packages:
  - git
  - ca-certificates

write_files:
  - path: /usr/local/sbin/pitv-firstboot.sh
    owner: root:root
    permissions: '0755'
    content: |
      #!/usr/bin/env bash
      set -euo pipefail
      exec > >(tee -a /var/log/pitv-firstboot.log) 2>&1
      echo "== PiTV first boot installer =="
      rm -rf /opt/PiTV-src
      git clone --depth 1 https://github.com/CaseyCZ/PiTV.git /opt/PiTV-src
      cd /opt/PiTV-src
      ./install.sh
      mkdir -p /var/lib/pitv
      touch /var/lib/pitv/firstboot-complete
      rm -f /boot/firmware/user-data /boot/firmware/network-config || true
      echo "== PiTV first boot complete =="

runcmd:
  - [bash, /usr/local/sbin/pitv-firstboot.sh]

power_state:
  delay: now
  mode: reboot
  message: "PiTV installation complete - rebooting"
  condition: true
EOF

sudo cp "$userdata_file" "$BOOT_MOUNT/user-data"
sudo cp "$network_file" "$BOOT_MOUNT/network-config"
sync
rm -rf "$tmpdir"
WIFI_PASSWORD=""

cleanup
trap - EXIT

step "Hotovo"
printf 'SD karta je připravena.\n\n'
printf '1. Vlož ji do Raspberry Pi 4, připoj HDMI a napájení.\n'
printf '2. První boot může trvat přibližně 10-30 minut.\n'
printf '3. Ubuntu se připojí na Wi-Fi, samo nainstaluje PiTV a jednou se restartuje.\n'
printf '4. Potom se má PiTV automaticky zobrazit na TV.\n\n'
printf 'Recovery SSH:\n  ssh -i "%s" %s@%s.local\n\n' "$KEY_PATH" "$ADMIN_USER" "$HOSTNAME_VALUE"
printf 'Log první instalace: /var/log/pitv-firstboot.log\n'
