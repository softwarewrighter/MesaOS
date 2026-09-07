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
    -smp 1 \
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
    "run /inyect/experiments/xclock/xclock.sh"
wait_for_log "MesaOS experiment: xclock v0.1.0 (Ring 3, no_std Rust)"
wait_for_log "o=hour  *=minute"
wait_for_log "=sweep second"
sleep 2

if ! kill -0 "$QEMU_PID" 2>/dev/null; then
    echo "Error: QEMU exited unexpectedly." >&2
    tail -80 "$SERIAL_LOG" >&2
    exit 1
fi

if ! grep -Fq "MesaOS experiment: xclock v0.1.0 (Ring 3, no_std Rust)" "$SERIAL_LOG"; then
    echo "Error: xclock banner was not observed." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi
if ! grep -Eq "Time: [0-2][0-9]:[0-5][0-9]:[0-5][0-9]" "$SERIAL_LOG"; then
    echo "Error: xclock did not display an RTC-style HH:MM:SS value." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi
if LC_ALL=C grep -q $'\033' "$SERIAL_LOG"; then
    echo "Error: xclock emitted raw ANSI control characters." >&2
    exit 1
fi
distinct_times=$(grep -Eo "Time: [0-2][0-9]:[0-5][0-9]:[0-5][0-9]" "$SERIAL_LOG" | sort -u | wc -l)
if (( distinct_times < 2 )); then
    echo "Error: xclock did not advance its displayed time." >&2
    tail -120 "$SERIAL_LOG" >&2
    exit 1
fi
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" --ctrl-c
sleep 0.5
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" --ctrl-c
sleep 0.5
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" --ctrl-c
wait_for_log "xclock stopped by Ctrl+C."
python3 "$SCRIPT_DIR/send-qemu-keys.py" "$MONITOR_SOCKET" uptime
wait_for_log "Uptime:"
echo "PASS: Ring-3 xclock rendered its analog clock successfully."
