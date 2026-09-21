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
case "$PHASE" in all|graph|modules) ;; *) echo "invalid PITV_CODEC2_PHASE: $PHASE" >&2; exit 2;; esac
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
restore_sources(){
  for dst in "${MODIFIED[@]}"; do
    target="$TREE/$dst"; key="${dst//\//__}"
    rm -rf "$target"
    [ ! -e "$SRC_BACKUP/$key" ] || mv "$SRC_BACKUP/$key" "$target"
  done
  rm -rf "$SRC_BACKUP"
}
trap restore_sources EXIT INT TERM
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
if [ "$PHASE" = "graph" ]; then
  # Generate and validate the complete Soong/Kati graph without compiling target
  # modules. The workflow persists TREE/out as a permission-preserving tarball,
  # so a later runner can resume after this expensive global bootstrap.
  m --skip-soong-tests --skip-ninja -j"$JOBS" "${targets[@]}"
  echo "CODEC2_GRAPH_READY=1"
  exit 0
fi
m --skip-soong-tests -j"$JOBS" "${targets[@]}"

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
