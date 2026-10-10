#!/usr/bin/env bash
set -euo pipefail
# Build only the PiTV Codec2 modules inside an existing Android 13 build tree.
# This script never runs repo init/sync and therefore cannot create the old
# full ~300GB workspace by itself.
TREE="$(readlink -f "${1:?Android 13 build tree required}")"
SOURCES="$(readlink -f "${2:?directory from fetch-minimal-codec2-sources.py required}")"
OUT="$(readlink -m "${3:?output payload directory required}")"
JOBS="${PITV_CODEC2_JOBS:-$(nproc)}"
PHASE="${PITV_CODEC2_PHASE:-all}"
SOURCE_EPOCH="${PITV_CODEC2_SOURCE_EPOCH:-946684800}"
case "$PHASE" in all|graph|modules|diagnose|narrow-list|narrow-probe|narrow-build) ;; *) echo "invalid PITV_CODEC2_PHASE: $PHASE" >&2; exit 2;; esac
[ -f "$TREE/build/envsetup.sh" ] || { echo "not an Android build tree" >&2; exit 2; }
for d in v4l2_codec2 ffmpeg ffmpeg_codec2 libudev_zero; do [ -d "$SOURCES/$d" ] || { echo "missing $d" >&2; exit 2; }; done
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/verify-minimal-codec2-sources.py" "$SOURCES"
python3 "$HERE/check-codec2-xml-contract.py"
bash "$HERE/guard-codec2-build-workspace.sh" "$TREE"
release_file="$TREE/build/make/core/version_defaults.mk"
if [ -f "$release_file" ] && ! grep -Eq 'PLATFORM_VERSION.*13|PLATFORM_VERSION_LAST_STABLE.*13' "$release_file"; then
  echo "build tree does not look like Android 13" >&2; exit 3
fi

SRC_BACKUP="$(mktemp -d /tmp/pitv-codec2-src-backup.XXXXXX)"
MODIFIED=()
SOURCES_RESTORED=0
restore_sources(){
  [ "$SOURCES_RESTORED" -eq 0 ] || return 0
  SOURCES_RESTORED=1
  # TERM/INT can be followed by EXIT. Disable all restore traps before
  # mutating paths so the original source tree cannot be removed twice.
  trap - EXIT INT TERM
  for dst in "${MODIFIED[@]}"; do
    target="$TREE/$dst"; key="${dst//\//__}"
    rm -rf "$target"
    [ ! -e "$SRC_BACKUP/$key" ] || mv "$SRC_BACKUP/$key" "$target"
  done
  rm -rf "$SRC_BACKUP"
}
trap restore_sources EXIT
trap 'restore_sources; exit 130' INT
trap 'restore_sources; exit 143' TERM
install_src(){
  src="$1"; dst="$2"
  target="$(readlink -m "$TREE/$dst")"
  case "$target/" in "$TREE/external/"*) ;; *) echo "unsafe source install target: $target" >&2; exit 2;; esac
  key="${dst//\//__}"
  if [ -e "$target" ] || [ -L "$target" ]; then mv "$target" "$SRC_BACKUP/$key"; fi
  MODIFIED+=("$dst")
  mkdir -p "$(dirname "$target")"
  cp -a "$SOURCES/$src" "$target"
  # A restored Soong bootstrap manifest depends on these build-definition
  # files. Fresh clones otherwise make them newer than the checkpoint and
  # force all bootstrap Go tools to rebuild on every runner.
  find "$target" -type f \( -name 'Android.bp' -o -name 'Android.mk' -o -name '*.mk' \) \
    -exec touch -d "@$SOURCE_EPOCH" {} +
}

prepare_temp_file_edit(){
  dst="$1"
  target="$(readlink -m "$TREE/$dst")"
  case "$target/" in "$TREE/"*) ;; *) echo "unsafe temporary edit target: $target" >&2; exit 2;; esac
  [ -f "$target" ] || { echo "missing temporary edit target: $dst" >&2; exit 2; }
  key="${dst//\//__}"
  [ ! -e "$SRC_BACKUP/$key" ] || { echo "duplicate temporary edit target: $dst" >&2; exit 2; }
  cp -a "$target" "$SRC_BACKUP/$key"
  MODIFIED+=("$dst")
}
install_src v4l2_codec2 external/v4l2_codec2
install_src ffmpeg external/ffmpeg
install_src ffmpeg_codec2 external/ffmpeg_codec2
install_src libudev_zero external/libudev-zero

