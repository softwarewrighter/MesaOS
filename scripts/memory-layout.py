#!/usr/bin/env python3
"""Emit the semantic memory layout of a MesaOS build as JSON.

This is the producer end of the boundary described in
`../../sw-ml-study/demo-extensions/docs/research.txt` and pinned by
`../../sw-ml-study/sw-mlpl/docs/storage-layout-viz.md`:

    MesaOS  ->  memory-layout.json  ->  MLPL script  ->  native3d  ->  viewer

MesaOS knows what its memory means. MLPL knows visualization. native3d knows
graphics. Nothing downstream has to learn about Limine, the initrd container
or the x86_64 higher half, and this script draws nothing -- it emits no
colours, no coordinates and no camera.

MesaOS is the third producer of the same contract, after SWTOS
(`../../sw-embed/sw-tos`) and MLOS (`../../sw-ml-study/sw-os-ml`). The
consumer is deliberately system-agnostic, so the shape here is identical to
theirs even though the systems are not: SWTOS shows a NOR flash catalog,
MesaOS shows a linked higher-half kernel image, an initrd embedded inside
that image, and the user address space a program is loaded into.

THE SHAPE IS COLUMNAR (struct-of-arrays). Every `region_*` array has the same
length N and is index-aligned; every `space_*` array has length S and
`spaces[i]` is the key `region_space` joins on. That is not a style
preference: MLPL's `parse_json` ingests homogeneous numeric arrays and string
lists today, while an array-of-objects would need a language feature that
does not exist. Writing rows here would push the cost onto the consumer.

WHERE THE NUMBERS COME FROM. Every figure is read out of an artifact the
build already produces, or out of the one source file that declares it, so
the picture cannot drift from the system it claims to describe:

    kernel image   the linked ELF (`iso/boot/mesa_kernel`), section by
                   section -- not `mesa_kernel/linker.ld`, which says what
                   was asked for rather than what was produced
    initrd         `output/initrd.bin`, the exact bytes the kernel embeds
                   via `include_bytes!` in `fs/initrd_data.rs`, walked with
                   the container format documented in `fs/initrd.rs`
    user space     the `pub const USER_*` declarations in
                   `memory/address_space.rs`, the brk origin in
                   `linux_compat/syscalls.rs`, and the loaded program's own
                   PT_LOAD segments

A region's `kind` is what it is, not how to draw it. Choosing colour, scale
and arrangement is the consumer's job.
"""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "sw-ml-study.system-layout"
VERSION = 1
PRODUCER = "MesaOS"

PAGE = 4096

#: The kernel ELF the ISO boots. `build.sh` links it into
#: `target/<triple>/release/mesa_kernel` and copies it here; the copy is the
#: one that is committed, so it is the one a rendered snapshot is traceable to.
DEFAULT_KERNEL = ROOT / "iso" / "boot" / "mesa_kernel"

#: The initrd container `fs/initrd_data.rs` embeds with `include_bytes!`.
#: `*.bin` is gitignored, so on a fresh clone this does not exist; the initrd
#: space is then omitted rather than invented. `--inyect-dir` packs one from
#: the injection tree instead, using the build's own packer.
DEFAULT_INITRD = ROOT / "output" / "initrd.bin"

#: Owners. The kernel owns its own image and its bookkeeping; free space and
#: unmapped holes are owned by nobody, and saying so is not the same as
#: calling them the kernel's.
KERNEL, NOBODY = "kernel", ""


# --------------------------------------------------------------------------
# ELF
#
# Read in full here rather than shelled out to readelf: the host is often not
# the target (this is an x86_64 ELF that gets inspected from macOS), and a
# producer that only runs where binutils happens to speak ELF is a producer
# that silently stops being run.
# --------------------------------------------------------------------------

SHF_ALLOC = 0x2
SHT_NOBITS = 8
PT_LOAD = 1
PF_X, PF_W, PF_R = 0x1, 0x2, 0x4


class ElfError(ValueError):
    pass


