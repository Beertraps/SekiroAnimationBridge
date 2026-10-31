"""Havok behavior files (the .hkx members of Sekiro's .behbnd binders) to XML, and XML read back.

Sekiro's .hkx files are Havok 2016.2 binary tagfiles (SDK version 20160200). The XML is the
tagfile v3 layout that HkxConverter writes, which modders edit and some mods ship. to_xml was
checked on 2026-10-27 against HkxConverter output for the vanilla c0000 and c9997 behaviors
(62 files whose binaries match the game's): the XML written here is the same apart from
whitespace and enum value comments. object_graph reads XML back for comparison.

This module writes no binary tagfile. The XML-to-binary writer (to_hkx) is a test helper,
standalone/tests/havok_xml_writer.py, that builds synthetic files: on 2026-10-31 Sekiro
crashed on load with a c0000.hkx that to_hkx rebuilt from its own XML. To change a game
behavior, patch it in place with havok_tagfile, as animation_slots does.

A binary tagfile is nested sections, each a big-endian u32 (0x40000000 marks a leaf; the low
30 bits are the size with the 8-byte header) and a four-character tag:
TAG0 {SDKV, DATA, TYPE {TPTR, TSTR, TNA1, FSTR, TBDY, THSH, TPAD}, INDX {ITEM, PTCH}}.
The type tables use packed big-endian integers. DATA holds the objects; a pointer, string or
array slot holds an item index, and ITEM gives each item's type, offset and count. PTCH lists
every non-null slot by slot type.

A tagfile keeps only the members of types that have instances. HkxConverter writes the full
definitions from the game's reflection, so the XML takes 19 Havok core types from
havok_core_types.json.

Ported with the author's permission from the sekiro-modding plugin (src/sekiro/havok.py on its
branch codex/optional-animation-tools, commit 72b960f). Changed for the bridge: the plugin's io
helpers are defined here, and its binder reader is left out (binder_members.Binder reads them).
"""

import json
import struct
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from xml.sax.saxutils import quoteattr


class ModdingError(ValueError):
    """A file the converter cannot read or write; the message says why."""


def require(condition, message):
    if not condition:
        raise ModdingError(message)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ModdingError(f"Cannot read {path}: {exc}") from exc


SDK = "20160200"
CORE_TYPES = Path(__file__).with_name("havok_core_types.json")
LAYOUT_VERSION = 1

# A type's format: the kind is the low byte. Integers and bools add signedness (0x200) and their
# bit count (>> 10); a fixed-size array (tuple) adds its length (>> 8).
VOID, OPAQUE, BOOL, STRING, INT, FLOAT, POINTER, RECORD, ARRAY = range(9)
TUPLE = 0x28
FLOAT32 = 0x174605
SIGNED = 0x200
# Optional parts of a type body (TBDY), in file order.
HAS_FORMAT, HAS_SUBTYPE, HAS_VERSION, HAS_SIZE, HAS_FLAGS, HAS_FIELDS, HAS_INTERFACES = (
    1,
    2,
    4,
    8,
    0x10,
    0x20,
    0x40,
)
NOT_SERIALIZED = 1  # a field flag: such fields are not in the XML
OBJECT_ITEM = 0x10000000  # an ITEM that is an object, not array or string content
INTEGER_CODES = {8: "b", 16: "h", 32: "i", 64: "q"}
# What reading malformed data raises; the readers turn it into a ModdingError.
DAMAGED = (
    AttributeError,
    IndexError,
    KeyError,
    OverflowError,
    RecursionError,
    TypeError,
    UnicodeDecodeError,
    ValueError,
    struct.error,
)


def is_tagfile(data):
    return data[4:8] == b"TAG0"


def is_xml(data):
    return data.lstrip(b"\xef\xbb\xbf \t\r\n")[:5] == b"<?xml"


