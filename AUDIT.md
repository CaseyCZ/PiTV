# PiTV 1.3 — audit

Datum auditu: **2026-09-19**  
Aktivní repozitář: **`CaseyCZ/PiTV`**, větev **`Master`**

## Výsledek

Aktuální PiTV 1.3 prošlo statickou kontrolou, runtime render testem a kompletním online smoke testem na Ubuntu 24.04 **x64 i ARM64**.

## Opravy provedené během auditu

- opravená navigace mřížek Home, PiTV Store, Server Store a Aktualizace,
- funkční focus a navigace levého sidebaru,
- CEC čtení převedeno na správný debug level,
- příjem i odesílání CEC sjednoceno do jednoho persistentního klienta,
- opravené probuzení TV po CEC standby,
- spořič se pozastaví během Kodi/Android foreground aplikace,
- Waydroid + Google Play lze nainstalovat přímo z PiTV UI,
- přidaný ARM64 Waydroid fallback snapshot pro případ výpadku `repo.waydro.id`, včetně SHA-256 ověření a automatické týdenní aktualizace,
- Google Play deep-link pro YouTube/Spotify/Plex používá omezený privilegovaný helper,
- SmartTube APK má kontrolu očekávaného package ID; Stremio používá nativní Linux Flatpak,
- zpřísněný APT allowlist,
- bezpečnější temp soubory Homebridge/Tailscale/Waydroid installerů,
- odstranění starých systémových app definic při update,
- zachování uživatelských app definic a nastavení,
- self-update a uninstall ověřené online,
- dokumentace sjednocená s PiTV 1.3.

## Online smoke test — PASS

Ověřeno:

- Ubuntu 24.04 x64: install → render → run → Kodi → catalogs → self-update → rerun → uninstall,
- Ubuntu 24.04 ARM64: stejný install/run/update/uninstall flow,
- ARM64 Server Store: Homebridge, Tailscale, Docker, ATVLoadly,
- ARM64 Android Store source: SmartTube download + `aapt` package kontrola; Stremio je Linux Flatpak,
- obě témata: PiTV Apple Dark + Light,
- všechny UI stránky,
- sudoers a instalované helpery.

## Zbývající hardware test

Nelze věrohodně simulovat v GitHub Actions:

1. Raspberry Pi 4 DRM/KMS + HDMI obraz,
2. fyzický HDMI-CEC adaptér a konkrétní TV,
3. HDMI audio a konkrétní receiver/TV,
4. Kodi VA/V4L2 hardware decode,
5. Waydroid binder/kernel/GPU na konkrétním Pi image,
6. skutečný Google Play login/certifikace zařízení.

Tyto body jsou poslední část před označením Raspberry Pi 4 build jako hardware-verified.

## Windows SD Installer — stabilizační audit

Po prvních fyzických testech na Windows byl SD Installer přezkoumán jako samostatný destruktivní nástroj, ne jen jako GUI skript.

Ověřeno / zpřísněno:

- Raspberry Pi Imager CLI parametry se kontrolují proti aktuálně instalované verzi,
- Alpha release se publikuje až po Windows integrační validaci,
- aktuální Ubuntu katalog se testuje online,
- cílový disk se před formátem/zápisem znovu ověřuje podle čísla, kapacity, názvu a pokud Windows poskytne také `UniqueId` / `SerialNumber`,
- systémový/boot disk je blokovaný fail-closed filtrem,
- externí instalace mají timeout,
- stderr Raspberry Pi Imageru jde do diagnostického logu,
- posledních 5 lokálních logů se rotuje a GitHub error report rediguje citlivé údaje.

Projekt Rufus (`pbatard/rufus`) byl použit pouze jako architektonická reference pro bezpečné zacházení s fyzickými disky, retry/error reporting a konzervativní UX. **Žádný Rufus GPLv3 kód není součástí PiTV**; PiTV zůstává pod MIT licencí.

## Rizika / další doporučení

- **Self-update:** aktuálně důvěřuje mutable GitHub větvi a spouští stažený installer jako root. Pro veřejné release je vhodné přejít na tag/release + checksum/signature.
- **Branch protection:** `Master` není chráněná. Pro veřejnou distribuci doporučeno vyžadovat PiTV Check před změnou release větve.
- **Waydroid:** instalace balíčků má vlastní fallback mimo `repo.waydro.id`, ale první `waydroid init` stále závisí na dostupnosti Android image zdrojů; cloud ARM64 runner neověřuje Android runtime na Raspberry Pi GPU/kernelu.
- **CEC:** implementace odpovídá libCEC chování, ale CEC se mezi výrobci TV liší.

## CI

- `PiTV Check` — rychlá automatická kontrola při push.
- `PiTV Online Smoke` — ruční plný instalační test.
- `Waydroid Fallback Mirror` — týdenní obnova ARM64/Noble fallback balíčků z oficiálního Waydroid repozitáře.


## Repo hygiene

- aktivní PiTV repo: `CaseyCZ/PiTV` / `Master`,
- žádné nalezené hardcoded tokeny, privátní klíče ani credentials,
- CI workflow používají minimální `contents: read` oprávnění a concurrency,
- README profilu CZ/EN odkazuje na samostatný repozitář `CaseyCZ/PiTV`.

## Kontrola externích Store zdrojů

K 2026-09-19:

- Stremio: aktuální PiTV katalog používá nativní Linux Flatpak `com.stremio.Stremio`; staré Android Stremio není součástí současného Store katalogu.
- SmartTube: katalog používá dynamický latest-release lookup; aktuální stable release 32.47 obsahuje `SmartTube_stable_32.47_arm64-v8a.apk`.
