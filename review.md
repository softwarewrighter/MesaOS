# MesaOS Review and Technical Discussion

This document records an edited version of the questions and answers from a
technical review of MesaOS. Repetition from live debugging has been condensed,
while commands, conclusions, and important caveats have been retained.

## English README

### Question

> Translate the README from Spanish to `README-en_US.md`.

### Answer

The root README was translated into `README-en_US.md`. Its Markdown structure,
commands, links, badges, paths, and technical identifiers were preserved.

## Running MesaOS safely in QEMU

### Question

> How can I run this in a VM or emulator like QEMU, and is it relatively safe
> to do so? Can I restrict file and network access?

### Answer

Running MesaOS in QEMU is relatively safe when only disposable virtual devices
are attached. The important precautions are:

- Do not run QEMU as root.
- Do not pass through physical disks, USB devices, or PCI devices.
- Do not configure host filesystem shares.
- Disable the guest network unless it is required.
- Use a disposable virtual disk.
- Enable QEMU's seccomp sandbox.
- Avoid `build.sh flash`, `run-tap`, and physical NVMe devices.

The original `build.sh run` configuration attached `disk.img`, enabled QEMU
user-mode networking, and forwarded host port 8080 to guest port 80. A more
isolated launcher was therefore added at:

```text
scripts/run-qemu-safe.sh
```

Its QEMU configuration provides:

- TCG software emulation rather than KVM
- No guest network adapter
- No host filesystem share
- No hardware passthrough
- A temporary 100 MB virtual disk deleted on exit
- A local-only VNC endpoint on `127.0.0.1:5901`
- QEMU's syscall sandbox

## Login, console access, and SSH

### Question

> Create a safe script for me to run this in QEMU. How do I attach to it? Does
> it have a CLI at boot? Does it have a user/password to SSH to?

### Answer

MesaOS boots to a graphical framebuffer login screen and then enters its
built-in shell. Login input is read from the emulated PS/2 keyboard, not from
QEMU's serial console.

The built-in local accounts are:

| User | Password |
|------|----------|
| `root` | Empty; press Enter |
| `guest` | `guest` |
| `mesa` | `mesa` |

No SSH server or port-22 service was found in the MesaOS source. QEMU port
forwarding cannot create an SSH service when nothing in the guest is listening.
Interactive access must therefore use the graphical console.

## Build failure diagnosis

### Question

> The script failed due to a missing build. I tried `build.sh build` and that
> failed. Please recreate and diagnose it. Pick a specific working recent
> nightly.

### Answer

Three independent build problems were reproduced and corrected:

1. `rust-toolchain.toml` followed the moving `nightly` channel. A newer unstable
   `Step` trait had become incompatible with the locked `x86_64 0.15.4` crate.
2. The host C compiler inserted stack-protector calls into freestanding C code,
   causing an unresolved `__stack_chk_fail` symbol at link time.
3. The checked-in `limine/` directory existed but omitted required CD image
   artifacts. `build.sh` only checked whether the directory existed and
   therefore skipped downloading the missing files.

The repository was pinned to:

```toml
channel = "nightly-2026-08-01"
```

The `x86_64` dependency was configured to use the required instruction and
interrupt ABI features without its incompatible optional `step_trait` feature.
The freestanding C compilation now uses `-fno-stack-protector`, and `build.sh`
validates individual Limine artifacts before deciding whether to download them.

After these fixes, the kernel compiled, the ISO was created, and a QEMU boot
test reached the MesaOS login screen.

## VNC launch and reconnect workflow

### Questions

> I did not see a QEMU window, only a TUI.

> Should I try the VNC server, and how do I do that? I am already using Chrome
> Remote Desktop to get here.

> Unable to connect. Please provide a launch script command and a reconnect VNC
> script; document them.

### Answer

The installed QEMU build did not provide a GTK or SDL display backend. Its
terminal view was QEMU's monitor/serial interface, not the MesaOS keyboard
console. Entering MesaOS credentials there could not work because the operating
system reads PS/2 keyboard events.

The solution was split into two independent scripts.

In terminal 1, launch the VM and keep the command running:

```bash
./scripts/run-qemu-safe.sh
```