python3 - "$TREE/external/v4l2_codec2/components/V4L2ComponentStore.cpp" <<'PYV4L2'
import sys
from pathlib import Path
p=Path(sys.argv[1]); s=p.read_text()
start=s.find("std::vector<std::shared_ptr<const C2Component::Traits>> V4L2ComponentStore::listComponents()")
if start<0: raise SystemExit("unexpected V4L2 Codec2 component store")
body=s.find("{",start); ret=s.find("    return ret;",body)
if body<0 or ret<0: raise SystemExit("unexpected V4L2 Codec2 listComponents body")
prefix=s[:body+1]
suffix=s[ret:]
new='''\n    std::vector<std::shared_ptr<const C2Component::Traits>> ret;
    ret.push_back(GetTraits(V4L2ComponentName::kH264Decoder));
'''
p.write_text(prefix+new+suffix)
PYV4L2

python3 - "$TREE/external/ffmpeg_codec2/service.cpp" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); s=p.read_text()
start=s.find("static const C2FFMPEGComponentInfo kFFMPEGVideoComponents[] = {")
end=s.find("\n};",start)
if start<0 or end<0: raise SystemExit("unexpected FFmpeg Codec2 video component table")
end+=3
table='''static const C2FFMPEGComponentInfo kFFMPEGVideoComponents[] = {
    { "c2.ffmpeg.hevc.decoder"  , MEDIA_MIMETYPE_VIDEO_HEVC  , AV_CODEC_ID_HEVC },
};'''
s=s[:start]+table+s[end:]
old='''static const size_t kNumAudioComponents =
    (sizeof(kFFMPEGAudioComponents) / sizeof(kFFMPEGAudioComponents[0]));'''
if old not in s: raise SystemExit("unexpected FFmpeg Codec2 audio component count")
s=s.replace(old,"static const size_t kNumAudioComponents = 0;",1)
p.write_text(s)
PY

if [ "${PITV_CODEC2_REQUIRE_BOOTSTRAP_REUSE:-0}" = "1" ]; then
  python3 "$HERE/check-codec2-bootstrap-checkpoint.py" "$TREE"
fi

if [ "$PHASE" = "diagnose" ]; then
  cd "$TREE"
  NINJA="$TREE/prebuilts/build-tools/linux-x86/bin/ninja"
  [ -x "$NINJA" ] || NINJA="$(command -v ninja)"
  echo "CODEC2_BOOTSTRAP_NINJA=${NINJA}"
  "$NINJA" -d explain -n -j1 -f out/soong/bootstrap.ninja out/host/linux-x86/bin/soong_build 2>&1 | tee /tmp/pitv-codec2-ninja-explain.log
  echo "CODEC2_BOOTSTRAP_DIAGNOSE_READY=1"
  exit 0
fi

cd "$TREE"
# Android envsetup/lunch scripts are not guaranteed to be nounset-clean.
set +u
# shellcheck disable=SC1091
source build/envsetup.sh
lunch "${PITV_CODEC2_LUNCH:-lineage_waydroid_arm64-userdebug}"
targets=(
  android.hardware.media.c2@1.0-service-v4l2-64
  libc2plugin_store
  android.hardware.media.c2@1.2-service-ffmpeg
  android.hardware.media.c2@1.2-ffmpeg.policy
  media_codecs_ffmpeg_c2.xml
)
if [ "$PHASE" = "narrow-list" ] || [ "$PHASE" = "narrow-probe" ] || [ "$PHASE" = "narrow-build" ]; then
  # Keep the disposable AVC graph native-only. Several HIDL interfaces generate
  # Java variants by default, and frameworks/av's root AIDL interface also
  # enables Java implicitly. Those variants are unrelated to the V4L2 service
  # but otherwise pull the full framework stub graph into this narrow build.
  NATIVE_ONLY_BP=(
    build/soong/cmd/soong_build/Android.bp
    frameworks/av/Android.bp
    hardware/interfaces/Android.bp
    hardware/interfaces/graphics/common/1.0/Android.bp
    hardware/interfaces/graphics/common/1.1/Android.bp
    hardware/interfaces/graphics/common/1.2/Android.bp
    hardware/interfaces/graphics/bufferqueue/1.0/Android.bp
    hardware/interfaces/graphics/bufferqueue/2.0/Android.bp
    hardware/interfaces/media/1.0/Android.bp
    system/libhidl/transport/base/1.0/Android.bp
    system/libhidl/transport/safe_union/1.0/Android.bp
    system/tools/hidl/build/Android.bp
  )
  for rel in "${NATIVE_ONLY_BP[@]}"; do prepare_temp_file_edit "$rel"; done
  python3 - "$TREE" "${NATIVE_ONLY_BP[@]}" <<'PYNATIVE'
