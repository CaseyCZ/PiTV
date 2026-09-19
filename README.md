<p align="center"><img src="assets/pitv-header.svg" alt="PiTV" width="100%"></p>

# PiTV 1.3

<p align="center">
  <strong>Lehký TV launcher pro Raspberry Pi 4 nad Ubuntu Serverem.</strong><br>
  Raspberry zůstává 24/7 server, zatímco HDMI nabízí vlastní rozhraní PiTV ovládané televizním ovladačem.
</p>

<p align="center">
  <a href="https://github.com/CaseyCZ/PiTV/actions/workflows/pitv-check.yml?query=branch%3AMaster"><img src="https://github.com/CaseyCZ/PiTV/actions/workflows/pitv-check.yml/badge.svg?branch=Master" alt="PiTV Check"></a>
  <a href="https://github.com/CaseyCZ/PiTV/actions/workflows/pitv-online-smoke.yml"><img src="https://img.shields.io/badge/Online%20Smoke-passed-22c55e?style=flat-square" alt="Online smoke passed"></a>
  <img src="https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white" alt="Raspberry Pi 4">
  <img src="https://img.shields.io/badge/Ubuntu%20Server-24.04-E95420?style=flat-square&logo=ubuntu&logoColor=white" alt="Ubuntu Server 24.04">
  <img src="https://img.shields.io/badge/License-MIT-38BDF8?style=flat-square" alt="MIT">
</p>

> **Samostatný projekt:** tento repozitář obsahuje kompletní PiTV včetně launcheru, Store, Server Store, instalátorů a self-update. PiTV není závislé na žádném jiném CaseyCZ projektu.

## Co PiTV umí

- fullscreen TV launcher bez GNOME/Ubuntu Desktopu,
- dvě sjednocená témata **PiTV Apple Dark** a **PiTV Apple Light**,
- HDMI-CEC: šipky, OK, Back, Home, power, active source, hlasitost a mute,
- vlastní spořič: hodiny → černá obrazovka → volitelný CEC standby,
- Wi-Fi scan/připojení/odpojení přes NetworkManager bez přepisování serverové sítě,
- HDMI audio pro Raspberry Pi 4,
- Linux aplikace včetně Kodi,
- Android/APK backend přes Waydroid + GAPPS/Google Play,
- **PiTV Store** pro TV aplikace,
- **Server Store** pro služby běžící 24/7 na pozadí,
- aktualizace PiTV, katalogů, Linux aplikací a Ubuntu přímo z TV,
- systémové informace: teplota, RAM, disk, uptime, kernel, síť a Tailscale,
- čistý uninstall, který ponechá uživatelská nastavení a APK data.

## Instalace

Primární cíl je **Ubuntu Server 24.04 ARM64 na Raspberry Pi 4**.

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
sudo reboot
```

Po restartu:

```text
Ubuntu Server
└── tty1 autologin: pitv
    └── dbus-run-session
        └── labwc / Wayland
            └── PiTV
