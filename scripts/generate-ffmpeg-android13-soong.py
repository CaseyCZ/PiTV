#!/usr/bin/env python3
"""Generate temporary Soong modules for the pinned Android 13 FFmpeg sources.

The upstream Android 13 Raspberry Vanilla FFmpeg trees are Android.mk-only.
PiTV's narrow Codec2 build cannot afford the global Kati/Soong graph, so this
script converts the *already resolved* Android 13 object inventory into small
local Android.bp files. The files are disposable build inputs, not upstream
source replacements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PINNED_FFMPEG = "92c47af5c1f739194355ca765779d5756b56669b"
PINNED_CODEC2 = "6a8cb149c8cc0190678b7371fb587a5ebcd6723f"
FFMPEG_LIBS = ("libavutil", "libswresample", "libswscale", "libavcodec")
TARGET_CONFIG_CFLAG = '-DTARGET_CONFIG="config-armv8-a.h"'

COMMON_CFLAGS = [
    "-DANDROID_SDK_VERSION=33",
    TARGET_CONFIG_CFLAG,
    "-DHAVE_AV_CONFIG_H",
    "-D_FILE_OFFSET_BITS=64",
    "-D_LARGEFILE_SOURCE",
    "-DPIC",
    "-O3",
    "-fno-math-errno",
    "-fno-signed-zeros",
    "-fomit-frame-pointer",
    "-fPIC",
    "-Wno-parentheses",
    "-Wno-switch",
    "-Wno-format-zero-length",
    "-Wno-pointer-sign",
    "-Wno-unused-const-variable",
    "-Wno-bool-operation",
    "-Wno-deprecated-declarations",
    "-Wno-unused-variable",
    "-Wno-unused-parameter",
    "-Wno-missing-field-initializers",
    "-Wno-incompatible-pointer-types-discards-qualifiers",
    "-Wno-sometimes-uninitialized",
    "-Wno-unneeded-internal-declaration",
    "-Wno-initializer-overrides",
    "-Wno-string-plus-int",
    "-Wno-absolute-value",
    "-Wno-constant-conversion",
    "-Wno-enum-conversion",
    "-Wno-unknown-attributes",
    "-Wno-inline-asm",
]

LIB_SHARED = {
    "libavutil": [],
    "libswresample": ["libavutil"],
    "libswscale": ["libavutil"],
    "libavcodec": [
        "libavutil",
        "libswresample",
        "libdav1d",
        "libdrm",
        "libudev",
        "libz",
    ],
}


def q(value: str) -> str:
    return json.dumps(value)


def bp_list(values: list[str], indent: int = 8) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}{q(v)}," for v in values)


def git_head(root: Path) -> str:
    import subprocess

    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode:
        raise SystemExit(f"cannot read git revision for {root}: {p.stderr}")
    return p.stdout.strip()


def write_ffmpeg_bp(root: Path, inventory: dict) -> Path:
    parts = [
        "// PITV GENERATED FILE - narrow Android 13 FFmpeg build only.\n",
        "cc_defaults {\n",
        '    name: "pitv_ffmpeg_android13_defaults",\n',
        "    vendor: true,\n",
        '    compile_multilib: "64",\n',
        "    local_include_dirs: [\n",
        '        ".",\n',
        '        "android/include",\n',
        "    ],\n",
        "    export_include_dirs: [\n",
        '        ".",\n',
        '        "android/include",\n',
        "    ],\n",
        "    cflags: [\n",
        bp_list(COMMON_CFLAGS),
        "\n    ],\n",
        "    asflags: [\n",
        '        "-DPIC",\n',
        '        "-fPIC",\n',
        f"        {q(TARGET_CONFIG_CFLAG)},\n",
        "    ],\n",
        "    ldflags: [\n",
        '        "-Wl,--no-fatal-warnings",\n',
        '        "-Wl,-Bsymbolic",\n',
        "    ],\n",
        '    c_std: "gnu99",\n',
        "}\n\n",
    ]

    libraries = inventory["libraries"]
    for name in FFMPEG_LIBS:
        entry = libraries[name]
        sources = list(entry["sources"])
        parts += [
            "cc_library_shared {\n",
            f"    name: {q(name)},\n",
            '    defaults: ["pitv_ffmpeg_android13_defaults"],\n',
            "    srcs: [\n",
            bp_list(sources),
            "\n    ],\n",
        ]
        shared = LIB_SHARED[name]
        if shared:
            parts += ["    shared_libs: [\n", bp_list(shared), "\n    ],\n"]
        parts += ["}\n\n"]

    path = root / "Android.bp"
    path.write_text("".join(parts))
    return path


def write_codec2_bp(root: Path) -> Path:
    service_sources = [
        "C2FFMPEGAudioDecodeComponent.cpp",
        "C2FFMPEGAudioDecodeInterface.cpp",
        "C2FFMPEGVideoDecodeComponent.cpp",
        "C2FFMPEGVideoDecodeInterface.cpp",
        "service.cpp",
    ]
    text = f'''// PITV GENERATED FILE - narrow Android 13 FFmpeg Codec2 build only.

cc_library_shared {{
    name: "libffmpeg_utils",
    vendor: true,
    compile_multilib: "64",
    srcs: [
        "ffmpeg_utils/ffmpeg_hwaccel.c",
        "ffmpeg_utils/ffmpeg_utils.cpp",
    ],
    export_include_dirs: ["ffmpeg_utils"],
    shared_libs: [
        "libavcodec",
        "libavutil",
        "libcutils",
        "liblog",
        "libstagefright_foundation",
        "libswresample",
        "libswscale",
        "libutils",
    ],
}}

cc_binary {{
    name: "android.hardware.media.c2@1.2-service-ffmpeg",
    vendor: true,
    compile_multilib: "64",
    relative_install_path: "hw",
    srcs: [
{bp_list(service_sources)}
    ],
    cflags: [{q(TARGET_CONFIG_CFLAG)}],
    shared_libs: [
        "android.hardware.media.c2@1.2",
        "libavcodec",
        "libavutil",
        "libavservices_minijail",
        "libbase",
        "libbinder",
        "libcodec2_hidl@1.2",
        "libcodec2_soft_common",
        "libcodec2_vndk",
        "libffmpeg_utils",
        "libhidlbase",
        "liblog",
        "libstagefright_foundation",
        "libswresample",
        "libswscale",
        "libutils",
    ],
    required: [
        "android.hardware.media.c2@1.2-ffmpeg.policy",
        "media_codecs_ffmpeg_c2.xml",
    ],
    init_rc: ["android.hardware.media.c2@1.2-service-ffmpeg.rc"],
    vintf_fragments: ["android.hardware.media.c2@1.2-service-ffmpeg.xml"],
}}

prebuilt_etc {{
    name: "android.hardware.media.c2@1.2-ffmpeg.policy",
    vendor: true,
    src: "seccomp_policy/android.hardware.media.c2@1.2-ffmpeg-arm64.policy",
    sub_dir: "seccomp_policy",
}}

prebuilt_etc {{
    name: "media_codecs_ffmpeg_c2.xml",
    vendor: true,
    src: "media_codecs_ffmpeg_c2.xml",
}}
'''
    path = root / "Android.bp"
    path.write_text(text)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ffmpeg", type=Path)
    ap.add_argument("ffmpeg_codec2", type=Path)
    ap.add_argument("inventory", type=Path)
    args = ap.parse_args()

    ffmpeg = args.ffmpeg.resolve()
    codec2 = args.ffmpeg_codec2.resolve()
    inventory = json.loads(args.inventory.read_text())

    if git_head(ffmpeg) != PINNED_FFMPEG:
        raise SystemExit("FFmpeg checkout is not the pinned Android 13 revision")
    if git_head(codec2) != PINNED_CODEC2:
        raise SystemExit("FFmpeg Codec2 checkout is not the pinned Android 13 revision")
    if inventory.get("ffmpeg_revision") != PINNED_FFMPEG:
        raise SystemExit("object inventory does not match the pinned FFmpeg revision")

    for name in FFMPEG_LIBS:
        if name not in inventory.get("libraries", {}):
            raise SystemExit(f"object inventory missing {name}")
        if not inventory["libraries"][name].get("sources"):
            raise SystemExit(f"object inventory has no sources for {name}")

    # libavformat is intentionally omitted. PiTV patches the two network-init
    # calls out of ffmpeg_utils for this local decoder-only service.
    ffmpeg_bp = write_ffmpeg_bp(ffmpeg, inventory)
    codec2_bp = write_codec2_bp(codec2)

    if "libavformat" in codec2_bp.read_text():
        raise SystemExit("generated Codec2 Soong module unexpectedly depends on libavformat")

    selected = sum(int(inventory["libraries"][name]["object_count"]) for name in FFMPEG_LIBS)
    removed = int(inventory["libraries"].get("libavformat", {}).get("object_count", 0))
    print(f"CODEC2_FFMPEG_SOONG_OBJECTS={selected}")
    print(f"CODEC2_FFMPEG_SOONG_AVFORMAT_OBJECTS_REMOVED={removed}")
    print(f"CODEC2_FFMPEG_SOONG_BP={ffmpeg_bp}")
    print(f"CODEC2_FFMPEG_CODEC2_SOONG_BP={codec2_bp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
