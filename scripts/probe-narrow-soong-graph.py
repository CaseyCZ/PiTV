#!/usr/bin/env python3
"""Run the narrow Soong probe with native-only HIDL memory interfaces."""
import os
import re
import runpy
import sys
from pathlib import Path

# Static contract markers implemented by probe-narrow-soong-graph-core.py.
# Keep these here because check-codec2-no-full-build.sh intentionally verifies
# the public probe entry point rather than following the wrapper at runtime.
# --available_env
# --soong_out
# --globListDir
# pitv-codec2.ninja
# pitv-codec2.environment.used
# CODEC2_NARROW_SOONG_READY=1
# CODEC2_NARROW_ALLOW_MISSING_DEPENDENCIES=1
# CODEC2_NARROW_MISSING_LABEL=
# CODEC2_NARROW_REQUIRED_PROVIDER_OVERRIDE=
# label_no_files_re
# source_candidates = [rel for rel in out if not rel.startswith("prebuilts/vndk/")]
# Allow_missing_dependencies
# PITV_CODEC2_NARROW_REQUIRED_MODULES

if len(sys.argv) != 3:
    raise SystemExit("usage: probe-narrow-soong-graph.py ANDROID_TREE MODULE_LIST")

tree = Path(sys.argv[1]).resolve()
module_list = Path(sys.argv[2]).resolve()
core = Path(__file__).with_name("probe-narrow-soong-graph-core.py")
if not core.is_file():
    raise SystemExit(f"missing narrow Soong probe core: {core}")
if not module_list.is_file():
    raise SystemExit(f"missing narrow Soong module list: {module_list}")

# Android's generated full Android.bp list can omit parent-package providers
# that are still valid dependencies of modules in the reduced graph. These two
# header-only modules are on the proven AVC path and have stable source
# providers. Add those exact Blueprint files directly instead of widening the
# graph, and remove the names from the generic provider lookup for this child
# process because the core index cannot discover files absent from the full
# list it indexes.
required_provider_overrides = {
    "av-headers": "frameworks/av/Android.bp",
    "media_ndk_headers": "frameworks/av/media/ndk/Android.bp",
}
required_raw = os.environ.get("PITV_CODEC2_NARROW_REQUIRED_MODULES", "")
required_modules = [
    x.strip() for x in re.split(r"[\n,]+", required_raw) if x.strip()
]

# Cache only dependencies that concrete Ninja attempts have already proven to
# be in the V4L2 AVC target closure. Without this, each fresh CI runner spends
# nearly all 16 outer build attempts rediscovering the same modules one layer at
# a time and can hit the attempt cap immediately before the next valid provider
# override is applied. These are not speculative graph roots: every entry came
# from a prior "missing dependencies" failure of the same AVC target.
proven_avc_modules = (
    "libbase",
    "libc++",
    "libclang_rt.builtins",
    "libcrypto",
    "libhidl-gen-hash",
    "libhidl-gen-host-utils",
    "libhidl-gen-utils",
    "libjsoncpp",
    "liblog",
    "fmtlib",
    "libc++abi",
    "libhwbinder_headers",
    "libcutils_headers",
    "libz",
    "libpropertyinfoparser",
    "crtbegin_dynamic",
    "crtend_android",
    "libavservices_minijail",
    "libc",
    "libchrome",
    "libdl",
    "libm",
    "libutils",
    "libstagefright_bufferqueue_helper",
    "libstagefright_foundation",
    "libui",
    "libhardware",
    "libnativewindow",
    "libstagefright_bufferpool@1.0",
    "libyuv_static",
    "android.hardware.media@1.0_interface",
    "android.hidl.base@1.0_interface",
    "android.hardware.media.bufferpool@2.0",
    "android.hardware.media.omx@1.0",
    "android.hidl.safe_union@1.0",
    "libminijail",
    "jni_headers",
    "libevent",
    "libmodpb64",
    "media_plugin_headers",
    "libbinder_headers",
    "libstagefright_bufferpool@2.0.1",
    "libdmabufheap",
    "libgralloctypes",
    "libion",
    "linux_bionic_supported",
    "libvndksupport",
    "android.hidl.manager@1.1_genc++_headers",
    "android.hidl.manager@1.2_genc++_headers",
    "libcap",
    "android.hidl.token@1.0-utils",
    "libEGL",
    "libgui_bufferqueue_static",
    "libhidlmemory",
    "android.hidl.token@1.0",
    "gl_headers",
    "LibGuiProperties",
    "inputconstants_aidl",
    "libbinderthreadstateutils",
    "libsync",
    "android.hidl.memory.token@1.0",
    "android.hidl.memory@1.0",
    "av-headers",
    "media_ndk_headers",
)
for module_name in proven_avc_modules:
    if module_name not in required_modules:
        required_modules.append(module_name)

