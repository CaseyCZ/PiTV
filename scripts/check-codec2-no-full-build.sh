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
grep -q 'VINTF metadata missing service' scripts/check-codec2-service-metadata.py
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
