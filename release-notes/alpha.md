# PiTV Alpha

### PiTV 1.4.11 · Appearance navigation fix
- opravená levá šipka v Nastavení → Vzhled: Velké → Normální → Malé nyní funguje oběma směry
- stejný konflikt LEFT byl opraven také u nastavení Spořiče a HDMI audio portu
- Back zůstává návrat o úroveň zpět, takže šipky ←/→ mohou bezpečně měnit hodnoty
### PiTV 1.4.10 · TV runtime incident fixes
- opravené HDMI-CEC **OK / Zpět**: vlastní parser cec-ctl, split-event i raw fallback
- vypnutý kernel RC passthrough; PiTV je jediná překladová vrstva pro TV ovladač
- CEC monitor se po HDMI/CEC resetu automaticky znovu připojí
- Linux aplikace před startem ověřují XDG_RUNTIME_DIR + WAYLAND_DISPLAY a zapisují chybu do launch logu
- Waydroid čeká na Session: RUNNING a sys.boot_completed=1, ověřuje package ID i skutečné spuštění aplikace
- Android TV ovládání používá nativní DPAD_CENTER/BACK keyeventy
- Plex Player automaticky instaluje kodi-send; Store/CI odpovídá Linux Stremio + Kodi/PM4K architektuře
- self-update je připnutý na konkrétní commit SHA a kontroluje bezpečnost ZIP cest/velikosti
- APK Store ověřuje SHA-256 digest GitHub Release assetů; přímé APK vyžaduje SHA-256
Aktuální průběžná testovací verze PiTV. **Pi 4 je hlavní a doporučený cíl.**

### Aktuálně
- PiTV SD Installer pro Windows v0.28
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
- v0.28: po raw zápisu installer čeká na stabilní návrat boot oddílu, při transientní chybě provede automatický `diskpart rescan` + až 3 finalize pokusy, cloud-init zapisuje s `Flush(true)` a read-back SHA-256; ruční OPRAVIT už nemá být nutný po běžném zápisu
- ODESLAT CHYBU nyní předvyplní do GitHub issue krátkou diagnostiku; celý report zůstává zároveň ve schránce a lokálním souboru
