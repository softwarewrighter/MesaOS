# ASCII xclock for MesaOS

This is a freestanding `no_std` Rust ELF that runs in Ring 3. It renders a
one-shot analog clock face in the MesaOS terminal. Since MesaOS does not expose
the RTC or framebuffer to userspace, the hands show time since boot and the
display uses text rather than pixels.

Run it inside MesaOS:

```text
run /inyect/experiments/xclock/xclock.sh
```

A graphical or continuously redrawn userspace clock will require a controlled
framebuffer/surface and event API from the kernel.

A VHS source for recording the same compiled renderer is available at
`experiments/demos/xclock.tape`.
