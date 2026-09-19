# PiTV Flasher

<p align="center">
  Připraví microSD kartu pro Raspberry Pi 4 tak, aby se po prvním bootu <strong>Ubuntu Server + PiTV nainstalovaly automaticky</strong>.
</p>

> **Stav:** beta. Skripty mají bezpečnostní kontrolu cílového disku a dry-run testy, ale skutečný zápis SD karty na Windows/macOS/Linux ještě musí projít fyzickým testem.

## Co Flasher udělá

1. najde výměnnou SD/USB kartu,
2. vyžádá přesné potvrzení před smazáním,
3. najde aktuální oficiální Ubuntu Server 24.04 LTS ARM64 image pro Raspberry Pi,
4. načte oficiální SHA-256 z Ubuntu,
5. použije Raspberry Pi Imager CLI pro zápis a ověření image,
6. zeptá se na Wi-Fi,
7. vytvoří recovery SSH klíč bez ukládání administrátorského hesla na SD kartu,
8. připraví cloud-init,
9. při prvním bootu Raspberry Pi samo stáhne `CaseyCZ/PiTV`,
10. spustí `install.sh`,
11. restartuje Raspberry Pi do PiTV.

## Windows

Stáhni skript:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.ps1 -OutFile "$env:TEMP\pitv-flasher.ps1"
```

Spusť ho:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:TEMP\pitv-flasher.ps1"
```

Skript si vyžádá administrátorská práva. Pokud Raspberry Pi Imager chybí a je dostupný `winget`, zkusí ho nainstalovat automaticky.

## Linux

```bash
curl -fsSL https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.sh -o /tmp/pitv-flasher.sh
chmod +x /tmp/pitv-flasher.sh
/tmp/pitv-flasher.sh
```

Na Linuxu se při chybějícím Raspberry Pi Imageru stáhne aktuální oficiální CLI `.deb` pro amd64/arm64.

## macOS

```bash
curl -fsSL https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/tools/pitv-flasher.sh -o /tmp/pitv-flasher.sh
chmod +x /tmp/pitv-flasher.sh
/tmp/pitv-flasher.sh
```

Pokud Raspberry Pi Imager není nainstalovaný a je dostupný Homebrew, skript použije:

```bash
brew install --cask raspberry-pi-imager
```

## Co zadáš

Flasher potřebuje pouze:

- cílovou SD kartu,
- Wi-Fi SSID,
- Wi-Fi heslo,
- volitelně hostname — výchozí `pitv`,
- volitelně recovery SSH uživatele — výchozí `pitvadmin`.

Wi-Fi heslo se na terminálu nezobrazuje. Recovery SSH používá samostatný Ed25519 klíč vytvořený na počítači.

## Bezpečnost disku

Flasher nikdy nezačne zápis jen podle pořadí disku. Před smazáním vypíše vybraný fyzický disk a vyžádá přesnou potvrzovací frázi.

Přesto vždy zkontroluj velikost a označení karty. **Vybraný disk bude kompletně přepsán.**

## První boot

Po dokončení Flasheru:

1. bezpečně vysuň SD kartu,
2. vlož ji do Raspberry Pi 4,
3. připoj HDMI a napájení,
4. počkej přibližně 10–30 minut.

První boot provede Ubuntu cloud-init, připojí Wi-Fi, stáhne PiTV a spustí instalaci. Po dokončení se Raspberry Pi automaticky restartuje.

Pokud vše proběhne správně, po restartu se na HDMI zobrazí PiTV.

## Recovery

Windows vytvoří recovery klíč přibližně zde:

```text
%USERPROFILE%\.ssh\pitv_ed25519
```

Linux/macOS:

```text
~/.ssh/pitv_ed25519
```

Výchozí připojení:

```bash
ssh -i ~/.ssh/pitv_ed25519 pitvadmin@pitv.local
```

Log automatické instalace na Raspberry Pi:

```text
/var/log/pitv-firstboot.log
```

## Dry run

Dry run nic nestahuje ani nezapisuje na disk.

Windows:

```powershell
.\tools\pitv-flasher.ps1 -DryRun
```

Linux/macOS:

```bash
./tools/pitv-flasher.sh --dry-run
```

## Ruční instalace zůstává

PiTV Flasher je pohodlnější cesta, ale klasická instalace přes Raspberry Pi Imager a `install.sh` zůstává podporovaná v [INSTALL.md](INSTALL.md).
