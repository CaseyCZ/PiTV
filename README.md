<p align="center">
  <img src="assets/pitv-header.svg" alt="PiTV by CaseyCZ" width="100%" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/CZ-%C4%8Ce%C5%A1tina-38BDF8?style=for-the-badge&labelColor=0284C7" alt="Čeština" />
  <a href="README_EN.md"><img src="https://img.shields.io/badge/EN-English-172033?style=for-the-badge&labelColor=111827" alt="English" /></a>
</p>

<p align="center">
  Lehký TV launcher pro <strong>Raspberry Pi 4</strong>, který spojuje vlastní TV rozhraní, aplikace a 24/7 serverové služby na jednom zařízení.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/KAN%C3%81L-Alpha-38BDF8?style=for-the-badge&labelColor=0284C7" alt="PiTV Alpha" />
  <img src="https://img.shields.io/badge/STAV-Aktivn%C3%AD%20v%C3%BDvoj-FDE68A?style=for-the-badge&labelColor=92400E" alt="Aktivní vývoj" />
</p>

<p align="center">
  <a href="https://github.com/CaseyCZ/PiTV/releases/tag/alpha"><img src="https://img.shields.io/badge/St%C3%A1hnout-Nejnov%C4%9Bj%C5%A1%C3%AD%20release-38BDF8?style=for-the-badge&labelColor=0284C7&logo=github&logoColor=white" alt="Stáhnout nejnovější PiTV release" /></a>
  <a href="FLASHER.md"><img src="https://img.shields.io/badge/PiTV%20SD%20Installer-N%C3%A1vod-172033?style=for-the-badge&labelColor=111827&logo=raspberrypi&logoColor=white" alt="PiTV SD Installer" /></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/N%C3%A1vod-Ru%C4%8Dn%C3%AD%20instalace-172033?style=for-the-badge&labelColor=111827&logo=ubuntu&logoColor=white" alt="Ruční instalace" /></a>
  <a href="https://github.com/CaseyCZ/PiTV/issues"><img src="https://img.shields.io/badge/GitHub-Nahl%C3%A1sit%20probl%C3%A9m-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="Nahlásit problém" /></a>
</p>

## O projektu

**PiTV** je vlastní TV prostředí pro Raspberry Pi 4 postavené nad **Ubuntu Server 24.04 ARM64**.

Raspberry Pi zůstává plnohodnotný 24/7 server, zatímco HDMI výstup nabízí samostatné TV rozhraní ovládané klasickým televizním ovladačem přes **HDMI-CEC**.

PiTV nepoužívá plný desktop typu GNOME. Grafická část běží nad lehkým **labwc / Wayland**, takže stejné Raspberry může současně provozovat například Homebridge, Tailscale, Docker nebo další služby na pozadí.

## Hlavní funkce

- 📺 vlastní fullscreen TV launcher
- 🎨 **PiTV Apple Dark** a **PiTV Apple Light**
- 🎮 ovládání přes **HDMI-CEC**
- 🔊 HDMI audio
- 💤 spořič obrazovky, black screen a volitelný CEC standby
- 📡 Wi-Fi a základní síťová správa přímo z TV
- 📦 **PiTV Store** pro TV aplikace
- 🖥️ **Server Store** pro 24/7 služby
- 🤖 **Waydroid + Google Play** pro Android TV aplikace
- ⬆️ aktualizace PiTV, katalogů, aplikací a Ubuntu
- 🌡️ systémové informace — teplota, RAM, disk, uptime, kernel, síť a Tailscale
- 🔄 self-update se zachováním uživatelského nastavení

## Stažení

