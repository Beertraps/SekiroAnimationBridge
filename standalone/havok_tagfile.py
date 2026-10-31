"""Read and patch Havok 2016 binary tagfiles (TAG0) in place.

A new character copies the template's behavior and skeleton files and changes only bone numbers, per-bone lists and
names. This module finds those values by walking the file's own type information and changes their bytes; every other
byte stays as the template has it. Lists that grow are written as new data at the end of the DATA section, and the
item that holds the list points there instead. Pointers inside new data are added to the PTCH section, which the game's
loader uses to turn item numbers into addresses.

The section, type and item layout follows Havoc's HkBinaryTagfileReader and HkBinaryTypeReader (MIT). Havoc reads an
array of pointers or strings with a stride of 4 bytes; Sekiro's files use the type's byte size, 8, so this reader
uses the byte size throughout.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

# Type flags and value formats.
HAS_FORMAT, HAS_SUBTYPE, HAS_VERSION, HAS_SIZE, HAS_UNKNOWN, HAS_FIELDS, HAS_INTERFACES = 1, 2, 4, 8, 16, 32, 64
VOID, OPAQUE, BOOL, STRING, INT, FLOAT, PTR, CLASS, ARRAY = range(9)


def packed_int(data, at):
    """Havok's variable-length integer. Returns the value and the offset after it."""
    first = data[at]
    if first & 0x80 == 0:
        return first, at + 1
    kind = first >> 3
    if 0x10 <= kind <= 0x17:
        return ((first << 8) | data[at + 1]) & 0x3FFF, at + 2
    if 0x18 <= kind <= 0x1B:
        return ((first << 16) | (data[at + 1] << 8) | data[at + 2]) & 0x1FFFFF, at + 3
    if kind == 0x1C:
        return int.from_bytes(data[at:at + 4], 'big') & 0x7FFFFFF, at + 4
    if kind == 0x1D:
        return int.from_bytes(data[at:at + 5], 'big') & 0x7FFFFFFFFFFFFFF, at + 5
    if kind == 0x1E:
        return int.from_bytes(data[at:at + 8], 'big') & 0x7FFFFFFFFFFFFFF, at + 8
    if first & 7 == 0:
        return int.from_bytes(data[at:at + 6], 'big') & 0xFFFFFFFFFF, at + 6
    if first & 7 == 1:
        return int.from_bytes(data[at + 1:at + 9], 'big'), at + 9
    return 0, at + 1


@dataclass
class Section:
    tag: str
    start: int  # Offset of the 8-byte header.
    body: int  # Offset of the first byte after the header.
    end: int
    leaf: bool
    children: list = field(default_factory=list)


def sections(data, start, end):
    found = []
    at = start
    while at < end:
        word = int.from_bytes(data[at:at + 4], 'big')
        size = word & 0x3FFFFFFF
        section = Section(data[at + 4:at + 8].decode('ascii'), at, at + 8, at + size, bool(word & 0xC0000000))
        if not section.leaf:
            section.children = sections(data, section.body, section.end)
        found.append(section)
        at += size
    return found


def child(section, tag):
    return next((s for s in section.children if s.tag == tag), None)


@dataclass(eq=False)
class HkField:
    name: str
    flags: int
    offset: int
    type: 'HkType | None'


@dataclass(eq=False)
class HkType:
    index: int  # One-based, as items and fields refer to it.
    name: str = ''
    parameters: list = field(default_factory=list)
    parent: 'HkType | None' = None
    flags: int = 0
    _format: int = 0
    _subtype: 'HkType | None' = None
    _version: int = 0
    _size: int = 0
    _alignment: int = 0
    own_fields: list = field(default_factory=list)

    def _inherit(self, flag, attribute, default=0):
        if self.flags & flag:
            return getattr(self, attribute)
        return self.parent._inherit(flag, attribute, default) if self.parent is not None and self.parent is not self else default

    @property
    def format_info(self):
        return self._inherit(HAS_FORMAT, '_format')

    @property
    def format(self):
        return self.format_info & 0xF

    @property
    def subtype(self):
        return self._inherit(HAS_SUBTYPE, '_subtype', None)

    @property
    def size(self):
        return self._inherit(HAS_SIZE, '_size')

    @property
    def alignment(self):
        return self._inherit(HAS_SIZE, '_alignment')

    @property
    def signed(self):
        return self.format in (BOOL, INT) and bool(self.format_info & 0x200)

    @property
    def bits(self):
        return self.format_info >> 10 if self.format in (BOOL, INT) else 0

    @property
    def fixed(self):
        return self.format in (STRING, ARRAY) and bool(self.format_info & 0x20)

    @property
    def fixed_count(self):
        if not self.fixed:
            return 0
        return self.format_info >> 16 if self.format == STRING else self.format_info >> 8

    @property
    def is_half(self):
        return self.format == FLOAT and self.format_info >> 8 == 0x746

    @property
    def fields(self):
        inherited = self.parent.fields if self.parent is not None and self.parent is not self else []
        return inherited + self.own_fields

    def __repr__(self):
        return f'HkType({self.index}, {self.name})'


