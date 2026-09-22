#!/usr/bin/env bash
set -euo pipefail
# Keep this script quiet on success; CI failures are diagnosed by line number.
trap 'echo "Codec2 static check failed at line $LINENO" >&2' ERR
PY=(
 scripts/probe-codec2-prebuilt.py
 scripts/collect-codec2-prebuilt.py
 scripts/assemble-codec2-overlay.py
 scripts/validate-codec2-payload.py
 scripts/verify-staged-codec2-payload.py
 scripts/make-codec2-rollback-manifest.py
 scripts/preflight-codec2-overlay.py
 scripts/test-codec2-no-full-build.py
 scripts/plan-codec2-backup.py
 scripts/check-codec2-payload-contract.py
 scripts/fetch-minimal-codec2-sources.py
 scripts/check-minimal-codec2-source-lock.py
 scripts/audit-codec2-payload-deps.py
 scripts/register-pitv-codec2-config.py
 scripts/inventory-codec2-payload.py
 scripts/evaluate-codec2-target.py
 scripts/enforce-codec2-payload-scope.py
 scripts/codec2-payload-readiness.py
 scripts/verify-codec2-metadata.py
 scripts/check-codec2-payload-size.py
 scripts/check-codec2-service-metadata.py
 scripts/check-codec2-manifest-closure.py
 scripts/verify-minimal-codec2-sources.py
 scripts/check-codec2-xml-contract.py
 scripts/check-codec2-bootstrap-checkpoint.py
 scripts/probe-narrow-soong-graph.py
)
SH=(
 scripts/probe-waydroid-codec2-target.sh
 scripts/guard-codec2-build-workspace.sh
 scripts/stage-codec2-payload.sh
 scripts/plan-codec2-overlay-install.sh
 scripts/prepare-codec2-overlay.sh
 scripts/install-codec2-overlay.sh
 scripts/rollback-codec2-overlay.sh
 scripts/build-minimal-codec2-modules.sh
 scripts/codec2-no-full-build.sh
 scripts/verify-codec2-runtime.sh
 scripts/extract-codec2-donor-image.sh
 scripts/prepare-codec2-from-donor.sh
 scripts/add-pitv-codec2-config-to-payload.sh
 scripts/accept-codec2-overlay-runtime.sh
 scripts/codec2-install-readiness.sh
 scripts/capture-codec2-evidence.sh
)
python3 -m py_compile "${PY[@]}"
python3 scripts/check-minimal-codec2-source-lock.py >/dev/null
python3 scripts/check-codec2-xml-contract.py >/dev/null
for f in "${SH[@]}"; do bash -n "$f"; done
grep -q 'never writes to Waydroid' scripts/probe-codec2-prebuilt.py
grep -q 'No Waydroid files are changed' scripts/collect-codec2-prebuilt.py
grep -q 'refusing risky donor dependency' scripts/collect-codec2-prebuilt.py
grep -q 'only reads state' scripts/probe-waydroid-codec2-target.sh
grep -q 'refusing full-build workspace' scripts/guard-codec2-build-workspace.sh
grep -q 'DRY RUN ONLY' scripts/plan-codec2-overlay-install.sh
grep -q 'restore; RESTORE=0; exit 20' scripts/install-codec2-overlay.sh
grep -q 'audit-codec2-payload-deps.py' scripts/install-codec2-overlay.sh
grep -q 'ro.vendor.v4l2_codec2.decode_concurrent_instances=4' scripts/install-codec2-overlay.sh
grep -q 'dumpsys media.codec' scripts/install-codec2-overlay.sh
grep -q 'c2.v4l2.avc.decoder' scripts/install-codec2-overlay.sh
grep -q 'c2.ffmpeg.hevc.decoder' scripts/install-codec2-overlay.sh
grep -q 'sha256sum -c SHA256SUMS' scripts/rollback-codec2-overlay.sh
! grep -Eq 'waydroid (init|session|container)|systemctl (start|stop|restart).*waydroid|mount ' scripts/stage-codec2-payload.sh
! grep -Eq 'cp .* /vendor|mount |waydroid init|systemctl restart' scripts/plan-codec2-overlay-install.sh

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/payload/vendor/lib64"
printf x >"$tmp/payload/vendor/lib64/libfixture.so"
printf 'vendor/lib64/libfixture.so\n' >"$tmp/payload/PITV-CODEC2-PAYLOAD.txt"
python3 scripts/validate-codec2-payload.py "$tmp/payload" >/dev/null
python3 scripts/verify-staged-codec2-payload.py "$tmp/payload" >/dev/null
python3 scripts/enforce-codec2-payload-scope.py "$tmp/payload" >/dev/null
python3 scripts/check-codec2-manifest-closure.py "$tmp/payload" >/dev/null
python3 scripts/check-codec2-payload-size.py "$tmp/payload" >/dev/null
python3 scripts/inventory-codec2-payload.py "$tmp/payload" >/dev/null
python3 scripts/make-codec2-rollback-manifest.py "$tmp/payload" >/dev/null
python3 scripts/verify-codec2-metadata.py "$tmp/payload" >/dev/null
python3 scripts/check-codec2-payload-size.py "$tmp/payload" >/dev/null
if bash scripts/plan-codec2-overlay-install.sh "$tmp/payload" >/dev/null 2>&1; then
  echo "fixture without codec ELF/service metadata unexpectedly became install-ready" >&2
  exit 1
