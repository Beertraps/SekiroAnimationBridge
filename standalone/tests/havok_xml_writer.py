"""XML tagfiles to Havok 2016 binary tagfiles, for tests only: it builds the synthetic behavior files they read and
patch. Never use it on a game file. On 2026-10-31 Sekiro crashed on load with a c0000.hkx rebuilt by to_hkx from its
own XML, with nothing changed: the rebuilt file numbers types and items in another order, hashes other types (THSH),
aligns every object to 16 bytes and leaves out the 0x20 flag of array and string items (docs/VERIFICATION.md). The
bridge changes game behaviors in place with havok_tagfile.

XML has no sizes, alignments or field offsets. They come from a layout database (`Layouts`), merged from tagfiles or
built by a test. Moved here from havok_xml, which keeps the reader, to_xml and the readback.
"""

import struct
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from havok_xml import (ARRAY, BOOL, DAMAGED, FLOAT, HAS_FIELDS, HAS_FLAGS, HAS_FORMAT, HAS_INTERFACES, HAS_SIZE,
                       HAS_SUBTYPE, HAS_VERSION, INT, INTEGER_CODES, OBJECT_ITEM, POINTER, RECORD, SDK, SIGNED,
                       STRING, TUPLE, HType, ModdingError, XmlTagfile, real_value, require)

ELEMENT = {
    BOOL: "bool",
    INT: "integer",
    FLOAT: "real",
    STRING: "string",
    POINTER: "pointer",
    RECORD: "record",
    ARRAY: "array",
    TUPLE: "array",
}


def packed(n):
    require(0 <= n < 0x8000000, f"Value {n} does not fit a packed integer")
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return struct.pack(">H", n | 0x8000)
    if n < 0x200000:
        return bytes([0xC0 | (n >> 16)]) + struct.pack(">H", n & 0xFFFF)
    return struct.pack(">I", n | 0xE0000000)


class Layouts:
    """Binary type definitions (sizes, alignments, field offsets) by full name, merged over
    tagfiles. A type keeps the definition with the most fields: files strip the members of
    types they have no instances of."""

    def __init__(self):
        self.types = {}
        self.conflicts = set()

    @classmethod
    def merged(cls, tagfiles):
        """Layouts merged over tagfiles, with every reference resolved to the merged types."""
        layouts = cls()
        for tagfile in tagfiles:
            layouts.add(tagfile)
        result = cls.from_json(layouts.to_json())
        result.conflicts = layouts.conflicts
        return result

    def add(self, tagfile):
        for t in tagfile.types[1:]:
            name = t.full_name()
            have = self.types.get(name)
            if have is None or len(t.fields) > len(have.fields) or (have.size is None and t.size is not None):
                if have is not None and None not in (have.size, t.size) and have.size != t.size:
                    self.conflicts.add(name)
                self.types[name] = t

    def get(self, name):
        require(
            name in self.types,
            f"No binary layout for Havok type {name!r}: no vanilla behavior file uses it",
        )
        return self.types[name]

    def to_json(self):
        def ref(t):
            return None if t is None else t.full_name()

        return {
            name: {
                "name": t.name,
                "params": [[n, ref(v) if n.startswith("t") else v] for n, v in t.params],
                "parent": ref(t.parent),
                "opt": t.opt,
                "format": t.format,
                "subtype": ref(t.subtype),
                "version": t.version,
                "size": t.size,
                "align": t.align,
                "flags": t.flags,
                "fields": [[n, fl, off, ref(ft)] for n, fl, off, ft in t.fields],
                "interfaces": [[ref(it), value] for it, value in t.interfaces],
                "hash": t.hash,
            }
            for name, t in sorted(self.types.items())
        }

    @classmethod
    def from_json(cls, value):
        layouts = cls()
        for name, entry in value.items():
            t = HType(entry["name"])
            t._full = name
            for key in ("opt", "format", "version", "size", "align", "flags", "hash"):
                setattr(t, key, entry[key])
            layouts.types[name] = t
        types = layouts.types

        def ref(name):
            require(name is None or name in types, f"Layout database refers to unknown type {name!r}")
            return None if name is None else types[name]

        for name, entry in value.items():
            t = types[name]
            t.params = [(n, ref(v) if n.startswith("t") else v) for n, v in entry["params"]]
            t.parent, t.subtype = ref(entry["parent"]), ref(entry["subtype"])
            t.fields = [(n, fl, off, ref(ft)) for n, fl, off, ft in entry["fields"]]
            t.interfaces = [(ref(it), v) for it, v in entry["interfaces"]]
        return layouts


