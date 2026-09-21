#!/usr/bin/env python3
"""Validate PiTV codec XML contract before packaging."""
import sys,xml.etree.ElementTree as ET
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
main=repo/"android/waydroid-rpi4/media_codecs.xml"
hevc=repo/"android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml"
a=ET.parse(main).getroot(); h=ET.parse(hevc).getroot()
def codecs(root): return {(x.get("name"),x.get("type")) for x in root.iter("MediaCodec")}
ac=codecs(a); hc=codecs(h)
if ("c2.v4l2.avc.decoder","video/avc") not in ac: raise SystemExit("AVC Codec2 XML contract missing")
if ("c2.ffmpeg.hevc.decoder","video/hevc") not in hc: raise SystemExit("HEVC Codec2 XML contract missing")
if list(a.iter("Include")): raise SystemExit("AVC fragment must not include other codec registries")
if len(hc)!=1: raise SystemExit("FFmpeg fragment must advertise HEVC only")
print("CODEC_XML_CONTRACT_OK=1")
