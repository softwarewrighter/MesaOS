#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
EXPERIMENTS_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

# Build and copy experiment artifacts into inyect/experiments/, regenerate the
# initrd, and rebuild mesa-os.iso. This creates a snapshot, not a live mount.
exec "$EXPERIMENTS_ROOT/install-and-build-iso.sh"
