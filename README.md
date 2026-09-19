<p align="center">
  <img src="assets/pitv-header.svg" alt="PiTV by CaseyCZ" width="100%" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/CZ-%C4%8Ce%C5%A1tina-38BDF8?style=for-the-badge&labelColor=0284C7" alt="Čeština" />
  <a href="README_EN.md"><img src="https://img.shields.io/badge/EN-English-172033?style=for-the-badge&labelColor=111827" alt="English" /></a>
</p>

<p align="center">
  Lehký TV launcher pro <strong>Raspberry Pi 4</strong>, který kombinuje vlastní TV rozhraní, aplikace a 24/7 serverové služby na jednom zařízení.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/VERZE-v1.3.0-38BDF8?style=for-the-badge&labelColor=0284C7" alt="PiTV verze 1.3.0" />
</p>

<p align="center">
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/PiTV-Instalace-38BDF8?style=for-the-badge&labelColor=0284C7&logo=raspberrypi&logoColor=white" alt="Instalace PiTV" /></a>
</p>

## O projektu

**PiTV** je vlastní TV prostředí pro Raspberry Pi 4 postavené nad **Ubuntu Server 24.04 ARM64**. Raspberry zůstává plnohodnotný 24/7 server, zatímco HDMI výstup nabízí přehledné rozhraní ovládané televizním ovladačem.

Cílem je spojit TV aplikace, Android aplikace, systémová nastavení a serverové služby do jednoho rozhraní bez nutnosti instalovat plný desktop typu GNOME.

## Hlavní funkce

- 📺 vlastní fullscreen TV launcher nad lehkým **labwc / Wayland**
- 🎨 témata **PiTV Apple Dark** a **PiTV Apple Light**
- 🎮 ovládání přes **HDMI-CEC** — šipky, OK, Back, Home, power, volume a mute
- 💤 vlastní spořič s hodinami, černou obrazovkou a volitelným CEC standby
- 🔊 HDMI audio pro Raspberry Pi 4
- 📡 Wi-Fi a síťové nastavení přímo z TV
- 📦 **PiTV Store** pro TV aplikace
- 🖥️ **Server Store** pro služby běžící 24/7 na pozadí
- 🤖 **Waydroid + Google Play** pro Android TV aplikace
- ⬆️ aktualizace PiTV, katalogů, Linux aplikací a Ubuntu přímo z TV
- 🌡️ systémový přehled — teplota, RAM, disk, uptime, kernel, síť a Tailscale
- 🔄 self-update se zachováním uživatelského nastavení

## PiTV Flasher

<p>
  <a href="FLASHER.md"><img src="https://img.shields.io/badge/PiTV%20Flasher-Automatick%C3%A1%20SD%20instalace-38BDF8?style=for-the-badge&labelColor=0284C7&logo=raspberrypi&logoColor=white" alt="PiTV Flasher" /></a>
</p>

Pro nejjednodušší instalaci lze použít **PiTV Flasher** pro Windows, Linux a macOS. Připojíš microSD kartu, vybereš ji, zadáš Wi-Fi a Flasher připraví **Ubuntu Server + automatickou první instalaci PiTV**. Podrobnosti jsou v **[FLASHER.md](FLASHER.md)**.

> PiTV Flasher je zatím **beta** a skutečný zápis SD karty na jednotlivých hostitelských systémech ještě musí projít fyzickým testem.

## Instalace

<p>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/N%C3%A1vod-Kompletn%C3%AD%20instalace-38BDF8?style=for-the-badge&labelColor=0284C7&logo=raspberrypi&logoColor=white" alt="Kompletní návod instalace PiTV" /></a>
</p>

Kompletní postup od prázdné microSD přes Raspberry Pi Imager, Wi-Fi a SSH až po první spuštění PiTV je v **[INSTALL.md](INSTALL.md)**.

Rychlá instalace na připraveném **Raspberry Pi 4 + Ubuntu Server 24.04 ARM64**:

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
sudo reboot
```

Po restartu se PiTV spustí automaticky:

```text
Ubuntu Server
└── tty1 autologin
    └── labwc / Wayland
        └── PiTV
