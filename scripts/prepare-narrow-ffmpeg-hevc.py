#!/usr/bin/env python3
"""Prepare a disposable Android 13 tree for the narrow FFmpeg HEVC graph.

The runner is disposable, so source edits do not need to survive this script.
The normal PiTV branch sources remain untouched; only the synchronized Android
workspace and pinned temporary Codec2 checkouts are modified.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NATIVE_ONLY_BP = (
    "build/soong/cmd/soong_build/Android.bp",
    "frameworks/av/Android.bp",
    "hardware/interfaces/Android.bp",
    "hardware/interfaces/graphics/common/1.0/Android.bp",
    "hardware/interfaces/graphics/common/1.1/Android.bp",
    "hardware/interfaces/graphics/common/1.2/Android.bp",
    "hardware/interfaces/graphics/bufferqueue/1.0/Android.bp",
    "hardware/interfaces/graphics/bufferqueue/2.0/Android.bp",
    "hardware/interfaces/media/1.0/Android.bp",
    "system/libhidl/transport/base/1.0/Android.bp",
    "system/libhidl/transport/safe_union/1.0/Android.bp",
    "system/tools/hidl/build/Android.bp",
)

BASE_PREFIXES = (
    "frameworks/av/media/codec2/core/",
    "frameworks/av/media/codec2/vndk/",
    "frameworks/av/media/codec2/components/base/",
    "frameworks/av/media/codec2/hidl/1.0/utils/",
    "frameworks/av/media/codec2/hidl/1.1/utils/",
    "frameworks/av/media/codec2/hidl/1.2/utils/",
    "frameworks/av/media/codec2/hidl/plugin/Android.bp",
    "frameworks/av/media/codec2/hidl/services/Android.bp",
    "frameworks/av/media/codec2/sfplugin/utils/",
    "hardware/interfaces/graphics/bufferqueue/",
    "hardware/interfaces/graphics/common/",
    "hardware/interfaces/media/c2/",
    "system/hardware/interfaces/Android.bp",
)

EXCLUDED_PREFIXES = (
    "hardware/interfaces/automotive/",
    "hardware/interfaces/neuralnetworks/",
    "hardware/interfaces/graphics/common/aidl/",
    "hardware/interfaces/common/aidl/",
    "frameworks/native/services/surfaceflinger/Tracing/",
)
EXCLUDED_PARTS = ("/tests/", "/test/", "/vts/")


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True)


def replace_tree(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True)


def patch_codec2(codec2: Path) -> None:
    service = codec2 / "service.cpp"
    s = service.read_text()
    start = s.find("static const C2FFMPEGComponentInfo kFFMPEGVideoComponents[] = {")
    end = s.find("\n};", start)
    if start < 0 or end < 0:
        raise SystemExit("unexpected FFmpeg Codec2 video component table")
    end += 3
    table = '''static const C2FFMPEGComponentInfo kFFMPEGVideoComponents[] = {
    { "c2.ffmpeg.hevc.decoder"  , MEDIA_MIMETYPE_VIDEO_HEVC  , AV_CODEC_ID_HEVC },
};'''
    s = s[:start] + table + s[end:]
    old_audio = '''static const size_t kNumAudioComponents =
    (sizeof(kFFMPEGAudioComponents) / sizeof(kFFMPEGAudioComponents[0]));'''
    if old_audio not in s:
        raise SystemExit("unexpected FFmpeg Codec2 audio component count")
    s = s.replace(old_audio, "static const size_t kNumAudioComponents = 0;", 1)
    service.write_text(s)

    header = codec2 / "ffmpeg_utils" / "ffmpeg_utils.h"
    h = header.read_text()
    include = '#include "libavformat/avformat.h"\n'
    if h.count(include) != 1:
        raise SystemExit("unexpected libavformat include in ffmpeg_utils.h")
    header.write_text(h.replace(include, "", 1))

    impl = codec2 / "ffmpeg_utils" / "ffmpeg_utils.cpp"
    c = impl.read_text()
    for call in ("        avformat_network_init();\n", "        avformat_network_deinit();\n"):
        if c.count(call) != 1:
            raise SystemExit(f"unexpected FFmpeg network init call: {call.strip()}")
        c = c.replace(call, "", 1)
    if "avformat_" in c:
        raise SystemExit("ffmpeg_utils.cpp still references libavformat")
    impl.write_text(c)
    print("CODEC2_FFMPEG_AVFORMAT_REMOVED=1")
    print("CODEC2_FFMPEG_HEVC_ONLY=1")


def extract_top_level_block(text: str, marker: str) -> str:
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"missing block marker: {marker}")
    brace = text.find("{", start)
    depth = 0
    in_string = False
    escaped = False
    for i in range(brace, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise SystemExit(f"unterminated block: {marker}")


def reduce_android_bp(tree: Path) -> None:
    for rel in NATIVE_ONLY_BP:
        p = tree / rel
        if not p.is_file():
            raise SystemExit(f"missing narrow Android.bp input: {rel}")
        s = p.read_text()
        if rel == "build/soong/cmd/soong_build/Android.bp":
            if 'name: "soong_build"' not in s or "primaryBuilder: true" not in s:
                raise SystemExit("unexpected soong_build Android.bp structure")
            s = '''package {
    default_applicable_licenses: ["Android-Apache-2.0"],
}

blueprint_go_binary {
    name: "soong_build",
    primaryBuilder: true,
}
'''
        elif rel == "frameworks/av/Android.bp":
            marker = "\naidl_interface {"
            cut = s.find(marker)
            if cut < 0 or 'name: "frameworks_av_license"' not in s[:cut]:
                raise SystemExit("unexpected frameworks/av root structure")
            s = s[:cut].rstrip() + "\n"
        elif rel == "hardware/interfaces/Android.bp":
            marker = "\n// VTS tests"
            cut = s.find(marker)
            if cut < 0 or 'name: "android.hardware"' not in s[:cut] or 'name: "hidl_defaults"' not in s[:cut]:
                raise SystemExit("unexpected hardware/interfaces root structure")
            s = s[:cut].rstrip() + "\n"
        elif rel == "system/tools/hidl/build/Android.bp":
            bootstrap = s.find("\nbootstrap_go_package {")
            if bootstrap < 0:
                raise SystemExit("unexpected HIDL build Android.bp structure")
            metadata = extract_top_level_block(s, "hidl_interfaces_metadata {")
            s = s[:bootstrap].rstrip() + "\n\n" + metadata.strip() + "\n"
        else:
            if "gen_java: true," not in s:
                raise SystemExit(f"expected gen_java true in {rel}")
            s = s.replace("gen_java: true,", "gen_java: false,")
            s = s.replace("gen_java_constants: true,", "gen_java_constants: false,")
        p.write_text(s)
    print("CODEC2_FFMPEG_NARROW_NATIVE_ONLY_BP=1")


def make_module_list(tree: Path, out: Path) -> None:
    full = tree / "out" / ".module_paths" / "Android.bp.list"
    if not full.is_file():
        raise SystemExit("missing Soong Android.bp.list checkpoint")
    lines = [x.strip() for x in full.read_text().splitlines() if x.strip()]
    primary_builder = "build/soong/cmd/soong_build/Android.bp"
    hidl_tool = "system/tools/hidl/Android.bp"
    selected = {
        x
        for x in lines
        if (
            x == "Android.bp"
            or x == primary_builder
            or x == hidl_tool
            or x.startswith(BASE_PREFIXES)
        )
        and not x.startswith(EXCLUDED_PREFIXES)
        and not any(part in x for part in EXCLUDED_PARTS)
    }
    # These files are generated/copied after the warm bootstrap, so they are
    # intentionally absent from the checkpoint's full Android.bp list.
    explicit = (
        "external/ffmpeg/Android.bp",
        "external/ffmpeg_codec2/Android.bp",
        "external/libudev-zero/Android.bp",
    )
    for rel in explicit:
        if not (tree / rel).is_file():
            raise SystemExit(f"missing explicit FFmpeg narrow provider: {rel}")
        selected.add(rel)
    for rel in (primary_builder, hidl_tool):
        if rel not in selected:
            raise SystemExit(f"narrow FFmpeg list missing required root: {rel}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(selected)) + "\n")
    print(f"CODEC2_FFMPEG_NARROW_BP_TOTAL={len(lines)}")
    print(f"CODEC2_FFMPEG_NARROW_BP_SELECTED={len(selected)}")
    print(f"CODEC2_FFMPEG_NARROW_BP_LIST={out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", type=Path)
    ap.add_argument("sources", type=Path)
    ap.add_argument("module_list", type=Path)
    args = ap.parse_args()

    tree = args.tree.resolve()
    sources = args.sources.resolve()
    here = Path(__file__).resolve().parent
    for rel in ("build/envsetup.sh", "out/host/linux-x86/bin/soong_build"):
        if not (tree / rel).exists():
            raise SystemExit(f"missing Android narrow prerequisite: {rel}")
    for name in ("ffmpeg", "ffmpeg_codec2", "libudev_zero"):
        if not (sources / name).is_dir():
            raise SystemExit(f"missing pinned Codec2 source: {name}")

    patch_codec2(sources / "ffmpeg_codec2")
    with tempfile.TemporaryDirectory(prefix="pitv-ffmpeg-hevc-") as td:
        inventory = Path(td) / "ffmpeg-android13-objects.json"
        run(
            sys.executable,
            str(here / "probe-ffmpeg-android13-objects.py"),
            str(sources / "ffmpeg"),
            str(inventory),
        )
        run(
            sys.executable,
            str(here / "generate-ffmpeg-android13-soong.py"),
            str(sources / "ffmpeg"),
            str(sources / "ffmpeg_codec2"),
            str(inventory),
        )

    replace_tree(sources / "ffmpeg", tree / "external" / "ffmpeg")
    replace_tree(sources / "ffmpeg_codec2", tree / "external" / "ffmpeg_codec2")
    replace_tree(sources / "libudev_zero", tree / "external" / "libudev-zero")
    reduce_android_bp(tree)
    make_module_list(tree, args.module_list.resolve())
    print("CODEC2_FFMPEG_NARROW_TREE_READY=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
