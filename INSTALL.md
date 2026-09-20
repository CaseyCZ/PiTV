# Instalace PiTV

<p align="center">
  Kompletní postup od prázdné microSD až po první spuštění <strong>PiTV na Raspberry Pi 4</strong>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?style=for-the-badge&logo=raspberrypi&logoColor=white" alt="Raspberry Pi 4" />
  <img src="https://img.shields.io/badge/Ubuntu%20Server-24.04%20LTS-E95420?style=for-the-badge&logo=ubuntu&logoColor=white" alt="Ubuntu Server 24.04 LTS" />
  <img src="https://img.shields.io/badge/PiTV-v1.3.0-38BDF8?style=for-the-badge&labelColor=0284C7" alt="PiTV 1.3.0" />
</p>

## Co budeš potřebovat

- Raspberry Pi 4
- microSD kartu
- čtečku nebo redukci microSD → SD
- micro-HDMI → HDMI kabel
- USB-C napájecí zdroj pro Raspberry Pi 4
- TV nebo monitor
- Wi-Fi
- počítač pro přípravu microSD
- klávesnici pro první lokální přihlášení pouze jako záložní možnost

Pro běžné ovládání PiTV je ideální TV ovladač přes **HDMI-CEC**.

## 1. Otestuj TV a ovladač

Ještě před instalací PiTV ověř:

- zapnutí a vypnutí TV
- šipky
- OK
- Back / Return
- Home / Menu (volitelné; starší TV ho nemusí mít)
- podržení Back / Return 3 s pro ukončení aplikace a návrat do PiTV
- Volume + / -
- Mute

V nastavení TV zapni **HDMI-CEC**.

Podle výrobce TV se může funkce jmenovat například:

- Samsung — Anynet+
- LG — SIMPLINK
- Sony — BRAVIA Sync
- Panasonic — VIERA Link
- Philips — EasyLink

PiTV přijímá povely z TV přes HDMI-CEC. Univerzální IR ovladač tedy ovládá TV a TV následně předává podporované povely Raspberry Pi.

## 2. Nainstaluj Raspberry Pi Imager

Na počítači nainstaluj **Raspberry Pi Imager**.

Oficiální stránka:

https://www.raspberrypi.com/software/

Vlož microSD kartu do počítače.

> Zápis image smaže všechna data na vybrané microSD kartě.

## 3. Vyber systém

V Raspberry Pi Imager nastav:

1. **Raspberry Pi Device** → Raspberry Pi 4
2. **Operating System** → Ubuntu
3. **Ubuntu Server 24.04 LTS (64-bit)**
4. **Storage** → tvoje microSD karta

Nepoužívej Ubuntu Desktop ani Raspberry Pi OS Desktop. PiTV je navržené jako lehký TV/server systém bez plného desktopového prostředí.

## 4. Nastav Wi-Fi a SSH ještě před zápisem

V nastavení image doporučujeme vyplnit:

- hostname, například `pitv`
- vlastní uživatelské jméno
- bezpečné heslo
- Wi-Fi SSID
- Wi-Fi heslo
- správnou zemi Wi-Fi
- časovou zónu
- klávesnici
- **Enable SSH**

Pro první instalaci je nejjednodušší povolit SSH pomocí hesla. Později lze přejít na SSH klíče.

Uživatele `pitv` není nutné vytvářet ručně. PiTV instalátor si připraví vlastní kiosk uživatelský účet.

## 5. Zapiš image

Potvrď zápis systému na microSD a nech Raspberry Pi Imager dokončit také kontrolu zápisu.

Potom kartu bezpečně vysuň.

## 6. První boot Raspberry Pi

1. vlož microSD do Raspberry Pi 4
2. připoj HDMI k TV
3. připoj napájení
4. počkej na první start Ubuntu Serveru

První boot může trvat několik minut.

Pokud jsi nastavil Wi-Fi v Raspberry Pi Imageru, Raspberry Pi se má automaticky připojit do domácí sítě.

## 7. Připoj se přes SSH

Z počítače ve stejné síti:

```bash
ssh TVOJE_JMENO@pitv.local
```

Pokud `pitv.local` nefunguje, použij IP adresu Raspberry Pi:

```bash
ssh TVOJE_JMENO@IP_ADRESA
```

Přihlas se heslem nastaveným v Raspberry Pi Imageru.

## 8. Aktualizuj základní systém

Doporučený první krok:

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

Po restartu se znovu připoj přes SSH.

## 9. Nainstaluj PiTV

Spusť:

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
```

Instalátor připraví potřebné balíčky, PiTV runtime, labwc / Wayland session, kiosk uživatele, HDMI-CEC nástroje, Store katalogy a privilegované helpery.

Po dokončení:

```bash
sudo reboot
```

## 10. První spuštění PiTV

Po restartu se má PiTV spustit automaticky na HDMI:

```text
Ubuntu Server
└── tty1 autologin: pitv
    └── labwc / Wayland
        └── PiTV
```

Raspberry Pi zůstává současně normální server. SSH a serverové služby pokračují na pozadí.

## 11. První kontrola v PiTV

Po prvním spuštění ověř:

- obraz přes HDMI
- rozlišení TV
- navigaci šipkami
- OK
- Back
- Home / Menu, pokud ho TV podporuje
- podržení Back 3 s = ukončit aplikaci a vrátit PiTV
- HDMI-CEC
- HDMI audio
- Wi-Fi
- PiTV Apple Dark / Light
- spořič obrazovky

Potom můžeš přejít na instalaci aplikací a služeb.

## 12. PiTV Store

V TV rozhraní:

**Nastavení → Aplikace → PiTV Store**

Dostupné položky:

- Kodi
- SmartTube
- Stremio
- YouTube
- Spotify
- Plex

## 13. Android / Google Play

Android je volitelný.

V PiTV:

**Nastavení → Android / APK → Waydroid + Google Play → Instalovat**

Po instalaci lze přes Google Play přidat například YouTube, Spotify nebo Plex.

## 14. Server Store

V PiTV:

**Nastavení → Server Store**

Lze nainstalovat:

- Homebridge
- Tailscale
- Docker Engine
- ATVLoadly

Tyto služby běží dál i po vypnutí TV.

## Když PiTV po restartu nenaběhne

Připoj se přes SSH a zkontroluj:

```bash
systemctl status getty@tty1
```

PiTV lze také spustit ručně pro diagnostiku:

```bash
sudo -u pitv /usr/local/bin/pitv-session
```

Pro kontrolu HDMI-CEC:

```bash
cec-client -l
```

Pro kontrolu dostupných HDMI audio zařízení:

```bash
aplay -l
```

## Odinstalace

Pokud budeš chtít PiTV odstranit:

```bash
cd PiTV
sudo ./uninstall.sh
```

Uživatelská PiTV konfigurace a APK data zůstávají zachovaná pro případnou reinstalaci.

## Další informace

- [README](README.md)
- [Audit](AUDIT.md)
- [Changelog](CHANGELOG.md)
- [Security](SECURITY.md)

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/PiTV-Zp%C4%9Bt%20na%20README-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="Zpět na README" /></a>
</p>
