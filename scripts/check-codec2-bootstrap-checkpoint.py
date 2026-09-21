#!/usr/bin/env python3
"""Reject a restored Soong bootstrap checkpoint with newer manifest inputs."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("usage: check-codec2-bootstrap-checkpoint.py ANDROID_TREE")

tree = Path(sys.argv[1]).resolve()
manifest = tree / "out/soong/bootstrap.ninja"
depfile = tree / "out/soong/bootstrap.ninja.d"
soong_build = tree / "out/host/linux-x86/bin/soong_build"

for path, label in (
    (manifest, "bootstrap manifest"),
    (depfile, "bootstrap depfile"),
    (soong_build, "soong_build"),
):
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"missing/unsafe {label}: {path}")

raw = depfile.read_text(encoding="utf-8")
logical = raw.replace("\\\n", " ")
if ":" not in logical:
    raise SystemExit("invalid bootstrap depfile")
_, dep_text = logical.split(":", 1)

try:
    deps = shlex.split(dep_text, posix=True)
except ValueError as exc:
    raise SystemExit(f"invalid bootstrap depfile quoting: {exc}") from exc

if not deps:
    raise SystemExit("bootstrap depfile contains no inputs")

manifest_mtime = manifest.stat().st_mtime_ns
newer: list[tuple[int, str]] = []
missing: list[str] = []

for rel in deps:
    rel = rel.strip()
    if not rel:
        continue
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SystemExit(f"unsafe bootstrap dependency path: {rel}")
    path = tree / candidate
    if path.is_symlink():
        raise SystemExit(f"bootstrap dependency is a symlink: {rel}")
    if not path.exists():
        missing.append(rel)
        continue
    delta = path.stat().st_mtime_ns - manifest_mtime
    if delta > 0:
        newer.append((delta, rel))

if missing:
    sample = ", ".join(missing[:5])
    raise SystemExit(f"bootstrap checkpoint dependencies missing ({len(missing)}): {sample}")

if newer:
    newer.sort(reverse=True)
    sample = ", ".join(f"{rel} (+{delta / 1_000_000_000:.3f}s)" for delta, rel in newer[:8])
    raise SystemExit(
        f"bootstrap checkpoint invalidated by newer inputs ({len(newer)}): {sample}"
    )

print(f"CODEC2_BOOTSTRAP_CHECKPOINT_REUSABLE=1 deps={len(deps)}")
