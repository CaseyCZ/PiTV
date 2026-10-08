#!/usr/bin/env python3
"""Run a disposable Soong graph probe with a reduced Android.bp module list.

When Soong reports a missing module, expand the list by the exact provider
Android.bp and retry in the same runner. This keeps the graph narrow without
paying for a fresh repo sync for every dependency-discovery step.
"""
import atexit
import json
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

# The reduced list intentionally contains Android.bp files that also define
# unrelated tests/tools. Let Soong keep unresolved deps on those unused modules
# instead of recursively expanding the global graph. A concrete Ninja build of
# the V4L2 install target below will still fail on any dependency that is
# actually in the target's transitive closure.
_product_vars_original = product_vars.read_bytes()
_product_vars_stat = product_vars.stat()
_product_vars_json = json.loads(_product_vars_original.decode("utf-8"))
_product_vars_json["Allow_missing_dependencies"] = True
product_vars.write_text(json.dumps(_product_vars_json, indent=2, sort_keys=True) + "\n")

def _restore_product_vars():
    product_vars.write_bytes(_product_vars_original)
    os.utime(
        product_vars,
        ns=(_product_vars_stat.st_atime_ns, _product_vars_stat.st_mtime_ns),
    )

atexit.register(_restore_product_vars)
print("CODEC2_NARROW_ALLOW_MISSING_DEPENDENCIES=1")

# libhidlbase reaches the manager 1.0, 1.1 and 1.2 generated C++ headers on the
# concrete AVC path. Their Java variants invoke dexpreopt and pull dex2oat into
# this deliberately reduced graph. Keep all three source interfaces native-only
# while generating the narrow Ninja graph, then restore their Android.bp files.
_manager_bp_backups = []
for manager_version in ("1.0", "1.1", "1.2"):
    manager_bp = tree / f"system/libhidl/transport/manager/{manager_version}/Android.bp"
    if not manager_bp.is_file():
        raise SystemExit(f"missing android.hidl.manager@{manager_version} Android.bp")
    manager_original = manager_bp.read_bytes()
    manager_stat = manager_bp.stat()
    manager_text = manager_original.decode("utf-8")
    if "gen_java: true," not in manager_text:
        raise SystemExit(
            f"unexpected android.hidl.manager@{manager_version} Android.bp structure"
        )
    manager_text = manager_text.replace("gen_java: true,", "gen_java: false,")
    manager_text = manager_text.replace(
        "gen_java_constants: true,", "gen_java_constants: false,"
    )
    manager_bp.write_text(manager_text)
    _manager_bp_backups.append((manager_bp, manager_original, manager_stat))
    print(f"CODEC2_NARROW_HIDL_MANAGER_NATIVE_ONLY_VERSION={manager_version}")
print("CODEC2_NARROW_HIDL_MANAGER_NATIVE_ONLY=1")

def _restore_manager_bp():
    for manager_bp, manager_original, manager_stat in reversed(_manager_bp_backups):
        manager_bp.write_bytes(manager_original)
        os.utime(
            manager_bp,
            ns=(manager_stat.st_atime_ns, manager_stat.st_mtime_ns),
        )

atexit.register(_restore_manager_bp)

# The AVC path needs libbinder_headers, but the same Android.bp also defines
# package-manager and test AIDL interfaces. In a reduced graph those interfaces
# request aidl_metadata_json, which recursively pulls the complete AIDL Soong
# plugin/Java graph and eventually dex2oatd. Remove only top-level aidl_interface
# modules for this disposable probe; native binder/header modules stay intact.
def _strip_top_level_modules(text: str, module_type: str):
    pat = re.compile(rf"(?m)^[ \t]*{re.escape(module_type)}[ \t]*\{{")
    out = []
    pos = 0
    removed = 0
    while True:
        match = pat.search(text, pos)
        if match is None:
            out.append(text[pos:])
            break
        out.append(text[pos:match.start()])
        brace = text.find("{", match.start(), match.end())
        depth = 0
        in_string = False
        escaped = False
        end = -1
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
                    end = i + 1
                    break
        if end < 0:
            raise SystemExit(f"unterminated {module_type} block")
        while end < len(text) and text[end] in " \t\r\n":
            end += 1
        pos = end
        removed += 1
    return "".join(out), removed

binder_bp = tree / "frameworks/native/libs/binder/Android.bp"
_binder_bp_original = None
_binder_bp_stat = None
if binder_bp.is_file():
    _binder_bp_original = binder_bp.read_bytes()
    _binder_bp_stat = binder_bp.stat()
    binder_text = _binder_bp_original.decode("utf-8")
    binder_text, removed_aidl = _strip_top_level_modules(binder_text, "aidl_interface")
    if removed_aidl < 1 or 'name: "libbinder_headers"' not in binder_text:
        raise SystemExit("unexpected frameworks/native binder Android.bp structure")
    binder_bp.write_text(binder_text)
    print(f"CODEC2_NARROW_BINDER_HEADERS_ONLY=1 removed_aidl={removed_aidl}")

