<p align="center">
  <img src="https://img.shields.io/badge/Rust-%23000000.svg?style=for-the-badge&logo=rust&logoColor=white"/>
  <img src="https://img.shields.io/badge/x86__64-00599C?style=for-the-badge&logo=intel&logoColor=white"/>
  <img src="https://img.shields.io/badge/Limine-FDEFE8?style=for-the-badge&logo=limine&logoColor=black"/>
  <img src="https://img.shields.io/badge/UEFI-0A5CF5?style=for-the-badge&logo=uefi&logoColor=white"/>
  <img src="https://img.shields.io/badge/license-GPL-blue?style=for-the-badge"/>
  <a href="https://discord.gg/sEaB7KAwtr"><img src="https://img.shields.io/badge/Discord-MesaOS-5865F2?style=for-the-badge&logo=discord&logoColor=white"/></a>
</p>
</p>


<h1 align="center">MesaOS</h1>
<p align="center"><i>A 64-bit operating system written from scratch in Rust.</i></p>
<p align="center">
  <b>Hybrid kernel</b> · <b>Preemptive multitasking</b> · <b>Linux driver shim</b> · <b>HD Audio</b> · <b>TCP/IP networking</b>
</p>

---
---
> 🤖 **Development note:**
> MesaOS is a systems architecture experiment designed and led by **crackanimador** (a secondary school student).
>
> All source code has been generated using language models (AI) according to my specifications, while the architecture design, debugging, testing on real hardware, and system integration are 100% human work.

## 🌟 What is MesaOS?

MesaOS is an x86_64 operating system written **100% from scratch in Rust**. It is not Linux with a new layer on top, nor a modified BSD—it is an original hybrid-architecture kernel that combines Rust's safety with Linux compatibility through a shim exporting more than 400 kernel symbols.

### What makes it unique?

- **Real Linux driver shim**: exports `kmalloc`, `printk`, `pci_*`, `dma_*`, and 400+ symbols to load unmodified Linux drivers
- **WAV audio streaming** through HDA with real-time resampling and 512 KB chunks
- **Complete network stack** (ARP/IPv4/ICMP/DHCP/DNS/Ethernet) over virtio-net and RTL8139
- **Persistent initrd**: files injected into the ISO survive reboots—persistence without a disk
- **Interactive shell** with 82 commands, pipes, redirection, history, autocomplete, and a text editor
- **Partial Linux binary compatibility**: Linux syscalls, `/proc`, `/sys`, epoll, signalfd, eventfd, timerfd

---

## 🚀 Features

### 🧠 Kernel and System

| Feature | Description |
|---------|-------------|
| Hybrid kernel | Monolithic with Ring 3 user space |
| Preemptive multitasking | Round-robin with 5 states, sleep queue, zombies |
| Native syscalls | SYSCALL/SYSRET with software SMAP/SMEP validation |
| Linux compatibility | ~350 syscalls recognized, 60+ implemented |
| Driver shim | 400+ exported Linux kernel symbols |
| ACPI | RSDP, MADT, AML interpreter through the `aml` crate |
| Multiprocessing | SMP detection (multicore scheduler pending) |
| Security | ASLR, stack canary, rate limiting, password hashing |

### 🎮 Drivers

| Driver | Description | Status |
|--------|-------------|--------|
| **HDA Audio** | 48 kHz/16-bit/stereo, CORB/RIRB, DMA streaming, codec routing | ✅ |
| **Virtio-Net** | MMIO, Rx/Tx queues, for QEMU | ✅ |
| **RTL8139** | 10/100 Ethernet, PIO, IRQ | ✅ |
| **PS/2 Keyboard** | Scan codes, ES/US layouts | ✅ |
| **RTC (CMOS)** | Real-time clock, timezone | ✅ |
| **Battery** | ACPI `_BST`/`_BIF` + EC fallback, cycle count, SOH | ✅ |
| **PC Speaker** | Tones, beep, experimental TTS | ✅ |
| **Framebuffer** | Console, Rose Pine, HTML rendering | ✅ |
| **UEFI NVRAM** | Read/write/list variables through runtime services | ✅ |
| **NVMe** | Complete code (disabled for safety) | ⏸️ |
| **xHCI (USB 3.0)** | Initialization and port scanning (drivers under construction, but the foundation is complete) | ✅ |
| **ATA/IDE** | Complete code (disabled for safety) | ⏸️ |

### 🌐 Networking

| Protocol | Status |
|----------|--------|
| Ethernet—frame parsing/creation | ✅ |
| ARP—cache, requests, replies | ✅ |
| IPv4—routing, fragmentation | ✅ |
| ICMP—echo (ping) | ✅ |
| TCP—header parsing | 🚧 |
| UDP | 🚧 |
| DHCP—client | ✅ |
| DNS—resolution | ✅ |
| RNDIS—USB tethering (currently only NCP initialization) | 🚧 |

### 📂 File System

| Component | Status |
|-----------|--------|
| Abstract VFS with File/Directory/Symlink/Device | ✅ |
| RamFS—in-memory tree | ✅ |
| Initrd—files embedded in the ISO (persistent) | ✅ |
| Partitions—MBR/GPT parsed | ✅ |
| `write`/`read`/`mkdir`/`rmdir`/`rename`/`chown`/`link`/`symlink` | ✅ |

### 🎵 Audio Player

| Feature | Status |
|---------|--------|
| 8/16/24/32-bit WAV PCM, mono/stereo | ✅ |
| Chunked linear resampling (prevents OOM) | ✅ |
| DMA streaming with 512 KB chunks (~2.7 s) | ✅ |
| MP3—metadata (duration, bitrate, sample rate) | ✅ |
| Commands: `play`, `audio-info`, `audio-list` | ✅ |