class HType:
    """A type from a tagfile's type section. References to other types are HType objects."""

    def __init__(self, name=""):
        self.name = name
        self.params = []  # (name, HType for a 't' parameter or int for a 'v' one)
        self.parent = None
        self.opt = 0
        self.format = self.subtype = self.version = self.size = self.align = self.flags = None
        self.fields = []  # (name, flags, offset, HType)
        self.interfaces = []  # (HType, value)
        self.hash = None
        self._full = None

    def full_name(self):
        if self._full is None:
            parts = (v.full_name() if isinstance(v, HType) else str(v) for _, v in self.params)
            self._full = f"{self.name}< {', '.join(parts)} >" if self.params else self.name
        return self._full

    def inherited(self, attribute):
        t = self
        while t is not None and getattr(t, attribute) is None:
            t = t.parent
        return None if t is None else getattr(t, attribute)

    def resolved_format(self):
        return self.inherited("format") or 0

    def resolved_size(self):
        return self.inherited("size") or 0

    def resolved_align(self):
        return self.inherited("align") or 1

    def all_fields(self):
        return (self.parent.all_fields() if self.parent else []) + self.fields

    def serialized_fields(self):
        return [f for f in self.all_fields() if not f[1] & NOT_SERIALIZED]


class Item:
    __slots__ = ("type", "pointed", "offset", "count")

    def __init__(self, htype, pointed, offset, count):
        self.type, self.pointed, self.offset, self.count = htype, pointed, offset, count


class Packed:
    """Reads the packed big-endian integers of the type tables."""

    def __init__(self, data):
        self.data, self.at = data, 0

    def more(self):
        return self.at < len(self.data)

    def next(self):
        data, at = self.data, self.at
        x = data[at]
        width = 1 if x < 0x80 else 2 if x < 0xC0 else 3 if x < 0xE0 else 4
        require(at + width <= len(data), "Truncated type table")
        self.at = at + width
        value = int.from_bytes(data[at : at + width], "big")
        return value & (0x7F, 0x3FFF, 0x1FFFFF, 0x7FFFFFF)[width - 1]


class TagFile:
    """A parsed binary tagfile: its types, its items and the DATA section."""

    def __init__(self, data):
        require(
            data[:4] != b"\x57\xe0\xe0\x57",
            "A Havok packfile (the older binary format, as in c9996.hkx), not a 2016 tagfile",
        )
        require(is_tagfile(data), "Not a Havok binary tagfile (no TAG0 section)")
        try:
            self.sections = {}
            size = struct.unpack_from(">I", data, 0)[0] & 0x3FFFFFFF
            self._walk(data, 0, min(size, len(data)), "")
            self.sdk = self.sections["TAG0/SDKV"].decode("ascii")
            self.data = self.sections["TAG0/DATA"]
            require(self.sdk == SDK, f"Havok SDK {self.sdk} is not supported; Sekiro's tagfiles are {SDK}")
            self._read_types()
            self._read_items()
        except DAMAGED as error:
            raise ModdingError(
                f"Damaged or unsupported Havok tagfile ({type(error).__name__}: {error})"
            ) from None

    def _walk(self, data, at, end, prefix):
        while at < end:
            head = struct.unpack_from(">I", data, at)[0]
            size = head & 0x3FFFFFFF
            require(8 <= size <= end - at, "Damaged tagfile section")
            key = prefix + data[at + 4 : at + 8].decode("ascii")
            self.sections[key] = data[at + 8 : at + size]
            if head >> 30 == 0:
                self._walk(data, at + 8, at + size, key + "/")
            at += size

    def _read_types(self):
        names = self.sections["TAG0/TYPE/TSTR"].split(b"\0")
        field_names = self.sections["TAG0/TYPE/FSTR"].split(b"\0")
        r = Packed(self.sections["TAG0/TYPE/TNA1"])
        self.types = [None] + [HType() for _ in range(r.next() - 1)]
        params = []
        for t in self.types[1:]:
            t.name = names[r.next()].decode()
            for _ in range(r.next()):
                name = names[r.next()].decode()
                params.append((t, name, r.next()))
        for t, name, value in params:
            t.params.append((name, self.types[value] if name.startswith("t") else value))
        r = Packed(self.sections["TAG0/TYPE/TBDY"])
        while r.more():
            index = r.next()
            if index == 0:
                continue
            t = self.types[index]
            t.parent = self.types[r.next()]
            t.opt = r.next()
            if t.opt & HAS_FORMAT:
                t.format = r.next()
            if t.opt & HAS_SUBTYPE:
                t.subtype = self.types[r.next()]
            if t.opt & HAS_VERSION:
                t.version = r.next()
            if t.opt & HAS_SIZE:
                t.size, t.align = r.next(), r.next()
            if t.opt & HAS_FLAGS:
                t.flags = r.next()
            if t.opt & HAS_FIELDS:
                for _ in range(r.next()):
                    name, flags, offset = field_names[r.next()].decode(), r.next(), r.next()
                    t.fields.append((name, flags, offset, self.types[r.next()]))
            if t.opt & HAS_INTERFACES:
                for _ in range(r.next()):
                    t.interfaces.append((self.types[r.next()], r.next()))
            require(t.opt < 0x80, f"Type {t.name} has attributes (0x80), which are not supported")
        hashes = self.sections.get("TAG0/TYPE/THSH", b"\0")
        r = Packed(hashes)
        for _ in range(r.next()):
            index = r.next()
            self.types[index].hash = struct.unpack_from("<I", hashes, r.at)[0]
            r.at += 4

    def _read_items(self):
        body = self.sections["TAG0/INDX/ITEM"]
        self.items = []
        for at in range(0, len(body) - 11, 12):
            flag, offset, count = struct.unpack_from("<III", body, at)
            index = flag & 0xFFFFFF
            self.items.append(
                Item(self.types[index] if index else None, bool(flag & OBJECT_ITEM), offset, count)
            )
        require(len(self.items) > 1, "The tagfile has no objects")


