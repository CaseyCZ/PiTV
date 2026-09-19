#!/usr/bin/env python3
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

SYSTEM_CATALOG = Path("/etc/pitv/store/catalog.json")
BUNDLED_CATALOG = Path(__file__).resolve().parent.parent / "store" / "catalog.json"
USER_APK_DIR = Path.home() / "PiTV" / "APKs"
RECEIPT_DIR = Path.home() / ".local" / "share" / "pitv" / "store"
MAX_APK_BYTES = 1024 * 1024 * 1024


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(path, expected, required=False):
    expected = str(expected or "").strip().lower()
    if expected.startswith("sha256:"):
        expected = expected.split(":", 1)[1]
    if not expected:
        if required:
            raise RuntimeError("Store zdroj nemá povinný SHA-256 otisk")
        return _sha256_file(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("Store zdroj má neplatný SHA-256 otisk")
    actual = _sha256_file(path)
    if actual != expected:
        try:
            Path(path).unlink()
        except Exception:
            pass
        raise RuntimeError("SHA-256 staženého APK nesouhlasí")
    return actual


def _read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def load_store_catalog():
    for p in (SYSTEM_CATALOG, BUNDLED_CATALOG):
        if p.exists():
            data = _read_json(p, {})
            return list(data.get("apps", []))
    return []


def apt_installed(package):
    if not package:
        return False
    try:
        p = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", package],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=5, check=False,
        )
        return p.returncode == 0 and "install ok installed" in p.stdout
    except Exception:
        return False


def _waydroid_packages():
    if shutil.which("waydroid") is None:
        return set()
    try:
        p = subprocess.run(
            ["waydroid", "app", "list"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=10, check=False,
        )
        packages = set()
        for line in p.stdout.splitlines():
            m = re.search(r"package(?:Name)?\s*[:=]\s*([A-Za-z0-9_.]+)", line, re.I)
            if m:
                packages.add(m.group(1))
            elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", line.strip()):
                packages.add(line.strip())
        return packages
    except Exception:
        return set()


def _receipt_path(store_id):
    return RECEIPT_DIR / f"{store_id}.json"


def read_receipt(store_id):
    return _read_json(_receipt_path(store_id), {})


def write_receipt(store_id, **values):
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    data = read_receipt(store_id)
    data.update(values)
    _receipt_path(store_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def store_state(item):
    installer = item.get("installer", {})
    kind = installer.get("type")
    if kind == "apt":
        return "installed" if apt_installed(installer.get("package", "")) else "available"
    if kind == "flatpak":
        app_id = installer.get("app_id", "")
        if not app_id or shutil.which("flatpak") is None:
            return "available"
        p = subprocess.run(["flatpak", "info", "--system", app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        return "installed" if p.returncode == 0 else "available"
    if kind in ("github_release_apk", "direct_apk"):
        receipt = read_receipt(item.get("id", ""))
        package = receipt.get("package", "")
        # A successful PiTV install writes an installation receipt.  Do not
        # downgrade that state merely because Waydroid is stopped: in that
        # state `waydroid app list` may return no packages at all, which used
        # to make Store offer INSTALOVAT again immediately after success.
        if receipt.get("installed") and package:
            return "installed"
        if package and package in _waydroid_packages():
            return "installed"
        path = receipt.get("path", "")
        if path and Path(path).is_file():
            return "downloaded"
        return "available"
    if kind == "play_store":
        package = installer.get("package", "")
        return "installed" if package and package in _waydroid_packages() else "available"
    if kind == "kodi_addon":
        addon_id = installer.get("addon_id", "")
        if not addon_id:
            return "unsupported"
        candidates = [
            Path.home() / ".kodi" / "addons" / addon_id / "addon.xml",
            Path("/usr/share/kodi/addons") / addon_id / "addon.xml",
        ]
        return "installed" if any(p.is_file() for p in candidates) else "available"
    return "unsupported"


def _github_latest_release(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PiTV-Store/1.3",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download_github_apk(item, progress=None):
    installer = item.get("installer", {})
    repo = installer.get("repo", "")
    pattern = installer.get("asset_regex", "")
    if not repo or not pattern:
        raise RuntimeError("Store položka nemá platný GitHub zdroj")

    release = _github_latest_release(repo)
    rx = re.compile(pattern, re.I)
    asset = next((a for a in release.get("assets", []) if rx.search(a.get("name", ""))), None)
    if not asset:
        raise RuntimeError("V posledním release nebylo nalezeno vhodné APK")

    url = asset.get("browser_download_url", "")
    name = asset.get("name", "app.apk")
    if not url:
        raise RuntimeError("Release nemá download URL")

    USER_APK_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", item.get("id", "app"))
    dest = USER_APK_DIR / f"store-{safe_id}-{name}"
    tmp = dest.with_suffix(dest.suffix + ".part")

    req = urllib.request.Request(url, headers={"User-Agent": "PiTV-Store/1.3"})
    with urllib.request.urlopen(req, timeout=60) as src, open(tmp, "wb") as out:
        total = int(src.headers.get("Content-Length", "0") or 0)
        if total and total > MAX_APK_BYTES:
            raise RuntimeError("APK je neočekávaně velké")
        done = 0
        while True:
            chunk = src.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if done > MAX_APK_BYTES:
                raise RuntimeError("APK překročilo bezpečný limit velikosti")
            if progress and total:
                progress(done, total)

    tmp.replace(dest)
    digest = asset.get("digest", "")
    sha256 = _verify_sha256(dest, digest, required=False)
    write_receipt(
        item.get("id", ""),
        path=str(dest),
        version=release.get("tag_name", ""),
        asset=name,
        source=repo,
        sha256=sha256,
        verified_digest=bool(digest),
    )
    return dest, release.get("tag_name", "")


def download_direct_apk(item, progress=None):
    installer = item.get("installer", {})
    url = installer.get("url", "")
    if not url.lower().startswith("https://"):
        raise RuntimeError("PiTV Store povoluje pouze HTTPS APK zdroje")

    version = str(installer.get("version", ""))
    expected_sha256 = str(installer.get("sha256", "")).strip()
    if not expected_sha256:
        raise RuntimeError("Přímý APK zdroj musí mít v katalogu SHA-256")
    filename = installer.get("filename", "") or Path(url).name or "app.apk"
    if not filename.lower().endswith(".apk"):
        raise RuntimeError("Store zdroj není APK")

    USER_APK_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", item.get("id", "app"))
    dest = USER_APK_DIR / f"store-{safe_id}-{filename}"
    tmp = dest.with_suffix(dest.suffix + ".part")

    req = urllib.request.Request(url, headers={"User-Agent": "PiTV-Store/1.3"})
    with urllib.request.urlopen(req, timeout=60) as src, open(tmp, "wb") as out:
        total = int(src.headers.get("Content-Length", "0") or 0)
        done = 0
        while True:
            chunk = src.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done, total)

    tmp.replace(dest)
    sha256 = _verify_sha256(dest, expected_sha256, required=True)
    write_receipt(
        item.get("id", ""),
        path=str(dest),
        version=version,
        source=url,
        sha256=sha256,
        verified_digest=True,
    )
    return dest, version


def mark_android_installed(item, package, path, version=""):
    write_receipt(
        item.get("id", ""),
        package=package,
        path=str(path),
        version=version,
        installed=True,
    )