def read_elf(data: bytes) -> dict:
    """The parts of a 64-bit little-endian ELF this producer needs: the
    entry point, the loadable segments, and the allocated sections."""
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ElfError("not an ELF file")
    if data[4] != 2:
        raise ElfError("not ELF64")
    if data[5] != 1:
        raise ElfError("not little-endian")

    e_type, _machine, _version, e_entry, e_phoff, e_shoff = struct.unpack_from(
        "<HHIQQQ", data, 16
    )
    e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
        "<HHHHH", data, 54
    )

    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 56 > len(data):
            raise ElfError("program headers out of bounds")
        p_type, p_flags, _p_off, p_vaddr, _p_paddr, p_filesz, p_memsz, _align = (
            struct.unpack_from("<IIQQQQQQ", data, off)
        )
        if p_type == PT_LOAD and p_memsz:
            segments.append(
                {"vaddr": p_vaddr, "filesz": p_filesz, "memsz": p_memsz,
                 "flags": p_flags}
            )
    segments.sort(key=lambda s: s["vaddr"])

    sections = []
    if e_shnum and e_shoff:
        raw = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            if off + 64 > len(data):
                raise ElfError("section headers out of bounds")
            (sh_name, sh_type, sh_flags, sh_addr, _sh_off, sh_size,
             _link, _info, _align, _entsize) = struct.unpack_from("<IIQQQQIIQQ", data, off)
            raw.append({"index": i, "name_offset": sh_name, "type": sh_type,
                        "flags": sh_flags, "addr": sh_addr, "size": sh_size})
        sections = raw
        if e_shstrndx < len(raw):
            # The section-header string table's own sh_offset/sh_size sit at
            # +24 and +32 of its header; the loop above kept only the fields
            # every section needs.
            off = e_shoff + e_shstrndx * e_shentsize
            str_off, str_size = struct.unpack_from("<QQ", data, off + 24)
            blob = data[str_off:str_off + str_size]
            for section in sections:
                end = blob.find(b"\0", section["name_offset"])
                section["name"] = blob[section["name_offset"]:end].decode(
                    "utf-8", "replace")
        else:
            for section in sections:
                section["name"] = f"section{section['index']}"

    return {"type": e_type, "entry": e_entry, "segments": segments,
            "sections": sections}


def segment_perm(flags: int) -> str:
    """`rwx` as a string, so a consumer can colour by permission without
    learning ELF's bit numbering."""
    return ("r" if flags & PF_R else "-") + \
           ("w" if flags & PF_W else "-") + \
           ("x" if flags & PF_X else "-")


def perm_of(address: int, segments: list[dict]) -> str:
    """The permission of whichever loadable segment covers an address. A
    section outside every segment is not loaded at all, and gets ``""``."""
    for segment in segments:
        if segment["vaddr"] <= address < segment["vaddr"] + segment["memsz"]:
            return segment_perm(segment["flags"])
    return ""


#: Section name -> the kind a visualizer classifies it as. Anything not
#: listed keeps its own name as its kind, which is the honest answer for a
#: section this producer has never seen.
SECTION_KINDS = {
    ".text": "text",
    ".rodata": "rodata",
    ".data": "data",
    ".bss": "bss",
    ".got": "got",
}


def kernel_regions(elf: dict, next_id) -> tuple[list[dict], int, int]:
    """The kernel image, section by section, with the alignment gaps between
    them named rather than hidden. Returns the rows plus the space base and
    capacity.

    Padding is emitted as its own kind because `.text`-to-`.rodata` alignment
    is a real cost of the 4 KiB page granularity, and a picture that folds it
    into the section before it hides what that granularity costs.
    """
    loaded = sorted(
        (s for s in elf["sections"]
         if s["flags"] & SHF_ALLOC and s["addr"] and s["size"]),
        key=lambda s: s["addr"],
    )
    if not loaded:
        raise ElfError("kernel ELF has no allocated sections")

    base = loaded[0]["addr"]
    rows, cursor = [], base
    for section in loaded:
        if section["addr"] > cursor:
            rows.append({
                "id": next_id("kernel-pad", section["index"]),
                "kind": "padding",
                "name": f"page alignment before {section['name']}",
                "owner": KERNEL, "location": "kernel-image", "state": "reserved",
                "perm": "", "start": cursor - base,
                "length": section["addr"] - cursor,
            })
        rows.append({
            "id": next_id("kernel-section", section["index"]),
            "kind": SECTION_KINDS.get(section["name"], section["name"].lstrip(".")),
            "name": section["name"],
            "owner": KERNEL,
            "location": "kernel-image",
            # .bss occupies no file bytes: it is address space the loader
            # zeroes, which is a different thing from stored content.
            "state": "zero" if section["type"] == SHT_NOBITS else "stored",
            "perm": perm_of(section["addr"], elf["segments"]),
            "start": section["addr"] - base,
            "length": section["size"],
        })
        cursor = section["addr"] + section["size"]

    # The image ends mid-page, and the loader maps whole pages: the tail is
    # mapped, owned by the kernel, and holds nothing. Naming it keeps the
    # space fully tiled and shows the last page's slack.
    capacity = align_up(cursor - base, PAGE)
    if capacity > cursor - base:
        rows.append({
            "id": next_id("kernel-pad", len(elf["sections"])),
            "kind": "padding", "name": "page tail", "owner": KERNEL,
            "location": "kernel-image", "state": "reserved", "perm": "",
            "start": cursor - base, "length": capacity - (cursor - base),
        })
    return rows, base, capacity


