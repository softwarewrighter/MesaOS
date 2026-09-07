# Experiment recordings

## xclock VHS tape

[`xclock.tape`](xclock.tape) builds and records the same freestanding xclock
ELF used by MesaOS:

```bash
vhs experiments/demos/xclock.tape
```

The resulting recording is written to:

```text
experiments/demos/xclock.gif
```

This is a hosted terminal preview: Linux executes the same static ELF because
the experiment deliberately uses Linux-numbered `write`, `time`, and `exit`
syscalls. The MesaOS build runs that ELF in Ring 3.

VHS records terminal PTYs and cannot capture the separate QEMU VNC window. To
record the actual guest framebuffer, connect VNC and use a desktop/window
screen recorder instead.
