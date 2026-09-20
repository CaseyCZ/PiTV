#!/usr/bin/env python3
"""Append reused PiTV config files to a payload manifest deterministically."""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: register-pitv-codec2-config.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
manifest=root/"PITV-CODEC2-PAYLOAD.txt"
required=[
"vendor/etc/media_codecs_pitv_rpi4.xml",
"vendor/etc/media_codecs_ffmpeg_c2.xml",
"vendor/etc/pitv-codec2.prop",
"vendor/etc/pitv-hwdecode.env",
"vendor/etc/seccomp_policy/codec2.vendor.ext.policy",
]
items=[]
if manifest.exists(): items=[x.strip() for x in manifest.read_text().splitlines() if x.strip()]
for rel in required:
    if not (root/rel).is_file(): raise SystemExit(f"missing reused config: {rel}")
    if rel not in items: items.append(rel)
manifest.write_text("\n".join(sorted(set(items)))+"\n")
print(f"MANIFEST_FILES={len(set(items))}")