# --------------------------------------------------------------------------
# initrd
#
# The container format is documented in mesa_kernel/src/fs/initrd.rs:
#
#   [u32 count]  then per entry
#   [u32 name_len][name][u32 path_len][path][u32 data_len][data]
#
# all little-endian, no alignment, no padding. Walking it is the whole point:
# it turns a 6 MB opaque blob inside .rodata into the list of programs and
# files the shell will actually find in its RamFS.
# --------------------------------------------------------------------------

def parse_initrd(data: bytes) -> list[dict]:
    """Every entry, with the byte extents of both its record and its payload,
    so the two can be drawn as separate regions the way a catalog record and
    the image it points at are."""
    if len(data) < 4:
        raise ValueError("initrd too small to hold its entry count")
    count = struct.unpack_from("<I", data, 0)[0]
    entries, offset = [], 4
    for index in range(count):
        record_start = offset

        def field(off: int) -> tuple[bytes, int]:
            if off + 4 > len(data):
                raise ValueError(f"initrd truncated in entry {index}")
            length = struct.unpack_from("<I", data, off)[0]
            off += 4
            if off + length > len(data):
                raise ValueError(f"initrd truncated in entry {index}")
            return data[off:off + length], off + length

        name, offset = field(offset)
        path, offset = field(offset)
        if offset + 4 > len(data):
            raise ValueError(f"initrd truncated in entry {index}")
        data_len = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        payload_start = offset
        if payload_start + data_len > len(data):
            raise ValueError(f"initrd truncated in entry {index}")
        payload = data[payload_start:payload_start + data_len]
        offset = payload_start + data_len

        entries.append({
            "index": index,
            "name": name.decode("utf-8", "replace"),
            "path": path.decode("utf-8", "replace"),
            # The record is everything but the payload: the three length
            # words and the two strings.
            "record_start": record_start,
            "record_length": payload_start - record_start,
            "data_start": payload_start,
            "data_length": data_len,
            "kind": payload_kind(payload),
            "payload": payload,
        })
    return entries


ET_REL, ET_EXEC, ET_DYN = 1, 2, 3


def payload_kind(payload: bytes) -> str:
    """What an initrd payload is, as far as MesaOS is concerned.

    The distinction matters because the three go to different places: an
    `image` is loaded into a user address space by `elf.rs`, a `module` is
    relocated into the kernel's own address space by the Linux driver shim,
    and a `file` is only ever a file in the RamFS. Calling a `.ko` a program
    would draw it as something that gets its own user space, which is exactly
    what it does not get.
    """
    if payload[:4] != b"\x7fELF":
        return "file"
    try:
        elf = read_elf(payload)
    except ElfError:
        return "file"
    if elf["type"] == ET_REL:
        return "module"
    return "image" if elf["segments"] else "file"


