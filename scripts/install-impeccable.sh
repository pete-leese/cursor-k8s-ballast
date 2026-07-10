#!/usr/bin/env bash
# Official Impeccable install for Cursor (run in your own terminal — needs DNS to impeccable.style).
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes impeccable install -y --providers=cursor --scope=project
echo
echo "Then in Cursor chat: /impeccable init"
