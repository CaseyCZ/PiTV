#!/usr/bin/env python3
"""Verify a staged Codec2 payload against its recorded SHA-256 manifest."""
import hashlib,json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: verify-staged-codec2-payload.py STAGE")
root=Path(sys.argv[1]).resolve()
m=root/"PITV-CODEC2-SHA256.json"
if not m.is_file(): raise SystemExit("missing checksum manifest")
data=json.loads(m.read_text())
for rel,want in data.items():
    q=Path(rel)
    if q.is_absolute() or ".." in q.parts: raise SystemExit(f"unsafe staged path: {rel}")
    raw=root/q
    if raw.is_symlink(): raise SystemExit(f"staged path is a symlink: {rel}")
    p=raw.resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit(f"path escapes stage: {rel}")
    if not p.is_file(): raise SystemExit(f"missing staged file: {rel}")
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got!=want: raise SystemExit(f"checksum mismatch: {rel}")
print(f"STAGE_OK={len(data)}")
