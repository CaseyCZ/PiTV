#!/usr/bin/env python3
"""Reject a restored Soong bootstrap checkpoint with newer manifest inputs."""

from __future__ import annotations

import os
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

normalize = os.environ.get("PITV_CODEC2_NORMALIZE_BOOTSTRAP_REUSE", "0") == "1"
source_epoch_ns = int(os.environ.get("PITV_CODEC2_SOURCE_EPOCH", "946684800")) * 1_000_000_000
ninja_log = tree / "out/.ninja_log"

resolved_deps: list[tuple[str, Path]] = []
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
    if path.is_symlink() and not path.exists():
        raise SystemExit(f"bootstrap dependency is a broken symlink: {rel}")
    if not path.exists():
        missing.append(rel)
        continue
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"cannot resolve bootstrap dependency: {rel}: {exc}") from exc
    try:
        resolved.relative_to(tree)
    except ValueError as exc:
        raise SystemExit(f"bootstrap dependency escapes tree: {rel} -> {resolved}") from exc
    resolved_deps.append((rel, path))

if missing:
    sample = ", ".join(missing[:5])
    raise SystemExit(f"bootstrap checkpoint dependencies missing ({len(missing)}): {sample}")

if normalize:
    for _rel, path in resolved_deps:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, source_epoch_ns))

    # bootstrap.ninja uses the prebuilt Go compiler/linker as implicit inputs
    # to many edges, but bootstrap.ninja.d does not list those tool binaries.
    # A fresh repo sync gives them a new checkout mtime, which makes every
    # restored Go archive look stale even when the source manifest is identical.
    go_toolchain = tree / "prebuilts/go/linux-x86"
    if go_toolchain.is_dir():
        normalized_tools = 0
        for path in go_toolchain.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            st = path.stat()
            os.utime(path, ns=(st.st_atime_ns, source_epoch_ns))
            normalized_tools += 1
        print(f"CODEC2_GO_TOOLCHAIN_MTIMES_NORMALIZED={normalized_tools}")

    if not ninja_log.is_file() or ninja_log.is_symlink():
        raise SystemExit(f"missing/unsafe ninja log: {ninja_log}")

    replayed = 0
    for line in ninja_log.read_text(encoding="utf-8", errors="strict").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 5:
            raise SystemExit("invalid ninja log row")
        try:
            recorded_mtime = int(fields[2])
        except ValueError as exc:
            raise SystemExit("invalid ninja log mtime") from exc
        output_rel = fields[3]
        output = Path(output_rel)
        if output.is_absolute() or ".." in output.parts:
            raise SystemExit(f"unsafe ninja log output path: {output_rel}")
        output_path = tree / output
        if not output_path.exists():
            raise SystemExit(f"ninja log output missing from checkpoint: {output_rel}")
        resolved_output = output_path.resolve(strict=True)
        try:
            resolved_output.relative_to(tree)
        except ValueError as exc:
            raise SystemExit(
                f"ninja log output escapes tree: {output_rel} -> {resolved_output}"
            ) from exc
        st = output_path.stat()
        os.utime(output_path, ns=(st.st_atime_ns, recorded_mtime))
        replayed += 1
    print(f"CODEC2_NINJA_MTIMES_REPLAYED={replayed}")

manifest_mtime = manifest.stat().st_mtime_ns
for rel, path in resolved_deps:
    delta = path.stat().st_mtime_ns - manifest_mtime
    if delta > 0:
        newer.append((delta, rel))

if newer:
    newer.sort(reverse=True)
    sample = ", ".join(f"{rel} (+{delta / 1_000_000_000:.3f}s)" for delta, rel in newer[:8])
    raise SystemExit(
        f"bootstrap checkpoint invalidated by newer inputs ({len(newer)}): {sample}"
    )

if normalize:
    checked_outputs = 0
    for line in ninja_log.read_text(encoding="utf-8", errors="strict").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        recorded_mtime = int(fields[2])
        output_path = tree / fields[3]
        actual_mtime = output_path.stat().st_mtime_ns
        if actual_mtime != recorded_mtime:
            raise SystemExit(
                f"ninja output mtime replay mismatch: {fields[3]} "
                f"expected={recorded_mtime} actual={actual_mtime}"
            )
        checked_outputs += 1
    print(f"CODEC2_NINJA_MTIMES_VERIFIED={checked_outputs}")

print(f"CODEC2_BOOTSTRAP_CHECKPOINT_REUSABLE=1 deps={len(deps)}")