# ----- XML type view -----


class XType:
    """A type as the XML writes it: names instead of references, and only serialized fields."""

    KEYS = ("name", "parent", "format", "has_subtype", "subtype", "version", "params", "flags", "fields")

    def __init__(
        self,
        name,
        parent=None,
        format=None,
        has_subtype=False,
        subtype=None,
        version=None,
        params=(),
        flags=None,
        fields=None,
    ):
        self.name, self.parent, self.format = name, parent, format
        self.has_subtype, self.subtype, self.version = has_subtype, subtype, version
        self.params = [tuple(p) for p in params]  # ("t", full name) or ("v", int)
        self.flags = flags
        self.fields = None if fields is None else [tuple(f) for f in fields]  # (name, type, flags)

    @classmethod
    def of(cls, t):
        return cls(
            t.name,
            t.parent.full_name() if t.parent else None,
            t.format if t.opt & HAS_FORMAT else None,
            bool(t.opt & HAS_SUBTYPE),
            t.subtype.full_name() if t.subtype else None,
            t.version if t.opt & HAS_VERSION else None,
            [("t", v.full_name()) if n.startswith("t") else ("v", v) for n, v in t.params],
            t.flags if t.opt & HAS_FLAGS else None,
            [(n, ft.full_name(), fl) for n, fl, _, ft in t.fields if not fl & NOT_SERIALIZED]
            if t.opt & HAS_FIELDS
            else None,
        )


def core_types(path=None):
    """The Havok core type definitions binaries strip, by full name (data/havok_core_types.json)."""
    data = read_json(path or CORE_TYPES)
    require(data.get("version") == 1, "Unsupported Havok core type file version")
    return {key: XType(**{k: value[k] for k in XType.KEYS}) for key, value in data["types"].items()}


def format_comment(fmt):
    kind = fmt & 0xFF
    if kind in (INT, BOOL):
        bits, signed = fmt >> 10, bool(fmt & SIGNED)
        if kind == BOOL:
            return f"bool{bits} ({'signed' if signed else 'unsigned'}, LE)"
        return f"{'int' if signed else 'uint'}{bits} (LE)"
    if kind == FLOAT:
        return "float" if fmt == FLOAT32 else "double"
    if kind == TUPLE:
        return f"array({fmt >> 8})"
    names = {VOID: "void", OPAQUE: "incomplete", STRING: "string (ptr)", POINTER: "pointer"}
    names.update({RECORD: "record", ARRAY: "array"})
    return names.get(kind, f"format {fmt}")


# ----- binary to XML -----


