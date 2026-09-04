#!/usr/bin/env python3
"""Send text to a QEMU guest keyboard through an HMP Unix socket."""

import socket
import sys
import time

KEYS = {
    " ": "spc",
    "/": "slash",
    ".": "dot",
    "-": "minus",
    "_": "shift-minus",
}


def send(monitor: socket.socket, command: str) -> None:
    monitor.sendall((command + "\n").encode("ascii"))
    # MesaOS's polling keyboard path drops/repeats events if driven too fast.
    time.sleep(0.075)


def type_text(monitor: socket.socket, text: str) -> None:
    for character in text:
        key = KEYS.get(character, character.lower())
        if character.isupper():
            key = "shift-" + character.lower()
        send(monitor, "sendkey " + key)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} MONITOR_SOCKET TEXT", file=sys.stderr)
        return 2
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as monitor:
        monitor.connect(sys.argv[1])
        monitor.recv(4096)
        type_text(monitor, sys.argv[2])
        send(monitor, "sendkey ret")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
