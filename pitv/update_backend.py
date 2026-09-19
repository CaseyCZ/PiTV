#!/usr/bin/env python3
import re
import urllib.request

PITV_VERSION_URL = "https://raw.githubusercontent.com/CaseyCZ/PiTV/Master/pitv/pitv.py"


def remote_pitv_version():
    req = urllib.request.Request(
        PITV_VERSION_URL,
        headers={"User-Agent": "PiTV-Updater/1.3"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8", errors="replace")
    m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    return m.group(1) if m else ""


def version_tuple(value):
    nums = re.findall(r"\d+", str(value))
    return tuple(int(x) for x in nums[:4]) or (0,)


def is_newer(remote, current):
    return version_tuple(remote) > version_tuple(current)
