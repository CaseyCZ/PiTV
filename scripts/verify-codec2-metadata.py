#!/usr/bin/env python3
"""Verify prepared payload metadata is internally consistent."""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: verify-codec2-metadata.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
sums=json.loads((root/"PITV-CODEC2-SHA256.json").read_text())
inv=json.loads((root/"PITV-CODEC2-INVENTORY.json").read_text())
rollback=json.loads((root/"PITV-CODEC2-ROLLBACK.json").read_text())
if inv.get("version")!=1 or rollback.get("version")!=1: raise SystemExit("unsupported metadata version")
files=inv.get("files",[]); entries=rollback.get("entries",[])
if len({x.get("path") for x in files})!=len(files): raise SystemExit("duplicate inventory metadata")
if len({x.get("payload") for x in entries})!=len(entries): raise SystemExit("duplicate rollback metadata")
invmap={x["path"]:x for x in files}
rbmap={x["payload"]:x for x in entries}
if set(sums)!=set(invmap) or set(sums)!=set(rbmap):
    raise SystemExit("metadata file sets differ")
for rel,want in sums.items():
    raw=root/rel
    if raw.is_symlink(): raise SystemExit(f"metadata path is a symlink: {rel}")
    p=raw.resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit(f"metadata path escapes payload: {rel}")
    if not p.is_file(): raise SystemExit(f"metadata references missing file: {rel}")
    if hashlib.sha256(p.read_bytes()).hexdigest()!=want: raise SystemExit(f"checksum drift: {rel}")
    if invmap[rel].get("sha256")!=want: raise SystemExit(f"inventory drift: {rel}")
    if rbmap[rel].get("sha256")!=want: raise SystemExit(f"rollback drift: {rel}")
print(f"METADATA_CONSISTENT={len(sums)}")
