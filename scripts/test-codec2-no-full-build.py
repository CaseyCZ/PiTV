#!/usr/bin/env python3
"""Self-tests for no-full-build Codec2 payload metadata helpers."""
import json,subprocess,sys,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
py=sys.executable
def run(*args,ok=True):
    p=subprocess.run(args,text=True,capture_output=True)
    if ok and p.returncode: raise AssertionError(p.stderr+p.stdout)
    if not ok and p.returncode==0: raise AssertionError("expected failure")
    return p
with tempfile.TemporaryDirectory() as td:
    root=Path(td)/"payload"; root.mkdir()
    (root/"vendor/lib64").mkdir(parents=True)
    (root/"vendor/lib64/libdemo.so").write_bytes(b"demo")
    (root/"PITV-CODEC2-PAYLOAD.txt").write_text("vendor/lib64/libdemo.so\n")
    run(py,str(repo/"scripts/validate-codec2-payload.py"),str(root))
    sums=json.loads((root/"PITV-CODEC2-SHA256.json").read_text())
    assert "vendor/lib64/libdemo.so" in sums
    run(py,str(repo/"scripts/make-codec2-rollback-manifest.py"),str(root))
    rb=json.loads((root/"PITV-CODEC2-ROLLBACK.json").read_text())
    assert rb["entries"][0]["target"]=="/vendor/lib64/libdemo.so"
    target=Path(td)/"target"; (target/"vendor/lib64").mkdir(parents=True)
    (target/"vendor/lib64/libdemo.so").write_bytes(b"old")
    run(py,str(repo/"scripts/preflight-codec2-overlay.py"),str(root),str(target))
    pf=json.loads((root/"PITV-CODEC2-PREFLIGHT.json").read_text())
    assert pf["entries"][0]["state"]=="replace"
    (root/"PITV-CODEC2-PAYLOAD.txt").write_text("../escape\n")
    run(py,str(repo/"scripts/validate-codec2-payload.py"),str(root),ok=False)
print("Codec2 metadata self-tests OK")
