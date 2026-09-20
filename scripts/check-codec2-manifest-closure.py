#!/usr/bin/env python3
"""Ensure payload manifest exactly describes payload-owned files."""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: check-codec2-manifest-closure.py PAYLOAD")
root=Path(sys.argv[1]).resolve(); mf=root/"PITV-CODEC2-PAYLOAD.txt"
listed={x.strip() for x in mf.read_text().splitlines() if x.strip()}
metadata={"PITV-CODEC2-PAYLOAD.txt","PITV-CODEC2-SHA256.json","PITV-CODEC2-INVENTORY.json","PITV-CODEC2-ROLLBACK.json","PITV-CODEC2-PREFLIGHT.json","PITV-CODEC2-BACKUP-PLAN.txt","PITV-CODEC2-INSTALL-PLAN.txt"}
actual={str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and str(p.relative_to(root)) not in metadata}
extra=actual-listed; missing=listed-actual
if extra: raise SystemExit("unmanifested payload files: "+", ".join(sorted(extra)))
if missing: raise SystemExit("manifest references missing files: "+", ".join(sorted(missing)))
print(f"MANIFEST_CLOSURE={len(listed)}")
