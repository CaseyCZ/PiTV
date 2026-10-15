#!/usr/bin/env python3
"""Validate the exact HEVC-only runtime produced by the narrow FFmpeg build."""
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: check-ffmpeg-hevc-runtime-payload.py PAYLOAD")

root = Path(sys.argv[1]).resolve()
expected = {
    "vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg",
    "vendor/lib64/libavcodec.so",
    "vendor/lib64/libavutil.so",
    "vendor/lib64/libswresample.so",
    "vendor/lib64/libswscale.so",
    "vendor/lib64/libffmpeg_utils.so",
    "vendor/lib64/libudev.so",
    "vendor/lib64/libdrm.so",
    "vendor/lib64/libdav1d.so",
    "vendor/etc/media_codecs_ffmpeg_c2.xml",
    "vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy",
    "vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc",
    "vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml",
}

manifest = root / "PITV-CODEC2-PAYLOAD.txt"
if not manifest.is_file():
    raise SystemExit("missing PITV-CODEC2-PAYLOAD.txt")
listed = {x.strip() for x in manifest.read_text().splitlines() if x.strip()}
if listed != expected:
    missing = ", ".join(sorted(expected - listed)) or "none"
    extra = ", ".join(sorted(listed - expected)) or "none"
    raise SystemExit(f"unexpected HEVC payload file set; missing={missing}; extra={extra}")

for rel in sorted(expected):
    raw = root / rel
    if raw.is_symlink() or not raw.is_file():
        raise SystemExit(f"missing/unsafe HEVC payload file: {rel}")
    try:
        raw.resolve().relative_to(root)
    except ValueError:
        raise SystemExit(f"HEVC payload path escapes root: {rel}")

readelf = shutil.which("readelf")
if not readelf:
    raise SystemExit("readelf required")
elfs = [x for x in sorted(expected) if x.startswith("vendor/bin/") or x.startswith("vendor/lib64/")]
for rel in elfs:
    p = root / rel
    hdr = subprocess.check_output([readelf, "-h", str(p)], text=True, stderr=subprocess.STDOUT)
    if "ELF64" not in hdr or "AArch64" not in hdr:
        raise SystemExit(f"not ELF64/AArch64: {rel}")
    dyn = subprocess.check_output([readelf, "-d", str(p)], text=True, stderr=subprocess.STDOUT)
    for dep in re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dyn):
        if "/" in dep:
            raise SystemExit(f"absolute DT_NEEDED rejected: {rel} -> {dep}")

codec_xml = root / "vendor/etc/media_codecs_ffmpeg_c2.xml"
try:
    codec_root = ET.parse(codec_xml).getroot()
except ET.ParseError as exc:
    raise SystemExit(f"invalid HEVC codec XML: {exc}")
codecs = [(node.get("name"), node.get("type")) for node in codec_root.iter("MediaCodec")]
if codecs != [("c2.ffmpeg.hevc.decoder", "video/hevc")]:
    raise SystemExit(f"HEVC codec XML not exclusive: {codecs}")

service_path = "/vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg"
rc = (root / "vendor/etc/init/android.hardware.media.c2@1.2-service-ffmpeg.rc").read_text(errors="ignore")
if not re.search(r"^service\s+\S+\s+" + re.escape(service_path) + r"(?:\s|$)", rc, re.M):
    raise SystemExit("FFmpeg init rc missing exact service path")

try:
    vintf = ET.parse(root / "vendor/etc/vintf/manifest/android.hardware.media.c2@1.2-service-ffmpeg.xml").getroot()
except ET.ParseError as exc:
    raise SystemExit(f"invalid FFmpeg VINTF fragment: {exc}")
ok = False
for hal in vintf.iter("hal"):
    names = [(node.text or "").strip() for node in hal.findall("fqname")]
    if hal.findtext("name", "").strip() == "android.hardware.media.c2" and "@1.2::IComponentStore/ffmpeg" in names:
        ok = True
if not ok:
    raise SystemExit("FFmpeg VINTF instance missing")

policy = root / "vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy"
if policy.stat().st_size == 0:
    raise SystemExit("empty FFmpeg seccomp policy")

print(f"FFMPEG_HEVC_PAYLOAD_FILES={len(expected)}")
print(f"FFMPEG_HEVC_PAYLOAD_ELF={len(elfs)}")
print("FFMPEG_HEVC_PAYLOAD_OK=1")
