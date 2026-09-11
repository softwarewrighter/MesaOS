#!/usr/bin/env python3
"""Check a memory-layout artifact against the shared interchange contract.

The contract is `sw-ml-study.system-layout` version 1, pinned by
`../../sw-ml-study/sw-mlpl/docs/storage-layout-viz.md`. Three repositories
consume it -- sw-mlpl turns it into geometry, demo-extensions renders and
picks it -- and a producer that quietly breaks an invariant costs all three a
debugging session in the wrong repository. So the checks below are the ones a
consumer would otherwise discover the hard way:

    columnar    every region_* array is the same length; every space_* array
                is the same length
    keyed       every region_space names a declared space
    stable      region ids are unique, which is what picking depends on
    dense       regions in a space tile it in address order with no gaps and
                no overlaps, and none runs past the space's capacity
    closed      every relationship endpoint is a region id that exists

Both serializations are accepted and told apart by their own shape: the
columnar form sw-mlpl reads has a `region_id` column, and the row form
demo-extensions' bounded Rust parser reads has a `regions` array. The row
schema additionally rejects an empty text field, so an absent owner has to be
spelled rather than left blank, and that is checked too.

Exit status is 0 when the artifact is fit to hand to a consumer and 1 when it
is not, so this can gate the handoff.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "sw-ml-study.system-layout"
VERSION = 1

REGION_REQUIRED = ["region_id", "region_space", "region_kind", "region_name",
                   "region_owner", "region_start", "region_length"]
SPACE_REQUIRED = ["spaces", "space_name", "space_block", "space_capacity"]


def check_rows(document: dict) -> list[str]:
    """The same invariants for the row serialization demo-extensions' bounded
    parser reads. The document is the same model either way, so the checks are
    the same questions asked of a different shape -- with one addition the row
    schema imposes and the columnar one does not: every text field must be
    non-empty, so an absent owner has to be spelled rather than left blank.
    """
    problems: list[str] = []

    def fail(message: str) -> None:
        problems.append(message)

    if document.get("schema") != SCHEMA:
        fail(f"schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    if document.get("version") != VERSION:
        fail(f"version is {document.get('version')!r}, expected {VERSION}")

    provenance = document.get("provenance", {})
    for field in ("producer", "producer_revision", "generated_at",
                  "source_description"):
        if not provenance.get(field):
            fail(f"provenance.{field} is missing or empty")
    if str(provenance.get("producer_revision", "")).endswith("-dirty"):
        fail("provenance.producer_revision is dirty: the artifact was "
             "generated from uncommitted sources and cannot be pinned")

    spaces = {}
    for space in document.get("spaces", []):
        if space["id"] in spaces:
            fail(f"duplicate space id {space['id']!r}")
        spaces[space["id"]] = space
        block = space.get("block_size")
        if block and space["extent"] % block != 0:
            fail(f"space {space['id']!r}: extent {space['extent']} is not a "
                 f"multiple of its block size {block}")

    seen = set()
    for region in document.get("regions", []):
        if region["id"] in seen:
            fail(f"duplicate region id {region['id']!r}")
        seen.add(region["id"])
        for field in ("id", "purpose", "owner", "location", "state"):
            if not str(region.get(field, "")).strip():
                fail(f"region {region.get('id')!r}: {field} is empty, which "
                     f"the row schema rejects")
        if region["space_id"] not in spaces:
            fail(f"region {region['id']!r} names unknown space "
                 f"{region['space_id']!r}")
            continue
        extent = spaces[region["space_id"]]["extent"]
        if region["extent"] <= 0:
            fail(f"region {region['id']!r} has extent {region['extent']}")
        if region["address"] + region["extent"] > extent:
            fail(f"region {region['id']!r} ends past its space's extent")

    for space_id, space in spaces.items():
        rows = sorted((r for r in document.get("regions", [])
                       if r["space_id"] == space_id),
                      key=lambda r: r["address"])
        cursor = 0
        for region in rows:
            if region["address"] > cursor:
                fail(f"space {space_id!r}: {region['address'] - cursor} "
                     f"unaccounted bytes before region {region['id']!r}")
            elif region["address"] < cursor:
                fail(f"space {space_id!r}: region {region['id']!r} overlaps "
                     f"the region ending at {cursor}")
            cursor = max(cursor, region["address"] + region["extent"])
        if cursor != space["extent"]:
            fail(f"space {space_id!r}: regions cover {cursor} of its "
                 f"{space['extent']} bytes")

    edge_ids = set()
    for edge in document.get("relationships", []):
        if edge["id"] in edge_ids:
            fail(f"duplicate relationship id {edge['id']!r}")
        edge_ids.add(edge["id"])
        if edge["from_region_id"] == edge["to_region_id"]:
            fail(f"relationship {edge['id']!r} points at itself")
        for endpoint in (edge["from_region_id"], edge["to_region_id"]):
            if endpoint not in seen:
                fail(f"relationship {edge['id']!r} names region {endpoint!r}, "
                     f"which does not exist")

    return problems


def check(document: dict) -> list[str]:
    """Every problem, not the first one: a producer fixing four broken
    columns should see four lines, not run this four times."""
    problems: list[str] = []

    def fail(message: str) -> None:
        problems.append(message)

    if document.get("schema") != SCHEMA:
        fail(f"schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    if document.get("version") != VERSION:
        fail(f"version is {document.get('version')!r}, expected {VERSION}")

    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        fail("provenance is missing")
    else:
        for field in ("producer", "revision"):
            if not provenance.get(field):
                fail(f"provenance.{field} is missing or empty")
        if str(provenance.get("revision", "")).endswith("-dirty"):
            fail("provenance.revision is dirty: the artifact was generated "
                 "from uncommitted sources and cannot be pinned by a consumer")

    missing = [name for name in REGION_REQUIRED + SPACE_REQUIRED
               if name not in document]
    if missing:
        fail(f"missing required columns: {', '.join(missing)}")
        return problems

    # Columnar: index-aligned arrays are the whole reason this shape was
    # chosen, so a ragged one is not a cosmetic problem.
    n = len(document["region_id"])
    for name in [c for c in document if c.startswith("region_")]:
        if len(document[name]) != n:
            fail(f"{name} has {len(document[name])} entries, expected {n}")
    s = len(document["spaces"])
    for name in [c for c in document if c.startswith("space_")]:
        if len(document[name]) != s:
            fail(f"{name} has {len(document[name])} entries, expected {s}")

    ids = document["region_id"]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        fail(f"region_id is not unique: {sorted(duplicates)}")

    spaces = document["spaces"]
    for space in set(document["region_space"]):
        if space not in spaces:
            fail(f"region_space {space!r} is not a declared space")

    # Dense: the regions of a space must tile it. A gap means the picture has
    # a hole the system does not have; an overlap means two boxes claim the
    # same bytes and picking one is ambiguous.
    for index, space in enumerate(spaces):
        rows = sorted(
            ((start, length, name) for start, length, name, where in zip(
                document["region_start"], document["region_length"],
                document["region_name"], document["region_space"])
             if where == space),
            key=lambda row: row[0],
        )
        if not rows:
            fail(f"space {space!r} has no regions")
            continue
        if rows[0][0] != 0:
            fail(f"space {space!r} starts at {rows[0][0]}, expected 0")
        cursor = 0
        for start, length, name in rows:
            if length <= 0:
                fail(f"space {space!r}: region {name!r} has length {length}")
            if start < cursor:
                fail(f"space {space!r}: region {name!r} at {start} overlaps "
                     f"the region ending at {cursor}")
            elif start > cursor:
                fail(f"space {space!r}: {start - cursor} unaccounted bytes "
                     f"before region {name!r}")
            cursor = max(cursor, start + length)
        capacity = document["space_capacity"][index]
        if cursor > capacity:
            fail(f"space {space!r}: regions end at {cursor}, past its "
                 f"capacity of {capacity}")
        elif cursor < capacity:
            fail(f"space {space!r}: {capacity - cursor} bytes of its capacity "
                 f"are unaccounted for; name them (free, padding) rather than "
                 f"leaving a hole in the picture")

    # Closed: an edge to a region that does not exist highlights nothing.
    edges = document.get("rel_kind", [])
    for name in ("rel_from", "rel_to"):
        if len(document.get(name, [])) != len(edges):
            fail(f"{name} has {len(document.get(name, []))} entries, "
                 f"expected {len(edges)}")
    known = set(ids)
    for kind, source, target in zip(edges, document.get("rel_from", []),
                                    document.get("rel_to", [])):
        for endpoint in (source, target):
            if endpoint not in known:
                fail(f"relationship {kind!r} names region id {endpoint}, "
                     f"which does not exist")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifact", type=Path, nargs="?",
                        default=ROOT / "build" / "memory-layout.json")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="do not fail on a dirty provenance revision "
                             "(for checking a work-in-progress artifact)")
    args = parser.parse_args()

    if not args.artifact.exists():
        print(f"memory-layout-check: no artifact at {args.artifact}; "
              f"run scripts/memory-layout.py first", file=sys.stderr)
        return 1

    raw = args.artifact.read_bytes()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        print(f"memory-layout-check: {args.artifact} is not JSON: {error}",
              file=sys.stderr)
        return 1

    # Which serialization this is answers itself: the columnar form has a
    # `region_id` column, the row form a `regions` array.
    rows = "regions" in document and "region_id" not in document
    problems = (check_rows if rows else check)(document)
    if args.allow_dirty:
        problems = [p for p in problems if "is dirty" not in p]

    if problems:
        print(f"memory-layout-check: {args.artifact} FAILS the contract")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    shape = "row" if rows else "columnar"
    count = len(document["regions"]) if rows else len(document["region_id"])
    edges = len(document["relationships"] if rows else document.get("rel_kind", []))
    provenance = document["provenance"]
    print(f"memory-layout-check: {args.artifact} conforms to {SCHEMA} "
          f"v{VERSION} ({shape})")
    print(f"  regions: {count} across {len(document['spaces'])} spaces, "
          f"{edges} edges")
    print(f"  producer: {provenance['producer']} @ "
          f"{provenance.get('revision') or provenance.get('producer_revision')}")
    print(f"  sha256:   {hashlib.sha256(raw).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
