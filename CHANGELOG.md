# Changelog

All notable PiTV changes are documented here.

## 1.3.3 — 2026-09-19

### Fixed
- Windows SD Installer detects the Raspberry Pi Imager 2.x install path,
- if winget installation fails, the official Raspberry Pi Imager installer is downloaded directly,
- installer diagnostics now distinguish winget and official-installer failures.

## 1.3.2 — 2026-09-19

### Fixed / improved
- Windows SD Installer discovers nearby Wi-Fi networks and saved profiles,
- saved Wi-Fi passwords are loaded when Windows knows them,
- added **Zobrazit heslo** before writing the SD card,
- manual SSID/password entry remains available as fallback.

## 1.3.1 — 2026-09-19

### Fixed
- Windows SD Installer no longer requires automatic Wi-Fi detection,
- Wi-Fi SSID and password can be entered manually,
- release downloads are reduced to one Windows installer ZIP,
- Windows launcher automatically uses the latest GitHub Release.

## 1.3.0 — 2026-09-19

### Added
- standalone `CaseyCZ/PiTV` repository,
- PiTV Apple Dark and PiTV Apple Light themes,
- PiTV Store: Kodi, SmartTube, Stremio, YouTube, Spotify and Plex,
- Server Store: Homebridge, Tailscale, Docker Engine and ATVLoadly,
- in-app Waydroid + GAPPS installation,
- in-app PiTV/catalog/Ubuntu update center,
- automated x64/ARM64 smoke tests,
- Waydroid ARM64/Noble fallback package snapshot with weekly refresh and SHA-256 verification.

### Improved
- Apple-TV-inspired Home, Store, Server Store, Settings and Updates layouts,
- TV-remote grid navigation and sidebar focus,
- one persistent HDMI-CEC client for input and commands,
- screensaver behavior while external media apps are running,
- self-update preservation of user settings,
- installer security and allowlists.

### Verified
- clean install/start/self-update/uninstall on Ubuntu 24.04 x64 and ARM64 CI,
- Kodi Store install path,
- Homebridge, Tailscale, Docker and ATVLoadly install on ARM64 CI,
- SmartTube and Stremio ARM64 APK download/package inspection.

### Hardware verification still required
- Raspberry Pi 4 HDMI/KMS,
- physical HDMI-CEC behavior,
- HDMI audio,
- Kodi hardware decoding,
- Waydroid GPU/kernel behavior on the target Pi image.