import sys
from pathlib import Path

tree = Path(sys.argv[1])
for rel in sys.argv[2:]:
    p = tree / rel
    s = p.read_text()
    if rel == "build/soong/cmd/soong_build/Android.bp":
        # Direct soong_build still runs Blueprint's bootstrap singleton, which
        # requires exactly one primary builder module. The real soong_build
        # module pulls the complete Go bootstrap dependency tree into this
        # disposable AVC graph. Keep only a marker module: in direct
        # non-bootstrap generation Blueprint emits this as a phony target, so
        # no Go sources or deps are needed and the restored host soong_build
        # binary remains the process actually generating the graph.
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
        # The narrow Codec2 graph needs only frameworks_av_license from this
        # root file. av-types-aidl / av-headers are unrelated to the V4L2
        # service and pull the global AIDL metadata graph via aidl_metadata_json.
        marker = "\naidl_interface {"
        cut = s.find(marker)
        if cut < 0 or 'name: "frameworks_av_license"' not in s[:cut]:
            raise SystemExit("unexpected frameworks/av root structure")
        s = s[:cut].rstrip() + "\n"
    elif rel == "hardware/interfaces/Android.bp":
        # Keep only the package license, android.hardware package root and
        # hidl_defaults. VTS defaults are unrelated to the V4L2 service.
        marker = "\n// VTS tests"
        cut = s.find(marker)
        if cut < 0 or 'name: "android.hardware"' not in s[:cut] or 'name: "hidl_defaults"' not in s[:cut]:
            raise SystemExit("unexpected hardware/interfaces root structure")
        s = s[:cut].rstrip() + "\n"
    elif rel == "system/tools/hidl/build/Android.bp":
        # soong_build already contains the HIDL plugin from the restored
        # bootstrap checkpoint. Keep only the metadata singleton definition;
        # the bootstrap_go_package here would otherwise pull Blueprint/Soong.
        bootstrap = s.find("\nbootstrap_go_package {")
        metadata = s.find("\nhidl_interfaces_metadata {")
        if bootstrap < 0 or metadata < 0 or metadata <= bootstrap:
            raise SystemExit("unexpected HIDL build Android.bp structure")
        brace = s.find("{", metadata)
        depth = 0
        end = -1
        for i in range(brace, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end < 0:
            raise SystemExit("unterminated hidl_interfaces_metadata block")
        s = s[:bootstrap].rstrip() + "\n\n" + s[metadata + 1:end].strip() + "\n"
    else:
        if "gen_java: true," not in s:
            raise SystemExit(f"expected gen_java true in {rel}")
        s = s.replace("gen_java: true,", "gen_java: false,")
        s = s.replace("gen_java_constants: true,", "gen_java_constants: false,")
    p.write_text(s)
print("CODEC2_NARROW_NATIVE_ONLY_BP=1")
print("CODEC2_NARROW_PRIMARY_BUILDER_STUB=1")
PYNATIVE

  # AOSP soong_ui normally feeds soong_build every Android.bp in the tree via
  # out/.module_paths/Android.bp.list.  Build a conservative Codec2-focused
  # candidate list for the next direct-soong probe without mutating that file.
  FULL_LIST="$TREE/out/.module_paths/Android.bp.list"
  NARROW_LIST="$TREE/out/.module_paths/pitv-codec2.Android.bp.list"
  [ -s "$FULL_LIST" ] || { echo "missing Soong Android.bp.list checkpoint" >&2; exit 12; }
  python3 - "$FULL_LIST" "$NARROW_LIST" <<'PYNARROW'
import sys
from pathlib import Path
src, dst = map(Path, sys.argv[1:3])
prefixes = (
    "Android.bp",
    "external/v4l2_codec2/",
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
lines = [x.strip() for x in src.read_text().splitlines() if x.strip()]
primary_builder = "build/soong/cmd/soong_build/Android.bp"
hidl_tool = "system/tools/hidl/Android.bp"
excluded_prefixes = (
    "hardware/interfaces/automotive/",
    "hardware/interfaces/neuralnetworks/",
    "hardware/interfaces/graphics/common/aidl/",
    "hardware/interfaces/common/aidl/",
    "frameworks/native/services/surfaceflinger/Tracing/",
)
excluded_parts = (
    "/tests/",
    "/test/",
    "/vts/",
)
selected = sorted({
    x for x in lines
    if (x == "Android.bp" or x == primary_builder or x == hidl_tool or x.startswith(prefixes[1:]))
    and not x.startswith(excluded_prefixes)
    and not any(part in x for part in excluded_parts)
})
required = (
    "external/v4l2_codec2/Android.bp",
    primary_builder,
    hidl_tool,
)
missing = [x for x in required if x not in selected]
if missing:
    raise SystemExit("narrow Soong list missing required roots: " + ", ".join(missing))
dst.write_text("\n".join(selected) + "\n")
print(f"CODEC2_NARROW_BP_TOTAL={len(lines)}")
print(f"CODEC2_NARROW_BP_SELECTED={len(selected)}")
print(f"CODEC2_NARROW_BP_LIST={dst}")
PYNARROW
  # The pinned FFmpeg and ffmpeg_codec2 trees are Android.mk-only. This probe
  # intentionally validates only the native-Soong V4L2/AVC graph.
  [ -f "$TREE/external/ffmpeg_codec2/Android.mk" ] || { echo "missing FFmpeg Codec2 Android.mk" >&2; exit 12; }
  [ -f "$TREE/external/ffmpeg/Android.mk" ] || { echo "missing FFmpeg Android.mk" >&2; exit 12; }
  echo "CODEC2_NARROW_LIST_READY=1"
  if [ "$PHASE" = "narrow-list" ]; then exit 0; fi
  if [ "$PHASE" = "narrow-probe" ]; then
    python3 "$HERE/probe-narrow-soong-graph.py" "$TREE" "$NARROW_LIST"
    exit 0
  fi

  NARROW_NINJA="$TREE/out/soong/pitv-codec2.ninja"
  NINJA="$TREE/prebuilts/build-tools/linux-x86/bin/ninja"
  [ -x "$NINJA" ] || NINJA="$(command -v ninja)"
  REQUIRED_MODULES=""
  PREVIOUS_REQUIRED_MODULES=""
  for build_attempt in $(seq 1 "${PITV_CODEC2_NARROW_BUILD_ATTEMPTS:-16}"); do
    echo "CODEC2_NARROW_BUILD_ATTEMPT=$build_attempt"
    if [ -n "$REQUIRED_MODULES" ]; then
      export PITV_CODEC2_NARROW_REQUIRED_MODULES="$REQUIRED_MODULES"
    else
      unset PITV_CODEC2_NARROW_REQUIRED_MODULES || true
    fi

    python3 "$HERE/probe-narrow-soong-graph.py" "$TREE" "$NARROW_LIST"
    [ -s "$NARROW_NINJA" ] || { echo "missing narrow Soong ninja graph" >&2; exit 13; }

    target_inventory="$("$NINJA" -f "$NARROW_NINJA" -t targets all)"

    # HIDL-generated headers depend on the installed host hidl-gen path. A
    # direct narrow Soong graph can expose only the module/intermediate target,
    # without the normal full-build install edge. Build that exact host tool
    # first, close only its concrete missing dependencies, then promote the
    # resulting executable to the canonical HOST_OUT path expected by HIDL.
    hidl_gen="$TREE/out/host/linux-x86/bin/hidl-gen"
    if [ ! -x "$hidl_gen" ]; then
      hidl_line="$(printf '%s\n' "$target_inventory" | grep -m1 -E '(^|/)hidl-gen: ' || true)"
      if [ -z "$hidl_line" ]; then
        echo "CODEC2_NARROW_HIDL_GEN_TARGETS_BEGIN=1"
        printf '%s\n' "$target_inventory" | grep -E '(^|/)(hidl-gen|libhidl-gen[^/:]*): ' | head -80 || true
        echo "CODEC2_NARROW_HIDL_GEN_TARGETS_END=1"
        echo "narrow graph missing host hidl-gen build target" >&2
        exit 13
      fi
      hidl_target="${hidl_line%%: *}"
      echo "CODEC2_NARROW_HIDL_GEN_TARGET=$hidl_target"
      set +e
      hidl_output="$("$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$hidl_target" 2>&1)"
      hidl_rc=$?
      set -e
      [ -z "$hidl_output" ] || printf '%s\n' "$hidl_output"
      if [ "$hidl_rc" -ne 0 ]; then
        REQUIRED_MODULES="$(printf '%s\n' "$hidl_output" | python3 -c '
import re, sys
text = re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read())
mods = set()
for match in re.finditer(r"missing dependencies:\s*([^\n]+)", text, re.I):
    for raw in match.group(1).split(","):
        name = raw.strip().strip("\"\\047").rstrip(".;")
        if re.fullmatch(r"[A-Za-z0-9_.+@:/=-]+", name):
            mods.add(name)
print(",".join(sorted(mods)))
')"
        if [ -z "$REQUIRED_MODULES" ]; then
          echo "CODEC2_NARROW_HIDL_GEN_NINJA_RC=$hidl_rc"
          exit "$hidl_rc"
        fi
        echo "CODEC2_NARROW_HIDL_GEN_MISSING=$REQUIRED_MODULES"
        if [ "$REQUIRED_MODULES" = "$PREVIOUS_REQUIRED_MODULES" ]; then
          echo "narrow hidl-gen dependency closure made no progress" >&2
          exit "$hidl_rc"
        fi
        PREVIOUS_REQUIRED_MODULES="$REQUIRED_MODULES"
        continue
      fi
      case "$hidl_target" in
        /*) hidl_binary="$hidl_target" ;;
        *) hidl_binary="$TREE/$hidl_target" ;;
      esac
      [ -f "$hidl_binary" ] || {
        hidl_binary="$(find "$TREE/out/soong/.intermediates/system/tools/hidl" -type f -name hidl-gen -print -quit 2>/dev/null || true)"
      }
      [ -n "$hidl_binary" ] && [ -f "$hidl_binary" ] || {
        echo "host hidl-gen target built but executable was not found" >&2
        exit 13
      }
      mkdir -p "$(dirname "$hidl_gen")"
      cp -f "$hidl_binary" "$hidl_gen"
      chmod +x "$hidl_gen"
      echo "CODEC2_NARROW_HIDL_GEN_PROMOTED=$hidl_binary"
    fi

    target_line="$(printf '%s\n' "$target_inventory" | grep -m1 -E '(^|/)[^:]*android\.hardware\.media\.c2@1\.0-service-v4l2-64: ' || true)"
    if [ -z "$target_line" ]; then
      echo "CODEC2_NARROW_V4L2_TARGET_CANDIDATES_BEGIN=1"
      printf '%s\n' "$target_inventory" | grep -E 'android\.hardware\.media\.c2@1\.0-service-v4l2|libv4l2_codec2' | head -80 || true
      echo "CODEC2_NARROW_V4L2_TARGET_CANDIDATES_END=1"
      echo "narrow graph missing V4L2 AVC 64-bit build target" >&2
      exit 13
    fi
    avc_target="${target_line%%: *}"
    echo "CODEC2_NARROW_AVC_TARGET=$avc_target"

    # Build sysprop_cpp from the narrow Soong graph, not bootstrap.ninja.
    # LibGuiProperties requires this host executable before AVC can compile.
    host_sysprop_cpp="$TREE/out/host/linux-x86/bin/sysprop_cpp"
    if [ ! -x "$host_sysprop_cpp" ]; then
      # The host binary lives in Soong intermediates; promote it to HOST_OUT.
      sysprop_target="$(printf '%s\n' "$target_inventory" | grep -m1 -E '/sysprop_cpp/linux_glibc_x86_64/sysprop_cpp: ' || true)"
      sysprop_target="${sysprop_target%%: *}"
      if [ -z "$sysprop_target" ]; then
        echo "CODEC2_NARROW_SYSPROP_TARGET_MISSING=1" >&2
        exit 14
      fi
      echo "CODEC2_NARROW_SYSPROP_TARGET=$sysprop_target"
      set +e
      sysprop_output="$("$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$sysprop_target" 2>&1)"
      sysprop_rc=$?
      set -e
      [ -z "$sysprop_output" ] || printf '%s\n' "$sysprop_output"
      if [ "$sysprop_rc" -ne 0 ]; then
        sysprop_missing="$(printf '%s\n' "$sysprop_output" | python3 -c '
import re, sys
mods = set()
for match in re.finditer(r"missing dependencies:\s*([^\n]+)", sys.stdin.read(), re.I):
    for raw in match.group(1).split(","):
        name = raw.strip().strip(chr(34) + chr(39)).rstrip(".;")
        if re.fullmatch(r"[A-Za-z0-9_.+@:/=-]+", name):
            mods.add(name)
print(",".join(sorted(mods)))
')"
        if [ -n "$sysprop_missing" ]; then
          echo "CODEC2_NARROW_SYSPROP_MISSING=$sysprop_missing"
          REQUIRED_MODULES="${REQUIRED_MODULES:+$REQUIRED_MODULES,}$sysprop_missing"
          continue
        fi
        exit "$sysprop_rc"
      fi
      test -s "$sysprop_target"
      mkdir -p "$(dirname "$host_sysprop_cpp")"
      cp "$sysprop_target" "$host_sysprop_cpp"
      chmod +x "$host_sysprop_cpp"
      test -x "$host_sysprop_cpp"
      echo "CODEC2_NARROW_SYSPROP_READY=1"
    fi

    # The narrow graph does not always install the host AIDL C++ generator.
    # Resolve its real Soong target and promote it before Ninja preflight.
    host_aidl_cpp="$TREE/out/host/linux-x86/bin/aidl-cpp"
    if [ ! -x "$host_aidl_cpp" ]; then
      aidl_cpp_line="$(printf '%s\n' "$target_inventory" | grep -m1 -E '/aidl-cpp(/linux_glibc[^/]*)?/aidl-cpp: ' || true)"
      if [ -z "$aidl_cpp_line" ]; then
        echo "CODEC2_NARROW_AIDL_CPP_TARGET_MISSING=1" >&2
        printf '%s\n' "$target_inventory" | grep -E '/aidl-cpp[^:]*: ' | head -30 || true
        exit 14
      fi
      aidl_cpp_target="${aidl_cpp_line%%: *}"
      echo "CODEC2_NARROW_AIDL_CPP_TARGET=$aidl_cpp_target"
      set +e
      aidl_cpp_output="$("$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$aidl_cpp_target" 2>&1)"
      aidl_cpp_rc=$?
      set -e
      [ -z "$aidl_cpp_output" ] || printf '%s\n' "$aidl_cpp_output"
      if [ "$aidl_cpp_rc" -ne 0 ]; then
        aidl_cpp_missing="$(printf '%s\n' "$aidl_cpp_output" | python3 -c '
import re, sys
mods = set()
for match in re.finditer(r"missing dependencies:\s*([^\n]+)", sys.stdin.read(), re.I):
    for raw in match.group(1).split(","):
        name = raw.strip().strip(chr(34) + chr(39)).rstrip(".;")
        if re.fullmatch(r"[A-Za-z0-9_.+@:/=-]+", name):
            mods.add(name)
print(",".join(sorted(mods)))
')"
        if [ -n "$aidl_cpp_missing" ]; then
          echo "CODEC2_NARROW_AIDL_CPP_MISSING=$aidl_cpp_missing"
          REQUIRED_MODULES="${REQUIRED_MODULES:+$REQUIRED_MODULES,}$aidl_cpp_missing"
          continue
        fi
        exit "$aidl_cpp_rc"
      fi
      case "$aidl_cpp_target" in /*) aidl_cpp_binary="$aidl_cpp_target" ;; *) aidl_cpp_binary="$TREE/$aidl_cpp_target" ;; esac
      [ -s "$aidl_cpp_binary" ] || { echo "aidl-cpp build produced no executable" >&2; exit 14; }
      mkdir -p "$(dirname "$host_aidl_cpp")"
      cp "$aidl_cpp_binary" "$host_aidl_cpp"
      chmod +x "$host_aidl_cpp"
      echo "CODEC2_NARROW_AIDL_CPP_READY=1"
    fi

    # Preflight the entire concrete AVC dependency graph without compiling.
    # Ninja -n checks missing inputs and absent generating rules up front.
    # A canonical missing HOST_OUT tool can be closed by adding only its
    # Soong module to the next narrow-graph attempt. Do not expand arbitrary
    # intermediates here: that would pull unrelated framework/test graphs.
    echo "CODEC2_NARROW_PREFLIGHT_BEGIN=1"
    preflight_output="$("$NINJA" -n -f "$NARROW_NINJA" -j"$JOBS" "$avc_target" 2>&1)" || preflight_rc=$?
    preflight_rc="${preflight_rc:-0}"
    echo "CODEC2_NARROW_PREFLIGHT_RC=$preflight_rc"
    printf '%s\n' "$preflight_output" | python3 -c '
import re, sys
text = sys.stdin.read()
for line in text.splitlines():
    if re.search(r"ninja: error:|missing and no known rule|missing dependencies:", line, re.I):
        print("CODEC2_NARROW_PREFLIGHT_ISSUE=" + line[:600])
' || true
    for host_tool in hidl-gen aidl aidl-cpp sysprop_cpp ndkstubgen sbox merge_zips; do
      if [ -x "$TREE/out/host/linux-x86/bin/$host_tool" ]; then
        echo "CODEC2_NARROW_HOST_TOOL_OK=$host_tool"
      else
        echo "CODEC2_NARROW_HOST_TOOL_ABSENT=$host_tool"
      fi
    done
    echo "CODEC2_NARROW_PREFLIGHT_END=1"
    if [ "$preflight_rc" -ne 0 ]; then
      preflight_host_modules="$(printf '%s\n' "$preflight_output" | python3 -c '
import re, sys
text = re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read())
mods = set()
for line in text.splitlines():
    if "missing and no known rule to make it" not in line.lower():
        continue
    for match in re.finditer(r"[\047\"]([^\047\"]*/out/host/linux-x86/bin/([A-Za-z0-9_.+-]+))[\047\"]", line):
        mods.add(match.group(2))
