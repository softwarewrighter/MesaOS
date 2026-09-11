# MesaOS memory layout — the 3D visualization producer

MesaOS emits a machine-readable description of its own memory layout so that
a shared, system-agnostic 3D viewer can draw it as stacks of classified
blocks. This document covers what is emitted, where the numbers come from,
and where the boundary with the other repositories is.

```
MesaOS                          memory semantics      (this repository)
   │ scripts/memory-layout.py
   ▼
build/memory-layout.json        the data contract     (columnar)
   │
   ▼
MLPL viz script                 visualization         (sw-ml-study/sw-mlpl)
   │
   ▼
native3d extension              graphics              (sw-ml-study/demo-extensions)
   │
   ▼
3D viewer
```

MesaOS knows what its memory means. MLPL knows visualization. native3d knows
graphics. **No MesaOS concept crosses that first arrow except as data** — the
consumer does not learn about Limine, the initrd container or the x86_64
higher half, and nothing in this repository picks a colour or a coordinate.

MesaOS is the third producer of the same contract, after SWTOS
(`../../sw-embed/sw-tos`) and MLOS (`../../sw-ml-study/sw-os-ml`). The
contract is pinned in `../../sw-ml-study/sw-mlpl/docs/storage-layout-viz.md`;
the original design note is
`../../sw-ml-study/demo-extensions/docs/research.txt`.

## Using it

```sh
# emit the layout (uses the committed kernel ELF and the injection tree)
python3 scripts/memory-layout.py --inyect-dir inyect

# check both artifacts against the interchange contract before the handoff
python3 scripts/memory-layout-check.py build/memory-layout.json
python3 scripts/memory-layout-check.py build/memory-layout.rows.json

# look at it now, without waiting for the shared renderer
python3 scripts/memory-layout-preview.py --open
```

Nothing here needs a toolchain: it is plain Python 3 with no third-party
imports, and the ELF reader is built in, so the producer runs on a macOS host
against an x86_64 target the same as it runs on the build machine.

| Flag | |
|---|---|
| `--kernel PATH` | the linked kernel ELF (default `iso/boot/mesa_kernel`) |
| `--initrd-from` | `embedded` (default), `inyect`, or a path — see below |
| `--inyect-dir DIR` | the injection tree `--initrd-from inyect` packs |
| `--program NAME` | draw this ELF's address space; repeatable |
| `--module-depth N` | how finely to attribute code to parts (default 1) |
| `--revision REV` | record this revision instead of asking git |
| `--shape columnar\|row\|both` | which serialization to write (default both) |
| `-o PATH` | where to write (default `build/memory-layout.json`) |

### Which initrd

`--initrd-from embedded` (the default) finds the container **inside the
kernel** by walking `.rodata` for one that parses. `INITRD_DATA` is a
`&[u8]`, so its payload has no symbol to look up, but the format is
constrained enough to recognise — on this kernel exactly one offset in 7.7 MB
satisfies it. That gives the initrd a real address, and describes the
container this kernel actually carries.

`--initrd-from inyect` packs one from the injection tree using
`tools/inject_to_iso.py`, the build's own packer. That describes what the
**next** build would embed, which is how a program added since the last build
becomes visible — `xclock` and `head` are in `inyect/` but not in the
committed kernel. The producer says so on stderr when the two differ, and
records which was used in `provenance.initrd_source`.

Either way the blob labelled inside the kernel image is the embedded one: the
bytes in `.rodata` do not change because a different container was asked
about.

## Two serializations of one document

The two consumers read the same schema name two different ways.

| | columnar | row |
|---|---|---|
| file | `build/memory-layout.json` | `build/memory-layout.rows.json` |
| read by | sw-mlpl | demo-extensions' bounded Rust parser |
| shape | `region_*` arrays, index-aligned | a `regions` array of objects |
| region id | integer | string, `"<space>.<id>"` |
| provenance | `producer`, `revision` | plus `generated_at`, `source_description` |

sw-mlpl's contract is columnar because `parse_json` ingests homogeneous
arrays and an array-of-objects would need a language feature MLPL does not
have. demo-extensions' parser reads rows with `deny_unknown_fields`. Neither
is wrong, and reconciling them is not this repository's call to make — so
MesaOS emits both rather than being the reason either consumer waits. It is
one model serialized twice, not two documents.

