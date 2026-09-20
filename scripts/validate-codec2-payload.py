#!/usr/bin/env python3
"""Validate an assembled minimal Codec2 payload before installation."""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: validate-codec2-payload.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
manifest=root/"PITV-CODEC2-PAYLOAD.txt"
if not manifest.is_file(): raise SystemExit("missing payload manifest")
files=[]\nseen=set()
for line in manifest.read_text().splitlines():
    if not line.strip(): continue
    p=(root/line).resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit("manifest escapes payload root")
    if not p.is_file(): raise SystemExit(f"missing payload file: {rel}")
    files.append(p)
if not files: raise SystemExit("empty payload")
sha={}
for p in files:
    sha[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
(root/"PITV-CODEC2-SHA256.json").write_text(json.dumps(sha,indent=2,sort_keys=True)+"\n")
print(f"VALIDATED_FILES={len(files)}")
