#!/usr/bin/env python3
"""Validate pinned source checkout contents required by the reduced build."""
import json,subprocess,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: verify-minimal-codec2-sources.py SOURCES")
root=Path(sys.argv[1]).resolve()
repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/"android/waydroid-rpi4/minimal-codec2-sources.lock.json").read_text())
required={
 "v4l2_codec2":["Android.bp","service/Android.bp","service/android.hardware.media.c2@1.0-service-v4l2-64.rc","service/android.hardware.media.c2@1.0-service-v4l2.xml"],
 "ffmpeg":["Android.bp"],
 "ffmpeg_codec2":["Android.mk","android.hardware.media.c2@1.2-service-ffmpeg.rc","android.hardware.media.c2@1.2-service-ffmpeg.xml","seccomp_policy/android.hardware.media.c2@1.2-ffmpeg-arm64.policy"],
 "libudev_zero":["Android.bp"],
}
for item in lock["sources"]:
    d=root/item["name"]
    if not d.is_dir(): raise SystemExit(f"missing source checkout: {item['name']}")
    head=d/".git"
    if not head.exists(): raise SystemExit(f"not a git checkout: {item['name']}")
    got=subprocess.check_output(["git","-C",str(d),"rev-parse","HEAD"],text=True).strip()
    if got!=item["commit"]: raise SystemExit(f"source commit mismatch: {item['name']} {got}")
    origin=subprocess.check_output(["git","-C",str(d),"remote","get-url","origin"],text=True).strip()
    if origin!=item["url"]: raise SystemExit(f"source origin mismatch: {item['name']} {origin}")
    dirty=subprocess.check_output(["git","-C",str(d),"status","--porcelain"],text=True)
    if dirty.strip(): raise SystemExit(f"source checkout is dirty: {item['name']}")
    for rel in required.get(item["name"],[]):
        if not (d/rel).is_file(): raise SystemExit(f"missing required source file: {item['name']}/{rel}")
    for rel in item.get("license_files",[]):
        if not (d/rel).is_file(): raise SystemExit(f"missing license: {item['name']}/{rel}")
print("MINIMAL_CODEC2_SOURCES_OK=1")