fi
grep -q 'vendor/lib64/libfixture.so' "$tmp/payload/PITV-CODEC2-PAYLOAD.txt" "$tmp/payload/PITV-CODEC2-INSTALL-PLAN.txt"
python3 scripts/test-codec2-no-full-build.py
echo "Codec2 no-full-build helper checks OK"
grep -q 'never runs repo init/sync' scripts/build-minimal-codec2-modules.sh
bash scripts/codec2-no-full-build.sh help | grep -q 'build-modules'
bash scripts/codec2-no-full-build.sh help | grep -q 'accept'
grep -q '"backup_required":True\|"backup_required": True' scripts/make-codec2-rollback-manifest.py
grep -q -- '--read-only' scripts/extract-codec2-donor-image.sh
grep -q 'prepare-donor' scripts/codec2-no-full-build.sh
grep -q 'Read-only' scripts/preflight-codec2-overlay.py
grep -q 'media_codecs_ffmpeg_c2.xml' scripts/add-pitv-codec2-config-to-payload.sh
grep -q 'codec2.vendor.ext.policy' scripts/add-pitv-codec2-config-to-payload.sh
grep -q 'dumpsys media.codec' scripts/accept-codec2-overlay-runtime.sh
grep -q 'c2.v4l2.avc.decoder' scripts/accept-codec2-overlay-runtime.sh
grep -q 'c2.ffmpeg.hevc.decoder' scripts/accept-codec2-overlay-runtime.sh
grep -q 'vendor.prop.*pitv-codec2.prop' scripts/assemble-codec2-overlay.py
grep -q 'register-pitv-codec2-config.py' scripts/add-pitv-codec2-config-to-payload.sh
bash scripts/codec2-no-full-build.sh help | grep -q 'add-config'
grep -q 'CODEC2_REGISTRY' scripts/probe-waydroid-codec2-target.sh
grep -q 'TARGET_PREREQUISITES_OK' scripts/evaluate-codec2-target.py
bash scripts/codec2-no-full-build.sh help | grep -q 'target-check'
grep -q 'plan-codec2-backup.py' scripts/install-codec2-overlay.sh
grep -q 'preflight-codec2-overlay.py' scripts/install-codec2-overlay.sh
grep -q 'enforce-codec2-payload-scope.py' scripts/install-codec2-overlay.sh
grep -q 'forbidden donor HAL surface' scripts/enforce-codec2-payload-scope.py
grep -q 'PAYLOAD_READY_FOR_TARGET_PREFLIGHT' scripts/codec2-payload-readiness.py
grep -q 'codec2-payload-readiness.py' scripts/prepare-codec2-overlay.sh
bash scripts/codec2-no-full-build.sh help | grep -q 'readiness PAYLOAD'
grep -q 'codec2-payload-readiness.py' scripts/install-codec2-overlay.sh
grep -q 'codec2-payload-readiness.py' scripts/stage-codec2-payload.sh
grep -q 'enforce-codec2-payload-scope.py' scripts/stage-codec2-payload.sh
grep -q 'verify-codec2-metadata.py' scripts/prepare-codec2-overlay.sh
grep -q 'codec2-payload-readiness.py' scripts/plan-codec2-overlay-install.sh
grep -q 'verify-codec2-metadata.py' scripts/install-codec2-overlay.sh
grep -q 'verify-codec2-metadata.py' scripts/stage-codec2-payload.sh
grep -q 'check-codec2-payload-size.py' scripts/install-codec2-overlay.sh
grep -q 'MAX_TOTAL=512' scripts/check-codec2-payload-size.py
grep -q 'codec2-payload-readiness.py' scripts/prepare-codec2-from-donor.sh
grep -q 'verify-codec2-metadata.py' scripts/prepare-codec2-from-donor.sh
grep -q 'codec2-payload-readiness.py' scripts/build-minimal-codec2-modules.sh
grep -q 'verify-codec2-metadata.py' scripts/build-minimal-codec2-modules.sh
grep -q 'v4l2_rank_property' scripts/accept-codec2-overlay-runtime.sh
grep -q 'c2_poolmask_property' scripts/accept-codec2-overlay-runtime.sh
bash scripts/codec2-no-full-build.sh help | grep -q 'install-readiness PAYLOAD'
grep -q 'CODEC2_READY_TO_INSTALL=1' scripts/codec2-install-readiness.sh
grep -q 'pitv-waydroid-device-patch --remove' scripts/rollback-codec2-overlay.sh
grep -q 'check-codec2-service-metadata.py' scripts/install-codec2-overlay.sh
grep -q 'check-codec2-service-metadata.py' scripts/codec2-install-readiness.sh
grep -q 'check-codec2-manifest-closure.py' scripts/install-codec2-overlay.sh
grep -q 'check-codec2-manifest-closure.py' scripts/prepare-codec2-overlay.sh
grep -q 'VINTF metadata missing Codec2 instance' scripts/check-codec2-service-metadata.py
grep -q 'check-codec2-manifest-closure.py' scripts/stage-codec2-payload.sh
grep -q 'check-codec2-payload-size.py' scripts/stage-codec2-payload.sh
grep -q 'check-codec2-manifest-closure.py' scripts/plan-codec2-overlay-install.sh
grep -q 'verify-codec2-metadata.py' scripts/plan-codec2-overlay-install.sh
grep -q 'check-codec2-manifest-closure.py' scripts/codec2-install-readiness.sh
grep -q 'pitv-waydroid-device-patch --remove' scripts/install-codec2-overlay.sh
grep -q 'mkdir -p "\$STATE"' scripts/install-codec2-overlay.sh
grep -q '/usr/local/libexec/pitv-waydroid-device-patch --remove' scripts/rollback-codec2-overlay.sh
grep -q 'verify-minimal-codec2-sources.py' scripts/build-minimal-codec2-modules.sh
grep -q 'last_rollback=' scripts/codec2-no-full-build.sh
grep -q 'current_stage=' scripts/codec2-no-full-build.sh
grep -q 'verify-minimal-codec2-sources.py' scripts/fetch-minimal-codec2-sources.py
grep -q 'v4l2_rank=' scripts/verify-codec2-runtime.sh
grep -q 'c2_poolmask=' scripts/verify-codec2-runtime.sh
bash scripts/codec2-no-full-build.sh help | grep -q 'evidence \[OUT\]'
grep -q 'last_evidence=' scripts/codec2-no-full-build.sh
grep -q 'check-codec2-xml-contract.py' scripts/prepare-codec2-overlay.sh
grep -q 'check-codec2-xml-contract.py' scripts/build-minimal-codec2-modules.sh
grep -q 'remaining external prerequisite is a real compatible codec payload' docs/experiments/rpi4-codec2-no-full-build.md
grep -q 'android.hardware.media.c2@1.2-ffmpeg.policy' scripts/build-minimal-codec2-modules.sh
grep -q 'ffmpeg_codec2.*Android.mk' scripts/verify-minimal-codec2-sources.py
grep -q 'service/android.hardware.media.c2@1.0-service-v4l2-64.rc' scripts/verify-minimal-codec2-sources.py
grep -q 'avc_service.*vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2' scripts/codec2-payload-readiness.py
grep -q 'hevc_service.*vendor/bin/hw/android.hardware.media.c2@1.2-service-ffmpeg' scripts/codec2-payload-readiness.py
grep -q 'both codec service ELF binaries' scripts/codec2-payload-readiness.py
grep -q 'payload path escapes root' scripts/check-codec2-payload-size.py
grep -q 'metadata path escapes payload' scripts/verify-codec2-metadata.py
grep -q 'init metadata missing exact service path' scripts/check-codec2-service-metadata.py
grep -q 'check-codec2-service-metadata.py' scripts/prepare-codec2-from-donor.sh
grep -q 'check-codec2-service-metadata.py' scripts/build-minimal-codec2-modules.sh
grep -q 'v4l2_instances_property' scripts/accept-codec2-overlay-runtime.sh
grep -q 'source commit mismatch' scripts/verify-minimal-codec2-sources.py
grep -q 'source origin mismatch' scripts/verify-minimal-codec2-sources.py
grep -q 'refusing dirty source checkout' scripts/fetch-minimal-codec2-sources.py
grep -q 'android_video_nodes' scripts/accept-codec2-overlay-runtime.sh
grep -q 'v4l2_instances=' scripts/verify-codec2-runtime.sh
grep -q '/dev/video not visible in Android' scripts/install-codec2-overlay.sh
grep -q 'unsafe output directory' scripts/prepare-codec2-overlay.sh
grep -q 'dynamic/super donor image detected' scripts/extract-codec2-donor-image.sh
grep -q 'backup must be inside' scripts/rollback-codec2-overlay.sh
grep -q 'restored vendor image mismatch' scripts/rollback-codec2-overlay.sh
grep -q 'android.hardware.media.c2@1.0-service-v4l2-64' scripts/build-minimal-codec2-modules.sh
grep -q 'output must not be inside build/source tree' scripts/build-minimal-codec2-modules.sh
grep -q 'media_codecs_pitv_rpi4.xml' scripts/assemble-codec2-overlay.py
grep -q 'Preserve the target.*existing codec registry' scripts/install-codec2-overlay.sh
! grep -q '"android/waydroid-rpi4/media_codecs.xml":"vendor/etc/media_codecs.xml"' scripts/assemble-codec2-overlay.py
grep -q 'media_codecs_pitv_rpi4.xml' scripts/codec2-payload-readiness.py
grep -q 'media_codecs_pitv_rpi4.xml' scripts/register-pitv-codec2-config.py
grep -q 'media_codecs_pitv_rpi4.xml' scripts/add-pitv-codec2-config-to-payload.sh
grep -q 'metadata path is a symlink' scripts/verify-codec2-metadata.py
grep -q 'payload entry is a symlink' scripts/check-codec2-payload-size.py
grep -q 'manifest symlink rejected' scripts/check-codec2-manifest-closure.py
grep -q 'p.is_file() and iself(p)' scripts/audit-codec2-payload-deps.py
grep -q 'unsafe OUT path' scripts/collect-codec2-prebuilt.py
grep -q 'ELF outside ROOT' scripts/probe-codec2-prebuilt.py
grep -q 'media_codecs_ffmpeg_c2.xml' scripts/prepare-codec2-from-donor.sh
grep -q 'output must not be inside donor tree' scripts/prepare-codec2-from-donor.sh
grep -q 'CONFIG_V4L2_REQUEST=yes' scripts/verify-minimal-codec2-sources.py
grep -q 'CONFIG_HEVC_V4L2REQUEST_HWACCEL=yes' scripts/verify-minimal-codec2-sources.py
grep -q 'android.hardware.media.c2@1.2-ffmpeg.policy' scripts/codec2-payload-readiness.py
grep -q 'installed payload hash mismatch' scripts/install-codec2-overlay.sh
grep -q 'unsafe source install target' scripts/build-minimal-codec2-modules.sh
grep -q 'media_codecs_ffmpeg_c2.xml' scripts/build-minimal-codec2-modules.sh
grep -q 'evidence output already exists' scripts/capture-codec2-evidence.sh
grep -Fq 'BACKUP="$STATE/backups/${STAMP}-$"' scripts/install-codec2-overlay.sh
grep -q 'check-codec2-payload-contract.py' scripts/codec2-install-readiness.sh
grep -q '"android_video_nodes"' scripts/evaluate-codec2-target.py
grep -q 'staged path is a symlink' scripts/verify-staged-codec2-payload.py
grep -q 'manifest symlink rejected' scripts/validate-codec2-payload.py
grep -q 'unsafe payload path' scripts/enforce-codec2-payload-scope.py
grep -q 'inventory symlink rejected' scripts/inventory-codec2-payload.py
grep -q 'unsafe rollback path' scripts/make-codec2-rollback-manifest.py
grep -q 'target symlink rejected' scripts/preflight-codec2-overlay.py
grep -q 'check-codec2-service-metadata.py' scripts/plan-codec2-overlay-install.sh
grep -q 'unsafe staging state' scripts/stage-codec2-payload.sh
grep -q 'check-codec2-service-metadata.py' scripts/stage-codec2-payload.sh
grep -Fq 'dest="$STATE/staged/${stamp}-$"' scripts/stage-codec2-payload.sh
grep -q 'missing exact codec contract' scripts/check-codec2-payload-contract.py
grep -q 'service-v4l2-64' scripts/codec2-payload-readiness.py
grep -q 'service-v4l2-64' scripts/check-codec2-service-metadata.py
grep -q 'service-v4l2-64' scripts/prepare-codec2-from-donor.sh
grep -q "name 'android.hardware.media.c2@1.0-service-v4l2-64'" scripts/build-minimal-codec2-modules.sh
grep -q 'payload path is a symlink' scripts/enforce-codec2-payload-scope.py
grep -q '@1.0::IComponentStore/v4l2' scripts/check-codec2-service-metadata.py
grep -q '"android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml":"vendor/etc/media_codecs_ffmpeg_c2.xml"' scripts/assemble-codec2-overlay.py
grep -q 'staged payload contains symlink' scripts/stage-codec2-payload.sh
grep -q 'invalid rollback manifest schema' scripts/preflight-codec2-overlay.py
grep -q 'duplicate preflight target' scripts/plan-codec2-backup.py
grep -q 'rollback payload symlink rejected' scripts/make-codec2-rollback-manifest.py
grep -q 'duplicate rollback path' scripts/make-codec2-rollback-manifest.py
grep -q 'duplicate inventory path' scripts/inventory-codec2-payload.py
grep -q 'unsupported metadata version' scripts/verify-codec2-metadata.py
grep -q 'duplicate rollback metadata' scripts/verify-codec2-metadata.py
grep -q 'codec XML escapes stage' scripts/check-codec2-payload-contract.py
grep -q 'metadata symlink rejected' scripts/check-codec2-service-metadata.py
! grep -q 'waydroid init -f || fail' scripts/install-codec2-overlay.sh
grep -q 'forcing waydroid init here can replace them' scripts/install-codec2-overlay.sh
grep -q 'AMBIGUOUS' scripts/audit-codec2-payload-deps.py
grep -q 'byte-identical' scripts/audit-codec2-payload-deps.py
grep -q 'insufficient free space for rollback-safe Codec2 install' scripts/install-codec2-overlay.sh
grep -q 'STAGE="$(readlink -f' scripts/install-codec2-overlay.sh
grep -q 'donor exceeds extraction limit' scripts/extract-codec2-donor-image.sh
grep -q 'refusing symlink output' scripts/extract-codec2-donor-image.sh
grep -q 'lpunpack required for dynamic/super donor image' scripts/extract-codec2-donor-image.sh
grep -q 'super image must contain exactly one vendor image' scripts/extract-codec2-donor-image.sh
grep -q 'restore_sources' scripts/build-minimal-codec2-modules.sh
grep -q 'pitv-codec2-src-backup' scripts/build-minimal-codec2-modules.sh
grep -q 'MODIFIED=()' scripts/build-minimal-codec2-modules.sh
grep -q 'MODIFIED+=("$dst")' scripts/build-minimal-codec2-modules.sh
grep -q 'v4l2_seccomp_base' scripts/codec2-payload-readiness.py
grep -q 'android.hardware.media.c2@1.2-default-seccomp_policy' scripts/build-minimal-codec2-modules.sh
grep -q 'android.hardware.media.c2@1.2-default-seccomp_policy' scripts/prepare-codec2-from-donor.sh
grep -q 'V4L2 Codec2 seccomp contract missing' scripts/verify-minimal-codec2-sources.py
grep -q 'active-vendor-path' scripts/install-codec2-overlay.sh
grep -q 'backup vendor path missing' scripts/rollback-codec2-overlay.sh
grep -q 'unsafe backup vendor path' scripts/rollback-codec2-overlay.sh
! grep -q '^waydroid init -f$' scripts/rollback-codec2-overlay.sh
grep -q 'refusing immutable/unsupported Waydroid vendor image path' scripts/install-codec2-overlay.sh
grep -q 'active_vendor_path=' scripts/codec2-no-full-build.sh
grep -q '^persist.ffmpeg_codec2.v4l2.h265=1$' android/waydroid-rpi4/vendor.prop
grep -q 'FFmpeg HEVC V4L2 Request property not active' scripts/install-codec2-overlay.sh
grep -q 'ffmpeg_hevc_v4l2_request=' scripts/verify-codec2-runtime.sh
grep -q 'ffmpeg_hevc_v4l2_request_property' scripts/accept-codec2-overlay-runtime.sh
grep -q 'persist.ffmpeg_codec2.v4l2.h265=1' scripts/codec2-payload-readiness.py
grep -q 'payload properties incomplete' scripts/codec2-payload-readiness.py
grep -q 'kNumAudioComponents = 0' scripts/build-minimal-codec2-modules.sh
grep -q 'c2.ffmpeg.hevc.decoder' scripts/build-minimal-codec2-modules.sh
grep -q 'kH264Decoder' scripts/build-minimal-codec2-modules.sh
grep -q 'unexpected V4L2 Codec2 component store' scripts/build-minimal-codec2-modules.sh
grep -q 'payload_rel=Path("vendor")/rel' scripts/collect-codec2-prebuilt.py
grep -q 'payload_rel="vendor/$rel"' scripts/prepare-codec2-from-donor.sh
grep -q 'payload_rel="vendor/$rel"' scripts/build-minimal-codec2-modules.sh
grep -q '^copy android/waydroid-rpi4/media_codecs_ffmpeg_c2.xml vendor/etc/media_codecs_ffmpeg_c2.xml' scripts/add-pitv-codec2-config-to-payload.sh
grep -q 'android.hardware.media.c2@1.2-default-seccomp_policy' scripts/prepare-codec2-overlay.sh
grep -q 'payload_rel="vendor/$rel"' scripts/prepare-codec2-overlay.sh
grep -q 'fresh=False' scripts/fetch-minimal-codec2-sources.py
grep -q 'checkout","--detach","--force"' scripts/fetch-minimal-codec2-sources.py

