#!/usr/bin/env python3
"""Validate the pinned minimal Codec2 source lock without network access."""
import json,re,sys
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"android/waydroid-rpi4/minimal-codec2-sources.lock.json"
d=json.loads(p.read_text())
assert d["android"]==13 and d["arch"]=="arm64"
assert d.get("verified_at") and d.get("verified_note")
names=set()
for x in d["sources"]:
    assert x["name"] not in names; names.add(x["name"])
    assert x["url"].startswith("https://github.com/") and x["url"].endswith(".git")
    assert re.fullmatch(r"[0-9a-f]{40}",x["commit"])
assert {"v4l2_codec2","ffmpeg","ffmpeg_codec2","libudev_zero"} <= names
print("Codec2 source lock OK")
