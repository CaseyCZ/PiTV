#!/usr/bin/env python3
"""Validate init/VINTF metadata references only files shipped by payload or target."""
import re,sys
from pathlib import Path
if len(sys.argv)<2: raise SystemExit("usage: check-codec2-service-metadata.py PAYLOAD [TARGET_ROOT...]")
root=Path(sys.argv[1]).resolve(); targets=[Path(x).resolve() for x in sys.argv[2:]]
available=set()
for base in [root,*targets]:
    if base.is_dir():
        available.update(p.name for p in base.rglob("*") if p.is_file())
service_names={"android.hardware.media.c2@1.0-service-v4l2","android.hardware.media.c2@1.2-service-ffmpeg"}
seen=set()
for p in root.rglob("*.rc"):
    text=p.read_text(errors="ignore")
    for name in service_names:
        if name in text:
            seen.add(name)
            m=re.search(r"^service\s+\S+\s+(/vendor/bin/\S+)",text,re.M)
            if m and Path(m.group(1)).name not in available:
                raise SystemExit(f"init service binary missing: {m.group(1)}")
for p in root.rglob("*.xml"):
    text=p.read_text(errors="ignore")
    for name in service_names:
        if name in text: seen.add(name)
missing=service_names-seen
if missing:
    raise SystemExit("missing Codec2 service metadata: "+", ".join(sorted(missing)))
print("SERVICE_METADATA="+",".join(sorted(seen)))
