#!/usr/bin/env python3
"""Verify prepared payload metadata is internally consistent."""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: verify-codec2-metadata.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
sums=json.loads((root/"PITV-CODEC2-SHA256.json").read_text())
inv=json.loads((root/"PITV-CODEC2-INVENTORY.json").read_text())
rollback=json.loads((root/"PITV-CODEC2-ROLLBACK.json").read_text())
invmap={x["path"]:x for x in inv.get("files",[])}
rbmap={x["payload"]:x for x in rollback.get("entries",[])}
if set(sums)!=set(invmap) or set(sums)!=set(rbmap):
    raise SystemExit("metadata file sets differ")
for rel,want in sums.items():
    p=(root/rel).resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit(f"metadata path escapes payload: {rel}")
    if not p.is_file(): raise SystemExit(f"metadata references missing file: {rel}")
    if hashlib.sha256(p.read_bytes()).hexdigest()!=want: raise SystemExit(f"checksum drift: {rel}")
    if invmap[rel].get("sha256")!=want: raise SystemExit(f"inventory drift: {rel}")
    if rbmap[rel].get("sha256")!=want: raise SystemExit(f"rollback drift: {rel}")
print(f"METADATA_CONSISTENT={len(sums)}")
