#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# The repository-level Cargo configuration contains kernel-only linker flags.
# CARGO_ENCODED_RUSTFLAGS replaces those flags; each command crate supplies its
# own user-space linker script from build.rs.
export CARGO_ENCODED_RUSTFLAGS=""

cd "$SCRIPT_DIR"
cargo build --workspace --release

HEAD_ELF="$SCRIPT_DIR/target/x86_64-unknown-none/release/head"
if [[ ! -f "$HEAD_ELF" ]]; then
    echo "Error: Cargo did not produce $HEAD_ELF" >&2
    exit 1
fi

echo "Built command ELFs:"
echo "  $HEAD_ELF"
file "$HEAD_ELF"