print(",".join(sorted(mods)))
')"
      if [ -n "$preflight_host_modules" ]; then
        preflight_added=0
        IFS=',' read -r -a preflight_host_array <<< "$preflight_host_modules"
        for module in "${preflight_host_array[@]}"; do
case ",$REQUIRED_MODULES," in
  *",$module,"*) ;;
  *)
    REQUIRED_MODULES="${REQUIRED_MODULES:+$REQUIRED_MODULES,}$module"
    preflight_added=1
    ;;
esac
        done
        if [ "$preflight_added" -eq 1 ]; then
echo "CODEC2_NARROW_PREFLIGHT_HOST_MODULES=$preflight_host_modules"
unset preflight_rc
continue
        fi
        echo "CODEC2_NARROW_PREFLIGHT_HOST_MODULES_STALLED=$preflight_host_modules" >&2
      fi
      echo "CODEC2_NARROW_PREFLIGHT_BLOCKED=1" >&2
      printf '%s\n' "$preflight_output" | tail -80 >&2
      exit "$preflight_rc"
    fi
    unset preflight_rc

    set +e
    build_output="$("$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$avc_target" 2>&1)"
    build_rc=$?
    set -e
    [ -z "$build_output" ] || printf '%s\n' "$build_output"
    if [ "$build_rc" -eq 0 ]; then
      avc_binary="$TREE/$avc_target"
      if [ ! -f "$avc_binary" ]; then
        avc_binary="$(find "$TREE/out" -type f -name 'android.hardware.media.c2@1.0-service-v4l2-64' -print -quit)"
      fi
      [ -n "$avc_binary" ] && [ -f "$avc_binary" ] || { echo "narrow AVC binary was not produced" >&2; exit 13; }
      echo "CODEC2_NARROW_AVC_BINARY=$avc_binary"
      echo "CODEC2_NARROW_BUILD_READY=1"
      exit 0
    fi

    REQUIRED_MODULES="$(printf '%s\n' "$build_output" | python3 -c '