class XmlWriter:
    """Writes a tagfile as HkxConverter does: types and objects numbered in breadth-first order of
    discovery, each type written just before the first object that needs it."""

    def __init__(self, tagfile, core):
        self.tf = tagfile
        self.xtypes = {t.full_name(): XType.of(t) for t in tagfile.types[1:]}
        self.xtypes.update(core)
        self.type_ids, self.type_queue, self.emitted = {}, deque(), set()
        self.object_ids, self.object_queue = {}, deque()
        self.out = []

    def tid(self, name):
        if name is None:
            return 0
        if name not in self.type_ids:
            self.type_ids[name] = len(self.type_ids) + 1
            self.type_queue.append(name)
        return self.type_ids[name]

    def number_types(self):
        while self.type_queue:
            name = self.type_queue.popleft()
            require(name in self.xtypes, f"No definition for Havok type {name!r}")
            x = self.xtypes[name]
            if x.parent:
                self.tid(x.parent)
            if x.format is not None and x.format & 0xFF == STRING:
                self.tid("char")
            if x.has_subtype:
                self.tid(x.subtype)
            for kind, value in x.params:
                if kind == "t":
                    self.tid(value)
            for _, field_type, _ in x.fields or []:
                self.tid(field_type)

    def emit_types(self):
        names = {number: name for name, number in self.type_ids.items()}
        pending = sorted(n for n in names if n not in self.emitted)
        # HkxConverter writes hkReferencedObject after T*< hkReferencedObject >.
        for i, number in enumerate(pending[:-1]):
            if names[number] == "hkReferencedObject" and names[pending[i + 1]] == "T*< hkReferencedObject >":
                pending[i], pending[i + 1] = pending[i + 1], pending[i]
                break
        for number in pending:
            self.write_type(number, self.xtypes[names[number]])
            self.emitted.add(number)

    def write_type(self, number, x):
        o = self.out
        o.append(f'  <type id="type{number}">')
        o.append(f"    <name value={quoteattr(x.name)}/>")
        if x.parent:
            o.append(f'    <parent id="type{self.tid(x.parent)}"/> <!-- {x.parent} -->')
        if x.format is not None:
            o.append(f'    <format value="{x.format}"/> <!-- {format_comment(x.format)} -->')
        if x.has_subtype:
            o.append(f'    <subtype id="type{self.tid(x.subtype)}"/> <!-- {x.subtype or "null"} -->')
        if x.version is not None:
            o.append(f'    <version value="{x.version}"/>')
        if x.params:
            o.append(f'    <parameters count="{len(x.params)}">')
            for kind, value in x.params:
                if kind == "t":
                    o.append(f'      <typeparam id="type{self.tid(value)}"/> <!-- {value} -->')
                else:
                    o.append(f'      <valueparam value="{value}"/>')
            o.append("    </parameters>")
        if x.flags is not None:
            o.append(f'    <flags value="{x.flags}"/>')
        if x.fields is not None:
            o.append(f'    <fields count="{len(x.fields)}">')
            for name, field_type, flags in x.fields:
                o.append(
                    f'      <field name="{name}" typeid="type{self.tid(field_type)}" flags="{flags}"/>'
                    f" <!-- {field_type} -->"
                )
            o.append("    </fields>")
        o.append("  </type>")

    def oid(self, item):
        if item == 0:
            return 0
        if item not in self.object_ids:
            self.object_ids[item] = len(self.object_ids) + 1
            self.object_queue.append(item)
        return self.object_ids[item]

    def scalar(self, t, at):
        """The inline element for a value, or None for a record or array."""
        fmt = t.resolved_format()
        kind, data = fmt & 0xFF, self.tf.data
        if kind in (INT, BOOL):
            code = INTEGER_CODES[fmt >> 10]
            value = struct.unpack_from("<" + (code if fmt & SIGNED else code.upper()), data, at)[0]
            if kind == BOOL:
                return f'<bool value="{"true" if value else "false"}"/>'
            return f'<integer value="{value}"/>'
        if kind == FLOAT:
            value = struct.unpack_from("<f" if t.resolved_size() == 4 else "<d", data, at)[0]
            bits = struct.unpack("<Q", struct.pack("<d", value))[0]
            # dec is C's %g (6 significant digits); hex holds the exact value.
            return f'<real dec="{"%g" % value}" hex="#{bits:x}"/>'
        if kind == STRING:
            index = struct.unpack_from("<I", data, at)[0]
            if index == 0:
                return "<string/>"
            item = self.tf.items[index]
            text = data[item.offset : item.offset + item.count - 1].decode("utf-8")
            return f"<string value={quoteattr(text)}/>"
        if kind == POINTER:
            return f'<pointer id="object{self.oid(struct.unpack_from("<I", data, at)[0])}"/>'
        return None

    def block(self, t, at, depth):
        fmt = t.resolved_format()
        kind, pad, o = fmt & 0xFF, "  " * depth, self.out
        if kind == RECORD:
            o.append(f"{pad}<record> <!-- {t.full_name()} -->")
            for name, _, offset, field_type in t.serialized_fields():
                self.field(name, field_type, at + offset, depth + 1)
            o.append(f"{pad}</record>")
            return
        sub = t.inherited("subtype")
        if kind == ARRAY:
            index = struct.unpack_from("<I", self.tf.data, at)[0]
            item = self.tf.items[index] if index else None
            count, base, element = (item.count, item.offset, item.type) if item else (0, 0, sub)
        else:
            require(kind == TUPLE, f"No XML form for Havok type {t.full_name()} (format {fmt})")
            count, base, element = fmt >> 8, at, sub
        # The declared element type: some shipped tagfiles give an array a wrong subtype.
        declared = self.xtypes.get(t.full_name())
        if declared is not None and declared.has_subtype:
            sub_name = declared.subtype
        else:
            sub_name = sub.full_name() if sub else None
        element_id = self.tid(sub_name)
        o.append(f'{pad}<array count="{count}" elementtypeid="type{element_id}"> <!-- ArrayOf {sub_name} -->')
        for n in range(count):
            self.value(element, base + n * element.resolved_size(), depth + 1)
        o.append(f"{pad}</array>")

    def value(self, t, at, depth):
        inline = self.scalar(t, at)
        if inline is None:
            self.block(t, at, depth)
        else:
            self.out.append("  " * depth + inline)

    def field(self, name, t, at, depth):
        pad = "  " * depth
        inline = self.scalar(t, at)
        if inline is not None:
            self.out.append(f'{pad}<field name="{name}">{inline}</field>')
            return
        self.out.append(f'{pad}<field name="{name}">')
        self.block(t, at, depth + 1)
        self.out.append(f"{pad}</field>")

    def write(self):
        self.out += ['<?xml version="1.0" encoding="utf-8"?>', '<hktagfile version="3">']
        self.oid(1)
        while self.object_queue:
            index = self.object_queue.popleft()
            item = self.tf.items[index]
            require(item.type is not None, f"Item {index} has no type")
            self.tid(item.type.full_name())
            self.number_types()
            start = len(self.out)
            name, number = item.type.full_name(), self.object_ids[index]
            self.out.append(f'  <object id="object{number}" typeid="type{self.tid(name)}"> <!-- {name} -->')
            self.block(item.type, item.offset, 2)
            self.out.append("  </object>")
            # The types an object needs come before it.
            self.number_types()
            body = self.out[start:]
            del self.out[start:]
            self.emit_types()
            self.out += body
        self.out.append("</hktagfile>")
        return "\n".join(self.out)  # without a final line break, as HkxConverter writes it


