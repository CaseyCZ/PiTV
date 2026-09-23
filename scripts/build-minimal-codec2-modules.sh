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
    frameworks/av/Android.bp
    hardware/interfaces/Android.bp
    system/tools/hidl/Android.bp
    system/libhidl/Android.bp
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
    if rel == "frameworks/av/Android.bp":
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
    elif rel == "system/tools/hidl/Android.bp":
        # Generated HIDL C++ modules need the package/license plus
        # hidl-module-defaults. Keep host hidl-gen libraries out of the narrow
        # graph while preserving system_tools_hidl_license for hidl_metadata_json.
        if 'name: "hidl-module-defaults"' not in s or 'name: "system_tools_hidl_license"' not in s:
            raise SystemExit("unexpected system/tools/hidl root structure")
        s = '''package {
    default_applicable_licenses: ["system_tools_hidl_license"],
}

license {
    name: "system_tools_hidl_license",
    visibility: [":__subpackages__"],
    license_kinds: [
        "SPDX-license-identifier-Apache-2.0",
    ],
    license_text: [
        "NOTICE",
    ],
}

cc_defaults {
    name: "hidl-module-defaults",
    cflags: [
        "-Wall",
        "-Werror",
        "-Wextra-semi",
    ],
    tidy_checks: [
        "-performance-unnecessary-value-param",
    ],
    product_variables: {
        debuggable: {
            cflags: ["-D__ANDROID_DEBUGGABLE__"],
        },
    },
}
'''
    elif rel == "system/libhidl/Android.bp":
        # Source HIDL interfaces need only the package license from this root.
        # libhidlbase and its tests are real platform modules, but not required
        # merely to generate the C++ interface modules used by this narrow graph.
        marker = "\ncc_defaults {"
        cut = s.find(marker)
        if cut < 0 or 'name: "system_libhidl_license"' not in s[:cut]:
            raise SystemExit("unexpected system/libhidl root structure")
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
    if (x == "Android.bp" or x.startswith(prefixes[1:]))
    and not x.startswith(excluded_prefixes)
    and not any(part in x for part in excluded_parts)
})
required = (
    "external/v4l2_codec2/Android.bp",
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
  python3 "$HERE/probe-narrow-soong-graph.py" "$TREE" "$NARROW_LIST"
  if [ "$PHASE" = "narrow-probe" ]; then exit 0; fi

  NARROW_NINJA="$TREE/out/soong/pitv-codec2.ninja"
  NINJA="$TREE/prebuilts/build-tools/linux-x86/bin/ninja"
  [ -x "$NINJA" ] || NINJA="$(command -v ninja)"
  [ -s "$NARROW_NINJA" ] || { echo "missing narrow Soong ninja graph" >&2; exit 13; }
  target_line="$("$NINJA" -f "$NARROW_NINJA" -t targets all | grep -m1 -E '(^|/)vendor/bin/hw/android\.hardware\.media\.c2@1\.0-service-v4l2-64: ' || true)"
  [ -n "$target_line" ] || { echo "narrow graph missing V4L2 AVC 64-bit install target" >&2; exit 13; }
  avc_target="${target_line%%: *}"
  echo "CODEC2_NARROW_AVC_TARGET=$avc_target"
  "$NINJA" -f "$NARROW_NINJA" -j"$JOBS" "$avc_target"
  [ -f "$TREE/$avc_target" ] || { echo "narrow AVC target was not produced: $avc_target" >&2; exit 13; }
  echo "CODEC2_NARROW_AVC_BINARY=$TREE/$avc_target"
  echo "CODEC2_NARROW_BUILD_READY=1"
  exit 0
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
