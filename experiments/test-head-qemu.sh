#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
ISO_PATH="$PROJECT_ROOT/mesa-os.iso"
TEST_DIR=$(mktemp -d --tmpdir mesaos-head-test.XXXXXX)
MONITOR_SOCKET="$TEST_DIR/monitor.sock"
SERIAL_LOG="$TEST_DIR/serial.log"
QEMU_PID=""

cleanup() {
    if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
        kill "$QEMU_PID" 2>/dev/null || true
        wait "$QEMU_PID" 2>/dev/null || true
    fi
    rm -rf -- "$TEST_DIR"
}
trap cleanup EXIT

if [[ ! -f "$ISO_PATH" ]]; then
    echo "Error: $ISO_PATH does not exist; run install-and-build-iso.sh first." >&2
    exit 1
fi

qemu-system-x86_64 \
    -machine pc,accel=tcg \
    -m 512 \
    -smp 4 \
    -boot order=d,menu=off \
    -cdrom "$ISO_PATH" \
    -nic none \
    -sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny \
    -no-reboot \
    -display none \
    -monitor "unix:$MONITOR_SOCKET,server=on,wait=off" \
    -serial "file:$SERIAL_LOG" &
QEMU_PID=$!

for _ in $(seq 1 100); do
    [[ -S "$MONITOR_SOCKET" ]] && break
    sleep 0.1
done
[[ -S "$MONITOR_SOCKET" ]]

wait_for_log() {
    local pattern=$1
    local attempts=${2:-300}
    for _ in $(seq 1 "$attempts"); do
        grep -Fq "$pattern" "$SERIAL_LOG" 2>/dev/null && return 0
        kill -0 "$QEMU_PID" 2>/dev/null || return 1
        sleep 0.1
    done
    echo "Error: timed out waiting for: $pattern" >&2
    tail -120 "$SERIAL_LOG" >&2
    return 1
}

# Synchronize with serial milestones instead of assuming a fixed boot speed.
wait_for_log "[LOGIN] Esperando nombre de usuario..."
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" root
wait_for_log "[LOGIN] Usuario introducido: root"
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" ""
wait_for_log "[SHELL] Shell iniciado"
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" \
    "run /inyect/experiments/head/head.sh -5 /inyect/experiments/head/input.txt"
wait_for_log "MesaOS experiment: head v0.1.0 (Ring 3, no_std Rust)"
sleep 1

if ! kill -0 "$QEMU_PID" 2>/dev/null; then
    echo "Error: QEMU exited unexpectedly." >&2
    tail -80 "$SERIAL_LOG" >&2
    exit 1
fi

if ! grep -Fq "MesaOS experiment: head v0.1.0 (Ring 3, no_std Rust)" "$SERIAL_LOG"; then
    echo "Error: head banner was not observed." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi
if ! grep -Fq "line 05" "$SERIAL_LOG"; then
    echo "Error: expected line 05 was not observed." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi
if grep -Fq "line 06" "$SERIAL_LOG"; then
    echo "Error: head printed line 06 despite a five-line limit." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi

echo "PASS: Ring-3 head printed exactly the requested first five lines."
