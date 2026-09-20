#!/usr/bin/env python3
import json
import os
import queue
import pwd
import shutil
import socket
import subprocess
import sys
import threading
import time
import re
import signal
from pathlib import Path

import pygame
from apk_backend import (discover_apks, ensure_apk_installed, inspect_apk,
                         waydroid_available, waydroid_packages, waydroid_status,
                         tailscale_info)
from store_backend import (clear_android_receipts, download_direct_apk,
                           download_github_apk, load_store_catalog,
                           mark_android_installed, store_state)
from update_backend import is_newer, remote_pitv_version

APP_NAME = "PiTV"
VERSION = "1.5.0"

SYSTEM_CONFIG = Path("/etc/pitv/config.json")
USER_CONFIG = Path.home() / ".config/pitv/config.json"
MIGRATION_DIR = USER_CONFIG.parent / "migrations"
LEGACY_ANDROID_PACKAGES = ("com.stremio.one", "com.plexapp.android")
SYSTEM_APPS = Path("/etc/pitv/apps.d")
USER_APPS = Path.home() / ".config/pitv/apps.d"
SYSTEM_SERVER_CATALOG = Path("/etc/pitv/store/server_catalog.json")
BUNDLED_SERVER_CATALOG = Path(__file__).resolve().parent.parent / "store" / "server_catalog.json"
LAUNCH_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "pitv-launch.json"
SYSTEM_INPUTD = Path("/usr/local/libexec/pitv-inputd")
SYSTEM_INPUT_READY = Path("/run/pitv/inputd.ready")
GLOBAL_ACTION_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "pitv-global-action"