The row form is lossy on purpose: its schema is `additionalProperties:
false`, so `region_perm` and `space_base` have nowhere to go, and an absent
owner is spelled `unowned` because every text field must be non-empty. **The
columnar artifact is the complete one.** The row artifact has been verified by
running demo-extensions' own `mlpl_system_layout::Layout::parse` against it.

Its `generated_at` is the HEAD commit's date rather than wall-clock time:
wall-clock would make every regeneration produce different bytes and turn a
checksum a consumer pins into a moving target.

## What gets emitted

Address spaces, each fully tiled by regions in address order: the kernel
image twice (once by section, once by the part of the project each byte was
built from), the initrd, and one per program whose loaded address space is
drawn.

```
      kernel image                 embedded initrd              user address space
   ffffffff80000000                 inside .rodata                 (per process)
┌──────────────────────┐        ┌──────────────────────┐        ┌──────────────────────┐
│ .text        r-x     │        │ entry count          │        │ unmapped (null guard)│
├──────────────────────┤        ├──────────────────────┤        ├──────────────────────┤
│ page alignment       │        │ record: bin/linux.elf│──┐     │ program text  r-x    │
├──────────────────────┤        ├──────────────────────┤  │     ├──────────────────────┤
│ .rodata      r--     │──┐     │ bin/linux.elf        │◀─┘     │ program bss          │
├──────────────────────┤  │     ├──────────────────────┤ ──────▶├──────────────────────┤
│ .data        rw-     │  │     │ record: xclock.elf   │        │ unmapped             │
├──────────────────────┤  │     ├──────────────────────┤        ├──────────────────────┤
│ .limine_requests     │  └────▶│ experiments/xclock…  │        │ brk origin           │
├──────────────────────┤        ├──────────────────────┤        ├──────────────────────┤
│ .bss         rw-     │        │ …                    │        │ mmap arena           │
├──────────────────────┤        └──────────────────────┘        ├──────────────────────┤
│ .got / page tail     │                                        │ stack         rw-    │
└──────────────────────┘                                        └──────────────────────┘
```

Each `experiments/` program gets its own tower. Every MesaOS process is laid
out at the same nominal addresses, so those towers overlay in the machine
even though they are drawn side by side — which is the point of drawing them
side by side.

That middle arrow is the point of the whole exercise. It is the chain MesaOS
is otherwise hard to explain in prose: a file is injected into the ISO, packed
into a container, embedded in `.rodata` by `include_bytes!`, unpacked into the
RamFS at boot, and loaded into a Ring 3 address space by `elf.rs`. It is
carried in the artifact as the relationship edge table:

| `rel_kind` | from | to |
|---|---|---|
| `embeds` | `.rodata` | the initrd it holds via `include_bytes!` |
| `describes` | an initrd record | the payload it points at |
| `loads-to` | an initrd ELF | the user segments and stack it becomes |

### The kernel image by part

Sections answer "how much of the image is read-only data". They do not answer
"how much of the image is the USB stack", which is what a rough layout is
actually asked. The kernel ELF is not stripped, so the symbol table answers
it: every sized symbol carries a Rust v0 mangled path naming the crate and
module it was compiled from, which the producer decodes far enough to get the
prefix. Adjacent symbols from the same part merge into one run, across gaps
up to a page — without that, a subsystem shatters into a thousand slivers
with a sliver of "no symbol" between each pair.

`module_name` / `module_bytes` / `module_runs` / `module_share_bp` roll that
up, largest first. On the committed kernel:

| bytes | share | what |
|---|---|---|
| 7,070,642 | 65.0% | the embedded initrd, sitting in `.rodata` |
| 1,319,460 | 12.1% | `mesa_kernel::smp` — the per-CPU stack arrays in `.bss` |
| 624,077 | 5.7% | genuinely unattributed: literals, vtables, padding |
| 529,338 | 4.9% | `mesa_kernel::memory` — mostly the PMM's 512 KiB bitmap |
| 166,926 | 1.5% | `mesa_kernel::drivers` |
| 112,808 | 1.0% | `aml::parser` — the ACPI interpreter |

