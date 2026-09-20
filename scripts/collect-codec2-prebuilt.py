#!/usr/bin/env python3
"""Create a minimal Codec2 payload from an extracted Android vendor tree.

Copies only explicitly selected roots plus their non-platform DT_NEEDED closure.
It refuses risky device/graphics HAL dependencies. No Waydroid files are changed.

Usage:
  python3 scripts/collect-codec2-prebuilt.py SOURCE OUT ROOT_ELF [ROOT_ELF ...]
"""
import os,re,shutil,subprocess,sys
from pathlib import Path

if len(sys.argv)<4: raise SystemExit("usage: collect-codec2-prebuilt.py SOURCE OUT ROOT_ELF...")
src=Path(sys.argv[1]).resolve(); out=Path(sys.argv[2]).resolve()
if not src.is_dir(): raise SystemExit("SOURCE must be an extracted vendor tree")
readelf=shutil.which("readelf")
if not readelf: raise SystemExit("readelf is required")
allow={"libc.so","libdl.so","libm.so","liblog.so","libbase.so","libutils.so","libcutils.so",
"libbinder.so","libhidlbase.so","libfmq.so","libhardware.so","libion.so","libsync.so","libui.so",
"libgui.so","libnativewindow.so","libmedia.so","libmedia_omx.so","libstagefright_foundation.so",
"libcodec2.so","libcodec2_vndk.so","libcodec2_hidl@1.0.so","libcodec2_hidl@1.2.so","libcodec2_soft_common.so",
"android.hardware.media.c2@1.0.so","android.hardware.media.c2@1.1.so","android.hardware.media.c2@1.2.so","libavservices_minijail.so",
"libbufferpool@2.0.so","libgralloctypes.so","libprocessgroup.so","libvndksupport.so","libz.so"}
risky=re.compile(r"(gralloc|mapper|allocator|egl|gles|vulkan|camera|audio|wifi|bluetooth|rpi|bcm|vc4)",re.I)

def aarch64_elf(p):
    try:
        s=subprocess.check_output([readelf,"-h",str(p)],stderr=subprocess.DEVNULL,text=True)
        return "ELF64" in s and "AArch64" in s
    except (subprocess.CalledProcessError,OSError):
        return False

index={}
for p in src.rglob("*"):
    if p.is_file() and aarch64_elf(p):
        index.setdefault(p.name,[]).append(p)

def needed(p):
    try: s=subprocess.check_output([readelf,"-d",str(p)],stderr=subprocess.DEVNULL,text=True)
    except subprocess.CalledProcessError: return []
    return re.findall(r"\(NEEDED\).*?\[([^\]]+)\]",s)

roots=[]
for x in sys.argv[3:]:
    p=(src/x).resolve() if not os.path.isabs(x) else Path(x).resolve()
    try: p.relative_to(src)
    except ValueError: raise SystemExit(f"root outside SOURCE: {p}")
    if not p.is_file(): raise SystemExit(f"missing root: {p}")
    if not aarch64_elf(p): raise SystemExit(f"root is not AArch64 ELF: {p}")
    roots.append(p)

queue=list(roots); chosen=set()
while queue:
    p=queue.pop(0)
    if p in chosen: continue
    chosen.add(p)
    for dep in needed(p):
        name=os.path.basename(dep)
        if name in allow: continue
        if risky.search(name): raise SystemExit(f"refusing risky donor dependency: {name} <- {p}")
        matches=index.get(name,[])
        if len(matches)!=1:
            raise SystemExit(f"dependency must resolve uniquely in donor tree: {name} ({len(matches)} matches)")
        queue.append(matches[0])

if out.exists(): shutil.rmtree(out)
for p in sorted(chosen):
    rel=p.relative_to(src)
    dest=out/rel; dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,dest)

manifest=out/"PITV-CODEC2-PAYLOAD.txt"
manifest.write_text("\n".join(str(p.relative_to(src)) for p in sorted(chosen))+"\n",encoding="utf-8")
print(f"PAYLOAD_FILES={len(chosen)}")
print(f"MANIFEST={manifest}")