# build-trigger: pinned source checkout fix

# [build-codec2] rerun with fresh-clone fix

# [build-codec2] run with corrected fetcher and green static checks

grep -q '"ffmpeg":\["Android.mk"' scripts/verify-minimal-codec2-sources.py

# [build-codec2] FFmpeg Android.mk verifier fixed

grep -Fq 'bash "$HERE/guard-codec2-build-workspace.sh" "$TREE"' scripts/build-minimal-codec2-modules.sh

# [build-codec2] retry after portable guard invocation

grep -q -- '--skip-soong-tests' scripts/build-minimal-codec2-modules.sh

# Reduced build generates the graph with Soong only; Kati/Make is unnecessary
# for the selected Android.bp Codec2 targets.
grep -q 'PITV_CODEC2_PHASE' scripts/build-minimal-codec2-modules.sh
grep -q 'CODEC2_GRAPH_READY=1' scripts/build-minimal-codec2-modules.sh
grep -Fq 'm --soong-only --skip-soong-tests --skip-ninja -j"$JOBS"' scripts/build-minimal-codec2-modules.sh
grep -Fq 'm --soong-only --skip-soong-tests -j"$JOBS"' scripts/build-minimal-codec2-modules.sh
grep -q -- 'tar --zstd -xf codec2-graph-checkpoint/codec2-graph-state.tar.zst' .github/workflows/codec2-no-full-build-check.yml
! grep -q -- 'tar --zstd --touch -xf' .github/workflows/codec2-no-full-build-check.yml
grep -q 'codec2-bootstrap:' .github/workflows/codec2-no-full-build-check.yml
grep -q 'timeout --signal=TERM --kill-after=15s 90s env PITV_CODEC2_PHASE=graph' .github/workflows/codec2-no-full-build-check.yml
grep -Fq 'name: pitv-codec2-bootstrap-${{ github.sha }}' .github/workflows/codec2-no-full-build-check.yml
grep -q 'Restore warmed Soong bootstrap' .github/workflows/codec2-no-full-build-check.yml
test "$(grep -Fc 'needs: [static, codec2-bootstrap]' .github/workflows/codec2-no-full-build-check.yml)" -eq 1
! grep -q '^  codec2-graph-warmup:' .github/workflows/codec2-no-full-build-check.yml
! grep -q '^  codec2-graph-warmup-2:' .github/workflows/codec2-no-full-build-check.yml


