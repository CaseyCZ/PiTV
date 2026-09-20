#!/usr/bin/env bash
set -euo pipefail
# Guard used by any future reduced Android media builder.
# It deliberately fails before source sync/build if the workspace budget is
# smaller than required or the selected path looks like the full-build tree.
WORK="${1:?workspace required}"
REQUIRED_GB="${PITV_CODEC2_REQUIRED_GB:-40}"
MAX_GB="${PITV_CODEC2_MAX_GB:-80}"
case "$WORK" in
  *pitv-waydroid-lineage20*) echo "refusing full-build workspace: $WORK" >&2; exit 20;;
esac
if (( REQUIRED_GB > MAX_GB )); then
  echo "required budget ${REQUIRED_GB}GB exceeds ceiling ${MAX_GB}GB" >&2; exit 21
fi
mkdir -p "$WORK"
avail_kb="$(df -Pk "$WORK" | awk 'NR==2 {print $4}')"
need_kb=$((REQUIRED_GB*1024*1024))
if (( avail_kb < need_kb )); then
  echo "insufficient free space: need ${REQUIRED_GB}GB" >&2; exit 22
fi
printf 'CODEC2_WORKSPACE=%s\nREQUIRED_GB=%s\nMAX_GB=%s\n' "$WORK" "$REQUIRED_GB" "$MAX_GB"
