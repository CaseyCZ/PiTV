# PiTV SD Installer — Windows

Malé grafické rozhraní pro vytvoření PiTV microSD bez ruční instalace Ubuntu, nastavování Wi-Fi nebo kopírování příkazů přes SSH.

## Spuštění

1. stáhni z GitHub Releases jediný ZIP, rozbal ho a ponech si `Start-PiTV-SD-Installer.cmd`,
2. vlož microSD do čtečky,
3. spusť **Start-PiTV-SD-Installer.cmd**,
4. potvrď UAC,
5. vyber Raspberry Pi — Pi 4 je doporučený,
6. vyber microSD,
7. zkontroluj nebo zadej Wi-Fi a klikni na **VYTVOŘIT PiTV SD**.

Pokud chceš kartu pouze vrátit do běžného stavu, použij **NAFORMÁTOVAT SD**. Installer smaže staré oddíly a vytvoří jeden exFAT oddíl `SDCARD` přes dostupnou kapacitu.

## Co udělá automaticky

- nabídne pouze bezpečné výměnné USB / SD / MMC disky,
- vyloučí Disk 0 a disk s Windows boot/system partition,
- nabídne Pi 3 / 3B+, Pi 4 a Pi 5; Pi 4 je výchozí doporučený model,
- najde Ubuntu Server 24.04 LTS ARM64 označený v aktuálním katalogu pro zvolený model,
- použije oficiální Raspberry Pi Imager CLI,
- při chybějícím Imageru se ho pokusí doinstalovat přes `winget`,
- vyhledá dostupné Wi-Fi sítě a spojí je s uloženými Windows profily,
- u známé sítě se pokusí načíst uložené heslo; SSID i heslo lze vždy zadat ručně,
- heslo lze dočasně zobrazit pro kontrolu před zápisem,
- připraví cloud-init,
- vytvoří silné náhodné recovery heslo pro `pitvadmin`,
- při prvním bootu stáhne `CaseyCZ/PiTV`, spustí `install.sh` a Raspberry restartuje,
- po úspěšné první instalaci odstraní dočasné `user-data` a `network-config` z boot oddílu.

Po vytvoření karty se recovery heslo zkopíruje do schránky.

## Bezpečnost

Před zápisem Installer znovu zobrazí číslo disku, model a kapacitu vybrané karty. Přesto vždy zkontroluj, že je vybraná správná microSD — cílový disk bude kompletně přepsán.

Samotný zápis image nedělá vlastní raw-disk kód. Používá oficiální Raspberry Pi Imager.

## Stav

Aktuálně jde o **v0.14 alpha**. PowerShell syntaxe, živý Ubuntu katalog pro Pi 3/4/5, launcher a aktuální Raspberry Pi Imager CLI jsou kontrolované GitHub Actions na Windows runneru.

Celý fyzický proces — skutečná microSD, první boot, Wi-Fi a automatická instalace na Raspberry Pi 4 — ještě před veřejným releasem ověříme na reálném hardware.

Později lze Windows variantu zabalit také jako malé `.exe`, aby uživatel nemusel vůbec vidět PowerShell.