In terminal 2, inside the Chrome Remote Desktop graphical session, attach a
viewer:

```bash
./scripts/connect-qemu-vnc.sh
```

The reconnect script checks that QEMU is listening before starting
`remote-viewer` or `gvncviewer`. Closing the viewer does not stop QEMU. It can be
reopened by running the connection script again. `Ctrl+C` in terminal 1 stops
QEMU and deletes the temporary virtual disk.

The VNC listener is bound only to `127.0.0.1:5901`; it is not exposed to the
guest, LAN, or public network.

During testing, a viewer was deliberately run under a short timeout. Its window
closing was initially mistaken for a MesaOS crash. A later reproduction showed
that QEMU and MesaOS remained running after the viewer disconnected.

## Shell crash investigation

### Question

> It came up. I was able to enter `root`, Enter for the password, `ls`, and
> `uptime`, and then it crashed.

### Answer

The exact sequence was reproduced through QEMU's emulated PS/2 keyboard while
capturing MesaOS's serial log:

```text
root
[empty password]
ls
uptime
```

MesaOS printed the directory listing, reported uptime, returned to the prompt,
and continued producing its shell heartbeat. The kernel had not crashed. The
problem was that the earlier launcher tied QEMU's lifetime to the VNC viewer;
when the viewer exited, launcher cleanup killed QEMU. The launcher was changed
so the VM owns the process lifetime and viewers may connect and disconnect
independently.

## Paging, editing, and shell scrollback

### Question

> When I type `help`, its output scrolls off the screen. There is no pipe,
> `less`, `more`, or `head` apparently. I could use `help > help.txt`. How do I
> page or edit that text file? How do I scroll back in the shell?

### Answer

MesaOS has output redirection and a limited pipe implementation, but it does
not implement a pager or console scrollback.

The file can be opened with:

```text
nano help.txt
```

The editor's useful controls are:

- Arrow keys to move the cursor
- Enter and Backspace to edit
- `Ctrl+S` to save
- `Ctrl+X` to exit

The framebuffer console scrolls by copying visible rows upward and discarding
the oldest row. It does not retain a scrollback buffer. Although keyboard scan
codes for Page Up and Page Down are recognized, the regular shell does not use
them for scrollback.

The pipe parser accepts one `command1 | command2` pair, but only `cat` contains
special built-in handling for shell pipe input. There is no `less`, `more`,
`head`, `tail`, or `split` implementation. The pipe buffer is also only 4096
bytes, so it is not yet a general Unix pipeline facility.

### Question

> Is there a `dd` command so I can cut the file?

### Answer

No. MesaOS currently has no `dd`, `cut`, `head`, `tail`, or `split` command.
Manual editing with `nano help.txt` is the only existing in-guest option for
trimming the file.

## Original MesaOS work versus reused Linux code

### Question

> Can you analyze the commits and codebase to describe how much is new original
> work and how much is reused Linux code?

### Answer

The repository as a whole is overwhelmingly composed of vendored or reference
Linux material, but the actual MesaOS kernel appears to be largely
project-specific Rust code rather than a modified Linux kernel.

Approximate tracked line counts were:

| Area | Approximate lines | Character |
|------|------------------:|-----------|
| `Linux/` | 39,413,699 | Complete vendored Linux source tree |
| `rtl88x2ce-dkms-master/` | 743,335 | External Realtek Linux driver |
| `DOCUMENTACION-WIFI-VER/` | 724,166 | Linux/driver reference material |
| `userland/` | 224,472 | Mostly copied Linux xHCI and rtw88 code |
| `mesa_kernel/` | 64,771 including documentation and backups | MesaOS implementation |
| `mesa_kernel/` implementation code | About 48,528 | Primarily Rust |

The complete Linux tree accounts for about 95.6% of the counted repository
text. Including external and copied driver trees raises clearly reused or
reference material above 99% of the repository.

That does not mean the running MesaOS kernel is 99% Linux. The regular build
does not compile the complete Linux tree. The MesaOS kernel consists of roughly
46,338 lines of Rust and 2,087 lines of C/header code, including its own:

