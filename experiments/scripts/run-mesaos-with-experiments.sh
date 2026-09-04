#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
EXPERIMENTS_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_ROOT=$(cd -- "$EXPERIMENTS_ROOT/.." && pwd)

echo "Building the experiments and taking an initrd snapshot..."
"$EXPERIMENTS_ROOT/install-and-build-iso.sh"

echo
echo "Starting the network-disabled MesaOS VM."
echo "The experiment snapshot is available in the guest under /inyect/experiments/."
echo "Connect from another terminal with:"
echo "  ./experiments/scripts/connect-vnc.sh"
echo

exec "$PROJECT_ROOT/scripts/run-qemu-safe.sh"