class TagWriter:
    """Writes an XML tagfile's objects reachable from its first object (the root) as a binary
    tagfile, with the layouts of the layout database."""

    def __init__(self, layouts, doc):
        self.layouts, self.doc = layouts, doc
        self.type_index, self.type_list = {}, [None]
        self.items = [(0, False, 0, 0)]  # (type index, object, offset, count)
        self.object_items, self.pending = {}, deque()
        self.data = bytearray()
        self.patches, self.fixups = {}, []
        self.where = None
        self.mismatches = []

    def tindex(self, t):
        if t is None:
            return 0
        name = t.full_name()
        if name not in self.type_index:
            t = self.layouts.types.get(name, t)
            self.type_index[name] = len(self.type_list)
            self.type_list.append(t)
            for related in (t.parent, t.subtype, *(v for n, v in t.params if n.startswith("t"))):
                self.tindex(related)
            for _, _, _, field_type in t.fields:
                self.tindex(field_type)
            for interface, _ in t.interfaces:
                self.tindex(interface)
        return self.type_index[name]

    def alloc(self, t, count, pointed, align=1):
        align = max(align, t.resolved_align())
        self.data += b"\0" * (-len(self.data) % align)
        at = len(self.data)
        self.data += b"\0" * (t.resolved_size() * count)
        self.items.append((self.tindex(t), pointed, at, count))
        return len(self.items) - 1, at

    def slot(self, t, at, item):
        struct.pack_into("<I", self.data, at, item)
        if item:
            self.patches.setdefault(self.tindex(t), []).append(at)

    def object_item(self, oid):
        require(oid in self.doc.objects, f"{self.where} points to missing object {oid}")
        if oid not in self.object_items:
            self.object_items[oid] = None  # allocated when its turn comes
            self.pending.append(oid)
        return oid

    def write_value(self, t, at, e, deferred):
        fmt = t.resolved_format()
        kind = fmt & 0xFF
        expected = ELEMENT.get(kind)
        require(expected is not None, f"{self.where}: cannot write Havok type {t.full_name()} (format {fmt})")
        require(e.tag == expected, f"{self.where}: {t.full_name()} needs <{expected}>, not <{e.tag}>")
        if kind in (INT, BOOL):
            bits = fmt >> 10
            if kind == BOOL:
                require(e.get("value") in ("true", "false"), f"{self.where}: bool must be true or false")
                value = int(e.get("value") == "true")
            else:
                value = int(e.get("value"))
            code = INTEGER_CODES[bits]
            if not fmt & SIGNED:
                code = code.upper()
                if value < 0:
                    value &= (1 << bits) - 1
            struct.pack_into("<" + code, self.data, at, value)
        elif kind == FLOAT:
            value, disagree = real_value(e)
            if disagree:
                self.mismatches.append(
                    {"kind": "real dec/hex", "object": self.where, "dec": e.get("dec"), "hex": e.get("hex")}
                )
            struct.pack_into("<f" if t.resolved_size() == 4 else "<d", self.data, at, value)
        elif kind == STRING:
            if e.get("value") is not None:
                deferred.append(("string", t, at, e.get("value")))
        elif kind == POINTER:
            if e.get("id") != "object0":
                deferred.append(("pointer", t, at, self.object_item(e.get("id"))))
        elif kind == RECORD:
            values = {f.get("name"): f for f in e.findall("field")}
            fields = t.serialized_fields()
            names = [name for name, _, _, _ in fields]
            require(
                sorted(values) == sorted(names),
                f"{self.where}: {t.full_name()} fields {sorted(values)} do not match its layout {names}",
            )
            for name, _, offset, field_type in fields:
                element = values[name]
                require(len(element) == 1, f"{self.where}: field {name} must hold one value")
                self.write_value(field_type, at + offset, element[0], deferred)
        elif kind == ARRAY:
            elements = list(e)
            if e.get("count", str(len(elements))) != str(len(elements)):
                self.mismatches.append(
                    {
                        "kind": "array count",
                        "object": self.where,
                        "count": e.get("count"),
                        "elements": len(elements),
                    }
                )
            if elements:
                deferred.append(("array", t, at, elements))
        else:
            sub = t.inherited("subtype")
            require(len(e) == fmt >> 8, f"{self.where}: {t.full_name()} needs {fmt >> 8} elements")
            for n, element in enumerate(e):
                self.write_value(sub, at + n * sub.resolved_size(), element, deferred)

    def flush(self, deferred):
        """Write strings and arrays right after their owner, depth first, as the game's files do."""
        for kind, t, at, payload in deferred:
            if kind == "string":
                raw = payload.encode("utf-8") + b"\0"
                item, start = self.alloc(self.layouts.get("char"), len(raw), False)
                self.data[start : start + len(raw)] = raw
                self.slot(t, at, item)
            elif kind == "pointer":
                self.fixups.append((t, at, payload))
            else:
                sub = self.layouts.types.get(t.inherited("subtype").full_name(), t.inherited("subtype"))
                item, start = self.alloc(sub, len(payload), False)
                self.slot(t, at, item)
                inner = []
                for n, element in enumerate(payload):
                    self.write_value(sub, start + n * sub.resolved_size(), element, inner)
                self.flush(inner)

    def build(self):
        self.object_item(self.doc.order[0])
        while self.pending:
            oid = self.where = self.pending.popleft()
            name, record = self.doc.objects[oid]
            item, at = self.alloc(self.layouts.get(name), 1, True, align=16)
            self.object_items[oid] = item
            deferred = []
            self.write_value(self.layouts.get(name), at, record, deferred)
            self.flush(deferred)
        for t, at, oid in self.fixups:
            self.slot(t, at, self.object_items[oid])
        self.data += b"\0" * (-len(self.data) % 16)
        return self.serialize()

    def serialize(self):
        type_names, field_names = {}, {}

        def string(table, text):
            return table.setdefault(text, len(table))

        tna1 = bytearray(packed(len(self.type_list)))
        for t in self.type_list[1:]:
            tna1 += packed(string(type_names, t.name)) + packed(len(t.params))
            for n, v in t.params:
                tna1 += packed(string(type_names, n)) + packed(self.tindex(v) if n.startswith("t") else v)
        tbdy = bytearray()
        for index, t in enumerate(self.type_list[1:], 1):
            tbdy += packed(index) + packed(self.tindex(t.parent)) + packed(t.opt)
            if t.opt & HAS_FORMAT:
                tbdy += packed(t.format)
            if t.opt & HAS_SUBTYPE:
                tbdy += packed(self.tindex(t.subtype))
            if t.opt & HAS_VERSION:
                tbdy += packed(t.version)
            if t.opt & HAS_SIZE:
                tbdy += packed(t.size) + packed(t.align)
            if t.opt & HAS_FLAGS:
                tbdy += packed(t.flags)
            if t.opt & HAS_FIELDS:
                tbdy += packed(len(t.fields))
                for n, flags, offset, field_type in t.fields:
                    tbdy += packed(string(field_names, n)) + packed(flags) + packed(offset)
                    tbdy += packed(self.tindex(field_type))
            if t.opt & HAS_INTERFACES:
                tbdy += packed(len(t.interfaces))
                for interface, value in t.interfaces:
                    tbdy += packed(self.tindex(interface)) + packed(value)
        hashed = [(i, t.hash) for i, t in enumerate(self.type_list[1:], 1) if t.hash is not None]
        thsh = bytearray(packed(len(hashed)))
        for index, value in hashed:
            thsh += packed(index) + struct.pack("<I", value)
        item = b"".join(
            struct.pack("<III", ti | (OBJECT_ITEM if obj else 0), at, n) for ti, obj, at, n in self.items
        )
        ptch = bytearray()
        for index in sorted(self.patches):
            offsets = sorted(self.patches[index])
            ptch += struct.pack(f"<II{len(offsets)}I", index, len(offsets), *offsets)

        def strings(table):
            return padded(b"".join(text.encode() + b"\0" for text in table))

        types = (
            section("TPTR", b"\0" * (8 * len(self.type_list)))
            + section("TSTR", strings(type_names))
            + section("TNA1", padded(tna1))
            + section("FSTR", strings(field_names))
            + section("TBDY", padded(tbdy))
            + section("THSH", padded(thsh))
            + section("TPAD", b"")
        )
        body = (
            section("SDKV", SDK.encode())
            + section("DATA", bytes(self.data))
            + section("TYPE", types, leaf=False)
            + section("INDX", section("ITEM", item) + section("PTCH", bytes(ptch)), leaf=False)
        )
        return section("TAG0", body, leaf=False)


def section(tag, body, leaf=True):
    return struct.pack(">I", (8 + len(body)) | (0x40000000 if leaf else 0)) + tag.encode() + body


def padded(data):
    return bytes(data) + b"\0" * (-len(data) % 4)


def to_hkx(text, layouts):
    """A binary tagfile from XML text: (bytes, report). Objects the root does not reach are left
    out, as HkxConverter does. The report counts them, reals whose dec and hex differ (dec is
    written) and arrays whose count differs from their elements (the elements are written)."""
    doc = XmlTagfile(text)
    writer = TagWriter(layouts, doc)
    try:
        data = writer.build()
    except DAMAGED as error:
        raise ModdingError(f"{writer.where}: unreadable value ({type(error).__name__}: {error})") from None
    kinds = [m["kind"] for m in writer.mismatches]
    return data, {
        "objects": len(writer.object_items),
        "unreachable_objects": len(doc.objects) - len(writer.object_items),
        "real_dec_hex_mismatches": kinds.count("real dec/hex"),
        "array_count_mismatches": kinds.count("array count"),
        "mismatch_examples": writer.mismatches[:10],
    }
