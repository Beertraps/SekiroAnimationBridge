"""What an Unreal game's files say before CUE4Parse mounts them: its project folder, the PAK and IoStore
headers (format version, encryption, compression) and the engine branch its executable was built from.

Everything here reads a few bytes of each file and never decrypts or decompresses anything.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

PAK_MAGIC = struct.pack('<I', 0x5A6F12E1)
TOC_MAGIC = b'-==--==--==--==-'
TOC_HEADER = struct.Struct('<16sBBHIIIIIIIII8s16sBBHIQII')
TOC_ENCRYPTED = 0x02
METHODS = ('Oodle', 'Zlib', 'Gzip', 'LZ4', 'Zstd', 'Brotli')

# The first engine version that writes each archive version. Several engine versions share one, so a version read
# from the archives is a guess; the branch name in the executable, a game profile or the user's choice decide.
TOC_ENGINES = {1: 'GAME_UE4_25', 2: 'GAME_UE4_26', 3: 'GAME_UE4_27', 4: 'GAME_UE5_0', 5: 'GAME_UE5_1', 6: 'GAME_UE5_3',
               7: 'GAME_UE5_4', 8: 'GAME_UE5_5', 9: 'GAME_UE5_6', 10: 'GAME_UE5_7'}
PAK_ENGINES = {1: 'GAME_UE4_0', 2: 'GAME_UE4_0', 3: 'GAME_UE4_3', 4: 'GAME_UE4_16', 5: 'GAME_UE4_20', 6: 'GAME_UE4_21',
               7: 'GAME_UE4_22', 8: 'GAME_UE4_22', 9: 'GAME_UE4_25', 10: 'GAME_UE4_26', 11: 'GAME_UE4_27', 12: 'GAME_UE5_7',
               13: 'GAME_UE5_7'}
# FEngineVersion's branch, such as ++UE5+Release-5.3, stored as UTF-16 in the executable.
BRANCH = re.compile(rb'\+\x00\+\x00U\x00E\x00([45])\x00\+\x00R\x00e\x00l\x00e\x00a\x00s\x00e\x00-\x00[45]\x00\.\x00(\d)\x00(\d\x00)?')
_BRANCHES = {}


def engine_label(engine):
    """GAME_UE5_3 as Unreal Engine 5.3."""
    match = re.fullmatch(r'GAME_UE(\d)_(\d+)', engine or '')
    return f'Unreal Engine {match[1]}.{match[2]}' if match else engine


def is_project(folder):
    """A project folder holds Content/Paks with archives. The engine's own folder and its programs, such as the crash
    reporter in Engine/Programs, do not count."""
    folder = Path(folder)
    names = [p.name.lower() for p in (folder, folder.parent, folder.parent.parent)]
    if names[0] == 'engine' or names[1:] == ['programs', 'engine']:
        return False
    paks = folder / 'Content' / 'Paks'
    return paks.is_dir() and bool(archive_files(paks))


def find_project(chosen):
    """The project folder for a chosen folder: the game folder, the folder above it, its Content or Paks folder, or a
    folder up to two levels below, as in Xbox installs (Game/Content/Project)."""
    chosen = Path(chosen)
    for candidate in (chosen, chosen.parent, chosen.parent.parent, chosen.parent.parent.parent):
        if is_project(candidate):
            return candidate
    for depth in (1, 2):
        pattern = '/'.join(['*'] * depth)
        found = sorted(p for p in chosen.glob(pattern) if p.is_dir() and is_project(p))
        if found:
            return found[0]
    return None


def archive_files(paks):
    """PAK and IoStore archives in a Paks folder and its subfolders (patches, ~mods), in name order."""
    paks = Path(paks)
    if not paks.is_dir():
        return []
    return sorted((p for p in paks.rglob('*') if p.suffix.lower() in ('.pak', '.utoc') and p.is_file()),
                  key=lambda p: str(p).lower())


def read_pak(path):
    """The trailer of a PAK file: version, whether the index is encrypted, the key GUID and the compression methods."""
    with open(path, 'rb') as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 1024))
        tail = handle.read()
    at = tail.rfind(PAK_MAGIC)
    if at < 17:
        return None
    version = struct.unpack_from('<i', tail, at + 4)[0]
    methods = sorted({m for m in METHODS if m.encode() in tail[at:]})
    return dict(kind='pak', version=version, encrypted=tail[at - 1] != 0, keyGuid=tail[at - 17:at - 1].hex(), methods=methods)


def read_toc(path):
    """The header of an IoStore .utoc file and the names of its compression methods."""
    with open(path, 'rb') as handle:
        header = handle.read(TOC_HEADER.size)
        if len(header) < TOC_HEADER.size or not header.startswith(TOC_MAGIC):
            return None
        (_, version, _, _, header_size, entries, blocks, block_size, method_count, method_length, _, _, _, _, key_guid,
         flags, _, _, seeds, _, unhashed, _) = TOC_HEADER.unpack(header)
        # FIoStoreTocResource: chunk IDs (12 bytes) and offsets (10), perfect-hash seeds and overflow indices
        # (4 each), compression blocks, then the method names.
        offset = header_size + entries * 22 + (seeds * 4 if version >= 4 else 0) + (unhashed * 4 if version >= 5 else 0)
        handle.seek(offset + blocks * block_size)
        names = handle.read(min(method_count, 16) * method_length) if method_length <= 64 else b''
    methods = sorted({m for m in METHODS if m.encode() in names})
    return dict(kind='iostore', version=version, encrypted=bool(flags & TOC_ENCRYPTED), keyGuid=key_guid.hex(), methods=methods)


def read_archives(files):
    """What the archives have in common: their container, newest versions, encryption and compression."""
    headers = []
    for path in files:
        try:
            header = read_toc(path) if path.suffix.lower() == '.utoc' else read_pak(path)
        except OSError:
            header = None
        if header:
            headers.append(dict(header, name=path.name))
    tocs = [h for h in headers if h['kind'] == 'iostore']
    paks = [h for h in headers if h['kind'] == 'pak']
    return dict(container='iostore' if tocs else 'pak', headers=headers,
                tocVersion=max((h['version'] for h in tocs), default=0), pakVersion=max((h['version'] for h in paks), default=0),
                encrypted=sorted(h['name'] for h in headers if h['encrypted']),
                methods=sorted({m for h in headers for m in h['methods']}), unread=len(files) - len(headers))


def guessed_engine(info):
    """The engine version the archive formats suggest, or ''."""
    if info['tocVersion']:
        return TOC_ENGINES.get(info['tocVersion'], 'GAME_UE5_LATEST' if info['tocVersion'] > max(TOC_ENGINES) else '')
    return PAK_ENGINES.get(info['pakVersion'], '')


def executables(project):
    """The game's executables, the large shipping builds first: they hold the engine's branch name."""
    found = [*Path(project).glob('Binaries/*/*.exe'), *Path(project).parent.glob('*.exe')]
    sized = []
    for path in found:
        try:
            sized.append((path.stat().st_size, path))
        except OSError:
            continue
    return [path for _, path in sorted(sized, key=lambda item: (-item[0], str(item[1])))]


def find_branch(handle, chunk=1 << 24):
    """The first branch name in a file, read in pieces that overlap by more than a branch name is long."""
    tail = b''
    while piece := handle.read(chunk):
        data = tail + piece
        match = BRANCH.search(data)
        if match:
            return match
        tail = data[-64:]
    return None


def branch_engine(path):
    """GAME_UE4_27 for an executable built from ++UE4+Release-4.27, or '' when it names no release branch or
    cannot be read (store installs protect theirs)."""
    path = Path(path)
    try:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in _BRANCHES:
            with open(path, 'rb') as handle:
                match = find_branch(handle)
            _BRANCHES[key] = f'GAME_UE{match[1].decode()}_{match[2].decode()}{match[3][:1].decode() if match[3] else ""}' if match else ''
        return _BRANCHES[key]
    except (OSError, ValueError):
        return ''


def detected_engine(project, info):
    """(engine, evidence): the branch of the first executable that names one, else the archive formats' guess."""
    for path in executables(project)[:4]:
        engine = branch_engine(path)
        if engine:
            return engine, f'{path.name} was built with {engine_label(engine)}'
    engine = guessed_engine(info)
    if not engine:
        return '', ''
    kind = f'IoStore version {info["tocVersion"]}' if info['tocVersion'] else f'PAK version {info["pakVersion"]}'
    return engine, f'{kind} suggests {engine_label(engine)}'
