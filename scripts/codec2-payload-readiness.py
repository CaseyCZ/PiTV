#!/usr/bin/env python3
"""Emit a concise readiness report for a prepared Codec2 payload."""
import json,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: codec2-payload-readiness.py PAYLOAD")
root=Path(sys.argv[1])
required={
 "manifest":"PITV-CODEC2-PAYLOAD.txt",
 "checksums":"PITV-CODEC2-SHA256.json",
 "inventory":"PITV-CODEC2-INVENTORY.json",
 "rollback":"PITV-CODEC2-ROLLBACK.json",
 "avc_xml":"vendor/etc/media_codecs_pitv_rpi4.xml",
 "hevc_xml":"vendor/etc/media_codecs_ffmpeg_c2.xml",
 "properties":"vendor/etc/pitv-codec2.prop",
 "backend_marker":"vendor/etc/pitv-hwdecode.env",
 "v4l2_seccomp_ext":"vendor/etc/seccomp_policy/codec2.vendor.ext.policy",
 "v4l2_seccomp_base":"vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-default-seccomp_policy",
 "ffmpeg_seccomp":"vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-ffmpeg.policy",
 "avc_service":"vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64",
 "hevc_service":"vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg",
}
state={k:(root/v).is_file() for k,v in required.items()}
for k,v in state.items(): print(f"{k}={'yes' if v else 'no'}")
missing=[k for k,v in state.items() if not v]
if missing: raise SystemExit("payload not ready: "+", ".join(missing))
inv=json.loads((root/required["inventory"]).read_text())
elfs=sum(1 for x in inv.get("files",[]) if x.get("kind")=="elf")
print(f"elf_files={elfs}")
if elfs<2: raise SystemExit("payload does not contain both codec service ELF binaries")
print("PAYLOAD_READY_FOR_TARGET_PREFLIGHT=1")