def read_types(data, section):
    """The types of a TYPE section, in the order items and fields number them (one-based)."""
    types, type_names, field_names = [], [], []

    def by_index(index):
        return None if index == 0 else types[index - 1]

    for sub in section.children:
        at, end = sub.body, sub.end
        if sub.tag in ('TSTR', 'TST1', 'FSTR', 'FST1'):
            names = type_names if sub.tag[0] == 'T' else field_names
            while at < end:
                stop = data.index(b'\0', at)
                names.append(data[at:stop].decode('utf-8', 'replace'))
                at = stop + 1
        elif sub.tag in ('TNAM', 'TNA1'):
            count, at = packed_int(data, at)
            types = [HkType(i + 1) for i in range(count)]
            for t in types:
                name, at = packed_int(data, at)
                t.name = type_names[name]
                parameters, at = packed_int(data, at)
                if parameters >= 0x40:
                    parameters &= 0x3F
                for _ in range(parameters):
                    name, at = packed_int(data, at)
                    value, at = packed_int(data, at)
                    t.parameters.append((type_names[name], value))
        elif sub.tag in ('TBOD', 'TBDY'):
            while at < end:
                index, at = packed_int(data, at)
                t = by_index(index)
                if t is None:
                    continue
                parent, at = packed_int(data, at)
                t.parent = by_index(parent)
                t.flags, at = packed_int(data, at)
                if t.flags & HAS_FORMAT:
                    t._format, at = packed_int(data, at)
                if t.flags & HAS_SUBTYPE:
                    subtype, at = packed_int(data, at)
                    t._subtype = by_index(subtype)
                if t.flags & HAS_VERSION:
                    t._version, at = packed_int(data, at)
                if t.flags & HAS_SIZE:
                    t._size, at = packed_int(data, at)
                    t._alignment, at = packed_int(data, at)
                if t.flags & HAS_UNKNOWN:
                    _, at = packed_int(data, at)
                if t.flags & HAS_FIELDS:
                    # The count byte carries flags above bit 5; 0xC3 0x00 escapes a packed count (Havoc's reading).
                    count = data[at]
                    at += 1
                    if count == 0xC3:
                        count = data[at]
                        at += 1
                        if count == 0:
                            count, at = packed_int(data, at)
                    for _ in range(count & 0x3F):
                        name, at = packed_int(data, at)
                        flags, at = packed_int(data, at)
                        offset, at = packed_int(data, at)
                        field_type, at = packed_int(data, at)
                        t.own_fields.append(HkField(field_names[name], flags, offset, by_index(field_type)))
                if t.flags & HAS_INTERFACES:
                    count, at = packed_int(data, at)
                    for _ in range(count):
                        _, at = packed_int(data, at)
                        _, at = packed_int(data, at)
    return types


def read_compendium(data):
    """The types of a type compendium (TCM0), with the IDs that tagfiles name in their TCRF section."""
    root = sections(data, 0, len(data))[0]
    if root.tag != 'TCM0':
        raise ValueError(f'A type compendium starts with TCM0, not {root.tag}.')
    ids = child(root, 'TCID')
    return read_types(data, child(root, 'TYPE')), [] if ids is None else \
        [int.from_bytes(data[a:a + 8], 'little') for a in range(ids.body, ids.end, 8)]


@dataclass
class Item:
    index: int
    type: 'HkType | None'
    flags: int  # The top byte of the type word.
    offset: int  # Relative to the DATA section's body.
    count: int


@dataclass
class Value:
    """One value the walk found: where it is, what it is and the chain of fields that leads to it."""
    path: str  # Field names from the root, such as 'namedVariants/variant/characterData/...'.
    field: str  # The name of the field, or of the array field for an element.
    owner: str  # The type name of the object that holds the field.
    type: HkType
    at: int  # Absolute offset in the file.
    item: int = -1  # For an array element: the item that holds the array.
    element: int = -1


