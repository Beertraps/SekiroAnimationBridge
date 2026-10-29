"""DOOM Eternal's containers: packagemapspec.json, .resources archives, .streamdb files and Oodle.

Ported from Valen (https://github.com/jandk/valen, MIT, by Jan De Kock) and checked against the game's files.
Everything here only reads the game folder.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path

import numpy as np

RESOURCES_MAGIC = 0x4C434449  # 'IDCL'

# One entry of a .resources file's table, 144 bytes, little endian.
ENTRY = np.dtype([
    ('typeString', '<i8'), ('nameString', '<i8'), ('descString', '<i8'), ('depIndices', '<i8'), ('strings', '<i8'),
    ('specialHashes', '<i8'), ('metaEntries', '<i8'), ('dataOffset', '<i8'), ('dataSize', '<i8'), ('uncompressedSize', '<i8'),
    ('dataCheckSum', '<u8'), ('generationTimeStamp', '<u8'), ('defaultHash', '<u8'), ('version', '<i4'), ('flags', '<i4'),
    ('compMode', 'u1'), ('reserved0', 'u1'), ('variation', '<u2'), ('reserved2', '<i4'), ('reservedForVariations', '<i8'),
    ('numStrings', '<i2'), ('numSources', '<i2'), ('numDependencies', '<i2'), ('numSpecialHashes', '<i2'),
    ('numMetaEntries', '<i2'), ('padding1', '<i4'), ('padding2', '<i2')])
assert ENTRY.itemsize == 144

COMP_NONE, COMP_KRAKEN, COMP_KRAKEN_CHUNKED = 0, 2, 4
STREAMDB_MAGIC = 0x61C7F32E29C2A550
STREAM_ENTRY = np.dtype([('identity', '<u8'), ('offset16', '<u4'), ('length', '<u4')])


class Oodle:
    """OodleLZ_Decompress from the game's own oo2core_8_win64.dll, used in place."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError(f'DOOM Eternal\'s Oodle library is missing: {self.path}. Check the game files in Steam.')
        self.library = ctypes.WinDLL(str(self.path))
        self.function = self.library.OodleLZ_Decompress
        self.function.restype = ctypes.c_int64
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]

    def decompress(self, data, size):
        source = ctypes.create_string_buffer(bytes(data), len(data))
        target = ctypes.create_string_buffer(size)
        written = self.function(source, len(data), target, size, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if written != size:
            raise ValueError(f'Oodle could not decompress {len(data)} bytes into {size} (got {written}).')
        return target.raw


class Entry:
    """One file inside a .resources archive."""

    __slots__ = ('name', 'type', 'path', 'offset', 'size', 'unpacked', 'mode', 'version', 'variation', 'hash')

    def __init__(self, name, type_, path, offset, size, unpacked, mode, version, variation, hash_=0):
        self.name, self.type, self.path = name, type_, path
        self.offset, self.size, self.unpacked, self.mode = offset, size, unpacked, mode
        self.version, self.variation = version, variation
        self.hash = hash_  # the key of its streamed data: geometry and image mips in the .streamdb files


def read_resources(path, kinds=None):
    """The entries of one .resources file that hold data; only the resource types in kinds when given."""
    path = Path(path)
    with path.open('rb') as file:
        header = np.frombuffer(file.read(128), dtype=np.uint8)
        values = header.view('<u4')
        if values[0] != RESOURCES_MAGIC or values[1] != 0xC:
            raise ValueError(f'{path.name} is not a DOOM Eternal resources file of version 12.')
        count, dependencies, dependency_indices, string_indices = (int(v) for v in values[8:12])
        longs = header[64:112].view('<i8')
        string_table, entries_offset, dependencies_offset = int(longs[0]), int(longs[2]), int(longs[3])
        file.seek(entries_offset)
        entries = np.frombuffer(file.read(count * ENTRY.itemsize), dtype=ENTRY)
        file.seek(string_table)
        string_count = int(np.frombuffer(file.read(8), '<i8')[0])
        file.seek(string_count * 8, 1)
        blob = file.read(dependencies_offset - file.tell())
        strings = blob.split(b'\0', string_count)[:string_count]
        file.seek(dependencies_offset + dependencies * 32 + dependency_indices * 4)
        string_index = np.frombuffer(file.read(string_indices * 8), '<i8')
    result = []
    for entry in entries:
        if entry['uncompressedSize'] <= 0:
            continue
        first = int(entry['strings'])
        type_ = strings[int(string_index[first])].decode('utf-8', 'replace')
        if kinds and type_ not in kinds:
            continue
        name = strings[int(string_index[first + 1])].decode('utf-8', 'replace')
        result.append(Entry(name, type_, path, int(entry['dataOffset']), int(entry['dataSize']), int(entry['uncompressedSize']),
                            int(entry['compMode']), int(entry['version']), int(entry['variation']), int(entry['defaultHash'])))
    return result


def read_streamdb(path):
    """{stream ID: (path, offset, size)} of one .streamdb file."""
    path = Path(path)
    with path.open('rb') as file:
        header = np.frombuffer(file.read(32), dtype=np.uint8)
        if int(header[:8].view('<u8')[0]) != STREAMDB_MAGIC:
            raise ValueError(f'{path.name} is not a DOOM Eternal stream file.')
        count = int(header[24:28].view('<u4')[0])
        entries = np.frombuffer(file.read(count * 16), STREAM_ENTRY)
    return {int(e['identity']): (path, int(e['offset16']) * 16, int(e['length'])) for e in entries}


class Game:
    """A DOOM Eternal installation: its package map, archives and stream files, read on demand."""

    def __init__(self, root, kinds=None):
        self.root = Path(root)
        self.kinds = frozenset(kinds) if kinds else None
        self.base = self.root / 'base'
        spec = json.loads((self.base / 'packagemapspec.json').read_text(encoding='utf-8'))
        self.files = [f['name'] for f in spec['files']]
        self.maps = [m['name'] for m in spec['maps']]
        self.map_files = {}
        for ref in spec['mapFileRefs']:
            self.map_files.setdefault(self.maps[ref['map']], []).append(self.files[ref['file']])
        self._oodle = None
        self._streams = None
        self._lock = threading.Lock()
        self._indexes = {}

    @property
    def oodle(self):
        if self._oodle is None:
            self._oodle = Oodle(self.root / 'oo2core_8_win64.dll')
        return self._oodle

    def resources(self, *maps):
        """The .resources files of these maps, in the game's order."""
        return [self.base / f for m in maps for f in self.map_files.get(m, []) if f.endswith('.resources')]

    def index(self, path):
        """The entries of one .resources file, cached."""
        key = str(path)
        with self._lock:
            if key not in self._indexes:
                self._indexes[key] = read_resources(path, self.kinds)
            return self._indexes[key]

    def entries(self, *maps):
        """{(type, name): entry} of these maps; an earlier file wins, as in the game."""
        found = {}
        for path in self.resources(*maps):
            for entry in self.index(path):
                found.setdefault((entry.type, entry.name), entry)
        return found

    def read(self, entry):
        with entry.path.open('rb') as file:
            file.seek(entry.offset)
            data = file.read(entry.size)
        if entry.mode == COMP_NONE:
            return data
        if entry.mode == COMP_KRAKEN:
            return self.oodle.decompress(data, entry.unpacked)
        if entry.mode == COMP_KRAKEN_CHUNKED:
            return self.oodle.decompress(data[12:], entry.unpacked)
        raise ValueError(f'{entry.name} uses compression mode {entry.mode}, which this package does not read.')

    def stream(self, identity, size=0):
        """Data from the .streamdb files by its stream ID; b'' when no stream file has it."""
        with self._lock:
            if self._streams is None:
                self._streams = {}
                for name in self.files:
                    if name.endswith('.streamdb'):
                        for key, value in read_streamdb(self.base / name).items():
                            self._streams.setdefault(key, value)
        found = self._streams.get(int(identity))
        if not found:
            return b''
        path, offset, length = found
        with path.open('rb') as file:
            file.seek(offset)
            data = file.read(length)
        return self.oodle.decompress(data, size) if size and size != length else data
