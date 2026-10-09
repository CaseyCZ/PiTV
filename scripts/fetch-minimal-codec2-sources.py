#!/usr/bin/env python3
"""Fetch only pinned external Codec2 sources, not an Android source tree."""
import json, os, re, subprocess, sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: fetch-minimal-codec2-sources.py WORKDIR")

repo = Path(__file__).resolve().parents[1]
lock = json.loads((repo / "android/waydroid-rpi4/minimal-codec2-sources.lock.json").read_text())
out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)

for item in lock["sources"]:
    dst = out / item["name"]
    fresh = False
    if not dst.exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", item["url"], str(dst)],
            check=True,
        )
        fresh = True
    elif not (dst / ".git").exists():
        raise SystemExit(f"existing path is not a git checkout: {dst}")

    origin = subprocess.check_output(
        ["git", "-C", str(dst), "remote", "get-url", "origin"], text=True
    ).strip()
    if origin != item["url"]:
        raise SystemExit(f"refusing source with unexpected origin: {item['name']} {origin}")

    # A fresh --no-checkout clone has HEAD and an index but intentionally no
    # populated worktree, so git status reports tracked files as deleted.
    # Only pre-existing checkouts are subject to the dirty-tree refusal.
    if not fresh:
        dirty = subprocess.check_output(
            ["git", "-C", str(dst), "status", "--porcelain"], text=True
        )
        if dirty.strip():
            raise SystemExit(f"refusing dirty source checkout: {item['name']}")

    subprocess.run(
        ["git", "-C", str(dst), "fetch", "--depth=1", "origin", item["commit"]],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dst), "checkout", "--detach", "--force", item["commit"]],
        check=True,
    )
    got = subprocess.check_output(
        ["git", "-C", str(dst), "rev-parse", "HEAD"], text=True
    ).strip()
    if got != item["commit"]:
        raise SystemExit(f"commit mismatch: {item['name']}")
    for rel in item.get("license_files", []):
        if not (dst / rel).is_file():
            raise SystemExit(f"missing license file {item['name']}/{rel}")
    print(f"{item['name']}={got}")

subprocess.run(
    [sys.executable, str(repo / "scripts/verify-minimal-codec2-sources.py"), str(out)],
    check=True,
)