```

SSH a serverové služby zůstávají dostupné i při vypnuté nebo uspáné TV.

## PiTV Store

Aplikace se instalují přímo z TV přes **Nastavení → Aplikace → PiTV Store**.

- 📺 **Kodi** — Ubuntu APT
- ▶️ **SmartTube** — oficiální ARM64 GitHub release
- 🎬 **Stremio** — oficiální Android TV ARM64 APK
- ▶️ **YouTube** — Google Play ve Waydroidu
- 🎵 **Spotify** — Google Play ve Waydroidu
- 🎞️ **Plex** — Google Play ve Waydroidu

PiTV u přímých APK kontroluje očekávané package ID před instalací.

## Server Store

**Nastavení → Server Store** umožňuje instalovat služby, které běží nezávisle na TV rozhraní.

- 🏠 **Homebridge** — oficiální repository, web UI na portu 8581
- 🔐 **Tailscale** — VPN / vzdálený přístup
- 🐳 **Docker Engine** — oficiální Docker repository
- 📲 **ATVLoadly** — Docker container, web UI na portu 5533

Serverové služby zůstávají spuštěné i při vypnuté TV nebo aktivním spořiči PiTV.

## Android / APK

Waydroid je volitelný — PiTV funguje i bez něj jako čistý Linux TV launcher.

Instalace přímo z TV:

**Nastavení → Android / APK → Waydroid + Google Play → Instalovat**

Vlastní APK lze vložit do:

```text
/var/lib/pitv/apks/
~/PiTV/APKs/
```

PiTV přes `aapt` načte package name, název aplikace, launchable activity, SDK a TV / Leanback informace.

## Ovládání

TV ovladač komunikuje s PiTV přes HDMI-CEC.

| Tlačítko | Akce |
|---|---|
| Šipky | navigace |
| OK / Enter | potvrzení |
| Back | zpět |
| Home / Menu | návrat do PiTV |
| Volume ± | TV / receiver |
| Mute | ztlumení |

PiTV používá jeden persistentní CEC klient pro příjem tlačítek i odesílání příkazů.

## Vzhled

PiTV používá stejný layout ve všech hlavních sekcích — Home, Store, Server Store, Nastavení, Aktualizace, Android / APK i HDMI / CEC.

- **PiTV Apple Dark** — tmavé glass panely, modrý focus a hero karty
- **PiTV Apple Light** — světlé čisté rozhraní se stejným ovládáním

Přepnutí vzhledu: **Nastavení → Vzhled**.

## Aktualizace

V **Nastavení → Aktualizace** lze:

- zkontrolovat novou verzi PiTV
- aktualizovat PiTV
- aktualizovat PiTV Store a Server Store katalog
- aktualizovat Linux Store aplikace
- aktualizovat Ubuntu balíčky
- restartovat pouze PiTV UI

Uživatelské nastavení v `/home/pitv/.config/pitv` zůstává při self-update zachované.

## Testování

PiTV má dvě úrovně GitHub Actions testů.

**PiTV Check** automaticky kontroluje Python, shell, JSON katalogy, oba motivy a render všech obrazovek.

**PiTV Online Smoke** ověřuje kompletní instalaci a spuštění na Ubuntu 24.04 **x64 i ARM64**, včetně Kodi, self-update, uninstall, Homebridge, Tailscale, Docker, ATVLoadly a Android APK zdrojů.

Poslední kompletní online test nového samostatného repozitáře skončil **PASS**.

> Fyzický Raspberry Pi 4 je stále potřeba pro finální ověření HDMI/KMS, konkrétní TV přes CEC, HDMI audio, hardwarovou akceleraci Kodi a Waydroid GPU/kernel kompatibilitu.

## Odkazy

<p>
  <a href="AUDIT.md"><img src="https://img.shields.io/badge/PiTV-Audit-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Audit" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/PiTV-Changelog-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Changelog" /></a>
  <a href="SECURITY.md"><img src="https://img.shields.io/badge/PiTV-Security-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Security" /></a>
</p>

## Podpora

<p align="center">
  <a href="https://www.buymeacoffee.com/caseycz"><img src="https://img.shields.io/badge/Podpo%C5%99it%20CaseyCZ-Buy%20Me%20a%20Coffee-38BDF8?style=for-the-badge&labelColor=0284C7&logo=buymeacoffee&logoColor=white" alt="Podpořit CaseyCZ" /></a>
</p>

<p align="center">
  <a href="https://www.buymeacoffee.com/caseycz"><img src="https://caseycz.github.io/support-qr.svg" width="150" alt="QR kód Buy Me a Coffee CaseyCZ" /></a><br>
  <sub>Naskenuj QR kód nebo klikni na tlačítko.</sub>
</p>

<p align="center">
  <a href="https://caseycz.github.io/"><img src="https://img.shields.io/badge/CaseyCZ%20Website-Otev%C5%99%C3%ADt-172033?style=flat-square&labelColor=111827" alt="CaseyCZ Website" /></a>
</p>
