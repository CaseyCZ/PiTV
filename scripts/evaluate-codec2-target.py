#!/usr/bin/env python3
"""Compare target probe output with the minimum RPi4 Codec2 contract."""
import shlex,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: evaluate-codec2-target.py PROBE_ENV")
vals={}
for raw in Path(sys.argv[1]).read_text().splitlines():
    if "=" not in raw: continue
    k,v=raw.split("=",1)
    try: vals[k]=shlex.split(v)[0] if v else ""
    except ValueError: vals[k]=v
checks={
 "arm64_host": vals.get("ARCH") in {"arm64","aarch64"},
 "rpi4": "Raspberry Pi 4" in vals.get("MODEL",""),
 "android13": vals.get("ANDROID_ro_build_version_release")=="13",
 "video_nodes": "/dev/video" in vals.get("VIDEO_NODES",""),
 "media_nodes": "/dev/media" in vals.get("MEDIA_NODES",""),
 "android_video_nodes": "/dev/video" in vals.get("ANDROID_VIDEO_NODES",""),
 "android_media_nodes": "/dev/media" in vals.get("ANDROID_MEDIA_NODES",""),
}
for k,v in checks.items(): print(f"{k}={'yes' if v else 'no'}")
missing=[k for k,v in checks.items() if not v]
if missing: raise SystemExit("target prerequisites missing: "+", ".join(missing))
print("TARGET_PREREQUISITES_OK=1")
