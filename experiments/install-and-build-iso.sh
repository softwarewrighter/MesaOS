#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR="$PROJECT_ROOT/inyect/experiments/head"
XCLOCK_DIR="$PROJECT_ROOT/inyect/experiments/xclock"
HEAD_ELF="$SCRIPT_DIR/target/x86_64-unknown-none/release/head"
XCLOCK_ELF="$SCRIPT_DIR/target/x86_64-unknown-none/release/xclock"

"$SCRIPT_DIR/build.sh"

mkdir -p "$INSTALL_DIR"
mkdir -p "$XCLOCK_DIR"
cp -- "$HEAD_ELF" "$INSTALL_DIR/head.elf"
cp -- "$SCRIPT_DIR/cmd/head/input.txt" "$INSTALL_DIR/input.txt"
cp -- "$SCRIPT_DIR/cmd/head/head.sh" "$INSTALL_DIR/head.sh"
cp -- "$XCLOCK_ELF" "$XCLOCK_DIR/xclock.elf"
cp -- "$SCRIPT_DIR/cmd/xclock/xclock.sh" "$XCLOCK_DIR/xclock.sh"

cd "$PROJECT_ROOT"
./tools/inject_to_iso.sh
NO_INJECT=1 ./build.sh build

echo
echo "Installed files:"
echo "  /inyect/experiments/head/head.elf"
echo "  /inyect/experiments/head/input.txt"
echo "  /inyect/experiments/head/head.sh"
echo "  /inyect/experiments/xclock/xclock.elf"
echo "  /inyect/experiments/xclock/xclock.sh"
echo
echo "Start the VM: ./scripts/run-qemu-safe.sh"
echo "Connect:      ./scripts/connect-qemu-vnc.sh"
echo "At the MesaOS prompt, run:"
echo "  run /inyect/experiments/head/head.sh -5 /inyect/experiments/head/input.txt"
echo "  run /inyect/experiments/xclock/xclock.sh"
