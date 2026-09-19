#!/usr/bin/env python3
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import re
from pathlib import Path

import pygame
from apk_backend import (discover_apks, ensure_apk_installed, inspect_apk,
                         waydroid_available, waydroid_packages, waydroid_status,
                         tailscale_info)
from store_backend import (download_direct_apk, download_github_apk,
                           load_store_catalog, mark_android_installed,
                           store_state)
from update_backend import is_newer, remote_pitv_version

APP_NAME = "PiTV"
VERSION = "1.4.11"

SYSTEM_CONFIG = Path("/etc/pitv/config.json")
USER_CONFIG = Path.home() / ".config/pitv/config.json"
SYSTEM_APPS = Path("/etc/pitv/apps.d")
USER_APPS = Path.home() / ".config/pitv/apps.d"
SYSTEM_SERVER_CATALOG = Path("/etc/pitv/store/server_catalog.json")
BUNDLED_SERVER_CATALOG = Path(__file__).resolve().parent.parent / "store" / "server_catalog.json"
LAUNCH_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "pitv-launch.json"

DEFAULT_CONFIG = {
    "theme": "apple_dark",
    "accent": "blue",
    "tile_scale": 1.0,
    "cec_enabled": True,
    "cec_wake_on_start": False,
    "show_clock": True,

    # PiTV runs 24/7. These values only control the HDMI/UI idle state.
    "screensaver_enabled": True,
    "screensaver_after_min": 5,
    "screensaver_mode": "clock",
    "screensaver_black_after_min": 15,
    "screensaver_cec_standby_after_min": 30,

    # HDMI is the only PiTV audio path.
    "hdmi_audio_port": "auto",
    "hidden_apps": [],
}

THEMES = {
    "apple_dark": {
        # CaseyCZ / iOS Hub palette
        "page": (7, 11, 20),          # #070b14
        "bg": (11, 16, 32),           # #0b1020
        "panel": (17, 24, 39),        # #111827
        "panel2": (23, 32, 51),       # #172033
        "input": (11, 18, 32),        # #0b1220
        "border": (42, 56, 80),       # #2a3850
        "text": (248, 250, 252),      # #f8fafc
        "muted": (148, 163, 184),     # #94a3b8
        "accent": (56, 189, 248),     # #38bdf8
        "accent2": (2, 132, 199),     # #0284c7
        "action": (3, 118, 181),      # #0376b5
        "action2": (7, 89, 133),      # #075985
        "accent_soft": (15, 43, 69),  # #0f2b45
        "good": (134, 239, 172),      # #86efac
        "warn": (253, 230, 138),      # #fde68a
        "bad": (252, 165, 165),       # #fca5a5
        "hero": (23, 37, 84),         # #172554
    },
    "apple_light": {
        "page": (238, 243, 248),      # #eef3f8
        "bg": (248, 250, 252),        # #f8fafc
        "panel": (255, 255, 255),     # #ffffff
        "panel2": (241, 245, 249),    # #f1f5f9
        "input": (248, 250, 252),     # #f8fafc
        "border": (215, 224, 235),    # #d7e0eb
        "text": (15, 23, 42),         # #0f172a
        "muted": (100, 116, 139),     # #64748b
        "accent": (3, 105, 161),      # #0369a1
        "accent2": (7, 89, 133),      # #075985
        "action": (3, 118, 181),
        "action2": (7, 89, 133),
        "accent_soft": (224, 242, 254),# #e0f2fe
        "good": (21, 128, 61),        # #15803d
        "warn": (146, 64, 14),        # #92400e
        "bad": (185, 28, 28),         # #b91c1c
        "hero": (219, 234, 254),      # #dbeafe
    },
}

PITV_KEY_VOLUMEUP = 0x70000001
PITV_KEY_VOLUMEDOWN = 0x70000002
PITV_KEY_MUTE = 0x70000003

CEC_MAP = {
    "up": pygame.K_UP,
    "down": pygame.K_DOWN,
    "left": pygame.K_LEFT,
    "right": pygame.K_RIGHT,
    "select": pygame.K_RETURN,
    "enter": pygame.K_RETURN,
    "exit": pygame.K_ESCAPE,
    "back": pygame.K_ESCAPE,
    "root menu": pygame.K_HOME,
    "contents menu": pygame.K_HOME,
    "top menu": pygame.K_HOME,
    "home": pygame.K_HOME,
    "return": pygame.K_ESCAPE,
    "play": pygame.K_SPACE,
    "pause": pygame.K_SPACE,
    "play / pause": pygame.K_SPACE,
    "volume up": PITV_KEY_VOLUMEUP,
    "volume down": PITV_KEY_VOLUMEDOWN,
    "mute": PITV_KEY_MUTE,
}

# HDMI-CEC UI command operand values from the Linux CEC UAPI.  Keep a numeric
# fallback because cec-ctl's human-readable labels can vary slightly by
# v4l-utils version while the wire values are stable.
CEC_CODE_MAP = {
    0x00: pygame.K_RETURN,   # Select / OK
    0x01: pygame.K_UP,
    0x02: pygame.K_DOWN,
    0x03: pygame.K_LEFT,
    0x04: pygame.K_RIGHT,
    0x09: pygame.K_HOME,     # Device Root Menu
    0x0B: pygame.K_HOME,     # Contents Menu
    0x0D: pygame.K_ESCAPE,   # Back
    0x10: pygame.K_HOME,     # Media Top Menu
    0x2B: pygame.K_RETURN,   # Enter
    0x32: pygame.K_ESCAPE,   # Previous Channel: common Back fallback
    0x41: PITV_KEY_VOLUMEUP,
    0x42: PITV_KEY_VOLUMEDOWN,
    0x43: PITV_KEY_MUTE,
    0x44: pygame.K_SPACE,
    0x46: pygame.K_SPACE,
}


def normalize_input_key(key):
    """Normalize SDL/Linux media-remote keys to PiTV navigation keys."""
    if key == pygame.K_BACKSPACE:
        return pygame.K_ESCAPE
    try:
        name = pygame.key.name(key).strip().lower().replace("_", " ").replace("-", " ")
    except Exception:
        name = ""
    aliases = {
        "ac back": pygame.K_ESCAPE,
        "back": pygame.K_ESCAPE,
        "escape": pygame.K_ESCAPE,
        "browser back": pygame.K_ESCAPE,
        "select": pygame.K_RETURN,
        "ok": pygame.K_RETURN,
        "enter": pygame.K_RETURN,
        "return": pygame.K_RETURN,
        "kp enter": pygame.K_RETURN,
        "keypad enter": pygame.K_RETURN,
        "home": pygame.K_HOME,
        "ac home": pygame.K_HOME,
        "browser home": pygame.K_HOME,
    }
    return aliases.get(name, key)


def safe_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback.copy() if isinstance(fallback, dict) else list(fallback)


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    for p in (SYSTEM_CONFIG, USER_CONFIG):
        if p.exists():
            cfg.update(safe_json(p, {}))

    # Normalize persisted settings. Old/manual configs must never be able to
    # push TV layout or timers outside values the Settings UI can represent.
    theme = {"dark": "apple_dark", "light": "apple_light"}.get(
        cfg.get("theme"), cfg.get("theme")
    )
    if theme not in THEMES:
        theme = DEFAULT_CONFIG["theme"]
    cfg["theme"] = theme

    try:
        scale = float(cfg.get("tile_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    scales = [0.85, 1.0, 1.15]
    cfg["tile_scale"] = min(scales, key=lambda value: abs(value - scale))

    if not isinstance(cfg.get("show_clock"), bool):
        cfg["show_clock"] = DEFAULT_CONFIG["show_clock"]
    if not isinstance(cfg.get("screensaver_enabled"), bool):
        cfg["screensaver_enabled"] = DEFAULT_CONFIG["screensaver_enabled"]
    if not isinstance(cfg.get("cec_enabled"), bool):
        cfg["cec_enabled"] = DEFAULT_CONFIG["cec_enabled"]
    if not isinstance(cfg.get("cec_wake_on_start"), bool):
        cfg["cec_wake_on_start"] = DEFAULT_CONFIG["cec_wake_on_start"]

    def normalized_int(name, values):
        try:
            current = int(cfg.get(name, DEFAULT_CONFIG[name]))
        except (TypeError, ValueError):
            current = int(DEFAULT_CONFIG[name])
        cfg[name] = min(values, key=lambda value: abs(value - current))

    normalized_int("screensaver_after_min", [1, 2, 5, 10, 15, 30, 60])
    normalized_int("screensaver_black_after_min", [0, 10, 15, 30, 60, 120])
    normalized_int("screensaver_cec_standby_after_min", [0, 15, 30, 60, 120, 240])

    if cfg.get("screensaver_mode") not in ("clock", "black"):
        cfg["screensaver_mode"] = DEFAULT_CONFIG["screensaver_mode"]
    if str(cfg.get("hdmi_audio_port", "auto")) not in ("auto", "0", "1"):
        cfg["hdmi_audio_port"] = DEFAULT_CONFIG["hdmi_audio_port"]
    else:
        cfg["hdmi_audio_port"] = str(cfg.get("hdmi_audio_port", "auto"))

    hidden = cfg.get("hidden_apps", [])
    cfg["hidden_apps"] = [str(x) for x in hidden] if isinstance(hidden, list) else []
    return cfg


def save_user_config(cfg):
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_server_catalog():
    for path in (SYSTEM_SERVER_CATALOG, BUNDLED_SERVER_CATALOG):
        if path.exists():
            data = safe_json(path, {})
            if isinstance(data, dict):
                return list(data.get("services", []))
    return []


def cmd_output(args, timeout=2):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, timeout=timeout, check=False)
        return p.stdout.strip()
    except Exception:
        return ""


def available_command(command):
    if not command:
        return False
    first = command.split()[0]
    if first.startswith("/"):
        return Path(first).exists()
    return shutil.which(first) is not None


def load_apps():
    apps = []
    for folder in (SYSTEM_APPS, USER_APPS):
        if not folder.exists():
            continue
        for p in sorted(folder.glob("*.json")):
            data = safe_json(p, {})
            if not data or not data.get("name") or not data.get("command"):
                continue
            if data.get("hidden", False):
                continue
            data.setdefault("kind", "linux")
            required = data.get("requires") or data["command"].split()[0]
            if available_command(required):
                apps.append(data)

    apk_apps = discover_apks()
    apps.extend(apk_apps)

    # Apps installed directly from Google Play have no APK in PiTV's watched
    # folders. Surface supported catalog packages as normal launcher tiles.
    installed_packages = waydroid_packages() if waydroid_available() else set()
    known_packages = {a.get("package", "") for a in apk_apps if a.get("package")}
    if installed_packages:
        for item in load_store_catalog():
            installer = item.get("installer", {})
            if installer.get("type") != "play_store":
                continue
            package = installer.get("package", "")
            if not package or package not in installed_packages or package in known_packages:
                continue
            apps.append({
                "name": item.get("name", package),
                "subtitle": "Android TV · Google Play",
                "icon": item.get("icon", "APK"),
                "kind": "apk",
                "apk_path": "",
                "package": package,
                "activity": "",
                "version": "",
                "sdk": "",
                "tv": True,
            })
    return apps


def get_ipv4():
    raw = cmd_output(["ip", "-j", "-4", "addr", "show"])
    try:
        rows = json.loads(raw)
        out = []
        for row in rows:
            if row.get("ifname") == "lo":
                continue
            for a in row.get("addr_info", []):
                if a.get("scope") == "global":
                    out.append((row.get("ifname", "?"), a.get("local", "?")))
        return out
    except Exception:
        return []


def get_default_route():
    return cmd_output(["ip", "route", "show", "default"]) or "není"


def get_wifi():
    if shutil.which("nmcli"):
        s = cmd_output(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])
        for line in s.splitlines():
            if line.startswith("yes:"):
                parts = line.split(":")
                return f"{parts[1]} ({parts[2]} %)" if len(parts) >= 3 else parts[1]
    return "—"


def get_temp():
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return f"{int(p.read_text().strip()) / 1000:.1f} °C"
    except Exception:
        return "—"


def get_model():
    p = Path("/proc/device-tree/model")
    try:
        return p.read_bytes().rstrip(b"\x00").decode(errors="replace")
    except Exception:
        return "Linux"


def get_mem():
    try:
        data = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            data[k] = int(v.strip().split()[0])
        used = data["MemTotal"] - data["MemAvailable"]
        return f"{used / 1024:.0f} / {data['MemTotal'] / 1024:.0f} MB"
    except Exception:
        return "—"


def get_disk():
    u = shutil.disk_usage("/")
    return f"{(u.total-u.free)/2**30:.1f} / {u.total/2**30:.1f} GB"


def uptime():
    try:
        seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
        d, seconds = divmod(seconds, 86400)
        h, m = divmod(seconds, 3600)[0], (seconds % 3600) // 60
        return (f"{d} d {h} h" if d else f"{h} h {m} min")
    except Exception:
        return "—"



def build_gui_env():
    """Return a normalized environment for children launched inside labwc."""
    env = os.environ.copy()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = runtime
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    env.setdefault("XDG_CURRENT_DESKTOP", "labwc")
    env.setdefault("PULSE_RUNTIME_PATH", str(Path(runtime) / "pulse"))

    display = env.get("WAYLAND_DISPLAY", "")
    display_path = Path(display) if display.startswith("/") else Path(runtime) / display
    if not display or not display_path.is_socket():
        try:
            sockets = [p for p in sorted(Path(runtime).glob("wayland-*")) if p.is_socket()]
        except Exception:
            sockets = []
        if sockets:
            env["WAYLAND_DISPLAY"] = sockets[0].name

    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        bus = Path(runtime) / "bus"
        if bus.is_socket():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return env


def gui_env_error(env):
    runtime = env.get("XDG_RUNTIME_DIR", "")
    display = env.get("WAYLAND_DISPLAY", "")
    if not runtime:
        return "XDG_RUNTIME_DIR není nastavený"
    if not display:
        return "WAYLAND_DISPLAY není nastavený"
    socket_path = Path(display) if display.startswith("/") else Path(runtime) / display
    if not socket_path.is_socket():
        return f"Wayland socket neexistuje: {socket_path}"
    return ""


def tail_text_file(path, max_chars=500):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return ""
        return text[-max_chars:].splitlines()[-1]
    except Exception:
        return ""


