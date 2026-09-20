# PiTV Alpha

### PiTV 1.4.27 · spolehlivá aktualizace při APT locku
- self-update už neselže kódem 100 jen proto, že Ubuntu právě spustilo `unattended-upgrades`
- nový instalátor používá `DPkg::Lock::Timeout=600` a bezpečně čeká až 10 minut na dokončení existující APT/DPKG transakce; lock soubory nemaže a cizí procesy nezabíjí
- `add-apt-repository` už nespouští vlastní neřízené APT update; všechny balíčkové operace procházejí stejným lock-aware tokem
- stejné čekání platí pro aktualizaci Ubuntu, Linux Store aplikací a APT instalace z PiTV
- self-updater zachytává výstup instalátoru a při chybě vrací krátkou smysluplnou zprávu místo celého terminálového logu
- toast a horní stavová hláška se nově ořezávají na šířku TV, takže dlouhý APT výstup už nepřetéká přes obrazovku
- oprava funguje i při přechodu ze starého PiTV, protože starý updater vždy stahuje aktuální `install.sh` z Master


### PiTV 1.4.26 · uzavření runtime oprav před fyzickým testem
- **3 s podržení Zpět je univerzální ukončení aplikace** i na starých TV bez Home; krátké Zpět zůstává normální Back uvnitř aplikace
- CEC long-press nově funguje i na televizích, které při držení tlačítka posílají opakované dvojice Press/Release místo jednoho dlouhého Press
- každý návrat z Kodi, Linux Stremia i Android/Waydroidu používá jednu deterministickou cestu zpět na pracovní plochu PiTV; platí to i pro normální ukončení aplikace bez nouzového gesta
- po návratu do launcheru PiTV znovu otevře jediný kernel CEC monitor, zaregistruje se a znovu oznámí Active Source; tím se opravuje stav, kdy CEC fungovalo po rebootu a později po přechodu aplikací přestalo reagovat
- známé staré Android instalace z vlastních historických PiTV katalogů se jednorázově migračně odstraní: `com.stremio.one` a starý Android Plex `com.plexapp.android`; cizí uživatelské Android balíčky se nemažou
- staré Store receipts těchto Android variant se také vyčistí, takže se po refreshi nevracejí do stavu „nainstalováno“
- Kodi dostává PiTV appliance defaults pro oba fyzicky ověřené DRM PRIME přepínače (`videoplayer.useprimedecoder=true` + `videoplayer.useprimedecoderforhw=true`); PiTV mění výchozí hodnoty, ne uživatelovy uložené volby
- instalace Kodi z PiTV Store zároveň instaluje `kodi-eventclients-kodi-send`, takže graceful Quit/Plex ovládání už není závislé na tom, zda balíček náhodou existoval
- zachovány jsou opravy z 1.4.20–1.4.25: odinstalace aplikací, glass UI, Kodi-style seznamové Nastavení, Cage fullscreen Waydroid, root-safe Android DPAD relay a persistentní Kodi lifecycle wrapper
- tato verze už nemá žádnou další plánovanou softwarovou opravu z incidentů 2026-09-19/20; další krok je **fyzický regresní test na Raspberry Pi 4**


### PiTV 1.4.25 · univerzální ukončení aplikace + Kodi lifecycle
- krátké Zpět zůstává běžné Back uvnitř aplikace; **podržení Zpět 3 s aplikaci skutečně ukončí a vrátí PiTV launcher**
- funkce není závislá na Home tlačítku; Home zůstává pouze volitelné pozastavení/multitasking pro ovladače, které ho mají
- návrat do launcheru proběhne okamžitě a cleanup aplikace pokračuje mimo render/input thread
- pokud aplikace po běžném TERM nezmizí do 2,5 s, PiTV použije cílený force fallback; tím se uklidí i procesy odpojené od původního wrapperu
- Android exit zastaví Cage/Waydroid session a po long-Back ukončí také Waydroid container, aby Pi 4 dostalo zpět RAM/GPU stav
- Kodi má nový `pitv-kodi-launch`, který sleduje skutečný `kodi.bin` i když distro `kodi` wrapper skončí a proces se reparentuje pod PID 1
- Plex/PM4K používá stejný Kodi lifecycle wrapper; `kodi-send` je volitelný pro běžné Kodi a povinný pouze tam, kde ho Plex integrace opravdu potřebuje
- stale focus recovery už nenechá skrytou aplikaci suspendovanou; provede deterministické ukončení a návrat do PiTV
- Home obrazovka i dokumentace ukazují nový TV kontrakt: **Podrž Zpět 3 s = ukončit aplikaci • PiTV**