class Tagfile:
    def __init__(self, data, compendium=None):
        self.data = bytearray(data)
        root = sections(self.data, 0, len(self.data))
        if not root or root[0].tag != 'TAG0':
            raise ValueError('This file is not a Havok 2016 binary tagfile (TAG0).')
        self.root = root[0]
        self.types = []
        if child(self.root, 'TCRF') is not None:
            if compendium is None:
                raise ValueError('The tagfile takes its types from a type compendium; pass the compendium.')
            self.types, ids = read_compendium(bytes(compendium))
            reference = int.from_bytes(self.data[child(self.root, 'TCRF').body:][:8], 'little')
            if ids and reference not in ids:
                raise ValueError('The tagfile names a type compendium other than the one passed.')
        if child(self.root, 'TYPE') is not None:
            self.types = read_types(self.data, child(self.root, 'TYPE'))
        self.data_section = child(self.root, 'DATA')
        index = child(self.root, 'INDX')
        self.item_section = child(index, 'ITEM')
        self.patch_section = child(index, 'PTCH')
        self.items = []
        for n, at in enumerate(range(self.item_section.body, self.item_section.end, 12)):
            word, offset, count = struct.unpack_from('<3I', self.data, at)
            type_index = word & 0xFFFFFF
            self.items.append(Item(n, None if type_index == 0 else self.types[type_index - 1], word >> 24, offset, count))
        self.patches = self._read_patches()
        self.appended = bytearray()
        self.new_items = []
        self.new_patches = {}
        self.dropped = []  # (start, end) of item data that no slot names any more.

    # Reading.

    def _read_patches(self):
        patches = {}
        if self.patch_section is None:
            return patches
        at = self.patch_section.body
        while at < self.patch_section.end:
            type_index, count = struct.unpack_from('<iI', self.data, at)
            patches[type_index] = list(struct.unpack_from(f'<{count}I', self.data, at + 8))
            at += 8 + 4 * count
        return patches

    @property
    def base(self):
        return self.data_section.body

    def item_at(self, index):
        items = self.items + self.new_items
        return None if index == 0 or index >= len(items) else items[index]

    def reference(self, at):
        """The item that a pointer, string or array slot at this offset names."""
        return self.item_at(struct.unpack_from('<I', self.data, at)[0])

    def integer(self, value_type, at):
        size = value_type.bits // 8
        return int.from_bytes(self.data[at:at + size], 'little', signed=value_type.signed)

    def float(self, value_type, at):
        return struct.unpack_from('<e' if value_type.is_half else '<f', self.data, at)[0]

    def text(self, at):
        """The string that an hkStringPtr slot names, or None."""
        item = self.reference(at)
        if item is None or item.count == 0:
            return None
        start = self.base + item.offset
        return bytes(self.data[start:start + item.count - 1]).decode('utf-8', 'replace')

    def elements(self, item):
        """The offsets of an item's elements."""
        stride = item.type.size
        return [self.base + item.offset + i * stride for i in range(item.count)]

    def walk(self):
        """Every value in the file reachable from the root object, depth first. Each object is visited once."""
        seen = set()
        found = []

        def visit(value_type, at, path, name, owner, item=-1, element=-1):
            if value_type is None:
                return
            kind = value_type.format
            found.append(Value(path, name, owner, value_type, at, item, element))
            if kind == CLASS:
                for f in value_type.fields:
                    visit(f.type, at + f.offset, f'{path}/{f.name}', f.name, value_type.name)
            elif kind == ARRAY and value_type.fixed:
                sub = value_type.subtype
                for i in range(value_type.fixed_count):
                    visit(sub, at + i * sub.size, path, name, owner)
            elif kind == ARRAY or kind == PTR:
                target = self.reference(at)
                if target is None or target.type is None or target.index in seen:
                    return
                seen.add(target.index)
                for i, element_at in enumerate(self.elements(target)):
                    visit(target.type, element_at, path, name, owner, target.index, i)

        root = self.items[1]
        seen.add(1)
        for i, at in enumerate(self.elements(root)):
            visit(root.type, at, '', '', '', 1, i)
        return found

    def unpatched(self):
        """Check the PTCH table against the slots: (slots that name an item but are not listed, listed offsets that
        are not slots). The game's loader turns only listed slots into addresses, so both lists must be empty."""
        slots = {}
        for value in self.walk():
            kind = value.type.format
            slot = kind == PTR or (kind in (STRING, ARRAY) and not value.type.fixed)
            if slot and struct.unpack_from('<I', self.data, value.at)[0]:
                slots.setdefault(value.type.index, set()).add(value.at - self.base)
        listed = {k: set(v) for k, v in self.patches.items()}
        missing = [(k, o) for k, offsets in slots.items() for o in sorted(offsets - listed.get(k, set()))]
        extra = [(k, o) for k, offsets in listed.items() for o in sorted(offsets - slots.get(k, set()))]
        return missing, extra

    def class_fields(self, value):
        """The fields of a class value as {name: Value}."""
        return {f.name: Value(f'{value.path}/{f.name}', f.name, value.type.name, f.type, value.at + f.offset)
                for f in value.type.fields}

    def array(self, slot):
        """The item an array, pointer or string slot names, as (item, element offsets)."""
        target = self.reference(slot.at)
        if target is None or target.type is None:
            return None, []
        return target, self.elements(target)

    # Patching.

    def set_integer(self, value_type, at, number):
        size = value_type.bits // 8
        self.data[at:at + size] = int(number).to_bytes(size, 'little', signed=value_type.signed)

    def set_float(self, value_type, at, number):
        struct.pack_into('<e' if value_type.is_half else '<f', self.data, at, number)

    def _append(self, payload, alignment=16):
        end = self.data_section.end - self.base + len(self.appended)
        self.appended += bytes(-end % alignment)
        offset = end + (-end % alignment)
        self.appended += payload
        return offset

    def replace_items(self, item, payload, count):
        """Move an item to new data at the end of the DATA section. Pointers inside must be added with add_patch;
        the patches of the old data are dropped, since nothing reads it any more."""
        self.dropped.append((item.offset, item.offset + item.count * item.type.size))
        item.offset = self._append(payload, max(16, item.type.alignment or 1))
        item.count = count
        return item.offset

    def add_item(self, value_type, flags, payload, count):
        """A new item with its data; returns its number for the slot that names it."""
        offset = self._append(payload, max(16, value_type.alignment or 1))
        item = Item(len(self.items) + len(self.new_items), value_type, flags, offset, count)
        self.new_items.append(item)
        return item.index

    def add_patch(self, type_index, offsets):
        self.new_patches.setdefault(type_index, []).extend(offsets)

    def item_patches(self, item):
        """{type number: offsets in the item} of the PTCH entries for an item's slots, as the file has them."""
        start, end = item.offset, item.offset + item.count * item.type.size
        found = {}
        for type_index, offsets in self.patches.items():
            inside = [o - start for o in offsets if start <= o < end]
            if inside:
                found[type_index] = inside
        return found

    def item_bytes(self, item):
        """An item's data, which must still be where the file has it."""
        start = self.base + item.offset
        end = start + item.count * item.type.size
        if end > self.data_section.end:
            raise ValueError(f'Item {item.index} has moved to new data; read it before it moves.')
        return bytes(self.data[start:end])

    def copy_item(self, item, payload=None):
        """A new item of an item's type and flags with its data, or payload of the same length, and the patches of its
        slots. Its slots name what the payload names. Returns its number."""
        payload = self.item_bytes(item) if payload is None else bytes(payload)
        if len(payload) != item.count * item.type.size:
            raise ValueError(f'A copy of item {item.index} needs {item.count * item.type.size} bytes, not {len(payload)}.')
        index = self.add_item(item.type, item.flags, payload, item.count)
        offset = self.item_at(index).offset
        for type_index, inside in self.item_patches(item).items():
            self.add_patch(type_index, [offset + o for o in inside])
        return index

    def add_string(self, like, text):
        """A new string item of the type and flags of another string item; returns its number."""
        raw = text.encode('utf-8') + b'\0'
        return self.add_item(like.type, like.flags, raw, len(raw))

    def append_elements(self, item, elements):
        """Grow an array item by elements (bytes each) at its end. The item moves to new data with the patches of its
        slots; a new pointer or string element that names an item is patched under the element type."""
        count, size = item.count, item.type.size
        patches = self.item_patches(item)
        offset = self.replace_items(item, self.item_bytes(item) + b''.join(elements), count + len(elements))
        for type_index, inside in patches.items():
            self.add_patch(type_index, [offset + o for o in inside])
        if item.type.format in (PTR, STRING):
            self.add_patch(item.type.index, [offset + (count + i) * size for i, element in enumerate(elements)
                                             if struct.unpack_from('<I', element)[0]])
        return offset

    def write(self):
        """The file with every patch applied."""
        def header(tag, size, leaf):
            return ((size + 8) | (0x40000000 if leaf else 0)).to_bytes(4, 'big') + tag.encode('ascii')

        data = bytes(self.data)
        body = bytearray()
        for section in self.root.children:
            if section.tag == 'DATA':
                payload = data[section.body:section.end] + bytes(self.appended)
                payload += bytes(-len(payload) % 4)
                body += header('DATA', len(payload), True) + payload
            elif section.tag == 'INDX':
                index = bytearray()
                for sub in section.children:
                    if sub.tag == 'ITEM':
                        payload = bytearray()
                        for item in self.items + self.new_items:
                            word = (item.flags << 24) | (0 if item.type is None else item.type.index)
                            payload += struct.pack('<3I', word, item.offset, item.count)
                        index += header('ITEM', len(payload), True) + payload
                    elif sub.tag == 'PTCH':
                        patches = {k: [o for o in v if not any(a <= o < b for a, b in self.dropped)]
                                   for k, v in self.patches.items()}
                        for type_index, offsets in self.new_patches.items():
                            patches.setdefault(type_index, []).extend(offsets)
                        payload = bytearray()
                        for type_index, offsets in sorted(patches.items()):
                            payload += struct.pack('<iI', type_index, len(offsets))
                            payload += struct.pack(f'<{len(offsets)}I', *sorted(offsets))
                        index += header('PTCH', len(payload), True) + payload
                    else:
                        index += data[sub.start:sub.end]
                body += header('INDX', len(index), False) + index
            else:
                body += data[section.start:section.end]
        return bytes(header('TAG0', len(body), False) + body)

    def patch_type(self, value_type):
        """The type number the PTCH section files a pointer slot of this type under."""
        return value_type.index