def initrd_regions(entries: list[dict], total: int, next_id) -> list[dict]:
    """The container in address order with no gaps: the count word, then a
    record and a payload per entry, then whatever is left over."""
    rows = [{
        "id": next_id("initrd-header", 0),
        "kind": "header", "name": "entry count",
        "owner": KERNEL, "location": "initrd", "state": "stored",
        "perm": "", "start": 0, "length": 4,
    }]
    cursor = 4
    for entry in entries:
        rows.append({
            "id": next_id("initrd-record", entry["index"]),
            "kind": "catalog",
            "name": f"record: {entry['path']}",
            "owner": entry["name"], "location": "initrd", "state": "stored",
            "perm": "", "start": entry["record_start"],
            "length": entry["record_length"],
        })
        rows.append({
            "id": next_id("initrd-file", entry["index"]),
            "kind": entry["kind"],
            "name": entry["path"],
            "owner": entry["name"], "location": "initrd", "state": "stored",
            "perm": "", "start": entry["data_start"],
            "length": entry["data_length"],
        })
        cursor = entry["data_start"] + entry["data_length"]

    if cursor < total:
        rows.append({
            "id": next_id("initrd-free", 0),
            "kind": "free", "name": "unused", "owner": NOBODY,
            "location": "initrd", "state": "free", "perm": "",
            "start": cursor, "length": total - cursor,
        })
    return rows


def pack_initrd(inyect_dir: Path) -> bytes:
    """Pack an initrd from the injection tree using the build's own packer,
    so a layout emitted without a built `output/initrd.bin` still describes
    the container the build would have produced rather than a second
    implementation of the same format."""
    import importlib.util
    import tempfile

    packer_path = ROOT / "tools" / "inject_to_iso.py"
    spec = importlib.util.spec_from_file_location("mesaos_inject", packer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {packer_path}")
    packer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packer)

    files = sorted(str(p) for p in inyect_dir.rglob("*") if p.is_file())
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "initrd.bin"
        packer.build_initrd({
            "files": files,
            "inject_dir": str(inyect_dir),
            "use_default": True,
            "initrd_path": str(out),
        })
        return out.read_bytes()


# --------------------------------------------------------------------------
# user address space
#
# Read out of the kernel sources that declare it rather than restated here:
# if the kernel moves its stack, the picture moves with it.
# --------------------------------------------------------------------------