Aktuální testovací build je vždy v jediném **[PiTV Alpha Release](https://github.com/CaseyCZ/PiTV/releases/tag/alpha)**.

Pro Windows stáhni jediný instalační balík **`PiTV-SD-Installer-Windows.zip`**, rozbal ho a spusť **`Start-PiTV-SD-Installer.cmd`**. Launcher při každém spuštění zkontroluje nejnovější GitHub Release a použije aktuální installer.

Linux a macOS používají `tools/pitv-flasher.sh` přímo z repozitáře. GitHub ke každému Release automaticky přidává také Source code ZIP/TAR.GZ.

## Instalace

### PiTV SD Installer — doporučeno

Nejjednodušší způsob je připravit microSD přímo z počítače.

| Platforma | Postup |
|---|---|
| **Windows** | spusť `tools/windows/Start-PiTV-SD-Installer.cmd`, vyber kartu a klikni **VYTVOŘIT PiTV SD** |
| **Linux** | spusť `tools/pitv-flasher.sh` |
| **macOS** | spusť `tools/pitv-flasher.sh` |

Windows installer nabízí **Raspberry Pi 3 / 3B+**, **Raspberry Pi 4** a **Raspberry Pi 5**. Pi 4 je výchozí a doporučený cíl; Pi 3 a Pi 5 jsou v Alpha fázi experimentální.

Installer připraví:

- Ubuntu Server 24.04 ARM64
- Wi-Fi
- první boot
- automatické stažení PiTV
- automatickou instalaci
- restart přímo do PiTV

Podrobnosti: **[PiTV SD Installer](FLASHER.md)**

### Formátování SD karty

Windows GUI obsahuje také **NAFORMÁTOVAT SD**. Kartu kompletně vyčistí a vytvoří jeden exFAT oddíl `SDCARD` přes celou dostupnou kapacitu.

Windows PowerShell:

```powershell
.\tools\pitv-flasher.ps1 -FormatOnly
```

Linux / macOS:

```bash
./tools/pitv-flasher.sh --format-only
```

### Ruční instalace

Pokud už běží **Ubuntu Server 24.04 ARM64**:

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
sudo reboot
```

Kompletní postup od prázdné microSD je v **[INSTALL.md](INSTALL.md)**.

## PiTV Store

Aplikace se instalují přímo z TV přes **Nastavení → Aplikace → PiTV Store**.

| Aplikace | Způsob instalace |
|---|---|
| Kodi | Ubuntu APT |
| SmartTube | ARM64 GitHub release |
| Stremio | Linux Flatpak (`com.stremio.Stremio`) |
| YouTube | Google Play / Waydroid |
| Spotify | Google Play / Waydroid |
| Plex | Kodi + PM4K (Linux) |

U přímých APK PiTV kontroluje očekávané package ID před instalací.

## Server Store

**Nastavení → Server Store**

| Služba | Použití |
|---|---|
| Homebridge | HomeKit bridge + web UI |
| Tailscale | vzdálený přístup / VPN |
| Docker Engine | kontejnery |
| ATVLoadly | Apple TV sideload server |

Serverové služby běží dál i při vypnuté nebo uspáné TV.

## Android / APK

Waydroid je volitelný. PiTV funguje i bez Androidu jako čistý Linux TV launcher.

Instalace:

**Nastavení → Android / APK → Waydroid + Google Play → Instalovat**

PiTV nejdřív používá oficiální `repo.waydro.id`. Pokud je nedostupné nebo instalace z něj selže, automaticky použije **PiTV fallback snapshot** uložený v tomto repozitáři. Snapshot pro Ubuntu 24.04 / ARM64 obsahuje potřebné Waydroid runtime balíčky, SHA-256 kontrolní součty a jednou týdně se obnovuje z oficiálního zdroje.

Vlastní APK:

```text
/var/lib/pitv/apks/
~/PiTV/APKs/
```

## Ovládání

TV ovladač komunikuje s Raspberry Pi přes HDMI-CEC.

| Tlačítko | Akce |
|---|---|
| Šipky | navigace |
| OK / Enter | potvrzení |
| Back | krátce = zpět v aplikaci · podržet 3 s = návrat do PiTV |
| Home / Menu | návrat do PiTV, pokud ho TV/ovladač podporuje |
| Volume ± | TV / receiver |
| Mute | ztlumení |

PiTV používá jeden persistentní CEC klient pro příjem tlačítek i odesílání příkazů.

## Požadavky

Doporučená sestava:

- **Raspberry Pi 4** — hlavní a doporučený cíl
- Raspberry Pi 3 / 3B+ — Alpha, omezenější výkon
- Raspberry Pi 5 — Alpha, hardware zatím není fyzicky ověřený
- microSD 32 GB nebo větší
- Ubuntu Server 24.04 LTS ARM64
- micro-HDMI → HDMI
- kvalitní USB-C napájení
- Wi-Fi nebo Ethernet
- TV s HDMI-CEC

## Stav projektu

PiTV je aktuálně ve fázi **Alpha / aktivní vývoj**.

Automatické testy ověřují:

- Python a shell syntax
- Store JSON katalogy
- render všech obrazovek
- PiTV Apple Dark / Light
- Ubuntu 24.04 x64 i ARM64 install / start / update / uninstall
- Kodi Store install
- SmartTube ARM64 APK zdroj + Linux Stremio Flatpak
- Homebridge, Tailscale, Docker a ATVLoadly

Na fyzickém Raspberry Pi 4 ještě ověřujeme zejména:

- HDMI/KMS výstup
- konkrétní TV přes HDMI-CEC
- HDMI audio
- Kodi hardware decode
- Waydroid GPU / kernel kompatibilitu

Podrobnosti: **[AUDIT.md](AUDIT.md)**

## Zásluhy

PiTV stojí na práci několika open-source projektů a služeb:

- **Raspberry Pi** — hardware a Raspberry Pi Imager
- **Ubuntu** — serverový základ
- **labwc / Wayland** — lehké grafické prostředí
- **Pygame** — PiTV UI runtime
- **libCEC / cec-utils** — HDMI-CEC komunikace
- **Waydroid** — Android prostředí
- **Kodi** — Linux media center
- **Homebridge** — HomeKit bridge
- **Tailscale** — mesh VPN
- **Docker** — kontejnery
- **Stremio a Plex** — Linux aplikace / Kodi integrace; **SmartTube, Spotify a YouTube** — Android/Waydroid aplikace dostupné přes PiTV Store

PiTV tyto projekty nevlastní a není jejich oficiální součástí. Jejich názvy a ochranné známky patří příslušným vlastníkům.

## Odkazy

<p>
  <a href="FLASHER.md"><img src="https://img.shields.io/badge/PiTV-SD%20Installer-172033?style=for-the-badge&labelColor=111827" alt="PiTV SD Installer" /></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/PiTV-Install%20Guide-172033?style=for-the-badge&labelColor=111827" alt="Install Guide" /></a>
  <a href="AUDIT.md"><img src="https://img.shields.io/badge/PiTV-Audit-172033?style=for-the-badge&labelColor=111827" alt="PiTV Audit" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/PiTV-Changelog-172033?style=for-the-badge&labelColor=111827" alt="PiTV Changelog" /></a>
  <a href="SECURITY.md"><img src="https://img.shields.io/badge/PiTV-Security-172033?style=for-the-badge&labelColor=111827" alt="PiTV Security" /></a>
</p>

## Licence

PiTV je vydané pod licencí **MIT**. Podrobnosti jsou v **[LICENSE](LICENSE)**.

Použité projekty a aplikace se řídí vlastními licencemi a podmínkami.

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