def run_privileged(action, payload=None, timeout=600):
    """Run the tightly scoped PiTV root helper."""
    helper = "/usr/local/libexec/pitv-helper"
    if not Path(helper).exists():
        return False, "PiTV system helper není nainstalovaný"
    try:
        p = subprocess.run(
            ["sudo", "-n", helper, action],
            input=json.dumps(payload or {}, ensure_ascii=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        msg = (p.stdout or "").strip()
        return p.returncode == 0, (msg or ("Hotovo" if p.returncode == 0 else "Operace selhala"))
    except subprocess.TimeoutExpired:
        return False, "Operace vypršela"
    except Exception as e:
        return False, f"Chyba: {e}"


def nm_available():
    if shutil.which("nmcli") is None:
        return False
    return cmd_output(["nmcli", "-t", "-f", "RUNNING", "general"], timeout=3).lower() == "running"


def nm_wifi_enabled():
    if not nm_available():
        return None
    out = cmd_output(["nmcli", "-t", "-f", "WIFI", "radio"], timeout=3).lower()
    return out == "enabled"


def split_nmcli(line):
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def list_wifi_networks():
    if not nm_available():
        return []
    try:
        p = subprocess.run(
            ["nmcli", "-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
             "device", "wifi", "list", "--rescan", "yes"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
            check=False,
        )
        nets = {}
        for line in (p.stdout or "").splitlines():
            parts = split_nmcli(line)
            if len(parts) < 4:
                continue
            active, ssid, signal, security = parts[:4]
            if not ssid:
                continue
            try:
                sig = int(signal)
            except Exception:
                sig = 0
            item = {
                "ssid": ssid,
                "signal": sig,
                "security": security or "OPEN",
                "active": active == "*",
            }
            if ssid not in nets or sig > nets[ssid]["signal"]:
                nets[ssid] = item
        return sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"], n["ssid"].lower()))
    except Exception:
        return []


def wifi_device():
    if not nm_available():
        return ""
    out = cmd_output(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], timeout=3)
    for line in out.splitlines():
        p = split_nmcli(line)
        if len(p) >= 2 and p[1] == "wifi":
            return p[0]
    return ""


def get_hdmi_ports():
    ports = []
    for p in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-*")):
        try:
            status = (p / "status").read_text().strip()
        except Exception:
            continue
        m = re.search(r"HDMI-A-(\d+)$", p.name)
        idx = int(m.group(1)) if m else len(ports) + 1
        modes = []
        try:
            modes = [x.strip() for x in (p / "modes").read_text().splitlines() if x.strip()]
        except Exception:
            pass
        ports.append({
            "index": idx,
            "name": f"HDMI {idx}",
            "drm": f"HDMI-A-{idx}",
            "status": status,
            "alsa": f"vc4hdmi{idx-1}",
            "mode": modes[0] if modes else "—",
        })
    return ports


def active_hdmi_audio_device(preference="auto"):
    ports = get_hdmi_ports()
    connected = [p for p in ports if p["status"] == "connected"]
    if preference in ("0", "1"):
        idx = int(preference) + 1
        for p in ports:
            if p["index"] == idx:
                return p
    if connected:
        return connected[0]
    return ports[0] if ports else {
        "index": 1, "name": "HDMI 1", "drm": "HDMI-A-1",
        "status": "unknown", "alsa": "vc4hdmi0", "mode": "—"
    }


def test_hdmi_audio(preference="auto"):
    if shutil.which("speaker-test") is None:
        return False, "speaker-test není nainstalovaný"
    dev = active_hdmi_audio_device(preference)
    alsa = f"sysdefault:CARD={dev['alsa']}"
    try:
        # Short stereo tone; timeout deliberately keeps this TV-friendly.
        p = subprocess.run(
            ["timeout", "2", "speaker-test", "-D", alsa, "-t", "sine", "-f", "440", "-c", "2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            timeout=4,
            check=False,
        )
        # timeout returns 124 after intentionally stopping speaker-test.
        if p.returncode in (0, 124):
            return True, f"Test odeslán přes {dev['name']}"
        return False, f"HDMI audio test selhal ({dev['name']})"
    except Exception as e:
        return False, f"HDMI audio chyba: {e}"


def count_updates():
    if shutil.which("apt") is None:
        return None
    try:
        p = subprocess.run(
            ["apt", "list", "--upgradable"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
            check=False,
        )
        return len([x for x in p.stdout.splitlines()
                    if x.strip() and not x.lower().startswith("listing")])
    except Exception:
        return None

_CEC_MANAGER = None


def cec_available():
    # Input uses the kernel CEC API; libCEC is only an optional output fallback.
    return shutil.which("cec-ctl") is not None and any(Path("/dev").glob("cec*"))


def cec_send(commands):
    """Send CEC output through the same kernel CEC stack used for input."""
    if not cec_available():
        return False, "cec-ctl nebo CEC adaptér není dostupný"
    if isinstance(commands, str):
        commands = [commands]

    device = None
    if _CEC_MANAGER is not None and _CEC_MANAGER.device is not None:
        device = str(_CEC_MANAGER.device)
    if not device:
        devices = sorted(Path("/dev").glob("cec*"))
        if devices:
            device = str(devices[0])
    if not device:
        return False, "CEC adaptér nebyl nalezen"

    modes = {
        "on 0": "on",
        "as": "active",
        "standby 0": "standby",
        "volup": "volup",
        "voldown": "voldown",
        "mute": "mute",
    }
    outputs = []
    for command in commands:
        mode = modes.get(str(command).strip().lower())
        if not mode:
            return False, f"Nepodporovaný CEC příkaz: {command}"
        try:
            p = subprocess.run(
                ["sudo", "-n", "/usr/local/libexec/pitv-cec-monitor", device, mode],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=6,
                check=False,
            )
            out = (p.stdout or "").strip()
            if out:
                outputs.append(out[-180:])
            if p.returncode != 0:
                return False, out[-180:] if out else f"CEC chyba {p.returncode}"
        except subprocess.TimeoutExpired:
            return False, "CEC timeout"
        except Exception as e:
            return False, f"CEC chyba: {e}"

    return True, outputs[-1] if outputs else "CEC příkaz odeslán"


def cec_tv_on():
    ok, msg = cec_send(["on 0", "as"])
    return ok, ("TV probuzena / PiTV aktivní zdroj" if ok else msg)


def cec_tv_standby():
    ok, msg = cec_send("standby 0")
    return ok, ("TV poslána do standby" if ok else msg)


def cec_active_source():
    ok, msg = cec_send("as")
    return ok, ("PiTV nastaveno jako aktivní HDMI zdroj" if ok else msg)


def cec_volume_up():
    ok, msg = cec_send("volup")
    return ok, ("Hlasitost +" if ok else msg)


def cec_volume_down():
    ok, msg = cec_send("voldown")
    return ok, ("Hlasitost −" if ok else msg)


def cec_mute():
    ok, msg = cec_send("mute")
    return ok, ("Mute přepnuto" if ok else msg)


class CECReader(threading.Thread):
    """Read TV remote keys from the Linux kernel HDMI-CEC API.

    Ubuntu on Raspberry Pi 4/5 exposes vc4 HDMI CEC as /dev/cec*.  The
    distro libCEC can still auto-select its legacy RPI backend, which detects
    an adapter but cannot open it with vc4-kms.  cec-ctl talks to the kernel
    API directly and is therefore the primary PiTV input path.
    """
    def __init__(self, event_queue):
        super().__init__(daemon=True)
        self.event_queue = event_queue
        self.proc = None
        self.device = None
        self.last_key = None
        self.last_key_at = 0.0
        self.key_released = True
        self._awaiting_ui_cmd = False
        self._stop_event = threading.Event()

    def _devices(self):
        return sorted(Path("/dev").glob("cec*"))

    def _device_info(self, device):
        try:
            p = subprocess.run(
                ["cec-ctl", "-d", str(device), "--show-topology"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=4, check=False,
            )
            return p.stdout or ""
        except Exception:
            return ""

    def _pick_device(self):
        devices = self._devices()
        if not devices:
            return None
        # Prefer a connector with a real HDMI physical address.  0.0.0.0 and
        # f.f.f.f are not connected to a usable CEC topology.
        for dev in devices:
            info = self._device_info(dev)
            m = re.search(r"Physical Address\s*:\s*([^\s]+)", info, re.I)
            if m and m.group(1).lower() not in ("0.0.0.0", "f.f.f.f"):
                return dev
        return devices[0]

    def is_ready(self):
        return self.device is not None and self.proc is not None and self.proc.poll() is None

    def send(self, commands):
        return cec_send(commands)

    def _queue_mapped(self, mapped):
        if mapped is None:
            return
        now = time.monotonic()
        # A short TV remote press must produce exactly one UI step. Some TVs
        # repeat USER_CONTROL_PRESSED aggressively; accept a held-key repeat
        # only after a deliberate delay.
        if mapped == self.last_key and not self.key_released:
            if (now - self.last_key_at) < 0.45:
                return
        self.last_key, self.last_key_at = mapped, now
        self.key_released = False
        self.event_queue.put(mapped)

    def _emit(self, name):
        key = re.sub(r"\s*\(.*$", "", name).strip().lower()
        key = key.replace("_", " ").replace("-", " ")
        aliases = {
            "device root menu": "root menu",
            "device setup menu": "root menu",
            "setup menu": "root menu",
            "favorite menu": "root menu",
            "media top menu": "top menu",
            "media context sensitive menu": "top menu",
            "device vendor specific": "home",
            "previous channel": "back",
            "ok": "select",
        }
        self._queue_mapped(CEC_MAP.get(aliases.get(key, key)))

    def _emit_code(self, code):
        self._queue_mapped(CEC_CODE_MAP.get(code))

    def _handle_monitor_line(self, line):
        """Parse one cec-ctl monitor line; supports split decoded output + raw frames."""
        upper = line.upper()

        if ("USER_CONTROL_RELEASED" in upper or
                re.search(r"(?:^|[\s>])[0-9A-Fa-f]{2}:45(?:\s|$)", line)):
            self._awaiting_ui_cmd = False
            self.key_released = True
            self.last_key = None
            return

        # Raw frame fallback is version-independent:
        # <header>:44:<ui-command>, e.g. 01:44:00 for Select/OK.
        raw = re.search(
            r"(?:^|[\s>])[0-9A-Fa-f]{2}:44:([0-9A-Fa-f]{2})(?:\s|$)",
            line,
        )
        if raw:
            self._emit_code(int(raw.group(1), 16))

        if "USER_CONTROL_PRESSED" in upper:
            self._awaiting_ui_cmd = True

        # cec-ctl normally prints USER_CONTROL_PRESSED and ui-cmd on separate
        # lines, so remember that a UI operand is expected.
        if self._awaiting_ui_cmd or "UI-CMD:" in upper:
            m = re.search(r"ui-cmd:\s*([^\(\r\n]+)", line, re.I)
            if m:
                self._awaiting_ui_cmd = False
                self._emit(m.group(1))

    def run(self):
        global _CEC_MANAGER
        if shutil.which("cec-ctl") is None:
            return

        _CEC_MANAGER = self
        try:
            while not self._stop_event.is_set():
                self.device = self._pick_device()
                if self.device is None:
                    self._stop_event.wait(1.0)
                    continue

                try:
                    registered = subprocess.run(
                        ["sudo", "-n", "/usr/local/libexec/pitv-cec-monitor",
                         str(self.device), "register"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, timeout=5, check=False,
                    )
                    if registered.returncode != 0:
                        self.device = None
                        self._stop_event.wait(1.0)
                        continue

                    self.proc = subprocess.Popen(
                        ["sudo", "-n", "/usr/local/libexec/pitv-cec-monitor",
                         str(self.device), "monitor"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1,
                    )

                    for line in self.proc.stdout:
                        if self._stop_event.is_set():
                            break
                        self._handle_monitor_line(line)
                except Exception:
                    pass
                finally:
                    proc = self.proc
                    self.proc = None
                    if proc is not None and proc.poll() is None:
                        try:
                            proc.terminate()
                            proc.wait(timeout=1)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass

                # HDMI hotplug / CEC resets can terminate cec-ctl. Reconnect
                # automatically instead of permanently losing the remote.
                if not self._stop_event.is_set():
                    self._stop_event.wait(0.75)
        finally:
            self.device = None
            if _CEC_MANAGER is self:
                _CEC_MANAGER = None

    def stop(self):
        global _CEC_MANAGER
        self._stop_event.set()
        if _CEC_MANAGER is self:
            _CEC_MANAGER = None
        try:
            if self.proc:
                self.proc.terminate()
        except Exception:
            pass


class PiTV:
    def __init__(self):
        pygame.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption(f"{APP_NAME} {VERSION}")
        pygame.mouse.set_visible(False)
        self.w, self.h = self.screen.get_size()
        self.cfg = load_config()
        self.apps = load_apps()
        self.page = "home"
        self.selected = 0
        self.settings_selected = 0
        self.sidebar_focus = False
        self.sidebar_selected = 0
        self.store_return_page = "apps"
        self.server_store_return_page = "settings"
        self.sub_selected = 0
        self.cec_selected = 0
        self.network_selected = 0
        self.audio_selected = 0
        self.apps_selected = 0
        self.system_selected = 0
        self.android_selected = 0
        self.store_selected = 0
        self.store_catalog = load_store_catalog()
        self.store_states = {}
        self.store_refreshing = False
        self.store_busy_id = ""
        self.server_store_selected = 0
        self.server_store_catalog = load_server_catalog()
        self.server_store_states = {}
        self.server_store_refreshing = False
        self.server_store_busy_id = ""
        self.updates_selected = 0
        self.remote_pitv = ""
        self.updates_status = "Nezkontrolováno"
        self.updates_busy = False
        self.external_proc = None
        self.external_kind = None
        self._relay_echo = {}

        self.wifi_networks = []
        self.wifi_scanning = False
        self.update_count = None
        self.update_checking = False
        self.upgrade_running = False

        # TV-friendly text input / confirmation overlays.
        self.keyboard_active = False
        self.keyboard_title = ""
        self.keyboard_value = ""
        self.keyboard_secret = False
        self.keyboard_shift = False
        self.keyboard_selected = 0
        self.keyboard_callback = None

        self.confirm_active = False
        self.confirm_title = ""
        self.confirm_message = ""
        self.confirm_yes = False
        self.confirm_callback = None

        self.toast = ""
        self.toast_until = 0.0
        # Persistent global activity indicator for long-running TV operations.
        self.operation_text = ""
        self.operation_progress = None
        self.operation_error = False
        self.operation_until = 0.0

        # 24/7 TV idle state. PiTV itself keeps running.
        self.last_activity = time.monotonic()
        self.screensaver_stage = "off"   # off | clock | black
        self.screensaver_preview = False
        self.cec_standby_sent = False

        self.running = True
        self.cec_queue = queue.Queue()
        self.cec = None
        if self.cfg.get("cec_enabled", True):
            self.cec = CECReader(self.cec_queue)
            self.cec.start()
            if self.cfg.get("cec_wake_on_start", False):
                threading.Thread(target=cec_tv_on, daemon=True).start()
        # One physical press = one navigation step. TV remotes already provide
        # their own hold/repeat events; SDL repeat caused multi-tile jumps.
        pygame.key.set_repeat()
        self.clock = pygame.time.Clock()

    @property
    def t(self):
        theme = self.cfg.get("theme", "apple_dark")
        theme = {"dark": "apple_dark", "light": "apple_light"}.get(theme, theme)
        return THEMES.get(theme, THEMES["apple_dark"])

    @property
    def theme_name(self):
        theme = self.cfg.get("theme", "apple_dark")
        theme = {"dark": "apple_dark", "light": "apple_light"}.get(theme, theme)
        return "PiTV Apple Light" if theme == "apple_light" else "PiTV Apple Dark"

    def main_left(self):
        return int(self.w * .235)

    def main_rect(self):
        left = self.main_left()
        return pygame.Rect(left, int(self.h*.035), self.w-left-int(self.w*.025), int(self.h*.93))

    def font(self, size, bold=False):
        return pygame.font.SysFont("DejaVu Sans", max(16, int(size)), bold=bold)

    def text(self, text, x, y, size, color=None, bold=False):
        surf = self.font(size, bold).render(str(text), True, color or self.t["text"])
        self.screen.blit(surf, (x, y))
        return surf.get_rect(topleft=(x, y))

    @staticmethod
    def mix(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def gradient_rect(self, rect, top, bottom, radius=0):
        # Lightweight vertical gradient. TV resolution is sampled in strips
        # rather than painting every row to keep the Pi 4 UI cheap.
        tmp = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        strips = max(12, min(48, rect.h // 8))
        for i in range(strips):
            y0 = round(i * rect.h / strips)
            y1 = round((i + 1) * rect.h / strips)
            c = self.mix(top, bottom, i / max(1, strips - 1))
            pygame.draw.rect(tmp, c, pygame.Rect(0, y0, rect.w, max(1, y1-y0)))
        if radius:
            mask = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255,255,255,255), mask.get_rect(), border_radius=radius)
            tmp.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MIN)
        self.screen.blit(tmp, rect.topleft)

    def draw_background(self):
        # iOS Hub inspired radial/hero feel, approximated cheaply for SDL.
        self.screen.fill(self.t["page"])
        upper = pygame.Rect(0, 0, self.w, int(self.h * .78))
        self.gradient_rect(upper, self.t["hero"], self.t["bg"])
        lower = pygame.Rect(0, int(self.h*.55), self.w, int(self.h*.45))
        fade = pygame.Surface((lower.w, lower.h), pygame.SRCALPHA)
        strips = 28
        for i in range(strips):
            y0 = round(i * lower.h / strips)
            y1 = round((i+1) * lower.h / strips)
            alpha = int(255 * (i / max(1, strips-1)))
            c = (*self.t["page"], alpha)
            pygame.draw.rect(fade, c, pygame.Rect(0, y0, lower.w, max(1,y1-y0)))
        self.screen.blit(fade, lower.topleft)

    def pill(self, text, x, y, color=None, selected=False):
        color = color or self.t["accent"]
        f = self.font(self.h*.016, True)
        surf = f.render(str(text).upper(), True, color)
        pad_x, pad_y = 14, 7
        r = pygame.Rect(x, y, surf.get_width()+pad_x*2, surf.get_height()+pad_y*2)
        bg = self.t["accent_soft"] if color == self.t["accent"] else self.t["input"]
        pygame.draw.rect(self.screen, bg, r, border_radius=r.h//2)
        pygame.draw.rect(self.screen, color if selected else self.t["border"], r, 1, border_radius=r.h//2)
        self.screen.blit(surf, (r.x+pad_x, r.y+pad_y))
        return r

    def glass_panel(self, rect, selected=False, alpha=225, radius=22):
        surface = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        base = self.t["accent_soft"] if selected else self.t["panel"]
        pygame.draw.rect(surface, (*base, alpha), surface.get_rect(), border_radius=radius)
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(
            self.screen,
            self.t["accent"] if selected else self.t["border"],
            rect,
            2 if selected else 1,
            border_radius=radius,
        )

    def draw_sidebar(self, active=""):
        w = int(self.w*.205)
        rect = pygame.Rect(int(self.w*.025), int(self.h*.035), w, int(self.h*.93))
        self.glass_panel(rect, False, 218, 26)

        x = rect.x + int(w*.11)
        top = rect.y + int(self.h*.035)
        mark = pygame.Rect(x, top, int(self.h*.055), int(self.h*.055))
        self.gradient_rect(mark, self.t["accent2"], self.t["action"], radius=14)
        play = self.font(mark.h*.34, True).render("▶", True, (255,255,255))
        self.screen.blit(play, play.get_rect(center=mark.center))
        self.text("PiTV", mark.right+14, top-3, self.h*.041, self.t["text"], True)
        self.text("Your TV. Your Way.", x, top+int(self.h*.065), self.h*.015, self.t["muted"])

        items = [
            ("home", "⌂", "Home"),
            ("store", "▣", "Store"),
            ("server_store", "◉", "Server Store"),
            ("android", "◆", "Android / APK"),
            ("updates", "↻", "Updates"),
            ("settings", "⚙", "Settings"),
        ]
        y0 = top + int(self.h*.115)
        row_h = int(self.h*.058)
        for i, (key, icon, label) in enumerate(items):
            rr = pygame.Rect(rect.x+int(w*.055), y0+i*row_h, int(w*.89), int(row_h*.82))
            selected = (self.sidebar_focus and i == self.sidebar_selected) or (
                not self.sidebar_focus and key == active
            )
            if selected:
                surf = pygame.Surface((rr.w, rr.h), pygame.SRCALPHA)
                pygame.draw.rect(surf, (*self.t["accent_soft"], 235), surf.get_rect(), border_radius=14)
                self.screen.blit(surf, rr.topleft)
                pygame.draw.rect(self.screen, self.t["accent"], rr, 2, border_radius=14)
            self.text(icon, rr.x+14, rr.y+int(rr.h*.20), rr.h*.36,
                      self.t["accent"] if selected else self.t["muted"], True)
            self.text(label, rr.x+int(rr.h*.75), rr.y+int(rr.h*.25), rr.h*.25,
                      self.t["text"] if selected else self.t["muted"], selected)

        divider_y = y0 + len(items)*row_h + int(self.h*.008)
        pygame.draw.line(self.screen, self.t["border"],
                         (rect.x+int(w*.08), divider_y),
                         (rect.right-int(w*.08), divider_y), 1)

        self.text("Media & Tools", x, divider_y+int(self.h*.020),
                  self.h*.014, self.t["muted"], True)
        quick = [
            ("▦", "Kodi"),
            ("▶", "SmartTube"),
            ("◆", "Stremio"),
            ("❯", "Plex"),
            ("•••", "More Apps"),
        ]
        qy = divider_y + int(self.h*.055)
        qh = int(self.h*.049)
        for j, (icon, label) in enumerate(quick):
            rr = pygame.Rect(rect.x+int(w*.055), qy, int(w*.89), int(qh*.82))
            selected = self.sidebar_focus and self.sidebar_selected == 6+j
            if selected:
                surf = pygame.Surface((rr.w, rr.h), pygame.SRCALPHA)
                pygame.draw.rect(surf, (*self.t["accent_soft"], 235), surf.get_rect(), border_radius=12)
                self.screen.blit(surf, rr.topleft)
                pygame.draw.rect(self.screen, self.t["accent"], rr, 2, border_radius=12)
            self.text(icon, rr.x+14, rr.y+int(rr.h*.16), rr.h*.34,
                      self.t["accent"] if selected else self.t["muted"], True)
            self.text(label, rr.x+int(rr.h*.78), rr.y+int(rr.h*.20), rr.h*.25,
                      self.t["text"] if selected else self.t["muted"], selected)
            qy += qh

        self.text("PiTV  "+VERSION, x, rect.bottom-int(self.h*.045), self.h*.013, self.t["muted"])

    def draw_hero(self, title, subtitle, badge="PiTV", action=""):
        r = pygame.Rect(self.main_left()+int(self.w*.015), int(self.h*.055),
                        int(self.w*.72), int(self.h*.265))
        self.gradient_rect(r, self.t["hero"], self.t["bg"], radius=24)
        pygame.draw.rect(self.screen, self.t["border"], r, 1, border_radius=24)
        self.text(str(badge).upper(), r.x+34, r.y+28, self.h*.015, self.t["muted"], True)
        self.text(title, r.x+34, r.y+int(self.h*.065), self.h*.050, self.t["text"], True)
        self.text(subtitle, r.x+36, r.y+int(self.h*.135), self.h*.020, self.t["muted"])
        if action:
            ar = pygame.Rect(r.x+36, r.bottom-int(self.h*.072), int(self.w*.12), int(self.h*.048))
            self.gradient_rect(ar, self.t["accent2"], self.t["action"], radius=ar.h//2)
            surf = self.font(ar.h*.27, True).render(action, True, (255,255,255))
            self.screen.blit(surf, surf.get_rect(center=ar.center))
        return r

    SIDEBAR_PAGES = ["home", "store", "server_store", "android", "updates", "settings"]

    def focus_sidebar(self, active_page=None):
        page = active_page or self.page
        # Settings children belong to the Settings sidebar entry.
        if page not in self.SIDEBAR_PAGES:
            page = "settings"
        try:
            self.sidebar_selected = self.SIDEBAR_PAGES.index(page)
        except ValueError:
            self.sidebar_selected = 0
        self.sidebar_focus = True

    def activate_sidebar(self):
        idx = self.sidebar_selected
        self.sidebar_focus = False

        if idx < len(self.SIDEBAR_PAGES):
            target = self.SIDEBAR_PAGES[idx]
            if target == "home":
                self.page = "home"
                self.selected = 0
            elif target == "store":
                self.page = "store"
                self.store_return_page = "home"
                self.store_selected = 0
                self.refresh_store_async()
            elif target == "server_store":
                self.page = "server_store"
                self.server_store_return_page = "home"
                self.server_store_selected = 0
                self.refresh_server_store_async()
            elif target == "android":
                self.page = "android"
                self.android_selected = 0
            elif target == "updates":
                self.page = "updates"
                self.updates_selected = 0
                self.check_updates_async()
            else:
                self.page = "settings"
                self.settings_selected = 0
            return

        shortcuts = [
            ("kodi", "Kodi"),
            ("smarttube", "SmartTube"),
            ("stremio", "Stremio"),
            ("plex", "Plex"),
        ]
        q = idx - len(self.SIDEBAR_PAGES)
        if q >= len(shortcuts):
            self.page = "store"
            self.store_return_page = "home"
            self.store_selected = 0
            self.refresh_store_async()
            return

        store_id, app_name = shortcuts[q]
        app = next((a for a in self.apps if a.get("name","").lower() == app_name.lower()), None)
        if app:
            self.launch(app)
            return

        self.page = "store"
        self.store_return_page = "home"
        self.store_selected = next(
            (i for i, item in enumerate(self.store_catalog) if item.get("id") == store_id), 0
        )
        self.refresh_store_async()

    def header(self, title, subtitle=None):
        left = self.main_left()+int(self.w*.018)
        top = int(self.h*.058)
        self.text(title, left, top, self.h*.043, self.t["text"], True)
        if subtitle:
            self.text(subtitle, left+2, top+int(self.h*.049), self.h*.017, self.t["muted"])

    def card(self, rect, title, subtitle="", selected=False, icon=""):
        radius = 18
        bg = self.t["accent_soft"] if selected else self.t["panel"]
        pygame.draw.rect(self.screen, bg, rect, border_radius=radius)
        pygame.draw.rect(self.screen, self.t["accent"] if selected else self.t["border"],
                         rect, 3 if selected else 1, border_radius=radius)

        # Slight shadow under focused cards, matching the web panel hierarchy.
        if selected:
            glow = rect.inflate(10, 10)
            halo = pygame.Surface((glow.w, glow.h), pygame.SRCALPHA)
            pygame.draw.rect(halo, (*self.t["accent"], 24), halo.get_rect(), border_radius=22)
            self.screen.blit(halo, glow.topleft)
            pygame.draw.rect(self.screen, bg, rect, border_radius=radius)
            pygame.draw.rect(self.screen, self.t["accent"], rect, 3, border_radius=radius)

        pad = int(rect.w*.065)
        icon_box = pygame.Rect(rect.x+pad, rect.y+int(rect.h*.12), int(rect.h*.28), int(rect.h*.28))
        self.gradient_rect(icon_box, self.t["accent2"], self.t["action"], radius=12)
        if icon:
            txt = self.font(icon_box.h*.36, True).render(str(icon), True, (255,255,255))
            self.screen.blit(txt, txt.get_rect(center=icon_box.center))
        self.text(title, rect.x+pad, rect.y+int(rect.h*.57), rect.h*.118, self.t["text"], True)
        if subtitle:
            self.text(subtitle, rect.x+pad, rect.y+int(rect.h*.76), rect.h*.073, self.t["muted"])

    def set_operation(self, text, progress=None, error=False):
        self.operation_text = str(text)
        self.operation_progress = None if progress is None else max(0, min(100, int(progress)))
        self.operation_error = bool(error)
        self.operation_until = 0.0

    def finish_operation(self, text="Hotovo", ok=True, seconds=3.0):
        self.operation_text = ("✓ " if ok else "! ") + str(text)
        self.operation_progress = 100 if ok else None
        self.operation_error = not ok
        self.operation_until = time.monotonic() + seconds

    def clear_operation_if_due(self):
        if self.operation_until and time.monotonic() >= self.operation_until:
            self.operation_text = ""
            self.operation_progress = None
            self.operation_error = False
            self.operation_until = 0.0

    def draw_operation(self):
        self.clear_operation_if_due()
        if not self.operation_text:
            return
        f = self.font(self.h*.017, True)
        suffix = "" if self.operation_progress is None else f"  {self.operation_progress}%"
        surf = f.render(self.operation_text + suffix, True,
                        self.t["bad"] if self.operation_error else self.t["text"])
        w = max(int(self.w*.19), surf.get_width()+54)
        h = int(self.h*.062)
        r = pygame.Rect(self.w-w-int(self.w*.025), int(self.h*.025), w, h)
        pygame.draw.rect(self.screen, self.t["panel2"], r, border_radius=h//2)
        pygame.draw.rect(self.screen, self.t["bad"] if self.operation_error else self.t["accent"],
                         r, 2, border_radius=h//2)
        if self.operation_progress is None:
            # Indeterminate spinner.
            angle = (time.monotonic()*300) % 360
            center = (r.x+22, r.centery)
            pygame.draw.arc(self.screen, self.t["accent"],
                            pygame.Rect(center[0]-9, center[1]-9, 18, 18),
                            angle*3.14159/180, (angle+250)*3.14159/180, 3)
        else:
            bw = int((r.w-20) * self.operation_progress / 100)
            pygame.draw.rect(self.screen, self.t["accent"],
                             pygame.Rect(r.x+10, r.bottom-7, bw, 3), border_radius=2)
        self.screen.blit(surf, (r.x+42, r.y+(r.h-surf.get_height())//2-1))

    def show_toast(self, message, seconds=2.4):
        self.toast = str(message)
        self.toast_until = time.time() + seconds

    def run_cec_action(self, fn):
        def worker():
            ok, msg = fn()
            self.show_toast(msg)
        threading.Thread(target=worker, daemon=True).start()

    def async_action(self, fn, done=None):
        def worker():
            try:
                result = fn()
            except Exception as e:
                result = (False, f"Chyba: {e}")
            if done:
                done(result)
            elif isinstance(result, tuple) and len(result) >= 2:
                self.show_toast(result[1])
        threading.Thread(target=worker, daemon=True).start()

    def open_keyboard(self, title, initial="", secret=False, callback=None):
        self.keyboard_active = True
        self.keyboard_title = title
        self.keyboard_value = initial
        self.keyboard_secret = secret
        self.keyboard_shift = False
        self.keyboard_selected = 0
        self.keyboard_callback = callback
        self.mark_activity()

    def open_confirm(self, title, message, callback):
        self.confirm_active = True
        self.confirm_title = title
        self.confirm_message = message
        self.confirm_yes = False
        self.confirm_callback = callback
        self.mark_activity()

    KEYBOARD_KEYS = list("abcdefghijklmnopqrstuvwxyz0123456789") + list("-_.@!#$%&*+?") + [
        "SPACE", "⌫", "SHIFT", "HOTOVO", "ZRUŠIT"
    ]

    def draw_keyboard(self):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        box = pygame.Rect(int(self.w*.07), int(self.h*.06), int(self.w*.86), int(self.h*.88))
        pygame.draw.rect(self.screen, self.t["panel"], box, border_radius=22)
        pygame.draw.rect(self.screen, self.t["border"], box, 2, border_radius=22)

        self.text(self.keyboard_title, box.x+34, box.y+24, self.h*.032, self.t["text"], True)
        shown = "•" * len(self.keyboard_value) if self.keyboard_secret else self.keyboard_value
        value_rect = pygame.Rect(box.x+34, box.y+int(self.h*.085), box.w-68, int(self.h*.073))
        pygame.draw.rect(self.screen, self.t["input"], value_rect, border_radius=12)
        pygame.draw.rect(self.screen, self.t["accent"], value_rect, 1, border_radius=12)
        shown = shown[-54:]
        self.text(shown or "…", value_rect.x+16, value_rect.y+int(value_rect.h*.25),
                  value_rect.h*.36, self.t["text"])

        cols = 10
        grid_x = box.x+34
        grid_y = value_rect.bottom+int(self.h*.027)
        gap = 7
        key_w = int((box.w-68-(cols-1)*gap)/cols)
        key_h = int(self.h*.061)
        for i, raw in enumerate(self.KEYBOARD_KEYS):
            row, col = divmod(i, cols)
            rect = pygame.Rect(grid_x+col*(key_w+gap), grid_y+row*(key_h+gap), key_w, key_h)
            selected = i == self.keyboard_selected
            pygame.draw.rect(self.screen, self.t["accent_soft"] if selected else self.t["panel2"],
                             rect, border_radius=10)
            pygame.draw.rect(self.screen, self.t["accent"] if selected else self.t["border"],
                             rect, 2 if selected else 1, border_radius=10)
            label = raw
            if len(raw) == 1 and raw.isalpha() and self.keyboard_shift:
                label = raw.upper()
            if raw == "SPACE": label = "␠"
            fs = key_h*.25 if len(label) > 2 else key_h*.37
            surf = self.font(fs, True).render(label, True, self.t["text"])
            self.screen.blit(surf, surf.get_rect(center=rect.center))

        self.text("Šipky • OK • Back = zrušit", box.x+34, box.bottom-int(self.h*.041),
                  self.h*.017, self.t["muted"])

    def handle_keyboard_key(self, key):
        if key == pygame.K_ESCAPE:
            self.keyboard_active = False
            self.keyboard_callback = None
            return
        cols = 10
        count = len(self.KEYBOARD_KEYS)
        if key == pygame.K_LEFT:
            self.keyboard_selected = max(0, self.keyboard_selected-1)
        elif key == pygame.K_RIGHT:
            self.keyboard_selected = min(count-1, self.keyboard_selected+1)
        elif key == pygame.K_UP:
            self.keyboard_selected = max(0, self.keyboard_selected-cols)
        elif key == pygame.K_DOWN:
            self.keyboard_selected = min(count-1, self.keyboard_selected+cols)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            raw = self.KEYBOARD_KEYS[self.keyboard_selected]
            if raw == "SPACE":
                self.keyboard_value += " "
            elif raw == "⌫":
                self.keyboard_value = self.keyboard_value[:-1]
            elif raw == "SHIFT":
                self.keyboard_shift = not self.keyboard_shift
            elif raw == "ZRUŠIT":
                self.keyboard_active = False
                self.keyboard_callback = None
            elif raw == "HOTOVO":
                value = self.keyboard_value
                cb = self.keyboard_callback
                self.keyboard_active = False
                self.keyboard_callback = None
                if cb:
                    cb(value)
            else:
                ch = raw.upper() if self.keyboard_shift and raw.isalpha() else raw
                if len(self.keyboard_value) < 128:
                    self.keyboard_value += ch

    def draw_confirm(self):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        box = pygame.Rect(int(self.w*.23), int(self.h*.28), int(self.w*.54), int(self.h*.42))
        pygame.draw.rect(self.screen, self.t["panel"], box, border_radius=22)
        pygame.draw.rect(self.screen, self.t["border"], box, 2, border_radius=22)
        self.text(self.confirm_title, box.x+32, box.y+28, self.h*.032, self.t["text"], True)
        self.text(self.confirm_message, box.x+32, box.y+int(self.h*.095), self.h*.021, self.t["muted"])
        opts = [("Ne", False), ("Ano", True)]
        bw, bh, gap = int(box.w*.30), int(self.h*.075), int(box.w*.07)
        startx = box.centerx - (bw*2+gap)//2
        y = box.bottom-int(self.h*.125)
        for i, (label, value) in enumerate(opts):
            selected = self.confirm_yes == value
            r = pygame.Rect(startx+i*(bw+gap), y, bw, bh)
            pygame.draw.rect(self.screen, self.t["accent_soft"] if selected else self.t["panel2"], r, border_radius=12)
            pygame.draw.rect(self.screen, self.t["accent"] if selected else self.t["border"], r, 2, border_radius=12)
            surf = self.font(bh*.30, True).render(label, True, self.t["text"])
            self.screen.blit(surf, surf.get_rect(center=r.center))

    def handle_confirm_key(self, key):
        if key == pygame.K_ESCAPE:
            self.confirm_active = False
            self.confirm_callback = None
            return
        if key in (pygame.K_LEFT, pygame.K_RIGHT):
            self.confirm_yes = not self.confirm_yes
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            yes = self.confirm_yes
            cb = self.confirm_callback
            self.confirm_active = False
            self.confirm_callback = None
            if yes and cb:
                cb()

    def scan_wifi_async(self):
        if self.wifi_scanning:
            return
        self.wifi_scanning = True
        self.set_operation("Hledám Wi‑Fi sítě…")
        self.show_toast("Hledám Wi‑Fi sítě…")
        def worker():
            self.wifi_networks = list_wifi_networks()
            self.wifi_scanning = False
            self.network_selected = min(self.network_selected, max(0, len(self.network_items())-1))
            self.finish_operation(f"Nalezeno {len(self.wifi_networks)} sítí", True)
            self.show_toast(f"Nalezeno {len(self.wifi_networks)} sítí")
        threading.Thread(target=worker, daemon=True).start()

    def connect_wifi(self, net):
        def do_connect(password=""):
            self.set_operation(f"Připojuji {net['ssid']}…")
            self.show_toast(f"Připojuji {net['ssid']}…")
            def worker():
                ok, msg = run_privileged("wifi-connect", {
                    "ssid": net["ssid"],
                    "password": password,
                }, timeout=45)
                self.finish_operation(msg, ok)
                self.show_toast(msg)
                time.sleep(.5)
                self.wifi_networks = list_wifi_networks()
            threading.Thread(target=worker, daemon=True).start()

        security = (net.get("security") or "").upper()
        if security in ("", "--", "OPEN"):
            do_connect("")
        else:
            self.open_keyboard(f"Heslo Wi‑Fi: {net['ssid']}", secret=True, callback=do_connect)

    def network_items(self):
        wifi = nm_wifi_enabled()
        state = "Zapnuto" if wifi is True else ("Vypnuto" if wifi is False else "Nedostupné")
        items = [
            {"kind": "wifi-toggle", "title": "Wi‑Fi", "detail": state},
            {"kind": "scan", "title": "Vyhledat sítě", "detail": "Obnovit seznam"},
        ]
        dev = wifi_device()
        if dev:
            items.append({"kind": "disconnect", "title": "Odpojit Wi‑Fi", "detail": dev})
        for n in self.wifi_networks:
            lock = "🔒" if (n.get("security") or "").upper() not in ("", "--", "OPEN") else "○"
            prefix = "✓" if n.get("active") else lock
            items.append({
                "kind": "wifi-net",
                "title": f"{prefix} {n['ssid']}",
                "detail": f"{n['signal']} % · {n.get('security') or 'OPEN'}",
                "net": n,
            })
        return items

    def audio_items(self):
        dev = active_hdmi_audio_device(self.cfg.get("hdmi_audio_port", "auto"))
        return [
            {"title": "HDMI audio", "detail": f"{dev['name']} · {dev['status']} · {dev['mode']}", "action": "port"},
            {"title": "Hlasitost +", "detail": "TV / receiver přes HDMI‑CEC", "action": "volup"},
            {"title": "Hlasitost −", "detail": "TV / receiver přes HDMI‑CEC", "action": "voldown"},
            {"title": "Mute / unmute", "detail": "TV / receiver přes HDMI‑CEC", "action": "mute"},
            {"title": "Test HDMI zvuku", "detail": f"ALSA {dev['alsa']}", "action": "test"},
        ]

    def mark_activity(self):
        self.last_activity = time.monotonic()
        self.screensaver_stage = "off"
        self.screensaver_preview = False
        self.cec_standby_sent = False

    def idle_minutes(self):
        return max(0.0, (time.monotonic() - self.last_activity) / 60.0)

    def update_idle_state(self):
        # Never run PiTV screensaver/CEC standby while Kodi or Android is
        # actively in the foreground. Playback can be idle from PiTV's point
        # of view for hours and must not turn the television off.
        if self.external_kind:
            self.last_activity = time.monotonic()
            self.screensaver_stage = "off"
            self.cec_standby_sent = False
            return

        if self.screensaver_preview:
            self.screensaver_stage = (
                "black" if self.cfg.get("screensaver_mode", "clock") == "black" else "clock"
            )
            return

        if not self.cfg.get("screensaver_enabled", True):
            self.screensaver_stage = "off"
            return

        idle = self.idle_minutes()
        saver_after = max(0, int(self.cfg.get("screensaver_after_min", 5)))
        black_after = max(0, int(self.cfg.get("screensaver_black_after_min", 15)))
        standby_after = max(0, int(self.cfg.get("screensaver_cec_standby_after_min", 30)))
        mode = self.cfg.get("screensaver_mode", "clock")

        if saver_after and idle >= saver_after:
            self.screensaver_stage = "black" if mode == "black" else "clock"
        else:
            self.screensaver_stage = "off"

        if black_after and idle >= black_after:
            self.screensaver_stage = "black"

        if standby_after and idle >= standby_after and not self.cec_standby_sent:
            self.cec_standby_sent = True
            if self.cfg.get("cec_enabled", True) and cec_available():
                # Never stop PiTV/server; only ask the display to enter standby.
                self.run_cec_action(cec_tv_standby)

    def wake_from_screensaver(self):
        was_asleep = self.screensaver_stage != "off" or self.screensaver_preview
        was_cec_standby = self.cec_standby_sent
        self.mark_activity()
        if was_cec_standby and self.cfg.get("cec_enabled", True) and cec_available():
            self.run_cec_action(cec_tv_on)
        return was_asleep

    def draw_screensaver(self):
        if self.screensaver_stage == "black":
            self.screen.fill((0, 0, 0))
            pygame.display.flip()
            return

        # Moving clock: changes position once a minute to reduce static-image burn-in.
        self.screen.fill(self.t["page"])
        now = time.localtime()
        clock_text = time.strftime("%H:%M", now)
        date_text = time.strftime("%d.%m.%Y", now)

        big = self.font(self.h * .115, True).render(clock_text, True, self.t["text"])
        small = self.font(self.h * .030, False).render(date_text, True, self.t["muted"])

        minute_slot = int(time.time() // 60)
        cols, rows = 4, 3
        col = (minute_slot * 3 + 1) % cols
        row = (minute_slot * 5 + 2) % rows

        margin_x = int(self.w * .09)
        margin_y = int(self.h * .10)
        usable_w = max(1, self.w - 2 * margin_x - big.get_width())
        usable_h = max(1, self.h - 2 * margin_y - big.get_height() - small.get_height() - 14)
        x = margin_x + int(usable_w * (col / max(1, cols - 1)))
        y = margin_y + int(usable_h * (row / max(1, rows - 1)))

        self.screen.blit(big, (x, y))
        self.screen.blit(small, (x + big.get_width() - small.get_width(), y + big.get_height() + 10))

        # Tiny, low-contrast status text moves with the clock.
        status = self.font(self.h*.016, False).render("PiTV", True, self.t["muted"])
        self.screen.blit(status, (x, y + big.get_height() + small.get_height() + 18))
        pygame.display.flip()

    @staticmethod
    def _cycle(current, values, direction):
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        idx = (idx + direction) % len(values)
        return values[idx]

    @staticmethod
    def _step(current, values, direction):
        """Move through an ordered setting without wrapping min <-> max."""
        try:
            idx = values.index(current)
        except ValueError:
            idx = min(range(len(values)), key=lambda i: abs(float(values[i]) - float(current)))
        idx = max(0, min(len(values)-1, idx + direction))
        return values[idx]

    def set_screensaver_value(self, row, direction):
        if row == 0:
            self.cfg["screensaver_enabled"] = not self.cfg.get("screensaver_enabled", True)
        elif row == 1:
            vals = [1, 2, 5, 10, 15, 30, 60]
            cur = int(self.cfg.get("screensaver_after_min", 5))
            self.cfg["screensaver_after_min"] = self._step(cur, vals, direction)
        elif row == 2:
            vals = ["clock", "black"]
            cur = self.cfg.get("screensaver_mode", "clock")
            self.cfg["screensaver_mode"] = self._cycle(cur, vals, direction)
        elif row == 3:
            vals = [0, 10, 15, 30, 60, 120]
            cur = int(self.cfg.get("screensaver_black_after_min", 15))
            self.cfg["screensaver_black_after_min"] = self._step(cur, vals, direction)
        elif row == 4:
            vals = [0, 15, 30, 60, 120, 240]
            cur = int(self.cfg.get("screensaver_cec_standby_after_min", 30))
            self.cfg["screensaver_cec_standby_after_min"] = self._step(cur, vals, direction)
        save_user_config(self.cfg)
        self.mark_activity()

    HOME_TILE_STYLE = {
        "kodi":       ((14,165,233), (2,132,199), "K"),
        "smarttube":  ((248,48,58), (185,28,28), "▶"),
        "stremio":    ((168,85,247), (109,40,217), "◆"),
        "plex":       ((48,48,48), (15,15,15), "❯"),
        "youtube-tv": ((250,250,250), (226,232,240), "▶"),
        "spotify-tv": ((34,197,94), (22,163,74), "●"),
        "homebridge": ((126,34,206), (88,28,135), "⌂"),
        "tailscale":  ((64,64,72), (25,25,30), "•••"),
        "docker":     ((14,165,233), (3,105,161), "▥"),
        "atvloadly":  ((56,189,248), (2,132,199), "⬇"),
        "android":    ((74,222,70), (22,163,74), "A"),
        "settings":   ((226,232,240), (148,163,184), "⚙"),
    }

    def _installed_app_for_store(self, store_item):
        package = (store_item.get("installer") or {}).get("package", "")
        name = store_item.get("name", "")
        for app in self.apps:
            if package and app.get("package") == package:
                return app
            if name and app.get("name", "").lower() == name.lower():
                return app
        return None

    def home_items(self):
        items = []

        # First row mirrors the approved mockup and remains useful before apps
        # are installed: OK opens the matching Store item.
        for store_item in self.store_catalog[:6]:
            app = self._installed_app_for_store(store_item)
            items.append({
                "id": store_item.get("id", ""),
                "name": store_item.get("name", "Aplikace"),
                "kind": "app" if app else "store",
                "app": app,
                "store_item": store_item,
            })

        # Keep six featured slots stable even if a future catalog is smaller.
        while len(items) < 6:
            items.append({
                "id": "store",
                "name": "PiTV Store",
                "kind": "store-root",
            })

        for service in self.server_store_catalog[:4]:
            items.append({
                "id": service.get("id", ""),
                "name": "Docker" if service.get("id") == "docker" else service.get("name", "Server"),
                "kind": "server",
                "server_item": service,
            })

        items.append({"id": "android", "name": "Android / APK", "kind": "android"})
        items.append({"id": "settings", "name": "Nastavení", "kind": "settings"})
        return items[:12]

    def draw_home_hero(self):
        # Dark.jpg / Light.jpg are DESIGN REFERENCES ONLY. This hero is drawn
        # natively so the TV UI stays live, scalable and fully interactive.
        left = self.main_left()+int(self.w*.015)
        r = pygame.Rect(left, int(self.h*.055),
                        self.w-left-int(self.w*.025), int(self.h*.405))

        is_light = self.theme_name.endswith("Light")
        top = (248,250,252) if is_light else (12,22,47)
        bottom = (232,238,245) if is_light else (18,31,67)
        self.gradient_rect(r, top, bottom, radius=24)

        # Subtle concentric artwork inspired by the approved mockup.
        art = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        center = (int(r.w*.72), int(r.h*.48))
        ring_color = (110,125,150,28) if is_light else (120,145,255,26)
        for radius in (
            int(r.h*.34), int(r.h*.47), int(r.h*.60),
            int(r.h*.73), int(r.h*.86),
        ):
            pygame.draw.circle(art, ring_color, center, radius, max(1,int(self.h*.002)))
        glow = (80,120,255,18) if not is_light else (70,105,155,14)
        pygame.draw.circle(art, glow, center, int(r.h*.30))
        self.screen.blit(art, r.topleft)

        badge_y = r.y+int(self.h*.060)
        self.text("STREAM. APPS. SERVERS. MORE.", r.x+40, badge_y,
                  self.h*.014, self.t["muted"], True)
        self.text("PiTV", r.x+40, r.y+int(self.h*.098),
                  self.h*.072, self.t["text"], True)
        self.text("Your TV. Your Way.", r.x+42, r.y+int(self.h*.195),
                  self.h*.022, self.t["text"], True)
        self.text("Streamování, aplikace a domácí server na jednom místě.",
                  r.x+42, r.y+int(self.h*.238), self.h*.017, self.t["muted"])

        ar = pygame.Rect(r.x+42, r.bottom-int(self.h*.082),
                         int(self.w*.112), int(self.h*.050))
        self.gradient_rect(ar, self.t["accent2"], self.t["action"], radius=ar.h//2)
        surf = self.font(ar.h*.27, True).render("Procházet  ›", True, (255,255,255))
        self.screen.blit(surf, surf.get_rect(center=ar.center))

        # Live decorative app stack on the right, matching the visual hierarchy
        # of the approved reference without embedding the reference image.
        cards = [
            ((14,165,233),(2,132,199),"K"),
            ((248,48,58),(185,28,28),"▶"),
            ((168,85,247),(109,40,217),"◆"),
        ]
        cx = r.x+int(r.w*.69)
        cy = r.y+int(r.h*.25)
        cw = int(r.w*.17)
        ch = int(r.h*.43)
        offsets = [(-int(cw*.28), int(ch*.18)), (int(cw*.18), -int(ch*.05)), (int(cw*.58), int(ch*.20))]
        for idx, (colors, offset) in enumerate(zip(cards, offsets)):
            rr = pygame.Rect(cx+offset[0], cy+offset[1], cw, ch)
            self.gradient_rect(rr, colors[0], colors[1], radius=18)
            pygame.draw.rect(self.screen, (255,255,255,35) if not is_light else self.t["border"],
                             rr, 1, border_radius=18)
            icon = self.font(ch*.30, True).render(colors[2], True, (255,255,255))
            self.screen.blit(icon, icon.get_rect(center=rr.center))

        pygame.draw.rect(self.screen, self.t["border"], r, 1, border_radius=24)

        if self.cfg.get("show_clock", True):
            clock = self.font(self.h*.022, True).render(time.strftime("%H:%M"), True, self.t["text"])
            self.screen.blit(clock, (self.w-clock.get_width()-int(self.w*.060), int(self.h*.020)))
            gear = self.font(self.h*.023, True).render("⚙", True, self.t["muted"])
            self.screen.blit(gear, (self.w-int(self.w*.037), int(self.h*.018)))
        return r

    def draw_home_tile(self, item, rect, selected):
        # Tiles are generated UI, not crops from Dark.jpg / Light.jpg.
        style = self.HOME_TILE_STYLE.get(
            item.get("id", ""),
            (self.t["accent2"], self.t["action"], item.get("name","?")[:1].upper())
        )
        top, bottom, icon_text = style

        if selected:
            glow = rect.inflate(12, 12)
            halo = pygame.Surface((glow.w, glow.h), pygame.SRCALPHA)
            pygame.draw.rect(halo, (*self.t["accent"], 48),
                             halo.get_rect(), border_radius=20)
            self.screen.blit(halo, glow.topleft)

        self.gradient_rect(rect, top, bottom, radius=16)

        dark_icon = item.get("id") in ("youtube-tv", "settings")
        icon_color = (239,35,45) if item.get("id") == "youtube-tv" else (
            (51,65,85) if dark_icon else (255,255,255)
        )
        icon = self.font(rect.h*.36, True).render(str(icon_text), True, icon_color)
        self.screen.blit(icon, icon.get_rect(center=rect.center))

        pygame.draw.rect(
            self.screen,
            self.t["accent"] if selected else self.t["border"],
            rect,
            3 if selected else 1,
            border_radius=16,
        )

        label = self.font(self.h*.017, selected).render(
            item.get("name",""), True, self.t["text"]
        )
        self.screen.blit(
            label,
            (rect.centerx-label.get_width()//2, rect.bottom+int(self.h*.010))
        )

    def draw_home(self):
        self.draw_sidebar("home")
        items = self.home_items()
        hero = self.draw_home_hero()

        x = self.main_left()+int(self.w*.015)
        area_w = self.w-x-int(self.w*.025)
        cols = 6
        gap = int(self.w*.009)
        tile_w = int((area_w-(cols-1)*gap)/cols)
        tile_h = int(self.h*.100*float(self.cfg.get("tile_scale",1.0)))

        first_title_y = hero.bottom+int(self.h*.018)
        self.text("Doporučené aplikace", x, first_title_y, self.h*.020, self.t["text"], True)
        first_y = first_title_y+int(self.h*.035)

        for i, item in enumerate(items[:6]):
            rr = pygame.Rect(x+i*(tile_w+gap), first_y, tile_w, tile_h)
            self.draw_home_tile(item, rr, i == self.selected)

        second_title_y = first_y+tile_h+int(self.h*.050)
        self.text("Nástroje & služby", x, second_title_y, self.h*.020, self.t["text"], True)
        second_y = second_title_y+int(self.h*.035)

        for j, item in enumerate(items[6:12]):
            i = j+6
            rr = pygame.Rect(x+j*(tile_w+gap), second_y, tile_w, tile_h)
            self.draw_home_tile(item, rr, i == self.selected)

    SETTINGS = [
        ("Vzhled", "Motiv, dlaždice a hodiny"),
        ("Spořič obrazovky", "Nečinnost, černá obrazovka a CEC standby"),
        ("Síť", "Ethernet, Wi-Fi a IP adresy"),
        ("Zvuk", "HDMI audio a hlasitost TV"),
        ("HDMI / CEC", "TV ovladač a ovládání televize"),
        ("Aplikace", "PiTV Store a aplikace na domovské obrazovce"),
        ("Server Store", "Homebridge, Tailscale, Docker a ATVLoadly"),
        ("Android / APK", "APK inspector a Waydroid backend"),
        ("Aktualizace", "PiTV, Store aplikace a Ubuntu"),
        ("Systém", "Stav Raspberry Pi"),
        ("Napájení", "Restart nebo vypnutí"),
        ("O PiTV", "Verze a informace"),
    ]

    def draw_settings(self):
        self.settings_selected = max(0, min(self.settings_selected, len(self.SETTINGS)-1))
        self.draw_sidebar("settings")
        self.header("Nastavení", "Všechno důležité pro PiTV na jednom místě")

        left = self.main_left()+int(self.w*.018)
        top = int(self.h*.165)
        list_w = int(self.w*.34)
        panel_w = self.w-left-list_w-int(self.w*.055)
        row_h = int(self.h*.055)

        for i, (name, desc) in enumerate(self.SETTINGS):
            rr = pygame.Rect(left, top+i*row_h, list_w, int(row_h*.82))
            selected = i == self.settings_selected
            if selected:
                self.glass_panel(rr, True, 235, 14)
            self.text(name, rr.x+18, rr.y+int(rr.h*.22), rr.h*.28,
                      self.t["text"] if selected else self.t["muted"], selected)

        detail = pygame.Rect(left+list_w+int(self.w*.018), top,
                             panel_w, int(self.h*.64))
        self.glass_panel(detail, False, 225, 22)
        name, desc = self.SETTINGS[self.settings_selected]
        self.text(name, detail.x+30, detail.y+28, self.h*.032, self.t["text"], True)
        self.text(desc, detail.x+30, detail.y+int(self.h*.075), self.h*.019, self.t["muted"])

        if name == "Vzhled":
            self.text("Téma", detail.x+30, detail.y+int(self.h*.145), self.h*.017, self.t["muted"], True)
            options = [("PiTV Apple Dark", "Tmavé glass rozhraní"), ("PiTV Apple Light", "Světlé čisté rozhraní")]
            for j,(label,sub) in enumerate(options):
                rr = pygame.Rect(detail.x+30, detail.y+int(self.h*(.19+j*.115)),
                                 detail.w-60, int(self.h*.09))
                current = (j==0 and self.theme_name.endswith("Dark")) or (j==1 and self.theme_name.endswith("Light"))
                self.glass_panel(rr, current, 238, 16)
                self.text(label, rr.x+18, rr.y+14, self.h*.021, self.t["text"], True)
                self.text(sub, rr.x+18, rr.y+int(self.h*.047), self.h*.015, self.t["muted"])
        else:
            bullets = {
                "Spořič obrazovky": ["Hodiny / černá obrazovka", "CEC standby TV", "PiTV běží dál 24/7"],
                "Síť": ["Ethernet a Wi‑Fi", "IP adresa a stav", "Připojení ovladačem"],
                "Zvuk": ["Pouze HDMI", "Hlasitost přes CEC", "Test zvuku"],
                "HDMI / CEC": ["Zapnout / uspat TV", "Aktivní HDMI vstup", "Ovladač TV"],
                "Aplikace": ["PiTV Store", "Skrýt / zobrazit aplikace", "Android aplikace"],
                "Server Store": ["Homebridge", "Tailscale", "Docker", "ATVLoadly"],
                "Android / APK": ["Waydroid", "APK inspector", "Google Play"],
                "Aktualizace": ["PiTV", "Store katalogy", "Ubuntu balíčky"],
                "Systém": ["Teplota", "RAM a disk", "Uptime"],
                "Napájení": ["Restart", "Vypnutí serveru", "Potvrzení akce"],
                "O PiTV": ["Verze "+VERSION, "Standalone build", self.theme_name],
            }.get(name, [desc])
            yy = detail.y+int(self.h*.145)
            for b in bullets:
                self.pill(b, detail.x+30, yy, self.t["accent"])
                yy += int(self.h*.055)
        self.text("↑/↓ vybere • OK otevře • Back návrat",
                  left, int(self.h*.91), self.h*.016, self.t["muted"])

    def draw_rows(self, title, subtitle, rows, selected=0, footer=""):
        self.draw_sidebar("settings")
        self.header(title, subtitle)
        x = self.main_left()+int(self.w*.022)
        y0 = int(self.h*.165)
        row_h = int(self.h*.071)
        width = self.w-x-int(self.w*.04)
        panel = pygame.Rect(x-int(self.w*.008), y0-int(self.h*.012),
                            width+int(self.w*.016), int(self.h*.64))
        self.glass_panel(panel, False, 218, 22)
        for i, row in enumerate(rows):
            label, value = row[0], row[1]
            y = y0+i*row_h
            rr = pygame.Rect(x, y, width, int(row_h*.82))
            active = i == selected
            if active:
                self.glass_panel(rr, True, 235, 14)
            self.text(label, rr.x+22, rr.y+int(rr.h*.27), rr.h*.27,
                      self.t["text"] if active else self.t["muted"], active)
            val = str(value)
            surf = self.font(rr.h*.25, True).render(val, True,
                        self.t["accent"] if active else self.t["text"])
            maxw = int(rr.w*.47)
            while surf.get_width() > maxw and len(val) > 4:
                val = val[:-2] + "…"
                surf = self.font(rr.h*.25, True).render(val, True,
                            self.t["accent"] if active else self.t["text"])
            self.screen.blit(surf, (rr.right-surf.get_width()-22,
                                    rr.y+int(rr.h*.28)))
        if footer:
            self.text(footer, x, int(self.h*.91), self.h*.016, self.t["muted"])

    def draw_appearance(self):
        theme = self.theme_name
        scale = float(self.cfg.get("tile_scale", 1.0))
        scale_name = "Malé" if scale < .95 else ("Velké" if scale > 1.05 else "Normální")
        rows = [
            ("Motiv", theme),
            ("Velikost dlaždic", scale_name),
            ("Hodiny na ploše", "Zapnuto" if self.cfg.get("show_clock") else "Vypnuto"),
        ]
        self.draw_rows("Vzhled", "Dvě sjednocená PiTV Apple témata", rows, self.sub_selected,
                       "↑/↓ vybere • ←/→ změní • Back návrat")

    def draw_screensaver_settings(self):
        enabled = self.cfg.get("screensaver_enabled", True)
        mode = self.cfg.get("screensaver_mode", "clock")
        saver_after = int(self.cfg.get("screensaver_after_min", 5))
        black_after = int(self.cfg.get("screensaver_black_after_min", 15))
        standby_after = int(self.cfg.get("screensaver_cec_standby_after_min", 30))
        fmt = lambda v: "Vypnuto" if int(v) == 0 else f"{int(v)} min"
        rows = [
            ("Spořič", "Zapnuto" if enabled else "Vypnuto"),
            ("Spustit po", f"{saver_after} min"),
            ("Typ", "Hodiny" if mode == "clock" else "Černá obrazovka"),
            ("Úplně zčernat po", fmt(black_after)),
            ("TV do standby přes CEC", fmt(standby_after)),
            ("Náhled", "OK spustí"),
        ]
        self.draw_rows("Spořič obrazovky", "PiTV i server dál běží 24/7",
                       rows, self.sub_selected,
                       "←/→ změní • OK na Náhledu • Back se vrátí")

    def draw_network(self):
        items = self.network_items()
        self.network_selected = max(0, min(self.network_selected, max(0, len(items)-1)))
        ips = " · ".join(f"{i}: {ip}" for i, ip in get_ipv4()) or "bez IP"
        subtitle = f"{socket.gethostname()} · {ips}"
        # Keep max 8 rows on TV and scroll around selection.
        visible = 8
        start = max(0, min(self.network_selected-visible//2, max(0, len(items)-visible)))
        subset = items[start:start+visible]
        selected = self.network_selected-start
        rows = [(x["title"], x["detail"]) for x in subset]
        if not rows:
            rows = [("Síť", "NetworkManager není aktivní")]
            selected = 0
        self.draw_rows("Síť", subtitle, rows, selected,
                       "OK = akce/připojit • heslo se zadává ovladačem • Ethernet PiTV nepřepisuje")

    def draw_audio(self):
        items = self.audio_items()
        rows = [(x["title"], x["detail"]) for x in items]
        self.draw_rows("Zvuk", "PiTV používá pouze zvuk přes HDMI", rows, self.audio_selected,
                       "Hlasitost TV/receiveru jde přes HDMI‑CEC")

    CEC_ACTIONS = [
        ("Zapnout / probudit TV", "Power On + Active Source", cec_tv_on),
        ("Přepnout TV na PiTV", "Active Source", cec_active_source),
        ("Hlasitost +", "TV / receiver přes CEC", cec_volume_up),
        ("Hlasitost −", "TV / receiver přes CEC", cec_volume_down),
        ("Mute / unmute", "TV / receiver přes CEC", cec_mute),
        ("Standby TV", "Vypnout obrazovku TV", cec_tv_standby),
    ]

    def draw_cec(self):
        self.draw_sidebar("settings")
        ports = get_hdmi_ports()
        port_text = " · ".join(f"{p['name']} {p['status']}" for p in ports) or "HDMI stav neznámý"
        self.header("HDMI / CEC", port_text)

        x = self.main_left()+int(self.w*.022)
        y = int(self.h*.165)
        self.pill("CEC READY" if cec_available() else "CEC CHYBÍ", x, y,
                  self.t["good"] if cec_available() else self.t["bad"])

        y0 = int(self.h*.245)
        row_h = int(self.h*.082)
        width = self.w-x-int(self.w*.04)
        for i, (name, desc, _) in enumerate(self.CEC_ACTIONS):
            rr = pygame.Rect(x, y0+i*row_h, width, int(row_h*.78))
            selected = i == self.cec_selected
            self.glass_panel(rr, selected, 232, 16)
            self.text(name, rr.x+22, rr.y+int(rr.h*.18), rr.h*.28, self.t["text"], True)
            self.text(desc, rr.x+22, rr.y+int(rr.h*.55), rr.h*.18,
                      self.t["accent"] if selected else self.t["muted"])

        self.text("↑/↓ vybere • OK spustí • Back návrat",
                  x, int(self.h*.90), self.h*.016, self.t["muted"])

    def app_items(self):
        hidden = set(self.cfg.get("hidden_apps", []))
        rows = [{"name": "PiTV Store", "store": True, "visible": True}]
        for a in self.apps:
            rows.append({
                "name": a["name"],
                "visible": a["name"] not in hidden,
                "app": a,
            })
        rows.append({"name": "Obnovit seznam aplikací", "refresh": True, "visible": True})
        return rows

    def draw_apps_settings(self):
        items = self.app_items()
        self.apps_selected = max(0, min(self.apps_selected, max(0, len(items)-1)))
        rows = []
        for x in items:
            if x.get("store"):
                rows.append((x["name"], "Instalace jedním OK"))
            elif x.get("refresh"):
                rows.append((x["name"], "OK"))
            else:
                rows.append((x["name"], "Na ploše" if x["visible"] else "Skryto"))

        visible = 8
        start = max(0, min(self.apps_selected-visible//2, max(0, len(rows)-visible)))
        subset = rows[start:start+visible]
        selected = self.apps_selected-start if subset else 0
        self.draw_rows("Aplikace", "Store + aplikace dostupné PiTV", subset, selected,
                       "↑/↓ vybere • OK = Store / zobrazit / skrýt • Back návrat")

    STORE_STATE_LABELS = {
        "installed": "Nainstalováno",
        "available": "Instalovat",
        "downloaded": "Staženo · dokončit instalaci",
        "unsupported": "Nepodporováno",
        "checking": "Kontroluji…",
    }

    def refresh_store_async(self):
        if self.store_refreshing:
            return
        self.store_refreshing = True
        self.store_catalog = load_store_catalog()
        self.store_states = {x.get("id",""): "checking" for x in self.store_catalog}

        def worker():
            for item in self.store_catalog:
                try:
                    state = store_state(item)
                except Exception:
                    state = "unsupported"
                self.store_states[item.get("id","")] = state
            self.store_refreshing = False

        threading.Thread(target=worker, daemon=True).start()

    def draw_store(self):
        self.draw_sidebar("store")
        items = self.store_catalog
        if not items:
            self.store_selected = 0
            self.header("PiTV Store", "Katalog aplikací")
            self.text("Katalog je prázdný", self.main_left()+40, int(self.h*.25), self.h*.025)
            return

        self.store_selected = max(0, min(self.store_selected, len(items)-1))
        selected_item = items[self.store_selected]
        state = self.store_states.get(selected_item.get("id",""), "checking")
        status = "Instaluji…" if self.store_busy_id == selected_item.get("id") else self.STORE_STATE_LABELS.get(state,state)
        self.draw_hero(
            selected_item.get("name","Aplikace"),
            selected_item.get("description","Aplikace pro PiTV"),
            f"{selected_item.get('platform','').upper()} · {status}",
            "OK · Instalovat" if state != "installed" else "Nainstalováno",
        )

        x = self.main_left()+int(self.w*.018)
        y = int(self.h*.355)
        self.text("Doporučené", x, y, self.h*.024, self.t["text"], True)
        y += int(self.h*.045)
        cols = 3
        gap = int(self.w*.015)
        area_w = self.w-x-int(self.w*.035)
        tile_w = int((area_w-(cols-1)*gap)/cols)
        tile_h = int(self.h*.145)
        for i,item in enumerate(items):
            rr = pygame.Rect(x+(i%cols)*(tile_w+gap),
                             y+(i//cols)*(tile_h+int(self.h*.05)), tile_w, tile_h)
            selected = i == self.store_selected
            self.glass_panel(rr, selected, 232, 18)
            st = self.store_states.get(item.get("id",""), "checking")
            st_label = "Instaluji…" if self.store_busy_id == item.get("id") else self.STORE_STATE_LABELS.get(st,st)
            self.text(item.get("name","Aplikace"), rr.x+18, rr.y+18, rr.h*.18, self.t["text"], True)
            self.text(item.get("category","Aplikace"), rr.x+18, rr.y+int(rr.h*.44), rr.h*.12, self.t["muted"])
            self.pill(st_label, rr.x+18, rr.bottom-int(rr.h*.31),
                      self.t["good"] if st=="installed" else self.t["accent"])

    def install_store_item(self, item):
        store_id = item.get("id","")
        if not store_id or self.store_busy_id:
            return

        state = self.store_states.get(store_id)
        if state == "installed":
            # Installed Store entries are actions, not dead-end status cards.
            installer = item.get("installer", {})
            itype = installer.get("type")
            if itype == "flatpak":
                self.launch_linux({"name": item.get("name","Aplikace"), "command": f"flatpak run {installer.get('app_id','')}"})
                return
            if itype == "kodi_addon":
                addon_id = installer.get("addon_id", "")
                if addon_id:
                    self.launch_linux({
                        "name": item.get("name", "Plex"),
                        "command": f"/usr/local/bin/pitv-kodi-addon run {addon_id}",
                    })
                    return
            app = next((a for a in self.apps if a.get("name","").lower() == item.get("name","").lower()), None)
            if app:
                self.launch(app)
                return
            package = installer.get("package") or installer.get("expected_package")
            if package:
                self.launch_apk({"name": item.get("name","Aplikace"), "kind":"apk", "package":package, "apk_path":""})
                return
            self.show_toast(f"{item.get('name','Aplikace')} je nainstalovaná")
            return

        installer = item.get("installer", {})
        install_type = installer.get("type")
        self.store_busy_id = store_id
        self.set_operation(f"Instaluji {item.get('name','aplikaci')}…")
        self.show_toast(f"Instaluji {item.get('name','aplikaci')}…", 4)

        def finish(message, ok=True):
            self.store_busy_id = ""
            self.apps = load_apps()
            try:
                self.store_states[store_id] = store_state(item)
            except Exception:
                self.store_states[store_id] = "installed" if ok else "available"
            self.finish_operation(message, ok)
            self.show_toast(message, 5)

        def progress(done, total):
            if total:
                self.set_operation(f"Stahuji {item.get('name','aplikaci')}…", done * 100 / total)

        def worker():
            try:
                if install_type == "apt":
                    package = installer.get("package","")
                    ok, msg = run_privileged("apt-install", {"package": package}, 1200)
                    finish(msg, ok)
                    return

                if install_type == "flatpak":
                    app_id = installer.get("app_id","")
                    ok, msg = run_privileged("flatpak-install", {"app_id": app_id}, 1800)
                    finish(msg, ok)
                    return

                if install_type == "kodi_addon":
                    package = installer.get("package", "kodi")
                    addon_id = installer.get("addon_id", "")
                    if not addon_id:
                        finish("Kodi add-on nemá ID", False)
                        return
                    if shutil.which("kodi") is None:
                        self.set_operation("Instaluji Kodi pro Plex…")
                        ok, msg = run_privileged("apt-install", {"package": package}, 1200)
                        if not ok:
                            finish(msg, False)
                            return
                    if shutil.which("kodi-send") is None:
                        self.set_operation("Instaluji ovládání Kodi pro Plex…")
                        ok, msg = run_privileged(
                            "apt-install", {"package": "kodi-eventclients-kodi-send"}, 1200
                        )
                        if not ok:
                            finish(msg, False)
                            return
                    try:
                        env = build_gui_env()
                        problem = gui_env_error(env)
                        if problem:
                            finish(f"Kodi/Plex: {problem}", False)
                            return
                        log_path = Path("/tmp/pitv-kodi-install.log")
                        log_path.write_text("", encoding="utf-8")
                        with log_path.open("a", encoding="utf-8") as log:
                            proc = subprocess.Popen(
                                ["/usr/local/bin/pitv-kodi-addon", "install", addon_id],
                                env=env,
                                cwd=str(Path.home()),
                                start_new_session=True,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                            )
                        self.external_proc = proc
                        self.external_kind = "linux"
                        self.store_busy_id = ""
                        self.set_operation(f"Otevírám {item.get('name','Plex')} v Kodi…")
                        self.show_toast("Kodi nainstaluje Plex přehrávač z Kodi.tv repozitáře", 6)
                        self._watch_launch(
                            proc, item.get("name","Plex"), "linux", str(log_path)
                        )
                    except Exception as e:
                        finish(f"Kodi/Plex: {e}", False)
                    return

                if install_type in ("github_release_apk", "direct_apk"):
                    if not waydroid_available():
                        self.set_operation("Připravuji Android + Google Play…")
                        ok, msg = run_privileged("waydroid-install", {}, 1800)
                        if not ok:
                            finish(msg, False)
                            return

                    if install_type == "github_release_apk":
                        path, version = download_github_apk(item, progress=progress)
                    else:
                        path, version = download_direct_apk(item, progress=progress)

                    meta = inspect_apk(path)
                    package = meta.get("package","")
                    expected_package = installer.get("expected_package", "")
                    if expected_package and package != expected_package:
                        try:
                            Path(path).unlink()
                        except Exception:
                            pass
                        finish(
                            f"APK odmítnuto: package {package or 'neznámý'} neodpovídá {expected_package}",
                            False,
                        )
                        return
                    app = {
                        "name": meta.get("name") or item.get("name","APK"),
                        "kind": "apk",
                        "apk_path": str(path),
                        "package": package,
                        "activity": meta.get("activity",""),
                        "version": meta.get("version","") or version,
                        "sdk": meta.get("sdk",""),
                        "tv": bool(meta.get("tv")),
                    }

                    ok, msg = run_privileged("waydroid-container-start", {}, 90)
                    if not ok:
                        finish(msg, False)
                        return
                    ok, msg = ensure_apk_installed(app)
                    if ok:
                        mark_android_installed(item, package, path, version)
                        finish(f"{item.get('name','APK')} nainstalováno", True)
                    else:
                        finish(msg or "APK staženo; instalaci dokončí Waydroid", False)
                    return

                if install_type == "play_store":
                    if not waydroid_available():
                        self.set_operation("Připravuji Android + Google Play…")
                        ok, msg = run_privileged("waydroid-install", {}, 1800)
                        if not ok:
                            finish(msg, False)
                            return
                    package = installer.get("package","")
                    if not package:
                        finish("Store položka nemá package ID", False)
                        return
                    try:
                        env = build_gui_env()
                        problem = gui_env_error(env)
                        if problem:
                            finish(f"Google Play: {problem}", False)
                            return
                        self.external_proc = subprocess.Popen(
                            ["/usr/local/bin/pitv-waydroid-launch", "--play-store", package],
                            env=env,
                            cwd=str(Path.home()),
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self.external_kind = "apk"
                        self.store_busy_id = ""
                        self.set_operation(f"Otevírám {item.get('name','aplikaci')} v Google Play…")
                        self.show_toast(f"Otevírám {item.get('name','aplikaci')} v Google Play", 5)
                        self._watch_launch(self.external_proc, "Google Play", "apk")
                    except Exception as e:
                        finish(f"Google Play: {e}", False)
                    return

                finish("Tento typ instalace PiTV Store nepodporuje", False)
            except Exception as e:
                finish(f"Store: {e}", False)

        threading.Thread(target=worker, daemon=True).start()

    SERVER_STATE_LABELS = {
        "active": "Běží",
        "running": "Běží",
        "inactive": "Nainstalováno · neběží",
        "exited": "Nainstalováno · zastaveno",
        "created": "Nainstalováno · zastaveno",
        "dead": "Nainstalováno · neběží",
    }

    def refresh_server_store_async(self):
        if self.server_store_refreshing:
            return
        self.server_store_refreshing = True
        self.server_store_catalog = load_server_catalog()

        def worker():
            ok, msg = run_privileged("server-store-status", {}, 30)
            if ok:
                try:
                    self.server_store_states = json.loads(msg)
                except Exception:
                    self.server_store_states = {}
            self.server_store_refreshing = False

        threading.Thread(target=worker, daemon=True).start()

    def server_store_status_label(self, item):
        sid = item.get("id", "")
        if self.server_store_busy_id == sid:
            return "Instaluji…"

        state = self.server_store_states.get(sid, {})
        if not state:
            return "Kontroluji…"
        if not state.get("installed"):
            requires = item.get("requires", [])
            if requires:
                return "Instalovat · vyžaduje " + ", ".join(requires)
            return "Instalovat"

        if sid == "tailscale":
            if state.get("authenticated"):
                return f"Běží · {state.get('ip','')}".strip(" ·")
            return "Nainstalováno · přihlásit"

        label = self.SERVER_STATE_LABELS.get(state.get("state", ""), "Nainstalováno")
        port = item.get("web_port")
        if port:
            ips = get_ipv4()
            if ips:
                label += f" · {ips[0][1]}:{port}"
        return label

    def draw_server_store(self):
        self.draw_sidebar("server_store")
        items = self.server_store_catalog
        if not items:
            self.server_store_selected = 0
            self.header("Server Store", "Služby na pozadí")
            self.text("Katalog je prázdný", self.main_left()+40, int(self.h*.25), self.h*.025)
            return

        self.server_store_selected = max(0, min(self.server_store_selected, len(items)-1))
        selected_item = items[self.server_store_selected]
        status = self.server_store_status_label(selected_item)
        self.draw_hero(
            selected_item.get("name","Služba"),
            selected_item.get("description","Serverová služba pro PiTV"),
            f"SERVER · {status}",
            "OK · Spravovat",
        )

        x = self.main_left()+int(self.w*.018)
        y = int(self.h*.355)
        self.text("Služby na pozadí", x, y, self.h*.024, self.t["text"], True)
        y += int(self.h*.045)
        cols = 2
        gap = int(self.w*.015)
        area_w = self.w-x-int(self.w*.035)
        tile_w = int((area_w-gap)/cols)
        tile_h = int(self.h*.145)
        for i,item in enumerate(items):
            rr = pygame.Rect(x+(i%cols)*(tile_w+gap),
                             y+(i//cols)*(tile_h+int(self.h*.045)), tile_w, tile_h)
            selected = i == self.server_store_selected
            self.glass_panel(rr, selected, 232, 18)
            status = self.server_store_status_label(item)
            self.text(item.get("name","Služba"), rr.x+20, rr.y+18, rr.h*.18, self.t["text"], True)
            self.text(item.get("category","Server"), rr.x+20, rr.y+int(rr.h*.44), rr.h*.12, self.t["muted"])
            self.pill(status, rr.x+20, rr.bottom-int(rr.h*.31),
                      self.t["good"] if ("Běží" in status or "Nainstalováno" in status) else self.t["accent"])

    def install_server_store_item(self, item):
        sid = item.get("id", "")
        if not sid or self.server_store_busy_id:
            return

        state = self.server_store_states.get(sid, {})
        if state.get("installed"):
            if sid == "tailscale" and not state.get("authenticated"):
                self.server_store_busy_id = sid
                self.show_toast("Připravuji přihlášení Tailscale…", 4)

                def login_worker():
                    ok, msg = run_privileged("tailscale-login", {}, 30)
                    self.server_store_busy_id = ""
                    self.show_toast(msg, 8)
                    self.refresh_server_store_async()

                threading.Thread(target=login_worker, daemon=True).start()
                return

            port = item.get("web_port")
            if port:
                ips = get_ipv4()
                if ips:
                    self.show_toast(f"{item.get('name')}: http://{ips[0][1]}:{port}", 7)
                    return
            self.show_toast(f"{item.get('name','Služba')} už je nainstalovaná")
            return

        requires = item.get("requires", [])
        for dep in requires:
            dep_state = self.server_store_states.get(dep, {})
            if not dep_state.get("installed"):
                self.show_toast(f"Nejdřív nainstaluj {dep}", 5)
                return

        self.server_store_busy_id = sid
        self.set_operation(f"Instaluji {item.get('name','službu')}…")
        self.show_toast(f"Instaluji {item.get('name','službu')}…", 5)

        def worker():
            ok, msg = run_privileged("server-store-install", {"target": sid}, 1800)
            self.server_store_busy_id = ""
            self.finish_operation(msg, ok)
            self.show_toast(msg, 7)
            self.refresh_server_store_async()

        threading.Thread(target=worker, daemon=True).start()

    def android_items(self):
        apks = [a for a in self.apps if a.get("kind") == "apk"]
        runtime = "Nainstalován" if waydroid_available() else "OK · Nainstalovat + Google Play"
        items = [
            ("Waydroid + Google Play", runtime),
            ("Waydroid session", waydroid_status()),
            ("APK složka", "/var/lib/pitv/apks"),
            ("Nalezená APK", str(len(apks))),
            ("Obnovit APK", "OK"),
            ("Otevřít plné Android UI", "OK" if waydroid_available() else "Nejdřív nainstalovat Waydroid"),
        ]
        for a in apks[:4]:
            meta = a.get("package") or "bez package"
            items.append((a.get("name","APK"), meta))
        return items

    def install_waydroid_async(self):
        if waydroid_available():
            self.show_toast("Waydroid už je nainstalovaný")
            return
        if self.updates_busy:
            return

        self.updates_busy = True
        self.set_operation("Instaluji Waydroid + Google Play…")
        self.show_toast("Instaluji Waydroid + Google Play…", 6)

        def worker():
            ok, msg = run_privileged("waydroid-install", {}, 1800)
            self.updates_busy = False
            self.finish_operation(msg, ok)
            self.show_toast(msg, 7)

        threading.Thread(target=worker, daemon=True).start()

    def draw_android(self):
        rows = self.android_items()
        self.android_selected = max(0, min(self.android_selected, max(0, len(rows)-1)))
        visible = 8
        start = max(0, min(self.android_selected-visible//2, max(0, len(rows)-visible)))
        self.draw_rows("Android / APK", "APK inspector · aapt/apktool · Waydroid",
                       rows[start:start+visible], self.android_selected-start,
                       "Nahraj .apk přes SSH do /var/lib/pitv/apks • OK = akce")

    def update_items(self):
        if self.remote_pitv:
            pitv_value = f"{VERSION} → {self.remote_pitv}" if is_newer(self.remote_pitv, VERSION) else f"{VERSION} · aktuální"
        else:
            pitv_value = f"{VERSION} · {self.updates_status}"

        ubuntu_value = "—" if self.update_count is None else f"{self.update_count} balíčků"
        if self.update_checking:
            ubuntu_value = "Kontroluji…"

        installed_linux = []
        for item in self.store_catalog:
            ins = item.get("installer", {})
            if ins.get("type") == "apt":
                try:
                    if store_state(item) == "installed":
                        installed_linux.append(item.get("name", ins.get("package","")))
                except Exception:
                    pass

        linux_value = ", ".join(installed_linux) if installed_linux else "žádné"
        return [
            ("PiTV", pitv_value),
            ("Store + Server katalog", "GitHub · PiTV"),
            ("Linux Store aplikace", linux_value),
            ("Ubuntu", ubuntu_value),
            ("Zkontrolovat vše", "OK"),
            ("Aktualizovat PiTV", "OK" if not self.updates_busy else "Probíhá…"),
            ("Aktualizovat Store katalog", "OK"),
            ("Aktualizovat Linux Store aplikace", "OK"),
            ("Aktualizovat Ubuntu", "OK"),
            ("Restartovat PiTV UI", "OK"),
        ]

    def draw_updates(self):
        self.draw_sidebar("updates")
        rows = self.update_items()
        self.header("Aktualizace", "PiTV, Store a systém na jednom místě")

        x = self.main_left()+int(self.w*.02)
        top = int(self.h*.165)
        cols = 2
        gap = int(self.w*.018)
        tile_w = int((self.w-x-int(self.w*.05)-gap)/2)
        tile_h = int(self.h*.115)

        for i,(label,value) in enumerate(rows):
            rr = pygame.Rect(x+(i%cols)*(tile_w+gap),
                             top+(i//cols)*(tile_h+int(self.h*.022)), tile_w, tile_h)
            selected = i == self.updates_selected
            self.glass_panel(rr, selected, 232, 18)
            self.text(label, rr.x+20, rr.y+16, rr.h*.20, self.t["text"], True)
            self.text(str(value), rr.x+20, rr.y+int(rr.h*.52), rr.h*.145,
                      self.t["accent"] if selected else self.t["muted"])
        self.text("OK = provést vybranou akci • aktualizace PiTV zachová nastavení",
                  x, int(self.h*.91), self.h*.016, self.t["muted"])

    def check_updates_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.updates_status = "Kontroluji…"
        self.show_toast("Kontroluji aktualizace…", 4)

        def worker():
            try:
                try:
                    self.remote_pitv = remote_pitv_version()
                except Exception:
                    self.remote_pitv = ""

                run_privileged("apt-update", {}, 300)
                self.update_count = count_updates()

                self.store_catalog = load_store_catalog()
                for item in self.store_catalog:
                    try:
                        self.store_states[item.get("id","")] = store_state(item)
                    except Exception:
                        pass

                if self.remote_pitv and is_newer(self.remote_pitv, VERSION):
                    self.updates_status = "Nová verze"
                    self.show_toast(f"Nové PiTV {self.remote_pitv} je dostupné", 5)
                else:
                    self.updates_status = "Aktuální"
                    self.show_toast("Kontrola aktualizací dokončena", 4)
            finally:
                self.updates_busy = False

        threading.Thread(target=worker, daemon=True).start()

    def update_pitv_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.set_operation("Aktualizuji PiTV z GitHubu…")
        self.show_toast("Aktualizuji PiTV z GitHubu…", 5)

        def worker():
            ok, msg = run_privileged("pitv-self-update", {}, 1800)
            self.updates_busy = False
            self.finish_operation("PiTV aktualizováno" if ok else msg, ok)
            if ok:
                self.show_toast("PiTV aktualizováno · restartuji rozhraní", 4)
                time.sleep(1)
                pygame.quit()
                os.execv(sys.executable, [sys.executable, __file__])
            else:
                self.show_toast(msg, 6)

        threading.Thread(target=worker, daemon=True).start()

    def update_store_catalog_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.set_operation("Aktualizuji Store katalog…")
        self.show_toast("Aktualizuji PiTV Store katalog…", 4)

        def worker():
            ok, msg = run_privileged("store-catalog-update", {}, 60)
            if ok:
                self.store_catalog = load_store_catalog()
                self.store_states = {}
                self.refresh_store_async()
            self.updates_busy = False
            self.finish_operation(msg, ok)
            self.show_toast(msg, 5)

        threading.Thread(target=worker, daemon=True).start()

    def update_linux_store_apps_async(self):
        if self.updates_busy:
            return
        packages = []
        for item in self.store_catalog:
            ins = item.get("installer", {})
            if ins.get("type") == "apt":
                try:
                    if store_state(item) == "installed":
                        packages.append(ins.get("package",""))
                except Exception:
                    pass
        packages = [p for p in packages if p]
        if not packages:
            self.show_toast("Žádné Linux Store aplikace k aktualizaci")
            return

        self.updates_busy = True
        self.set_operation("Aktualizuji Store aplikace…")
        self.show_toast("Aktualizuji Store aplikace…", 4)

        def worker():
            ok, msg = run_privileged("apt-store-upgrade", {"packages": packages}, 1200)
            self.updates_busy = False
            self.apps = load_apps()
            self.finish_operation(msg, ok)
            self.show_toast(msg, 5)

        threading.Thread(target=worker, daemon=True).start()

    def update_ubuntu_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.set_operation("Aktualizuji Ubuntu…")
        self.show_toast("Aktualizuji Ubuntu balíčky…", 5)

        def worker():
            ok, msg = run_privileged("apt-upgrade", {}, 1200)
            self.update_count = count_updates()
            self.updates_busy = False
            self.finish_operation(msg, ok)
            self.show_toast(msg, 5)

        threading.Thread(target=worker, daemon=True).start()

    def system_items(self):
        upd = "Kontroluji…" if self.update_checking else (
            "—" if self.update_count is None else f"{self.update_count} balíčků"
        )
        return [
            ("Zařízení", get_model()),
            ("Teplota", get_temp()),
            ("RAM", get_mem()),
            ("Disk /", get_disk()),
            ("Uptime", uptime()),
            ("Kernel", cmd_output(["uname", "-r"]) or "—"),
            ("Aktualizace", upd),
            ("Zkontrolovat aktualizace", "OK"),
            ("Nainstalovat aktualizace", "OK"),
            ("Restartovat PiTV UI", "OK"),
        ]

    def draw_system(self):
        rows = self.system_items()
        self.system_selected = max(0, min(self.system_selected, max(0, len(rows)-1)))
        visible = 8
        start = max(0, min(self.system_selected-visible//2, max(0, len(rows)-visible)))
        self.draw_rows("Systém", "Ubuntu Server / Raspberry Pi",
                       rows[start:start+visible], self.system_selected-start,
                       "Aktualizace systému běží na pozadí; server se sám nerestartuje")

    def draw_power(self):
        rows = [
            ("Restartovat Raspberry Pi", "Vyžaduje potvrzení"),
            ("Vypnout Raspberry Pi", "Vyžaduje potvrzení"),
        ]
        self.draw_rows("Napájení", "PiTV i serverové služby", rows, self.sub_selected,
                       "OK → potvrzení")

    def draw_about(self):
        ports = get_hdmi_ports()
        hdmi = ", ".join(p["name"] for p in ports if p["status"] == "connected") or "—"
        ts_state, ts_ip = tailscale_info()
        rows = [
            ("PiTV", VERSION),
            ("Režim", "Ubuntu Server + labwc / Wayland"),
            ("UI", f"Pygame {pygame.version.ver}"),
            ("Uživatel", os.environ.get("USER", "?")),
            ("HDMI", hdmi),
            ("CEC", "Dostupné" if cec_available() else "Nedostupné"),
            ("Síťová správa", "NetworkManager" if nm_available() else "Systém / SSH"),
            ("Tailscale", f"{ts_state} {ts_ip}".strip()),
            ("Android", "Waydroid" if waydroid_available() else "není připraven"),
        ]
        self.draw_rows("O PiTV", "TV vrstva nad Ubuntu Serverem", rows, 99,
                       "Homebridge, Tailscale a ostatní služby běží mimo PiTV")

    def draw(self):
        self.draw_background()
        if self.page == "home": self.draw_home()
        elif self.page == "settings": self.draw_settings()
        elif self.page == "appearance": self.draw_appearance()
        elif self.page == "screensaver": self.draw_screensaver_settings()
        elif self.page == "network": self.draw_network()
        elif self.page == "audio": self.draw_audio()
        elif self.page == "cec": self.draw_cec()
        elif self.page == "apps": self.draw_apps_settings()
        elif self.page == "store": self.draw_store()
        elif self.page == "server_store": self.draw_server_store()
        elif self.page == "android": self.draw_android()
        elif self.page == "updates": self.draw_updates()
        elif self.page == "system": self.draw_system()
        elif self.page == "power": self.draw_power()
        elif self.page == "about": self.draw_about()

        if self.toast and time.time() < self.toast_until:
            f = self.font(self.h*.021, True)
            surf = f.render(self.toast, True, self.t["text"])
            pad_x, pad_y = 24, 14
            rect = pygame.Rect(0, 0, surf.get_width()+pad_x*2, surf.get_height()+pad_y*2)
            rect.midbottom = (self.w//2, self.h-int(self.h*.035))
            pygame.draw.rect(self.screen, self.t["panel2"], rect, border_radius=14)
            pygame.draw.rect(self.screen, self.t["border"], rect, 1, border_radius=14)
            self.screen.blit(surf, (rect.x+pad_x, rect.y+pad_y))
        elif self.toast:
            self.toast = ""

        self.draw_operation()

        if self.keyboard_active:
            self.draw_keyboard()
        if self.confirm_active:
            self.draw_confirm()

        pygame.display.flip()

    WTYPE_KEYS = {
        pygame.K_UP: "Up", pygame.K_DOWN: "Down", pygame.K_LEFT: "Left",
        pygame.K_RIGHT: "Right", pygame.K_RETURN: "Return", pygame.K_KP_ENTER: "Return",
        pygame.K_ESCAPE: "Escape", pygame.K_SPACE: "space",
    }
    ANDROID_KEYEVENTS = {
        pygame.K_UP: "19",          # KEYCODE_DPAD_UP
        pygame.K_DOWN: "20",        # KEYCODE_DPAD_DOWN
        pygame.K_LEFT: "21",        # KEYCODE_DPAD_LEFT
        pygame.K_RIGHT: "22",       # KEYCODE_DPAD_RIGHT
        pygame.K_RETURN: "23",      # KEYCODE_DPAD_CENTER
        pygame.K_KP_ENTER: "23",
        pygame.K_ESCAPE: "4",       # KEYCODE_BACK
        pygame.K_SPACE: "85",       # KEYCODE_MEDIA_PLAY_PAUSE
    }

    def _mark_relay_echo(self, key):
        # If the foreground app failed to take focus, wtype can send our
        # synthetic key back to the PiTV SDL window. Never relay that echo
        # again or one physical CEC press can become a feedback loop.
        self._relay_echo[key] = time.monotonic() + 0.30

    def _consume_relay_echo(self, key):
        now = time.monotonic()
        expired = [k for k, until in self._relay_echo.items() if until < now]
        for k in expired:
            self._relay_echo.pop(k, None)
        until = self._relay_echo.get(key, 0.0)
        if until >= now:
            self._relay_echo.pop(key, None)
            return True
        return False

    def relay_to_external(self, key):
        if self.external_kind == "apk":
            code = self.ANDROID_KEYEVENTS.get(key)
            if code and shutil.which("waydroid"):
                try:
                    subprocess.Popen(
                        ["waydroid", "shell", "input", "keyevent", code],
                        env=build_gui_env(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            return

        name = self.WTYPE_KEYS.get(key)
        if name and shutil.which("wtype"):
            try:
                self._mark_relay_echo(key)
                subprocess.Popen(
                    ["wtype", "-k", name],
                    env=build_gui_env(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self._relay_echo.pop(key, None)

    def stop_external(self):
        proc = self.external_proc
        kind = self.external_kind
        self.external_proc = None
        self.external_kind = None
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 15)
            except Exception:
                try: proc.terminate()
                except Exception: pass
        if kind == "apk":
            try:
                subprocess.Popen(["waydroid", "session", "stop"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.apps = load_apps()
            self.refresh_store_async()
        self.page = "home"
        self.show_toast("PiTV")

    def _watch_launch(self, proc, name, kind, log_path=None):
        def worker():
            # A healthy GUI normally stays alive. Catch immediate launcher
            # failures instead of silently returning to PiTV.
            try:
                rc = proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.finish_operation(f"{name} spuštěno", True, 2.0)
                return
            if self.external_proc is proc:
                self.external_proc = None
                self.external_kind = None
            if rc == 0:
                self.finish_operation(f"{name} ukončeno", True, 2.0)
            else:
                if log_path:
                    detail = tail_text_file(log_path)
                elif kind == "apk":
                    detail = tail_text_file("/tmp/pitv-waydroid-launch.log")
                else:
                    detail = tail_text_file("/tmp/pitv-linux-launch.log")
                self.finish_operation(detail or f"{name}: chyba spuštění ({rc})", False, 6.0)
        threading.Thread(target=worker, daemon=True).start()

    def launch_linux(self, app):
        try:
            name = app.get("name", "Aplikace")
            env = build_gui_env()
            problem = gui_env_error(env)
            if problem:
                self.finish_operation(f"{name}: {problem}", False, 6.0)
                return

            log_path = Path("/tmp/pitv-linux-launch.log")
            log_path.write_text("", encoding="utf-8")
            self.set_operation(f"Spouštím {name}…")
            with log_path.open("a", encoding="utf-8") as log:
                self.external_proc = subprocess.Popen(
                    ["/bin/bash", "-c", app["command"]],
                    env=env,
                    cwd=str(Path.home()),
                    start_new_session=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            self.external_kind = "linux"
            self.show_toast(f"Spouštím {name}")
            self._watch_launch(self.external_proc, name, "linux", str(log_path))
        except Exception as e:
            self.finish_operation(f"Nelze spustit: {e}", False, 5.0)
            self.show_toast(f"Nelze spustit: {e}", 4)

    def launch_apk(self, app):
        if not waydroid_available():
            self.show_toast("Waydroid není nainstalovaný — viz Android / APK", 5)
            return
        package = app.get("package", "")
        apk_path = app.get("apk_path", "")
        if not package:
            self.show_toast("APK nemá rozpoznaný package name", 5)
            return
        try:
            name = app.get("name", "Android aplikace")
            env = build_gui_env()
            problem = gui_env_error(env)
            if problem:
                self.finish_operation(f"{name}: {problem}", False, 6.0)
                return

            self.set_operation(f"Spouštím {name}…")
            self.external_proc = subprocess.Popen(
                ["/usr/local/bin/pitv-waydroid-launch", package, apk_path],
                env=env,
                cwd=str(Path.home()),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.external_kind = "apk"
            self.show_toast(f"Připravuji {name}…")
            self._watch_launch(self.external_proc, name, "apk")
        except Exception as e:
            self.finish_operation(f"Waydroid: {e}", False, 5.0)
            self.show_toast(f"Waydroid: {e}", 5)

    def launch(self, app):
        if app.get("kind") == "apk":
            self.launch_apk(app)
        else:
            self.launch_linux(app)

    def enter_settings_item(self):
        pages = ["appearance", "screensaver", "network", "audio", "cec",
                 "apps", "server_store", "android", "updates", "system", "power", "about"]
        self.page = pages[self.settings_selected]
        self.sub_selected = 0
        if self.page == "network":
            self.network_selected = 0
            if nm_available():
                self.scan_wifi_async()
        elif self.page == "audio":
            self.audio_selected = 0
        elif self.page == "cec":
            self.cec_selected = 0
        elif self.page == "apps":
            self.apps_selected = 0
        elif self.page == "server_store":
            self.server_store_return_page = "settings"
            self.server_store_selected = 0
            self.refresh_server_store_async()
        elif self.page == "android":
            self.android_selected = 0
        elif self.page == "updates":
            self.updates_selected = 0
            self.check_updates_async()
        elif self.page == "system":
            self.system_selected = 0

    def handle_home(self, key):
        items = self.home_items()
        cols = 6
        if not items:
            return

        self.selected = min(self.selected, len(items)-1)

        if key == pygame.K_LEFT:
            if self.selected % cols == 0:
                self.focus_sidebar("home")
            else:
                self.selected = max(0, self.selected-1)
        elif key == pygame.K_RIGHT:
            self.selected = min(len(items)-1, self.selected+1)
        elif key == pygame.K_UP:
            self.selected = max(0, self.selected-cols)
        elif key == pygame.K_DOWN:
            self.selected = min(len(items)-1, self.selected+cols)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            item = items[self.selected]
            kind = item.get("kind")

            if kind == "app" and item.get("app"):
                self.launch(item["app"])
            elif kind in ("store", "store-root"):
                self.page = "store"
                self.store_return_page = "home"
                sid = item.get("id", "")
                self.store_selected = next(
                    (i for i, x in enumerate(self.store_catalog) if x.get("id") == sid), 0
                )
                self.refresh_store_async()
            elif kind == "server":
                self.page = "server_store"
                self.server_store_return_page = "home"
                sid = item.get("id", "")
                self.server_store_selected = next(
                    (i for i, x in enumerate(self.server_store_catalog) if x.get("id") == sid), 0
                )
                self.refresh_server_store_async()
            elif kind == "android":
                self.page = "android"
                self.android_selected = 0
            elif kind == "settings":
                self.page = "settings"
                self.settings_selected = 0

    def handle_key(self, key):
        # Modal input has priority.
        if self.keyboard_active:
            self.mark_activity()
            self.handle_keyboard_key(key)
            return
        if self.confirm_active:
            self.mark_activity()
            self.handle_confirm_key(key)
            return

        # First key after idle only wakes PiTV.
        if self.screensaver_stage != "off" or self.screensaver_preview:
            self.wake_from_screensaver()
            return

        self.mark_activity()

        # PiTV owns HDMI-CEC. While Kodi/Android is on top, relay navigation
        # through Wayland. HOME always closes the foreground app and returns.
        if self.external_kind:
            if key == pygame.K_HOME:
                self.stop_external()
                return
            if key in (PITV_KEY_VOLUMEUP, pygame.K_KP_PLUS):
                self.run_cec_action(cec_volume_up); return
            if key in (PITV_KEY_VOLUMEDOWN, pygame.K_KP_MINUS):
                self.run_cec_action(cec_volume_down); return
            if key == PITV_KEY_MUTE:
                self.run_cec_action(cec_mute); return
            self.relay_to_external(key)
            return

        if self.sidebar_focus:
            if key == pygame.K_UP:
                self.sidebar_selected = max(0, self.sidebar_selected-1)
            elif key == pygame.K_DOWN:
                self.sidebar_selected = min(len(self.SIDEBAR_PAGES)+4, self.sidebar_selected+1)
            elif key == pygame.K_RIGHT:
                self.sidebar_focus = False
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.activate_sidebar()
            elif key == pygame.K_ESCAPE:
                self.sidebar_focus = False
            return

        if key == pygame.K_HOME:
            self.sidebar_focus = False
            self.page = "home"; self.selected = 0; return

        if key == pygame.K_ESCAPE:
            if self.page == "home":
                return
            if self.page == "store":
                self.page = self.store_return_page
                return
            if self.page == "server_store":
                self.page = self.server_store_return_page
                return
            if self.page == "settings":
                self.page = "home"
                self.selected = max(0, len(self.home_items())-1)
                return
            # Every Settings child returns one level to Settings.
            self.page = "settings"
            return

        # Hardware volume buttons: HDMI TV/receiver via CEC.
        if key in (PITV_KEY_VOLUMEUP, pygame.K_KP_PLUS):
            self.run_cec_action(cec_volume_up); return
        if key in (PITV_KEY_VOLUMEDOWN, pygame.K_KP_MINUS):
            self.run_cec_action(cec_volume_down); return
        if key == PITV_KEY_MUTE:
            self.run_cec_action(cec_mute); return

        if self.page == "home":
            self.handle_home(key)

        elif self.page == "settings":
            if key == pygame.K_LEFT:
                self.focus_sidebar("settings")
            elif key == pygame.K_UP:
                self.settings_selected = max(0, self.settings_selected-1)
            elif key == pygame.K_DOWN:
                self.settings_selected = min(len(self.SETTINGS)-1, self.settings_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.enter_settings_item()

        elif self.page == "appearance":
            if key == pygame.K_UP:
                self.sub_selected = max(0, self.sub_selected-1)
            elif key == pygame.K_DOWN:
                self.sub_selected = min(2, self.sub_selected+1)
            elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                direction = 1 if key == pygame.K_RIGHT else -1
                if self.sub_selected == 0:
                    themes = ["apple_dark", "apple_light"]
                    current = {"dark":"apple_dark","light":"apple_light"}.get(
                        self.cfg.get("theme","apple_dark"), self.cfg.get("theme","apple_dark"))
                    try:
                        cur = themes.index(current)
                    except ValueError:
                        cur = 0
                    self.cfg["theme"] = themes[max(0, min(len(themes)-1, cur + direction))]
                elif self.sub_selected == 1:
                    vals = [.85, 1.0, 1.15]
                    cur = min(range(len(vals)), key=lambda i: abs(vals[i]-float(self.cfg.get("tile_scale",1))))
                    cur = max(0, min(len(vals)-1, cur + direction))
                    self.cfg["tile_scale"] = vals[cur]
                else:
                    self.cfg["show_clock"] = not self.cfg.get("show_clock", True)
                save_user_config(self.cfg)

        elif self.page == "screensaver":
            if key == pygame.K_UP:
                self.sub_selected = max(0, self.sub_selected-1)
            elif key == pygame.K_DOWN:
                self.sub_selected = min(5, self.sub_selected+1)
            elif key in (pygame.K_LEFT, pygame.K_RIGHT) and self.sub_selected <= 4:
                self.set_screensaver_value(self.sub_selected, 1 if key == pygame.K_RIGHT else -1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.sub_selected == 5:
                    self.screensaver_preview = True
                    self.screensaver_stage = "clock" if self.cfg.get("screensaver_mode","clock") == "clock" else "black"
                elif self.sub_selected == 0:
                    self.set_screensaver_value(0, 1)

        elif self.page == "network":
            if key == pygame.K_LEFT:
                self.focus_sidebar("network")
                return
            items = self.network_items()
            if not items:
                self.network_selected = 0
                return
            self.network_selected = min(self.network_selected, len(items)-1)
            if key == pygame.K_UP:
                self.network_selected = max(0, self.network_selected-1)
            elif key == pygame.K_DOWN:
                self.network_selected = min(len(items)-1, self.network_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                item = items[self.network_selected]
                kind = item["kind"]
                if kind == "wifi-toggle":
                    enabled = nm_wifi_enabled()
                    if enabled is None:
                        self.show_toast("NetworkManager není aktivní")
                    else:
                        self.async_action(lambda: run_privileged("wifi-radio", {"enabled": not enabled}, 20))
                elif kind == "scan":
                    self.scan_wifi_async()
                elif kind == "disconnect":
                    dev = wifi_device()
                    if dev:
                        self.async_action(lambda: run_privileged("wifi-disconnect", {"device": dev}, 20))
                elif kind == "wifi-net":
                    self.connect_wifi(item["net"])

        elif self.page == "audio":
            items = self.audio_items()
            if key == pygame.K_UP:
                self.audio_selected = max(0, self.audio_selected-1)
            elif key == pygame.K_DOWN:
                self.audio_selected = min(len(items)-1, self.audio_selected+1)
            elif key in (pygame.K_LEFT, pygame.K_RIGHT) and self.audio_selected == 0:
                vals = ["auto", "0", "1"]
                cur = self.cfg.get("hdmi_audio_port", "auto")
                self.cfg["hdmi_audio_port"] = self._cycle(cur, vals, 1 if key == pygame.K_RIGHT else -1)
                save_user_config(self.cfg)
            elif key == pygame.K_LEFT:
                self.focus_sidebar("audio")
                return
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                action = items[self.audio_selected]["action"]
                if action == "port":
                    vals = ["auto", "0", "1"]
                    self.cfg["hdmi_audio_port"] = self._cycle(self.cfg.get("hdmi_audio_port","auto"), vals, 1)
                    save_user_config(self.cfg)
                elif action == "volup":
                    self.run_cec_action(cec_volume_up)
                elif action == "voldown":
                    self.run_cec_action(cec_volume_down)
                elif action == "mute":
                    self.run_cec_action(cec_mute)
                elif action == "test":
                    pref = self.cfg.get("hdmi_audio_port", "auto")
                    self.async_action(lambda: test_hdmi_audio(pref))

        elif self.page == "cec":
            if key == pygame.K_LEFT:
                self.focus_sidebar("cec")
                return
            if key == pygame.K_UP:
                self.cec_selected = max(0, self.cec_selected-1)
            elif key == pygame.K_DOWN:
                self.cec_selected = min(len(self.CEC_ACTIONS)-1, self.cec_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.run_cec_action(self.CEC_ACTIONS[self.cec_selected][2])

        elif self.page == "apps":
            if key == pygame.K_LEFT:
                self.focus_sidebar("apps")
                return
            items = self.app_items()
            if key == pygame.K_UP:
                self.apps_selected = max(0, self.apps_selected-1)
            elif key == pygame.K_DOWN:
                self.apps_selected = min(len(items)-1, self.apps_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                item = items[self.apps_selected]
                if item.get("store"):
                    self.page = "store"
                    self.store_return_page = "apps"
                    self.store_selected = 0
                    self.refresh_store_async()
                elif item.get("refresh"):
                    self.apps = load_apps()
                    self.apps_selected = min(self.apps_selected, max(0, len(self.app_items())-1))
                    self.show_toast("Seznam aplikací obnoven")
                else:
                    hidden = set(self.cfg.get("hidden_apps", []))
                    name = item["name"]
                    if name in hidden: hidden.remove(name)
                    else: hidden.add(name)
                    self.cfg["hidden_apps"] = sorted(hidden)
                    save_user_config(self.cfg)

        elif self.page == "store":
            items = self.store_catalog
            cols = 3
            if key == pygame.K_LEFT:
                if self.store_selected % cols == 0:
                    self.focus_sidebar("store")
                else:
                    self.store_selected = max(0, self.store_selected-1)
            elif key == pygame.K_RIGHT:
                self.store_selected = min(max(0, len(items)-1), self.store_selected+1)
            elif key == pygame.K_UP:
                self.store_selected = max(0, self.store_selected-cols)
            elif key == pygame.K_DOWN:
                self.store_selected = min(max(0, len(items)-1), self.store_selected+cols)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and items:
                self.install_store_item(items[self.store_selected])

        elif self.page == "server_store":
            items = self.server_store_catalog
            cols = 2
            if key == pygame.K_LEFT:
                if self.server_store_selected % cols == 0:
                    self.focus_sidebar("server_store")
                else:
                    self.server_store_selected = max(0, self.server_store_selected-1)
            elif key == pygame.K_RIGHT:
                self.server_store_selected = min(max(0, len(items)-1),
                                                 self.server_store_selected+1)
            elif key == pygame.K_UP:
                self.server_store_selected = max(0, self.server_store_selected-cols)
            elif key == pygame.K_DOWN:
                self.server_store_selected = min(max(0, len(items)-1),
                                                 self.server_store_selected+cols)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and items:
                self.install_server_store_item(items[self.server_store_selected])

        elif self.page == "android":
            rows = self.android_items()
            if not rows:
                self.android_selected = 0
                return
            self.android_selected = min(self.android_selected, len(rows)-1)
            if key == pygame.K_LEFT:
                self.focus_sidebar("android")
            elif key == pygame.K_UP:
                self.android_selected = max(0, self.android_selected-1)
            elif key == pygame.K_DOWN:
                self.android_selected = min(len(rows)-1, self.android_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.android_selected == 0 and not waydroid_available():
                    self.open_confirm(
                        "Waydroid + Google Play",
                        "Nainstalovat Android runtime pro PiTV Store?",
                        self.install_waydroid_async,
                    )
                elif self.android_selected == 4:
                    self.apps = load_apps()
                    self.android_selected = min(self.android_selected, len(self.android_items())-1)
                    self.show_toast("APK seznam obnoven")
                elif self.android_selected == 5 and waydroid_available():
                    try:
                        env = build_gui_env()
                        problem = gui_env_error(env)
                        if problem:
                            self.show_toast(f"Android UI: {problem}", 6)
                            return
                        self.external_proc = subprocess.Popen(
                            ["/usr/local/bin/pitv-waydroid-launch", "--full-ui"],
                            env=env,
                            cwd=str(Path.home()),
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self.external_kind = "apk"
                        self.show_toast("Spouštím Android UI")
                        self._watch_launch(self.external_proc, "Android UI", "apk")
                    except Exception as e:
                        self.show_toast(str(e), 5)
                elif self.android_selected >= 6:
                    apks = [a for a in self.apps if a.get("kind") == "apk"]
                    apk_index = self.android_selected - 6
                    if 0 <= apk_index < len(apks):
                        self.launch_apk(apks[apk_index])

        elif self.page == "updates":
            rows = self.update_items()
            cols = 2
            if key == pygame.K_LEFT:
                if self.updates_selected % cols == 0:
                    self.focus_sidebar("updates")
                else:
                    self.updates_selected = max(0, self.updates_selected-1)
            elif key == pygame.K_RIGHT:
                self.updates_selected = min(len(rows)-1, self.updates_selected+1)
            elif key == pygame.K_UP:
                self.updates_selected = max(0, self.updates_selected-cols)
            elif key == pygame.K_DOWN:
                self.updates_selected = min(len(rows)-1, self.updates_selected+cols)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.updates_selected == 4:
                    self.check_updates_async()
                elif self.updates_selected == 5:
                    self.open_confirm(
                        "Aktualizovat PiTV",
                        "Stáhnout a nainstalovat nejnovější PiTV z GitHubu?",
                        self.update_pitv_async,
                    )
                elif self.updates_selected == 6:
                    self.update_store_catalog_async()
                elif self.updates_selected == 7:
                    self.open_confirm(
                        "Store aplikace",
                        "Aktualizovat Linux aplikace nainstalované z PiTV Store?",
                        self.update_linux_store_apps_async,
                    )
                elif self.updates_selected == 8:
                    self.open_confirm(
                        "Aktualizovat Ubuntu",
                        "Nainstalovat dostupné systémové aktualizace?",
                        self.update_ubuntu_async,
                    )
                elif self.updates_selected == 9:
                    self.show_toast("Restartuji PiTV UI…")
                    pygame.quit()
                    os.execv(sys.executable, [sys.executable, __file__])

        elif self.page == "system":
            if key == pygame.K_LEFT:
                self.focus_sidebar("system")
                return
            rows = self.system_items()
            if key == pygame.K_UP:
                self.system_selected = max(0, self.system_selected-1)
            elif key == pygame.K_DOWN:
                self.system_selected = min(len(rows)-1, self.system_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.system_selected == 7:
                    if not self.update_checking:
                        self.update_checking = True
                        self.show_toast("Kontroluji aktualizace…")
                        def worker():
                            run_privileged("apt-update", {}, 240)
                            self.update_count = count_updates()
                            self.update_checking = False
                            self.show_toast(f"Aktualizace: {self.update_count if self.update_count is not None else '—'}")
                        threading.Thread(target=worker, daemon=True).start()
                elif self.system_selected == 8:
                    def upgrade():
                        self.show_toast("Instaluji aktualizace…")
                        ok, msg = run_privileged("apt-upgrade", {}, 1200)
                        self.show_toast(msg, 5)
                        self.update_count = count_updates()
                    self.open_confirm("Aktualizace systému",
                                      "Nainstalovat dostupné balíčky?", 
                                      lambda: threading.Thread(target=upgrade, daemon=True).start())
                elif self.system_selected == 9:
                    self.show_toast("Restartuji PiTV UI…")
                    pygame.quit()
                    os.execv(sys.executable, [sys.executable, __file__])

        elif self.page == "power":
            if key == pygame.K_LEFT:
                self.focus_sidebar("power")
                return
            if key == pygame.K_UP: self.sub_selected = max(0, self.sub_selected-1)
            elif key == pygame.K_DOWN: self.sub_selected = min(1, self.sub_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.sub_selected == 0:
                    self.open_confirm("Restart Raspberry Pi",
                                      "Opravdu restartovat celý server?",
                                      lambda: subprocess.Popen(["sudo","-n","/usr/bin/systemctl","reboot"]))
                else:
                    self.open_confirm("Vypnout Raspberry Pi",
                                      "Opravdu vypnout celý server?",
                                      lambda: subprocess.Popen(["sudo","-n","/usr/bin/systemctl","poweroff"]))

        elif self.page == "about":
            if key == pygame.K_LEFT:
                self.focus_sidebar("about")
                return

    def run(self):
        while self.running:
            while True:
                try:
                    key = self.cec_queue.get_nowait()
                    self.handle_key(key)
                except queue.Empty:
                    break
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    # A USB keyboard is the guaranteed local fallback for TV
                    # remotes. Backspace behaves as Back/Escape, matching the
                    # on-screen keyboard legend and common media-center UX.
                    key = normalize_input_key(event.key)
                    if self.external_kind == "linux" and self._consume_relay_echo(key):
                        continue
                    self.handle_key(key)

            if self.external_proc is not None and self.external_proc.poll() is not None:
                finished_kind = self.external_kind
                self.external_proc = None
                self.external_kind = None
                if finished_kind in ("apk", "linux"):
                    self.apps = load_apps()
                    self.refresh_store_async()

            self.update_idle_state()
            if self.external_kind:
                # The external client owns the visible surface. Keep PiTV's
                # input/session manager responsive without burning GPU/CPU on
                # a hidden 30 FPS render loop.
                self.clock.tick(10)
                continue
            if self.screensaver_stage != "off":
                self.draw_screensaver()
            else:
                self.draw()
            self.clock.tick(30)
        if self.cec:
            self.cec.stop()
        pygame.quit()


if __name__ == "__main__":
    PiTV().run()
