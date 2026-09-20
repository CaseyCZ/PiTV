#!/usr/bin/env python3
"""Reject payloads containing files outside the intended minimal Codec2 surface."""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: enforce-codec2-payload-scope.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
m=root/"PITV-CODEC2-PAYLOAD.txt"
if not m.is_file(): raise SystemExit("missing payload manifest")
allowed=(
 "vendor/bin/","vendor/lib64/","vendor/etc/",
)
for rel in m.read_text().splitlines():
    rel=rel.strip()
    if not rel: continue
    q=Path(rel)
    if q.is_absolute() or ".." in q.parts: raise SystemExit(f"unsafe payload path: {rel}")
    raw=root/q
    if raw.is_symlink(): raise SystemExit(f"payload path is a symlink: {rel}")
    try: raw.resolve().relative_to(root)
    except ValueError: raise SystemExit(f"payload path escapes root: {rel}")
    if not rel.startswith(allowed):
        raise SystemExit(f"payload path outside minimal vendor scope: {rel}")
    low=rel.lower()
    forbidden=("egl/","hw/gralloc","hw/mapper","hw/allocator","camera","audio","wifi","bluetooth")
    if any(x in low for x in forbidden):
        raise SystemExit(f"forbidden donor HAL surface in payload: {rel}")
print("PAYLOAD_SCOPE_OK=1")
