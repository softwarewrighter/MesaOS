#!/usr/bin/env bash

# Run MesaOS with conservative QEMU defaults:
#   - software emulation (no KVM device access)
#   - no network adapter
#   - no host filesystem shares or hardware passthrough
#   - a temporary virtual disk that is deleted on exit
#   - QEMU's seccomp sandbox enabled

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
cleanup() {
    rm -f -- "$TEMP_DISK"
}
trap cleanup EXIT

# This disk is disposable. MesaOS may write to it, but it is removed when
# QEMU exits and is never mapped to a physical host disk.
truncate -s 100M "$TEMP_DISK"

echo "Starting MesaOS in an isolated QEMU window."
echo "  Network:       disabled"
echo "  Host shares:   none"
echo "  Virtual disk:  temporary (deleted on exit)"
echo "  Acceleration:  TCG software emulation"
echo
echo "Use the QEMU window for the MesaOS keyboard and CLI."
echo "In this terminal, press Ctrl-A then X to stop QEMU."

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
    -serial mon:stdio