- Boot and architecture setup
- Scheduler
- Memory manager
- VFS and RamFS
- Shell
- Network stack
- Native drivers
- ELF loader
- Linux syscall compatibility layer
- Linux driver-symbol shim

The Linux compatibility code implements Linux-facing APIs; API compatibility
does not by itself make that implementation Linux code.

There is direct reuse in the driver areas. The audit found:

- About 162,366 lines in `userland/rtw88` byte-for-byte identical to matching
  Linux `rtw88` files.
- About 30,868 lines in `userland/xhci` byte-for-byte identical to matching
  Linux xHCI files.
- `userland/xhci_build` contains both identical and modified Linux xHCI files.
- `rtl88x2ce-dkms-master` identifies itself as an external driver repository.

The Git history cannot establish detailed authorship. The first commit imported
about 95,219 files and 44 million lines in one snapshot. Subsequent creator
commits mainly changed the README. There is no incremental kernel history from
which to reconstruct development or provenance.

The README also states that language models generated the source according to
the creator's specifications, while architecture, debugging, integration, and
hardware testing were human work. Consequently, “project-specific code” should
not automatically be interpreted as independently human-authored code.

## Are the shell commands Rust or ported Linux commands?

### Question

> Linux generally does not have much Rust. The shell I ran was limited. Were
> its commands also written in Rust, or were Linux commands ported to run on the
> Rust kernel?

### Answer

The interactive boot shell and its normal commands are Rust functions compiled
directly into the MesaOS kernel. They are not GNU coreutils or Linux command
binaries.

The shell parses a line, matches the first word, and calls a Rust function. For
example:

```rust
match command {
    "help" => cmd_help(),
    "ls" => cmd_ls(args),
    "cat" => cmd_cat(args),
    "nano" => cmd_nano(args),
    // ...
}
```

These built-ins run in Ring 0 and can call MesaOS's internal filesystem,
framebuffer, keyboard, network, and scheduler modules directly.

The Linux compatibility layer is separate. It provides Linux-style syscall
numbers and partial implementations for ELF programs running in Ring 3.

## Adding `head`, `tail`, `more`, `less`, or `dd`

### Question

> How would I add more commands to the shell, such as `head`, `tail`, `less`,
> `more`, or `dd`?

### Answer

The most practical current approach is to add them as Rust kernel-shell
built-ins:

1. Add the command name to the `COMMANDS` array in `mesa_kernel/src/main.rs`.
2. Add a match arm such as `"head" => cmd_head(args)`.
3. Implement `cmd_head`, using `fs::read_to_string()` and `mesa_println!()`.
4. Add the command to `cmd_help()`.
5. Rebuild the ISO and restart QEMU.

`head` and `tail` are straightforward file-processing functions. `more` needs
an interactive loop that prints a screen at a time and waits for Space, Enter,
or `q`. A real `less` additionally needs backward navigation, search, wrapping,
and status display.

A built-in `dd` could parse `if=`, `of=`, `bs=`, and `count=` arguments and use
MesaOS filesystem reads and writes. It should initially be restricted to RamFS
paths because the block and storage drivers are experimental.

## Writing and injecting a Rust CLI application

### Question

> How would I write a Rust CLI app that runs in this demo? Would I
> cross-compile it, and how would I get the binary into the filesystem and run
> it from the shell?

### Answer

MesaOS has an ELF64 loader and can create Ring 3 processes, but its userland is
not yet a normal Linux or Rust environment. A Rust program must currently be:

- `#![no_std]`
- `#![no_main]`
- Statically linked
- Built for x86-64
- Given its own `_start` entry point
- Limited to direct syscall wrappers
- Free of libc and dynamic-library dependencies

The practical target is `x86_64-unknown-none`, using the repository's pinned
`nightly-2026-08-01` toolchain. The ELF should use a small linker script with a
known user-space address such as `0x400000`.

The current loader accepts x86-64 `ET_EXEC` and `ET_DYN` files with `PT_LOAD`
segments. The shell runs an injected executable with:

```text
exec /inyect/program.elf
```

An executable can be added to the initrd and ISO with:

```bash
./tools/inject_build.sh path/to/program.elf
```

