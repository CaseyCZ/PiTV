#!/usr/bin/env python3
"""Validate the pinned minimal Codec2 source lock without network access."""
import json,re
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"android/waydroid-rpi4/minimal-codec2-sources.lock.json"
try: d=json.loads(p.read_text())
except Exception as e: raise SystemExit(f"invalid source lock: {e}")
if d.get("android")!=13 or d.get("arch")!="arm64": raise SystemExit("source lock must target Android 13 arm64")
if not d.get("verified_at") or not d.get("verified_note"): raise SystemExit("source lock verification metadata missing")
expected={
"v4l2_codec2":"https://github.com/raspberry-vanilla/android_external_v4l2_codec2.git",
"ffmpeg":"https://github.com/raspberry-vanilla/android_external_ffmpeg.git",
"ffmpeg_codec2":"https://github.com/raspberry-vanilla/android_external_ffmpeg_codec2.git",
"libudev_zero":"https://github.com/raspberry-vanilla/android_external_libudev-zero.git",
}
sources=d.get("sources")
if not isinstance(sources,list): raise SystemExit("sources must be a list")
seen=set()
for x in sources:
    if not isinstance(x,dict): raise SystemExit("invalid source entry")
    name=x.get("name")
    if name in seen: raise SystemExit(f"duplicate source: {name}")
    seen.add(name)
    if expected.get(name)!=x.get("url"): raise SystemExit(f"unexpected source URL: {name}")
    if not re.fullmatch(r"[0-9a-f]{40}",str(x.get("commit",""))): raise SystemExit(f"invalid commit: {name}")
    if not isinstance(x.get("branch"),str) or not x["branch"]: raise SystemExit(f"missing branch: {name}")
    for rel in x.get("license_files",[]):
        q=Path(rel)
        if q.is_absolute() or ".." in q.parts: raise SystemExit(f"unsafe license path: {name}/{rel}")
if seen!=set(expected): raise SystemExit("source set mismatch: "+",".join(sorted(seen)))
print("Codec2 source lock OK")
