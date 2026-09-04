# MesaOS Rust command experiments

This directory is an independent Cargo workspace for freestanding MesaOS
user-space commands. Command binaries live under `cmd/`; the first example is
[`cmd/head`](cmd/head/README.md).

Reusable `no_std` support lives under `crates/`. `mesaos-user` currently
provides Ring-3 syscall wrappers, file reads, console output, request-file
arguments, process exit, and a standard experiment banner.

Build every command:

```bash
./experiments/build.sh
```

Build all commands, copy their runtime files into `inyect/`, regenerate the
initrd, and rebuild `mesa-os.iso`:

```bash
./experiments/install-and-build-iso.sh
```

Run the automated, network-disabled QEMU smoke test:

```bash
./experiments/test-head-qemu.sh
```

Convenience launch, snapshot-sharing, and VNC scripts are documented in
[`scripts/README.md`](scripts/README.md).

## MesaOS shell scripts

MesaOS has a deliberately small script runner:

```text
run script.sh arg1 arg2
```

It executes each non-comment line as a shell command and substitutes `$0`,
`$1` through the supplied positional arguments, `$#`, `$@`, and `$*`. Commands
can use the shell's single pipe and `>`/`>>` redirection.

It is not Bash or a POSIX shell interpreter: it currently has no assignments,
environment expansion, `if`, loops, functions, command substitution, or shell
built-in mechanism for counting/selecting lines. A script can wrap a `head`
binary, but cannot implement `head` from the currently available primitives.
