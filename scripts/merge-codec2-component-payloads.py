#!/usr/bin/env python3
"""Merge independently built AVC and HEVC Codec2 component payloads safely."""
import hashlib
import shutil
import sys
from pathlib import Path

if len(sys.argv) != 4:
    raise SystemExit("usage: merge-codec2-component-payloads.py AVC_PAYLOAD HEVC_PAYLOAD OUT")

avc = Path(sys.argv[1]).resolve()
hevc = Path(sys.argv[2]).resolve()
out = Path(sys.argv[3]).resolve()

for root, label in ((avc, "AVC"), (hevc, "HEVC")):
    if not root.is_dir():
        raise SystemExit(f"{label} payload directory missing: {root}")
if (out == Path("/") or out in (avc, hevc) or avc in out.parents or hevc in out.parents\n        or out in avc.parents or out in hevc.parents):\n    raise SystemExit("unsafe merged payload output path")

expected = {
    avc: "vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64",
    hevc: "vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg",
}
for root, rel in expected.items():
    p = root / rel
    if p.is_symlink() or not p.is_file():
        raise SystemExit(f"component payload missing expected service: {rel}")

def manifest_paths(root: Path):
    manifest = root / "PITV-CODEC2-PAYLOAD.txt"
    if not manifest.is_file():
        raise SystemExit(f"missing component manifest: {manifest}")
    seen = set()
    result = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        rel = raw.strip()
        if not rel:
            continue
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts or rel in seen:
            raise SystemExit(f"invalid/duplicate component path: {rel}")
        seen.add(rel)
        src = root / p
        if src.is_symlink() or not src.is_file():
            raise SystemExit(f"component manifest entry missing/not regular: {rel}")
        resolved = src.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise SystemExit(f"component path escapes payload: {rel}")
        result.append((rel, resolved))
    if not result:
        raise SystemExit(f"empty component manifest: {manifest}")
    return result

if out.exists():
    if out.is_symlink():
        raise SystemExit("refusing symlink merged output")
    shutil.rmtree(out)
out.mkdir(parents=True)

merged = {}
for root in (avc, hevc):
    for rel, src in manifest_paths(root):
        dst = out / rel
        if rel in merged:
            old = merged[rel]
            if hashlib.sha256(old.read_bytes()).digest() != hashlib.sha256(src.read_bytes()).digest():
                raise SystemExit(f"component payload conflict: {rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        merged[rel] = dst

manifest = out / "PITV-CODEC2-PAYLOAD.txt"
manifest.write_text("\n".join(sorted(merged)) + "\n", encoding="utf-8")
for rel in expected.values():
    if not (out / rel).is_file():
        raise SystemExit(f"merged payload lost required service: {rel}")
print(f"MERGED_CODEC2_FILES={len(merged)}")
print(f"MERGED_MANIFEST={manifest}")
