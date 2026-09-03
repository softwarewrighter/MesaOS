#!/usr/bin/env bash

# Run MesaOS with conservative QEMU defaults:
#   - software emulation (no KVM device access)
#   - no network adapter
#   - no host filesystem shares or hardware passthrough
#   - a temporary virtual disk that is deleted on exit
#   - QEMU's seccomp sandbox enabled
#   - display exposed only through localhost VNC

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
ISO_PATH="$PROJECT_ROOT/mesa-os.iso"

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "Error: qemu-system-x86_64 is not installed." >&2
    echo "On Debian/Ubuntu: sudo apt install qemu-system-x86" >&2
    exit 1
fi

if [[ ! -f "$ISO_PATH" ]]; then
    echo "MesaOS ISO not found; building it now without refreshing injected files."
    (cd "$PROJECT_ROOT" && NO_INJECT=1 ./build.sh build)
    if [[ ! -f "$ISO_PATH" ]]; then
        echo "Error: the build completed without creating $ISO_PATH." >&2
        exit 1
    fi
fi

TEMP_DISK=$(mktemp --tmpdir mesaos-qemu-disk.XXXXXX.img)
SERIAL_LOG=$(mktemp --tmpdir mesaos-qemu-serial.XXXXXX.log)
QEMU_PID=""
VIEWER_PID=""
cleanup() {
    if [[ -n "$VIEWER_PID" ]] && kill -0 "$VIEWER_PID" 2>/dev/null; then
        kill "$VIEWER_PID" 2>/dev/null || true
        wait "$VIEWER_PID" 2>/dev/null || true
    fi
    if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
        kill "$QEMU_PID" 2>/dev/null || true
        wait "$QEMU_PID" 2>/dev/null || true
    fi
    rm -f -- "$TEMP_DISK"
    rm -f -- "$SERIAL_LOG"
}
trap cleanup EXIT

# This disk is disposable. MesaOS may write to it, but it is removed when
# QEMU exits and is never mapped to a physical host disk.
truncate -s 100M "$TEMP_DISK"

echo "Starting MesaOS on a local-only VNC display."
echo "  Network:       disabled"
echo "  Host shares:   none"
echo "  Virtual disk:  temporary (deleted on exit)"
echo "  Acceleration:  TCG software emulation"
echo "  VNC endpoint:  127.0.0.1:5901"
echo
echo "Use the VNC viewer for the MesaOS keyboard and CLI."
echo "Press Ctrl-C in this terminal to stop QEMU."
echo "Reconnect with: remote-viewer vnc://127.0.0.1:5901"
echo "Serial diagnostics: $SERIAL_LOG"

qemu-system-x86_64 \
    -machine pc,accel=tcg \
    -m 512 \
    -smp 4 \
    -boot order=d,menu=off \
    -cdrom "$ISO_PATH" \
    -drive "file=$TEMP_DISK,format=raw,media=disk,if=ide" \
    -nic none \
    -sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny \
    -no-reboot \
    -display none \
    -vnc 127.0.0.1:1 \
    -monitor none \
    -serial "file:$SERIAL_LOG" &
QEMU_PID=$!

# Give QEMU a moment to create its VNC listener and report early failures.
sleep 1
if ! kill -0 "$QEMU_PID" 2>/dev/null; then
    wait "$QEMU_PID"
fi

if [[ -n "${DISPLAY:-}" ]] && command -v remote-viewer >/dev/null 2>&1; then
    echo "Opening remote-viewer on the current desktop..."
    remote-viewer vnc://127.0.0.1:5901 &
    VIEWER_PID=$!
elif [[ -n "${DISPLAY:-}" ]] && command -v gvncviewer >/dev/null 2>&1; then
    echo "Opening gvncviewer on the current desktop..."
    gvncviewer 127.0.0.1:1 &
    VIEWER_PID=$!
else
    echo
    echo "No graphical VNC viewer was found. In another terminal, run:"
    echo "  remote-viewer vnc://127.0.0.1:5901"
fi

# The VM owns the launcher lifetime. Closing or losing the VNC viewer must not
# stop QEMU; reconnect with the command printed above or rerun remote-viewer.
wait "$QEMU_PID"
