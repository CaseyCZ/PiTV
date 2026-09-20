#!/usr/bin/env python3
"""Create deterministic backup instructions from a Codec2 preflight report."""
import json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: plan-codec2-backup.py STAGE")
stage=Path(sys.argv[1]).resolve()
p=stage/"PITV-CODEC2-PREFLIGHT.json"
if not p.is_file(): raise SystemExit("missing preflight report")
data=json.loads(p.read_text())
if data.get("version")!=1 or not isinstance(data.get("entries"),list): raise SystemExit("invalid preflight schema")
lines=["# Backup plan generated from preflight"]
seen=set()
for e in data.get("entries",[]):
    target=e["target"]
    if target in seen: raise SystemExit(f"duplicate preflight target: {target}")
    seen.add(target)
    if not target.startswith("/vendor/"): raise SystemExit(f"unsafe target: {target}")
    if e["state"]=="replace":
        if not e.get("old_sha256"): raise SystemExit(f"missing old checksum: {target}")
        lines.append(f"BACKUP {target} sha256={e['old_sha256']}")
    elif e["state"]=="new":
        lines.append(f"REMOVE_ON_ROLLBACK {target}")
    else:
        raise SystemExit(f"unknown preflight state: {e['state']}")
out=stage/"PITV-CODEC2-BACKUP-PLAN.txt"
out.write_text("\n".join(lines)+"\n")
print(f"BACKUP_PLAN_ENTRIES={len(lines)-1}")