# What a new character changes in a behavior file.

INDEX_FIELD = re.compile(
    r'^(?!ragdoll)(\w*[bB]one|hip|knee|ankle|shoulder|elbow|wrist|pelvis|head|neck|spine|leftFoot|rightFoot|leftHand|rightHand)(Sibling)?Index$')
INDEX_ARRAY_FIELD = re.compile(r'^(?!ragdoll)\w*([bB]oneIndices|[bB]oneIndexArray)$')
WEIGHT_ARRAY_FIELD = re.compile(r'^\w*[wW]eights$')
PROPERTY_NAME = re.compile(r'^(?!.*[rR]agdoll)\w*(Start|End|BoneIndex|Bone)$')
PROPERTY_SETS = {
    'hkbCharacterData': ('characterPropertyInfos', 'characterPropertyNames', 'characterPropertyValues'),
    'hkbBehaviorGraphData': ('variableInfos', 'variableNames', 'variableInitialValues'),
}


def bone_fields(tag, bone_count=0):
    """The values of a behavior file that hold bone numbers or one entry per bone.

    Each entry is a dict with kind 'index' (one number), 'indices' (a list of numbers), 'weights' (one float per
    bone), 'mirror' (hkbMirroredSkeletonInfo.bonePairMap), 'lodCounts' (numBonesPerLod) or 'property' (a character
    property or behavior variable whose name ends in Start, End, Bone or BoneIndex and whose value is a whole number).
    """
    fields = []
    for value in tag.walk():
        kind = value.type.format
        if kind == INT and value.element < 0 and INDEX_FIELD.match(value.field):
            fields.append(dict(kind='index', path=value.path, field=value.field, owner=value.owner, at=value.at,
                               type=value.type, value=tag.integer(value.type, value.at)))
        elif kind == ARRAY and not value.type.fixed and value.element < 0:
            target, offsets = tag.array(value)
            if target is None:
                continue
            element = target.type
            if element.format == INT and INDEX_ARRAY_FIELD.match(value.field):
                kind_name = 'indices'
            elif element.format == INT and value.field == 'bonePairMap':
                kind_name = 'mirror'
            elif element.format == INT and value.field == 'numBonesPerLod':
                kind_name = 'lodCounts'
            elif element.format == FLOAT and WEIGHT_ARRAY_FIELD.match(value.field) and \
                    (bone_count == 0 or target.count == bone_count):
                fields.append(dict(kind='weights', path=value.path, field=value.field, owner=value.owner, item=target,
                                   values=[tag.float(element, a) for a in offsets]))
                continue
            else:
                continue
            fields.append(dict(kind=kind_name, path=value.path, field=value.field, owner=value.owner, item=target,
                               type=element, offsets=offsets, values=[tag.integer(element, a) for a in offsets]))
    fields.extend(properties(tag))
    return fields


