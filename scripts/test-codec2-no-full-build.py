#!/usr/bin/env python3
"""Self-tests for no-full-build Codec2 payload metadata helpers."""
import json, subprocess, sys, tempfile
from pathlib import Path
repo = Path(__file__).resolve().parents[1]
py = sys.executable

def run(*args, ok=True):
    p = subprocess.run(args, text=True, capture_output=True)
    if ok and p.returncode:
        raise AssertionError(p.stderr + p.stdout)
    if not ok and p.returncode == 0:
        raise AssertionError("expected failure")
    return p

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "payload"
    (root / "vendor/lib64").mkdir(parents=True)
    (root / "vendor/etc").mkdir(parents=True)
    (root / "vendor/lib64/libdemo.so").write_bytes(b"demo")
    (root / "vendor/etc/media_codecs.xml").write_text(
        '<MediaCodec name="c2.v4l2.avc.decoder"/><Include href="media_codecs_ffmpeg_c2.xml"/>'
    )
    (root / "vendor/etc/media_codecs_ffmpeg_c2.xml").write_text(
        '<MediaCodec name="c2.ffmpeg.hevc.decoder"/>'
    )
    manifest = [
        "vendor/lib64/libdemo.so",
        "vendor/etc/media_codecs.xml",
        "vendor/etc/media_codecs_ffmpeg_c2.xml",
    ]
    (root / "PITV-CODEC2-PAYLOAD.txt").write_text("\n".join(manifest) + "\n")
    run(py, str(repo / "scripts/validate-codec2-payload.py"), str(root))
    run(py, str(repo / "scripts/check-codec2-payload-contract.py"), str(root))
    sums = json.loads((root / "PITV-CODEC2-SHA256.json").read_text())
    assert "vendor/lib64/libdemo.so" in sums
    run(py, str(repo / "scripts/make-codec2-rollback-manifest.py"), str(root))

    target = Path(td) / "target"
    (target / "vendor/lib64").mkdir(parents=True)
    (target / "vendor/lib64/libdemo.so").write_bytes(b"old")
    run(py, str(repo / "scripts/preflight-codec2-overlay.py"), str(root), str(target))
    run(py, str(repo / "scripts/plan-codec2-backup.py"), str(root))
    bp = (root / "PITV-CODEC2-BACKUP-PLAN.txt").read_text()
    assert "BACKUP /vendor/lib64/libdemo.so sha256=" in bp

    (root / "vendor/lib64/libnew.so").write_bytes(b"new")
    manifest.append("vendor/lib64/libnew.so")
    (root / "PITV-CODEC2-PAYLOAD.txt").write_text("\n".join(manifest) + "\n")
    run(py, str(repo / "scripts/validate-codec2-payload.py"), str(root))
    run(py, str(repo / "scripts/make-codec2-rollback-manifest.py"), str(root))
    run(py, str(repo / "scripts/preflight-codec2-overlay.py"), str(root), str(target))
    run(py, str(repo / "scripts/plan-codec2-backup.py"), str(root))
    bp = (root / "PITV-CODEC2-BACKUP-PLAN.txt").read_text()
    assert "REMOVE_ON_ROLLBACK /vendor/lib64/libnew.so" in bp

    (root / "PITV-CODEC2-PAYLOAD.txt").write_text("../escape\n")
    run(py, str(repo / "scripts/validate-codec2-payload.py"), str(root), ok=False)

print("Codec2 metadata self-tests OK")
