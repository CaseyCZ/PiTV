#!/usr/bin/env python3
"""Audit ELF DT_NEEDED closure against payload + target Android images."""
import os,re,shutil,subprocess,sys
from pathlib import Path
if len(sys.argv)<3:
    raise SystemExit("usage: audit-codec2-payload-deps.py PAYLOAD TARGET_ROOT [TARGET_ROOT...]")
payload=Path(sys.argv[1]).resolve(); targets=[Path(x).resolve() for x in sys.argv[2:]]
readelf=shutil.which("readelf")
if not readelf: raise SystemExit("readelf required")
def iself(p):
    try:
        s=subprocess.check_output([readelf,"-h",str(p)],stderr=subprocess.DEVNULL,text=True)
        return "ELF64" in s and "AArch64" in s
    except (subprocess.CalledProcessError,OSError): return False
def needed(p):
    try: s=subprocess.check_output([readelf,"-d",str(p)],stderr=subprocess.DEVNULL,text=True)
    except subprocess.CalledProcessError: return []
    return re.findall(r"\(NEEDED\).*?\[([^\]]+)\]",s)
index={}
def safe_tree(root):
    for raw in root.rglob("*"):
        if raw.is_symlink(): continue
        p=raw.resolve()
        try: p.relative_to(root)
        except ValueError: continue
        yield p
for root in [payload,*targets]:
    if not root.is_dir(): continue
    for p in safe_tree(root):
        if p.is_file() and iself(p): index.setdefault(p.name,[]).append(p)
bad=[]; checked=0
for p in safe_tree(payload):
    if not p.is_file(): continue
    try:
        hdr=subprocess.check_output([readelf,"-h",str(p)],stderr=subprocess.DEVNULL,text=True)
    except (subprocess.CalledProcessError,OSError): continue
    checked+=1
    if "ELF64" not in hdr or "AArch64" not in hdr:
        bad.append(f"BAD_ARCH {p.relative_to(payload)}"); continue
    for dep in needed(p):
        name=os.path.basename(dep)
        if "/" in dep: bad.append(f"ABSOLUTE_NEEDED {p.relative_to(payload)} -> {dep}")
        candidates=index.get(name,[])
        if not candidates: bad.append(f"MISSING {p.relative_to(payload)} -> {name}")
        elif len(candidates)>1:
            # Multiple copies are acceptable only when byte-identical.
            import hashlib
            hashes={hashlib.sha256(x.read_bytes()).hexdigest() for x in candidates}
            if len(hashes)>1: bad.append(f"AMBIGUOUS {p.relative_to(payload)} -> {name} ({len(candidates)} providers)")
print(f"AUDITED_ELF={checked}")
for x in bad: print(x)
if checked==0: raise SystemExit("payload contains no AArch64 ELF files")
if bad: raise SystemExit(10)
print("DEPENDENCY_CLOSURE=OK")
