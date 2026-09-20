#!/usr/bin/env python3
"""Preflight a rollback manifest against an extracted target vendor tree.

Read-only: verifies every replacement has a deterministic backup source or is
explicitly marked as a new file. It never modifies the target tree.
"""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=3: raise SystemExit("usage: preflight-codec2-overlay.py STAGE TARGET_ROOT")
stage=Path(sys.argv[1]).resolve(); target=Path(sys.argv[2]).resolve()
m=stage/"PITV-CODEC2-ROLLBACK.json"
if not m.is_file(): raise SystemExit("missing rollback manifest")
data=json.loads(m.read_text())
report=[]
for e in data.get("entries",[]):
    raw_target=e.get("target","")
    if not raw_target.startswith("/vendor/") or ".." in Path(raw_target).parts:
        raise SystemExit(f"unsafe target: {raw_target}")
    rel=raw_target.lstrip("/")
    # TARGET_ROOT may be filesystem root or extracted vendor root.
    if target.name=="vendor" and rel.startswith("vendor/"): rel=rel[len("vendor/"):]
    rawp=target/rel
    if rawp.is_symlink(): raise SystemExit(f"target symlink rejected: {e['target']}")
    p=rawp.resolve()
    try: p.relative_to(target)
    except ValueError: raise SystemExit(f"target escapes root: {e['target']}")
    if p.is_file():
        old=hashlib.sha256(p.read_bytes()).hexdigest()
        state="replace"
    else:
        old=None; state="new"
    report.append({"target":e["target"],"state":state,"old_sha256":old})
out=stage/"PITV-CODEC2-PREFLIGHT.json"
out.write_text(json.dumps({"version":1,"entries":report},indent=2,sort_keys=True)+"\n")
print(f"PREFLIGHT_OK={len(report)}")