import re, sys
text = re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read())
mods = set()
for match in re.finditer(r"missing dependencies:\s*([^\n]+)", text, re.I):
    for raw in match.group(1).split(","):
        name = raw.strip().strip("\"\047").rstrip(".;")
        if re.fullmatch(r"[A-Za-z0-9_.+@:/=-]+", name):
            mods.add(name)
print(",".join(sorted(mods)))
')"
    if [ -z "$REQUIRED_MODULES" ]; then
      echo "CODEC2_NARROW_NINJA_RC=$build_rc"
      exit "$build_rc"
    fi
    echo "CODEC2_NARROW_NINJA_MISSING=$REQUIRED_MODULES"
    if [ "$REQUIRED_MODULES" = "$PREVIOUS_REQUIRED_MODULES" ]; then
      echo "narrow AVC dependency closure made no progress" >&2
      exit "$build_rc"
    fi
    PREVIOUS_REQUIRED_MODULES="$REQUIRED_MODULES"
  done
  echo "CODEC2_NARROW_BUILD_ATTEMPTS_EXHAUSTED=1" >&2
  exit 13
fi
if [ "$PHASE" = "graph" ]; then
  # Generate and validate the complete Soong/Kati graph without compiling target
  # modules. The workflow persists TREE/out as a permission-preserving tarball,
  # so a later runner can resume after this expensive global bootstrap.
  m --soong-only --skip-soong-tests --skip-ninja -j"$JOBS" "${targets[@]}"
  echo "CODEC2_GRAPH_READY=1"
  exit 0
