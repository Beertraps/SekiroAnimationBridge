"""Havok behavior files (the .hkx members of Sekiro's .behbnd binders) to and from XML.

Sekiro's .hkx files are Havok 2016.2 binary tagfiles (SDK version 20160200). The XML is the
tagfile v3 layout that HkxConverter writes, which modders edit and some mods ship. Both
directions were checked on 2026-10-27 against HkxConverter output for the vanilla c0000 and
c9997 behaviors (62 files whose binaries match the game's): the XML written here is the same
apart from whitespace and enum value comments, and every one of them rebuilt from its XML
reads back as the same object graph. That is file-level (L1) evidence only: on 2026-10-31
Sekiro crashed on load with a c0000.hkx rebuilt by to_hkx from its own XML. The rebuilt file
numbers types and items in another order, hashes other types (THSH), aligns every object to
16 bytes and leaves out the 0x20 flag of array and string items (docs/VERIFICATION.md). To
change a game behavior, patch it in place with havok_tagfile, as animation_slots does.

A binary tagfile is nested sections, each a big-endian u32 (0x40000000 marks a leaf; the low
30 bits are the size with the 8-byte header) and a four-character tag:
TAG0 {SDKV, DATA, TYPE {TPTR, TSTR, TNA1, FSTR, TBDY, THSH, TPAD}, INDX {ITEM, PTCH}}.
The type tables use packed big-endian integers. DATA holds the objects; a pointer, string or
array slot holds an item index, and ITEM gives each item's type, offset and count. PTCH lists
every non-null slot by slot type.

Two things the conversions need are not in the file they read:
- A tagfile keeps only the members of types that have instances. HkxConverter writes the full
  definitions from the game's reflection, so the XML takes 19 Havok core types from
  havok_core_types.json.
- XML has no sizes, alignments or field offsets. They come from a layout database merged from
  the user's own vanilla behavior binders (`Layouts`).

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


def packed(n):
    require(0 <= n < 0x8000000, f"Value {n} does not fit a packed integer")
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return struct.pack(">H", n | 0x8000)
    if n < 0x200000:
        return bytes([0xC0 | (n >> 16)]) + struct.pack(">H", n & 0xFFFF)
    return struct.pack(">I", n | 0xE0000000)


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


# ----- layouts -----


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


# ----- XML to binary -----


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