# A restored bootstrap must keep pinned build definitions older than the
# checkpoint manifest, otherwise Soong recompiles all bootstrap Go tools.
grep -q 'PITV_CODEC2_SOURCE_EPOCH' scripts/build-minimal-codec2-modules.sh
grep -q "name 'Android.bp'" scripts/build-minimal-codec2-modules.sh
grep -q 'check-codec2-bootstrap-checkpoint.py' scripts/build-minimal-codec2-modules.sh
grep -q 'SOURCES_RESTORED=0' scripts/build-minimal-codec2-modules.sh
grep -q 'trap - EXIT INT TERM' scripts/build-minimal-codec2-modules.sh
grep -Fq "trap 'restore_sources; exit 130' INT" scripts/build-minimal-codec2-modules.sh
grep -Fq "trap 'restore_sources; exit 143' TERM" scripts/build-minimal-codec2-modules.sh
test "$(grep -c 'PITV_CODEC2_REQUIRE_BOOTSTRAP_REUSE: 1' .github/workflows/codec2-no-full-build-check.yml)" -eq 4
test "$(grep -c 'PITV_CODEC2_NORMALIZE_BOOTSTRAP_REUSE: 1' .github/workflows/codec2-no-full-build-check.yml)" -eq 4
test "$(grep -c 'repo manifest -r > "\${GITHUB_WORKSPACE}/pitv-source-manifest.xml"' .github/workflows/codec2-no-full-build-check.yml)" -eq 5
grep -Fq 'cp "${GITHUB_WORKSPACE}/pitv-source-manifest.xml" "$TREE/out/soong/pitv-source-manifest.xml"' .github/workflows/codec2-no-full-build-check.yml
test "$(grep -c 'cmp "$TREE/out/soong/pitv-source-manifest.xml"' .github/workflows/codec2-no-full-build-check.yml)" -eq 4
grep -q 'all|graph|modules|diagnose' scripts/build-minimal-codec2-modules.sh
grep -q 'CODEC2_BOOTSTRAP_DIAGNOSE_READY=1' scripts/build-minimal-codec2-modules.sh
grep -Fq '"$NINJA" -d explain -n' scripts/build-minimal-codec2-modules.sh
grep -q 'codec2-reuse-diagnose:' .github/workflows/codec2-no-full-build-check.yml
grep -q "contains(github.event.head_commit.message, '\[diagnose-codec2\]')" .github/workflows/codec2-no-full-build-check.yml
grep -q 'run-id: 35591736044' .github/workflows/codec2-no-full-build-check.yml

