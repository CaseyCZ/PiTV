# PiTV SD Installer — Windows

Malé grafické rozhraní pro vytvoření PiTV microSD bez ruční instalace Ubuntu, nastavování Wi-Fi nebo kopírování příkazů přes SSH.

## Spuštění

1. stáhni z GitHub Releases ZIP **PiTV-SD-Installer-Windows.zip** a rozbal celý obsah,
2. vlož microSD do čtečky,
3. spusť **Start-PiTV-SD-Installer.cmd**,
4. potvrď UAC,
5. vyber Raspberry Pi — Pi 4 je doporučený,
6. nech doporučenou online Ubuntu image, nebo zvol **Vlastní image...**,
7. vyber microSD,
8. zkontroluj nebo zadej Wi-Fi a klikni na **VYTVOŘIT PiTV SD**.

Pokud chceš kartu pouze vrátit do běžného stavu, použij **NAFORMÁTOVAT SD**. Installer smaže staré oddíly a vytvoří jeden exFAT oddíl `SDCARD` přes dostupnou kapacitu.

## Jak funguje online image

Installer načte aktuální oficiální katalog, najde Ubuntu Server 24.04 LTS ARM64 kompatibilní se zvoleným Raspberry Pi a image stáhne jen tehdy, když ještě není uložená v počítači.

Stažené komprimované image se ukládají mimo instalační ZIP do:

`%LOCALAPPDATA%\PiTV\images`

Aktualizace PiTV Installeru tuto cache nemaže. Pokud je v katalogu stále stejná image a její velikost / SHA-256 souhlasí, další vytvoření SD přeskočí stahování a použije lokální kopii. Novější vydání image dostane nový soubor a stáhne se automaticky.

Nedokončené soubory používají příponu `.part` a nepovažují se za platnou cache.

## Vlastní image

Tlačítko **Vlastní image...** je rychlejší režim pro uživatele, kteří už image mají staženou.

Podporované vstupy:

- `.img` — jde rovnou do kontroly a zápisu,
- `.img.xz` / `.xz` — rozbalí se přiloženým malým `PiTV-XZ.exe` postaveným nad `liblzma`,
- `.zip` — musí obsahovat právě jeden `.img` soubor.

Vlastní image musí být kompatibilní se zvoleným Raspberry Pi a s cloud-init, pokud má automaticky fungovat Wi-Fi a první instalace PiTV.

## Co udělá automaticky

- nabídne pouze bezpečné výměnné USB / SD / MMC disky,
- vyloučí Disk 0 a disk s Windows boot/system partition,
- nabídne Pi 3 / 3B+, Pi 4 a Pi 5; Pi 4 je výchozí doporučený model,
- najde správnou Ubuntu Server 24.04 LTS ARM64 image v aktuálním oficiálním katalogu,
- použije trvalou lokální cache a nestahuje stejnou ověřenou image znovu,
- zkontroluje velikost a dostupný SHA-256 stažené image,
- rozbalí image do dočasného raw `.img`,
- zapíše image přímo na `\\.\PhysicalDriveN` vlastním PiTV raw writerem,
- po zápisu vyžádá od Windows skutečný `FlushFileBuffers`, přečte stejné bajty zpět z karty a porovná SHA-256,
- počká na stabilní re-enumeraci SD/USB zařízení; při transientní chybě umí provést omezený `diskpart rescan`,
- znovu načte boot oddíl a vloží `user-data`, `network-config` a podle potřeby `meta-data` s durable flush + read-back kontrolou,
- finalize fázi při chybě automaticky zopakuje až 3×, takže běžný post-write race už nemá vyžadovat ruční **OPRAVIT / DOPLNIT PiTV**,
- vyhledá dostupné Wi-Fi sítě a spojí je s uloženými Windows profily,
- u známé sítě se pokusí načíst uložené heslo; SSID i heslo lze vždy zadat ručně,
- vytvoří silné náhodné recovery heslo pro `pitvadmin`,
- při prvním bootu stáhne `CaseyCZ/PiTV`, spustí `install.sh` a Raspberry restartuje,
- po úspěšné první instalaci odstraní dočasné `user-data` a `network-config` z boot oddílu.

Po vytvoření karty se recovery heslo zkopíruje do schránky.

## Co už není potřeba

PiTV SD Installer už **nepoužívá ani neinstaluje Raspberry Pi Imager**. Zápis provádí vlastní modul `PiTV-ImageEngine.ps1` přes Windows raw-disk API.

Pro rozbalení XZ používá přiložený `PiTV-XZ.exe`; uživatel nemusí instalovat žádný další program. `PiTV-XZ.exe` používá `liblzma` z XZ Utils (0BSD); informace o licenci jsou v `THIRD-PARTY-NOTICES.txt`.

## Bezpečnost

Před destruktivní operací Installer znovu ověří číslo disku, model, kapacitu a dostupnou identitu cílové karty. Systémový disk a boot disk Windows se nenabízejí.

Přesto vždy zkontroluj, že je vybraná správná microSD — cílový disk bude kompletně přepsán.

## Diagnostika

Okno zobrazuje aktuální fázi a progress. Kompletní log se ukládá do:

`%LOCALAPPDATA%\PiTV\SD-Installer\logs`

Při chybě se zapisuje typ výjimky, zpráva, HResult, PowerShell error ID, kategorie, stack trace, řádek a příkaz. Tlačítko **ODESLAT CHYBU** připraví zkrácený report a před odesláním skryje nalezená SSID.

## Stav

Aktuálně jde o **v0.28 alpha**.

GitHub Actions na Windows kontrolují:

- PowerShell syntaxi hlavního installeru i image enginu,
- živý Ubuntu katalog pro Pi 3 / 4 / 5,
- že se `PiTV-XZ.exe` na Windows úspěšně sestaví a byte-perfect rozbalí testovací raw XZ stream,
- že aplikace neobsahuje starou závislost na Raspberry Pi Imageru,
- že release ZIP obsahuje nový zapisovací engine.

Skutečný zápis na fyzickou microSD a první boot je dál potřeba ověřovat na reálném hardware.

- vlastní PiTV uživatel a heslo se zadávají přímo v installeru před zápisem