Two thirds of this kernel is the files injected into it, and an eighth is
preallocated SMP stacks. That is the kind of thing a section view cannot say.

The attribution is deliberately rough, and says so: symbols cover about a
third of the image — `.text` almost completely, `.bss` well, `.rodata`
barely — and what is left is reported as `unattributed` rather than
distributed by guesswork. An honest third is worth more than a fabricated
whole.

`--module-depth 1` gives a per-subsystem view (`mesa_kernel::drivers`); `2`
goes a level finer (`mesa_kernel::drivers::usb`). A symbol sitting directly
in the crate root keeps its own name, which is what makes a shell built-in
such as `nano` visible as itself rather than dissolved into the crate.

`kernel` and `kernel-modules` are two views of the same bytes. The
`space_overlays` column says so, so a consumer that assumes spaces are
disjoint knows which one to drop.

### Region kinds

`kind` says what a region **is**, never how to draw it.

| kind | |
|---|---|
| `text` `rodata` `data` `bss` `got` | ELF sections and user segments |
| `limine_requests*` | the bootloader request markers, kept under their own names |
| `header` `catalog` | the initrd's entry count and its per-entry records |
| `image` | a loadable ELF: `elf.rs` gives it a user address space |
| `module` | a relocatable `.ko`: the Linux driver shim loads it into the kernel's |
| `file` | anything else the RamFS will simply hold |
| `heap` `stack` `mmap` | the user address space's dynamic areas |
| `code` | a run of symbols from one part of the project |
| `blob` | an opaque extent inside the image that is known but not code |
| `unattributed` | image bytes no symbol covers |
| `padding` | the cost of 4 KiB page alignment, named rather than hidden |
| `free` | unmapped or unused capacity |

Calling a `.ko` an `image` would draw it as something that gets its own user
space, which is exactly what it does not get — hence the separate kind.

#### What MesaOS adds to the shared vocabulary

`kind` is a small closed vocabulary per the contract, and the consumer's
palette has to cover the union of what the producers emit — a kind with no
palette row draws as nothing. MesaOS shares `header`, `catalog`, `image`,
`free`, `padding`, `text`, `data`, `bss` and `stack` with SWTOS, and adds:

| kind | why it is not one of the existing ones |
|---|---|
| `rodata` | a read-only segment is neither `text` nor `data`, and it is the largest single region in the kernel image |
| `got` | linker bookkeeping, not program data |
| `module` | a `.ko` loaded into the kernel's address space, not a user program |
| `file` | an initrd payload that is never loaded at all |
| `heap` | the brk origin, which grows on demand rather than being placed |
| `mmap` | the anonymous-mapping arena, which is address space rather than memory |
| `limine_requests`, `limine_requests_start`, `limine_requests_end` | bootloader request markers, kept under their own names because an unrecognised section keeping its name is more honest than folding it into `data` |

The producer prints its emitted vocabulary in the run summary, so relaying
this to the palette owner is a matter of reading the last run.

### The four colour modes

Colour should mean one thing at a time, so the artifact carries four
independent classifications and the consumer picks one:

| column | meaning |
|---|---|
| `region_kind` | purpose — what the bytes are |
| `region_owner` | who the bytes belong to (`kernel`, a program name, nobody) |
| `region_location` | `kernel-image`, `initrd`, `user-space` |
| `region_state` | `stored`, `zero`, `live`, `reserved`, `free`, `unmapped` |
| `region_perm` | the page permission it is mapped with, `rwx`-style |
| `region_module` | which part of the project the bytes were built from |

`region_location`, `region_state` and `region_perm` are additive columns
beyond the four the contract requires; a consumer that ignores them still
reads the artifact correctly.

## Where every number comes from

Nothing is restated here that the system already declares somewhere else. If
the kernel moves its stack, the picture moves with it.