def rust_const(source: Path, name: str) -> int:
    """One `pub const NAME: u64 = <expr>;` from a Rust source file. The
    expression is a literal or a small product of literals -- `64 * 1024` --
    which is exactly what these declarations are, and nothing more is
    evaluated."""
    text = source.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        rf"(?:pub\s+)?(?:static\s+mut\s+|const\s+){re.escape(name)}\s*:\s*u\d+\s*=\s*([^;]+);",
        text,
    )
    if not match:
        raise ValueError(f"{name} not found in {source}")
    expression = match.group(1).replace("_", "").strip()
    if not re.fullmatch(r"[0-9a-fA-FxX*+\s]+", expression):
        raise ValueError(f"{name} in {source} is not a plain literal: {expression}")
    return int(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307


def user_layout() -> dict:
    """The nominal user address space. Nominal, not actual: `elf.rs`
    randomizes the stack top and the load base of PIE binaries, so an
    observed process sits near these addresses rather than on them."""
    address_space = ROOT / "mesa_kernel" / "src" / "memory" / "address_space.rs"
    syscalls = ROOT / "mesa_kernel" / "src" / "linux_compat" / "syscalls.rs"
    stack_top = rust_const(address_space, "USER_STACK_TOP")
    return {
        "code_base": rust_const(address_space, "USER_CODE_BASE"),
        "stack_top": stack_top,
        "stack_size": rust_const(address_space, "USER_STACK_SIZE"),
        "heap_base": rust_const(address_space, "USER_HEAP_BASE"),
        "brk_origin": rust_const(syscalls, "PROGRAM_BREAK"),
        # mmap_get_unused_addr() starts its search one 16 MiB step above the
        # heap base and stops at the bottom of the stack.
        "mmap_base": rust_const(address_space, "USER_HEAP_BASE") + 0x100_0000,
    }


SEGMENT_KINDS = [(PF_X, "text"), (PF_W, "data")]


def user_regions(program: dict | None, layout: dict, next_id) -> list[dict]:
    """A user address space with a program loaded into it, in address order
    with no gaps: the null guard, the program's own loadable segments, the
    brk origin, the mmap arena and the stack."""
    rows = []
    owner = program["name"] if program else NOBODY

    def gap(start: int, end: int, name: str) -> None:
        if end > start:
            rows.append({
                "id": next_id("user-gap", start), "kind": "free", "name": name,
                "owner": NOBODY, "location": "user-space", "state": "unmapped",
                "perm": "", "start": start, "length": end - start,
            })

    cursor = 0
    if program:
        for number, segment in enumerate(program["elf"]["segments"]):
            gap(cursor, segment["vaddr"], "unmapped")
            kind = next((k for bit, k in SEGMENT_KINDS
                         if segment["flags"] & bit), "rodata")
            perm = segment_perm(segment["flags"])
            rows.append({
                "id": next_id("user-segment", number), "kind": kind,
                "name": f"{program['name']} {kind}", "owner": owner,
                "location": "user-space", "state": "live", "perm": perm,
                "start": segment["vaddr"], "length": segment["filesz"],
            })
            # memsz beyond filesz is the segment's .bss: address space the
            # loader zeroes, with no bytes behind it in the file.
            if segment["memsz"] > segment["filesz"]:
                rows.append({
                    "id": next_id("user-segment-bss", number), "kind": "bss",
                    "name": f"{program['name']} bss", "owner": owner,
                    "location": "user-space", "state": "zero", "perm": perm,
                    "start": segment["vaddr"] + segment["filesz"],
                    "length": segment["memsz"] - segment["filesz"],
                })
            cursor = segment["vaddr"] + segment["memsz"]
    else:
        gap(0, layout["code_base"], "unmapped")
        cursor = layout["code_base"]

    # The break starts at a fixed address and grows up on demand; one page is
    # drawn so the origin is visible, not because one page is reserved.
    gap(cursor, layout["brk_origin"], "unmapped")
    rows.append({
        "id": next_id("user-brk", 0), "kind": "heap",
        "name": "brk origin", "owner": owner, "location": "user-space",
        "state": "reserved", "perm": "rw-",
        "start": layout["brk_origin"], "length": PAGE,
    })

    stack_bottom = layout["stack_top"] - layout["stack_size"]
    gap(layout["brk_origin"] + PAGE, layout["mmap_base"], "unmapped")
    rows.append({
        "id": next_id("user-mmap", 0), "kind": "mmap",
        "name": "mmap arena", "owner": NOBODY, "location": "user-space",
        "state": "free", "perm": "", "start": layout["mmap_base"],
        "length": stack_bottom - layout["mmap_base"],
    })
    rows.append({
        "id": next_id("user-stack", 0), "kind": "stack",
        "name": f"{owner or 'user'} stack", "owner": owner,
        "location": "user-space", "state": "live", "perm": "rw-",
        "start": stack_bottom, "length": layout["stack_size"],
    })
    return rows


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def align_up(value: int, to: int) -> int:
    return (value + to - 1) // to * to


class Ids:
    """Stable region ids.

    native3d picks and cross-highlights by id, so an id that shifts when a
    file is injected would move the selection to a different region. Ids are
    therefore derived from what MesaOS itself uses to identify a thing -- an
    ELF section header index, an initrd entry index, a fixed address-space
    slot -- inside a per-category base, rather than from a position in the
    emitted array.
    """

    BASES = {
        "initrd-header": 1, "initrd-free": 3,
        "kernel-section": 1_000, "kernel-pad": 2_000,
        "initrd-record": 3_000, "initrd-file": 4_000,
        "user-segment": 5_000, "user-segment-bss": 5_500, "user-brk": 6_000,
        "user-mmap": 6_001, "user-stack": 6_002, "user-gap": 7_000,
    }

    def __init__(self):
        self.taken: dict[int, str] = {}

    def __call__(self, category: str, key: int) -> int:
        # A gap is identified by where it starts, which can be large; fold it
        # into the category's range and resolve the rare collision by probing.
        ident = self.BASES[category] + (key if category != "user-gap"
                                        else key // PAGE % 1000)
        while ident in self.taken:
            ident += 1
        self.taken[ident] = category
        return ident


#: What the emitted layout is actually read from. Only these decide whether a
#: revision is honest: a tree with unrelated edits elsewhere still produced
#: this artifact from committed inputs, and marking it dirty would make a
#: consumer refuse a pin that is perfectly sound.
INPUT_PATHS = [
    "iso/boot/mesa_kernel",
    "output/initrd.bin",
    "inyect",
    "mesa_kernel/src/memory/address_space.rs",
    "mesa_kernel/src/linux_compat/syscalls.rs",
    "mesa_kernel/src/fs/initrd.rs",
    "tools/inject_to_iso.py",
    "scripts/memory-layout.py",
]


def revision() -> str:
    """The producer's source revision, so a rendered snapshot is traceable
    back to the tree that produced it. An input edited but not committed is
    marked `-dirty`: a bare hash would claim a picture came from committed
    sources when it did not, and a consumer pins this to reproduce it."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True)
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--"]
            + INPUT_PATHS,
            cwd=ROOT, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def choose_program(entries: list[dict], wanted: str | None) -> dict | None:
    """The program whose loaded address space is drawn. One user space is
    drawn, not one per program, because MesaOS gives each process its own
    page tables at the same nominal addresses -- overlaying them would draw
    the same rectangle N times."""
    elves = [e for e in entries if e["kind"] == "image"]
    if wanted:
        match = [e for e in elves
                 if wanted in (e["name"], e["path"], Path(e["path"]).name)]
        if not match:
            available = ", ".join(e["path"] for e in elves) or "none"
            raise ValueError(f"no ELF named {wanted!r} in the initrd (have: {available})")
        chosen = match[0]
    elif elves:
        chosen = min(elves, key=lambda e: e["index"])
    else:
        return None
    return {"name": Path(chosen["path"]).name, "entry": chosen,
            "elf": read_elf(chosen["payload"])}


def build(kernel_bytes: bytes, initrd_bytes: bytes | None,
          wanted_program: str | None, source_revision: str | None) -> dict:
    ids = Ids()
    kernel_elf = read_elf(kernel_bytes)
    kernel_rows, kernel_base, kernel_capacity = kernel_regions(kernel_elf, ids)

    spaces = [{
        "id": "kernel", "name": "kernel image (higher half)",
        "base": kernel_base, "block": PAGE, "capacity": kernel_capacity,
        "rows": kernel_rows,
    }]

    entries = parse_initrd(initrd_bytes) if initrd_bytes is not None else []
    if initrd_bytes is not None:
        spaces.append({
            "id": "initrd", "name": "embedded initrd", "base": 0,
            # The container is byte-packed with no alignment at all, so a
            # block larger than a byte would draw boundaries that do not exist.
            "block": 1, "capacity": len(initrd_bytes),
            "rows": initrd_regions(entries, len(initrd_bytes), ids),
        })

    program = choose_program(entries, wanted_program)
    layout = user_layout()
    spaces.append({
        "id": "user", "name": "user address space", "base": 0,
        "block": PAGE, "capacity": layout["stack_top"],
        "rows": user_regions(program, layout, ids),
    })

    rows = [row for space in spaces for row in space["rows"]]
    space_of = {id(row): space["id"] for space in spaces for row in space["rows"]}

    def column(field, default=0):
        return [row.get(field, default) for row in rows]

    document = {
        "schema": SCHEMA,
        "version": VERSION,
        "provenance": {
            "producer": PRODUCER,
            "revision": source_revision or revision(),
            "kernel_sha256": hashlib.sha256(kernel_bytes).hexdigest(),
            "initrd_sha256": (hashlib.sha256(initrd_bytes).hexdigest()
                              if initrd_bytes is not None else ""),
        },

        "spaces": [space["id"] for space in spaces],
        "space_name": [space["name"] for space in spaces],
        "space_block": [space["block"] for space in spaces],
        "space_capacity": [space["capacity"] for space in spaces],
        # Absolute address the space starts at. Region offsets are relative to
        # it so that a higher-half kernel does not force a consumer to lay out
        # 2^47 empty blocks before the first byte of .text.
        "space_base": [space["base"] for space in spaces],
        # The same value as text, because 0xffffffff80000000 is beyond the
        # 2^53 a JSON number is safe at in a JavaScript consumer. It happens
        # to survive the round trip today; a future base one page lower would
        # not, and an address that is quietly wrong is worse than no address.
        "space_base_hex": [f"{space['base']:#x}" for space in spaces],
        "space_used": [sum(row["length"] for row in space["rows"]
                           if row["kind"] not in ("free", "mmap"))
                       for space in spaces],

        "region_id": column("id"),
        "region_space": [space_of[id(row)] for row in rows],
        "region_kind": column("kind"),
        "region_name": column("name"),
        "region_owner": column("owner", ""),
        "region_start": column("start"),
        "region_length": column("length"),

        # The other three colour modes the visualization asks for. `kind` is
        # purpose; these are location, lifecycle state, and the page
        # permission the region is mapped with (empty where it is not mapped).
        "region_location": column("location", ""),
        "region_state": column("state", ""),
        "region_perm": column("perm", ""),
    }
    document.update(relationships(entries, program, ids, kernel_rows,
                                  initrd_bytes is not None))

    # Length P, not length N: an initrd entry that is not an ELF has a region
    # but is not a program, and a program has more than one region.
    document.update({
        "program_name": [Path(e["path"]).name for e in entries],
        "program_path": [e["path"] for e in entries],
        "program_kind": [e["kind"] for e in entries],
        "program_length": [e["data_length"] for e in entries],
        "program_region": [Ids.BASES["initrd-file"] + e["index"] for e in entries],
    })
    return document


def relationships(entries: list[dict], program: dict | None, ids: Ids,
                  kernel_rows: list[dict], has_initrd: bool) -> dict:
    """The edge table: what explains what. Length E, independent of N.

    Three kinds, which together are the chain this visualization exists to
    show -- a file is embedded in the kernel image, described by a record,
    and loaded into an address space:

        embeds     .rodata -> the initrd it holds via include_bytes!
        describes  an initrd record -> the payload it points at
        loads-to   an initrd ELF -> the user segments it becomes
    """
    kind, source, target = [], [], []

    if has_initrd:
        rodata = next((row for row in kernel_rows if row["name"] == ".rodata"), None)
        header = Ids.BASES["initrd-header"]
        if rodata is not None:
            kind.append("embeds")
            source.append(rodata["id"])
            target.append(header)

    for entry in entries:
        kind.append("describes")
        source.append(Ids.BASES["initrd-record"] + entry["index"])
        target.append(Ids.BASES["initrd-file"] + entry["index"])

    if program:
        stored = Ids.BASES["initrd-file"] + program["entry"]["index"]
        for region_id, category in ids.taken.items():
            if category in ("user-segment", "user-segment-bss", "user-stack"):
                kind.append("loads-to")
                source.append(stored)
                target.append(region_id)

    return {"rel_kind": kind, "rel_from": source, "rel_to": target}


# --------------------------------------------------------------------------
# the row shape
#
# The two consumers read the same schema name two different ways. sw-mlpl's
# contract is columnar because `parse_json` ingests homogeneous arrays and an
# array-of-objects would need a language feature MLPL does not have;
# demo-extensions' bounded Rust parser reads rows, with string ids and a
# four-field provenance. Neither is wrong and reconciling them is not this
# repository's call to make.
#
# What this repository can do is refuse to be the reason either one waits. The
# model is the same either way -- spaces, regions, relationships -- so the row
# shape below is a second serialization of one document, not a second document.
#
# The row form is lossy on purpose: its schema is `additionalProperties:
# false`, so `region_perm` and `space_base` have nowhere to go. The columnar
# artifact remains the complete one.
# --------------------------------------------------------------------------

#: The row schema requires every text field to be non-empty, so the absence of
#: an owner has to be spelled rather than left blank.
UNOWNED = "unowned"


def as_rows(document: dict, generated_at: str) -> dict:
    """The same layout as rows, conforming to demo-extensions'
    `system-layout-v1.schema.json`."""
    spaces = []
    for i, space in enumerate(document["spaces"]):
        extent = document["space_capacity"][i]
        block = document["space_block"][i]
        entry = {"id": space, "address_unit": "byte", "extent": extent}
        # The parser rejects a block size the extent is not a multiple of --
        # a granule that does not divide the space is not a granule.
        if extent % block == 0:
            entry["block_size"] = block
        spaces.append(entry)

    regions = []
    for i in range(len(document["region_id"])):
        regions.append({
            # Ids are strings here and integers in the columnar form. Both are
            # stable and both derive from the same producer-assigned number.
            "id": f"{document['region_space'][i]}.{document['region_id'][i]}",
            "space_id": document["region_space"][i],
            "address": document["region_start"][i],
            "extent": document["region_length"][i],
            "purpose": document["region_kind"][i],
            "owner": document["region_owner"][i] or UNOWNED,
            "location": document["region_location"][i] or "unplaced",
            "state": document["region_state"][i] or "unknown",
        })

    by_number = {document["region_id"][i]: regions[i]["id"]
                 for i in range(len(regions))}
    relationships = []
    for i, kind in enumerate(document["rel_kind"]):
        source = by_number[document["rel_from"][i]]
        target = by_number[document["rel_to"][i]]
        if source == target:  # the parser rejects a self-edge, rightly
            continue
        relationships.append({"id": f"rel.{i}", "kind": kind,
                              "from_region_id": source, "to_region_id": target})

    provenance = document["provenance"]
    return {
        "schema": document["schema"],
        "version": document["version"],
        "provenance": {
            "producer": provenance["producer"],
            "producer_revision": provenance["revision"],
            "generated_at": generated_at,
            "source_description":
                "Linked kernel ELF, embedded initrd container, and the nominal "
                "user address space of a loaded program",
        },
        "spaces": spaces,
        "regions": regions,
        "relationships": relationships,
    }


def committed_at() -> str:
    """The HEAD commit's date, as the `generated_at` the row schema requires.

    Wall-clock time would make every regeneration produce different bytes and
    turn a checksum a consumer pins into a moving target. The commit date is
    what the artifact actually describes the state of.
    """
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cd", "--date=iso-strict", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kernel", type=Path, default=DEFAULT_KERNEL,
                        help="the linked kernel ELF the ISO boots")
    parser.add_argument("--initrd", type=Path, default=DEFAULT_INITRD,
                        help="the initrd container the kernel embeds")
    parser.add_argument("--inyect-dir", type=Path, default=None,
                        help="pack an initrd from this injection tree instead "
                             "of reading one (uses tools/inject_to_iso.py)")
    parser.add_argument("--program", default=None,
                        help="which embedded ELF's loaded address space to "
                             "draw (default: the first one in the initrd)")
    parser.add_argument("-o", "--output", type=Path,
                        default=ROOT / "build" / "memory-layout.json")
    parser.add_argument("--revision", default=None,
                        help="record this as the producer revision instead of "
                             "asking git (for a reproducible artifact)")
    parser.add_argument("--shape", choices=("columnar", "row", "both"),
                        default="both",
                        help="which serialization to write: columnar for "
                             "sw-mlpl, row for demo-extensions' bounded "
                             "parser, or both (default)")
    args = parser.parse_args()

    if not args.kernel.exists():
        print(f"memory-layout: no kernel at {args.kernel}; run ./build.sh build",
              file=sys.stderr)
        return 1

    initrd_bytes = None
    if args.inyect_dir is not None:
        if not args.inyect_dir.is_dir():
            print(f"memory-layout: no injection tree at {args.inyect_dir}",
                  file=sys.stderr)
            return 1
        initrd_bytes = pack_initrd(args.inyect_dir)
    elif args.initrd.exists():
        initrd_bytes = args.initrd.read_bytes()
    else:
        print(f"memory-layout: no initrd at {args.initrd}; emitting the kernel "
              f"and user spaces only (pass --inyect-dir inyect to pack one)",
              file=sys.stderr)

    try:
        document = build(args.kernel.read_bytes(), initrd_bytes, args.program,
                         args.revision)
    except (ElfError, ValueError) as error:
        print(f"memory-layout: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = []
    if args.shape in ("columnar", "both"):
        args.output.write_text(json.dumps(document, indent=2) + "\n")
        written.append(args.output)
    if args.shape in ("row", "both"):
        rows = args.output.with_suffix(".rows.json")
        rows.write_text(json.dumps(as_rows(document, committed_at()),
                                   indent=2) + "\n")
        written.append(rows)

    kinds: dict[str, int] = {}
    for kind in document["region_kind"]:
        kinds[kind] = kinds.get(kind, 0) + 1
    print(f"  spaces:  {', '.join(document['spaces'])}")
    print(f"  regions: {len(document['region_id'])} "
          f"({', '.join(f'{n}x {k}' for k, n in sorted(kinds.items()))})")
    print(f"  edges:   {len(document['rel_kind'])}")
    # The kind vocabulary, so relaying it to whoever owns the consumer's
    # palette is a matter of reading the last run: a kind with no palette row
    # draws as nothing.
    print(f"  kinds:   {' '.join(sorted(kinds))}")
    for path in written:
        shape = "row     " if path.name.endswith(".rows.json") else "columnar"
        print(f"  {shape} {path}")
        print(f"           sha256 {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
