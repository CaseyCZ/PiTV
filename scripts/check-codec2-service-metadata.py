#!/usr/bin/env python3
"""Validate exact init/VINTF metadata for both PiTV Codec2 services."""
import re,sys
from pathlib import Path
if len(sys.argv)<2: raise SystemExit("usage: check-codec2-service-metadata.py PAYLOAD [TARGET_ROOT...]")
root=Path(sys.argv[1]).resolve()
services={
 "android.hardware.media.c2@1.0-service-v4l2":"/vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2",
 "android.hardware.media.c2@1.2-service-ffmpeg":"/vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg",
}
rc_text="\n".join(p.read_text(errors="ignore") for p in root.rglob("*.rc"))
xml_text="\n".join(p.read_text(errors="ignore") for p in root.rglob("*.xml"))
for name,path in services.items():
    binary=root/path.removeprefix("/")
    if not binary.is_file(): raise SystemExit(f"service binary missing: {path}")
    if not re.search(r"^service\s+\S+\s+"+re.escape(path)+r"(?:\s|$)",rc_text,re.M):
        raise SystemExit(f"init metadata missing exact service path: {path}")
    if name not in xml_text:
        raise SystemExit(f"VINTF metadata missing service: {name}")
print("SERVICE_METADATA="+",".join(sorted(services)))
