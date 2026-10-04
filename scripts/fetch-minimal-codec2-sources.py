#!/usr/bin/env python3
"""Fetch only pinned external Codec2 sources, not an Android source tree."""
import json,os,subprocess,sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("usage: fetch-minimal-codec2-sources.py WORKDIR")
repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/"android/waydroid-rpi4/minimal-codec2-sources.lock.json").read_text())
out=Path(sys.argv[1]).resolve(); out.mkdir(parents=True,exist_ok=True)
for item in lock["sources"]:
    dst=out/item["name"]
    fresh=False
    if not dst.exists():
        subprocess.run(["git","clone","--filter=blob:none","--no-checkout",item["url"],str(dst)],check=True)
        fresh=True
    elif not (dst/".git").exists():
        raise SystemExit(f"existing path is not a git checkout: {dst}")
    origin=subprocess.check_output(["git","-C",str(dst),"remote","get-url","origin"],text=True).strip()
    if origin!=item["url"]: raise SystemExit(f"refusing source with unexpected origin: {item['name']} {origin}")
    # A fresh --no-checkout clone has HEAD and an index but intentionally no
    # populated worktree, so git status reports tracked files as deleted.
    # Only pre-existing checkouts are subject to the dirty-tree refusal.
    if not fresh:
        dirty=subprocess.check_output(["git","-C",str(dst),"status","--porcelain"],text=True)
        if dirty.strip(): raise SystemExit(f"refusing dirty source checkout: {item['name']}")
    subprocess.run(["git","-C",str(dst),"fetch","--depth=1","origin",item["commit"]],check=True)
    subprocess.run(["git","-C",str(dst),"checkout","--detach","--force",item["commit"]],check=True)
    got=subprocess.check_output(["git","-C",str(dst),"rev-parse","HEAD"],text=True).strip()
    if got!=item["commit"]: raise SystemExit(f"commit mismatch: {item['name']}")
    for rel in item.get("license_files",[]):
        if not (dst/rel).is_file(): raise SystemExit(f"missing license file {item['name']}/{rel}")
    print(f"{item['name']}={got}")
subprocess.run([sys.executable,str(repo/"scripts/verify-minimal-codec2-sources.py"),str(out)],check=True)

# ndkstubgen is a python_binary_host, not a bootstrap.ninja target.  The
# narrow graph still expects it under HOST_OUT, so provide the equivalent
# lightweight launcher directly from the synced Android tree before the warm
# bootstrap step tries to use it.
tree_env=os.environ.get("TREE")
if tree_env:
    tree=Path(tree_env).resolve()
    ndkstubgen_src=tree/"build/soong/cc/ndkstubgen/__init__.py"
    symbolfile_src=tree/"build/soong/cc/symbolfile/__init__.py"
    if ndkstubgen_src.is_file() and symbolfile_src.is_file():
        host_ndkstubgen=tree/"out/host/linux-x86/bin/ndkstubgen"
        host_ndkstubgen.parent.mkdir(parents=True,exist_ok=True)
        host_ndkstubgen.write_text(
            "#!/bin/sh\n"
            f"export PYTHONPATH=\"{tree}/build/soong/cc${{PYTHONPATH:+:$PYTHONPATH}}\"\n"
            f"exec python3 \"{ndkstubgen_src}\" \"$@\"\n"
        )
        host_ndkstubgen.chmod(0o755)
        print("CODEC2_NARROW_NDKSTUBGEN_WRAPPER=1")

    # Stable AIDL interfaces in the narrow native graph invoke the canonical
    # HOST_OUT aidl path. Android 13 already ships a matching SDK prebuilt host
    # compiler, so expose that exact tool through a tiny wrapper instead of
    # pulling system/tools/aidl tests and Java integration modules into Soong.
    prebuilt_aidl=tree/"prebuilts/sdk/tools/linux/bin/aidl"
    prebuilt_aidl_lib64=tree/"prebuilts/sdk/tools/linux/lib64"
    if prebuilt_aidl.is_file():
        host_aidl=tree/"out/host/linux-x86/bin/aidl"
        host_aidl.parent.mkdir(parents=True,exist_ok=True)
        host_aidl.write_text(
            "#!/bin/sh\n"
            f"export LD_LIBRARY_PATH=\"{prebuilt_aidl_lib64}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}\"\n"
            f"exec \"{prebuilt_aidl}\" \"$@\"\n"
        )
        host_aidl.chmod(0o755)
        print("CODEC2_NARROW_PREBUILT_AIDL_WRAPPER=1")

    # aidl_hash_gen is only a host sh_binary around hash_gen.sh. The generated
    # frozen-API dump rules still refer to its canonical HOST_OUT path, so
    # expose the synced Android 13 script without adding the AIDL test graph.
    aidl_hash_gen_src=tree/"system/tools/aidl/build/hash_gen.sh"
    if aidl_hash_gen_src.is_file():
        host_aidl_hash_gen=tree/"out/host/linux-x86/bin/aidl_hash_gen"
        host_aidl_hash_gen.parent.mkdir(parents=True,exist_ok=True)
        host_aidl_hash_gen.write_text(
            "#!/bin/sh\n"
            f"exec bash \"{aidl_hash_gen_src}\" \"$@\"\n"
        )
        host_aidl_hash_gen.chmod(0o755)
        print("CODEC2_NARROW_AIDL_HASH_GEN_WRAPPER=1")

    # The direct narrow graph links host hidl-gen against Soong's shared
    # libc++.  Unlike a normal full build, the promoted HOST_OUT hidl-gen has
    # no install-time runtime-library setup.  GitHub Actions applies GITHUB_ENV
    # to the following step, so point the AVC build at the exact host libc++
    # intermediate directory before hidl-gen is invoked by generated HIDL rules.
    github_env=os.environ.get("GITHUB_ENV")
    if github_env:
        host_libcxx_dir=tree/"out/soong/.intermediates/external/libcxx/libc++/linux_glibc_x86_64_shared"
        with Path(github_env).open("a") as env_file:
            env_file.write(f"LD_LIBRARY_PATH={host_libcxx_dir}\n")
            env_file.write("PITV_CODEC2_NARROW_BUILD_ATTEMPTS=32\n")
        print(f"CODEC2_NARROW_HOST_LIBCXX_DIR={host_libcxx_dir}")
        print("CODEC2_NARROW_BUILD_ATTEMPTS=32")
