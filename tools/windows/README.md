# PiTV SD Installer — Windows

Malé grafické rozhraní pro vytvoření PiTV microSD bez ruční instalace Ubuntu, nastavování Wi-Fi nebo kopírování příkazů přes SSH.

## Spuštění

1. vlož microSD do čtečky,
2. spusť **Start-PiTV-SD-Installer.cmd**,
3. potvrď UAC,
4. vyber microSD,
5. klikni na **VYTVOŘIT PiTV SD**.

## Co udělá automaticky

- nabídne pouze bezpečné výměnné USB / SD / MMC disky,
- vyloučí Disk 0 a disk s Windows boot/system partition,
- najde podporovaný Ubuntu Server 24.04 LTS ARM64,
- použije oficiální Raspberry Pi Imager CLI,
- při chybějícím Imageru se ho pokusí doinstalovat přes `winget`,
- převezme aktuální Wi-Fi profil z Windows,
- připraví cloud-init,
- vytvoří silné náhodné recovery heslo pro `pitvadmin`,
- při prvním bootu stáhne `CaseyCZ/PiTV`, spustí `install.sh` a Raspberry restartuje,
- po úspěšné první instalaci odstraní dočasné `user-data` a `network-config` z boot oddílu.

Po vytvoření karty se recovery heslo zkopíruje do schránky.

## Bezpečnost

Před zápisem Installer znovu zobrazí číslo disku, model a kapacitu vybrané karty. Přesto vždy zkontroluj, že je vybraná správná microSD — cílový disk bude kompletně přepsán.

Samotný zápis image nedělá vlastní raw-disk kód. Používá oficiální Raspberry Pi Imager.

## Stav

Aktuálně jde o **v0.1 beta/prototyp**. PowerShell syntaxe a launcher jsou kontrolované GitHub Actions na Windows runneru.

Celý fyzický proces — skutečná microSD, první boot, Wi-Fi a automatická instalace na Raspberry Pi 4 — ještě před veřejným releasem ověříme na reálném hardware.

Později lze Windows variantu zabalit také jako malé `.exe`, aby uživatel nemusel vůbec vidět PowerShell.