DEFAULT_CONFIG = {
    "theme": "apple_dark",
    "accent": "blue",
    "tile_scale": 1.0,
    "show_tile_labels": True,
    "home_layout": "default",
    "content_density": "normal",
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
    scales = [0.85, 1.0, 1.15, 1.30]
    cfg["tile_scale"] = min(scales, key=lambda value: abs(value - scale))

    if cfg.get("accent") not in ("blue", "purple", "green"):
        cfg["accent"] = "blue"
    if cfg.get("home_layout") not in ("default", "compact"):
        cfg["home_layout"] = "default"
    if cfg.get("content_density") not in ("comfortable", "normal", "compact"):
        cfg["content_density"] = "normal"
    if not isinstance(cfg.get("show_tile_labels"), bool):
        cfg["show_tile_labels"] = True

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
    """Return the canonical PiTV TV-session environment for GUI children."""
    env = os.environ.copy()
    runtime = f"/run/user/{os.getuid()}"
    runtime_path = Path(runtime)
    env["HOME"] = "/home/pitv"
    env["USER"] = "pitv"
    env["LOGNAME"] = "pitv"
    env["XDG_RUNTIME_DIR"] = runtime
    env["XDG_SESSION_TYPE"] = "wayland"
    env["XDG_CURRENT_DESKTOP"] = "labwc"
    env["PULSE_RUNTIME_PATH"] = str(runtime_path / "pulse")

    # One source of truth for the visible TV compositor. Nested Cage/Android
    # sockets live in the same runtime directory, so choosing the first
    # wayland-* socket can launch a native app into Android by accident.
    marker = runtime_path / "pitv-wayland-display"
    try:
        display = marker.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        display = ""
    if (re.fullmatch(r"wayland-[0-9]+", display or "") and
            (runtime_path / display).is_socket()):
        env["WAYLAND_DISPLAY"] = display
    else:
        env.pop("WAYLAND_DISPLAY", None)

    bus = runtime_path / "bus"
    if bus.is_socket():
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    else:
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
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


def set_default_hdmi_audio(preference="auto"):
    """Select a connected HDMI PipeWire/Pulse sink as the session default."""
    try:
        try:
            idx = int(preference) if str(preference) in ("0", "1") else 0
        except Exception:
            idx = 0

        # Prefer pactl because pipewire-pulse exposes stable sink names that
        # Kodi also shows. Older PiTV installs may not have pulseaudio-utils,
        # so keep a native WirePlumber/wpctl fallback.
        if shutil.which("pactl") is not None:
            p = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False,
            )
            if p.returncode == 0:
                sinks = []
                for line in (p.stdout or "").splitlines():
                    parts = line.split("\t")
                    if len(parts) < 2:
                        parts = line.split()
                    if len(parts) < 2:
                        continue
                    if "hdmi" in line.lower():
                        sinks.append(parts[1])
                if sinks:
                    idx = max(0, min(idx, len(sinks)-1))
                    sink = sinks[idx]
                    q = subprocess.run(
                        ["pactl", "set-default-sink", sink],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if q.returncode == 0:
                        return True, sink

        if shutil.which("wpctl") is not None:
            p = subprocess.run(
                ["wpctl", "status", "-n"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False,
            )
            if p.returncode == 0:
                sinks = []
                in_sinks = False
                for line in (p.stdout or "").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Sinks:") or "─ Sinks:" in line:
                        in_sinks = True
                        continue
                    if in_sinks and ("Sink endpoints:" in line or "Sources:" in line):
                        break
                    if not in_sinks or "hdmi" not in line.lower():
                        continue
                    m = re.search(r"[*\s│├└─]*([0-9]+)\.\s+(.+?)(?:\s+\[|$)", line)
                    if m:
                        sinks.append((m.group(1), m.group(2).strip()))
                if sinks:
                    idx = max(0, min(idx, len(sinks)-1))
                    sink_id, sink_name = sinks[idx]
                    q = subprocess.run(
                        ["wpctl", "set-default", sink_id],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if q.returncode == 0:
                        return True, sink_name

        return False, "HDMI audio sink nebyl v PiTV session nalezen"
    except Exception as e:
        return False, f"HDMI audio: {e}"


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

def cec_available():
    # PiTV 1.5 owns remote input in pitv-inputd. The GUI only checks whether
    # the kernel CEC device/output tool exists for power/source/volume actions.
    return shutil.which("cec-ctl") is not None and any(Path("/dev").glob("cec*"))


def system_input_managed():
    """PiTV 1.5+ owns TV remote input below the visual shell."""
    return SYSTEM_INPUTD.exists()


def system_input_ready():
    return system_input_managed() and SYSTEM_INPUT_READY.exists()


def system_input_cec_device():
    if not system_input_managed():
        return ""
    try:
        device = Path("/run/pitv/cec-device").read_text(
            encoding="utf-8", errors="replace"
        ).strip()
    except Exception:
        return ""
    if re.fullmatch(r"/dev/cec[0-9]+", device) and Path(device).exists():
        return device
    return ""


def cec_send(commands):
    """Send CEC output through the same kernel CEC stack used for input."""
    if not cec_available():
        return False, "cec-ctl nebo CEC adaptér není dostupný"
    if isinstance(commands, str):
        commands = [commands]

    device = None

    # PiTV 1.5 inputd selects the physically connected CEC adapter and
    # publishes it for the rest of the appliance. Power/volume commands must
    # use that same adapter rather than blindly choosing /dev/cec0.
    try:
        selected = Path("/run/pitv/cec-device").read_text(
            encoding="utf-8", errors="replace"
        ).strip()
        if re.fullmatch(r"/dev/cec[0-9]+", selected) and Path(selected).exists():
            device = selected
    except Exception:
        pass

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
                ["sudo", "-n", "/usr/local/libexec/pitv-cec-control", device, mode],
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


class PiTV:
    def __init__(self):
        # Compatibility with older/manual launch paths: if Python is started
        # outside the PiTV supervisor, clean stale TV apps before creating the
        # new fullscreen launcher. CI/dummy rendering must never touch host
        # runtimes.
        if (os.environ.get("PITV_SUPERVISED") != "1" and
                os.environ.get("SDL_VIDEODRIVER", "").lower() != "dummy"):
            run_privileged("tv-runtime-reset", {}, 90)

        # PiTV is a silent launcher. Do not initialize pygame.mixer/audio:
        # media applications own the PipeWire/HDMI audio path.
        pygame.display.init()
        pygame.font.init()
        # Give labwc the PiTV title before the first map so its appliance
        # window rule can maximize the launcher immediately.
        pygame.display.set_caption(f"{APP_NAME} {VERSION}")
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption(f"{APP_NAME} {VERSION}")
        pygame.mouse.set_visible(False)
        self.w, self.h = self.screen.get_size()
        self._last_desktop_size = self._desktop_size()
        self._last_display_probe_at = time.monotonic()
        self._last_fullscreen_repair_at = 0.0
        self._main_thread_id = threading.get_ident()
        self._fullscreen_repair_requested = False
        self.cfg = load_config()
        # PiTV is HDMI-only. Make the connected HDMI PipeWire/Pulse sink the
        # default before any TV app (Kodi, Stremio, Waydroid) is launched.
        set_default_hdmi_audio(self.cfg.get("hdmi_audio_port", "auto"))
        self.apps = load_apps()
        self.page = "home"
        self.selected = 0
        self.settings_selected = 0
        # True only while a page was opened from Settings. Shared pages such
        # as Updates/Android/Server Store keep their full-screen top-level UI
        # when opened directly from the sidebar.
        self.settings_context = False
        self.sidebar_focus = False
        self.sidebar_selected = 0
        self.store_return_page = "apps"
        self.store_return_settings_context = False
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
        self.app_action_busy = False
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
        self.external_app = None
        self.external_task_key = None
        self.external_started_at = 0.0
        # Android starts invisibly on its own workspace. Do not mark it as the
        # foreground app until the requested package confirms it is running.
        self.android_pending_proc = None
        self.android_pending_package = ""
        self.android_pending_app = None
        self.background_tasks = {}
        self._relay_echo = {}
        # Kept only for non-CEC keyboard/development compatibility. Installed
        # PiTV 1.5 routes TV navigation directly through the system virtual
        # remote, so foreground applications receive normal Linux key events.
        self.android_key_queue = queue.Queue(maxsize=32)
        if not system_input_managed():
            threading.Thread(
                target=self._android_key_worker, daemon=True
            ).start()
        self._back_hold_triggered = False
        self._keyboard_back_down_at = 0.0
        self._cec_refreshing = False
        self._legacy_migration_started = False

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

        self.choice_active = False
        self.choice_title = ""
        self.choice_options = []
        self.choice_selected = 0
        self.choice_callback = None

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
        if (self.cfg.get("cec_enabled", True) and
                self.cfg.get("cec_wake_on_start", False)):
            threading.Thread(target=cec_tv_on, daemon=True).start()
        # One physical press = one navigation step. TV remotes already provide
        # their own hold/repeat events; SDL repeat caused multi-tile jumps.
        pygame.key.set_repeat()
        self.clock = pygame.time.Clock()

        # Legacy cleanup is deliberately asynchronous, but it may only run
        # against the already-systemd-owned warm Android runtime. It must not
        # boot/stop Waydroid in parallel with Home or the first app launch.
        self.migrate_legacy_android_async()

    def migrate_legacy_android_async(self):
        """Remove Android apps that older PiTV alpha catalogs installed.

        These package IDs are known from PiTV's own repository history. The
        migration is intentionally narrow: no unknown/user-installed Android
        package is touched.
        """
        marker = MIGRATION_DIR / "legacy-android-media-v2.done"
        if self._legacy_migration_started or marker.exists() or not waydroid_available():
            return
        self._legacy_migration_started = True

        def worker():
            try:
                # Wait passively for Android warm-up. This prevents the old
                # migration from racing SmartTube by creating its own container
                # lifecycle while systemd is still preparing Waydroid.
                deadline = time.monotonic() + 180.0
                idle_since = 0.0
                while time.monotonic() < deadline:
                    if marker.exists():
                        return
                    if not self._android_runtime_ready():
                        idle_since = 0.0
                        time.sleep(0.25)
                        continue

                    # Foreground/pending Android work always wins over cleanup.
                    # Require two quiet seconds before removing PiTV's known
                    # obsolete Stremio/Plex packages.
                    android_busy = (
                        (self.android_pending_proc is not None and
                         self.android_pending_proc.poll() is None) or
                        self.external_kind == "apk"
                    )
                    if android_busy:
                        idle_since = 0.0
                        time.sleep(0.5)
                        continue

                    if idle_since <= 0:
                        idle_since = time.monotonic()
                    if time.monotonic() - idle_since >= 2.0:
                        break
                    time.sleep(0.25)
                else:
                    return

                ok, msg = run_privileged("waydroid-clean-legacy", {}, 300)
                if not ok:
                    return

                # Old Store receipts can otherwise make obsolete Android media
                # entries look installed after the package itself is gone.
                for package in LEGACY_ANDROID_PACKAGES:
                    clear_android_receipts(package, "")
                    # Remove the two known stale desktop/icon artifacts after
                    # package cleanup completed inside the warm runtime.
                    for stale in (
                        Path.home() / ".local/share/applications" /
                            f"waydroid.{package}.desktop",
                        Path.home() / ".local/share/waydroid/data/icons" /
                            f"{package}.png",
                    ):
                        try:
                            stale.unlink(missing_ok=True)
                        except Exception:
                            pass

                # Older alpha builds could also have persisted a launcher
                # JSON in ~/.config/pitv/apps.d. Remove only launchers that
                # explicitly target one of the same known obsolete packages.
                if USER_APPS.exists():
                    for launcher in USER_APPS.glob("*.json"):
                        data = safe_json(launcher, {})
                        package = str(data.get("package", "") or "").strip()
                        command = str(data.get("command", "") or "")
                        targets_legacy = package in LEGACY_ANDROID_PACKAGES
                        if not targets_legacy:
                            targets_legacy = any(
                                re.search(r"(?<![A-Za-z0-9_.])" + re.escape(pkg) +
                                          r"(?![A-Za-z0-9_.])", command)
                                for pkg in LEGACY_ANDROID_PACKAGES
                            )
                        if targets_legacy:
                            try:
                                launcher.unlink(missing_ok=True)
                            except Exception:
                                pass

                # An older/manual PiTV build may also have left a managed APK
                # copy. discover_apks() would surface it again even after the
                # Android package itself is removed. Delete only APKs whose
                # inspected package ID is one of PiTV's known obsolete IDs.
                managed_roots = (
                    Path("/var/lib/pitv/apks").resolve(),
                    (Path.home() / "PiTV" / "APKs").resolve(),
                )
                for app in list(self.apps):
                    if (app.get("kind") != "apk" or
                            app.get("package") not in LEGACY_ANDROID_PACKAGES):
                        continue
                    apk_path = str(app.get("apk_path", "") or "").strip()
                    if not apk_path:
                        continue
                    try:
                        target = Path(apk_path).resolve()
                        if (target.suffix.lower() == ".apk" and
                                any(root in target.parents for root in managed_roots)):
                            target.unlink(missing_ok=True)
                    except Exception:
                        pass

                MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    "PiTV legacy Android media migration completed\n",
                    encoding="utf-8",
                )
                self.apps = load_apps()

                removed = ""
                if msg.startswith("removed:"):
                    removed = msg.split(":", 1)[1].strip()
                if removed:
                    names = []
                    if "com.stremio.one" in removed:
                        names.append("staré Android Stremio")
                    if "com.plexapp.android" in removed:
                        names.append("starý Android Plex")
                    self.show_toast("Odstraněno: " + ", ".join(names), 5)
            finally:
                self._legacy_migration_started = False

        threading.Thread(target=worker, daemon=True).start()

    def legacy_android_migration_ready(self):
        """Compatibility shim: maintenance must never block an app launch."""
        if waydroid_available():
            self.migrate_legacy_android_async()
        return True

    @property
    def t(self):
        theme = self.cfg.get("theme", "apple_dark")
        theme = {"dark": "apple_dark", "light": "apple_light"}.get(theme, theme)
        accent = self.cfg.get("accent", "blue")
        key = (theme, accent)
        if getattr(self, "_theme_palette_key", None) != key:
            palette = dict(THEMES.get(theme, THEMES["apple_dark"]))
            light = theme == "apple_light"
            if accent == "purple":
                palette.update({
                    "accent": (168, 85, 247) if not light else (126, 34, 206),
                    "accent2": (126, 34, 206),
                    "action": (109, 40, 217),
                    "action2": (88, 28, 135),
                    "accent_soft": (40, 24, 68) if not light else (243, 232, 255),
                })
            elif accent == "green":
                palette.update({
                    "accent": (74, 222, 128) if not light else (22, 163, 74),
                    "accent2": (34, 197, 94),
                    "action": (22, 163, 74),
                    "action2": (21, 128, 61),
                    "accent_soft": (15, 55, 39) if not light else (220, 252, 231),
                })
            self._theme_palette_key = key
            self._theme_palette_cache = palette
        return self._theme_palette_cache

    @property
    def theme_name(self):
        theme = self.cfg.get("theme", "apple_dark")
        theme = {"dark": "apple_dark", "light": "apple_light"}.get(theme, theme)
        return "PiTV Apple Light" if theme == "apple_light" else "PiTV Apple Dark"

    def main_left(self):
        return int(self.w * .198)

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
        """Deep layered backdrop behind the translucent PiTV glass surfaces."""
        self.screen.fill(self.t["page"])
        is_light = self.theme_name.endswith("Light")

        # Main vertical depth.
        upper = pygame.Rect(0, 0, self.w, self.h)
        self.gradient_rect(
            upper,
            (241, 246, 252) if is_light else (5, 15, 33),
            (226, 235, 246) if is_light else (3, 9, 22),
        )

        # Soft blue atmospheric pools make translucent panels read as glass.
        glow = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        pools = [
            (int(self.w*.68), int(self.h*.08), int(self.w*.46), (29, 120, 255, 30 if not is_light else 16)),
            (int(self.w*.28), int(self.h*.78), int(self.w*.32), (35, 87, 170, 24 if not is_light else 10)),
        ]
        for cx, cy, radius, color in pools:
            for step in range(7, 0, -1):
                alpha = max(1, int(color[3] * step / 7))
                rr = max(1, int(radius * step / 7))
                pygame.draw.circle(glow, (*color[:3], alpha), (cx, cy), rr)
        self.screen.blit(glow, (0, 0))

        # Very subtle top sheen.
        sheen = pygame.Surface((self.w, int(self.h*.32)), pygame.SRCALPHA)
        for i in range(20):
            a = int((20-i) * (1.6 if not is_light else .8))
            pygame.draw.rect(
                sheen, (90, 170, 255, max(0, a)),
                pygame.Rect(0, int(i*sheen.get_height()/20), self.w,
                            max(1, int(sheen.get_height()/20)+1)),
            )
        self.screen.blit(sheen, (0, 0))

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

    def glass_panel(self, rect, selected=False, alpha=205, radius=22):
        """Glassmorphism panel: translucent fill, sheen, shadow and soft focus glow."""
        is_light = self.theme_name.endswith("Light")

        shadow = pygame.Surface((rect.w+18, rect.h+18), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow,
            (0, 0, 0, 42 if not is_light else 18),
            pygame.Rect(9, 10, rect.w, rect.h),
            border_radius=radius+3,
        )
        self.screen.blit(shadow, (rect.x-9, rect.y-9))

        if selected:
            halo = pygame.Surface((rect.w+22, rect.h+22), pygame.SRCALPHA)
            for n, a in ((0, 62), (4, 34), (8, 16)):
                pygame.draw.rect(
                    halo, (*self.t["accent"], a),
                    pygame.Rect(11-n, 11-n, rect.w+2*n, rect.h+2*n),
                    max(1, 3 if n == 0 else 2),
                    border_radius=radius+n,
                )
            self.screen.blit(halo, (rect.x-11, rect.y-11))

        surface = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        base_top = self.t["panel2"] if not selected else self.t["accent_soft"]
        base_bottom = self.t["panel"]
        strips = max(8, min(28, rect.h//8))
        for i in range(strips):
            y0 = round(i*rect.h/strips)
            y1 = round((i+1)*rect.h/strips)
            color = self.mix(base_top, base_bottom, i/max(1,strips-1))
            a = min(245, alpha + (18 if selected else 0))
            pygame.draw.rect(surface, (*color, a),
                             pygame.Rect(0, y0, rect.w, max(1,y1-y0)))
        mask = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255,255,255,255), mask.get_rect(), border_radius=radius)
        surface.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MIN)
        self.screen.blit(surface, rect.topleft)

        # Thin inner highlight + cool outer edge sell the glass illusion.
        hi = (255,255,255,34 if not is_light else 95)
        edge = self.t["accent"] if selected else (
            (74, 104, 145) if not is_light else self.t["border"]
        )
        pygame.draw.line(
            self.screen, hi,
            (rect.x+radius, rect.y+1), (rect.right-radius, rect.y+1), 1,
        )
        pygame.draw.rect(
            self.screen, edge, rect, 2 if selected else 1, border_radius=radius
        )

    def draw_sidebar(self, active=""):
        w = int(self.w*.174)
        rect = pygame.Rect(int(self.w*.014), int(self.h*.030), w, int(self.h*.940))
        self.glass_panel(rect, False, 172, 28)

        x = rect.x + int(w*.095)
        top = rect.y + int(self.h*.032)
        mark = pygame.Rect(x, top, int(self.h*.055), int(self.h*.055))
        self.gradient_rect(mark, self.t["accent"], self.t["action"], radius=15)
        play = self.font(mark.h*.34, True).render("▶", True, (255,255,255))
        self.screen.blit(play, play.get_rect(center=mark.center))
        self.text("PiTV", mark.right+13, top-4, self.h*.040, self.t["text"], True)
        self.text("Your TV. Your Way.", x, top+int(self.h*.064), self.h*.014, self.t["muted"])

        items = [
            ("home", "⌂", "Home"),
            ("store", "▣", "Store"),
            ("server_store", "◉", "Server Store"),
            ("android", "◆", "Android / APK"),
            ("updates", "↻", "Updates"),
            ("settings", "⚙", "Settings"),
        ]
        y0 = top + int(self.h*.122)
        row_h = int(self.h*.054)
        for i, (key, icon, label) in enumerate(items):
            rr = pygame.Rect(rect.x+int(w*.050), y0+i*row_h, int(w*.900), int(row_h*.82))
            selected = (self.sidebar_focus and i == self.sidebar_selected) or (
                not self.sidebar_focus and key == active
            )
            if selected:
                self.glass_panel(rr, True, 188, 14)
            self.text(icon, rr.x+14, rr.y+int(rr.h*.18), rr.h*.36,
                      self.t["accent"] if selected else self.t["muted"], True)
            self.text(label, rr.x+int(rr.h*.78), rr.y+int(rr.h*.23), rr.h*.26,
                      self.t["text"] if selected else self.t["muted"], selected)

        divider_y = y0 + len(items)*row_h + int(self.h*.010)
        pygame.draw.line(self.screen, (*self.t["border"],),
                         (rect.x+int(w*.08), divider_y),
                         (rect.right-int(w*.08), divider_y), 1)

        self.text("MEDIA & TOOLS", x, divider_y+int(self.h*.019),
                  self.h*.012, self.t["muted"], True)
        quick = [
            ("▦", "Kodi"),
            ("▶", "SmartTube"),
            ("◆", "Stremio"),
            ("❯", "Plex"),
            ("•••", "More Apps"),
        ]
        qy = divider_y + int(self.h*.051)
        qh = int(self.h*.047)
        for j, (icon, label) in enumerate(quick):
            rr = pygame.Rect(rect.x+int(w*.050), qy, int(w*.900), int(qh*.82))
            selected = self.sidebar_focus and self.sidebar_selected == 6+j
            if selected:
                self.glass_panel(rr, True, 184, 12)
            self.text(icon, rr.x+14, rr.y+int(rr.h*.14), rr.h*.35,
                      self.t["accent"] if selected else self.t["muted"], True)
            self.text(label, rr.x+int(rr.h*.80), rr.y+int(rr.h*.18), rr.h*.26,
                      self.t["text"] if selected else self.t["muted"], selected)
            qy += qh

        self.text("PiTV  "+VERSION, x, rect.bottom-int(self.h*.040), self.h*.012, self.t["muted"])

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
        self.settings_context = False

        if idx < len(self.SIDEBAR_PAGES):
            target = self.SIDEBAR_PAGES[idx]
            if target == "home":
                self.page = "home"
                self.selected = 0
            elif target == "store":
                self.page = "store"
                self.store_return_page = "home"
                self.store_return_settings_context = False
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
            self.store_return_settings_context = False
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
        self.store_return_settings_context = False
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

    def _fit_ui_text(self, text, font, max_width):
        """Collapse terminal-style output and ellipsize it to a TV-safe width."""
        line = " ".join(str(text or "").split())
        if not line:
            return ""
        if font.size(line)[0] <= max_width:
            return line
        suffix = "…"
        lo, hi = 0, len(line)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = line[:mid].rstrip() + suffix
            if font.size(candidate)[0] <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return line[:lo].rstrip() + suffix

    def set_operation(self, text, progress=None, error=False):
        # Long-running work is part of the visible TV experience. Keep the
        # launcher awake so the global status banner can never disappear
        # behind the PiTV screensaver/CEC standby.
        self.mark_activity()
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

        f = self.font(self.h*.018, True)
        suffix = "" if self.operation_progress is None else f"  {self.operation_progress}%"
        label = self._fit_ui_text(
            self.operation_text + suffix, f, int(self.w*.72)
        )
        surf = f.render(
            label, True,
            self.t["bad"] if self.operation_error else self.t["text"],
        )

        # Consistent Google/Apple-TV-style transient status surface: centered
        # at the top, visible from every PiTV page, never tied to Settings.
        w = min(int(self.w*.78), max(int(self.w*.34), surf.get_width()+92))
        h = int(self.h*.066)
        r = pygame.Rect(0, int(self.h*.022), w, h)
        r.centerx = self.w//2

        shadow = pygame.Surface((r.w+12, r.h+12), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow, (0, 0, 0, 105),
            pygame.Rect(6, 6, r.w, r.h),
            border_radius=h//2,
        )
        self.screen.blit(shadow, (r.x-6, r.y-6))

        pygame.draw.rect(self.screen, self.t["panel2"], r, border_radius=h//2)
        pygame.draw.rect(
            self.screen,
            self.t["bad"] if self.operation_error else self.t["accent"],
            r, 2, border_radius=h//2,
        )

        icon_x = r.x+27
        if self.operation_progress is None or self.operation_progress < 100:
            angle = (time.monotonic()*300) % 360
            pygame.draw.arc(
                self.screen, self.t["accent"],
                pygame.Rect(icon_x-10, r.centery-10, 20, 20),
                angle*3.14159/180, (angle+250)*3.14159/180, 3,
            )
        else:
            self.text(
                "✓", icon_x-8, r.y+int(r.h*.20),
                r.h*.35, self.t["good"], True,
            )

        self.screen.blit(
            surf,
            (r.x+52, r.y+(r.h-surf.get_height())//2-2),
        )

        if self.operation_progress is not None:
            track = pygame.Rect(r.x+20, r.bottom-8, r.w-40, 3)
            pygame.draw.rect(
                self.screen, self.t["border"], track, border_radius=2
            )
            fill = pygame.Rect(
                track.x, track.y,
                int(track.w*self.operation_progress/100), track.h,
            )
            pygame.draw.rect(
                self.screen, self.t["accent"], fill, border_radius=2
            )

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

    def open_choice(self, title, options, current, callback):
        """Open a Kodi-style visible list of values for a TV setting."""
        options = list(options or [])
        if not options:
            return
        self.choice_active = True
        self.choice_title = str(title)
        self.choice_options = options
        self.choice_selected = next(
            (i for i, (_, value) in enumerate(options) if value == current), 0
        )
        self.choice_callback = callback
        self.mark_activity()

    def draw_choice(self):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 122 if not self.theme_name.endswith("Light") else 72))
        self.screen.blit(overlay, (0, 0))

        count = max(1, len(self.choice_options))
        row_h = int(self.h*.061)
        box_h = int(self.h*.095) + count*row_h + int(self.h*.045)
        box_h = min(box_h, int(self.h*.72))
        box_w = int(self.w*.330)
        box = pygame.Rect(0, 0, box_w, box_h)
        box.center = (int(self.w*.620), int(self.h*.555))
        self.glass_panel(box, False, 218, 22)

        self.text(self.choice_title, box.x+24, box.y+20,
                  self.h*.024, self.t["text"], True)
        y0 = box.y+int(self.h*.070)
        visible = max(1, int((box.bottom-y0-int(self.h*.025))/row_h))
        start = max(0, min(
            self.choice_selected-visible//2,
            max(0, len(self.choice_options)-visible),
        ))

        for local_i, (label, value) in enumerate(self.choice_options[start:start+visible]):
            i = start+local_i
            rr = pygame.Rect(box.x+18, y0+local_i*row_h,
                             box.w-36, int(row_h*.84))
            selected = i == self.choice_selected
            self.glass_panel(rr, selected, 185, 12)
            self.text(str(label), rr.x+18, rr.y+int(rr.h*.24),
                      rr.h*.29, self.t["text"], selected)
            if selected:
                check = self.font(rr.h*.30, True).render("✓", True, self.t["accent"])
                self.screen.blit(
                    check,
                    (rr.right-check.get_width()-18,
                     rr.y+(rr.h-check.get_height())//2),
                )

        self.text("↑/↓ vybere • OK potvrdit • Back zrušit",
                  box.x+22, box.bottom-int(self.h*.035),
                  self.h*.014, self.t["muted"])

    def handle_choice_key(self, key):
        if key == pygame.K_ESCAPE:
            self.choice_active = False
            self.choice_callback = None
            return
        if key == pygame.K_UP:
            self.choice_selected = max(0, self.choice_selected-1)
        elif key == pygame.K_DOWN:
            self.choice_selected = min(
                max(0, len(self.choice_options)-1), self.choice_selected+1
            )
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if not self.choice_options:
                self.choice_active = False
                return
            _, value = self.choice_options[self.choice_selected]
            callback = self.choice_callback
            self.choice_active = False
            self.choice_callback = None
            if callback:
                callback(value)

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

    def open_wifi_choice(self):
        current = nm_wifi_enabled()
        if current is None:
            self.show_toast("NetworkManager není aktivní", 4)
            return

        def apply(enabled):
            def worker():
                ok, msg = run_privileged(
                    "wifi-radio", {"enabled": bool(enabled)}, 20
                )
                self.show_toast(msg, 4)
                if ok and enabled:
                    time.sleep(0.4)
                    self.wifi_networks = list_wifi_networks()
            threading.Thread(target=worker, daemon=True).start()

        self.open_choice(
            "Wi‑Fi",
            [("Zapnuto", True), ("Vypnuto", False)],
            bool(current),
            apply,
        )

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
        # A visible long-running operation is active UI, not idle time.
        # Keep the global banner visible and never let CEC standby hide an
        # installation/update/app-start behind the screensaver.
        if self.operation_text:
            self.last_activity = time.monotonic()
            self.screensaver_stage = "off"
            self.cec_standby_sent = False
            return

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
        self._repair_fullscreen(force=True)
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

    def open_screensaver_choice(self, row):
        choices = {
            0: ("Spořič", [("Zapnuto", True), ("Vypnuto", False)], "screensaver_enabled"),
            1: ("Spustit po", [(f"{v} min", v) for v in (1,2,5,10,15,30,60)], "screensaver_after_min"),
            2: ("Typ spořiče", [("Hodiny","clock"), ("Černá obrazovka","black")], "screensaver_mode"),
            3: ("Úplně zčernat po", [("Vypnuto",0)] + [(f"{v} min",v) for v in (10,15,30,60,120)], "screensaver_black_after_min"),
            4: ("TV do standby přes CEC", [("Vypnuto",0)] + [(f"{v} min",v) for v in (15,30,60,120,240)], "screensaver_cec_standby_after_min"),
        }
        if row not in choices:
            return
        title, options, key = choices[row]
        self.open_choice(
            title, options, self.cfg.get(key, DEFAULT_CONFIG.get(key)),
            lambda value, setting=key: self._save_choice(setting, value),
        )

    def open_audio_port_choice(self):
        options = [("Automaticky","auto"), ("HDMI 0","0"), ("HDMI 1","1")]
        def apply(value):
            self._save_choice("hdmi_audio_port", value)
            set_default_hdmi_audio(value)
        self.open_choice(
            "HDMI audio výstup", options,
            str(self.cfg.get("hdmi_audio_port", "auto")), apply,
        )

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
        left = self.main_left()+int(self.w*.012)
        right = int(self.w*.014)
        hero_h = int(self.h*(.385 if self.cfg.get("home_layout") == "default" else .335))
        r = pygame.Rect(left, int(self.h*.058), self.w-left-right, hero_h)

        # The hero is itself glass, with a darker cinematic layer underneath.
        self.glass_panel(r, False, 170, 24)
        inner = r.inflate(-2, -2)
        hero_layer = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
        strips = 30
        is_light = self.theme_name.endswith("Light")
        top = (220,235,252) if is_light else (7,23,52)
        bottom = (242,247,252) if is_light else (3,13,31)
        for i in range(strips):
            y0 = round(i*inner.h/strips)
            y1 = round((i+1)*inner.h/strips)
            color = self.mix(top, bottom, i/max(1,strips-1))
            pygame.draw.rect(
                hero_layer, (*color, 214 if not is_light else 185),
                pygame.Rect(0,y0,inner.w,max(1,y1-y0)),
            )

        # Space/planet-inspired artwork built natively: atmospheric arc + city-like lights.
        art = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
        center = (int(inner.w*.72), int(inner.h*.90))
        radii = [int(inner.h*x) for x in (1.10, .98, .86, .74)]
        for i, radius in enumerate(radii):
            col = (76, 153, 255, max(12, 46-i*9)) if not is_light else (65,120,190,max(8,26-i*5))
            pygame.draw.circle(art, col, center, radius, max(1,int(self.h*.003)))
        # Deliberistic "city lights" dots, deterministic and cheap.
        for n in range(42):
            px = int(inner.w*(.50 + ((n*37)%47)/100))
            py = int(inner.h*(.40 + ((n*19)%34)/100))
            size = 1 + (n % 3 == 0)
            col = (255,205,116,110 if not is_light else 70)
            pygame.draw.circle(art, col, (px,py), size)
        art_glow = pygame.Surface((inner.w, inner.h), pygame.SRCALPHA)
        pygame.draw.circle(
            art_glow,
            (40,135,255,32 if not is_light else 16),
            (int(inner.w*.80), int(inner.h*.38)),
            int(inner.h*.52),
        )
        hero_layer.blit(art_glow,(0,0))
        hero_layer.blit(art,(0,0))
        self.screen.blit(hero_layer, inner.topleft)

        tx = r.x+int(self.w*.035)
        self.text("STREAM. APLIKACE. SERVERY. VÍCE.", tx, r.y+int(self.h*.050),
                  self.h*.014, self.t["muted"], True)
        self.text("PiTV", tx, r.y+int(self.h*.082),
                  self.h*.078, self.t["text"], True)
        self.text("Streamování, aplikace a domácí", tx+2, r.y+int(self.h*.185),
                  self.h*.021, self.t["text"])
        self.text("servery na jednom místě.", tx+2, r.y+int(self.h*.215),
                  self.h*.021, self.t["text"])

        ar = pygame.Rect(tx+2, r.bottom-int(self.h*.075), int(self.w*.118), int(self.h*.052))
        self.gradient_rect(ar, self.t["accent"], self.t["action"], radius=ar.h//2)
        pygame.draw.rect(self.screen, (255,255,255,42), ar, 1, border_radius=ar.h//2)
        surf = self.font(ar.h*.27, True).render("Prozkoumat  ›", True, (255,255,255))
        self.screen.blit(surf, surf.get_rect(center=ar.center))

        # Right-hand editorial words from the visual concept.
        rx = r.right-int(self.w*.165)
        ry = r.y+int(self.h*.090)
        for i, word in enumerate(("ZÁBAVA", "PŘIPOJENÍ", "VLASTNÍ SERVERY", "PODLE VÁS")):
            self.text(word, rx, ry+i*int(self.h*.034), self.h*.013, self.t["muted"], True)
        pygame.draw.line(
            self.screen, self.t["accent"],
            (rx, ry+int(self.h*.150)), (rx+int(self.w*.032), ry+int(self.h*.150)), 3,
        )

        # Page dots anchor the hero visually.
        dots_y = r.bottom-int(self.h*.018)
        dots_x = r.centerx-int(self.w*.015)
        for i in range(5):
            col = self.t["text"] if i == 0 else self.t["border"]
            pygame.draw.circle(self.screen, col, (dots_x+i*14, dots_y), 4)

        if self.cfg.get("show_clock", True):
            clock = self.font(self.h*.020, True).render(time.strftime("%H:%M"), True, self.t["text"])
            self.screen.blit(clock, (self.w-clock.get_width()-int(self.w*.055), int(self.h*.020)))
            gear_r = pygame.Rect(self.w-int(self.w*.038), int(self.h*.014), int(self.h*.040), int(self.h*.040))
            self.glass_panel(gear_r, False, 175, 11)
            gear = self.font(self.h*.020, True).render("⚙", True, self.t["text"])
            self.screen.blit(gear, gear.get_rect(center=gear_r.center))
        return r

    def draw_home_tile(self, item, rect, selected):
        style = self.HOME_TILE_STYLE.get(
            item.get("id", ""),
            (self.t["accent2"], self.t["action"], item.get("name","?")[:1].upper())
        )
        top, bottom, icon_text = style

        # Colored app tile inside a glass focus halo.
        if selected:
            glow = rect.inflate(14, 14)
            halo = pygame.Surface((glow.w, glow.h), pygame.SRCALPHA)
            pygame.draw.rect(halo, (*self.t["accent"], 54),
                             halo.get_rect(), border_radius=21)
            self.screen.blit(halo, glow.topleft)

        self.gradient_rect(rect, top, bottom, radius=17)
        sheen = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(
            sheen, (255,255,255,20), pygame.Rect(1,1,rect.w-2,max(2,int(rect.h*.46))),
            border_radius=16,
        )
        self.screen.blit(sheen, rect.topleft)

        dark_icon = item.get("id") in ("youtube-tv", "settings")
        icon_color = (239,35,45) if item.get("id") == "youtube-tv" else (
            (51,65,85) if dark_icon else (255,255,255)
        )
        icon = self.font(rect.h*.35, True).render(str(icon_text), True, icon_color)
        self.screen.blit(icon, icon.get_rect(center=rect.center))
        pygame.draw.rect(
            self.screen,
            self.t["accent"] if selected else (110,130,160),
            rect, 3 if selected else 1, border_radius=17,
        )

        app = item.get("app")
        if app:
            task_key = self._task_key(app, "apk" if app.get("kind") == "apk" else "linux")
            if task_key in self.background_tasks:
                badge = pygame.Rect(
                    rect.x+8, rect.y+8,
                    min(rect.w-16, int(self.w*.070)), int(self.h*.025),
                )
                badge_surf = pygame.Surface((badge.w, badge.h), pygame.SRCALPHA)
                pygame.draw.rect(
                    badge_surf, (4, 12, 26, 205), badge_surf.get_rect(),
                    border_radius=badge.h//2,
                )
                self.screen.blit(badge_surf, badge.topleft)
                pygame.draw.circle(
                    self.screen, self.t["accent"],
                    (badge.x+int(badge.h*.48), badge.centery), 3,
                )
                self.text(
                    "POZASTAVENO", badge.x+int(badge.h*.80),
                    badge.y+int(badge.h*.22), badge.h*.25,
                    (235,244,255), True,
                )

        if self.cfg.get("show_tile_labels", True):
            label = self.font(self.h*.0165, selected).render(
                item.get("name",""), True, self.t["text"]
            )
            self.screen.blit(
                label,
                (rect.centerx-label.get_width()//2, rect.bottom+int(self.h*.009))
            )

    def draw_home(self):
        self.draw_sidebar("home")
        items = self.home_items()
        hero = self.draw_home_hero()

        x = self.main_left()+int(self.w*.012)
        area_w = self.w-x-int(self.w*.014)
        cols = 6
        density = self.cfg.get("content_density", "normal")
        gap = int(self.w*({"comfortable": .012, "normal": .009, "compact": .007}.get(density,.009)))
        tile_w = int((area_w-(cols-1)*gap)/cols)
        scale = float(self.cfg.get("tile_scale",1.0))
        tile_h = int(self.h*.104*scale)

        title_gap = int(self.h*.017)
        label_space = int(self.h*.033) if self.cfg.get("show_tile_labels", True) else int(self.h*.012)
        first_title_y = hero.bottom+title_gap
        self.text("Doporučené aplikace", x, first_title_y, self.h*.020, self.t["text"], True)
        first_y = first_title_y+int(self.h*.036)

        for i, item in enumerate(items[:6]):
            rr = pygame.Rect(x+i*(tile_w+gap), first_y, tile_w, tile_h)
            self.draw_home_tile(item, rr, i == self.selected)

        second_title_y = first_y+tile_h+label_space+int(self.h*.020)
        self.text("Nástroje & utility", x, second_title_y, self.h*.020, self.t["text"], True)
        second_y = second_title_y+int(self.h*.036)

        for j, item in enumerate(items[6:12]):
            i = j+6
            rr = pygame.Rect(x+j*(tile_w+gap), second_y, tile_w, tile_h)
            self.draw_home_tile(item, rr, i == self.selected)

        hint = "Podrž Zpět 3 s = ukončit aplikaci • PiTV"
        hint_surf = self.font(self.h*.0135, False).render(
            hint, True, self.t["muted"]
        )
        self.screen.blit(
            hint_surf,
            (self.w-hint_surf.get_width()-int(self.w*.020),
             self.h-int(self.h*.030)),
        )

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

    SETTINGS_ICONS = ["✎", "▣", "⌁", "◖", "▱", "▦", "◉", "◆", "↻", "⚙", "◉", "ⓘ"]

    def _draw_settings_categories(self, selected_index):
        left = self.main_left()+int(self.w*.010)
        top = int(self.h*.195)
        width = int(self.w*.205)
        row_h = int(self.h*.057)
        for i, (name, _) in enumerate(self.SETTINGS):
            rr = pygame.Rect(left, top+i*row_h, width, int(row_h*.80))
            active = i == selected_index
            self.glass_panel(rr, active, 176, 13)
            icon = self.SETTINGS_ICONS[i] if i < len(self.SETTINGS_ICONS) else "•"
            self.text(icon, rr.x+15, rr.y+int(rr.h*.19), rr.h*.32,
                      self.t["accent"] if active else self.t["muted"], True)
            self.text(name, rr.x+int(rr.h*.76), rr.y+int(rr.h*.23), rr.h*.27,
                      self.t["text"] if active else self.t["muted"], active)
            ok_hint = self.font(rr.h*.19, True).render(
                "OK", True, self.t["accent"] if active else self.t["muted"]
            )
            self.screen.blit(
                ok_hint,
                (rr.right-ok_hint.get_width()-12,
                 rr.y+(rr.h-ok_hint.get_height())//2),
            )
        return pygame.Rect(left, top, width, row_h*len(self.SETTINGS))

    def draw_settings(self):
        self.settings_selected = max(0, min(self.settings_selected, len(self.SETTINGS)-1))
        self.draw_sidebar("settings")
        self.header("Nastavení", "Vše důležité pro PiTV na jednom místě")

        nav = self._draw_settings_categories(self.settings_selected)
        gap = int(self.w*.012)
        center_x = nav.right+gap
        center_w = int(self.w*.300)
        info_x = center_x+center_w+gap
        info_w = self.w-info_x-int(self.w*.014)
        top = int(self.h*.195)
        panel_h = int(self.h*.690)

        center = pygame.Rect(center_x, top, center_w, panel_h)
        info = pygame.Rect(info_x, top, info_w, panel_h)
        self.glass_panel(center, False, 174, 21)
        self.glass_panel(info, False, 165, 21)

        name, desc = self.SETTINGS[self.settings_selected]
        self.text(name, center.x+26, center.y+24, self.h*.030, self.t["text"], True)
        self.text(desc, center.x+26, center.y+int(self.h*.070), self.h*.016, self.t["muted"])

        bullets = {
            "Vzhled": ["Motiv a glass téma", "Barevný akcent", "Velikost a rozložení dlaždic"],
            "Spořič obrazovky": ["Hodiny / černá obrazovka", "Časovače", "CEC standby TV"],
            "Síť": ["Ethernet a Wi‑Fi", "IP adresa", "Výběr Wi‑Fi sítě"],
            "Zvuk": ["HDMI výstup", "CEC hlasitost", "Test zvuku"],
            "HDMI / CEC": ["TV ovladač", "Aktivní HDMI vstup", "Power / standby"],
            "Aplikace": ["Zobrazení aplikací", "Odinstalovat aplikace", "PiTV Store"],
            "Server Store": ["Homebridge", "Tailscale", "Docker", "ATVLoadly"],
            "Android / APK": ["Waydroid", "APK aplikace", "Google Play"],
            "Aktualizace": ["PiTV", "Store katalog", "Ubuntu"],
            "Systém": ["Teplota", "Paměť a disk", "Uptime"],
            "Napájení": ["Restart", "Vypnutí", "Potvrzení akce"],
            "O PiTV": ["PiTV "+VERSION, "Ubuntu Server + labwc", self.theme_name],
        }.get(name, [desc])

        yy = center.y+int(self.h*.135)
        for bullet in bullets:
            rr = pygame.Rect(center.x+22, yy, center.w-44, int(self.h*.061))
            self.glass_panel(rr, False, 154, 12)
            pygame.draw.circle(self.screen, self.t["accent"], (rr.x+18, rr.centery), 4)
            self.text(bullet, rr.x+34, rr.y+int(rr.h*.27), rr.h*.25, self.t["text"])
            yy += int(self.h*.074)

        # Visual help / live preview panel.
        preview = pygame.Rect(info.x+22, info.y+28, info.w-44, int(self.h*.225))
        self.glass_panel(preview, False, 145, 18)
        pw = int((preview.w-34)/2)
        ph = int((preview.h-34)/2)
        colors = [
            ((14,165,233),(2,132,199),"▶"),
            ((248,48,58),(185,28,28),"▶"),
            ((168,85,247),(109,40,217),"◆"),
            ((34,197,94),(22,163,74),"●"),
        ]
        for i,(a,b,icon_text) in enumerate(colors):
            rr = pygame.Rect(preview.x+11+(i%2)*(pw+12),
                             preview.y+11+(i//2)*(ph+12), pw, ph)
            self.gradient_rect(rr,a,b,radius=12)
            icon=self.font(rr.h*.30,True).render(icon_text,True,(255,255,255))
            self.screen.blit(icon,icon.get_rect(center=rr.center))

        self.text(name, info.x+24, preview.bottom+int(self.h*.028),
                  self.h*.025, self.t["text"], True)
        help_lines = {
            "Vzhled": ["Upravte vzhled PiTV.", "Volby se otevírají jako", "viditelný seznam – stejně jako v Kodi."],
            "Aplikace": ["Spravujte aplikace přes seznamy.", "OK otevře další nabídku.", "Žádné skryté akce na pravé šipce."],
        }.get(name, ["Stiskněte OK pro otevření.", "Back se vrátí o úroveň zpět."])
        hy = preview.bottom+int(self.h*.072)
        for line in help_lines:
            self.text(line, info.x+24, hy, self.h*.016, self.t["muted"])
            hy += int(self.h*.026)

        self.text("↑/↓ vybere • OK otevře • Back návrat",
                  nav.x, int(self.h*.922), self.h*.014, self.t["muted"])

    def draw_rows(self, title, subtitle, rows, selected=0, footer="",
                  settings_index=None, info_lines=None, sidebar_active="settings"):
        """Draw a TV-friendly list.

        When a page was opened from Settings, every Settings section uses the
        same three-column navigation model as Appearance: categories on the
        left, the actual choices/actions in the middle and contextual help on
        the right. Shared top-level pages keep their normal full-width layout.
        """
        if self.settings_context and settings_index is not None:
            self.draw_sidebar("settings")
            self.header("Nastavení", "Vše důležité pro PiTV na jednom místě")
            nav = self._draw_settings_categories(settings_index)

            gap = int(self.w*.012)
            center_x = nav.right+gap
            center_w = int(self.w*.300)
            info_x = center_x+center_w+gap
            info_w = self.w-info_x-int(self.w*.014)
            top = int(self.h*.195)
            panel_h = int(self.h*.690)

            center = pygame.Rect(center_x, top, center_w, panel_h)
            info = pygame.Rect(info_x, top, info_w, panel_h)
            self.glass_panel(center, False, 175, 21)
            self.glass_panel(info, False, 165, 21)

            icon = self.SETTINGS_ICONS[settings_index] if settings_index < len(self.SETTINGS_ICONS) else "•"
            self.text(f"{icon}  {title}", center.x+24, center.y+22,
                      self.h*.027, self.t["text"], True)
            self.text(subtitle, center.x+26, center.y+int(self.h*.064),
                      self.h*.0145, self.t["muted"])

            rows = list(rows or [])
            if rows:
                selected = max(0, min(selected, len(rows)-1))
            else:
                selected = 0
                rows = [("Žádné položky", "—")]

            visible = min(8, len(rows))
            start_row = max(0, min(selected-visible//2, max(0, len(rows)-visible)))
            shown = rows[start_row:start_row+visible]
            local_selected = selected-start_row
            y0 = center.y+int(self.h*.105)
            row_h = int(self.h*.066)
            for i,row in enumerate(shown):
                label, value = str(row[0]), str(row[1])
                rr = pygame.Rect(center.x+16, y0+i*row_h,
                                 center.w-32, int(row_h*.82))
                active = i == local_selected
                self.glass_panel(rr, active, 176, 12)
                self.text(label, rr.x+15, rr.y+int(rr.h*.22),
                          rr.h*.245, self.t["text"], active)

                vf = self.font(rr.h*.205, False)
                maxw = int(rr.w*.42)
                shown_value = self._fit_ui_text(value, vf, maxw)
                vs = vf.render(shown_value, True,
                               self.t["accent"] if active else self.t["muted"])
                ok_hint = self.font(rr.h*.19, True).render(
                    "OK", True, self.t["accent"] if active else self.t["muted"]
                )
                self.screen.blit(
                    ok_hint,
                    (rr.right-ok_hint.get_width()-10,
                     rr.y+(rr.h-ok_hint.get_height())//2),
                )
                self.screen.blit(
                    vs,
                    (rr.right-ok_hint.get_width()-vs.get_width()-24,
                     rr.y+(rr.h-vs.get_height())//2),
                )

            selected_row = rows[selected]
            preview = pygame.Rect(info.x+22, info.y+28,
                                  info.w-44, int(self.h*.188))
            self.glass_panel(preview, False, 148, 18)
            self.text(str(selected_row[0]), preview.x+22, preview.y+22,
                      self.h*.024, self.t["text"], True)
            value_font = self.font(self.h*.019, True)
            value_text = self._fit_ui_text(
                str(selected_row[1]), value_font, preview.w-44
            )
            value_surf = value_font.render(value_text, True, self.t["accent"])
            self.screen.blit(value_surf, (preview.x+22, preview.y+int(self.h*.072)))

            help_y = preview.bottom+int(self.h*.033)
            help_title = "Co tato část dělá"
            self.text(help_title, info.x+24, help_y,
                      self.h*.021, self.t["text"], True)
            help_y += int(self.h*.043)
            lines = list(info_lines or [
                "↑/↓ vybere položku.",
                "OK otevře volbu nebo provede akci.",
                "Back se vrátí do seznamu Nastavení.",
            ])
            for line in lines[:7]:
                self.text(str(line), info.x+24, help_y,
                          self.h*.0155, self.t["muted"])
                help_y += int(self.h*.028)

            if footer:
                self.text(footer, center.x, int(self.h*.922),
                          self.h*.014, self.t["muted"])
            return

        self.draw_sidebar(sidebar_active)
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

    def appearance_rows(self):
        scale = float(self.cfg.get("tile_scale", 1.0))
        scale_names = {0.85:"Malá", 1.0:"Normální", 1.15:"Velká", 1.30:"Extra velká"}
        return [
            ("Motiv", "Tmavý" if self.theme_name.endswith("Dark") else "Světlý"),
            ("Barevný akcent", {"blue":"Modrý","purple":"Fialový","green":"Zelený"}.get(self.cfg.get("accent"),"Modrý")),
            ("Velikost dlaždic", scale_names.get(scale, "Normální")),
            ("Rozložení domovské obrazovky", "Výchozí" if self.cfg.get("home_layout") == "default" else "Kompaktní"),
            ("Zobrazit popisky ikon", "Zapnuto" if self.cfg.get("show_tile_labels", True) else "Vypnuto"),
            ("Hustota obsahu", {"comfortable":"Vzdušná","normal":"Normální","compact":"Kompaktní"}.get(self.cfg.get("content_density"),"Normální")),
            ("Hodiny na ploše", "Zapnuto" if self.cfg.get("show_clock", True) else "Vypnuto"),
        ]

    def _save_choice(self, key, value):
        self.cfg[key] = value
        save_user_config(self.cfg)
        self.mark_activity()

    def open_appearance_choice(self, row):
        choices = {
            0: ("Motiv", [("Tmavý", "apple_dark"), ("Světlý", "apple_light")], "theme"),
            1: ("Barevný akcent", [("Modrý","blue"), ("Fialový","purple"), ("Zelený","green")], "accent"),
            2: ("Velikost dlaždic", [("Malá",.85), ("Normální",1.0), ("Velká",1.15), ("Extra velká",1.30)], "tile_scale"),
            3: ("Rozložení domovské obrazovky", [("Výchozí","default"), ("Kompaktní","compact")], "home_layout"),
            4: ("Zobrazit popisky ikon", [("Zapnuto",True), ("Vypnuto",False)], "show_tile_labels"),
            5: ("Hustota obsahu", [("Vzdušná","comfortable"), ("Normální","normal"), ("Kompaktní","compact")], "content_density"),
            6: ("Hodiny na ploše", [("Zapnuto",True), ("Vypnuto",False)], "show_clock"),
        }
        title, options, key = choices.get(row, choices[0])
        self.open_choice(
            title, options, self.cfg.get(key, DEFAULT_CONFIG.get(key)),
            lambda value, setting=key: self._save_choice(setting, value),
        )

    def draw_appearance(self):
        self.draw_sidebar("settings")
        self.header("Nastavení", "Vše důležité pro PiTV na jednom místě")
        nav = self._draw_settings_categories(0)

        gap = int(self.w*.012)
        center_x = nav.right+gap
        center_w = int(self.w*.300)
        info_x = center_x+center_w+gap
        info_w = self.w-info_x-int(self.w*.014)
        top = int(self.h*.195)
        panel_h = int(self.h*.690)

        center = pygame.Rect(center_x, top, center_w, panel_h)
        info = pygame.Rect(info_x, top, info_w, panel_h)
        self.glass_panel(center, False, 175, 21)
        self.glass_panel(info, False, 165, 21)

        self.text("✎  Vzhled", center.x+24, center.y+22,
                  self.h*.030, self.t["text"], True)
        self.text("Přizpůsobte si vzhled a chování PiTV.",
                  center.x+26, center.y+int(self.h*.067),
                  self.h*.0155, self.t["muted"])

        rows = self.appearance_rows()
        self.sub_selected = max(0,min(self.sub_selected,len(rows)-1))
        y0 = center.y+int(self.h*.110)
        row_h = int(self.h*.070)
        for i,(label,value) in enumerate(rows):
            rr=pygame.Rect(center.x+16,y0+i*row_h,center.w-32,int(row_h*.83))
            active=i==self.sub_selected
            self.glass_panel(rr,active,175,12)
            self.text(label,rr.x+16,rr.y+int(rr.h*.25),rr.h*.25,
                      self.t["text"],active)
            value_surf=self.font(rr.h*.235,False).render(value,True,
                        self.t["accent"] if active else self.t["muted"])
            ok_hint=self.font(rr.h*.19,True).render(
                "OK",True,self.t["accent"] if active else self.t["muted"]
            )
            self.screen.blit(
                ok_hint,
                (rr.right-ok_hint.get_width()-10,
                 rr.y+(rr.h-ok_hint.get_height())//2),
            )
            self.screen.blit(
                value_surf,
                (rr.right-ok_hint.get_width()-value_surf.get_width()-24,
                 rr.y+(rr.h-value_surf.get_height())//2),
            )

        # Live preview mirrors the selected tile size and accent.
        preview=pygame.Rect(info.x+22,info.y+28,info.w-44,int(self.h*.225))
        self.glass_panel(preview,False,145,18)
        size=float(self.cfg.get("tile_scale",1.0))
        base_w=int(preview.w*.35*min(1.14,size))
        base_h=int(preview.h*.35*min(1.14,size))
        colors=[
            ((14,165,233),(2,132,199),"▶"),
            ((248,48,58),(185,28,28),"▶"),
            ((168,85,247),(109,40,217),"◆"),
            ((34,197,94),(22,163,74),"●"),
        ]
        sx=preview.centerx-(base_w*2+10)//2
        sy=preview.centery-(base_h*2+10)//2
        for i,(a,b,icon_text) in enumerate(colors):
            rr=pygame.Rect(sx+(i%2)*(base_w+10),sy+(i//2)*(base_h+10),base_w,base_h)
            self.gradient_rect(rr,a,b,radius=11)
            icon=self.font(rr.h*.28,True).render(icon_text,True,(255,255,255))
            self.screen.blit(icon,icon.get_rect(center=rr.center))

        selected_label=rows[self.sub_selected][0]
        self.text(selected_label,info.x+24,preview.bottom+int(self.h*.028),
                  self.h*.025,self.t["text"],True)
        info_lines=[
            "Stiskněte OK a zobrazí se všechny",
            "možnosti v seznamu. Žádné slepé",
            "přepínání hodnot šipkami.",
        ]
        iy=preview.bottom+int(self.h*.075)
        for line in info_lines:
            self.text(line,info.x+24,iy,self.h*.0155,self.t["muted"])
            iy+=int(self.h*.026)
        self.text("OK = otevřít nabídku • Back = zpět",
                  center.x, int(self.h*.922), self.h*.014, self.t["muted"])

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
        self.draw_rows(
            "Spořič obrazovky", "PiTV i server dál běží 24/7",
            rows, self.sub_selected,
            "OK otevře seznam možností • Náhled spustí spořič • Back návrat",
            settings_index=1,
            info_lines=[
                "Nastavte, co se stane při nečinnosti.",
                "PiTV ani server se kvůli spořiči nevypínají.",
                "Každá hodnota se vybírá z viditelného seznamu.",
            ],
        )

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
        self.draw_rows(
            "Síť", subtitle, rows, selected,
            "OK = akce/připojit • heslo se zadává ovladačem • Ethernet PiTV nepřepisuje",
            settings_index=2,
            info_lines=[
                "Wi‑Fi můžete zapnout, vypnout a znovu vyhledat.",
                "Vyberte síť a potvrďte OK.",
                "Ethernet a serverové služby PiTV nepřepisuje.",
            ],
        )

    def draw_audio(self):
        items = self.audio_items()
        rows = [(x["title"], x["detail"]) for x in items]
        self.draw_rows(
            "Zvuk", "PiTV používá pouze zvuk přes HDMI",
            rows, self.audio_selected,
            "Hlasitost TV/receiveru jde přes HDMI‑CEC",
            settings_index=3,
            info_lines=[
                "HDMI výstup otevře seznam dostupných voleb.",
                "Hlasitost a Mute se posílají televizi přes CEC.",
                "Test zvuku ověří vybraný HDMI výstup.",
            ],
        )

    CEC_ACTIONS = [
        ("Zapnout / probudit TV", "Power On + Active Source", cec_tv_on),
        ("Přepnout TV na PiTV", "Active Source", cec_active_source),
        ("Hlasitost +", "TV / receiver přes CEC", cec_volume_up),
        ("Hlasitost −", "TV / receiver přes CEC", cec_volume_down),
        ("Mute / unmute", "TV / receiver přes CEC", cec_mute),
        ("Standby TV", "Vypnout obrazovku TV", cec_tv_standby),
    ]

    def cec_rows(self):
        if self.cfg.get("cec_enabled", True):
            if system_input_managed():
                device = system_input_cec_device()
                if device:
                    cec_state = f"Zapnuto · systémový TV input · {device}"
                elif system_input_ready():
                    cec_state = "Zapnuto · čekám na HDMI‑CEC"
                else:
                    cec_state = "Zapnuto · TV input se spouští"
            else:
                cec_state = "Zapnuto · systémová TV input služba chybí"
        else:
            cec_state = "Vypnuto"
        return [
            (
                "HDMI‑CEC ovládání",
                cec_state,
            ),
            (
                "Probudit TV při startu",
                "Zapnuto" if self.cfg.get("cec_wake_on_start", False) else "Vypnuto",
            ),
        ] + [(name, desc) for name, desc, _ in self.CEC_ACTIONS]

    def _apply_cec_enabled(self, enabled):
        enabled = bool(enabled)
        self._save_choice("cec_enabled", enabled)

        if not system_input_managed():
            self.show_toast("Systémová TV input služba není nainstalovaná", 4)
            return

        def worker():
            ok, msg = run_privileged(
                "tv-input-enable", {"enabled": enabled}, 30
            )
            self.show_toast(
                "HDMI‑CEC zapnuto" if ok and enabled
                else "HDMI‑CEC vypnuto" if ok
                else (msg or "HDMI‑CEC změna selhala"),
                3,
            )
        threading.Thread(target=worker, daemon=True).start()

    def open_cec_choice(self, row):
        if row == 0:
            self.open_choice(
                "HDMI‑CEC ovládání",
                [("Zapnuto", True), ("Vypnuto", False)],
                bool(self.cfg.get("cec_enabled", True)),
                self._apply_cec_enabled,
            )
        elif row == 1:
            self.open_choice(
                "Probudit TV při startu",
                [("Zapnuto", True), ("Vypnuto", False)],
                bool(self.cfg.get("cec_wake_on_start", False)),
                lambda value: self._save_choice("cec_wake_on_start", bool(value)),
            )

    def draw_cec(self):
        ports = get_hdmi_ports()
        port_text = " · ".join(
            f"{p['name']} {p['status']}" for p in ports
        ) or "HDMI stav neznámý"
        rows = self.cec_rows()
        self.cec_selected = max(0, min(self.cec_selected, len(rows)-1))
        self.draw_rows(
            "HDMI / CEC",
            ("CEC dostupné · " if cec_available() else "CEC nedostupné · ") + port_text,
            rows, self.cec_selected,
            "↑/↓ vybere • OK spustí • Back návrat",
            settings_index=4,
            info_lines=[
                "Tady se ovládá televize přes HDMI‑CEC.",
                "Ovladač běží jako systémová TV input služba pod aplikacemi.",
                "Power, Active Source i hlasitost jsou samostatné akce.",
            ],
        )

    def _store_item_for_app(self, app):
        """Return the Store entry that owns an app, without confusing legacy APKs."""
        if not app:
            return None
        kind = app.get("kind", "linux")
        package = str(app.get("package", "") or "").strip()
        command = str(app.get("command", "") or "")
        name = str(app.get("name", "") or "").strip().lower()

        # Android entries must match by package. A legacy Android Stremio can
        # have the same display name as today's native Linux Stremio.
        if kind == "apk":
            if not package:
                return None
            for item in self.store_catalog:
                installer = item.get("installer", {})
                candidate = installer.get("package") or installer.get("expected_package")
                if candidate == package:
                    return item
            return None

        for item in self.store_catalog:
            installer = item.get("installer", {})
            app_id = str(installer.get("app_id", "") or "")
            package_name = str(installer.get("package", "") or "")
            if app_id and app_id in command:
                return item
            if package_name and command.split()[:1] == [package_name]:
                return item
            if name and str(item.get("name", "")).strip().lower() == name:
                return item
        return None

    def app_can_uninstall(self, app):
        if not app:
            return False
        if app.get("kind") == "apk":
            return bool(app.get("package"))
        item = self._store_item_for_app(app)
        if not item:
            return False
        return item.get("installer", {}).get("type") in ("apt", "flatpak")

    def uninstall_app_async(self, app):
        if self.app_action_busy:
            self.show_toast("Probíhá jiná operace s aplikací", 3)
            return
        app = dict(app or {})
        if not self.app_can_uninstall(app):
            self.show_toast("Tuto aplikaci PiTV neumí bezpečně odinstalovat", 5)
            return

        self.app_action_busy = True
        name = app.get("name", "Aplikace")
        self.set_operation(f"Odinstalovávám {name}…")
        self.show_toast(f"Odinstalovávám {name}…", 4)

        def worker():
            ok = False
            msg = ""
            try:
                if app.get("kind") == "apk":
                    package = str(app.get("package", "") or "").strip()
                    apk_path = str(app.get("apk_path", "") or "").strip()
                    ok, msg = run_privileged(
                        "waydroid-app-uninstall", {"package": package}, 300
                    )
                    if ok:
                        # PiTV-managed APK files are safe to remove together
                        # with the Android package. Never unlink an arbitrary path.
                        if apk_path:
                            try:
                                target = Path(apk_path).resolve()
                                roots = [
                                    Path("/var/lib/pitv/apks").resolve(),
                                    (Path.home() / "PiTV" / "APKs").resolve(),
                                ]
                                if target.suffix.lower() == ".apk" and any(
                                        target == root or root in target.parents
                                        for root in roots):
                                    target.unlink(missing_ok=True)
                            except Exception:
                                pass
                        clear_android_receipts(package, apk_path)
                else:
                    item = self._store_item_for_app(app)
                    installer = item.get("installer", {}) if item else {}
                    install_type = installer.get("type")
                    if install_type == "flatpak":
                        ok, msg = run_privileged(
                            "flatpak-uninstall",
                            {"app_id": installer.get("app_id", "")},
                            1200,
                        )
                    elif install_type == "apt":
                        ok, msg = run_privileged(
                            "apt-remove",
                            {"package": installer.get("package", "")},
                            1200,
                        )
                    else:
                        msg = "Tento typ aplikace zatím nelze odinstalovat"

                if ok:
                    hidden = set(self.cfg.get("hidden_apps", []))
                    hidden.discard(str(name))
                    self.cfg["hidden_apps"] = sorted(hidden)
                    save_user_config(self.cfg)
                    self.apps = load_apps()
                    self.apps_selected = min(
                        self.apps_selected, max(0, len(self.app_items()) - 1)
                    )
                    self.android_selected = min(
                        self.android_selected, max(0, len(self.android_items()) - 1)
                    )
                    self.refresh_store_async()
            except Exception as e:
                ok, msg = False, f"Odinstalace selhala: {e}"
            finally:
                self.app_action_busy = False
                final = f"{name} odinstalováno" if ok else (msg or "Odinstalace selhala")
                self.finish_operation(final, ok, 4.0 if ok else 7.0)
                self.show_toast(final, 5 if ok else 7)

        threading.Thread(target=worker, daemon=True).start()

    def app_items(self):
        """High-level application management menu.

        Settings never overloads Right with destructive actions. Every
        configuration path is opened explicitly with OK and, where a value or
        target must be chosen, uses the same visible choice list.
        """
        uninstallable = [a for a in self.apps if self.app_can_uninstall(a)]
        return [
            {
                "kind": "store",
                "name": "PiTV Store",
                "detail": "Instalovat a spravovat aplikace",
            },
            {
                "kind": "visibility",
                "name": "Zobrazení aplikací",
                "detail": f"{len(self.apps)} aplikací · vybrat ze seznamu",
            },
            {
                "kind": "uninstall",
                "name": "Odinstalovat aplikace",
                "detail": (
                    f"{len(uninstallable)} aplikací · vybrat ze seznamu"
                    if uninstallable else "Žádná aplikace k odinstalování"
                ),
            },
            {
                "kind": "refresh",
                "name": "Obnovit seznam aplikací",
                "detail": "Načíst aktuální stav",
            },
        ]

    def set_app_visibility(self, name, visible):
        hidden = set(self.cfg.get("hidden_apps", []))
        if visible:
            hidden.discard(name)
        else:
            hidden.add(name)
        self.cfg["hidden_apps"] = sorted(hidden)
        save_user_config(self.cfg)
        self.mark_activity()

    def open_app_visibility_choice(self, item):
        name = item.get("name", "Aplikace")
        hidden = set(self.cfg.get("hidden_apps", []))
        visible = name not in hidden
        self.open_choice(
            name,
            [
                ("Zobrazit na ploše", True),
                ("Skrýt z plochy", False),
            ],
            visible,
            lambda value, app_name=name: self.set_app_visibility(
                app_name, bool(value)
            ),
        )

    def open_app_visibility_list(self):
        options = [
            (
                (
                    f"{app.get('name','Aplikace')}  ·  "
                    f"{'Na ploše' if app.get('name','') not in set(self.cfg.get('hidden_apps', [])) else 'Skryto'}"
                ),
                dict(app),
            )
            for app in self.apps
        ]
        if not options:
            self.show_toast("Nejsou nalezené žádné aplikace", 4)
            return
        self.open_choice(
            "Zobrazení aplikací",
            options,
            None,
            self.open_app_visibility_choice,
        )

    def _confirm_uninstall_app(self, app):
        app = dict(app or {})
        name = app.get("name", "aplikaci")
        self.open_confirm(
            f"Odinstalovat {name}",
            "Opravdu aplikaci odinstalovat z PiTV?",
            lambda selected=app: self.uninstall_app_async(selected),
        )

    def open_app_uninstall_list(self):
        apps = [dict(app) for app in self.apps if self.app_can_uninstall(app)]
        if not apps:
            self.show_toast("Žádná aplikace není dostupná k odinstalování", 4)
            return
        self.open_choice(
            "Odinstalovat aplikace",
            [(app.get("name", "Aplikace"), app) for app in apps],
            None,
            self._confirm_uninstall_app,
        )

    def draw_apps_settings(self):
        items = self.app_items()
        self.apps_selected = max(0, min(self.apps_selected, max(0, len(items)-1)))
        rows = [(item["name"], item["detail"]) for item in items]
        self.draw_rows(
            "Aplikace", "Správa aplikací pomocí jednotných seznamových nabídek",
            rows, self.apps_selected,
            "↑/↓ vybere • OK otevře • Back návrat",
            settings_index=5,
            info_lines=[
                "OK vždy otevře vybranou nabídku.",
                "Zobrazení aplikací vybere aplikaci ze seznamu.",
                "Odinstalování má vlastní seznam a následné potvrzení.",
                "Pravá šipka v Nastavení nespouští žádnou akci.",
            ],
        )

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
                    ok, msg = run_privileged("apt-install", {"package": package}, 1800)
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
                        ok, msg = run_privileged("apt-install", {"package": package}, 1800)
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
                        self._register_external(proc, "linux", app)
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
                        proc = subprocess.Popen(
                            ["/usr/local/bin/pitv-waydroid-launch", "--play-store", package],
                            env=env,
                            cwd=str(Path.home()),
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self.store_busy_id = ""
                        self.android_pending_proc = proc
                        self.android_pending_package = "com.android.vending"
                        self.android_pending_app = dict(app)
                        self.set_operation(f"Otevírám {item.get('name','aplikaci')} v Google Play…")
                        self.show_toast(f"Otevírám {item.get('name','aplikaci')} v Google Play", 5)
                        self._watch_android_launch(
                            proc, dict(app), "com.android.vending", "Google Play"
                        )
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
        items = self.server_store_catalog
        if self.settings_context:
            self.server_store_selected = max(
                0, min(self.server_store_selected, max(0, len(items)-1))
            )
            rows = [
                (
                    item.get("name", "Služba"),
                    self.server_store_status_label(item),
                )
                for item in items
            ]
            self.draw_rows(
                "Server Store", "Služby běžící na pozadí",
                rows or [("Server Store", "Katalog je prázdný")],
                self.server_store_selected if rows else 0,
                "OK = instalovat / spravovat • Back návrat",
                settings_index=6,
                info_lines=[
                    "Serverové služby běží i když PiTV UI restartujete.",
                    "OK nainstaluje službu nebo zobrazí její stav.",
                    "Homebridge, Tailscale a Docker nejsou TV aplikace.",
                ],
            )
            return

        self.draw_sidebar("server_store")
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
        self.draw_rows(
            "Android / APK", "APK inspector · aapt/apktool · Waydroid",
            rows[start:start+visible], self.android_selected-start,
            "OK = otevřít / provést akci • Back návrat",
            settings_index=7,
            info_lines=[
                "Waydroid zajišťuje Android TV aplikace.",
                "APK lze obnovit, spustit a bezpečně odinstalovat.",
                "Google Play se instaluje společně s Waydroidem.",
            ],
            sidebar_active="android",
        )

    def _installed_store_apt_packages(self):
        packages = []
        for item in self.store_catalog:
            ins = item.get("installer", {})
            if ins.get("type") != "apt":
                continue
            try:
                if store_state(item) == "installed" and ins.get("package"):
                    packages.append(ins.get("package"))
            except Exception:
                pass
        return packages

    def _installed_store_flatpak_ids(self):
        app_ids = []
        for item in self.store_catalog:
            ins = item.get("installer", {})
            if ins.get("type") != "flatpak":
                continue
            try:
                if store_state(item) == "installed" and ins.get("app_id"):
                    app_ids.append(ins.get("app_id"))
            except Exception:
                pass
        return app_ids

    def update_status_items(self):
        if self.remote_pitv:
            pitv_value = (
                f"{VERSION} → {self.remote_pitv}"
                if is_newer(self.remote_pitv, VERSION)
                else f"{VERSION} · aktuální"
            )
        else:
            pitv_value = f"{VERSION} · {self.updates_status}"

        ubuntu_value = "—" if self.update_count is None else f"{self.update_count} balíčků"
        if self.update_checking or self.updates_status == "Kontroluji…":
            ubuntu_value = "Kontroluji…"

        installed_linux = []
        for item in self.store_catalog:
            ins = item.get("installer", {})
            if ins.get("type") in ("apt", "flatpak"):
                try:
                    if store_state(item) == "installed":
                        installed_linux.append(
                            item.get("name", ins.get("package") or ins.get("app_id", ""))
                        )
                except Exception:
                    pass

        return [
            ("PiTV", pitv_value),
            ("Store katalogy", "PiTV Store + Server Store"),
            ("Store aplikace", ", ".join(installed_linux) if installed_linux else "žádné"),
            ("Ubuntu", ubuntu_value),
        ]

    def update_items(self):
        busy = "Probíhá…" if self.updates_busy else "Doporučeno"
        checked = self.updates_status if self.updates_status not in ("", "Nezkontrolováno") else "Zjistit stav"
        return [
            ("Aktualizovat vše", busy),
            ("Zkontrolovat aktualizace", checked),
            ("Pokročilé možnosti", "Jednotlivé části"),
            ("Restartovat PiTV UI", "Server zůstane běžet"),
        ]

    def _updates_help_lines(self):
        status = self.update_status_items()
        return [
            f"PiTV: {status[0][1]}",
            f"Ubuntu: {status[3][1]}",
            f"Store aplikace: {status[2][1]}",
            "Aktualizovat vše je doporučená volba.",
            "Nastavení a uživatelská data zůstanou zachována.",
        ]

    def draw_updates(self):
        actions = self.update_items()
        self.updates_selected = max(0, min(self.updates_selected, len(actions)-1))

        if self.settings_context:
            self.draw_rows(
                "Aktualizace", "Jedno místo pro celé PiTV",
                actions, self.updates_selected,
                "OK = spustit • Pokročilé = jednotlivé části • Back návrat",
                settings_index=8,
                info_lines=self._updates_help_lines(),
            )
            return

        self.draw_sidebar("updates")
        self.header("Aktualizace", "Jedno tlačítko pro PiTV, Store aplikace a Ubuntu")

        x = self.main_left()+int(self.w*.020)
        width = self.w-x-int(self.w*.038)
        top = int(self.h*.158)

        # One status panel instead of a grid of unrelated action cards.
        status_panel = pygame.Rect(x, top, width, int(self.h*.245))
        self.glass_panel(status_panel, False, 218, 22)
        self.text("Stav aktualizací", status_panel.x+24, status_panel.y+18,
                  self.h*.025, self.t["text"], True)
        self.text(
            "PiTV zkontroluje všechny části za vás.",
            status_panel.x+24, status_panel.y+int(self.h*.058),
            self.h*.015, self.t["muted"],
        )

        statuses = self.update_status_items()
        col_gap = int(self.w*.014)
        inner_w = status_panel.w-48
        col_w = int((inner_w-col_gap)/2)
        row_h = int(self.h*.066)
        sy = status_panel.y+int(self.h*.092)
        for i,(label,value) in enumerate(statuses):
            col = i % 2
            row = i // 2
            rr = pygame.Rect(
                status_panel.x+24+col*(col_w+col_gap),
                sy+row*row_h, col_w, int(row_h*.80),
            )
            self.glass_panel(rr, False, 155, 12)
            self.text(label, rr.x+14, rr.y+int(rr.h*.20),
                      rr.h*.245, self.t["text"], True)
            vf = self.font(rr.h*.205, False)
            value_text = self._fit_ui_text(str(value), vf, int(rr.w*.58))
            vs = vf.render(value_text, True, self.t["muted"])
            self.screen.blit(vs, (
                rr.right-vs.get_width()-14,
                rr.y+(rr.h-vs.get_height())//2,
            ))

        action_y = status_panel.bottom+int(self.h*.030)

        # The recommended action is intentionally dominant.
        primary = pygame.Rect(x, action_y, width, int(self.h*.105))
        primary_selected = self.updates_selected == 0
        self.glass_panel(primary, primary_selected, 236, 18)
        self.text("Aktualizovat vše", primary.x+24, primary.y+int(primary.h*.20),
                  primary.h*.255, self.t["text"], True)
        self.text(
            "Store katalogy → Store aplikace → Ubuntu → PiTV",
            primary.x+24, primary.y+int(primary.h*.57),
            primary.h*.155,
            self.t["accent"] if primary_selected else self.t["muted"],
        )
        badge = "PROBÍHÁ" if self.updates_busy else "DOPORUČENO"
        self.pill(badge, primary.right-int(self.w*.112),
                  primary.y+int(primary.h*.31), self.t["accent"])

        y = primary.bottom+int(self.h*.024)
        small_h = int(self.h*.078)
        for i,(label,value) in enumerate(actions[1:], start=1):
            rr = pygame.Rect(x, y, width, small_h)
            selected = i == self.updates_selected
            self.glass_panel(rr, selected, 210, 15)
            self.text(label, rr.x+22, rr.y+int(rr.h*.27),
                      rr.h*.255, self.t["text"], selected)
            vf = self.font(rr.h*.205, False)
            vs = vf.render(str(value), True,
                           self.t["accent"] if selected else self.t["muted"])
            self.screen.blit(vs, (
                rr.right-vs.get_width()-22,
                rr.y+(rr.h-vs.get_height())//2,
            ))
            y += small_h+int(self.h*.014)

        self.text(
            "Aktualizovat vše = běžná volba • Pokročilé = jen jedna konkrétní část",
            x, int(self.h*.920), self.h*.015, self.t["muted"],
        )

    def open_update_advanced_choice(self):
        self.open_choice(
            "Pokročilé aktualizace",
            [
                ("Pouze PiTV", "pitv"),
                ("Pouze Store + Server katalog", "catalog"),
                ("Pouze Store aplikace", "linux"),
                ("Pouze Ubuntu", "ubuntu"),
            ],
            "",
            self._run_update_advanced,
        )

    def _run_update_advanced(self, action):
        if action == "pitv":
            self.open_confirm(
                "Aktualizovat pouze PiTV",
                "Stáhnout nejnovější PiTV a poté restartovat rozhraní?",
                self.update_pitv_async,
            )
        elif action == "catalog":
            self.update_store_catalog_async()
        elif action == "linux":
            self.open_confirm(
                "Store aplikace",
                "Aktualizovat nainstalované aplikace spravované PiTV Store?",
                self.update_linux_store_apps_async,
            )
        elif action == "ubuntu":
            self.open_confirm(
                "Aktualizovat Ubuntu",
                "Nainstalovat dostupné systémové aktualizace Ubuntu?",
                self.update_ubuntu_async,
            )

    def update_all_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.set_operation("Aktualizovat vše · připravuji…", 5)
        self.show_toast("Aktualizuji celé PiTV…", 5)

        def fail(step, msg):
            self.updates_busy = False
            text = f"{step}: {msg}"
            self.finish_operation(text, False, 7)
            self.show_toast(text, 7)

        def worker():
            # 1) Catalogs first so the rest of the update uses current metadata.
            self.set_operation("1/4 · Aktualizuji Store katalogy…", 15)
            ok, msg = run_privileged("store-catalog-update", {}, 90)
            if not ok:
                fail("Store katalogy", msg)
                return
            self.store_catalog = load_store_catalog()
            self.server_store_catalog = load_server_catalog()
            self.store_states = {}

            # 2) Update all PiTV-managed native Linux Store apps. Kodi is
            # APT-managed while Stremio is system Flatpak; both belong under
            # the same user-facing "Store aplikace" step.
            self.set_operation("2/4 · Aktualizuji Store aplikace…", 38)
            packages = self._installed_store_apt_packages()
            flatpaks = self._installed_store_flatpak_ids()
            if packages:
                ok, msg = run_privileged(
                    "apt-store-upgrade", {"packages": packages}, 1800
                )
                if not ok:
                    fail("Store aplikace", msg)
                    return
            if flatpaks:
                ok, msg = run_privileged(
                    "flatpak-store-upgrade", {"app_ids": flatpaks}, 1800
                )
                if not ok:
                    fail("Store aplikace", msg)
                    return
            if packages or flatpaks:
                self.apps = load_apps()

            # 3) Ubuntu packages. Refresh package metadata explicitly even
            # when no APT-based Store application was installed.
            self.set_operation("3/4 · Aktualizuji Ubuntu…", 65)
            ok, msg = run_privileged("apt-update", {}, 900)
            if not ok:
                fail("Ubuntu", msg)
                return
            ok, msg = run_privileged("apt-upgrade", {}, 1800)
            if not ok:
                fail("Ubuntu", msg)
                return
            self.update_count = count_updates()

            # 4) PiTV itself is last because success requires a UI restart.
            self.set_operation("4/4 · Aktualizuji PiTV…", 88)
            ok, msg = run_privileged("pitv-self-update", {}, 1800)
            if not ok:
                fail("PiTV", msg)
                return

            self.updates_busy = False
            self.finish_operation("Vše aktualizováno · restartuji PiTV UI", True, 5)
            self.show_toast("Vše aktualizováno · restartuji PiTV UI", 4)
            time.sleep(1)
            self.restart_ui_clean()

        threading.Thread(target=worker, daemon=True).start()

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

                run_privileged("apt-update", {}, 900)
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

    def restart_ui_clean(self):
        """Restart the complete supervised TV shell without rebooting Linux."""
        # PiTV is labwc's primary client (-S). Ending the main loop lets the
        # normal cleanup run, then labwc exits and systemd Restart=always
        # reconstructs compositor + launcher + optional Android runtime.
        # Server services remain untouched.
        self.running = False

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
                self.restart_ui_clean()
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
        packages = self._installed_store_apt_packages()
        flatpaks = self._installed_store_flatpak_ids()
        if not packages and not flatpaks:
            self.show_toast("Žádné Store aplikace k aktualizaci")
            return

        self.updates_busy = True
        self.set_operation("Aktualizuji Store aplikace…")
        self.show_toast("Aktualizuji Store aplikace…", 4)

        def worker():
            if packages:
                ok, msg = run_privileged(
                    "apt-store-upgrade", {"packages": packages}, 1800
                )
                if not ok:
                    self.updates_busy = False
                    self.finish_operation(msg, False)
                    self.show_toast(msg, 6)
                    return
            if flatpaks:
                ok, msg = run_privileged(
                    "flatpak-store-upgrade", {"app_ids": flatpaks}, 1800
                )
                if not ok:
                    self.updates_busy = False
                    self.finish_operation(msg, False)
                    self.show_toast(msg, 6)
                    return

            self.updates_busy = False
            self.apps = load_apps()
            self.finish_operation("Store aplikace aktualizovány", True)
            self.show_toast("Store aplikace aktualizovány", 5)

        threading.Thread(target=worker, daemon=True).start()

    def update_ubuntu_async(self):
        if self.updates_busy:
            return
        self.updates_busy = True
        self.set_operation("Aktualizuji Ubuntu…")
        self.show_toast("Aktualizuji Ubuntu balíčky…", 5)

        def worker():
            ok, msg = run_privileged("apt-upgrade", {}, 1800)
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
            ("Dostupné aktualizace", upd),
            ("Otevřít Aktualizace", "OK"),
        ]

    def draw_system(self):
        rows = self.system_items()
        self.system_selected = max(0, min(self.system_selected, max(0, len(rows)-1)))
        visible = 8
        start = max(0, min(self.system_selected-visible//2, max(0, len(rows)-visible)))
        self.draw_rows(
            "Systém", "Ubuntu Server / Raspberry Pi",
            rows[start:start+visible], self.system_selected-start,
            "Aktualizace systému běží na pozadí; server se sám nerestartuje",
            settings_index=9,
            info_lines=[
                "Zobrazuje stav Raspberry Pi a Ubuntu.",
                "Teplota, RAM, disk a kernel jsou pouze informace.",
                "Aktualizace systému lze spustit přímo z této nabídky.",
            ],
        )

    def draw_power(self):
        rows = [
            ("Restartovat Raspberry Pi", "Vyžaduje potvrzení"),
            ("Vypnout Raspberry Pi", "Vyžaduje potvrzení"),
        ]
        self.draw_rows(
            "Napájení", "PiTV i serverové služby",
            rows, self.sub_selected, "OK → potvrzení",
            settings_index=10,
            info_lines=[
                "Restartuje nebo vypne celé Raspberry Pi.",
                "Před provedením se vždy zobrazí potvrzení.",
                "Restart PiTV UI najdete v Aktualizacích/Systému.",
            ],
        )

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
        self.draw_rows(
            "O PiTV", "TV vrstva nad Ubuntu Serverem", rows, 99,
            "Homebridge, Tailscale a ostatní služby běží mimo PiTV",
            settings_index=11,
            info_lines=[
                "Verze a technický stav instalace PiTV.",
                "Serverové služby běží nezávisle na TV launcheru.",
                "Tyto údaje jsou pouze pro kontrolu a diagnostiku.",
            ],
        )

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
            label = self._fit_ui_text(self.toast, f, int(self.w*.78))
            surf = f.render(label, True, self.t["text"])
            pad_x, pad_y = 24, 14
            rect = pygame.Rect(0, 0, min(int(self.w*.86), surf.get_width()+pad_x*2),
                               surf.get_height()+pad_y*2)
            rect.midbottom = (self.w//2, self.h-int(self.h*.035))
            pygame.draw.rect(self.screen, self.t["panel2"], rect, border_radius=14)
            pygame.draw.rect(self.screen, self.t["border"], rect, 1, border_radius=14)
            self.screen.blit(surf, (rect.x+pad_x, rect.y+pad_y))
        elif self.toast:
            self.toast = ""

        if self.keyboard_active:
            self.draw_keyboard()
        if self.confirm_active:
            self.draw_confirm()
        if self.choice_active:
            self.draw_choice()

        # One global activity banner for the entire PiTV experience. Draw it
        # last so installs, updates and app launches remain visible on Home,
        # Store, Settings and above every modal overlay.
        self.draw_operation()

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

    def _android_key_worker(self):
        while True:
            code = self.android_key_queue.get()
            try:
                run_privileged("waydroid-keyevent", {"code": code}, 10)
            except Exception:
                pass
            finally:
                self.android_key_queue.task_done()

    def relay_to_external(self, key):
        if self.external_kind == "apk":
            code = self.ANDROID_KEYEVENTS.get(key)
            if code and shutil.which("waydroid"):
                try:
                    self.android_key_queue.put_nowait(code)
                except queue.Full:
                    # TV input must feel current. If an unhealthy Android
                    # runtime stopped consuming keys, discard one stale key
                    # rather than letting a long backlog replay later.
                    try:
                        self.android_key_queue.get_nowait()
                        self.android_key_queue.task_done()
                    except queue.Empty:
                        pass
                    try:
                        self.android_key_queue.put_nowait(code)
                    except queue.Full:
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

    def _desktop_size(self):
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return tuple(int(v) for v in sizes[0])
        except Exception:
            pass
        try:
            info = pygame.display.Info()
            if info.current_w and info.current_h:
                return (int(info.current_w), int(info.current_h))
        except Exception:
            pass
        return tuple(self.screen.get_size()) if hasattr(self, "screen") else (0, 0)

    def _repair_fullscreen(self, force=False):
        """Re-bind SDL fullscreen after HDMI/EDID disconnect/reconnect.

        SDL display mutation is main-thread only. Worker threads may request a
        repair, but the render loop performs the actual set_mode operation.
        """
        if threading.get_ident() != self._main_thread_id:
            self._fullscreen_repair_requested = True
            return False
        if os.environ.get("SDL_VIDEODRIVER", "").lower() == "dummy":
            return False
        if self.external_kind:
            return False

        now = time.monotonic()
        if force and now - self._last_fullscreen_repair_at < 1.5:
            return False

        desktop = self._desktop_size()
        current = tuple(self.screen.get_size())
        changed = desktop != self._last_desktop_size or current != desktop
        if not force and not changed:
            return False

        try:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            pygame.display.set_caption(f"{APP_NAME} {VERSION}")
            self.w, self.h = self.screen.get_size()
            self._last_desktop_size = self._desktop_size()
            self._last_fullscreen_repair_at = now
            return True
        except Exception:
            return False

    def _probe_display_geometry(self):
        if self.external_kind:
            return

        now = time.monotonic()
        requested = self._fullscreen_repair_requested
        if not requested and now - self._last_display_probe_at < 2.0:
            return

        self._last_display_probe_at = now
        self._fullscreen_repair_requested = False
        desktop = self._desktop_size()
        if (requested or desktop != self._last_desktop_size or
                tuple(self.screen.get_size()) != desktop):
            self._repair_fullscreen(force=True)

    def _task_key(self, app, kind=None):
        app = app or {}
        kind = kind or app.get("kind", "linux")
        if kind == "apk":
            # The OS runtime is shared, but each Android TV application is a
            # distinct task. This lets PiTV suspend/resume SmartTube and
            # another APK independently without reusing the wrong wrapper.
            package = str(app.get("package", "") or "").strip()
            return "android:" + (package or "ui")
        command = str(app.get("command", "") or "")
        name = str(app.get("name", "") or "").lower()
        if command.strip() == "kodi" or "pitv-kodi-addon" in command or "kodi" in name or "plex" in name:
            return "kodi"
        if "com.stremio.Stremio" in command or "stremio" in name:
            return "stremio"
        return "linux:" + (command or name or "app")

    def _workspace_for_app(self, app, kind=None):
        key = self._task_key(app, kind)
        if key == "kodi":
            return "Kodi"
        if key == "stremio":
            return "Stremio"
        if key.startswith("android:"):
            return "Android"
        return "Apps"

    WORKSPACE_KEYS = {
        "Apps": "F8",
        "PiTV": "F9",
        "Kodi": "F10",
        "Stremio": "F11",
        "Android": "F12",
    }

    def _switch_workspace(self, workspace):
        key = self.WORKSPACE_KEYS.get(workspace)
        if not key or not shutil.which("wtype"):
            return False
        try:
            subprocess.Popen(
                ["wtype", "-M", "logo", "-k", key, "-m", "logo"],
                env=build_gui_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    def _known_app_alive(self, task):
        app = task.get("app") or {}
        key = task.get("key") or self._task_key(app, task.get("kind"))
        proc = task.get("proc")
        if proc is not None and proc.poll() is None:
            return True
        if key == "kodi":
            try:
                return subprocess.run(
                    ["pgrep", "-u", "pitv", "-x", "kodi.bin"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode == 0
            except Exception:
                return False
        if key == "stremio":
            try:
                p = subprocess.run(
                    ["flatpak", "ps", "--columns=application"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=3, check=False,
                )
                return "com.stremio.Stremio" in (p.stdout or "")
            except Exception:
                return False
        if key.startswith("android:"):
            package = str(app.get("package", "") or "").strip()
            if package:
                try:
                    ok, _ = run_privileged(
                        "waydroid-app-running", {"package": package}, 8
                    )
                    return bool(ok)
                except Exception:
                    return False
            try:
                p = subprocess.run(
                    ["waydroid", "status"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=3, check=False,
                )
                return bool(re.search(
                    r"^Session:\s*RUNNING\s*$", p.stdout or "", re.M | re.I
                ))
            except Exception:
                return False
        return False

    def _set_linux_suspended(self, task, suspend):
        app = task.get("app") or {}
        proc = task.get("proc")
        sig = signal.SIGSTOP if suspend else signal.SIGCONT

        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except Exception:
                try:
                    os.kill(proc.pid, sig)
                except Exception:
                    pass

        # Kodi can re-parent kodi.bin outside the original wrapper/process
        # group. Suspend/continue the real player too, preserving playback
        # position without relying on a toggle-style Pause action.
        if task.get("key") == "kodi":
            flag = "-STOP" if suspend else "-CONT"
            for proc_name in ("kodi.bin", "kodi"):
                try:
                    subprocess.run(
                        ["pkill", flag, "-u", "pitv", "-x", proc_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=False,
                    )
                except Exception:
                    pass

    def _pause_android_media(self):
        # KEYCODE_MEDIA_PAUSE is pause-only (unlike PLAY_PAUSE), so a movie
        # that is already paused is never accidentally resumed when returning
        # to the PiTV launcher.
        def worker():
            run_privileged("waydroid-keyevent", {"code": "127"}, 10)
        threading.Thread(target=worker, daemon=True).start()

    def _register_external(self, proc, kind, app=None):
        self.external_proc = proc
        self.external_kind = kind
        self.external_app = dict(app or {})
        self.external_task_key = self._task_key(self.external_app, kind)
        self.external_started_at = time.monotonic()
        self._back_hold_triggered = False

    def _clear_external_state(self):
        self.external_proc = None
        self.external_kind = None
        self.external_app = None
        self.external_task_key = None
        self.external_started_at = 0.0
        self._pitv_focus_samples = 0
        self._relay_echo.clear()
        self._back_hold_triggered = False
        self._keyboard_back_down_at = 0.0

    def _consume_global_tv_action(self):
        """Apply compositor-level Home/long-Back without stealing app input."""
        try:
            action = GLOBAL_ACTION_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except Exception:
            return
        try:
            GLOBAL_ACTION_FILE.unlink()
        except OSError:
            pass

        if action == "home":
            if self.external_kind:
                self.suspend_external()
            else:
                self._return_to_launcher("Domů", refresh_cec=False)
        elif action == "close":
            if self.external_kind:
                self.stop_external()
            else:
                self._return_to_launcher("Domů", refresh_cec=False)
        elif action == "display":
            # HDMI/EDID recovery repaired the compositor output in place.
            # Rebind SDL immediately when PiTV is visible; when another app is
            # foreground, remember the request and repair PiTV on return.
            self._fullscreen_repair_requested = True
            if not self.external_kind:
                self._repair_fullscreen(force=True)

    def _refresh_cec_after_return(self):
        """Re-announce PiTV without changing ownership of remote input."""
        if (not self.cfg.get("cec_enabled", True) or
                not cec_available() or self._cec_refreshing):
            return
        # pitv-inputd is the only input owner. Returning Home only announces
        # the Raspberry Pi as the active HDMI source.
        threading.Thread(target=cec_active_source, daemon=True).start()

    def _return_to_launcher(self, message="PiTV", refresh_cec=True):
        """One deterministic path back to the visible PiTV workspace."""
        self.page = "home"
        self.sidebar_focus = False
        self.selected = 0
        self._switch_workspace("PiTV")
        self._repair_fullscreen(force=True)
        if refresh_cec:
            self._refresh_cec_after_return()
        if message:
            self.show_toast(message, 2.2)

    def suspend_external(self):
        """TV multitasking: pause/suspend the foreground app and show PiTV."""
        if not self.external_kind:
            return

        task = {
            "key": self.external_task_key or self._task_key(self.external_app, self.external_kind),
            "proc": self.external_proc,
            "kind": self.external_kind,
            "app": dict(self.external_app or {}),
            "workspace": self._workspace_for_app(self.external_app, self.external_kind),
            "suspended_at": time.monotonic(),
        }

        if task["kind"] == "apk":
            self._pause_android_media()
        else:
            self._set_linux_suspended(task, True)

        self.background_tasks[task["key"]] = task
        self._clear_external_state()
        self._return_to_launcher("Aplikace pozastavena • PiTV")

    def _resume_task(self, task, requested_app=None):
        if not task or not self._known_app_alive(task):
            if task:
                self.background_tasks.pop(task.get("key"), None)
            return False

        requested_app = dict(requested_app or task.get("app") or {})
        kind = task.get("kind")
        key = task.get("key")

        if kind == "apk":
            package = requested_app.get("package", "")
            if package:
                try:
                    subprocess.Popen(
                        ["waydroid", "app", "launch", package],
                        env=build_gui_env(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    task["app"] = requested_app
                except Exception:
                    pass
            # Do not send Play here. Returning to the app leaves media paused;
            # playback resumes only when the user explicitly presses Play.
        else:
            self._set_linux_suspended(task, False)

        self.background_tasks.pop(key, None)
        self.external_proc = task.get("proc")
        self.external_kind = kind
        self.external_app = dict(task.get("app") or requested_app)
        self.external_task_key = key
        self.external_started_at = time.monotonic()
        self._back_hold_triggered = False
        self._switch_workspace(task.get("workspace") or self._workspace_for_app(self.external_app, kind))
        self.show_toast("Pokračuji v aplikaci", 1.6)
        return True

    def _resume_existing_for_app(self, app, kind):
        key = self._task_key(app, kind)
        task = self.background_tasks.get(key)
        return self._resume_task(task, app) if task else False

    def _reap_background_tasks(self):
        dead = []
        for key, task in list(self.background_tasks.items()):
            if not self._known_app_alive(task):
                dead.append(key)
        for key in dead:
            self.background_tasks.pop(key, None)

    def _terminate_known_external(self, app, force=False):
        """Explicit close path for app management / recovery, not normal Back."""
        command = str((app or {}).get("command", "") or "")
        name = str((app or {}).get("name", "") or "").lower()

        if command.strip() == "kodi" or "pitv-kodi-addon" in command or "kodi" in name:
            sig = "-KILL" if force else "-TERM"
            for proc_name in ("kodi.bin", "kodi"):
                try:
                    subprocess.Popen(
                        ["pkill", sig, "-u", "pitv", "-x", proc_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass

        if "com.stremio.Stremio" in command:
            try:
                subprocess.Popen(
                    ["flatpak", "kill", "com.stremio.Stremio"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _recover_external_focus(self):
        # If labwc unexpectedly returned focus to PiTV while the launcher still
        # thinks an app owns the foreground, the marker is stale. Cleanly close
        # that runtime instead of leaving a hidden/frozen process behind.
        self.stop_external()

    def stop_external(self, force=False):
        """Close the foreground task and return immediately to the PiTV launcher.

        TV apps do not expose a consistent Quit action.  PiTV first asks the
        tracked process/runtime to stop gracefully, then escalates after a
        short grace period so a detached kodi.bin, Flatpak client or Waydroid
        session cannot keep the TV stuck behind the launcher.
        """
        proc = self.external_proc
        kind = self.external_kind
        app = dict(self.external_app or {})
        task_key = self.external_task_key or self._task_key(app, kind)
        task = {
            "key": task_key,
            "proc": proc,
            "kind": kind,
            "app": app,
        }
        try:
            pgid = os.getpgid(proc.pid) if proc and proc.poll() is None else None
        except Exception:
            pgid = None

        self._clear_external_state()
        if task_key:
            self.background_tasks.pop(task_key, None)

        # Reveal PiTV first. Cleanup continues off the render/input thread.
        # CEC is reopened immediately so the old TV remote never depends on
        # the foreground application's shutdown timing.
        self.set_operation("Ukončuji aplikaci…", 20)
        self._return_to_launcher("Ukončuji aplikaci…")

        def worker():
            sig = signal.SIGKILL if force else signal.SIGTERM
            if proc and proc.poll() is None:
                try:
                    if pgid is not None:
                        os.killpg(pgid, sig)
                    elif force:
                        proc.kill()
                    else:
                        proc.terminate()
                except Exception:
                    pass

            self._terminate_known_external(app, force=force)

            if kind == "apk":
                package = str(app.get("package", "") or "").strip()
                if package:
                    try:
                        run_privileged(
                            "waydroid-app-stop", {"package": package}, 15
                        )
                    except Exception:
                        pass

            # A wrapper can exit while the real application survives (Kodi was
            # observed re-parented to PID 1). Give normal shutdown a moment,
            # then terminate the actual known runtime as a deterministic exit.
            if not force:
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline:
                    if not self._known_app_alive(task):
                        break
                    time.sleep(0.15)

                if self._known_app_alive(task):
                    if pgid is not None:
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                        except Exception:
                            pass
                    self._terminate_known_external(app, force=True)

            if kind == "apk":
                # Android TV-style lifecycle: close only the selected app.
                # Cage/Waydroid stay prewarmed so the next app opens quickly.
                self.apps = load_apps()

            self.finish_operation("Aplikace ukončena • PiTV", True, 2.0)
            self.show_toast("Aplikace ukončena • PiTV", 2.0)

        threading.Thread(target=worker, daemon=True).start()

    def _check_global_back_hold(self):
        if not self.external_kind:
            self._back_hold_triggered = False
            self._keyboard_back_down_at = 0.0
            return

        held = 0.0
        if self._keyboard_back_down_at > 0:
            held = time.monotonic() - self._keyboard_back_down_at

        if held >= 3.0 and not self._back_hold_triggered:
            self._back_hold_triggered = True
            # Universal TV escape: most media apps have inconsistent or hidden
            # Quit actions. A deliberate 3-second Back hold must always close
            # the foreground runtime and reveal PiTV, without relying on Home.
            self.stop_external()

    def _android_ready_file(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        return Path(runtime) / "pitv-waydroid-app-ready"

    def _android_runtime_ready_file(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        return Path(runtime) / "pitv-waydroid-runtime-ready"

    def _android_runtime_ready(self):
        """Fast local proof that the systemd-owned warm client is alive."""
        try:
            raw = self._android_runtime_ready_file().read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            pid = int(raw)
            if pid <= 1:
                return False
            os.kill(pid, 0)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _clear_android_pending(self, proc=None):
        if proc is None or self.android_pending_proc is proc:
            self.android_pending_proc = None
            self.android_pending_package = ""
            self.android_pending_app = None

    def _watch_android_launch(self, proc, app, expected_package, name):
        """Keep PiTV visible until the requested Android app is actually ready."""
        ready_file = self._android_ready_file()

        def worker():
            started = time.monotonic()
            deadline = started + 95.0
            last_stage = ""
            while time.monotonic() < deadline:
                rc = proc.poll()
                if rc is not None:
                    self._clear_android_pending(proc)
                    detail = tail_text_file("/tmp/pitv-waydroid-launch.log")
                    self.finish_operation(
                        detail or f"{name}: Android se nespustil ({rc})",
                        False, 7.0,
                    )
                    self.show_toast(f"{name} se nepodařilo spustit", 5)
                    return

                elapsed = time.monotonic() - started
                runtime_ready = self._android_runtime_ready()
                stage = (
                    f"Startuji Android pro {name}…"
                    if not runtime_ready else f"Spouštím {name}…"
                )
                if elapsed > 12 and not runtime_ready:
                    stage = f"První start Androidu • {name}…"
                if stage != last_stage:
                    self.set_operation(
                        stage,
                        25 if not runtime_ready else 70,
                    )
                    last_stage = stage

                try:
                    marker = ready_file.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                except Exception:
                    marker = ""

                if marker == expected_package:
                    if self.android_pending_proc is not proc:
                        return
                    self._clear_android_pending(proc)
                    self._register_external(proc, "apk", app)
                    # Cage was mapped to Android with follow=no. Only now,
                    # after the requested package is alive, reveal it.
                    self._switch_workspace("Android")
                    self.finish_operation(f"{name} spuštěno", True, 2.0)
                    return
                time.sleep(0.15)

            self._clear_android_pending(proc)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            detail = tail_text_file("/tmp/pitv-waydroid-launch.log")
            self.finish_operation(
                detail or f"{name}: spuštění Androidu trvá příliš dlouho",
                False, 7.0,
            )
            self.show_toast(f"{name}: spuštění selhalo", 5)

        threading.Thread(target=worker, daemon=True).start()

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
                self._clear_external_state()
                self._return_to_launcher(
                    f"{name} ukončeno • PiTV" if rc == 0 else "PiTV"
                )
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
        if self._resume_existing_for_app(app, "linux"):
            return
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
                proc = subprocess.Popen(
                    ["/bin/bash", "-c", app["command"]],
                    env=env,
                    cwd=str(Path.home()),
                    start_new_session=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            self._register_external(proc, "linux", app)
            self.show_toast(f"Spouštím {name}")
            self._watch_launch(self.external_proc, name, "linux", str(log_path))
        except Exception as e:
            self.finish_operation(f"Nelze spustit: {e}", False, 5.0)
            self.show_toast(f"Nelze spustit: {e}", 4)

    def launch_apk(self, app):
        if self._resume_existing_for_app(app, "apk"):
            return
        if (self.android_pending_proc is not None and
                self.android_pending_proc.poll() is None):
            self.show_toast("Android aplikace se už připravuje…", 3)
            return
        if not self.legacy_android_migration_ready():
            return
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

            # Keep PiTV visible while Cage + Android boot on the hidden Android
            # workspace. The wrapper publishes a marker only after this exact
            # package is running.
            try:
                self._android_ready_file().unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass

            self.set_operation(f"Spouštím {name}…", 10)
            proc = subprocess.Popen(
                ["/usr/local/bin/pitv-waydroid-launch", package, apk_path],
                env=env,
                cwd=str(Path.home()),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.android_pending_proc = proc
            self.android_pending_package = package
            self.android_pending_app = dict(app)
            self.show_toast(f"Připravuji {name}…")
            self._watch_android_launch(proc, dict(app), package, name)
        except Exception as e:
            self._clear_android_pending()
            self.finish_operation(f"Waydroid: {e}", False, 5.0)
            self.show_toast(f"Waydroid: {e}", 5)

    def launch(self, app):
        if (self.android_pending_proc is not None and
                self.android_pending_proc.poll() is None):
            self.show_toast("Počkejte, Android aplikace se připravuje…", 3)
            return
        if app.get("kind") == "apk":
            self.launch_apk(app)
        else:
            self.launch_linux(app)

    def enter_settings_item(self):
        pages = ["appearance", "screensaver", "network", "audio", "cec",
                 "apps", "server_store", "android", "updates", "system", "power", "about"]
        self.settings_context = True
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
                self.store_return_settings_context = False
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
                self.settings_context = False
                self.page = "settings"
                self.settings_selected = 0

    def handle_key(self, key):
        # Modal input has priority.
        if self.choice_active:
            self.mark_activity()
            self.handle_choice_key(key)
            return
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

        # PiTV 1.5 does not own ordinary remote navigation. pitv-inputd emits
        # one Linux TV-remote device and labwc delivers it directly to whichever
        # surface is focused. This branch is only PiTV state bookkeeping plus
        # compatibility behavior for older installations.
        if self.external_kind:
            if key == pygame.K_HOME:
                self.suspend_external()
                return
            if key in (PITV_KEY_VOLUMEUP, pygame.K_KP_PLUS):
                self.run_cec_action(cec_volume_up); return
            if key in (PITV_KEY_VOLUMEDOWN, pygame.K_KP_MINUS):
                self.run_cec_action(cec_volume_down); return
            if key == PITV_KEY_MUTE:
                self.run_cec_action(cec_mute); return

            if system_input_managed():
                # In PiTV 1.5 this branch is not the app-input path. The
                # virtual Linux remote is delivered by labwc directly to the
                # focused Kodi/Stremio/Cage surface. If PiTV receives a key
                # while external state is still set, do not synthesize a
                # second key and create a focus/echo loop.
                return

            # Pre-1.5 compatibility only.
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
            self.page = "home"
            self.selected = 0
            self.show_toast("Domů", 1.2)
            return

        if key == pygame.K_ESCAPE:
            if self.page == "home":
                # At the root there is nowhere further back to go. Move focus
                # to the navigation rail so Back still produces a useful,
                # visible result on a TV remote.
                self.focus_sidebar("home")
                return
            if self.page == "store":
                self.page = self.store_return_page
                if self.store_return_page == "apps":
                    self.settings_context = bool(
                        self.store_return_settings_context
                    )
                    self.store_return_settings_context = False
                return
            if self.page == "server_store":
                if self.server_store_return_page == "settings":
                    self.settings_context = False
                self.page = self.server_store_return_page
                return
            if self.page == "settings":
                self.page = "home"
                self.selected = max(0, len(self.home_items())-1)
                return
            # Every Settings child returns one level to Settings.
            self.settings_context = False
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
            rows = self.appearance_rows()
            if key == pygame.K_UP:
                self.sub_selected = max(0, self.sub_selected-1)
            elif key == pygame.K_DOWN:
                self.sub_selected = min(len(rows)-1, self.sub_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.open_appearance_choice(self.sub_selected)
            elif key == pygame.K_LEFT:
                self.settings_context = False
                self.page = "settings"
                self.settings_selected = 0

        elif self.page == "screensaver":
            if key == pygame.K_UP:
                self.sub_selected = max(0, self.sub_selected-1)
            elif key == pygame.K_DOWN:
                self.sub_selected = min(5, self.sub_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.sub_selected == 5:
                    self.screensaver_preview = True
                    self.screensaver_stage = (
                        "clock" if self.cfg.get("screensaver_mode","clock") == "clock"
                        else "black"
                    )
                else:
                    self.open_screensaver_choice(self.sub_selected)
            elif key == pygame.K_LEFT:
                self.settings_context = False
                self.page = "settings"
                self.settings_selected = 1

        elif self.page == "network":
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 2
                else:
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
                    self.open_wifi_choice()
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
            elif key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 3
                else:
                    self.focus_sidebar("audio")
                return
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                action = items[self.audio_selected]["action"]
                if action == "port":
                    self.open_audio_port_choice()
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
            rows = self.cec_rows()
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 4
                else:
                    self.focus_sidebar("cec")
                return
            if key == pygame.K_UP:
                self.cec_selected = max(0, self.cec_selected-1)
            elif key == pygame.K_DOWN:
                self.cec_selected = min(len(rows)-1, self.cec_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.cec_selected < 2:
                    self.open_cec_choice(self.cec_selected)
                else:
                    self.run_cec_action(
                        self.CEC_ACTIONS[self.cec_selected-2][2]
                    )

        elif self.page == "apps":
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 5
                else:
                    self.focus_sidebar("apps")
                return
            items = self.app_items()
            self.apps_selected = min(self.apps_selected, max(0, len(items)-1))
            if key == pygame.K_UP:
                self.apps_selected = max(0, self.apps_selected-1)
            elif key == pygame.K_DOWN:
                self.apps_selected = min(len(items)-1, self.apps_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                item = items[self.apps_selected]
                kind = item.get("kind")
                if kind == "store":
                    self.store_return_settings_context = self.settings_context
                    self.settings_context = False
                    self.page = "store"
                    self.store_return_page = "apps"
                    self.store_selected = 0
                    self.refresh_store_async()
                elif kind == "visibility":
                    self.open_app_visibility_list()
                elif kind == "uninstall":
                    self.open_app_uninstall_list()
                elif kind == "refresh":
                    self.apps = load_apps()
                    self.apps_selected = min(
                        self.apps_selected, max(0, len(self.app_items())-1)
                    )
                    self.show_toast("Seznam aplikací obnoven")

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
            if self.settings_context:
                if key == pygame.K_LEFT:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 6
                elif key == pygame.K_UP:
                    self.server_store_selected = max(0, self.server_store_selected-1)
                elif key == pygame.K_DOWN:
                    self.server_store_selected = min(
                        max(0, len(items)-1), self.server_store_selected+1
                    )
                elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and items:
                    self.install_server_store_item(items[self.server_store_selected])
            else:
                cols = 2
                if key == pygame.K_LEFT:
                    if self.server_store_selected % cols == 0:
                        self.focus_sidebar("server_store")
                    else:
                        self.server_store_selected = max(0, self.server_store_selected-1)
                elif key == pygame.K_RIGHT:
                    self.server_store_selected = min(
                        max(0, len(items)-1), self.server_store_selected+1
                    )
                elif key == pygame.K_UP:
                    self.server_store_selected = max(0, self.server_store_selected-cols)
                elif key == pygame.K_DOWN:
                    self.server_store_selected = min(
                        max(0, len(items)-1), self.server_store_selected+cols
                    )
                elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and items:
                    self.install_server_store_item(items[self.server_store_selected])

        elif self.page == "android":
            rows = self.android_items()
            if not rows:
                self.android_selected = 0
                return
            self.android_selected = min(self.android_selected, len(rows)-1)
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 7
                else:
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
                    if not self.legacy_android_migration_ready():
                        return
                    try:
                        env = build_gui_env()
                        problem = gui_env_error(env)
                        if problem:
                            self.show_toast(f"Android UI: {problem}", 6)
                            return
                        proc = subprocess.Popen(
                            ["/usr/local/bin/pitv-waydroid-launch", "--full-ui"],
                            env=env,
                            cwd=str(Path.home()),
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self._register_external(
                            proc, "apk",
                            {"name": "Android UI", "kind": "apk", "package": ""},
                        )
                        self._switch_workspace("Android")
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
            self.updates_selected = min(self.updates_selected, len(rows)-1)
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 8
                else:
                    self.focus_sidebar("updates")
            elif key == pygame.K_UP:
                self.updates_selected = max(0, self.updates_selected-1)
            elif key == pygame.K_DOWN:
                self.updates_selected = min(len(rows)-1, self.updates_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.updates_selected == 0:
                    self.open_confirm(
                        "Aktualizovat vše",
                        "Aktualizovat Store, aplikace, Ubuntu i PiTV jedním krokem?",
                        self.update_all_async,
                    )
                elif self.updates_selected == 1:
                    self.check_updates_async()
                elif self.updates_selected == 2:
                    self.open_update_advanced_choice()
                elif self.updates_selected == 3:
                    self.open_confirm(
                        "Restartovat PiTV UI",
                        "Restartovat pouze TV rozhraní? Serverové služby poběží dál.",
                        self.restart_ui_clean,
                    )

        elif self.page == "system":
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 9
                else:
                    self.focus_sidebar("system")
                return
            rows = self.system_items()
            if key == pygame.K_UP:
                self.system_selected = max(0, self.system_selected-1)
            elif key == pygame.K_DOWN:
                self.system_selected = min(len(rows)-1, self.system_selected+1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.system_selected == 7:
                    self.page = "updates"
                    self.settings_context = True
                    self.updates_selected = 0

        elif self.page == "power":
            if key == pygame.K_LEFT:
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 10
                else:
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
                if self.settings_context:
                    self.settings_context = False
                    self.page = "settings"
                    self.settings_selected = 11
                else:
                    self.focus_sidebar("about")
                return

    def run(self):
        while self.running:
            self._consume_global_tv_action()
            for event in pygame.event.get():
                display_events = {
                    value for value in (
                        getattr(pygame, "WINDOWDISPLAYCHANGED", None),
                        getattr(pygame, "WINDOWSIZECHANGED", None),
                        getattr(pygame, "WINDOWRESTORED", None),
                        getattr(pygame, "VIDEORESIZE", None),
                    ) if value is not None
                }
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type in display_events:
                    self._repair_fullscreen(force=True)
                elif event.type == pygame.KEYUP:
                    key = normalize_input_key(event.key)
                    if key == pygame.K_ESCAPE:
                        self._keyboard_back_down_at = 0.0
                elif event.type == pygame.KEYDOWN:
                    # A USB keyboard is the guaranteed local fallback for TV
                    # remotes. Backspace behaves as Back/Escape, matching the
                    # on-screen keyboard legend and common media-center UX.
                    key = normalize_input_key(event.key)
                    # Under Wayland the hidden PiTV launcher cannot receive
                    # keyboard input while an external client really owns
                    # focus. If a system-routed TV key reaches PiTV while an
                    # external task is still marked foreground, the compositor
                    # has already returned focus to the launcher and that task
                    # marker is stale. Recover immediately instead of leaving
                    # a visible but non-rendering/frozen PiTV screen.
                    if self.external_kind and system_input_managed():
                        self._recover_external_focus()
                        self.handle_key(key)
                        continue
                    if (self.external_kind and key == pygame.K_ESCAPE and
                            self._keyboard_back_down_at <= 0):
                        self._keyboard_back_down_at = time.monotonic()
                    if self.external_kind == "linux" and self._consume_relay_echo(key):
                        # The synthetic key came back to PiTV, therefore the
                        # launcher owns keyboard focus again. Clear the stale
                        # external session and apply this physical key once.
                        self._recover_external_focus()
                        self.handle_key(key)
                        continue
                    self.handle_key(key)

            self._check_global_back_hold()
            self._reap_background_tasks()
            self._probe_display_geometry()

            if self.external_proc is not None and self.external_proc.poll() is not None:
                finished_kind = self.external_kind
                self._clear_external_state()
                self._return_to_launcher("Aplikace ukončena • PiTV")
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
        if (self.android_pending_proc is not None and
                self.android_pending_proc.poll() is None):
            try:
                os.killpg(os.getpgid(self.android_pending_proc.pid), signal.SIGTERM)
            except Exception:
                pass
        pygame.quit()


if __name__ == "__main__":
    try:
        current_user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        current_user = ""
    if current_user != "pitv" and os.environ.get("PITV_ALLOW_NON_KIOSK_USER") != "1":
        print(
            "PiTV GUI musí běžet jako uživatel pitv. "
            "Pro příkazy z SSH použij: sudo pitv-session-run <příkaz>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    PiTV().run()
