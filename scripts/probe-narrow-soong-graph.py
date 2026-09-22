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
bootstrap = tree / "out/soong/bootstrap.ninja"
ninja = tree / "prebuilts/build-tools/linux-x86/bin/ninja"
builder = tree / "out/host/linux-x86/bin/soong_build"
for p in (bootstrap, ninja, builder, module_list):
    if not p.exists():
        raise SystemExit(f"missing narrow Soong probe prerequisite: {p}")

# Ask Ninja for its fully expanded commands instead of duplicating AOSP's
# version-specific soong_build flags here.
proc = subprocess.run(
    [str(ninja), "-t", "commands", "-f", str(bootstrap)],
    cwd=tree, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
)
commands = [x.strip() for x in proc.stdout.splitlines() if "soong_build" in x]
if not commands:
    raise SystemExit("bootstrap.ninja did not expose a soong_build command")

# Prefer the normal build.ninja-producing invocation over docs/modulegraph modes.
candidates = [x for x in commands if " --module_graph_file " not in f" {x} " and " --soong_docs " not in f" {x} "]
command = candidates[-1] if candidates else commands[-1]
argv = shlex.split(command)
try:
    exe_i = next(i for i, x in enumerate(argv) if x.endswith("/soong_build") or x == "soong_build")
except StopIteration:
    raise SystemExit("could not identify soong_build executable")
argv = argv[exe_i:]

def replace_flag(flag: str, value: str) -> None:
    for i, item in enumerate(argv):
        if item == flag:
            if i + 1 >= len(argv):
                raise SystemExit(f"missing value after {flag}")
            argv[i + 1] = value
            return
        if item.startswith(flag + "="):
            argv[i] = flag + "=" + value
            return
    raise SystemExit(f"bootstrap soong_build command missing {flag}")

probe_out = tree / "out/soong/pitv-codec2.ninja"
replace_flag("-l", str(module_list))
replace_flag("-o", str(probe_out))

# Never let the probe overwrite normal Soong environment dependency tracking.
used = tree / "out/soong/pitv-codec2.environment.used"
replace_flag("--used_env", str(used))

print("CODEC2_NARROW_SOONG_EXEC=" + shlex.join(argv))
env = {"TOP": str(tree)}
result = subprocess.run(argv, cwd=tree, env=env)
if result.returncode:
    print(f"CODEC2_NARROW_SOONG_RC={result.returncode}")
    raise SystemExit(result.returncode)
if not probe_out.is_file() or probe_out.stat().st_size == 0:
    raise SystemExit("narrow Soong probe produced no ninja graph")
print(f"CODEC2_NARROW_SOONG_NINJA={probe_out}")
print("CODEC2_NARROW_SOONG_READY=1")
