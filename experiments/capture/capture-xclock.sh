#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
CAPTURE_TMP=$(mktemp -d --tmpdir mesaos-xclock-capture.XXXXXX)
VNC_PORT=5902
HTTP_PORT=6080
QEMU_PID=""
SERVER_PID=""

cleanup() {
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
    [[ -n "$QEMU_PID" ]] && kill "$QEMU_PID" 2>/dev/null || true
    rm -rf -- "$CAPTURE_TMP"
}
trap cleanup EXIT

truncate -s 100M "$CAPTURE_TMP/disk.img"
qemu-system-x86_64 \
    -machine pc,accel=tcg -m 512 -smp 1 -boot order=d,menu=off \
    -cdrom "$PROJECT_ROOT/mesa-os.iso" \
    -drive "file=$CAPTURE_TMP/disk.img,format=raw,media=disk,if=ide" \
    -nic none \
    -sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny \
    -no-reboot -display none -vnc 127.0.0.1:2 -monitor none \
    -serial "file:$CAPTURE_TMP/serial.log" &
QEMU_PID=$!

CAPTURE_HTTP_PORT=$HTTP_PORT CAPTURE_VNC_PORT=$VNC_PORT \
    node "$SCRIPT_DIR/server.mjs" >"$CAPTURE_TMP/server.log" 2>&1 &
SERVER_PID=$!
sleep 3

cd "$SCRIPT_DIR"
CAPTURE_SERIAL_LOG="$CAPTURE_TMP/serial.log" node capture.mjs

ffmpeg -y -ss 2 -i xclock-vnc.webm -vf "fps=8,scale=768:-1:flags=lanczos" \
    -loop 0 xclock-demo.webp >/dev/null 2>&1
ffmpeg -y -ss 2 -i xclock-vnc.webm -vf \
    "fps=8,scale=768:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
    -loop 0 xclock-vnc.gif >/dev/null 2>&1

WEBP_SIZE=$(stat -c %s xclock-demo.webp)
GIF_SIZE=$(stat -c %s xclock-vnc.gif)
if (( WEBP_SIZE <= GIF_SIZE )); then
    rm -f xclock-vnc.gif
    echo "Created experiments/capture/xclock-demo.webp ($WEBP_SIZE bytes; smaller than GIF)."
else
    rm -f xclock-demo.webp
    echo "Created experiments/capture/xclock-vnc.gif ($GIF_SIZE bytes; smaller than WebP)."
fi