def to_xml(data, core=None):
    """The XML tagfile text of a binary tagfile."""
    tagfile = TagFile(data)
    try:
        return XmlWriter(tagfile, core_types() if core is None else core).write()
    except DAMAGED as error:
        raise ModdingError(f"Damaged Havok tagfile data ({type(error).__name__}: {error})") from None


# ----- XML tagfiles -----


def float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def real_value(element):
    """A real's value and whether its dec and hex disagree.

    hex holds the exact bits and dec only 6 significant digits, so hex is used while dec names
    the same float32. When they differ, an edit changed dec and left hex stale, and dec is used:
    Malevolence's XML has hundreds of clips with playbackSpeed dec="1.0" hex="#0", and that mod
    plays (inferred; the game reading such XML is not tested here).
    """
    dec, text = element.get("dec"), element.get("hex")
    if not text:
        return float(dec), False
    require(text.startswith("#"), f"Malformed real hex {text!r}")
    exact = struct.unpack("<d", struct.pack("<Q", int(text[1:], 16)))[0]
    if dec is None or "%g" % float32(float(dec)) == "%g" % float32(exact):
        return exact, False
    return float(dec), True


class XmlTagfile:
    """The type names and objects of an XML tagfile."""

    def __init__(self, text):
        require("<!DOCTYPE" not in text, "XML tagfiles never declare a DOCTYPE; refusing this one")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as error:
            raise ModdingError(f"Not well-formed XML: {error}") from None
        require(
            root.tag == "hktagfile" and root.get("version") == "3",
            'Not a Havok XML tagfile (<hktagfile version="3">)',
        )
        raw = {e.get("id"): e for e in root.findall("type")}
        self.names = {}
        visiting = set()

        def full(tid):
            if tid in (None, "type0"):
                return "None"
            if tid not in self.names:
                require(tid in raw and tid not in visiting, f"Unknown or circular type reference {tid!r}")
                visiting.add(tid)
                e = raw[tid]
                name = e.find("name").get("value")
                params = e.find("parameters")
                if params is not None:
                    parts = [full(p.get("id")) if p.tag == "typeparam" else p.get("value") for p in params]
                    name = f"{name}< {', '.join(parts)} >"
                self.names[tid] = name
                visiting.discard(tid)
            return self.names[tid]

        self.objects, self.order = {}, []
        for e in root.findall("object"):
            oid = e.get("id")
            require(len(e) == 1 and e[0].tag == "record", f"{oid} must hold one record")
            require(oid not in self.objects, f"Duplicate object id {oid}")
            self.objects[oid] = (full(e.get("typeid")), e[0])
            self.order.append(oid)
        require(self.order, "The XML tagfile has no objects")


