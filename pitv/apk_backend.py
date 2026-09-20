#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

SYSTEM_APK_DIR = Path('/var/lib/pitv/apks')
USER_APK_DIR = Path.home() / 'PiTV' / 'APKs'


def _run(args, timeout=15):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or '').strip()
    except Exception:
        return 127, ''


def inspect_apk(path):
    path = Path(path)
    meta = {
        'name': path.stem,
        'package': '',
        'activity': '',
        'version': '',
        'sdk': '',
        'tv': False,
        'abis': [],
        'path': str(path),
    }
    if not path.is_file():
        return meta
    aapt = shutil.which('aapt')
    if not aapt:
        return meta
    rc, out = _run([aapt, 'dump', 'badging', str(path)], timeout=20)
    if rc != 0:
        return meta
    m = re.search(r"^package: name='([^']+)'(?: versionCode='[^']*')? versionName='([^']*)'", out, re.M)
    if m:
        meta['package'] = m.group(1)
        meta['version'] = m.group(2)
    else:
        m = re.search(r"^package: name='([^']+)'", out, re.M)
        if m: meta['package'] = m.group(1)
    m = re.search(r"^application-label(?:-[^:]+)?:'([^']+)'", out, re.M)
    if m and m.group(1).strip(): meta['name'] = m.group(1).strip()
    m = re.search(r"^launchable-activity: name='([^']+)'", out, re.M)
    if m: meta['activity'] = m.group(1)
    m = re.search(r"^sdkVersion:'([^']+)'", out, re.M)
    if m: meta['sdk'] = m.group(1)
    low = out.lower()
    meta['tv'] = ('leanback' in low or 'android.software.leanback' in low or
                  'android.hardware.type.television' in low)
    m = re.search(r"^native-code:\s*(.+)$", out, re.M)
    if m:
        meta['abis'] = re.findall(r"'([^']+)'", m.group(1))
    return meta


def discover_apks():
    seen = set()
    items = []
    for folder in (SYSTEM_APK_DIR, USER_APK_DIR):
        if not folder.exists():
            continue
        for p in sorted(folder.glob('*.apk')):
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in seen:
                continue
            seen.add(key)
            meta = inspect_apk(p)
            package = meta.get('package') or p.stem
            items.append({
                'name': meta.get('name') or p.stem,
                'subtitle': ('Android TV APK' if meta.get('tv') else 'Android APK'),
                'icon': 'APK',
                'kind': 'apk',
                'apk_path': str(p),
                'package': package,
                'activity': meta.get('activity',''),
                'version': meta.get('version',''),
                'sdk': meta.get('sdk',''),
                'tv': bool(meta.get('tv')),
            })
    return items


def waydroid_available():
    return shutil.which('waydroid') is not None


def waydroid_status():
    if not waydroid_available():
        return 'nenainstalován'
    rc, out = _run(['waydroid', 'status'], timeout=5)
    if not out:
        return 'neaktivní'
    for line in out.splitlines():
        if 'Session:' in line:
            return line.split(':',1)[1].strip().lower()
    return 'dostupný'


def waydroid_packages():
    if not waydroid_available():
        return set()

    helper = Path('/usr/local/libexec/pitv-helper')
    if helper.is_file() and shutil.which('sudo'):
        try:
            p = subprocess.run(
                ['sudo', '-n', str(helper), 'waydroid-packages'],
                input='{}',
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=25,
                check=False,
            )
            if p.returncode == 0:
                return {
                    line.strip()
                    for line in (p.stdout or '').splitlines()
                    if re.fullmatch(
                        r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+',
                        line.strip(),
                    )
                }
        except Exception:
            pass

    # Development/non-PiTV fallback. The GUI-facing list is less authoritative
    # than Android PackageManager but keeps local tooling useful off-device.
    rc, out = _run(['waydroid', 'app', 'list'], timeout=10)
    if rc != 0:
        return set()
    packages = set()
    for line in out.splitlines():
        m = re.search(r'package(?:Name)?\s*[:=]\s*([A-Za-z0-9_.]+)', line, re.I)
        if m:
            packages.add(m.group(1))
        elif re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', line.strip()):
            packages.add(line.strip())
    return packages


def ensure_apk_installed(app):
    if not waydroid_available():
        return False, 'Waydroid není nainstalovaný'
    package = app.get('package','')
    apk = app.get('apk_path','')
    if package and package in waydroid_packages():
        return True, 'APK je už nainstalované'
    if not apk or not Path(apk).is_file():
        return False, 'APK soubor nebyl nalezen'
    rc, out = _run(['waydroid', 'app', 'install', apk], timeout=120)
    if rc != 0:
        return False, out[-250:] if out else 'Instalace APK selhala'

    # waydroid app install can report success before the desktop-app cache sees
    # the package. Verify against Android PackageManager, not the GUI app list.
    if package:
        for _ in range(10):
            if package in waydroid_packages():
                return True, f"{app.get('name','APK')} nainstalováno"
            time.sleep(0.25)
        return False, f"{app.get('name','APK')}: Android package po instalaci stále chybí"

    return True, f"{app.get('name','APK')} nainstalováno"


def tailscale_info():
    if shutil.which('tailscale') is None:
        return ('nenainstalován', '')
    rc, ip = _run(['tailscale', 'ip', '-4'], timeout=3)
    rc2, status = _run(['tailscale', 'status', '--self'], timeout=4)
    state = 'připojeno' if rc == 0 and ip else 'nepřipojeno'
    return state, ip.splitlines()[0].strip() if ip else ''