### PiTV 1.4.24 · TV multitasking místo ukončování
- 3sekundové podržení Zpět už aplikaci nezabije: pozastaví ji, vrátí launcher PiTV a aplikace zůstane připravená v paměti
- Kodi/Plex, nativní Stremio, Android/Waydroid a ostatní TV aplikace dostávají vlastní labwc pracovní plochu; PiTV launcher zůstává na samostatné ploše
- Kodi/Plex se při návratu do launcheru suspendují přes SIGSTOP včetně odpojeného `kodi.bin`; obraz i zvuk se zastaví a pozice přehrávání zůstane zachovaná
- nativní Linux aplikace se po opětovném otevření obnoví přes SIGCONT; přehrávání se samo nespouští, Play zůstává na uživateli
- Android dostane pause-only `KEYCODE_MEDIA_PAUSE (127)`; Cage + Waydroid zůstávají běžet jako jeden Android multitasking slot
- opětovné otevření stejné Android aplikace nebo jiné APK použije existující Waydroid session místo jejího zničení a nového bootu
- dlaždice na Home ukáže stav `POZASTAVENO`, pokud aplikace běží na pozadí
- Home tlačítko na televizích, které ho mají, používá stejné pozastavení; starší TV bez Home používají univerzální 3s Zpět
- explicitní Ukončit zůstává oddělená recovery/správcovská akce; běžný návrat do PiTV už aplikace neukončuje


### PiTV 1.4.23 · 3s Back = vždy zpět do PiTV
- starší TV bez tlačítka Home už nejsou závislé na Home pro opuštění externí aplikace
- krátké Zpět zůstává normální Back uvnitř Kodi, Stremia, SmartTube a dalších aplikací
- podržení Zpět po dobu 3 sekund vždy ukončí právě běžící externí aplikaci a vrátí launcher PiTV
- při držení Back se CEC repeat framy neposílají opakovaně do aplikace; aplikace dostane pouze první krátký Back a PiTV samostatně měří dobu držení
- Android/Waydroid se při nouzovém návratu ukončí včetně Cage session a explicitního `waydroid session stop`
- Kodi/Plex mají tvrdý fallback pro odpojený `kodi.bin`, který se na fyzickém Pi už jednou reparentoval pod PID 1
- nativní Linux Stremio používá při návratu cílený `flatpak kill com.stremio.Stremio`
- stejné 3s gesto funguje i přes USB klávesnici Back/Escape jako servisní fallback


### PiTV 1.4.22 · Waydroid fullscreen isolation
- Android aplikace se už nespouštějí přímo do hlavního labwc compositoru; PiTV používá dokumentovaný Waydroid kiosk/fullscreen model přes nested Cage
- Cage běží jako jediný fullscreen Android povrch uvnitř PiTV a po ukončení aplikace se celý Android compositor/session zavře a vrátí se launcher
- před startem Cage PiTV ukončí starou Waydroid session, aby se nová session svázala se správným nested Wayland socketem
- uvnitř Cage se používá oficiální `waydroid show-full-ui`; poté se explicitně nastaví `persist.waydroid.multi_windows=false` a až pak se spustí SmartTube / APK / Play Store
- přidaný Raspberry Pi preflight: 4 KiB page size a dostupné PSI (`/proc/pressure`) před spuštěním Androidu
- CEC/DPAD relay do Androidu opraven: upstream Waydroid vyžaduje root pro `waydroid shell`, proto PiTV posílá Android keyeventy přes omezený privilegovaný helper
- instalátor přidává `cage`; labwc automaticky maximalizuje nested wlroots/Cage povrch
- změna zachovává nativní Kodi a Linux Stremio přímo v labwc; izolace se týká pouze Waydroid/Android aplikací

### PiTV 1.4.21 · Glass UI + seznamové Nastavení
- Home a Nastavení přepracované podle schváleného mockupu: užší glass sidebar, hlubší navy pozadí, průsvitné panely, jemný sheen, tenké hrany a modrý focus glow
- hero panel má nové proporce, editoriální pravý blok, page dots a nativní planet/space artwork bez těžkého obrázkového pozadí
- domovské dlaždice mají jednotnější proporce, sheen a glass focus halo
- Nastavení je nové třísloupcové TV rozhraní: kategorie, detail a živý preview/help panel
- Vzhled nabízí Motiv, Barevný akcent, Velikost dlaždic, Rozložení plochy, Popisky ikon, Hustotu obsahu a Hodiny
- hodnoty se už nepřepínají naslepo šipkami: OK / → otevře viditelný Kodi-style seznam a ✓ označí aktivní volbu
- stejný seznamový model je použit i pro Spořič obrazovky a HDMI audio výstup
- zachované jsou funkční PiTV 1.4.20 odinstalace aplikací a dosavadní CEC/media architektura

### PiTV 1.4.20 · Odinstalace aplikací
- Nastavení → Aplikace: šipka doprava otevře potvrzení pro bezpečné odinstalování vybrané aplikace
- Android / APK: nalezené APK lze odinstalovat přímo z TV; PiTV odebere Waydroid package, spravovaný APK soubor i odpovídající Store receipt
- nativní Linux Stremio lze odebrat jako system Flatpak; Kodi jako povolený APT Store balíček
- ochrana brání odebrání systémových Android balíčků/GApps, ale dovolí běžné PiTV Google Play aplikace
- legacy Android Stremio se podle package ID neplete s dnešním nativním Linux Stremio jen kvůli stejnému názvu

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