fi
m --soong-only --skip-soong-tests -j"$JOBS" "${targets[@]}"

TREE="$(readlink -f "$TREE")"; SOURCES="$(readlink -f "$SOURCES")"; OUT="$(readlink -m "$OUT")"
[ "$OUT" != "/" ] && [ "$OUT" != "$TREE" ] && [ "$OUT" != "$SOURCES" ] || { echo "unsafe output directory" >&2; exit 2; }
case "$OUT/" in "$TREE/"*|"$SOURCES/"*) echo "output must not be inside build/source tree" >&2; exit 2;; esac
rm -rf "$OUT"; mkdir -p "$OUT"
PRODUCT_OUT="${ANDROID_PRODUCT_OUT:?ANDROID_PRODUCT_OUT missing after lunch/build}"
VENDOR_OUT="$PRODUCT_OUT/vendor"
mapfile -t avc_roots < <(find "$VENDOR_OUT" -type f -name 'android.hardware.media.c2@1.0-service-v4l2-64' | sort)
mapfile -t hevc_roots < <(find "$VENDOR_OUT" -type f -name 'android.hardware.media.c2@1.2-service-ffmpeg' | sort)
[ "${#avc_roots[@]}" -eq 1 ] || { echo "expected one AVC service output" >&2; exit 10; }
[ "${#hevc_roots[@]}" -eq 1 ] || { echo "expected one HEVC service output" >&2; exit 10; }
roots=("${avc_roots[0]#"$VENDOR_OUT"/}" "${hevc_roots[0]#"$VENDOR_OUT"/}")
python3 "$HERE/collect-codec2-prebuilt.py" "$VENDOR_OUT" "$OUT" "${roots[@]}"

