"""Add an exported HKX to a BND4 animation binder, or replace the member of the same name.

The binder is rewritten with the layout FromSoftware's own binders have, so that
an unchanged binder comes out byte for byte as it went in: the header and each
member's header are kept, names follow the member headers, the path hash table
follows the names on an 8-byte boundary, and each member's data starts on a
16-byte boundary, as Havok data loaded in place needs. Soulstruct's own writer
does not keep that alignment, so it is not used here; Soulstruct still does the
DCX compression, in the binder's own DCX type.

A new member goes into the folder of the clip it was made from, or of the
binder's other clips, with the ID that the binder's other clips follow:
1000000000 + category * 1000000 + number for aXXX_YYYYYY.hkx in Sekiro and
Dark Souls III. Members stay in ID order.
"""
from __future__ import annotations
import re
import shutil
import struct
from collections import Counter
from pathlib import Path, PureWindowsPath

CLIP = re.compile(r'a(\d{3})_(\d{6})\.hkx', re.I)


def reverse_bits(value):
    return int(f'{value:08b}'[::-1], 2)


def file_format(raw, bit_big_endian):
    """SoulsFormats' Binder.ReadFormat: the format flags, bit 0 big-endian ... bit 5 compression."""
    reverse = bit_big_endian or (raw & 1 and not raw & 0x80)
    return raw if reverse else reverse_bits(raw)


def path_hash(path):
    """SoulsFormats' SFUtil.FromPathHash."""
    text = path.strip().replace('\\', '/').lower()
    if not text.startswith('/'):
        text = '/' + text
    value = 0
    for char in text:
        value = (value * 37 + ord(char)) & 0xFFFFFFFF
    return value


def is_prime(value):
    return value >= 2 and all(value % divisor for divisor in range(2, int(value ** .5) + 1))


