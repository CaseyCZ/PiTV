#!/usr/bin/env python3
"""Reject suspiciously large files/payloads in the minimal Codec2 experiment."""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: check-codec2-payload-size.py PAYLOAD")
root=Path(sys.argv[1]).resolve()
m=root/"PITV-CODEC2-PAYLOAD.txt"
MAX_FILE=128*1024*1024
MAX_TOTAL=512*1024*1024
total=0
for rel in m.read_text().splitlines():
    rel=rel.strip()
    if not rel: continue
    p=root/rel
    size=p.stat().st_size
    if size>MAX_FILE: raise SystemExit(f"payload file too large: {rel} ({size})")
    total+=size
if total>MAX_TOTAL: raise SystemExit(f"payload exceeds minimal size ceiling: {total}")
print(f"PAYLOAD_BYTES={total}")
