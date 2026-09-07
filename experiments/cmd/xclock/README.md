# ASCII xclock for MesaOS

This is a freestanding `no_std` Rust ELF that runs in Ring 3. It renders a
continuously updated analog clock face in the MesaOS terminal. A small read-only
MesaOS syscall supplies local RTC seconds to the unprivileged ELF. Narrowly
scoped display syscalls clear the terminal and select hand colors without giving
userspace direct framebuffer access.
The blue hour hand uses `o`, the blue minute hand uses `*`, and the red
sweep-second hand uses `.`. The rim labels `12`, `3`, `6`, and `9`, with dots
for the other hours.

Run it inside MesaOS:

```text
run /inyect/experiments/xclock/xclock.sh
```

Press Ctrl+C to stop clock redraws and return control to the shell. `exec` runs
the ELF as a foreground child, so the kernel shell does not race it for keyboard
or display access. A small latched-input syscall delivers Ctrl+C to Ring 3.

The safe launcher uses one virtual CPU. In that configuration the clock uses
cooperative waits and redraws only when the RTC second changes, avoiding the
currently unreliable SMP scheduler path.

After the child exits, `exec` collects it and restores the shell prompt.

A VHS source for recording the same compiled renderer is available at
`experiments/demos/xclock.tape`.
