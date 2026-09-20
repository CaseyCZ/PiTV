#!/usr/bin/env bash
set -euo pipefail
# Static self-test for the no-full-build helper scripts. Does not need Android.
python3 -m py_compile scripts/probe-codec2-prebuilt.py scripts/collect-codec2-prebuilt.py
grep -q 'never writes to Waydroid' scripts/probe-codec2-prebuilt.py
grep -q 'No Waydroid files are changed' scripts/collect-codec2-prebuilt.py
grep -q 'refusing risky donor dependency' scripts/collect-codec2-prebuilt.py
echo "Codec2 no-full-build helper checks OK"