def _restore_binder_bp():
    if _binder_bp_original is None:
        return
    binder_bp.write_bytes(_binder_bp_original)
    os.utime(
        binder_bp,
        ns=(_binder_bp_stat.st_atime_ns, _binder_bp_stat.st_mtime_ns),
    )

atexit.register(_restore_binder_bp)

# libui exports the V3 NDK graphics-common AIDL headers. They are on the real
# AVC compile path (GraphicTypes.h -> BlendMode.h), but the source interfaces
# also enable Java by default. Keep only their native NDK variants in this
# disposable graph and restore both Android.bp files afterwards.
_aidl_native_only_backups = []

def _disable_aidl_java_backend(rel: str, interface_name: str):
    bp = tree / rel
    if not bp.is_file():
        raise SystemExit(f"missing required AIDL provider: {rel}")
    original = bp.read_bytes()
    stat = bp.stat()
    text = original.decode("utf-8")
    if f'name: "{interface_name}"' not in text:
        raise SystemExit(f"unexpected AIDL interface in {rel}")
    java = re.search(r"(?ms)(^[ \t]*java:[ \t]*\{\n)(.*?)(^[ \t]*\},)", text)
    if java is None:
        raise SystemExit(f"missing Java backend block in {rel}")
    body = java.group(2)
    if re.search(r"(?m)^[ \t]*enabled:[ \t]*true,[ \t]*$", body):
        body = re.sub(
            r"(?m)^([ \t]*)enabled:[ \t]*true,[ \t]*$",
            r"\1enabled: false,",
            body,
            count=1,
        )
    elif not re.search(r"(?m)^[ \t]*enabled:[ \t]*false,[ \t]*$", body):
        indent = re.match(r"([ \t]*)", java.group(1)).group(1) + "    "
        body = f"{indent}enabled: false,\n" + body
    text = text[:java.start(2)] + body + text[java.end(2):]
    bp.write_text(text)
    _aidl_native_only_backups.append((bp, original, stat))
    print(f"CODEC2_NARROW_AIDL_NATIVE_ONLY={interface_name}")

_disable_aidl_java_backend(
    "hardware/interfaces/graphics/common/aidl/Android.bp",
    "android.hardware.graphics.common",
)
_disable_aidl_java_backend(
    "hardware/interfaces/common/aidl/Android.bp",
    "android.hardware.common",
)

def _restore_aidl_native_only():
    for bp, original, stat in reversed(_aidl_native_only_backups):
        bp.write_bytes(original)
        os.utime(bp, ns=(stat.st_atime_ns, stat.st_mtime_ns))

atexit.register(_restore_aidl_native_only)

# aidl_metadata_json shares its Android.bp with the aidl-soong-rules bootstrap
# plugin and many Java test interfaces. The warm soong_build already contains
# the AIDL plugin, so the reduced graph only needs the metadata sink required by
# reverse dependencies from the two native AIDL interfaces above. Replace that
# Android.bp with a metadata-only module for the disposable probe, then restore.
aidl_build_bp = tree / "system/tools/aidl/build/Android.bp"
_aidl_build_bp_original = None
_aidl_build_bp_stat = None
if aidl_build_bp.is_file():
    _aidl_build_bp_original = aidl_build_bp.read_bytes()
    _aidl_build_bp_stat = aidl_build_bp.stat()
    aidl_build_text = _aidl_build_bp_original.decode("utf-8")
    if 'name: "aidl_metadata_json"' not in aidl_build_text:
        raise SystemExit("unexpected system/tools/aidl/build Android.bp structure")
    aidl_build_bp.write_text(
        'aidl_interfaces_metadata {\n'
        '    name: "aidl_metadata_json",\n'
        '    visibility: ["//visibility:public"],\n'
        '}\n'
    )
    print("CODEC2_NARROW_AIDL_METADATA_ONLY=1")

def _restore_aidl_build_bp():
    if _aidl_build_bp_original is None:
        return
    aidl_build_bp.write_bytes(_aidl_build_bp_original)
    os.utime(
        aidl_build_bp,
        ns=(_aidl_build_bp_stat.st_atime_ns, _aidl_build_bp_stat.st_mtime_ns),
    )

atexit.register(_restore_aidl_build_bp)

probe_out = tree / "out/soong/pitv-codec2.ninja"
used = tree / "out/soong/pitv-codec2.environment.used"
glob_file = tree / "out/soong/pitv-codec2-build-globs.ninja"
glob_dir = tree / "out/soong/.pitv-codec2-globs"

