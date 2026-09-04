# Running MesaOS with experiment files

MesaOS does not currently include a QEMU 9p or virtio-fs guest driver, so it
cannot mount a live host directory. These scripts provide a safer snapshot
workflow instead: binaries, scripts, and data are copied into the initrd and
appear in MesaOS under `/inyect/experiments/`.

Build and refresh the snapshot without starting QEMU:

```bash
./experiments/scripts/build-and-share.sh
```

Build, refresh the snapshot, and start the network-disabled VNC VM:

```bash
./experiments/scripts/run-mesaos-with-experiments.sh
```

Connect from a second terminal:

```bash
./experiments/scripts/connect-vnc.sh
```

The QEMU process must remain running in the first terminal. Disconnecting the
VNC viewer does not stop the VM. To refresh changed experiment files, stop the
VM with Ctrl-C and rerun `run-mesaos-with-experiments.sh`.

Inside MesaOS, the current proof of concept can be used like this:

```text
help > help.txt
run /inyect/experiments/head/head.sh -5 help.txt
```

Enter those as two separate commands because MesaOS does not support `&&`.
