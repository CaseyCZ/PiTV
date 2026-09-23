#!/usr/bin/env python3
"""Run a disposable Soong graph probe with a reduced Android.bp module list.

When Soong reports a missing module, expand the list by the exact provider
Android.bp and retry in the same runner. This keeps the graph narrow without
paying for a fresh repo sync for every dependency-discovery step.
"""
import os
import re
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
full_list = tree / "out/.module_paths/Android.bp.list"
for p in (builder, available, product_vars, module_list, full_list):
    if not p.exists():
        raise SystemExit(f"missing narrow Soong probe prerequisite: {p}")

probe_out = tree / "out/soong/pitv-codec2.ninja"
used = tree / "out/soong/pitv-codec2.environment.used"
glob_file = tree / "out/soong/pitv-codec2-build-globs.ninja"
glob_dir = tree / "out/soong/.pitv-codec2-globs"

forbidden_prefixes = (
    "cts/",
    "external/skia/",
    "hardware/interfaces/automotive/",
    "hardware/interfaces/neuralnetworks/",
    "hardware/interfaces/graphics/common/aidl/",
    "hardware/interfaces/common/aidl/",
    "packages/modules/NeuralNetworks/",
    "frameworks/native/services/surfaceflinger/Tracing/",
)
forbidden_parts = (
    "/test/",
    "/tests/",
    "/vts/",
)

def allowed(rel: str) -> bool:
    return (
        not rel.startswith(forbidden_prefixes)
        and not any(part in rel for part in forbidden_parts)
    )

all_bp = [x.strip() for x in full_list.read_text().splitlines() if x.strip()]
selected = {x.strip() for x in module_list.read_text().splitlines() if x.strip()}
initial_selected = set(selected)

# Index literal module/default/interface names once. AOSP Blueprint module names
# are normally declared as name: "..."; generated AIDL variants are handled by
# mapping their generated suffix back to the aidl_interface base name.
name_re = re.compile(r'\bname\s*:\s*"([^"]+)"')
providers = {}
for rel in all_bp:
    if not allowed(rel):
        continue
    p = tree / rel
    try:
        text = p.read_text(errors="ignore")
    except OSError:
        continue
    for name in name_re.findall(text):
        providers.setdefault(name, []).append(rel)

generated_aidl_re = re.compile(
    r"^(?P<base>.+)-V\d+-(?:ndk|ndk_platform|cpp|java|rust)(?:-source)?$"
)
ansi_re = re.compile(r"\x1b\[[0-9;]*m")
missing_re = re.compile(
    r'error:\s+([^:\n]+):\d+:\d+:\s+"[^"]+" depends on undefined module "([^"]+)"'
)
package_root_re = re.compile(
    r"error:\s+([^:\n]+):\d+:\d+:.*?Cannot find package root specification "
    r"for package root '([^']+)'"
)
aidl_import_re = re.compile(
    r"error:\s+([^:\n]+):\d+:\d+:.*?imports: Import does not exist: ([^\s]+)"
)

def common_prefix_score(a: str, b: str) -> int:
    ap = Path(a).parts[:-1]
    bp = Path(b).parts[:-1]
    score = 0
    for x, y in zip(ap, bp):
        if x != y:
            break
        score += 1
    return score

def provider_candidates(module: str):
    names = [module]
    m = generated_aidl_re.match(module)
    if m:
        names.append(m.group("base"))
    out = []
    seen = set()
    for name in names:
        for rel in providers.get(name, []):
            if rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out

def choose_provider(module: str, consumer: str):
    candidates = [x for x in provider_candidates(module) if x not in selected]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-common_prefix_score(consumer, x), len(Path(x).parts), x))
    return candidates[0]

def write_selected():
    module_list.write_text("\n".join(sorted(selected)) + "\n")

# Android 13 soong_build accepts the same direct arguments that soong_ui puts
# into bootstrap.ninja. Invoke it directly so the narrow probe never starts
# Ninja. The environment is intentionally empty except TOP: soong_build reads
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
env = {"TOP": str(tree)}
max_attempts = int(os.environ.get("PITV_CODEC2_NARROW_MAX_ATTEMPTS", "64"))

for attempt in range(1, max_attempts + 1):
    write_selected()
    print(f"CODEC2_NARROW_SOONG_ATTEMPT={attempt}")
    print("CODEC2_NARROW_SOONG_EXEC=" + shlex.join(argv))
    result = subprocess.run(
        argv,
        cwd=tree,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = result.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode == 0:
        if not probe_out.is_file() or probe_out.stat().st_size == 0:
            raise SystemExit("narrow Soong probe produced no graph")
        print(f"CODEC2_NARROW_SOONG_NINJA={probe_out}")
        print(f"CODEC2_NARROW_AUTO_ADDED={len(selected) - len(initial_selected)}")
        print("CODEC2_NARROW_SOONG_READY=1")
        raise SystemExit(0)

    clean_output = ansi_re.sub("", output)
    missing = []
    seen_missing = set()
    for consumer, module in missing_re.findall(clean_output):
        key = (consumer, module)
        if key not in seen_missing:
            seen_missing.add(key)
            missing.append(key)
    for consumer, package_root in package_root_re.findall(clean_output):
        key = (consumer, package_root)
        if key not in seen_missing:
            seen_missing.add(key)
            missing.append(key)
            print(
                f"CODEC2_NARROW_MISSING_PACKAGE_ROOT={package_root} "
                f"consumer={consumer}"
            )
    for consumer, aidl_import in aidl_import_re.findall(clean_output):
        key = (consumer, aidl_import)
        if key not in seen_missing:
            seen_missing.add(key)
            missing.append(key)
            print(
                f"CODEC2_NARROW_MISSING_AIDL_IMPORT={aidl_import} "
                f"consumer={consumer}"
            )
    if not missing:
        print(f"CODEC2_NARROW_SOONG_RC={result.returncode}")
        raise SystemExit(result.returncode)

    additions = []
    for consumer, module in missing:
        provider = choose_provider(module, consumer)
        if provider is None:
            candidates = provider_candidates(module)
            blocked = []
            for x in all_bp:
                p = tree / x
                if allowed(x) or not p.is_file():
                    continue
                try:
                    if module in p.read_text(errors="ignore"):
                        blocked.append(x)
                except OSError:
                    continue
            if blocked:
                print(f'CODEC2_NARROW_BLOCKED_MODULE={module} providers={",".join(blocked[:8])}')
            elif candidates:
                print(f'CODEC2_NARROW_PROVIDER_ALREADY_SELECTED={module} providers={",".join(candidates[:8])}')
            else:
                print(f'CODEC2_NARROW_PROVIDER_NOT_FOUND={module}')
            print(f"CODEC2_NARROW_SOONG_RC={result.returncode}")
            raise SystemExit(result.returncode)
        if provider not in additions:
            additions.append(provider)
            print(f'CODEC2_NARROW_ADD_PROVIDER module={module} consumer={consumer} provider={provider}')

    if not additions:
        print(f"CODEC2_NARROW_SOONG_RC={result.returncode}")
        raise SystemExit(result.returncode)
    selected.update(additions)
    print(f"CODEC2_NARROW_BP_SELECTED_NOW={len(selected)}")

print(f"CODEC2_NARROW_MAX_ATTEMPTS_REACHED={max_attempts}")
raise SystemExit(1)
