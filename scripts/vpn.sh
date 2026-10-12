#!/bin/sh
# Turn Cloudflare WARP off for a tick, then put it back only if it was on.
set -eu

state="${HOME}/.jobhunt/vpn.state"
mkdir -p "${HOME}/.jobhunt"

if [ "${1:-}" = "off" ]; then
  current=$(warp-cli --accept-tos status 2>/dev/null || true)
  if printf '%s' "$current" | grep -q "Connected"; then
    printf 'connected\n' > "$state"
  else
    printf 'disconnected\n' > "$state"
  fi
  warp-cli --accept-tos disconnect >/dev/null 2>&1 || true
  waited=0
  while [ "$waited" -lt 20 ]; do
    now=$(warp-cli --accept-tos status 2>/dev/null || true)
    if printf '%s' "$now" | grep -q "Disconnected"; then
      exit 0
    fi
    waited=$((waited + 1))
    sleep 1
  done
  exit 1
fi

if [ "${1:-}" = "restore" ]; then
  if [ -f "$state" ] && grep -q '^connected$' "$state"; then
    warp-cli --accept-tos connect >/dev/null 2>&1 || true
  fi
  rm -f "$state"
  exit 0
fi

echo "usage: vpn.sh off|restore" >&2
exit 2
