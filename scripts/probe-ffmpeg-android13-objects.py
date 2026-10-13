#!/usr/bin/env python3
"""Resolve the pinned Raspberry Vanilla Android 13 FFmpeg object graph.

This deliberately asks GNU Make to evaluate the exact Android 13 FFmpeg
configuration and library Makefiles instead of approximating their source lists.
The resulting JSON is the input for a future narrow Soong shim.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

PINNED_FFMPEG = "92c47af5c1f739194355ca765779d5756b56669b"
LIBRARIES = (
    "libavutil",
    "libswresample",
    "libswscale",
    "libavcodec",
    "libavformat",
)
REQUIRED_CONFIG = (
    "CONFIG_HEVC_DECODER=yes",
    "CONFIG_V4L2_REQUEST=yes",
    "CONFIG_LIBDRM=yes",
    "CONFIG_LIBUDEV=yes",
)
REQUIRED_AVCODEC_SOURCES = (
    "hevcdec.c",
    "v4l2_req_media.c",
    "v4l2_req_devscan.c",
)

MAKEFILE = r"""
FFMPEG_SRC := $(abspath $(FFMPEG_SRC))
SRC_PATH := $(FFMPEG_SRC)

OBJS :=
ARMV5TE-OBJS :=
ARMV6-OBJS :=
ARMV8-OBJS :=
VFP-OBJS :=
NEON-OBJS :=
ALTIVEC-OBJS :=
VSX-OBJS :=
RVV-OBJS :=
MMX-OBJS :=
X86ASM-OBJS :=

include $(FFMPEG_SRC)/android/config-armv8-a.mak
include $(FFMPEG_SRC)/$(LIB)/Makefile
-include $(FFMPEG_SRC)/$(LIB)/aarch64/Makefile
include $(FFMPEG_SRC)/ffbuild/arch.mak

FINAL_OBJS := $(sort $(OBJS) $(OBJS-yes))

dump:
	@printf '%s\n' 'NAME=$(NAME)'
	@printf '%s\n' 'FFLIBS=$($(NAME)_FFLIBS)'
	@printf '%s\n' 'OBJS=$(FINAL_OBJS)'
""".lstrip()


def run(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def resolve_source(root: Path, library: str, obj: str) -> str:
    if not obj.endswith(".o"):
        raise SystemExit(f"unexpected FFmpeg object name for {library}: {obj}")
    stem = obj[:-2]
    candidates: list[Path] = []
    for ext in (".c", ".S", ".s", ".asm"):
        candidates.extend(
            (
                root / library / f"{stem}{ext}",
                root / f"{stem}{ext}",
                root / "android" / "include" / library / f"{stem}{ext}",
            )
        )
    hits = [p for p in candidates if p.is_file()]
    if not hits:
        raise SystemExit(f"no source file found for {library}/{obj}")
    # A generated Android include may shadow a source with the same basename.
    # Prefer the library source when both exist, otherwise keep the first exact hit.
    hit = hits[0]
    return hit.relative_to(root).as_posix()


def evaluate_library(root: Path, makefile: Path, library: str) -> dict[str, object]:
    stdout = run(
        "make",
        "--no-print-directory",
        "-rR",
        "-f",
        str(makefile),
        "dump",
        f"FFMPEG_SRC={root}",
        f"LIB={library}",
        cwd=root,
    )
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if not values.get("NAME") or "OBJS" not in values:
        raise SystemExit(f"incomplete GNU Make probe for {library}: {stdout}")
    objects = sorted(set(values["OBJS"].split()))
    sources = [resolve_source(root, library, obj) for obj in objects]
    return {
        "name": values["NAME"],
        "fflibs": values.get("FFLIBS", "").split(),
        "object_count": len(objects),
        "objects": objects,
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ffmpeg", type=Path, help="pinned android_external_ffmpeg checkout")
    parser.add_argument("output", type=Path, help="JSON inventory output")
    args = parser.parse_args()

    root = args.ffmpeg.resolve()
    config = root / "android" / "config-armv8-a.mak"
    if not config.is_file():
        raise SystemExit(f"missing Android ARM64 FFmpeg config: {config}")

    head = run("git", "rev-parse", "HEAD", cwd=root)
    if head != PINNED_FFMPEG:
        raise SystemExit(f"unexpected FFmpeg revision: {head}; expected {PINNED_FFMPEG}")

    config_text = config.read_text()
    for marker in REQUIRED_CONFIG:
        if marker not in config_text.splitlines():
            raise SystemExit(f"pinned FFmpeg config lost required marker: {marker}")

    with tempfile.TemporaryDirectory(prefix="pitv-ffmpeg-probe-") as td:
        makefile = Path(td) / "probe.mk"
        makefile.write_text(MAKEFILE)
        libraries = {
            library: evaluate_library(root, makefile, library) for library in LIBRARIES
        }

    avcodec_sources = set(libraries["libavcodec"]["sources"])
    for basename in REQUIRED_AVCODEC_SOURCES:
        if not any(path.endswith("/" + basename) for path in avcodec_sources):
            raise SystemExit(f"libavcodec probe missing required hardware source: {basename}")

    inventory = {
        "schema": 1,
        "ffmpeg_revision": head,
        "android_config": "android/config-armv8-a.mak",
        "hardware_contract": {
            "codec": "HEVC",
            "decoder": True,
            "v4l2_request": True,
            "libdrm": True,
            "libudev": True,
        },
        "libraries": libraries,
        "total_objects": sum(int(v["object_count"]) for v in libraries.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")

    print(f"CODEC2_FFMPEG_REVISION={head}")
    for library in LIBRARIES:
        entry = libraries[library]
        print(
            f"CODEC2_FFMPEG_OBJECTS_{library.upper()}="
            f"{entry['object_count']} deps={','.join(entry['fflibs']) or '-'}"
        )
    print(f"CODEC2_FFMPEG_OBJECTS_TOTAL={inventory['total_objects']}")
    print("CODEC2_FFMPEG_HEVC_V4L2_REQUEST=1")
    print(f"CODEC2_FFMPEG_OBJECT_INVENTORY={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
