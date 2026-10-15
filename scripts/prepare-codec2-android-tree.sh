#!/usr/bin/env bash
set -euo pipefail

TREE="$(readlink -m "${1:?Android tree path required}")"
MANIFEST_OUT="$(readlink -m "${2:?manifest output path required}")"
SYNC_JOBS="${PITV_CODEC2_SYNC_JOBS:-4}"

mkdir -p "$TREE"
cd "$TREE"

init_ok=0
for attempt in 1 2 3; do
  echo "CODEC2_REPO_INIT_ATTEMPT=$attempt"
  rm -rf .repo
  if repo init \
      -u https://android.googlesource.com/platform/manifest \
      -b android-13.0.0_r75 \
      --depth=1 \
      --no-clone-bundle; then
    init_ok=1
    break
  fi
  sleep $((attempt * 5))
done
if [ "$init_ok" -ne 1 ]; then
  echo "Android repo init failed after 3 attempts" >&2
  exit 1
fi

curl -fsSL --retry 3 --create-dirs \
  -o .repo/local_manifests/manifest_brcm_rpi4.xml \
  https://raw.githubusercontent.com/raspberry-vanilla/android_local_manifest/android-13.0/manifest_brcm_rpi4.xml
curl -fsSL --retry 3 \
  -o .repo/local_manifests/remove_projects.xml \
  https://raw.githubusercontent.com/raspberry-vanilla/android_local_manifest/android-13.0/remove_projects.xml

sync_ok=0
for attempt in 1 2 3; do
  echo "CODEC2_REPO_SYNC_ATTEMPT=$attempt jobs=$SYNC_JOBS"
  if repo sync -c --no-tags --no-clone-bundle --optimized-fetch --fail-fast -j"$SYNC_JOBS"; then
    sync_ok=1
    break
  fi
  sleep $((attempt * 10))
done
if [ "$sync_ok" -ne 1 ]; then
  echo "Android repo sync failed after 3 attempts" >&2
  exit 1
fi

mkdir -p "$(dirname "$MANIFEST_OUT")"
repo manifest -r > "$MANIFEST_OUT"
rm -rf "$TREE/.repo"
echo "CODEC2_REPO_METADATA_DROPPED=1"
df -h "$TREE"