# ndkstubgen is a python_binary_host, not a bootstrap.ninja target. The narrow
# graph still expects it under HOST_OUT, so prepare the lightweight host tools
# needed by the disposable CI tree before the direct narrow build uses them.
tree_env = os.environ.get("TREE")
if tree_env:
    tree = Path(tree_env).resolve()
    narrow_ci = os.environ.get("GITHUB_JOB") == "codec2-narrow-probe"

    # Android 13's AIDL Soong backend hardcodes Tidy=true on generated native
    # implementation libraries. The reduced graph cannot materialize that
    # unrelated clang-tidy sidecar, so disable it only in the disposable tree.
    if narrow_ci:
        aidl_backends = tree / "system/tools/aidl/build/aidl_interface_backends.go"
        if not aidl_backends.is_file():
            raise SystemExit("missing Android 13 AIDL backend source")
        aidl_text = aidl_backends.read_text()
        tidy_true = "Tidy:                      proptools.BoolPtr(true),"
        tidy_false = "Tidy:                      proptools.BoolPtr(false),"
        replaced = aidl_text.count(tidy_true)
        if replaced:
            aidl_backends.write_text(aidl_text.replace(tidy_true, tidy_false))
        elif tidy_false not in aidl_text:
            raise SystemExit("unexpected Android 13 AIDL tidy backend structure")
        print(f"CODEC2_NARROW_AIDL_TIDY_DISABLED=1 replaced={replaced}")

        available_env = tree / "out/soong/soong.environment.available"
        if available_env.is_file():
            entries = json.loads(available_env.read_text())
            if not isinstance(entries, list):
                raise SystemExit("unexpected Soong available environment format")
            by_key = {
                entry.get("Key"): entry
                for entry in entries
                if isinstance(entry, dict) and entry.get("Key")
            }
            for key in ("WITH_TIDY", "ALLOW_LOCAL_TIDY_TRUE"):
                by_key[key] = {"Key": key, "Value": ""}
            available_env.write_text(
                json.dumps(sorted(by_key.values(), key=lambda entry: entry["Key"]), indent=4)
                + "\n"
            )
            print("CODEC2_NARROW_TIDY_DISABLED=1")

    ndkstubgen_src = tree / "build/soong/cc/ndkstubgen/__init__.py"
    symbolfile_src = tree / "build/soong/cc/symbolfile/__init__.py"
    if ndkstubgen_src.is_file() and symbolfile_src.is_file():
        host_ndkstubgen = tree / "out/host/linux-x86/bin/ndkstubgen"
        host_ndkstubgen.parent.mkdir(parents=True, exist_ok=True)
        host_ndkstubgen.write_text(
            "#!/bin/sh\n"
            f"export PYTHONPATH=\"{tree}/build/soong/cc${{PYTHONPATH:+:$PYTHONPATH}}\"\n"
            f"exec python3 \"{ndkstubgen_src}\" \"$@\"\n"
        )
        host_ndkstubgen.chmod(0o755)
        print("CODEC2_NARROW_NDKSTUBGEN_WRAPPER=1")

    prebuilt_aidl = tree / "prebuilts/build-tools/linux-x86/bin/aidl"
    if prebuilt_aidl.is_file():
        host_aidl = tree / "out/host/linux-x86/bin/aidl"
        host_aidl.parent.mkdir(parents=True, exist_ok=True)
        host_aidl.write_text(
            "#!/bin/sh\n"
            f"exec \"{prebuilt_aidl}\" \"$@\"\n"
        )
        host_aidl.chmod(0o755)
        print("CODEC2_NARROW_PREBUILT_AIDL_WRAPPER=1")

    aidl_hash_gen_src = tree / "system/tools/aidl/build/hash_gen.sh"
    if aidl_hash_gen_src.is_file():
        host_aidl_hash_gen = tree / "out/host/linux-x86/bin/aidl_hash_gen"
        host_aidl_hash_gen.parent.mkdir(parents=True, exist_ok=True)
        host_aidl_hash_gen.write_text(
            "#!/bin/sh\n"
            f"exec bash \"{aidl_hash_gen_src}\" \"$@\"\n"
        )
        host_aidl_hash_gen.chmod(0o755)
        print("CODEC2_NARROW_AIDL_HASH_GEN_WRAPPER=1")

    # dep_fixer is a Soong bootstrap host tool. The warm probe can stop before
    # its HOST_OUT install edge; build the exact bootstrap target and promote it.
    if narrow_ci:
        host_dep_fixer = tree / "out/host/linux-x86/bin/dep_fixer"
        bootstrap_ninja = tree / "out/soong/bootstrap.ninja"
        if not host_dep_fixer.is_file() and bootstrap_ninja.is_file():
            ninja = tree / "prebuilts/build-tools/linux-x86/bin/ninja"
            if not ninja.is_file():
                raise SystemExit("missing Android bootstrap ninja executable")
            inventory = subprocess.check_output(
                [str(ninja), "-f", str(bootstrap_ninja), "-t", "targets", "all"],
                cwd=tree,
                text=True,
            )
            dep_target = None
            for line in inventory.splitlines():
                target = line.split(": ", 1)[0]
                if target.endswith("/dep_fixer"):
                    dep_target = target
                    break
            if not dep_target:
                raise SystemExit("bootstrap graph missing dep_fixer target")
            subprocess.run(
                [str(ninja), "-f", str(bootstrap_ninja), dep_target], cwd=tree, check=True
            )
            dep_binary = Path(dep_target)
            if not dep_binary.is_absolute():
                dep_binary = tree / dep_binary
            if not dep_binary.is_file():
                raise SystemExit(
                    f"dep_fixer target built but output is missing: {dep_binary}"
                )
            host_dep_fixer.parent.mkdir(parents=True, exist_ok=True)
            host_dep_fixer.write_bytes(dep_binary.read_bytes())
            host_dep_fixer.chmod(0o755)
            print(f"CODEC2_NARROW_DEP_FIXER_READY={dep_binary}")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        host_libcxx_dir = (
            tree / "out/soong/.intermediates/external/libcxx/libc++/linux_glibc_x86_64_shared"
        )
        math_headers_dir = tree / "frameworks/native/libs/math/include"
        with Path(github_env).open("a") as env_file:
            env_file.write(f"LD_LIBRARY_PATH={host_libcxx_dir}\n")
            env_file.write(f"CPATH={math_headers_dir}\n")
            env_file.write("PITV_CODEC2_NARROW_BUILD_ATTEMPTS=32\n")
            if narrow_ci:
                env_file.write("PITV_CODEC2_JOBS=1\n")
        print(f"CODEC2_NARROW_HOST_LIBCXX_DIR={host_libcxx_dir}")
        print(f"CODEC2_NARROW_MATH_HEADERS_DIR={math_headers_dir}")
        print("CODEC2_NARROW_BUILD_ATTEMPTS=32")
        if narrow_ci:
            print("CODEC2_NARROW_SERIAL_JOBS=1")

    # Keep experimental CI repairs in one place. This edits only the disposable
    # workflow checkout of the driver and leaves Master and Android sources alone.
    if narrow_ci:
        build_driver = repo / "scripts/build-minimal-codec2-modules.sh"
        driver = build_driver.read_text()

        # Repair historical over-escaping so missing-dependency output is parsed.
        driver = driver.replace("printf '%s\\\\n'", "printf '%s\\n'")
        driver = driver.replace(
            r'r"missing dependencies:\\s*([^\\n]+)"',
            r'r"missing dependencies:\s*([^\n]+)"',
        )
        driver = driver.replace(
            r'r"missing dependencies:\\s*([^\\n]+)"'.replace(r'\"', '"'),
            r'r"missing dependencies:\s*([^\n]+)"'.replace(r'\"', '"'),
        )

        # Preflight is diagnostic only. A dry-run cannot execute the deliberate
        # missing-module closure commands generated by the narrow graph.
        driver, preflight_patches = re.subn(
            r'''    # Fail immediately on a broken graph instead of spending the build budget\n'''
            r'''    # retrying an AVC target that Ninja already proved cannot be built\.\n'''
            r'''    if \[ "\$preflight_rc" -ne 0 \]; then\n'''
            r'''      echo "CODEC2_NARROW_PREFLIGHT_BLOCKED=1" >&2\n'''
            r'''      printf .*?\n'''
            r'''      exit "\$preflight_rc"\n'''
            r'''    fi\n'''
            r'''    unset preflight_rc\n''',
            '''    # Keep this dry-run diagnostic-only. The concrete Ninja build below\n    # feeds proven missing modules back into the narrow Soong provider closure.\n    unset preflight_rc\n''',
            driver,
            count=1,
        )
        if preflight_patches not in (0, 1):
            raise SystemExit("unexpected preflight fail-fast patch count")

        driver = driver.replace(
            "for host_tool in hidl-gen aidl sysprop_cpp ndkstubgen sbox merge_zips; do",
            "for host_tool in hidl-gen aidl aprotoc sysprop_cpp ndkstubgen sbox merge_zips; do",
            1,
        )

        # One accumulated, stable dependency set is shared by HIDL, aprotoc,
        # sysprop_cpp and the final AVC build. New discoveries are unioned and
        # deduplicated instead of replacing or blindly appending the old set.
        closure_init = '''  REQUIRED_MODULES=""\n  PREVIOUS_REQUIRED_MODULES=""\n'''
        closure_helper = r'''  merge_required_modules() {
    python3 - "$@" <<'PYMERGE'
import re, sys
seen = set()
out = []
for value in sys.argv[1:]:
    for name in re.split(r"[\s,]+", value):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
print(",".join(out))
PYMERGE
  }
'''
        if "  merge_required_modules() {" not in driver:
            if driver.count(closure_init) != 1:
                raise SystemExit("unexpected narrow closure initialization")
            driver = driver.replace(closure_init, closure_init + closure_helper, 1)

        # HIDL and final AVC used to overwrite REQUIRED_MODULES with only the
        # latest failure. Merge the parser result with the accumulated set before
        # their existing no-progress check runs.
        hidl_tail = ''')"\n        if [ -z "$REQUIRED_MODULES" ]; then\n'''
        hidl_tail_merged = ''')"\n        REQUIRED_MODULES="$(merge_required_modules "$PREVIOUS_REQUIRED_MODULES" "$REQUIRED_MODULES")"\n        if [ -z "$REQUIRED_MODULES" ]; then\n'''
        if hidl_tail in driver and hidl_tail_merged not in driver:
            driver = driver.replace(hidl_tail, hidl_tail_merged, 1)
        elif hidl_tail_merged not in driver:
            raise SystemExit("missing HIDL closure merge point")

        avc_tail = ''')"\n    if [ -z "$REQUIRED_MODULES" ]; then\n'''
        avc_tail_merged = ''')"\n    REQUIRED_MODULES="$(merge_required_modules "$PREVIOUS_REQUIRED_MODULES" "$REQUIRED_MODULES")"\n    if [ -z "$REQUIRED_MODULES" ]; then\n'''
        if avc_tail in driver and avc_tail_merged not in driver:
            driver = driver.replace(avc_tail, avc_tail_merged, 1)
        elif avc_tail_merged not in driver:
            raise SystemExit("missing AVC closure merge point")

        # sysprop already stores its parser output separately. Union it into the
        # accumulated set and enforce progress before regenerating the graph.
        sysprop_append = '''          REQUIRED_MODULES="${REQUIRED_MODULES:+$REQUIRED_MODULES,}$sysprop_missing"\n          continue\n'''
        sysprop_merge = '''          REQUIRED_MODULES="$(merge_required_modules "$REQUIRED_MODULES" "$sysprop_missing")"\n          if [ "$REQUIRED_MODULES" = "$PREVIOUS_REQUIRED_MODULES" ]; then\n            echo "narrow sysprop_cpp dependency closure made no progress" >&2\n            exit "$sysprop_rc"\n          fi\n          PREVIOUS_REQUIRED_MODULES="$REQUIRED_MODULES"\n          continue\n'''
        if sysprop_append in driver:
            driver = driver.replace(sysprop_append, sysprop_merge, 1)
        elif sysprop_merge not in driver:
            raise SystemExit("missing sysprop closure merge point")

        aprotoc_marker = '    host_sysprop_cpp="$TREE/out/host/linux-x86/bin/sysprop_cpp"'
        aprotoc_ready = "CODEC2_NARROW_APROTOC_READY=1"
        if aprotoc_ready not in driver:
            if aprotoc_marker not in driver:
                raise SystemExit("missing sysprop host-tool insertion point")
            aprotoc_block = r'''    # sysprop proto generation expects aprotoc at HOST_OUT, while the reduced
    # Soong graph exposes the real cc_binary_host only in .intermediates.
    host_aprotoc="$TREE/out/host/linux-x86/bin/aprotoc"
    if [ ! -x "$host_aprotoc" ]; then
      aprotoc_target="$(python3 -c '
import sys
for line in sys.stdin:
    if "/aprotoc/linux_glibc_x86_64/aprotoc: " in line:
        print(line.split(": ", 1)[0]); break
' <<<"$target_inventory")"
      if [ -z "$aprotoc_target" ]; then
        echo "CODEC2_NARROW_APROTOC_TARGET_MISSING=1" >&2
        exit 15
      fi
      echo "CODEC2_NARROW_APROTOC_TARGET=$aprotoc_target"
      set +e
      aprotoc_output="$("$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$aprotoc_target" 2>&1)"
      aprotoc_rc=$?
      set -e
      [ -z "$aprotoc_output" ] || printf '%s\n' "$aprotoc_output"
      if [ "$aprotoc_rc" -ne 0 ]; then
        aprotoc_missing="$(printf '%s\n' "$aprotoc_output" | python3 -c '
import re, sys
mods = set()
for match in re.finditer(r"missing dependencies:\s*([^\n]+)", sys.stdin.read(), re.I):
    for raw in match.group(1).split(","):
        name = raw.strip().strip(chr(34) + chr(39)).rstrip(".;")
        if re.fullmatch(r"[A-Za-z0-9_.+@:/=-]+", name):
            mods.add(name)
print(",".join(sorted(mods)))
')"
        if [ -n "$aprotoc_missing" ]; then
          echo "CODEC2_NARROW_APROTOC_MISSING=$aprotoc_missing"
          REQUIRED_MODULES="$(merge_required_modules "$REQUIRED_MODULES" "$aprotoc_missing")"
          if [ "$REQUIRED_MODULES" = "$PREVIOUS_REQUIRED_MODULES" ]; then
            echo "narrow aprotoc dependency closure made no progress" >&2
            exit "$aprotoc_rc"
          fi
          PREVIOUS_REQUIRED_MODULES="$REQUIRED_MODULES"
          continue
        fi
        exit "$aprotoc_rc"
      fi
      test -s "$aprotoc_target"
      mkdir -p "$(dirname "$host_aprotoc")"
      cp "$aprotoc_target" "$host_aprotoc"
      chmod +x "$host_aprotoc"
      test -x "$host_aprotoc"
      echo "CODEC2_NARROW_APROTOC_READY=1"
    fi

'''.replace('\\"', '"')
            driver = driver.replace(aprotoc_marker, aprotoc_block + aprotoc_marker, 1)

        build_driver.write_text(driver)
        print("CODEC2_NARROW_RUNTIME_DRIVER_REPAIR=2")