mkdir -p "$tmp/bootstrap-ok/out/soong" "$tmp/bootstrap-ok/out/host/linux-x86/bin" "$tmp/bootstrap-ok/external/v4l2_codec2"
printf 'x\n' >"$tmp/bootstrap-ok/external/v4l2_codec2/Android.bp"
printf 'out/soong/bootstrap.ninja: external/v4l2_codec2/Android.bp\n' >"$tmp/bootstrap-ok/out/soong/bootstrap.ninja.d"
printf 'ninja\n' >"$tmp/bootstrap-ok/out/soong/bootstrap.ninja"
printf '#!/bin/sh\n' >"$tmp/bootstrap-ok/out/host/linux-x86/bin/soong_build"
chmod +x "$tmp/bootstrap-ok/out/host/linux-x86/bin/soong_build"
touch -d '@946684800' "$tmp/bootstrap-ok/external/v4l2_codec2/Android.bp"
touch -d '@946684900' "$tmp/bootstrap-ok/out/soong/bootstrap.ninja" "$tmp/bootstrap-ok/out/soong/bootstrap.ninja.d" "$tmp/bootstrap-ok/out/host/linux-x86/bin/soong_build"
python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-ok" >/dev/null
touch -d '@946685000' "$tmp/bootstrap-ok/external/v4l2_codec2/Android.bp"
if python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-ok" >/dev/null 2>&1; then
  echo "newer bootstrap dependency unexpectedly accepted" >&2
  exit 1
