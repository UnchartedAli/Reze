#!/bin/sh
# Reze container entrypoint — fixes volume ownership, then drops root.
# Developer: UnchartedAli · Channel: @yamods
set -eu

DATA_DIR="${REZE_DATA_DIR:-/app/data}"

mkdir -p "$DATA_DIR" 2>/dev/null || true

if [ "$(id -u)" = "0" ]; then
    # A freshly mounted PaaS volume is usually root-owned; make it writable by
    # the unprivileged bot user before dropping privileges.
    chown -R reze:reze "$DATA_DIR" 2>/dev/null || true
    exec gosu reze "$@"
fi

exec "$@"
