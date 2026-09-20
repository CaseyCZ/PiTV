#!/usr/bin/env python3
"""Static compatibility probe for candidate Android 13 ARM64 Codec2 prebuilts.

This is intentionally non-destructive. It never writes to Waydroid.
Usage:
  python3 scripts/probe-codec2-prebuilt.py ROOT [ELF ...]

ROOT is an extracted candidate payload/vendor tree. If ELF paths are omitted,
all ELF files under ROOT are inspected.
"""
import os, re, shutil, subprocess, sys
from pathlib import Path

if len(sys.argv) < 2:
    raise SystemExit("usage: probe-codec2-prebuilt.py ROOT [ELF ...]")
root=Path(sys.argv[1]).resolve()
if not root.is_dir():
    raise SystemExit(f"not a directory: {root}")
readelf=shutil.which("readelf")
if not readelf:
    raise SystemExit("readelf is required")

platform_allow={
"libc.so","libdl.so","libm.so","liblog.so","libbase.so","libutils.so",
"libcutils.so","libbinder.so","libhidlbase.so","libfmq.so","libhardware.so",
"libion.so","libsync.so","libui.so","libgui.so","libnativewindow.so",
"libmedia.so","libmedia_omx.so","libstagefright_foundation.so",
"libcodec2.so","libcodec2_vndk.so","libcodec2_hidl@1.0.so",
"libcodec2_soft_common.so","libbufferpool@2.0.so","libgralloctypes.so",
"libprocessgroup.so","libvndksupport.so","libz.so",
}
risky=re.compile(r"(gralloc|mapper|allocator|egl|gles|vulkan|camera|audio|wifi|bluetooth|rpi|bcm|vc4)",re.I)

def elf(p):
    try:
        o=subprocess.check_output([readelf,"-h",str(p)],stderr=subprocess.DEVNULL,text=True)
        return "AArch64" in o
    except subprocess.CalledProcessError:
        return False

def needed(p):
    out=subprocess.check_output([readelf,"-d",str(p)],stderr=subprocess.DEVNULL,text=True)
    return re.findall(r"\(NEEDED\).*?\[([^\]]+)\]",out)

files=[Path(x).resolve() for x in sys.argv[2:]]
if not files:
    files=[p for p in root.rglob("*") if p.is_file() and elf(p)]

byname={}
for p in root.rglob("*"):
    if p.is_file(): byname.setdefault(p.name,[]).append(p)

bad_arch=[]; missing={}; donor=[]; absolute=[]
for p in files:
    if not elf(p):
        bad_arch.append(str(p)); continue
    for n in needed(p):
        if "/" in n:
            absolute.append((str(p),n))
        base=os.path.basename(n)
        if base in platform_allow: continue
        if base in byname:
            if risky.search(base): donor.append((str(p),base))
        else:
            missing.setdefault(base,[]).append(str(p))

print(f"ELF_AARCH64={len(files)-len(bad_arch)}")
print(f"BAD_ARCH={len(bad_arch)}")
print(f"MISSING_NONPLATFORM={len(missing)}")
print(f"RISKY_DONOR_DEPS={len(donor)}")
print(f"ABSOLUTE_DT_NEEDED={len(absolute)}")
for k,v in sorted(missing.items()):
    print("MISSING",k,"<-",",".join(v))
for p,n in donor:
    print("RISKY",n,"<-",p)
for p,n in absolute:
    print("ABSOLUTE",n,"<-",p)

# Exit 10 means unsuitable for automatic transplant. Risky donor deps are
# intentionally fatal: recursively copying graphics/device HALs defeats the
# minimal-payload safety model.
if bad_arch or missing or donor or absolute:
    raise SystemExit(10)
