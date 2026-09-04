#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR="$PROJECT_ROOT/inyect/experiments/head"
HEAD_ELF="$SCRIPT_DIR/target/x86_64-unknown-none/release/head"

"$SCRIPT_DIR/build.sh"

mkdir -p "$INSTALL_DIR"
cp -- "$HEAD_ELF" "$INSTALL_DIR/head.elf"
cp -- "$SCRIPT_DIR/cmd/head/input.txt" "$INSTALL_DIR/input.txt"
cp -- "$SCRIPT_DIR/cmd/head/head.sh" "$INSTALL_DIR/head.sh"

cd "$PROJECT_ROOT"
./tools/inject_to_iso.sh
NO_INJECT=1 ./build.sh build

echo
echo "Installed files:"
echo "  /inyect/experiments/head/head.elf"
echo "  /inyect/experiments/head/input.txt"
echo "  /inyect/experiments/head/head.sh"
echo
echo "Start the VM: ./scripts/run-qemu-safe.sh"
echo "Connect:      ./scripts/connect-qemu-vnc.sh"
echo "At the MesaOS prompt, run:"
echo "  run /inyect/experiments/head/head.sh -5 /inyect/experiments/head/input.txt"