fi

# AOSP may use symlinked Android.bp inputs (for example the tree root).
# Permit symlinks only when their resolved target remains inside the Android tree.
mkdir -p "$tmp/bootstrap-link/out/soong" "$tmp/bootstrap-link/out/host/linux-x86/bin" "$tmp/bootstrap-link/build/soong"
printf 'root\n' >"$tmp/bootstrap-link/build/soong/root.bp"
ln -s build/soong/root.bp "$tmp/bootstrap-link/Android.bp"
printf 'out/soong/bootstrap.ninja: Android.bp\n' >"$tmp/bootstrap-link/out/soong/bootstrap.ninja.d"
printf 'ninja\n' >"$tmp/bootstrap-link/out/soong/bootstrap.ninja"
printf '#!/bin/sh\n' >"$tmp/bootstrap-link/out/host/linux-x86/bin/soong_build"
chmod +x "$tmp/bootstrap-link/out/host/linux-x86/bin/soong_build"
touch -d '@946684800' "$tmp/bootstrap-link/build/soong/root.bp"
touch -d '@946684900' "$tmp/bootstrap-link/out/soong/bootstrap.ninja" "$tmp/bootstrap-link/out/soong/bootstrap.ninja.d" "$tmp/bootstrap-link/out/host/linux-x86/bin/soong_build"
python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-link" >/dev/null

