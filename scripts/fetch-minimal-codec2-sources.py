#!/usr/bin/env python3
"""Fetch only pinned external Codec2 sources, not an Android source tree."""
import json,subprocess,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: fetch-minimal-codec2-sources.py WORKDIR")
repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/"android/waydroid-rpi4/minimal-codec2-sources.lock.json").read_text())
out=Path(sys.argv[1]).resolve(); out.mkdir(parents=True,exist_ok=True)
for item in lock["sources"]:
    dst=out/item["name"]
    if not dst.exists():
        subprocess.run(["git","clone","--filter=blob:none","--no-checkout",item["url"],str(dst)],check=True)
    subprocess.run(["git","-C",str(dst),"fetch","--depth=1","origin",item["commit"]],check=True)
    subprocess.run(["git","-C",str(dst),"checkout","--detach",item["commit"]],check=True)
    got=subprocess.check_output(["git","-C",str(dst),"rev-parse","HEAD"],text=True).strip()
    if got!=item["commit"]: raise SystemExit(f"commit mismatch: {item['name']}")
    for rel in item.get("license_files",[]):
        if not (dst/rel).is_file(): raise SystemExit(f"missing license file {item['name']}/{rel}")
    print(f"{item['name']}={got}")
subprocess.run([sys.executable,str(repo/"scripts/verify-minimal-codec2-sources.py"),str(out)],check=True)
