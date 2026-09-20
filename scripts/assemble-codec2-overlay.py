#!/usr/bin/env python3
"""Add PiTV-owned Android 13 Codec2 configuration to a collected payload."""
import shutil,sys
from pathlib import Path
if len(sys.argv)!=3:
    raise SystemExit("usage: assemble-codec2-overlay.py PAYLOAD REPO_ROOT")
payload=Path(sys.argv[1]).resolve(); repo=Path(sys.argv[2]).resolve()
manifest=payload/"PITV-CODEC2-PAYLOAD.txt"
if not manifest.is_file(): raise SystemExit("missing collected payload manifest")
owned={
 "android/waydroid-rpi4/media_codecs.xml":"vendor/etc/media_codecs.xml",
 "android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml":"vendor/etc/media_codecs_ffmpeg_c2.xml",
 "android/waydroid-rpi4/codec2.vendor.ext.policy":"vendor/etc/seccomp_policy/codec2.vendor.ext.policy",
 "android/waydroid-rpi4/hwdecode.env":"vendor/etc/pitv-hwdecode.env",
}
lines=[x for x in manifest.read_text().splitlines() if x.strip()]
for source,rel in owned.items():
    src=repo/source
    if not src.is_file(): raise SystemExit(f"missing PiTV config: {source}")
    dst=payload/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    if rel not in lines: lines.append(rel)
manifest.write_text("\n".join(sorted(set(lines)))+"\n",encoding="utf-8")
print(f"OVERLAY_FILES={len(set(lines))}")