printf 'outside\n' >"$tmp/outside-Android.bp"
ln -s "$tmp/outside-Android.bp" "$tmp/bootstrap-link/escape.bp"
printf 'out/soong/bootstrap.ninja: escape.bp\n' >"$tmp/bootstrap-link/out/soong/bootstrap.ninja.d"
if python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-link" >/dev/null 2>&1; then
  echo "bootstrap dependency symlink escaping tree unexpectedly accepted" >&2
  exit 1
fi
grep -q 'bootstrap dependency escapes tree' scripts/check-codec2-bootstrap-checkpoint.py

# Restored Ninja outputs must recover the exact nanosecond mtimes recorded in
# .ninja_log while bootstrap inputs are normalized to a safe older epoch.
mkdir -p "$tmp/bootstrap-ninja/out/soong" "$tmp/bootstrap-ninja/out/host/linux-x86/bin" "$tmp/bootstrap-ninja/out/obj" "$tmp/bootstrap-ninja/src"
printf 'source\n' >"$tmp/bootstrap-ninja/src/Android.bp"
printf 'out/soong/bootstrap.ninja: src/Android.bp\n' >"$tmp/bootstrap-ninja/out/soong/bootstrap.ninja.d"
cat >"$tmp/bootstrap-ninja/out/soong/bootstrap.ninja" <<'NINJAFIXTURE'
rule fixture
  command = cp $in $out
build out/obj/fixture.a: fixture src/Android.bp | prebuilts/go/linux-x86/pkg/tool/linux_amd64/compile
build out/host/linux-x86/bin/soong_build: phony out/obj/fixture.a
NINJAFIXTURE
printf '#!/bin/sh\n' >"$tmp/bootstrap-ninja/out/host/linux-x86/bin/soong_build"
printf 'object\n' >"$tmp/bootstrap-ninja/out/obj/fixture.a"
chmod +x "$tmp/bootstrap-ninja/out/host/linux-x86/bin/soong_build"
python3 - "$tmp/bootstrap-ninja" <<'PYNINJA'
import os, sys
from pathlib import Path
root=Path(sys.argv[1])
manifest_ns=946684900_000_000_000
recorded_ns=946684950_123_456_789
for rel in ("out/soong/bootstrap.ninja","out/soong/bootstrap.ninja.d","out/host/linux-x86/bin/soong_build"):
    p=root/rel; st=p.stat(); os.utime(p, ns=(st.st_atime_ns, manifest_ns))
