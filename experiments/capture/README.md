# Capture the actual QEMU VNC display

This automation boots MesaOS without networking or host shares, bridges its
localhost-only VNC display to noVNC, controls the guest with Playwright, and
records the real browser-rendered framebuffer. It encodes both animated WebP
and GIF and retains the smaller result.

```bash
cd experiments/capture
npm install
cd ../..
./experiments/capture/capture-xclock.sh
```

The intermediate Playwright recording is `xclock-vnc.webm`. The final result
is either `xclock-vnc.webp` or `xclock-vnc.gif` in this directory.

## Browser-based VNC viewer

Start MesaOS and the browser bridge in separate terminals:

```bash
./experiments/scripts/run-mesaos-with-experiments.sh
./experiments/capture/serve-vnc-browser.sh
```

Then open `http://127.0.0.1:6080/` in Chrome on the same remote desktop. The
HTTP server, WebSocket endpoint, and QEMU VNC listener bind only to localhost.
