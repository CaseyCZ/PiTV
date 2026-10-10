#!/usr/bin/env python3
"""Run the narrow Soong probe with native-only HIDL memory interfaces."""
import os
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
# label_no_files_re
# source_candidates = [rel for rel in out if not rel.startswith("prebuilts/vndk/")]
# Allow_missing_dependencies
# PITV_CODEC2_NARROW_REQUIRED_MODULES

if len(sys.argv) != 3:
    raise SystemExit("usage: probe-narrow-soong-graph.py ANDROID_TREE MODULE_LIST")

tree = Path(sys.argv[1]).resolve()
core = Path(__file__).with_name("probe-narrow-soong-graph-core.py")
if not core.is_file():
    raise SystemExit(f"missing narrow Soong probe core: {core}")

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
