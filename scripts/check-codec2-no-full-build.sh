#!/usr/bin/env bash
set -euo pipefail
# Keep this script quiet on success; CI failures are diagnosed by line number.
trap 'echo "Codec2 static check failed at line $LINENO" >&2' ERR
PY=(
 scripts/probe-codec2-prebuilt.py
 scripts/collect-codec2-prebuilt.py
 scripts/assemble-codec2-overlay.py
 scripts/validate-codec2-payload.py
 scripts/verify-staged-codec2-payload.py scripts/make-codec2-rollback-manifest.py scripts/preflight-codec2-overlay.py scripts/test-codec2-no-full-build.py scripts/plan-codec2-backup.py scripts/check-codec2-payload-contract.py
 scripts/plan-codec2-backup.py
 scripts/fetch-minimal-codec2-sources.py
 scripts/check-minimal-codec2-source-lock.py
 scripts/audit-codec2-payload-deps.py
 scripts/make-codec2-rollback-manifest.py
 scripts/register-pitv-codec2-config.py
 scripts/inventory-codec2-payload.py
 scripts/evaluate-codec2-target.py
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
)
python3 -m py_compile "${PY[@]}"
python3 scripts/check-minimal-codec2-source-lock.py >/dev/null
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
bash scripts/plan-codec2-overlay-install.sh "$tmp/payload" >/dev/null
grep -q 'COPY vendor/lib64/libfixture.so -> /vendor/lib64/libfixture.so' "$tmp/payload/PITV-CODEC2-INSTALL-PLAN.txt"
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