def properties(tag):
    """Character properties and behavior variables whose whole-number value names a bone."""
    found = []
    for value in tag.walk():
        if value.type.format != CLASS or value.type.name not in PROPERTY_SETS:
            continue
        infos_name, names_name, values_name = PROPERTY_SETS[value.type.name]
        own = tag.class_fields(value)
        names = []
        strings = tag.reference(own['stringData'].at) if 'stringData' in own else None
        if strings is not None:
            string_fields = tag.class_fields(Value('', '', '', strings.type, tag.elements(strings)[0]))
            target, offsets = tag.array(string_fields[names_name])
            names = [tag.text(a) for a in offsets]
        _, infos = tag.array(own[infos_name])
        info_type = tag.reference(own[infos_name].at).type if infos else None
        value_set = tag.reference(own[values_name].at)
        if value_set is None or info_type is None:
            continue
        set_fields = tag.class_fields(Value('', '', '', value_set.type, tag.elements(value_set)[0]))
        words_item, words = tag.array(set_fields['wordVariableValues'])
        if not words:
            continue
        word_value = next(f for f in words_item.type.fields if f.name == 'value')
        info_kind = next(f for f in info_type.fields if f.name == 'type')
        for i in range(min(len(names), len(infos), len(words))):
            # hkbVariableInfo.type: 1 to 3 are the whole-number types (bool, int8, int16, int32 are 0 to 3).
            number_type = tag.integer(info_kind.type, infos[i] + info_kind.offset)
            if names[i] and PROPERTY_NAME.match(names[i]) and 1 <= number_type <= 3:
                at = words[i] + word_value.offset
                found.append(dict(kind='property', path=f'{value.type.name}/{names[i]}', field=names[i],
                                  owner=value.type.name, at=at, type=word_value.type,
                                  value=tag.integer(word_value.type, at)))
    return found


def strings(tag, needle=''):
    """Every string of the file, as (slot offset, text), or those that contain the needle."""
    found = []
    for value in tag.walk():
        if value.type.format == STRING and not value.type.fixed:
            text = tag.text(value.at)
            if text is not None and needle.lower() in text.lower():
                found.append((value, text))
    return found


def rename(tag, old, new):
    """Replace a name in every string, in place. The new name has the same length, so no item moves."""
    if len(old) != len(new):
        raise ValueError(f'{new} must have as many characters as {old}.')
    changes = []
    pattern = re.compile(re.escape(old), re.IGNORECASE)
    for value, text in strings(tag, old):
        renamed = pattern.sub(new, text)
        item = tag.reference(value.at)
        start = tag.base + item.offset
        tag.data[start:start + len(renamed)] = renamed.encode('utf-8')
        changes.append(dict(kind='string', field=value.field, path=value.path, **{'from': text, 'to': renamed}))
    return changes


