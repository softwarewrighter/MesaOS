# `head` in `no_std` Rust for MesaOS

This experiment is a freestanding, statically linked x86-64 ELF written in
Rust. It uses `core` but no Rust standard library, C library, or Linux runtime.
It calls MesaOS's Linux-compatible `open`, `read`, `write`, `close`, and `exit`
syscalls directly.

## Important current limitation

MesaOS's kernel shell parses `exec <ELF path>` but passes neither arguments nor
an initial Linux `argc`/`argv` stack to the ELF. This proof of concept uses a
shell wrapper as an argument bridge: it writes the requested path and line
count to `/tmp/head.path` and `/tmp/head.lines`, and the Ring-3 ELF reads them.

```text
/tmp/head.path
/tmp/head.lines
```

An absent or invalid line-count file defaults to 10 lines.

## Build only

From the repository root:

```bash
./experiments/build.sh
```

The result is:

```text
experiments/target/x86_64-unknown-none/release/head
```

The repository's pinned nightly toolchain and `rust-src` component are used.

## Build, copy into the initrd, and rebuild MesaOS

```bash
./experiments/install-and-build-iso.sh
```

This copies the ELF and sample input under `inyect/experiments/head/`, rebuilds
`output/initrd.bin`, then rebuilds `mesa-os.iso`. Files in the initrd appear
beneath `/inyect` when MesaOS boots.

## Run it

Terminal 1:

```bash
./scripts/run-qemu-safe.sh
```

Terminal 2:

```bash
./scripts/connect-qemu-vnc.sh
```

Log in and enter, for example:

```text
run /inyect/experiments/head/head.sh -5 /inyect/experiments/head/input.txt
```

The banner and lines 1 through 5 of the sample should appear; line 6 should
not. The wrapper contains:

```text
write /tmp/head.lines $1
write /tmp/head.path $2
exec /inyect/experiments/head/head.elf
```

This is intentionally an experimental bridge. Fixed request paths mean two
concurrent invocations could overwrite each other's arguments.

To page the existing `help` output, enter these as **two separate commands**:

```text
help > help.txt
run /inyect/experiments/head/head.sh -5 help.txt
```

MesaOS does not currently implement `&&`; writing both operations on one line
would not sequence them as it does in Bash.

## Changing the input

Edit `input.txt` and rerun `install-and-build-iso.sh`. Every initrd change
requires rebuilding the kernel and ISO because `output/initrd.bin` is compiled
into the kernel.