| what | read from |
|---|---|
| kernel sections, sizes, permissions | the linked ELF, section and program headers |
| initrd contents | `output/initrd.bin`, walked with the format `mesa_kernel/src/fs/initrd.rs` documents |
| user code/stack/heap addresses | the `pub const USER_*` declarations in `mesa_kernel/src/memory/address_space.rs` |
| brk origin | `PROGRAM_BREAK` in `mesa_kernel/src/linux_compat/syscalls.rs` |
| mmap arena | `mmap_get_unused_addr()`'s search base and bound |
| loaded program extents | that program's own PT_LOAD segments |

The kernel ELF read is `iso/boot/mesa_kernel`, not `mesa_kernel/linker.ld`.
The linker script says what was asked for; the ELF says what was produced,
and they differ today — the script names a `.requests` section the build emits
as `.limine_requests`.

### What it does not claim to know

- **The user space is nominal.** `elf.rs` randomizes the stack top, and the
  load base of PIE binaries, under ASLR. A live process sits near these
  addresses, not on them.
- **One user space is drawn, not one per program.** Every MesaOS process gets
  its own page tables at the same nominal addresses; overlaying them would
  draw the same rectangle N times. `--program` selects which one.
- **Physical RAM is absent.** The frame allocator's map comes from Limine at
  boot and `mem` reports only free/total frames, so there is no honest static
  answer. It belongs to the runtime snapshot phase below.
- **The initrd's address inside `.rodata` is not resolved.** `INITRD_DATA` is
  a `&[u8]` whose payload has no symbol of its own, so the `embeds` edge says
  which section holds it without claiming an offset it cannot prove.

## Checking an artifact

`scripts/memory-layout-check.py` is what a consumer would otherwise discover
the hard way, run before the handoff instead:

- every `region_*` array is the same length, and every `space_*` array is
- every `region_space` names a declared space
- region ids are unique — picking depends on it
- regions tile their space in address order: no gaps, no overlaps, nothing
  past capacity
- every relationship endpoint is a region id that exists
- the provenance revision is not `-dirty`, so a consumer can pin it

It takes either serialization, telling them apart by their own shape, and
exits non-zero on any failure, reporting the sha256 a consumer pins.

A revision is `-dirty` only when one of the layout's own inputs is
uncommitted. Unrelated edits elsewhere in the tree do not make a layout
generated from committed inputs unreproducible, and marking it dirty would
make a consumer refuse a pin that is perfectly sound.

## The preview page

`scripts/memory-layout-preview.py` writes a single self-contained HTML file —
no CDN, no build step, no server — that draws the artifact as three adjacent
towers with orbit, pan, zoom, click-to-inspect, the four colour modes, and
relationship lines on the selected region.

It is deliberately **not** the product. The renderer that matters is the
system-agnostic one in `demo-extensions`, where the same code draws SWTOS,
MLOS and MesaOS; nothing in the preview is meant to migrate there. What it is
for is the only question a producer has to answer — does the data describe
the system correctly? — and it answers it by reading the same public columns
a consumer reads. If the towers look wrong, the artifact is wrong.

Its block heights offer three scales because no single one is honest and
useful at once: true scale shows that `.rodata` is 70% of the kernel image and
makes the 16-byte `.limine_requests_end` next to it invisible; the log default
keeps both on screen; equal treats each region as a slab.

That is also how the Linux driver blobs stay out of the way. `xhci-hcd.ko` is
6 MB of a 7 MB initrd — on a true scale it is the entire tower and the 8 KB
`xclock.elf` is a hairline. The log default keeps both legible, colouring by
purpose separates `module` (a `.ko` the driver shim loads) from `image` (an
ELF that gets a user address space), and clicking a legend key hides that
whole class. Hiding `module` leaves the picture that is actually interesting:
the programs.

## Next: the runtime snapshot

Everything above is static — emitted from build artifacts, describing the
system as linked and packed. The phase after this one is a second artifact
describing a *running* MesaOS: the Limine memory map, the frame allocator's
used/free extents, the kernel heap's current and high-water usage, and the
live processes' address spaces.

That needs a kernel change, not another script: `mem` currently reports only
free and total frame counts, which is not a map. The natural shape is a shell
verb that prints the same columnar document over the serial console, so the
runtime artifact and this one are the same contract and the same viewer.
