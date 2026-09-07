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
XCLOCK_ELF="$SCRIPT_DIR/target/x86_64-unknown-none/release/xclock"
for elf in "$HEAD_ELF" "$XCLOCK_ELF"; do
    [[ -f "$elf" ]] || { echo "Error: Cargo did not produce $elf" >&2; exit 1; }
done

echo "Built command ELFs:"
echo "  $HEAD_ELF"
file "$HEAD_ELF"
echo "  $XCLOCK_ELF"
file "$XCLOCK_ELF"
