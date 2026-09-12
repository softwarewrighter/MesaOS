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
            (sh_name, sh_type, sh_flags, sh_addr, sh_off, sh_size,
             _link, _info, _align, _entsize) = struct.unpack_from("<IIQQQQIIQQ", data, off)
            raw.append({"index": i, "name_offset": sh_name, "type": sh_type,
                        "flags": sh_flags, "addr": sh_addr, "size": sh_size,
                        "file_offset": sh_off})
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
# symbols, and what part of the project they came from
#
# Sections answer "how much of the image is read-only data". They do not
# answer "how much of the image is the USB stack", which is the question a
# rough layout is actually asked. The kernel ELF is not stripped, so the
# symbol table can answer it: every sized symbol carries a Rust v0 mangled
# path whose prefix names the crate and module it was compiled from.
#
# The attribution is deliberately rough. Symbols cover about a third of the
# image -- .text almost completely, .bss well, .rodata barely -- and what is
# left over is reported as unattributed rather than distributed by guesswork.
# An honest third is worth more than a fabricated whole.
# --------------------------------------------------------------------------

STT_OBJECT, STT_FUNC = 1, 2
SHT_SYMTAB = 2


def read_symbols(data: bytes) -> list[dict]:
    """Every symbol with both an address and a size. A symbol with neither
    describes nothing that occupies memory."""
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, _ = struct.unpack_from("<HHH", data, 0x3A)
    headers = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        if off + 64 > len(data):
            return []
        headers.append(struct.unpack_from("<IIQQQQIIQQ", data, off))

    table = next((h for h in headers if h[1] == SHT_SYMTAB), None)
    if table is None or table[6] >= len(headers):
        return []
    strings = headers[table[6]]

    def name_at(offset: int) -> str:
        start = strings[4] + offset
        end = data.find(b"\0", start)
        return data[start:end].decode("utf-8", "replace")

    symbols = []
    for i in range(table[5] // 24):
        off = table[4] + i * 24
        if off + 24 > len(data):
            break
        name, info, _other, shndx, value, size = struct.unpack_from(
            "<IBBHQQ", data, off)
        if size and value and (info & 0xF) in (STT_OBJECT, STT_FUNC):
            symbols.append({"name": name_at(name), "address": value,
                            "size": size, "section": shndx})
    symbols.sort(key=lambda s: s["address"])
    return symbols


def v0_path(mangled: str) -> list[str]:
    """The path prefix of a Rust v0 mangled name, outermost first.

    Only the prefix is decoded, because only the prefix says where the code
    came from: `_RNvNtNtCs..._11mesa_kernel6memory3pmm6BITMAP` yields
    `[mesa_kernel, memory, pmm, BITMAP]`. Generic arguments, types and
    backreferences are not decoded -- the grammar for those is large, and
    nothing here needs them.
    """
    i, out = 2, []

    def number() -> int | None:
        nonlocal i
        start = i
        while i < len(mangled) and mangled[i].isdigit():
            i += 1
        return int(mangled[start:i]) if i > start else None

    def skip_disambiguator() -> None:
        nonlocal i
        if i < len(mangled) and mangled[i] == "s":
            i += 1
            while i < len(mangled) and mangled[i] != "_":
                i += 1
            i += 1

    def identifier() -> str | None:
        nonlocal i
        skip_disambiguator()
        punycode = i < len(mangled) and mangled[i] == "u"
        if punycode:
            i += 1
        length = number()
        if length is None:
            return None
        if i < len(mangled) and mangled[i] == "_":
            i += 1
        text, i_end = mangled[i:i + length], i + length
        i = i_end
        return text

    def path(depth: int = 0) -> bool:
        """Descend to the crate root, then collect identifiers on the way
        back out -- which is the order the path reads in."""
        nonlocal i
        if depth > 24 or i >= len(mangled):
            return False
        tag = mangled[i]
        i += 1
        if tag == "C":
            name = identifier()
            if name is None:
                return False
            out.append(name)
            return True
        if tag == "N":
            i += 1  # the namespace byte
            if not path(depth + 1):
                return False
            name = identifier()
            if name is not None:
                out.append(name)
            return True
        if tag in ("I", "M", "X", "Y"):
            # A specialization or an impl still hangs off a path; descend
            # into it and stop there rather than decoding the type grammar.
            # An impl path carries its own disambiguator first.
            if tag in ("M", "X", "Y"):
                skip_disambiguator()
            return path(depth + 1)
        return False  # a backreference or something undecoded

    if not mangled.startswith("_R"):
        return []
    path()
    return out


def legacy_path(mangled: str) -> list[str]:
    """The same for the older `_ZN3foo3barE` mangling."""
    i, out = 3, []
    while i < len(mangled) and mangled[i].isdigit():
        start = i
        while i < len(mangled) and mangled[i].isdigit():
            i += 1
        length = int(mangled[start:i])
        out.append(mangled[i:i + length])
        i += length
    return out


#: Unmangled symbols, bucketed by what they actually are. The Linux driver
#: shim is the interesting one: it is a headline feature of this kernel and
#: exports its symbols under C names, so leaving it in an "unmangled" pile
#: would hide several hundred functions that are very much part of the
#: project.
BUILTIN_NAMES = {"memcpy", "memmove", "memset", "memcmp", "strlen", "bcmp"}


def plain_bucket(name: str) -> str:
    if name.startswith("__shim_"):
        return "mesa_kernel::shim (C ABI)"
    if name in BUILTIN_NAMES or name.startswith("__"):
        return "compiler_builtins"
    return "(unmangled)"


def attribute(symbol: dict, depth: int) -> str:
    """Which part of the project a symbol belongs to.

    `depth` is how many path segments below the crate to keep. One gives a
    per-subsystem view (`mesa_kernel::drivers`), two goes a level finer
    (`mesa_kernel::drivers::usb`). A symbol that sits directly in the crate
    root keeps its own name, which is what makes a shell built-in such as
    `nano` visible as itself rather than dissolved into the crate.
    """
    path = v0_path(symbol["name"]) or legacy_path(symbol["name"])
    if not path:
        return plain_bucket(symbol["name"])
    return "::".join(path[:1 + max(depth, 1)])


#: How far apart two symbols from the same part can sit and still be drawn
#: as one run. Between consecutive functions there is alignment padding, and
#: the symbol table does not cover every literal a function refers to, so
#: without a tolerance a subsystem shatters into a thousand slivers with a
#: sliver of "no symbol" between each pair. A page is the granularity the
#: kernel is mapped at, which makes it the natural place to stop pretending
#: to know more.
MERGE_GAP = PAGE


def module_regions(symbols: list[dict], base: int, capacity: int,
                   depth: int, known: list[dict], next_id,
                   merge_gap: int = MERGE_GAP) -> list[dict]:
    """The kernel image again, attributed to the parts it was built from.

    Adjacent symbols from the same part are merged into one run, because a
    picture with one box per symbol is a picture of nothing. Everything the
    symbol table does not cover becomes an `unattributed` region -- mostly
    .rodata, which is string literals and the embedded initrd -- so the space
    still tiles and the size of what is not known stays visible.

    `known` names extents that are unattributed but not unknown; the initrd
    is the whole reason .rodata is the size it is, and labelling it turns the
    largest region in the image from a mystery into a fact.
    """
    runs: list[dict] = []
    for symbol in symbols:
        start, end = symbol["address"], symbol["address"] + symbol["size"]
        if start < base or end > base + capacity:
            continue
        part = attribute(symbol, depth)
        if runs and start < runs[-1]["end"] and runs[-1]["part"] != part:
            continue  # an overlapping alias from elsewhere; the first wins
        if (runs and runs[-1]["part"] == part
                and start <= runs[-1]["end"] + merge_gap):
            runs[-1]["end"] = max(runs[-1]["end"], end)
            runs[-1]["symbols"] += 1
        else:
            runs.append({"part": part, "start": start, "end": end,
                         "symbols": 1})

    labelled = sorted(known, key=lambda k: k["start"])
    rows, cursor = [], base

    def fill(upto: int) -> None:
        """Name the space between two runs, using a known extent where one
        covers it and `unattributed` everywhere else."""
        nonlocal cursor
        while cursor < upto:
            here = next((k for k in labelled
                         if k["start"] < upto and k["end"] > cursor), None)
            if here is None:
                rows.append(gap_row(cursor, upto))
                cursor = upto
                return
            if here["start"] > cursor:
                rows.append(gap_row(cursor, here["start"]))
                cursor = here["start"]
            end = min(here["end"], upto)
            rows.append({
                "id": next_id("kernel-known", here["index"]),
                "kind": here["kind"], "name": here["name"],
                "owner": here["owner"], "location": "kernel-image",
                "state": "stored", "perm": "r--", "module": here["name"],
                "start": cursor - base, "length": end - cursor,
            })
            cursor = end

    def gap_row(start: int, end: int) -> dict:
        return {
            "id": next_id("kernel-unattributed", (start - base) // PAGE),
            "kind": "unattributed", "name": "no symbol", "owner": NOBODY,
            "location": "kernel-image", "state": "stored", "perm": "",
            "module": "", "start": start - base, "length": end - start,
        }

    for run in runs:
        fill(run["start"])
        rows.append({
            "id": next_id("kernel-module", (run["start"] - base) // 8),
            "kind": "code", "name": run["part"], "owner": run["part"],
            "location": "kernel-image", "state": "stored",
            "perm": "", "module": run["part"],
            "start": run["start"] - base, "length": run["end"] - run["start"],
            "symbols": run["symbols"],
        })
        cursor = run["end"]
    fill(base + capacity)
    return rows


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


def find_embedded_initrd(kernel: bytes, elf: dict) -> dict | None:
    """The initrd container actually embedded in this kernel, found by
    walking `.rodata` for one that parses.

    `INITRD_DATA` is a `&[u8]`, so the payload has no symbol of its own and
    cannot be looked up -- but the container is self-describing enough to
    recognise: a plausible entry count, then entries whose name and path
    lengths bound printable ASCII, walked to a clean end. On this kernel
    exactly one offset in 7.7 MB satisfies that, which is the point: a format
    this constrained is not matched by accident.

    Finding it matters twice over. It is the difference between saying "the
    initrd is somewhere in .rodata" and pointing at it, and it is the only
    way to describe the initrd this kernel really carries rather than the one
    the injection tree would produce on the next build.
    """
    rodata = next((s for s in elf["sections"] if s.get("name") == ".rodata"),
                  None)
    if rodata is None:
        return None
    file_start = rodata["file_offset"]
    end = min(file_start + rodata["size"], len(kernel))

    offset = file_start
    while offset < end - 8:
        # Both leading words are small, so their high bytes are zero. Testing
        # that first keeps the scan over several megabytes cheap.
        if kernel[offset + 3] or kernel[offset + 7]:
            offset += 1
            continue
        count = struct.unpack_from("<I", kernel, offset)[0]
        if 1 <= count <= 1024:
            name_len = struct.unpack_from("<I", kernel, offset + 4)[0]
            if (1 <= name_len <= 64
                    and all(32 <= c < 127
                            for c in kernel[offset + 8:offset + 8 + name_len])):
                try:
                    entries = parse_initrd(kernel[offset:end])
                except ValueError:
                    entries = None
                if entries and len(entries) == count:
                    length = (entries[-1]["data_start"]
                              + entries[-1]["data_length"])
                    return {
                        "bytes": kernel[offset:offset + length],
                        "file_offset": offset,
                        "address": rodata["addr"] + (offset - file_start),
                        "length": length,
                    }
        offset += 1
    return None


def pack_initrd(inyect_dir: Path) -> bytes:
    """Pack an initrd from the injection tree using the build's own packer,
    so a layout emitted without a built `output/initrd.bin` still describes
    the container the build would have produced rather than a second
    implementation of the same format."""
    import importlib.util
    import tempfile

    # Importing the packer would otherwise drop a __pycache__ beside it.
    # Reading a repository should not write to it.
    bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
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
        packed = out.read_bytes()
    sys.dont_write_bytecode = bytecode
    return packed


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


def user_regions(program: dict | None, layout: dict, next_id,
                 slot: int = 0) -> list[dict]:
    """A user address space with a program loaded into it, in address order
    with no gaps: the null guard, the program's own loadable segments, the
    brk origin, the mmap arena and the stack.

    `slot` keeps the ids of one program's tower apart from another's. Every
    process is laid out at the same nominal addresses, so without it two
    programs would claim the same region ids and picking one would select
    the other.
    """
    rows = []
    owner = program["name"] if program else NOBODY
    seat = slot * 100

    def gap(start: int, end: int, name: str) -> None:
        if end > start:
            rows.append({
                "id": next_id("user-gap", start + seat), "kind": "free", "name": name,
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
                "id": next_id("user-segment", number + seat), "kind": kind,
                "name": f"{program['name']} {kind}", "owner": owner,
                "location": "user-space", "state": "live", "perm": perm,
                "start": segment["vaddr"], "length": segment["filesz"],
            })
            # memsz beyond filesz is the segment's .bss: address space the
            # loader zeroes, with no bytes behind it in the file.
            if segment["memsz"] > segment["filesz"]:
                rows.append({
                    "id": next_id("user-segment-bss", number + seat), "kind": "bss",
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
        "id": next_id("user-brk", seat), "kind": "heap",
        "name": "brk origin", "owner": owner, "location": "user-space",
        "state": "reserved", "perm": "rw-",
        "start": layout["brk_origin"], "length": PAGE,
    })

    stack_bottom = layout["stack_top"] - layout["stack_size"]
    gap(layout["brk_origin"] + PAGE, layout["mmap_base"], "unmapped")
    rows.append({
        "id": next_id("user-mmap", seat), "kind": "mmap",
        "name": "mmap arena", "owner": NOBODY, "location": "user-space",
        "state": "free", "perm": "", "start": layout["mmap_base"],
        "length": stack_bottom - layout["mmap_base"],
    })
    rows.append({
        "id": next_id("user-stack", seat), "kind": "stack",
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
        "user-mmap": 6_200, "user-stack": 6_400, "user-gap": 7_000,
        "kernel-module": 100_000, "kernel-unattributed": 400_000,
        "kernel-known": 500_000,
    }

    def __init__(self):
        self.taken: dict[int, str] = {}

    def __call__(self, category: str, key: int) -> int:
        # A gap is identified by where it starts, which can be large; fold it
        # into the category's range and resolve the rare collision by probing.
        ident = self.BASES[category] + (key if category != "user-gap"
                                        else key // PAGE % 100_000)
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


#: Where the curated Ring 3 command experiments live in the injection tree.
#: They are the programs worth drawing a loaded address space for by default:
#: the `bin/linux*.elf` set are syscall probes that all link identically, so
#: drawing fifteen of them would be drawing the same picture fifteen times.
EXPERIMENTS = "experiments/"


def choose_programs(entries: list[dict], wanted: list[str]) -> list[dict]:
    """The programs whose loaded address spaces are drawn, one tower each.

    Each MesaOS process gets its own page tables at the same nominal
    addresses, so these towers overlay in the machine even though they are
    drawn side by side. That is the point of drawing them side by side.
    """
    elves = [e for e in entries if e["kind"] == "image"]
    if wanted:
        chosen = []
        for name in wanted:
            match = [e for e in elves
                     if name in (e["name"], e["path"], Path(e["path"]).name)]
            if not match:
                available = ", ".join(e["path"] for e in elves) or "none"
                raise ValueError(
                    f"no ELF named {name!r} in the initrd (have: {available})")
            if match[0] not in chosen:
                chosen.append(match[0])
    else:
        chosen = [e for e in elves if e["path"].startswith(EXPERIMENTS)]
        if not chosen and elves:
            chosen = [min(elves, key=lambda e: e["index"])]

    return [{"name": Path(e["path"]).name, "entry": e,
             "elf": read_elf(e["payload"])} for e in chosen]


def build(kernel_bytes: bytes, initrd: dict | None, wanted: list[str],
          source_revision: str | None, module_depth: int,
          embedded: dict | None = None) -> dict:
    ids = Ids()
    kernel_elf = read_elf(kernel_bytes)
    kernel_rows, kernel_base, kernel_capacity = kernel_regions(kernel_elf, ids)

    spaces = [{
        "id": "kernel", "name": "kernel image, by section",
        "base": kernel_base, "block": PAGE, "capacity": kernel_capacity,
        "rows": kernel_rows,
    }]

    initrd_bytes = initrd["bytes"] if initrd else None
    entries = parse_initrd(initrd_bytes) if initrd_bytes is not None else []

    # The same bytes again, attributed to the parts of the project they were
    # built from. Sections say how much is read-only data; this says how much
    # is the USB stack -- which is the question a rough layout is asked.
    # The blob labelled inside the kernel image is always the one this
    # kernel actually carries, even when the initrd drawn in its own tower
    # came from the injection tree. The bytes in .rodata do not change
    # because a different container was asked about.
    known = []
    if embedded and embedded.get("address"):
        known.append({
            "index": 0, "kind": "blob",
            "name": "embedded initrd", "owner": KERNEL,
            "start": embedded["address"],
            "end": embedded["address"] + embedded["length"],
        })
    spaces.append({
        "id": "kernel-modules", "name": "kernel image, by module",
        "base": kernel_base, "block": 1, "capacity": kernel_capacity,
        "overlays": "kernel",
        "rows": module_regions(read_symbols(kernel_bytes), kernel_base,
                               kernel_capacity, module_depth, known, ids),
    })

    if initrd_bytes is not None:
        spaces.append({
            "id": "initrd", "name": "embedded initrd", "base": 0,
            # The container is byte-packed with no alignment at all, so a
            # block larger than a byte would draw boundaries that do not exist.
            "block": 1, "capacity": len(initrd_bytes),
            "rows": initrd_regions(entries, len(initrd_bytes), ids),
        })

    programs = choose_programs(entries, wanted)
    layout = user_layout()
    for number, program in enumerate(programs):
        rows = user_regions(program, layout, ids, number)
        # What this program's stored image becomes once loaded. Collected
        # here rather than recomputed from id arithmetic, because a duplicate
        # id gets nudged when it is assigned and the arithmetic would then
        # point at a region belonging to another program.
        program["loaded"] = [row["id"] for row in rows
                             if row["owner"] == program["name"]]
        spaces.append({
            "id": f"user:{program['name']}",
            "name": f"{program['name']} address space",
            "base": 0, "block": PAGE, "capacity": layout["stack_top"],
            "rows": rows,
        })
    if not programs:
        spaces.append({
            "id": "user", "name": "user address space", "base": 0,
            "block": PAGE, "capacity": layout["stack_top"],
            "rows": user_regions(None, layout, ids, 0),
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
            # Which initrd this describes. "embedded" is the container found
            # inside this kernel; anything else describes a container the
            # NEXT build would embed, which is a different claim.
            "initrd_source": initrd["source"] if initrd else "none",
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
        # Which space this one re-describes, or "" when it is a space in its
        # own right. `kernel` and `kernel-modules` are two views of the same
        # bytes; a consumer that assumes spaces are disjoint should draw one
        # of them, and this column is how it knows which.
        "space_overlays": [space.get("overlays", "") for space in spaces],
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
        # Which part of the project a region was built from, for the regions
        # where that is known. Empty for everything outside the module view.
        "region_module": column("module", ""),
        # How many symbols a module run merged, so a consumer can say whether
        # a box is one big function or four hundred small ones. Zero outside
        # the module view.
        "region_symbols": column("symbols", 0),
    }
    document.update(relationships(entries, programs, ids, kernel_rows,
                                  initrd_bytes is not None))
    document.update(rollup(spaces))

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


def rollup(spaces: list[dict]) -> dict:
    """Per-part totals for the kernel image, largest first. Length M.

    The towers show where the bytes are; this says how many, which is the
    other half of "relative sizes" and the half you cannot read off a
    picture. It is a rollup of the module view, not a second measurement.
    """
    totals: dict[str, dict] = {}
    for space in spaces:
        if space["id"] != "kernel-modules":
            continue
        for row in space["rows"]:
            part = row["module"] or "(unattributed)"
            entry = totals.setdefault(part, {"bytes": 0, "runs": 0})
            entry["bytes"] += row["length"]
            entry["runs"] += 1
    order = sorted(totals, key=lambda part: -totals[part]["bytes"])
    total = sum(entry["bytes"] for entry in totals.values()) or 1
    return {
        "module_name": order,
        "module_bytes": [totals[part]["bytes"] for part in order],
        "module_runs": [totals[part]["runs"] for part in order],
        # Share of the kernel image, in basis points: an integer column
        # survives a consumer that only ingests homogeneous numeric arrays,
        # and a percentage rounded to a whole number would show most parts
        # of this kernel as 0.
        "module_share_bp": [round(totals[part]["bytes"] * 10_000 / total)
                            for part in order],
    }


def relationships(entries: list[dict], programs: list[dict], ids: Ids,
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

    for program in programs:
        stored = Ids.BASES["initrd-file"] + program["entry"]["index"]
        for region_id in program.get("loaded", []):
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
    parser.add_argument("--initrd-from", default="embedded",
                        help="where the initrd comes from: 'embedded' (the "
                             "container found inside the kernel itself), "
                             "'inyect' (packed from the injection tree, which "
                             "is what the NEXT build would embed), or a path")
    parser.add_argument("--inyect-dir", type=Path, default=ROOT / "inyect",
                        help="the injection tree --initrd-from inyect packs")
    parser.add_argument("--program", action="append", default=[],
                        metavar="NAME",
                        help="draw this ELF's loaded address space; repeatable "
                             f"(default: every ELF under {EXPERIMENTS})")
    parser.add_argument("--module-depth", type=int, default=1, metavar="N",
                        help="how many path segments below the crate to keep "
                             "when attributing code to a part of the project: "
                             "1 gives mesa_kernel::drivers, 2 goes a level "
                             "finer (default: 1)")
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

    kernel_bytes = args.kernel.read_bytes()
    try:
        kernel_elf = read_elf(kernel_bytes)
    except ElfError as error:
        print(f"memory-layout: {args.kernel}: {error}", file=sys.stderr)
        return 1

    embedded = find_embedded_initrd(kernel_bytes, kernel_elf)
    initrd = None
    if args.initrd_from == "embedded":
        if embedded is None:
            print("memory-layout: no initrd container found inside the "
                  "kernel; emitting the kernel and user spaces only "
                  "(try --initrd-from inyect)", file=sys.stderr)
        else:
            initrd = {**embedded, "source": "embedded"}
    elif args.initrd_from == "inyect":
        if not args.inyect_dir.is_dir():
            print(f"memory-layout: no injection tree at {args.inyect_dir}",
                  file=sys.stderr)
            return 1
        initrd = {"bytes": pack_initrd(args.inyect_dir), "address": 0,
                  "length": 0, "source": "inyect"}
        initrd["length"] = len(initrd["bytes"])
    else:
        path = Path(args.initrd_from)
        if not path.exists():
            print(f"memory-layout: no initrd at {path}", file=sys.stderr)
            return 1
        initrd = {"bytes": path.read_bytes(), "address": 0,
                  "length": path.stat().st_size, "source": str(path)}

    # An initrd that is not the embedded one describes a container this
    # kernel does not carry. That can be exactly what is wanted -- it is how
    # a program added since the last build becomes visible -- but it is a
    # different claim, and a picture that does not say so is misleading.
    if initrd and initrd["source"] != "embedded" and embedded is not None:
        if hashlib.sha256(initrd["bytes"]).digest() != \
                hashlib.sha256(embedded["bytes"]).digest():
            print(f"memory-layout: note: the initrd from "
                  f"{initrd['source']} is NOT the one embedded in "
                  f"{args.kernel.name}; the picture describes what the next "
                  f"build would embed", file=sys.stderr)

    try:
        document = build(kernel_bytes, initrd, args.program, args.revision,
                         args.module_depth, embedded)
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