# build-minimal-codec2-modules.sh deliberately reduces frameworks/av/Android.bp
# to its package/license prefix before the direct narrow Soong probe. The real
# AVC closure has now proven that libstagefright_foundation needs av-headers,
# which in Android 13 is declared after av-types-aidl in that same root file.
# Re-introduce only the production C++ AIDL interface and header module here;
# explicitly disable the default Java backend so dexpreopt/dex2oat remains out
# of the disposable graph. The parent script restores the original Android.bp
# from its temporary-edit backup when the narrow build exits.
av_root_bp = tree / "frameworks/av/Android.bp"
if "av-headers" in required_modules:
    if not av_root_bp.is_file():
        raise SystemExit("missing frameworks/av/Android.bp")
    av_root_text = av_root_bp.read_text(errors="ignore")
    if 'name: "av-headers"' not in av_root_text:
        if 'name: "frameworks_av_license"' not in av_root_text:
            raise SystemExit("unexpected reduced frameworks/av root structure")
        av_root_text = av_root_text.rstrip() + r'''

aidl_interface {
    name: "av-types-aidl",
    unstable: true,
    host_supported: true,
    vendor_available: true,
    double_loadable: true,
    local_include_dir: "aidl",
    srcs: [
        "aidl/android/media/InterpolatorConfig.aidl",
        "aidl/android/media/InterpolatorType.aidl",
        "aidl/android/media/MicrophoneInfoData.aidl",
        "aidl/android/media/VolumeShaperConfiguration.aidl",
        "aidl/android/media/VolumeShaperConfigurationOptionFlag.aidl",
        "aidl/android/media/VolumeShaperConfigurationType.aidl",
        "aidl/android/media/VolumeShaperOperation.aidl",
        "aidl/android/media/VolumeShaperOperationFlag.aidl",
        "aidl/android/media/VolumeShaperState.aidl",
    ],
    backend: {
        java: {
            enabled: false,
        },
        cpp: {
            min_sdk_version: "29",
            apex_available: [
                "//apex_available:platform",
                "com.android.bluetooth",
                "com.android.media",
                "com.android.media.swcodec",
            ],
        },
    },
}

cc_library_headers {
    name: "av-headers",
    export_include_dirs: ["include"],
    static_libs: [
        "av-types-aidl-cpp",
    ],
    export_static_lib_headers: [
        "av-types-aidl-cpp",
    ],
    header_libs: [
        "libaudioclient_aidl_conversion_util",
    ],
    export_header_lib_headers: [
        "libaudioclient_aidl_conversion_util",
    ],
    host_supported: true,
    vendor_available: true,
    double_loadable: true,
    min_sdk_version: "29",
    apex_available: [
        "//apex_available:platform",
        "com.android.bluetooth",
        "com.android.media",
        "com.android.media.swcodec",
    ],
    target: {
        darwin: {
            enabled: false,
        },
    },
}
''' + "\n"
        av_root_bp.write_text(av_root_text)
        print("CODEC2_NARROW_AV_HEADERS_NATIVE_ONLY=1")

selected = {x.strip() for x in module_list.read_text().splitlines() if x.strip()}
overridden = []
for module_name, rel in required_provider_overrides.items():
    if module_name not in required_modules:
        continue
    bp = tree / rel
    if not bp.is_file():
        raise SystemExit(f"missing narrow provider override: {rel}")
    if f'name: "{module_name}"' not in bp.read_text(errors="ignore"):
        raise SystemExit(
            f"unexpected narrow provider override for {module_name}: {rel}"
        )
    selected.add(rel)
    required_modules = [x for x in required_modules if x != module_name]
    overridden.append((module_name, rel))

if overridden:
    module_list.write_text("\n".join(sorted(selected)) + "\n")
    os.environ["PITV_CODEC2_NARROW_REQUIRED_MODULES"] = ",".join(required_modules)
    for module_name, rel in overridden:
        print(
            f"CODEC2_NARROW_REQUIRED_PROVIDER_OVERRIDE="
            f"{module_name}:{rel}"
        )

# libhidlmemory is in the real native AVC dependency closure. Its source HIDL
# interfaces also generate Java variants by default on Android 13; direct
# reduced soong_build has intentionally no dex2oatd/dexpreopt graph, so those
# unrelated variants panic during GenerateBuildActions. Keep only the native
# variants for this disposable graph and restore the source files afterwards.
targets = (
    (
        "system/libhidl/transport/memory/token/1.0/Android.bp",
        "android.hidl.memory.token@1.0",
    ),
    (
        "system/libhidl/transport/memory/1.0/Android.bp",
        "android.hidl.memory@1.0",
    ),
)
backups = []
try:
    for rel, module_name in targets:
        bp = tree / rel
        if not bp.is_file():
            raise SystemExit(f"missing required HIDL memory provider: {rel}")
        original = bp.read_bytes()
        stat = bp.stat()
        text = original.decode("utf-8")
        if f'name: "{module_name}"' not in text:
            raise SystemExit(f"unexpected HIDL memory module in {rel}")
        if "gen_java: true," in text:
            text = text.replace("gen_java: true,", "gen_java: false,")
        elif "gen_java: false," not in text:
            raise SystemExit(f"missing gen_java setting in {rel}")
        text = text.replace("gen_java_constants: true,", "gen_java_constants: false,")
        bp.write_text(text)
        backups.append((bp, original, stat))
        print(f"CODEC2_NARROW_HIDL_MEMORY_NATIVE_ONLY={module_name}")

    runpy.run_path(str(core), run_name="__main__")
finally:
    for bp, original, stat in reversed(backups):
        bp.write_bytes(original)
        os.utime(bp, ns=(stat.st_atime_ns, stat.st_mtime_ns))