p=root/"out/obj/fixture.a"; st=p.stat(); os.utime(p, ns=(st.st_atime_ns, 946685100_000_000_000))
(root/"out/.ninja_log").write_text(
    "# ninja log v5\n0\t1\t946684950123456789\tout/obj/fixture.a\tdeadbeef\n",
    encoding="utf-8",
)
PYNINJA
# Fresh repo sync also refreshes AOSP Go tool mtimes. These tools are implicit
# bootstrap edge inputs and are not listed by bootstrap.ninja.d.
mkdir -p "$tmp/bootstrap-ninja/prebuilts/go/linux-x86/pkg/tool/linux_amd64"
printf '#!/bin/sh\n' >"$tmp/bootstrap-ninja/prebuilts/go/linux-x86/pkg/tool/linux_amd64/compile"
chmod +x "$tmp/bootstrap-ninja/prebuilts/go/linux-x86/pkg/tool/linux_amd64/compile"
touch -d '@946685500' "$tmp/bootstrap-ninja/prebuilts/go/linux-x86/pkg/tool/linux_amd64/compile"
PITV_CODEC2_NORMALIZE_BOOTSTRAP_REUSE=1 python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-ninja" | grep -q 'CODEC2_BOOTSTRAP_INPUT_MTIMES_NORMALIZED='
test "$(stat -c %Y "$tmp/bootstrap-ninja/prebuilts/go/linux-x86/pkg/tool/linux_amd64/compile")" -eq 946684800
test "$(stat -c %Y "$tmp/bootstrap-ninja/src/Android.bp")" -eq 946684800

PITV_CODEC2_NORMALIZE_BOOTSTRAP_REUSE=1 python3 scripts/check-codec2-bootstrap-checkpoint.py "$tmp/bootstrap-ninja" | grep -q 'CODEC2_NINJA_MTIMES_VERIFIED=1'
python3 - "$tmp/bootstrap-ninja/out/obj/fixture.a" <<'PYMTIME'
import sys
from pathlib import Path
expected=946684950123456789
actual=Path(sys.argv[1]).stat().st_mtime_ns
if actual != expected:
    raise SystemExit(f"fixture Ninja mtime mismatch: expected={expected} actual={actual}")
PYMTIME

# Bootstrap timeout cleanup must quiesce Soong before checkpointing.
grep -q 'pgrep -x soong_ui' .github/workflows/codec2-no-full-build-check.yml
grep -q 'pkill -KILL -x ninja' .github/workflows/codec2-no-full-build-check.yml
grep -Fq "tar --exclude='out/.path_interposer_log' --zstd -cf" .github/workflows/codec2-no-full-build-check.yml

# [build-codec2] retry Ubuntu 24.04 checkpoint after safe symlink validation

# [build-codec2] retry after checkpoint quiescence fix

# [build-codec2] retry with exact Ninja mtime restore

# [build-codec2] retry after idempotent source restore fix

# [diagnose-codec2] explain restored bootstrap dirtiness

# The exact soong_build dependency closure must be normalized. It includes both
# fresh source files and implicit Go compile/link tools from the new checkout.
grep -q 'CODEC2_BOOTSTRAP_INPUT_MTIMES_NORMALIZED' scripts/check-codec2-bootstrap-checkpoint.py
grep -q '"-t",' scripts/check-codec2-bootstrap-checkpoint.py
grep -q '"inputs",' scripts/check-codec2-bootstrap-checkpoint.py

# [diagnose-codec2] verify Go toolchain mtime normalization

# [diagnose-codec2] verify full soong_build input normalization

# [build-codec2] retry after full soong_build dependency normalization

# [build-codec2] retry with graph warmup checkpoint

# [build-codec2] retry clean graph warmup checkpoint boundary

# [build-codec2] retry 120s process-group graph checkpoint

# [build-codec2] retry with two staged graph checkpoints

# [build-codec2] retry with Soong-only graph generation


# Narrow Soong experiment: generate a Codec2-focused Android.bp list first.
grep -q 'all|graph|modules|diagnose|narrow-list|narrow-probe' scripts/build-minimal-codec2-modules.sh
grep -q 'pitv-codec2.Android.bp.list' scripts/build-minimal-codec2-modules.sh
grep -q 'CODEC2_NARROW_BP_SELECTED=' scripts/build-minimal-codec2-modules.sh
grep -q 'CODEC2_NARROW_LIST_READY=1' scripts/build-minimal-codec2-modules.sh
grep -q 'external/v4l2_codec2/Android.bp' scripts/build-minimal-codec2-modules.sh
grep -q 'external/ffmpeg_codec2/Android.mk' scripts/build-minimal-codec2-modules.sh

! grep -q 'ninja.*-t.*commands' scripts/probe-narrow-soong-graph.py
grep -q -- '--available_env' scripts/probe-narrow-soong-graph.py
grep -q -- '--globListDir' scripts/probe-narrow-soong-graph.py
grep -q 'pitv-codec2.ninja' scripts/probe-narrow-soong-graph.py
grep -q 'pitv-codec2.environment.used' scripts/probe-narrow-soong-graph.py
grep -q 'CODEC2_NARROW_SOONG_READY=1' scripts/probe-narrow-soong-graph.py
