#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

echo "Serving the MesaOS VNC display at:"
echo "  http://127.0.0.1:6080/"
echo
echo "The normal QEMU launcher must be running on VNC port 5901."
echo "Press Ctrl-C here to stop only the browser bridge."

CAPTURE_HTTP_PORT=6080 CAPTURE_VNC_PORT=5901 exec node "$SCRIPT_DIR/server.mjs"
