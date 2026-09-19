<p align="center">
  <img src="assets/pitv-header.svg" alt="PiTV by CaseyCZ" width="100%" />
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/CZ-%C4%8Ce%C5%A1tina-172033?style=for-the-badge&labelColor=111827" alt="Czech" /></a>
  <img src="https://img.shields.io/badge/EN-English-38BDF8?style=for-the-badge&labelColor=0284C7" alt="English" />
</p>

<p align="center">
  A lightweight TV launcher for <strong>Raspberry Pi 4</strong> combining a custom TV interface, apps and 24/7 server services on one device.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/VERSION-v1.3.0-38BDF8?style=for-the-badge&labelColor=0284C7" alt="PiTV version 1.3.0" />
</p>

<p align="center">
  <a href="INSTALL_EN.md"><img src="https://img.shields.io/badge/PiTV-Install-38BDF8?style=for-the-badge&labelColor=0284C7&logo=raspberrypi&logoColor=white" alt="Install PiTV" /></a>
</p>

## About

**PiTV** is a custom TV environment for Raspberry Pi 4 built on **Ubuntu Server 24.04 ARM64**. The Raspberry Pi remains a full 24/7 server while HDMI provides a clean interface controlled by the TV remote.

The goal is to combine TV apps, Android apps, system settings and background server services without installing a full desktop environment such as GNOME.

## Main features

- 📺 fullscreen TV launcher on lightweight **labwc / Wayland**
- 🎨 **PiTV Apple Dark** and **PiTV Apple Light** themes
- 🎮 **HDMI-CEC** control — arrows, OK, Back, Home, power, volume and mute
- 💤 screensaver with clock, black screen and optional CEC standby
- 🔊 HDMI audio for Raspberry Pi 4
- 📡 Wi-Fi and network settings directly from the TV
- 📦 **PiTV Store** for TV apps
- 🖥️ **Server Store** for 24/7 background services
- 🤖 **Waydroid + Google Play** for Android TV apps
- ⬆️ PiTV, catalog, Linux app and Ubuntu updates from the TV
- 🌡️ system overview — temperature, RAM, disk, uptime, kernel, network and Tailscale
- 🔄 self-update while preserving user settings

## Installation

<p>
  <a href="INSTALL_EN.md"><img src="https://img.shields.io/badge/Guide-Full%20installation-38BDF8?style=for-the-badge&labelColor=0284C7&logo=raspberrypi&logoColor=white" alt="Full PiTV installation guide" /></a>
</p>

The complete process from an empty microSD card through Raspberry Pi Imager, Wi-Fi and SSH to the first PiTV boot is in **[INSTALL_EN.md](INSTALL_EN.md)**.

Quick install on a prepared **Raspberry Pi 4 + Ubuntu Server 24.04 ARM64**:

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
sudo reboot
```

After reboot PiTV starts automatically:

```text
Ubuntu Server
└── tty1 autologin
    └── labwc / Wayland
        └── PiTV
```

SSH and server services remain available while the TV is off or asleep.

## PiTV Store

Apps are installed from **Settings → Applications → PiTV Store**.

- 📺 **Kodi** — Ubuntu APT
- ▶️ **SmartTube** — official ARM64 GitHub release
- 🎬 **Stremio** — official Android TV ARM64 APK
- ▶️ **YouTube** — Google Play inside Waydroid
- 🎵 **Spotify** — Google Play inside Waydroid
- 🎞️ **Plex** — Google Play inside Waydroid

PiTV validates the expected package ID for direct APK installs.

## Server Store

**Settings → Server Store** installs services that continue running independently of the TV interface.

- 🏠 **Homebridge** — official repository, web UI on port 8581
- 🔐 **Tailscale** — VPN / remote access
- 🐳 **Docker Engine** — official Docker repository
- 📲 **ATVLoadly** — Docker container, web UI on port 5533

Server services remain active while the TV is off or PiTV is in screensaver mode.

## Android / APK

Waydroid is optional — PiTV also works as a pure Linux TV launcher.

Install directly from the TV:

**Settings → Android / APK → Waydroid + Google Play → Install**

Custom APK files can be placed in:

```text
/var/lib/pitv/apks/
~/PiTV/APKs/
```

PiTV uses `aapt` to read package name, app label, launchable activity, SDK and TV / Leanback information.

## Remote control

PiTV receives TV remote input through HDMI-CEC.

| Button | Action |
|---|---|
| Arrows | navigation |
| OK / Enter | confirm |
| Back | back |
| Home / Menu | return to PiTV |
| Volume ± | TV / receiver |
| Mute | mute |

PiTV uses one persistent CEC client for both input and outgoing commands.

## Appearance

The same visual system is used across Home, Store, Server Store, Settings, Updates, Android / APK and HDMI / CEC.

- **PiTV Apple Dark** — dark glass panels, blue focus and hero cards
- **PiTV Apple Light** — clean light interface with identical navigation

Switch themes in **Settings → Appearance**.

## Updates

**Settings → Updates** can:

- check for a new PiTV version
- update PiTV
- update PiTV Store and Server Store catalogs
- update Linux Store apps
- update Ubuntu packages
- restart only the PiTV UI

User configuration in `/home/pitv/.config/pitv` is preserved during self-update.

## Testing

PiTV includes two GitHub Actions test levels.

**PiTV Check** validates Python, shell scripts, JSON catalogs, both themes and all UI screens.

**PiTV Online Smoke** performs a complete install/start test on Ubuntu 24.04 **x64 and ARM64**, including Kodi, self-update, uninstall, Homebridge, Tailscale, Docker, ATVLoadly and Android APK sources.

The latest full online test of the standalone repository completed with **PASS**.

> A physical Raspberry Pi 4 is still required for final HDMI/KMS, real TV CEC, HDMI audio, Kodi hardware acceleration and Waydroid GPU/kernel verification.

## Links

<p>
  <a href="AUDIT.md"><img src="https://img.shields.io/badge/PiTV-Audit-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Audit" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/PiTV-Changelog-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Changelog" /></a>
  <a href="SECURITY.md"><img src="https://img.shields.io/badge/PiTV-Security-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="PiTV Security" /></a>
</p>

## Support

<p align="center">
  <a href="https://www.buymeacoffee.com/caseycz"><img src="https://img.shields.io/badge/Support%20CaseyCZ-Buy%20Me%20a%20Coffee-38BDF8?style=for-the-badge&labelColor=0284C7&logo=buymeacoffee&logoColor=white" alt="Support CaseyCZ" /></a>
</p>

<p align="center">
  <a href="https://www.buymeacoffee.com/caseycz"><img src="https://caseycz.github.io/support-qr.svg" width="150" alt="Buy Me a Coffee QR code" /></a><br>
  <sub>Scan the QR code or click the button.</sub>
</p>

<p align="center">
  <a href="https://caseycz.github.io/"><img src="https://img.shields.io/badge/CaseyCZ%20Website-Open-172033?style=flat-square&labelColor=111827" alt="CaseyCZ Website" /></a>
</p>
