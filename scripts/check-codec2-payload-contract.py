#!/usr/bin/env python3
"""Check whether a staged payload contains the expected AVC/HEVC codec markers.

This is intentionally conservative: it scans file names and small text/XML
files only. Runtime dumpsys validation remains mandatory on the Pi.
"""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: check-codec2-payload-contract.py STAGE")
root=Path(sys.argv[1]).resolve()
need={"c2.v4l2.avc.decoder":False,"c2.ffmpeg.hevc.decoder":False}
for p in root.rglob("*"):
    if not p.is_file(): continue
    hay=str(p.relative_to(root))
    if p.suffix.lower() in {".xml",".txt",".conf",".rc",".prop",".env"}:
        try: hay+="\n"+p.read_text(errors="ignore")
        except OSError: pass
    for key in need:
        if key in hay: need[key]=True
missing=[k for k,v in need.items() if not v]
if missing: raise SystemExit("missing codec contract marker(s): "+", ".join(missing))
print("CODEC2_CONTRACT_OK=1")