# ----- readback -----


def object_graph(text):
    """The objects the root of an XML tagfile reaches, in breadth-first order, as comparable
    values: pointers become positions in that order, reals their float32 bits, records sorted
    by field name. Element and type ids, comments and whitespace do not count."""
    doc = XmlTagfile(text)
    numbers, queue = {}, deque()

    def number(oid):
        if oid == "object0":
            return 0
        require(oid in doc.objects, f"Pointer to missing object {oid}")
        if oid not in numbers:
            numbers[oid] = len(numbers) + 1
            queue.append(oid)
        return numbers[oid]

    def value(e):
        if e.tag == "integer":
            return int(e.get("value"))
        if e.tag == "bool":
            return e.get("value") == "true"
        if e.tag == "real":
            return ("real", struct.pack("<f", real_value(e)[0]))
        if e.tag == "string":
            return ("string", e.get("value"))
        if e.tag == "pointer":
            return ("pointer", number(e.get("id")))
        if e.tag == "record":
            return ("record", tuple(sorted((f.get("name"), value(f[0])) for f in e.findall("field"))))
        require(e.tag == "array", f"Unknown XML value element <{e.tag}>")
        return ("array", tuple(value(x) for x in e))

    graph = []
    number(doc.order[0])
    try:
        while queue:
            name, record = doc.objects[queue.popleft()]
            graph.append((name, value(record)))
    except DAMAGED as error:
        raise ModdingError(f"Unreadable XML value ({type(error).__name__}: {error})") from None
    return graph


def same(a, b):
    """Equal values; a negative integer also equals its unsigned form, which readback gives."""
    if isinstance(a, int) and isinstance(b, int):
        return a == b or (a < 0 <= b and any(a % (1 << bits) == b for bits in INTEGER_CODES))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def graph_difference(expected, found):
    """None when two object graphs are the same, else where they first differ."""
    if len(expected) != len(found):
        return f"{len(expected)} reachable objects expected, {len(found)} read back"
    for n, (a, b) in enumerate(zip(expected, found), 1):
        if not same(a, b):
            return f"object {n} in breadth-first order ({a[0]}) differs"
    return None
