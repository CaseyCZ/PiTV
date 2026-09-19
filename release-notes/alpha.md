# PiTV Alpha

Aktuální průběžná testovací verze PiTV. **Pi 4 je hlavní a doporučený cíl.**

### Aktuálně
- PiTV SD Installer pro Windows v0.21
- výběr Raspberry Pi 3 / 3B+, Pi 4 nebo Pi 5
- Pi 3 a Pi 5 jsou zatím experimentální Alpha cíle
- automatické vyhledání Wi-Fi + načtení uloženého hesla
- zobrazení hesla před zápisem
- online Ubuntu Server 24.04 ARM64 nebo vlastní kompatibilní image
- trvalá cache stažených image v `%LOCALAPPDATA%\PiTV\images`
- stejná ověřená image se při dalším zápisu nestahuje znovu
- vlastní PiTV raw writer — Raspberry Pi Imager už není potřeba
- vlastní lehký `PiTV-XZ.exe` pro `.img.xz` — žádný Rufus, Raspberry Pi Imager ani externí XZ nástroj
- podpora `.img`, `.img.xz/.xz` a ZIP s jedním `.img`
- SHA-256 kontrola image a úplné read-back ověření SD po zápisu
- bezpečné formátování SD karty
- kontrola identity cílového disku před destruktivní operací
- viditelný progress jednotlivých fází
- rozšířená diagnostika + ODESLAT CHYBU
- automatické vložení cloud-init, Wi-Fi a instalace PiTV

### Instalace
Stáhni **PiTV-SD-Installer-Windows.zip**, rozbal **celý ZIP** a spusť `Start-PiTV-SD-Installer.cmd`.

> Alpha se průběžně aktualizuje. Stejný release a stejný soubor vždy obsahují aktuální testovací verzi.

- vlastní uživatelské jméno a heslo pro správu PiTV se zadávají před vytvořením SD

- ověření zápisu nyní čte přes stejný otevřený PhysicalDrive handle; tím se vyhne okamžité chybě některých USB/SD čteček po dokončení raw zápisu

- v0.24: pro výměnná média se fallback už nesnaží svazky dismountovat; pouze je zamkne a drží PhysicalDrive handle otevřený přes zápis i ověření, aby USB/SD čtečky nespadly do stavu „Zařízení není připraveno“
- ODESLAT CHYBU nyní předvyplní do GitHub issue krátkou diagnostiku; celý report zůstává zároveň ve schránce a lokálním souboru
