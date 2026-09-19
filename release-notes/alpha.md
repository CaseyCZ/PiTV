# PiTV Alpha

### Physical Pi 4 checkpoint · 2026-09-19
- PiTV 1.4.19 je na fyzickém zařízení potvrzené; `pitv-session-run` a single-user TV session fungují
- HDMI zvuk je potvrzený přes PipeWire/WirePlumber a Kodi HDMI sink
- Kodi je po zapnutí obou DRM PRIME voleb plynulé; log potvrzuje `CDVDVideoCodecDRMPRIME` pro H.264
- otevřený problém: CEC nefungovalo už po bootu před spuštěním Kodi; `/dev/cec0`, logical address 4 i root monitor jsou přitom aktivní
- ruční CEC `active` úspěšně vyslal ACTIVE_SOURCE na 2.0.0.0; další krok je automatické active po register/reconnect a fyzický test po rebootu
- samostatný problém: skutečný `kodi.bin` se může odpojit od sledovaného wrapperu a zůstat pod PID 1; plain Kodi instalace na zařízení navíc neměla `kodi-send`
- úplný diagnostický checkpoint je uložen v `docs/debug-2026-09-19.md`

### PiTV 1.4.19 · Noble ARM64 update fix
- odstraněna závislost na balíčku wlrctl, který na použitém Ubuntu 24.04 ARM64 nebyl přes APT dostupný a blokoval self-update
- návrat ovládání z Kodi/Stremio se nově pozná přímo podle wtype echo do PiTV, takže není potřeba externí focus utility
- update z PiTV 1.4.10 už nemusí instalovat wlrctl a může pokračovat přes běžné Noble ARM64 balíčky
### PiTV 1.4.18 · Full user/session ownership audit
- TV runtime má jednoho vlastníka: uživatel pitv; admin zůstává pouze SSH/recovery a root pouze privilegované/system operace
- labwc, PipeWire, WirePlumber, Kodi, Stremio a Waydroid GUI sdílejí jediný systemd user D-Bus a /run/user/<pitv UID>
- odstraněn privátní dbus-run-session a nucený SDL_AUDIODRIVER=alsa; tichý PiTV launcher už neinicializuje audio mixer
- všechny GUI child procesy přepisují HOME/USER/LOGNAME/XDG_RUNTIME_DIR/PULSE_RUNTIME_PATH/DBUS na pitv session
- cizí nebo absolutní WAYLAND_DISPLAY mimo pitv runtime je odmítnut a nahrazen skutečným labwc socketem
- Kodi a Waydroid wrappery odmítnou spuštění mimo uživatele pitv
- sudo pitv-session-run <příkaz> poskytuje z SSH správný kontext TV session pro wpctl a další diagnostiku
- serverové služby Homebridge/Tailscale/Docker/ATVLoadly zůstávají správně systémové/root; APT/Flatpak instalace jsou systémové, ale TV aplikace se spouštějí jako pitv
### PiTV 1.4.17 · Session isolation audit
- TV GUI, Kodi, Stremio, Waydroid a PipeWire jsou sjednocené pod uživatelem pitv
- odstraněn privátní dbus-run-session; labwc používá standardní systemd user D-Bus /run/user/<uid>/bus
- PiTV launcher už neinicializuje pygame audio a autostart nevynucuje SDL_AUDIODRIVER=alsa
- Kodi/Waydroid wrapper odmítne spuštění mimo TV uživatele pitv
- přidán sudo pitv-session-run <příkaz> pro správnou SSH diagnostiku TV session
- přímé spuštění PiTV GUI pod admin/root je blokované, aby nevznikaly druhé HOME/config/audio session
### PiTV 1.4.16 · HDMI audio session fix
- automatický HDMI výstup už není závislý pouze na pactl; PiTV používá i wpctl fallback
- installer doplňuje pulseaudio-utils, takže pactl je na nových/aktualizovaných instalacích dostupný
- oprava cílí na stav, kdy Kodi/PiTV běží pod uživatelem pitv, ale diagnostika spuštěná pod admin vidí pouze vlastní Dummy Output session
### PiTV 1.4.15 · External app return/focus recovery
- opravuje stav, kdy se po návratu z Kodi launcher zobrazil, ale nereagoval na ovladač
- návrat z externí Linux aplikace se detekuje přímo přes wtype echo bez dalšího Wayland nástroje
- pokud se focus vrátí do PiTV, ale externí session zůstane omylem aktivní, PiTV ji automaticky ukončí a obnoví vlastní CEC/input
- všechny Linux/Waydroid launch cesty používají jednotnou registraci external session
### PiTV 1.4.14 · CEC Home / Back
- doplněny všechny běžné HDMI-CEC menu kódy pro tlačítko Home/domeček (Root, Setup, Contents, Favorite, Media Top, Media Context)
- Home v Kodi/externí aplikaci se mapuje zpět do PiTV
- Back na hlavní stránce PiTV už není neviditelný no-op; přesune focus do levého menu
- Home na hlavní stránce resetuje výběr a zobrazí krátké potvrzení Domů
### PiTV 1.4.13 · HDMI audio default
- PiTV při startu vybere dostupný HDMI PipeWire/Pulse sink jako výchozí pro Kodi, Stremio a Waydroid
- změna HDMI audio portu v Nastavení se okamžitě promítne do výchozího Pulse sinku
- řeší stav, kdy Kodi vidělo HDMI zařízení, ale zůstalo na Default Output Device bez zvuku
### PiTV 1.4.12 · Full Settings audit
- Vzhled: levá/pravá šipka spolehlivě mění Motiv, Velikost dlaždic a Hodiny; Back se vrací
- Spořič: časové hodnoty už nepřetékají z minima na maximum a opačně
- Aplikace: dlouhý seznam má scroll a focus zůstává viditelný
- Síť, Android, Store, Server Store a Systém: dynamické seznamy po refreshi ořezávají neplatný výběr
- Android/APK: nalezené APK lze spustit přes OK; plné Android UI používá validovaný Wayland launch bridge
- O PiTV: levá šipka může bezpečně otevřít sidebar stejně jako ostatní read-only stránky
- config.json: motiv, velikost dlaždic, spořič, HDMI port a další hodnoty se při načtení normalizují do podporovaných mezí
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
