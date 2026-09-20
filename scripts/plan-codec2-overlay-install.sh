#!/usr/bin/env bash
set -euo pipefail
# Generate a dry-run installation plan from a verified stage. No files outside
# the stage are changed.
STAGE="${1:?stage required}"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/verify-staged-codec2-payload.py" "$STAGE" >/dev/null
python3 "$HERE/enforce-codec2-payload-scope.py" "$STAGE" >/dev/null
python3 "$HERE/check-codec2-manifest-closure.py" "$STAGE" >/dev/null
python3 "$HERE/check-codec2-payload-size.py" "$STAGE" >/dev/null
python3 "$HERE/verify-codec2-metadata.py" "$STAGE" >/dev/null
python3 "$HERE/codec2-payload-readiness.py" "$STAGE" >/dev/null
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
