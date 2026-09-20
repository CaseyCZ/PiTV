#!/usr/bin/env python3
"""Create and validate rollback metadata for a future Codec2 overlay install.

This helper does not modify Android/Waydroid. It records exactly which target
paths a payload would replace so an installer can require backups first.
"""
import json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: make-codec2-rollback-manifest.py STAGE")
root=Path(sys.argv[1]).resolve()
manifest=root/"PITV-CODEC2-PAYLOAD.txt"
checks=root/"PITV-CODEC2-SHA256.json"
if not manifest.is_file() or not checks.is_file(): raise SystemExit("stage is not validated")
sha=json.loads(checks.read_text())
entries=[]
for rel in manifest.read_text().splitlines():
    rel=rel.strip()
    if not rel: continue
    if rel not in sha: raise SystemExit(f"checksum missing for {rel}")
    target="/"+rel if rel.startswith("vendor/") else "/vendor/"+rel
    entries.append({"payload":rel,"target":target,"sha256":sha[rel],"backup_required":True})
out=root/"PITV-CODEC2-ROLLBACK.json"
out.write_text(json.dumps({"version":1,"entries":entries},indent=2,sort_keys=True)+"\n")
print(f"ROLLBACK_ENTRIES={len(entries)}")
