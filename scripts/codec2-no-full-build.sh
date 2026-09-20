#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cmd="${1:-help}"; shift || true
case "$cmd" in
  target-probe) exec "$HERE/probe-waydroid-codec2-target.sh" "$@";;
  fetch-sources) exec python3 "$HERE/fetch-minimal-codec2-sources.py" "$@";;
  build-modules) exec "$HERE/build-minimal-codec2-modules.sh" "$@";;
  prepare) exec "$HERE/prepare-codec2-overlay.sh" "$@";;
  stage) exec "$HERE/stage-codec2-payload.sh" "$@";;
  plan) exec "$HERE/plan-codec2-overlay-install.sh" "$@";;
  install) exec "$HERE/install-codec2-overlay.sh" "$@";;
  rollback) exec "$HERE/rollback-codec2-overlay.sh" "$@";;
  check) exec "$HERE/check-codec2-no-full-build.sh" "$@";;
  status)
    state=/var/lib/pitv/codec2-experiment
    echo "experiment=codec2-no-full-build"
    [ -f "$state/active-stage" ] && echo "active_stage=$(cat "$state/active-stage")" || echo "active_stage="
    [ -f "$state/last-backup" ] && echo "last_backup=$(cat "$state/last-backup")" || echo "last_backup="
    [ -f "$state/active-vendor.sha256" ] && cat "$state/active-vendor.sha256" || true
    ;;
  help|*)
    cat <<'EOF'
PiTV Codec2 no-full-build experiment
  target-probe [OUT]
  fetch-sources WORKDIR
  build-modules ANDROID13_TREE SOURCES_DIR PAYLOAD_OUT
  prepare DONOR_TREE PAYLOAD_OUT ROOT_ELF...
  stage PAYLOAD [STATE]
  plan STAGE
  install STAGE                 (root, RPi4 only)
  rollback [BACKUP]             (root)
  status
  check
EOF
    [ "$cmd" = help ] || exit 2
    ;;
esac