def edit_behavior(data, compendium, bone_map, weight_source, mirror, bone_count, renames=()):
    """A behavior file with its bone numbers, per-bone lists and names changed for a new skeleton.

    bone_map[old] is the new number of each template bone. weight_source[new] is the template bone whose per-bone
    values a new bone takes, or -1. mirror is the new bonePairMap. Returns (bytes, changes).
    """
    tag = Tagfile(data, compendium)
    old_count = len(bone_map)
    changes = []

    def mapped(number):
        return bone_map[number] if 0 <= number < old_count else number

    for entry in bone_fields(tag, old_count):
        kind = entry['kind']
        if kind in ('index', 'property'):
            old = entry['value']
            if mapped(old) != old:
                tag.set_integer(entry['type'], entry['at'], mapped(old))
                changes.append(dict(kind=kind, field=entry['field'], path=entry['path'], **{'from': old, 'to': mapped(old)}))
        elif kind == 'indices':
            for at, old in zip(entry['offsets'], entry['values']):
                if mapped(old) != old:
                    tag.set_integer(entry['type'], at, mapped(old))
                    changes.append(dict(kind='index', field=entry['field'], path=entry['path'], **{'from': old, 'to': mapped(old)}))
        elif kind == 'lodCounts':
            for at, old in zip(entry['offsets'], entry['values']):
                if old == old_count and bone_count != old_count:
                    tag.set_integer(entry['type'], at, bone_count)
                    changes.append(dict(kind=kind, field=entry['field'], path=entry['path'], **{'from': old, 'to': bone_count}))
        elif kind == 'weights' and entry['item'].count == old_count:
            values = entry['values']
            new = [values[s] if 0 <= s < old_count else 0.0 for s in weight_source]
            if new != values:
                element = entry['item'].type
                payload = b''.join(struct.pack('<e' if element.is_half else '<f', v) for v in new)
                tag.replace_items(entry['item'], payload, len(new))
                changes.append(dict(kind=kind, field=entry['field'], path=entry['path'], **{'from': len(values), 'to': len(new)}))
        elif kind == 'mirror' and mirror is not None and entry['item'].count == old_count:
            if list(mirror) != entry['values']:
                element = entry['type']
                size = element.bits // 8
                payload = b''.join(int(v).to_bytes(size, 'little', signed=element.signed) for v in mirror)
                tag.replace_items(entry['item'], payload, len(mirror))
                changes.append(dict(kind=kind, field=entry['field'], path=entry['path'], **{'from': old_count, 'to': len(mirror)}))
    for old, new in renames:
        changes.extend(rename(tag, old, new))
    return tag.write(), changes


# Skeletons.

def skeleton(data, compendium=None):
    """The first hkaSkeleton of a file: name, bones (name, parent, translation, rotation, scale) and list sizes."""
    tag = Tagfile(data, compendium)
    value = next((v for v in tag.walk() if v.type.format == CLASS and v.type.name == 'hkaSkeleton'), None)
    if value is None:
        raise ValueError('The file holds no hkaSkeleton.')
    own = tag.class_fields(value)
    bones_item, bones = tag.array(own['bones'])
    bone_name = next(f for f in bones_item.type.fields if f.name == 'name') if bones_item else None
    names = [tag.text(a + bone_name.offset) for a in bones] if bones_item else []
    parents_item, parents = tag.array(own['parentIndices'])
    parent_list = [tag.integer(parents_item.type, a) for a in parents]
    _, poses = tag.array(own['referencePose'])
    pose = [struct.unpack_from('<12f', tag.data, a) for a in poses]
    if not (len(names) == len(parent_list) == len(pose)):
        raise ValueError("The skeleton's bones, parents and reference pose differ in length.")

    def count(name):
        return tag.array(own[name])[0].count if name in own and tag.array(own[name])[0] else 0

    return dict(name=tag.text(own['name'].at) or '', bones=[
        dict(name=n, parent=p, translation=list(q[0:3]), rotation=list(q[4:8]), scale=list(q[8:11]))
        for n, p, q in zip(names, parent_list, pose)],
        partitions=count('partitions'), floatSlots=count('floatSlots'), localFrames=count('localFrames'),
        referenceFloats=count('referenceFloats'))


def track_bones(data, compendium=None):
    """The skeleton bone numbers that an animation file's tracks move, in track order: its binding's
    transformTrackToBoneIndices, or the first numberOfTransformTracks bones where the binding lists none."""
    tag = Tagfile(data, compendium)
    indices, tracks = None, 0
    for value in tag.walk():
        if value.field == 'transformTrackToBoneIndices' and value.type.format == ARRAY and indices is None:
            item, offsets = tag.array(value)
            indices = [] if item is None else [tag.integer(item.type, a) for a in offsets]
        elif value.field == 'numberOfTransformTracks' and value.type.format == INT and not tracks:
            tracks = tag.integer(value.type, value.at)
    return indices or list(range(tracks))