forbidden_prefixes = (
    "cts/",
    "external/skia/",
    "hardware/interfaces/automotive/",
    "hardware/interfaces/neuralnetworks/",
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
generated_hidl_re = re.compile(
    r"^(?P<base>.+@\d+\.\d+)(?:_interface|_genc\+\+(?:_headers)?|-inheritance-hierarchy|-hidl-lint)$"
)
ansi_re = re.compile(r"\x1b\[[0-9;]*m")
missing_re = re.compile(
    r'error:\s+([^:\n]+):\d+:\d+:\s+"[^"]+" depends on undefined module "([^"]+)"'
)
reverse_missing_re = re.compile(
    r'error:\s+([^:\n]+):\d+:\d+:\s+"[^"]+" has a reverse dependency on undefined module "([^"]+)"'
)
package_root_re = re.compile(
    r"error:\s+([^:\n]+):\d+:\d+:.*?Cannot find package root specification "
    r"for package root '([^']+)'"
)
aidl_import_re = re.compile(
    r"error:\s+([^:\n]+):\d+:\d+:.*?imports: Import does not exist: ([^\s]+)"
)
label_no_files_re = re.compile(
    r'error:\s+([^:\n]+):\d+:\d+:.*?cmd:\s+(?:default )?label ":(?P<label>[^"]+)" has no files'
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
    # Generated HIDL helper modules must resolve back to the source
    # hidl_interface declaration. VNDK prebuilts often export modules with the
    # same generated names; selecting those expands the graph into every VNDK
    # snapshot instead of the Android 13 source interface we are probing.
    h = generated_hidl_re.match(module)
    if h:
        names = [h.group("base")]
    else:
        names = [module]
        m = generated_aidl_re.match(module)
        if m:
            names.append(m.group("base"))
    out = []
    seen = set()
    for name in names:
        for rel in providers.get(name, []):
            if h and rel.startswith("prebuilts/vndk/"):
                continue
            if rel not in seen:
                seen.add(rel)
                out.append(rel)
    # Prefer Android 13 source modules over VNDK snapshot copies whenever a
    # source provider exists. Snapshot Android.bp files export many familiar
    # names (for example libhidlbase/libutils), but selecting them does not
    # produce the source variant required by this narrow target graph.
    source_candidates = [rel for rel in out if not rel.startswith("prebuilts/vndk/")]
    if source_candidates:
        out = source_candidates
    return out

def choose_provider(module: str, consumer: str):
    candidates = [x for x in provider_candidates(module) if x not in selected]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-common_prefix_score(consumer, x), len(Path(x).parts), x))
    return candidates[0]

# A previous concrete Ninja attempt can feed back only the missing modules that
# were proven to be on the AVC target path. Add their exact providers before
# regenerating the graph, while keeping unrelated missing deps tolerated.
required_raw = os.environ.get("PITV_CODEC2_NARROW_REQUIRED_MODULES", "")
required_modules = [
    x.strip() for x in re.split(r"[\n,]+", required_raw) if x.strip()
]
# Some transitive header-only dependencies are silently omitted when
# Allow_missing_dependencies is enabled, so their missing includes never appear
# as normal module errors. Seed only the header/interface providers proven to be
# on the concrete AVC compile path.
seed_modules = (
    "libfmq-base",                         # fmq/MQDescriptorBase.h
    "libsystem_headers",                   # system/graphics.h
    "android.hidl.manager@1.0",            # android/hidl/manager/1.0/IServiceManager.h
    "libarect",                            # android/rect.h
    "libnativebase_headers",               # nativebase/nativebase.h
    "libbacktrace_headers",                # backtrace/backtrace_constants.h used by libhidlbase
    "android.hardware.common-V2-ndk",       # imported by graphics common AIDL
    "android.hardware.graphics.common-V3-ndk", # aidl/.../graphics/common/BlendMode.h
    "android.hardware.graphics.mapper@4.0", # android/hardware/graphics/mapper/4.0/IMapper.h
    "libbinder_headers_platform_shared",   # android/binder_enums.h
)
for module in seed_modules:
    if module not in required_modules:
        required_modules.append(module)
        print(f"CODEC2_NARROW_SEED_MODULE={module}")
for module in required_modules:
    candidates = provider_candidates(module)
    if any(rel in selected for rel in candidates):
        print(f"CODEC2_NARROW_REQUIRED_ALREADY_SELECTED={module}")
        continue
    provider = choose_provider(module, "")
    if provider is None:
        if candidates:
            print(f'CODEC2_NARROW_REQUIRED_BLOCKED={module} providers={",".join(candidates[:8])}')
        else:
            print(f"CODEC2_NARROW_REQUIRED_PROVIDER_NOT_FOUND={module}")
        raise SystemExit(1)
    selected.add(provider)
    print(f"CODEC2_NARROW_REQUIRE_PROVIDER module={module} provider={provider}")

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
    for consumer, module in reverse_missing_re.findall(clean_output):
        key = (consumer, module)
        if key not in seen_missing:
            seen_missing.add(key)
            missing.append(key)
            print(
                f"CODEC2_NARROW_MISSING_REVERSE_DEP={module} "
                f"consumer={consumer}"
            )
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
    for consumer, label in label_no_files_re.findall(clean_output):
        key = (consumer, label)
        if key not in seen_missing:
            seen_missing.add(key)
            missing.append(key)
            print(
                f"CODEC2_NARROW_MISSING_LABEL={label} "
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
