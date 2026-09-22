#!/usr/bin/env python3
"""Run a disposable Soong graph probe with a reduced Android.bp module list."""
import os
import shlex
import subprocess
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: probe-narrow-soong-graph.py ANDROID_TREE MODULE_LIST")

tree = Path(sys.argv[1]).resolve()
module_list = Path(sys.argv[2]).resolve()
builder = tree / "out/host/linux-x86/bin/soong_build"
available = tree / "out/soong/soong.environment.available"
product_vars = tree / "out/soong/soong.variables"
for p in (builder, available, product_vars, module_list):
    if not p.exists():
        raise SystemExit(f"missing narrow Soong probe prerequisite: {p}")

probe_out = tree / "out/soong/pitv-codec2.ninja"
used = tree / "out/soong/pitv-codec2.environment.used"
glob_file = tree / "out/soong/pitv-codec2-build-globs.ninja"
glob_dir = tree / "out/soong/.pitv-codec2-globs"

# Android 13 soong_build accepts the same direct arguments that soong_ui puts
# into bootstrap.ninja.  Invoke it directly so the narrow probe never starts
# Ninja.  The environment is intentionally empty except TOP: soong_build reads
# tracked build variables from --available_env.
argv = [
    str(builder),
    "--top", str(tree),
    "--out", str(tree / "out"),
    "--soong_out", str(tree / "out/soong"),
    "-l", str(module_list),
    "-o", str(probe_out),
    "--available_env", str(available),
    "--used_env", str(used),
    "--globFile", str(glob_file),
    "--globListDir", str(glob_dir),
    "Android.bp",
]

print("CODEC2_NARROW_SOONG_EXEC=" + shlex.join(argv))
env = {"TOP": str(tree)}
result = subprocess.run(argv, cwd=tree, env=env)
if result.returncode:
    print(f"CODEC2_NARROW_SOONG_RC={result.returncode}")
    raise SystemExit(result.returncode)
if not probe_out.is_file() or probe_out.stat().st_size == 0:
    raise SystemExit("narrow Soong probe produced no graph")
print(f"CODEC2_NARROW_SOONG_NINJA={probe_out}")
print("CODEC2_NARROW_SOONG_READY=1")
