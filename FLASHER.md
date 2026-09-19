# PiTV SD Installer

<p align="center">
  Připraví microSD kartu pro Raspberry Pi 4 tak, aby se po prvním zapnutí <strong>Ubuntu Server + PiTV nainstalovaly automaticky</strong>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-GUI-38BDF8?style=for-the-badge&labelColor=0284C7&logo=windows&logoColor=white" alt="Windows GUI" />
  <img src="https://img.shields.io/badge/Linux-Script-172033?style=for-the-badge&labelColor=111827&logo=linux&logoColor=white" alt="Linux" />
  <img src="https://img.shields.io/badge/macOS-Script-172033?style=for-the-badge&labelColor=111827&logo=apple&logoColor=white" alt="macOS" />
</p>

> **Stav: beta.** Syntaxe, bezpečnostní kontroly a dry-run jsou testované v CI. Skutečný zápis microSD a první boot ještě ověříme na fyzickém Raspberry Pi 4.

## Jak to funguje

PiTV SD Installer použije oficiální Raspberry Pi Imager pro zápis Ubuntu Serveru 24.04 LTS ARM64. Na boot kartu přidá Wi-Fi a cloud-init konfiguraci. Při prvním startu se Raspberry připojí k internetu, stáhne aktuální `CaseyCZ/PiTV`, spustí `install.sh` a po dokončení se restartuje přímo do PiTV.

Běžný uživatel tedy nemusí ručně instalovat Ubuntu, hledat IP adresu Raspberry ani kopírovat instalační příkazy přes SSH.

## Windows — doporučená cesta

Windows má vlastní malé grafické rozhraní. Hotový balíček je dostupný také v **[GitHub Releases](https://github.com/CaseyCZ/PiTV/releases/latest)** jako `PiTV-SD-Installer-Windows-v1.3.1.zip`.

1. stáhni nebo naklonuj repozitář PiTV,
2. otevři `tools/windows/`,
3. spusť **Start-PiTV-SD-Installer.cmd**,
4. potvrď oprávnění správce,
5. vyber microSD kartu,
6. klikni na **VYTVOŘIT PiTV SD**.

Installer se pokusí načíst aktuální Wi-Fi profil z Windows, ale **SSID i heslo lze vždy zadat ručně**. Launcher při každém spuštění zkontroluje nejnovější GitHub Release, takže kvůli běžné aktualizaci není potřeba ručně stahovat nový installer. Pokud Raspberry Pi Imager chybí a je dostupný `winget`, pokusí se ho nainstalovat.

Windows nástroj nabízí pouze výměnné USB / SD / MMC disky, vylučuje systémový a boot disk a před zápisem zobrazí model i kapacitu zvolené karty.

Po dokončení vytvoří náhodné recovery heslo pro účet `pitvadmin` a zkopíruje ho do schránky. Po prvním úspěšném bootu PiTV odstraní z boot oddílu dočasné cloud-init soubory s Wi-Fi nastavením.

Podrobnosti: **[tools/windows/README.md](tools/windows/README.md)**

## Windows — PowerShell CLI

Pro uživatele, kteří nechtějí GUI, zůstává dostupný konzolový flasher:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.ps1 -OutFile "$env:TEMP\pitv-flasher.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\pitv-flasher.ps1"
```

CLI se zeptá na kartu, Wi-Fi, hostname a recovery uživatele. Recovery přístup používá SSH klíč.

## Linux

```bash
curl -fsSL https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.sh -o /tmp/pitv-flasher.sh
chmod +x /tmp/pitv-flasher.sh
/tmp/pitv-flasher.sh
```

Na Linuxu skript nabídne pouze výměnné disky, vyžádá přesné potvrzení před smazáním a používá recovery SSH klíč.

## macOS

```bash
curl -fsSL https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.sh -o /tmp/pitv-flasher.sh
chmod +x /tmp/pitv-flasher.sh
/tmp/pitv-flasher.sh
```

Pokud Raspberry Pi Imager není nainstalovaný a je dostupný Homebrew, skript ho může nainstalovat přes Homebrew.

## Co se stane na Raspberry Pi

Po vložení připravené microSD a zapnutí Raspberry:

```text
První boot Ubuntu Server
        ↓
Wi-Fi
        ↓
cloud-init
        ↓
stáhne CaseyCZ/PiTV
        ↓
./install.sh
        ↓
automatický restart
        ↓
PiTV na HDMI
```

První boot může podle rychlosti SD karty a internetu trvat přibližně **10–30 minut**.

## Bezpečnost disku

Zápis microSD je destruktivní operace. Installer proto omezuje výběr na výměnná zařízení a před smazáním vyžaduje další potvrzení.

Přesto vždy zkontroluj **model a kapacitu vybrané karty**. Vybraný fyzický disk bude kompletně přepsán.

## Recovery

Pokud automatická první instalace selže, PiTV lze diagnostikovat přes SSH. Log first-boot instalace je:

```text
/var/log/pitv-firstboot.log
```

Linux/macOS a Windows CLI ukládají recovery SSH klíč jako:

```text
~/.ssh/pitv_ed25519
```

Windows GUI místo toho vytvoří silné náhodné recovery heslo a po zápisu ho zkopíruje do schránky.

## Testování bez zápisu

Linux/macOS:

```bash
./tools/pitv-flasher.sh --dry-run
```

Windows CLI:

```powershell
.\tools\pitv-flasher.ps1 -DryRun
```

Windows GUI má samostatnou GitHub Actions kontrolu PowerShell syntaxe a launcheru.

## Ruční instalace

Automatický installer je doporučená pohodlná cesta. Klasická instalace přes Raspberry Pi Imager + SSH zůstává podporovaná v **[INSTALL.md](INSTALL.md)**.
