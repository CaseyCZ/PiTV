#!/usr/bin/env python3
"""Validate pinned source checkout contents required by the reduced build."""
import json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: verify-minimal-codec2-sources.py SOURCES")
root=Path(sys.argv[1]).resolve()
repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/"android/waydroid-rpi4/minimal-codec2-sources.lock.json").read_text())
required={
 "v4l2_codec2":["Android.bp"],
 "ffmpeg":["Android.bp"],
 "ffmpeg_codec2":["Android.bp"],
 "libudev_zero":["Android.bp"],
}
for item in lock["sources"]:
    d=root/item["name"]
    if not d.is_dir(): raise SystemExit(f"missing source checkout: {item['name']}")
    head=d/".git"
    if not head.exists(): raise SystemExit(f"not a git checkout: {item['name']}")
    for rel in required.get(item["name"],[]):
        if not (d/rel).is_file(): raise SystemExit(f"missing build definition: {item['name']}/{rel}")
    for rel in item.get("license_files",[]):
        if not (d/rel).is_file(): raise SystemExit(f"missing license: {item['name']}/{rel}")
print("MINIMAL_CODEC2_SOURCES_OK=1")