def hash_table(names):
    """SoulsFormats' BinderHashTable: the number of groups, the first prime from a seventh of the members, and in
    each group the (hash, member index) pairs of the names whose hash falls in it, by hash."""
    groups = next(count for count in range(len(names) // 7, 100001) if is_prime(count))
    buckets = [[] for _ in range(groups)]
    for index, name in enumerate(names):
        value = path_hash(name)
        buckets[value % groups].append((value, index))
    for bucket in buckets:
        bucket.sort(key=lambda item: item[0])
    return groups, buckets


class Binder:
    """A BND4 binder as its parts: header, members as (header bytes, name, data), the layout's settings."""

    def __init__(self, data):
        if data[:4] != b'BND4':
            raise ValueError('This archive is not a BND4 binder. Adding members works for Sekiro, Dark Souls III and '
                             'Elden Ring animation binders.')
        self.big_endian = bool(data[9])
        self.bit_big_endian = not data[0xA]
        if self.big_endian:
            raise ValueError('Big-endian binders are not supported.')
        count, = struct.unpack_from('<i', data, 0xC)
        self.header = bytearray(data[:0x40])
        self.entry_size, = struct.unpack_from('<q', data, 0x20)
        self.unicode = bool(data[0x30])
        self.format = file_format(data[0x31], self.bit_big_endian)
        self.extended = data[0x32]
        if self.extended not in (0, 4):
            raise ValueError(f'This binder has a path table of type {self.extended}, which is not supported.')
        if not self.format & 0x0C:
            raise ValueError('This binder has no member names, so a member cannot be found by its name.')
        if not self.format & 0x02:
            raise ValueError('This binder has no member IDs.')
        # Where each field sits in a member header, after flags, padding, -1 and the stored size.
        offset = 0x10 + (8 if self.format & 0x20 else 0)
        self.data_at, offset = offset, offset + (8 if self.format & 0x10 else 4)
        self.id_at, offset = offset, offset + 4
        self.name_at, offset = offset, offset + 4
        if offset > self.entry_size:
            raise ValueError('This binder\'s member headers have an unknown layout.')
        self.members = []
        for index in range(count):
            at = 0x40 + index * self.entry_size
            entry = bytearray(data[at:at + self.entry_size])
            size, = struct.unpack_from('<q', entry, 8)
            start, = struct.unpack_from('<q' if self.format & 0x10 else '<I', entry, self.data_at)
            self.members.append([entry, self.read_name(data, struct.unpack_from('<I', entry, self.name_at)[0]),
                                 bytes(data[start:start + size])])

    def read_name(self, data, at):
        if self.unicode:
            end = at
            while data[end:end + 2] != b'\0\0':
                end += 2
            return data[at:end].decode('utf-16-le')
        return data[at:data.index(b'\0', at)].decode('shift_jis')

    def member_id(self, member):
        return struct.unpack_from('<i', member[0], self.id_at)[0]

    def to_bytes(self):
        out = bytearray(self.header)
        struct.pack_into('<i', out, 0xC, len(self.members))
        headers_at = len(out)
        out += b''.join(bytes(entry) for entry, _, _ in self.members)
        for index, (entry, name, _) in enumerate(self.members):
            struct.pack_into('<I', out, headers_at + index * self.entry_size + self.name_at, len(out))
            out += name.encode('utf-16-le') + b'\0\0' if self.unicode else name.encode('shift_jis') + b'\0'
        if self.extended == 4:
            out += b'\0' * (-len(out) % 8)
            struct.pack_into('<q', out, 0x38, len(out))
            groups, buckets = hash_table([name for _, name, _ in self.members])
            table_at = len(out)
            out += struct.pack('<qIi', 0, groups, 0x00080810)
            index = 0
            for bucket in buckets:
                out += struct.pack('<ii', len(bucket), index)
                index += len(bucket)
            struct.pack_into('<q', out, table_at, len(out))
            out += b''.join(struct.pack('<Ii', value, member) for bucket in buckets for value, member in bucket)
        struct.pack_into('<q', out, 0x28, len(out))
        for index, (entry, _, data) in enumerate(self.members):
            if data:
                out += b'\0' * (-len(out) % 0x10)
            at = headers_at + index * self.entry_size
            struct.pack_into('<q', out, at + 8, len(data))
            if self.format & 0x20:
                struct.pack_into('<q', out, at + 0x10, len(data))
            struct.pack_into('<q' if self.format & 0x10 else '<I', out, at + self.data_at, len(out))
            out += data
        return bytes(out)


def clip_id(name):
    match = CLIP.fullmatch(name)
    return 1000000000 + int(match.group(1)) * 1000000 + int(match.group(2)) if match else None


def plan_member(binder, name, near=''):
    """(index of the member named name, or None for a new one; its path; its ID)."""
    if not CLIP.fullmatch(name):
        raise ValueError(f'Name the member like the game\'s clips, aXXX_YYYYYY.hkx, such as a050_002000.hkx: {name}')
    for index, member in enumerate(binder.members):
        if PureWindowsPath(member[1]).name.lower() == name.lower():
            return index, member[1], binder.member_id(member)
    clips = [member for member in binder.members if CLIP.fullmatch(PureWindowsPath(member[1]).name)]
    if not clips:
        raise ValueError('This binder holds no aXXX_YYYYYY.hkx clips, so the folder and ID of a new one are not known.')
    if any(binder.member_id(member) != clip_id(PureWindowsPath(member[1]).name) for member in clips):
        raise ValueError('The clips in this binder do not follow the ID scheme 1000000000 + category * 1000000 + number, so '
                         'the ID of a new clip is not known. Replace an existing clip instead.')
    folders = Counter(str(PureWindowsPath(member[1]).parent) for member in clips)
    near_folder = str(PureWindowsPath(near).parent) if near else ''
    folder = near_folder if near_folder in folders else folders.most_common(1)[0][0]
    ident = clip_id(name)
    if any(binder.member_id(member) == ident for member in binder.members):
        raise ValueError(f'Another member of this binder has the ID {ident}.')
    return None, str(PureWindowsPath(folder) / name), ident


def add_member(binder_path, name, data, base_path=None, near=''):
    """Add data to the binder as member name, or replace the member of that name. Returns (new binder bytes, report).

    The binder is read from binder_path when it exists, else from base_path, such as the archive the clip came from.
    """
    from dcx_codec import unwrap
    from soulstruct.dcx import DCXType, compress
    binder_path = Path(binder_path)
    source = binder_path if binder_path.is_file() else Path(base_path) if base_path else None
    if source is None or not source.is_file():
        raise ValueError(f'The binder was not found, and no archive to start it from is known: {binder_path}')
    raw, kind = unwrap(source.read_bytes())
    binder = Binder(raw)
    index, path, ident = plan_member(binder, name, near)
    if index is None:
        template = next(member for member in binder.members if CLIP.fullmatch(PureWindowsPath(member[1]).name))
        entry = bytearray(template[0])
        struct.pack_into('<i', entry, binder.id_at, ident)
        member = [entry, path, data]
        place = next((i for i, other in enumerate(binder.members) if binder.member_id(other) > ident), len(binder.members))
        binder.members.insert(place, member)
    else:
        binder.members[index][2] = data
    written = binder.to_bytes()
    check = Binder(written)
    if not any(m[1] == path and m[2] == data for m in check.members) or len(check.members) != len(binder.members):
        raise RuntimeError('The rewritten binder did not read back with the new member.')
    if kind != DCXType.Null:
        packed = compress(written, kind)
        if unwrap(packed)[0] != written:
            raise RuntimeError('The DCX readback of the rewritten binder differs.')
        written = packed
    return written, dict(binder=str(binder_path), base=str(source), member=path, id=ident, replaced=index is not None,
                         members=len(binder.members), dcx=getattr(kind, 'name', str(kind)))


def backup(path):
    """Copy a binder to path.bak once, before it is first changed. Returns the backup's path, or ''."""
    path = Path(path)
    copy = path.with_name(path.name + '.bak')
    if path.is_file() and not copy.exists():
        shutil.copyfile(path, copy)
        return str(copy)
    return ''
