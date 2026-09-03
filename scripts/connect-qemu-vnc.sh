#!/usr/bin/env bash

# Connect a graphical viewer to an already-running run-qemu-safe.sh instance.

set -euo pipefail

VNC_HOST=127.0.0.1
VNC_PORT=5901

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "Error: no graphical desktop is available in this terminal." >&2
    echo "Open a terminal inside Chrome Remote Desktop and run this script there." >&2
    exit 1
fi

if command -v ss >/dev/null 2>&1; then
    if ! ss -H -ltn "sport = :$VNC_PORT" | grep -q "$VNC_HOST:$VNC_PORT"; then
        echo "Error: MesaOS VNC is not listening on $VNC_HOST:$VNC_PORT." >&2
        echo "In another terminal, start it with: ./scripts/run-qemu-safe.sh" >&2
        echo "Keep that launcher terminal open while using or reconnecting to MesaOS." >&2
        exit 1
    fi
fi

if command -v remote-viewer >/dev/null 2>&1; then
    exec remote-viewer "vnc://$VNC_HOST:$VNC_PORT"
elif command -v gvncviewer >/dev/null 2>&1; then
    exec gvncviewer "$VNC_HOST:1"
else
    echo "Error: no supported VNC viewer is installed." >&2
    echo "On Debian/Ubuntu: sudo apt install virt-viewer" >&2
    exit 1
fi
