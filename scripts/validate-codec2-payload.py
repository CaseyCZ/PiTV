#!/usr/bin/env python3
"""Validate an assembled minimal Codec2 payload before installation."""
import hashlib
import json
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: validate-codec2-payload.py PAYLOAD")
root = Path(sys.argv[1]).resolve()
manifest = root / "PITV-CODEC2-PAYLOAD.txt"
if not manifest.is_file():
    raise SystemExit("missing payload manifest")

files = []
seen = set()
for raw in manifest.read_text().splitlines():
    rel = raw.strip()
    if not rel:
        continue
    if rel.startswith("/") or rel in seen:
        raise SystemExit(f"invalid/duplicate manifest path: {rel}")
    seen.add(rel)
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise SystemExit(f"manifest escapes payload root: {rel}")
    if not p.is_file():
        raise SystemExit(f"missing payload file: {rel}")
    files.append(p)

if not files:
    raise SystemExit("empty payload")
sha = {}
for p in files:
    sha[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
(root / "PITV-CODEC2-SHA256.json").write_text(
    json.dumps(sha, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"VALIDATED_FILES={len(files)}")
