#!/usr/bin/env python3
"""Create a machine-readable inventory of a minimal Codec2 payload."""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: inventory-codec2-payload.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
manifest=root/"PITV-CODEC2-PAYLOAD.txt"
if not manifest.is_file(): raise SystemExit("missing payload manifest")
entries=[]
for rel in manifest.read_text().splitlines():
    rel=rel.strip()
    if not rel: continue
    q=Path(rel)
    if q.is_absolute() or ".." in q.parts: raise SystemExit(f"unsafe inventory path: {rel}")
    raw=root/q
    if raw.is_symlink(): raise SystemExit(f"inventory symlink rejected: {rel}")
    p=raw.resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit(f"path escapes payload: {rel}")
    if not p.is_file(): raise SystemExit(f"missing payload file: {rel}")
    b=p.read_bytes()
    kind="elf" if b.startswith(b"\x7fELF") else ("xml" if p.suffix==".xml" else "data")
    entries.append({"path":rel,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"kind":kind})
out=root/"PITV-CODEC2-INVENTORY.json"
out.write_text(json.dumps({"version":1,"files":entries},indent=2,sort_keys=True)+"\n")
print(f"INVENTORY_FILES={len(entries)}")
