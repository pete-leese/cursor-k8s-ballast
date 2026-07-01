#!/usr/bin/env bash
# Stop background port-forwards started with BACKGROUND=1 ./scripts/port-forward.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PIDFILE="${PIDFILE:-${TASKFILE_DIR:-.}/.cluster-port-forwards.pid}"

if [ ! -f "$PIDFILE" ]; then
  echo "No background port-forwards found (${PIDFILE})"
  exit 0
fi

while read -r pid; do
  [ -n "$pid" ] || continue
  kill "$pid" 2>/dev/null || true
done <"$PIDFILE"
rm -f "$PIDFILE"
echo "==> Port-forwards stopped"
