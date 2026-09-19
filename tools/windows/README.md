# PiTV SD Installer

První prototyp jednoduchého Windows nástroje pro přípravu microSD karty bez ruční instalace Ubuntu a PiTV.

## Co umí

- zobrazí pouze bezpečné výměnné USB / SD / MMC disky,
- nikdy nenabízí Disk 0 ani disk s Windows boot/system partition,
- nabídne podporovaný Ubuntu Server 24.04 LTS ARM64,
- použije oficiální Raspberry Pi Imager CLI pro samotný zápis,
- pokud Imager chybí, pokusí se ho doinstalovat přes winget,
- převezme aktuální Wi-Fi profil a heslo z Windows,
- vloží cloud-init konfiguraci,
- při prvním bootu Raspberry automaticky:
  - připojí Wi-Fi,
  - vytvoří recovery účet pitvadmin,
  - stáhne CaseyCZ/PiTV,
  - spustí install.sh,
  - restartuje Raspberry,
  - následně naběhne PiTV.

## Spuštění

Nejjednodušší:

1. vlož microSD do čtečky,
2. spusť Start-PiTV-SD-Installer.cmd,
3. potvrď UAC,
4. vyber SD kartu,
5. klikni na VYTVOŘIT PiTV SD.

Nebo z PowerShellu použij PiTV-SD-Installer.ps1.

## Stav

Toto je v0.1 prototyp pro Windows. Zápis image nedělá vlastní raw-disk kód; používá oficiální Raspberry Pi Imager CLI.

Před veřejným releasem ještě chceme ověřit celý proces na skutečné microSD + Raspberry Pi 4 a následně zabalit Windows verzi jako malé .exe.