def write_skeleton(data, bones, compendium=None, renames=()):
    """The file with new bones for its first hkaSkeleton. Each bone is a dict of name, parent, translation (3),
    rotation (x, y, z, w) and scale (3). Bone names become new string items; the old ones stay unused. renames
    replaces names of the same length in the file's other strings, such as the skeleton's own name."""
    tag = Tagfile(data, compendium)
    for old, new in renames:
        rename(tag, old, new)
    value = next((v for v in tag.walk() if v.type.format == CLASS and v.type.name == 'hkaSkeleton'), None)
    if value is None:
        raise ValueError('The file holds no hkaSkeleton.')
    set_bones(tag, value, bones)
    return tag.write()


def set_bones(tag, value, bones):
    """Give an hkaSkeleton value new bones, parents and reference pose; see write_skeleton."""
    own = tag.class_fields(value)
    for name in ('partitions', 'localFrames'):
        if name in own and tag.array(own[name])[0] is not None and tag.array(own[name])[0].count:
            raise ValueError(f'The template skeleton has {name}; a new skeleton cannot keep them.')

    bones_item, bone_slots = tag.array(own['bones'])
    bone_type = bones_item.type
    name_field = next(f for f in bone_type.fields if f.name == 'name')
    template_bone = bytes(tag.data[bone_slots[0]:bone_slots[0] + bone_type.size])
    name_item = tag.reference(bone_slots[0] + name_field.offset)
    payload = bytearray()
    for bone in bones:
        text = bone['name'].encode('utf-8') + b'\0'
        index = tag.add_item(name_item.type, name_item.flags, text, len(text))
        element = bytearray(template_bone)
        struct.pack_into('<I', element, name_field.offset, index)
        payload += element
    start = tag.replace_items(bones_item, bytes(payload), len(bones))
    tag.add_patch(tag.patch_type(name_field.type), [start + i * bone_type.size + name_field.offset for i in range(len(bones))])

    parents_item, _ = tag.array(own['parentIndices'])
    size = parents_item.type.bits // 8
    tag.replace_items(parents_item, b''.join(int(b['parent']).to_bytes(size, 'little', signed=True) for b in bones), len(bones))

    pose_item, _ = tag.array(own['referencePose'])
    pose = b''.join(struct.pack('<12f', *b['translation'], 0.0, *b['rotation'], *b['scale'], 0.0) for b in bones)
    tag.replace_items(pose_item, pose, len(bones))


# A ragdoll file (the chrbnd's <id>.hkx): bodies with capsule shapes, which are what attacks hit, a ragdoll skeleton
# whose bones hold the bodies, a copy of the animation skeleton, and skeleton mappers between the two.

def qs_transform(at, data):
    """An hkQsTransform as (translation, rotation x y z w, scale)."""
    q = struct.unpack_from('<12f', data, at)
    return list(q[0:3]), list(q[4:8]), list(q[8:11])


def _skeletons(tag, values):
    found = {}
    for value in values:
        if value.type.format == CLASS and value.type.name == 'hkaSkeleton':
            own = tag.class_fields(value)
            bones_item, bones = tag.array(own['bones'])
            name_field = next(f for f in bones_item.type.fields if f.name == 'name')
            parents_item, parents = tag.array(own['parentIndices'])
            _, poses = tag.array(own['referencePose'])
            found[value.item] = dict(value=value, name=tag.text(own['name'].at) or '', bones=[
                dict(name=tag.text(at + name_field.offset), parent=tag.integer(parents_item.type, parent), pose=pose)
                for at, parent, pose in zip(bones, parents, poses)])
    return found


def _mappers(tag, values):
    found = []
    for value in values:
        if value.type.format == CLASS and value.type.name == 'hkaSkeletonMapperData':
            own = tag.class_fields(value)
            for name in ('partitionMap', 'simpleMappingPartitionRanges', 'chainMappingPartitionRanges'):
                if name in own and tag.array(own[name])[0] is not None and tag.array(own[name])[0].count:
                    raise ValueError(f'The ragdoll has a skeleton mapper with {name}; a new skeleton cannot keep them.')
            lists = {}
            for name in ('simpleMappings', 'chainMappings', 'unmappedBones'):
                item, slots = tag.array(own[name])
                fields = {f.name: f for f in item.type.fields} if item is not None and item.type.fields else {}
                lists[name] = (item, slots, fields)
            found.append(dict(value=value, own=own, lists=lists, a=tag.reference(own['skeletonA'].at).index,
                              b=tag.reference(own['skeletonB'].at).index))
    return found


