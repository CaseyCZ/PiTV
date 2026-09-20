#!/usr/bin/env python3
"""Validate exact staged AVC/HEVC Codec2 XML entries."""
import sys,xml.etree.ElementTree as ET
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: check-codec2-payload-contract.py STAGE")
root=Path(sys.argv[1]).resolve()
expected={
 "vendor/etc/media_codecs_pitv_rpi4.xml":("c2.v4l2.avc.decoder","video/avc"),
 "vendor/etc/media_codecs_ffmpeg_c2.xml":("c2.ffmpeg.hevc.decoder","video/hevc"),
}
for rel,pair in expected.items():
    raw=root/rel
    if raw.is_symlink() or not raw.is_file(): raise SystemExit(f"missing codec XML: {rel}")
    p=raw.resolve()
    try: p.relative_to(root)
    except ValueError: raise SystemExit(f"codec XML escapes stage: {rel}")
    try: x=ET.parse(p).getroot()
    except ET.ParseError as e: raise SystemExit(f"invalid codec XML {rel}: {e}")
    found={(n.get("name"),n.get("type")) for n in x.iter("MediaCodec")}
    if pair not in found: raise SystemExit(f"missing exact codec contract in {rel}: {pair[0]} {pair[1]}")
print("CODEC2_CONTRACT_OK=1")
