#!/usr/bin/env python3
"""Validate exact init/VINTF metadata for both PiTV Codec2 services."""
import re,sys,xml.etree.ElementTree as ET
from pathlib import Path
if len(sys.argv)<2: raise SystemExit("usage: check-codec2-service-metadata.py PAYLOAD [TARGET_ROOT...]")
root=Path(sys.argv[1]).resolve()
services={
 "v4l2":("/vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2","@1.0::IComponentStore/default"),
 "ffmpeg":("/vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg","@1.2::IComponentStore/ffmpeg"),
}
rc_text="\n".join(p.read_text(errors="ignore") for p in root.rglob("*.rc"))
xmls=list(root.rglob("*.xml"))
for label,(path,fqname) in services.items():
    binary=root/path.removeprefix("/")
    if not binary.is_file(): raise SystemExit(f"service binary missing: {path}")
    if not re.search(r"^service\s+\S+\s+"+re.escape(path)+r"(?:\s|$)",rc_text,re.M):
        raise SystemExit(f"init metadata missing exact service path: {path}")
    ok=False
    for p in xmls:
        try:
            x=ET.parse(p).getroot()
        except ET.ParseError:
            continue
        for hal in x.iter("hal"):
            name=hal.findtext("name","").strip()
            fqs=[(n.text or "").strip() for n in hal.findall("fqname")]
            if name=="android.hardware.media.c2" and fqname in fqs: ok=True
    if not ok: raise SystemExit(f"VINTF metadata missing Codec2 instance: {label} {fqname}")
print("SERVICE_METADATA=v4l2,ffmpeg")