def ragdoll(data):
    """What a ragdoll file holds: its skeletons by item number (name; bones with name, parent and reference pose),
    the item of the ragdoll skeleton, its skeleton mappers (skeleton items a and b; simple mappings (boneA, boneB);
    chain mappings (startBoneA, endBoneA, startBoneB, endBoneB); unmapped bones) and the body of each ragdoll bone."""
    tag = Tagfile(data)
    values = tag.walk()
    skeletons = _skeletons(tag, values)
    mappers = []
    for mapper in _mappers(tag, values):
        simple_item, simple, f = mapper['lists']['simpleMappings']
        chain_item, chains, g = mapper['lists']['chainMappings']
        unmapped_item, unmapped, _ = mapper['lists']['unmappedBones']
        mappers.append(dict(a=mapper['a'], b=mapper['b'],
                            simple=[(tag.integer(f['boneA'].type, at + f['boneA'].offset), tag.integer(f['boneB'].type, at + f['boneB'].offset))
                                    for at in simple],
                            chains=[tuple(tag.integer(g[k].type, at + g[k].offset) for k in ('startBoneA', 'endBoneA', 'startBoneB', 'endBoneB'))
                                    for at in chains],
                            unmapped=[tag.integer(unmapped_item.type, at) for at in unmapped]))
    data_value = next((v for v in values if v.type.format == CLASS and v.type.name == 'hknpRagdollData'), None)
    if data_value is None:
        raise ValueError('The file holds no hknpRagdollData.')
    own = tag.class_fields(data_value)
    body_item, bodies = tag.array(own['boneToBodyMap'])
    return dict(skeletons={k: dict(name=s['name'], bones=[dict(name=b['name'], parent=b['parent']) for b in s['bones']],
                                   pose=[qs_transform(b['pose'], tag.data) for b in s['bones']])
                           for k, s in skeletons.items()},
                ragdollSkeleton=tag.reference(own['skeleton'].at).index, mappers=mappers,
                boneToBody=[tag.integer(body_item.type, at) for at in bodies],
                bodies=tag.array(own['bodyCinfos'])[0].count)


def write_ragdoll(data, animation_item, animation_bones, ragdoll_pose, mappers, bodies):
    """The ragdoll file on a new animation skeleton.

    animation_item names the copy of the animation skeleton, which gets animation_bones (as for write_skeleton).
    ragdoll_pose is the ragdoll skeleton's new reference pose, one (translation, rotation, scale) per bone. mappers
    follow ragdoll(): per mapper, simple mappings (boneA, boneB, aFromBTransform), chain mappings (startBoneA,
    endBoneA, startBoneB, endBoneB, startAFromBTransform, endAFromBTransform) and the unmapped bones; the mappings keep
    their number. bodies is each body's new (position, orientation x y z w)."""
    tag = Tagfile(data)
    values = tag.walk()
    skeletons = _skeletons(tag, values)

    def put_transform(at, transform):
        # The fourth floats of the translation and scale are padding; they keep the template's bytes.
        t, r, s = transform
        pad = struct.unpack_from('<f', tag.data, at + 12)[0], struct.unpack_from('<f', tag.data, at + 44)[0]
        struct.pack_into('<12f', tag.data, at, *t, pad[0], *r, *s, pad[1])

    ragdoll_value = next(v for v in values if v.type.format == CLASS and v.type.name == 'hknpRagdollData')
    ragdoll_item = tag.reference(tag.class_fields(ragdoll_value)['skeleton'].at).index
    for bone, transform in zip(skeletons[ragdoll_item]['bones'], ragdoll_pose, strict=True):
        put_transform(bone['pose'], transform)

    found = _mappers(tag, values)
    if len(found) != len(mappers):
        raise ValueError('The ragdoll has another number of skeleton mappers.')
    for mapper, new in zip(found, mappers):
        _, simple, f = mapper['lists']['simpleMappings']
        for at, (a, b, transform) in zip(simple, new['simple'], strict=True):
            tag.set_integer(f['boneA'].type, at + f['boneA'].offset, a)
            tag.set_integer(f['boneB'].type, at + f['boneB'].offset, b)
            put_transform(at + f['aFromBTransform'].offset, transform)
        _, chains, g = mapper['lists']['chainMappings']
        for at, chain in zip(chains, new['chains'], strict=True):
            for key, number in zip(('startBoneA', 'endBoneA', 'startBoneB', 'endBoneB'), chain[:4]):
                tag.set_integer(g[key].type, at + g[key].offset, number)
            put_transform(at + g['startAFromBTransform'].offset, chain[4])
            put_transform(at + g['endAFromBTransform'].offset, chain[5])
        unmapped_item, unmapped, _ = mapper['lists']['unmappedBones']
        old = [tag.integer(unmapped_item.type, at) for at in unmapped] if unmapped_item else []
        if old != list(new['unmapped']):
            if unmapped_item is None:
                raise ValueError('A skeleton mapper of the template maps every bone; the new skeleton needs a list of '
                                 'unmapped bones, which the file has no item for.')
            size = unmapped_item.type.bits // 8
            tag.replace_items(unmapped_item, b''.join(int(n).to_bytes(size, 'little', signed=True) for n in new['unmapped']),
                              len(new['unmapped']))
    body_values = [v for v in values if v.type.format == CLASS and v.field == 'bodyCinfos' and v.element >= 0]
    for value, (position, orientation) in zip(body_values, bodies, strict=True):
        own = tag.class_fields(value)
        struct.pack_into('<4f', tag.data, own['position'].at, *position, 1.0)
        struct.pack_into('<4f', tag.data, own['orientation'].at, *orientation)
    set_bones(tag, skeletons[animation_item]['value'], animation_bones)
    return tag.write()