```

SSH a serverové služby zůstávají dostupné. PiTV nevypíná Raspberry při běžném uspání TV.

## Ovládání

TV ovladač přes HDMI-CEC:

| Tlačítko | PiTV |
|---|---|
| Šipky | navigace |
| OK / Enter | potvrzení |
| Back | zpět |
| Home / Menu | návrat do PiTV |
| Volume ± | TV / receiver přes CEC |
| Mute | TV / receiver přes CEC |

PiTV používá jeden persistentní CEC klient pro příjem tlačítek i odesílání CEC příkazů.

## PiTV Store

**Nastavení → Aplikace → PiTV Store**

| Aplikace | Instalace |
|---|---|
| Kodi | Ubuntu APT |
| SmartTube | oficiální GitHub ARM64 release |
| Stremio | oficiální Android TV ARM64 APK |
| YouTube | Google Play ve Waydroidu |
| Spotify | Google Play ve Waydroidu |
| Plex | Google Play ve Waydroidu |

U přímých APK PiTV kontroluje package ID před instalací.

## Android / APK

Waydroid je volitelný. PiTV funguje i bez něj jako čistý Linux TV launcher.

Normální instalace bez SSH:

**Nastavení → Android / APK → Waydroid + Google Play → Instalovat**

PiTV nainstaluje Waydroid z oficiálního repozitáře a inicializuje GAPPS image. Ruční recovery cesta zůstává:

```bash
sudo ./scripts/install-waydroid.sh
```

Vlastní APK lze vložit do:

```text
/var/lib/pitv/apks/
~/PiTV/APKs/
```

PiTV přes `aapt` zjišťuje package, název, launchable activity, SDK a TV/Leanback informace.

## Server Store

**Nastavení → Server Store**

| Služba | Zdroj | Výsledek |
|---|---|---|
| Homebridge | oficiální Homebridge repository | služba + web :8581 |
| Tailscale | oficiální Linux installer | tailscaled + login |
| Docker Engine | oficiální Docker repository | Docker service |
| ATVLoadly | `bitxeno/atvloadly` | Docker container + web :5533 |

Tyto služby běží dál i při vypnuté/uspáné TV.

## Aktualizace

**Nastavení → Aktualizace**

PiTV umí přímo z TV:

- zkontrolovat dostupnou verzi PiTV,
- provést self-update z větve `Master`,
- aktualizovat PiTV Store + Server Store katalog,
- aktualizovat Linux Store aplikace,
- aktualizovat Ubuntu balíčky,
- restartovat pouze PiTV UI.

Uživatelské nastavení v `/home/pitv/.config/pitv` se při self-update zachovává.

## Nastavení

- Vzhled
- Spořič obrazovky
- Síť / Wi-Fi
- Zvuk / HDMI
- HDMI / CEC
- Aplikace / PiTV Store
- Server Store
- Android / APK
- Aktualizace
- Systém
- Napájení
- O PiTV

## Témata

### PiTV Apple Dark
Tmavé glass panely, modrý focus, hero karty a TV-first rozložení.

### PiTV Apple Light
Světlé panely, čisté pozadí a stejná navigace i funkce jako Dark.

Přepnutí: **Nastavení → Vzhled**.

## Online testy

Repo obsahuje dvě úrovně CI:

### PiTV Check
`.github/workflows/pitv-check.yml`

Automaticky při změnách kontroluje:

- Python syntax,
- shell syntax,
- JSON katalogy,
- všech 15 obrazovek,
- oba motivy Dark/Light,
- základní runtime render přes dummy SDL.

### PiTV Online Smoke
`.github/workflows/pitv-online-smoke.yml`

Ruční těžší test. Poslední kompletní audit prošel na **Ubuntu 24.04 x64 i ARM64** a ověřil:

- čistou instalaci `sudo ./install.sh`,
- instalované soubory a sudoers,
- start PiTV event loopu,
- render všech obrazovek,
- navigaci Home/sidebar,
- instalaci Kodi ze Store,
- online update obou katalogů,
- PiTV self-update a následný restart,
- čistý uninstall,
- Homebridge / Tailscale / Docker / ATVLoadly na ARM64,
- stažení a `aapt` kontrolu SmartTube + Stremio ARM64 APK.

Podrobnosti jsou v [AUDIT.md](AUDIT.md). Historie změn je v [CHANGELOG.md](CHANGELOG.md) a bezpečnostní model v [SECURITY.md](SECURITY.md).

## Co ještě vyžaduje fyzický Raspberry Pi 4

Cloud CI nenahradí skutečný HDMI hardware. Na fyzickém Pi je ještě potřeba ověřit:

- KMS/Wayland obraz přes konkrétní HDMI port a TV,
- skutečný TV ovladač přes HDMI-CEC,
- CEC power/standby/volume podle výrobce TV/receiveru,
- HDMI audio `vc4hdmi0/vc4hdmi1`,
- Kodi fullscreen + hardwarovou akceleraci videa,
- Waydroid binder/kernel/GPU kompatibilitu konkrétního Ubuntu image,
- Android TV aplikace v reálném Waydroid okně.

## Struktura projektu

```text
pitv/
  pitv.py                 hlavní UI, navigace, nastavení
  apk_backend.py          APK/Waydroid detekce
  store_backend.py        PiTV Store backend
  update_backend.py       kontrola verze
store/
  catalog.json            TV aplikace
  server_catalog.json     serverové služby
system/
  pitv-helper             omezené privilegované akce
  pitv-session            TV Wayland session
  pitv-waydroid-launch    Android foreground wrapper
  pitv-self-update        self-update
  labwc/                  compositor config
config/
  config.json
  apps.d/
scripts/
  install-waydroid.sh
install.sh
uninstall.sh
```

## Bezpečnost

Privilegované akce nejdou přes obecný root shell. Uživatel `pitv` může přes sudo spouštět pouze PiTV helper, který používá allowlist akcí/balíčků/package ID.

Self-update stahuje aktuální větev `Master` z tohoto GitHub repozitáře a spouští její `install.sh` jako root. Pro produkční distribuci je vhodné později přejít na podepsané/verzované releasy.

## Odinstalace

```bash
sudo ./uninstall.sh
```

Odstraní PiTV runtime, kiosk/autologin konfiguraci a PiTV helpery. Uživatel `pitv`, jeho nastavení a APK data zůstanou zachované pro případnou reinstalaci.

## Licence

MIT © 2026 CaseyCZ