### 🖥️ Shell (82 commands)

| Command | Function |
|---------|----------|
| `play f.wav` | Play WAV audio |
| `hda test` / `hda vol 80` | HDA test / volume |
| `battery-report` | Full battery report |
| `nano` | Text editor |
| `neofetch` | System information |
| `ping 10.0.2.2` | ICMP echo |
| `dhcp` | Network configuration |
| `bios-analyze` | BIOS scan |
| `nvram list/read/write/del` | UEFI NVRAM management |
| `su`, `passwd`, `useradd`, `userdel` | Multi-user support |
| `exec f.elf` | Run an ELF binary in Ring 3 |
| `ps`, `kill`, `top` | Process management |
| `|`, `>`, `>>` | Pipes and redirection |

---

## 🔋 Battery Report

Inspired by Linux's `upower -i`. Two cascading data sources:

1. **ACPI AML** (preferred): evaluates `_BST`/`_BIF`/`_BTP`
2. **Direct EC** (fallback): standard 0xD0/0xD8 registers

```
╔══════════════════════════════════════════════════════════════╗
║              MESA OS  -  B A T T E R Y   R E P O R T         ║
╚══════════════════════════════════════════════════════════════╝

  state                    discharging
  percentage               72%
  energy-full-design       45000 mWh
  energy-now               30600 mWh
  time-to-empty            2:27:33
  capacity (SOH)           94%
  cycle-count              124
  source                   AML (ACPI _BST/_BIF)
```

```bash
battery-report        # Full report
battery-report -w     # Monitor mode (refreshes every 2 s)
battery-report -b     # Brief (one line)
battery-report -v     # Verbose (OEM info, warnings)
```

---

## 📦 Persistent Initrd

Files injected into the ISO **stay there permanently**. They are not lost after a reboot because they are embedded in the kernel inside the ISO.

```bash
# Inject files and rebuild in a single step
./tools/inject_build.sh my_data/

# Or run the steps separately
./tools/inject_to_iso.sh file.wav config.conf
./build.sh build

# Restore a clean ISO (without files)
./build.sh restore
```

> The files appear under `/inyect/` inside the OS.

---

## 🧱 Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     RING 3 (USER)                        │
│  ELF Processes · Shell · Pipes · Linux/MesaOS Syscalls   │
├──────────────────────────────────────────────────────────┤
│                    RING 0 (KERNEL)                        │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  Scheduler   │  │    Memory    │  │  Linux Shim    │ │
│  │  Round-Robin │  │  PMM/VMM     │  │  400+ symbols  │ │
│  │  Sleep Queue │  │  Heap/HHDM   │  │  workqueues    │ │
│  │  Zombies     │  │  Paging      │  │  timers        │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │   Drivers    │  │  Networking  │  │  File System   │ │
│  │  HDA Audio   │  │  ARP/IPv4    │  │  VFS · RamFS   │ │
│  │  RTL8139     │  │  ICMP/DHCP   │  │  Initrd · MBR  │ │
│  │  Virtio-Net  │  │  DNS/TCP     │  │  GPT           │ │
│  │  xHCI/NVMe   │  │  Ethernet    │  │                │ │
│  │  Keyboard    │  │              │  │                │ │
│  └──────────────┘  └──────────────┘  └────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  x86_64: GDT · IDT · APIC/PIC · SYSCALL/SYSRET · TSS││
│  └──────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## ⚙️ Building

### Requirements

```bash
rustup toolchain install nightly
rustup default nightly
sudo apt install xorriso qemu-system-x86_64 git make gcc
```

### Build

```bash
chmod +x build.sh

./build.sh build           # Build kernel + ISO
```

### Run in QEMU

```bash
./build.sh run             # Virtio-net (recommended)
./build.sh run-nvme        # With simulated NVMe
./build.sh run-usb         # With xHCI USB
./build.sh run-wifi        # With graphical display
```

### Environment variables

```bash
NO_INJECT=1 ./build.sh build    # Build without injection
ARCH=aarch64 ./build.sh build   # ARM64 (experimental)
```

---

## 🗺️ Roadmap

- [x] **v0.1** — Base kernel, memory, scheduler, basic shell
- [x] **v0.2** — HDA Audio, WAV streaming, networking (ARP/IP/DHCP)
- [x] **v0.3** — Persistent initrd, battery report, UEFI NVRAM
- [x] **v0.4** — Linux shim, 350 syscalls, Ring 3, ELF loader, nano editor
- [/] **v0.5** — Functional xHCI (real control transfers), USB storage
- [ ] **v0.6** — TCP state machine (real connections)
- [x] **v0.7** — SMP (multicore scheduler)
- [ ] **v0.8** — Embedded HTTP web server
- [ ] **v0.9** — MP3 decoder (Huffman + MDCT)
- [ ] **v1.0** — Wi-Fi RTL8822CE

---

## 🧪 Tested Hardware

| Platform | Works |
|----------|-------|
| QEMU (KVM/TCG) | ✅ Fully |
| HP 15s-eq2xxx | ✅ Audio, battery, networking, NVMe |
| UEFI (Limine) | ✅ |
| BIOS (GRUB) | ✅ |

---

## ⚠️ Warning

The **NVMe driver overwrites Sector 0** (the partition table) during initialization.
**Do not run it on hardware containing important data if you uncomment the NVMe driver.** Use QEMU or a test disk.

Additionally, **the QEMU version may experience errors due to SMP**, but all features otherwise work as intended.

---

## 👤 Creator

**Crackanimad0r / Crackanimador** ⛩️


---

<p align="center">
  <i>Made with ☕, 🦀, and a lot of patience.</i>
</p>
