#!/usr/bin/env bash
set -euo pipefail
# Generate a dry-run installation plan from a verified stage. No files outside
# the stage are changed.
STAGE="${1:?stage required}"
python3 "$(dirname "$0")/verify-staged-codec2-payload.py" "$STAGE" >/dev/null
PLAN="$STAGE/PITV-CODEC2-INSTALL-PLAN.txt"
{
  echo "# PiTV Codec2 experimental install plan"
  echo "# DRY RUN ONLY"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    case "$rel" in
      vendor/*) target="/$rel";;
      *) target="/vendor/$rel";;
    esac
    printf 'COPY %s -> %s\n' "$rel" "$target"
  done <"$STAGE/PITV-CODEC2-PAYLOAD.txt"
  echo "VALIDATE android13-arm64"
  echo "VALIDATE codec2-registry"
  echo "VALIDATE codec2-services"
  echo "ROLLBACK required-on-any-failure"
} >"$PLAN"
cat "$PLAN"