# ELF DT_NEEDED does not carry init/VINTF/seccomp metadata. Copy only metadata
# installed by the two selected services, never the rest of donor vendor.
for pattern in \
  'android.hardware.media.c2@1.0-service-v4l2*.rc' \
  'android.hardware.media.c2@1.0-service-v4l2*.xml' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.rc' \
  'android.hardware.media.c2@1.2-service-ffmpeg*.xml' \
  '*v4l2*policy*' '*ffmpeg*policy*' 'android.hardware.media.c2@1.2-default-seccomp_policy' 'media_codecs_ffmpeg_c2.xml'
do
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    rel="${p#"$VENDOR_OUT"/}"
    payload_rel="vendor/$rel"
    mkdir -p "$OUT/$(dirname "$payload_rel")"
    cp -a "$p" "$OUT/$payload_rel"
    printf '%s\n' "$payload_rel" >>"$OUT/PITV-CODEC2-PAYLOAD.txt"
  done < <(find "$VENDOR_OUT" -type f -name "$pattern" | sort)
done
sort -u "$OUT/PITV-CODEC2-PAYLOAD.txt" -o "$OUT/PITV-CODEC2-PAYLOAD.txt"
python3 "$HERE/assemble-codec2-overlay.py" "$OUT" "$HERE/.."
python3 "$HERE/validate-codec2-payload.py" "$OUT"
python3 "$HERE/enforce-codec2-payload-scope.py" "$OUT"
python3 "$HERE/check-codec2-payload-size.py" "$OUT"
python3 "$HERE/inventory-codec2-payload.py" "$OUT"
python3 "$HERE/make-codec2-rollback-manifest.py" "$OUT"
python3 "$HERE/verify-codec2-metadata.py" "$OUT"
python3 "$HERE/codec2-payload-readiness.py" "$OUT"
python3 "$HERE/check-codec2-service-metadata.py" "$OUT"
echo "Minimal Codec2 build payload: $OUT"