After restarting QEMU, an explicitly injected file appears under `/inyect` by
basename. Alternatively, placing it in `inyect/bin/` before a normal build
causes it to appear under `/inyect/bin/`.

Current userland limitations include:

- No Rust standard library or libc
- No documented userland SDK crate
- No standard terminal API
- No environment variables
- No conventional `argc`/`argv` process stack
- `exec` ignores arguments after the executable path
- The shell does not automatically search for external executables
- The shell launches external tasks without conventional job control/waiting
- Only a subset of Linux syscalls is implemented

For these reasons, utilities that require filenames and options are easier to
implement as built-ins today. Standalone CLI utilities become more practical
after the loader and shell support `argc`/`argv`, external-command lookup, and
more complete process and terminal semantics.

## Location and nature of the Rust APIs

### Question

> If this is `no_std` Rust, where are the Rust source files and documentation
> for the available APIs?

### Answer

The primary Rust sources are under `mesa_kernel/src/`:

| Area | Location |
|------|----------|
| Boot, login, shell, commands | `mesa_kernel/src/main.rs` |
| Filesystem | `mesa_kernel/src/fs/` |
| Memory management | `mesa_kernel/src/memory/` |
| Scheduler | `mesa_kernel/src/scheduler/` |
| Drivers | `mesa_kernel/src/drivers/` |
| Networking | `mesa_kernel/src/net/` |
| ELF loading | `mesa_kernel/src/elf.rs` |
| Native syscalls | `mesa_kernel/src/syscall/` |
| Linux-compatible syscalls | `mesa_kernel/src/linux_compat/` |
| Ring 3 support | `mesa_kernel/src/userland/` |
| Linux driver shim | `mesa_kernel/src/shim/` |

`no_std` means that the kernel does not depend on an underlying operating
system's Rust standard library. It still uses Rust `core`, Rust `alloc` after
initializing its own allocator, compatible third-party crates, and internal
MesaOS modules.

There is no complete MesaOS SDK or generated public API manual. Documentation
currently consists of source-level `//!` and `///` comments, the syscall
dispatcher, example programs under `userland/hello_elf`, and a small number of
Markdown architecture notes. For userland work, the syscall implementation and
examples are effectively the API specification.

## Is `nano` a port?

### Questions

> One of the commands is `nano`. Is that a port, or a fake nano written in
> Rust? How does nano use a TUI? It is a window editor, not a line editor. Where
> is the source?

### Answer

It is a small, homemade, nano-inspired editor written in Rust. It is not a port
of GNU nano, and there is no separate `/bin/nano` executable.

The complete implementation is the `cmd_nano()` function in:

```text
mesa_kernel/src/main.rs
```

It begins at approximately line 3804 in the reviewed revision and is compiled
directly into the Ring 0 shell.

It does not use curses or a terminal UI protocol. Instead, it obtains the raw
framebuffer address and dimensions, creates MesaOS's `UiRenderer`, and draws
rectangles and glyphs at pixel coordinates. Its graphical primitives are in:

```text
mesa_kernel/src/drivers/framebuffer/ui.rs
```

The editor:

- Clears and fills the framebuffer
- Draws a title bar labeled `Mesa Nano 1.0`
- Draws visible file lines at explicit pixel positions
- Draws the cursor as a small rectangle
- Draws a footer with shortcut labels
- Reads keyboard events directly from MesaOS's keyboard driver
- Automatically adjusts its visible row offset as the cursor moves

QEMU then transmits the emulated VGA framebuffer over VNC. The VNC viewer is
showing pixels produced by MesaOS; it is not interpreting terminal escape
sequences.

The implemented editing controls are limited to character insertion, Enter,
Backspace, arrow keys, `Ctrl+S`, and `Ctrl+X`. It lacks search, selection,
copy/paste, mouse support, Page Up/Down handling, and most GNU nano features.
Although its footer mentions `Ctrl+C Cancel`, the reviewed implementation does
not handle that key inside the editor.

This illustrates the difference between MesaOS built-ins and Ring 3 programs:

- A built-in such as nano runs in Ring 0 and directly uses internal framebuffer,
  keyboard, and filesystem APIs.
- A Ring 3 ELF can only use exposed syscalls and currently has no public
  framebuffer or userland UI API.
