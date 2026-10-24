"""DCX codec shared by folder import and the optional command line utility.

Uses the pinned Soulstruct dependency already used by the animation writer. The
installed Sekiro Modding Agents bridge uses the same DCX/DFLT/KRAK approach via
SoulsFormats. No plugin, WitchyBND process or game DLL is bundled here.
"""
from __future__ import annotations
import argparse
import json
import os
import struct
import zlib
from pathlib import Path


def configure_oodle(path=""):
    """Use an explicit DLL, the environment, Steam's game copy, or Soulstruct's search."""
    from soulstruct.dcx import oodle
    explicit = path or os.environ.get('SEKIRO_OODLE_DLL', '')
    candidates = []
    if explicit:
        dll = Path(explicit).expanduser().resolve()
        if not dll.is_file():
            raise ValueError(f'Oodle DLL not found: {dll}')
        oodle.LOAD_DLL(str(dll))
        return dict(ready=True, path=str(dll))
    if os.name == 'nt':
        import winreg
        for hive, key in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    steam = Path(winreg.QueryValueEx(handle, 'SteamPath' if hive == winreg.HKEY_CURRENT_USER else 'InstallPath')[0])
                candidates.append(steam / 'steamapps/common/Sekiro/oo2core_6_win64.dll')
                libraries = steam / 'steamapps/libraryfolders.vdf'
                if libraries.is_file():
                    import re
                    for folder in re.findall(r'"path"\s+"([^"]+)"', libraries.read_text(encoding='utf-8')):
                        candidates.append(Path(folder.replace('\\\\', '\\')) / 'steamapps/common/Sekiro/oo2core_6_win64.dll')
            except OSError:
                pass
    for dll in candidates:
        if dll.is_file():
            oodle.LOAD_DLL(str(dll))
            return dict(ready=True, path=str(dll))
    try:
        found = oodle.find_oodle_dll()
        if found:
            oodle.LOAD_DLL(found)
            return dict(ready=True, path=str(found))
    except Exception:
        pass
    return dict(ready=False, path='', message='Choose oo2core_6_win64.dll from your Sekiro game folder in Settings. DFLT files work without it.')


def unwrap(data):
    """Return bytes and their DCX type; also accept already uncompressed data."""
    from soulstruct.dcx import DCXType, decompress
    if data[:4] not in (b'DCX\0', b'DCP\0'):
        return data, DCXType.Null
    try:
        return decompress(data)
    except Exception as exc:
        # The plugin bridge's Units.Unwrap accepts DFLT files written by older
        # tools with nonzero reserved header bytes. Keep the size checks here.
        if len(data) >= 0x50 and data[0x28:0x2c] == b'DFLT':
            version = struct.unpack_from('>I', data, 4)[0]
            offset = struct.unpack_from('>I', data, 0x14)[0]
            raw_size, compressed_size = struct.unpack_from('>II', data, 0x1c)
            if 0x40 <= offset <= len(data) and compressed_size <= len(data) - offset:
                result = zlib.decompress(data[offset:offset + compressed_size])
                if len(result) == raw_size:
                    return result, (DCXType.DCX_DFLT_10000_44_9 if version == 0x10000 else DCXType.DCX_DFLT_11000_44_9)
        raise ValueError('Could not decode DCX. For KRAK files, choose your game’s oo2core_6_win64.dll in Settings. '
                         f'Decoder detail: {exc}') from exc


def safe_output(source, output, force=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError('Choose a separate output file.')
    if output.exists() and not force:
        raise ValueError(f'Output already exists: {output}. Use --force to replace it.')
    protect_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    return source, output


def protect_output(output):
    output = Path(output).resolve()
    game_executables = ('sekiro.exe', 'DarkSouls.exe', 'DarkSoulsRemastered.exe', 'DarkSoulsIII.exe', 'eldenring.exe')
    if any((p / name).is_file() for p in output.parents for name in game_executables):
        raise ValueError('Write outputs to your mod workspace outside the game installation.')
    saves = (Path(os.environ.get('APPDATA', Path.home())) / 'Sekiro').resolve()
    if output == saves or saves in output.parents or output.suffix.lower() == '.sl2':
        raise ValueError('Save files are protected.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['decompress', 'compress', 'status'])
    parser.add_argument('input', nargs='?', type=Path)
    parser.add_argument('output', nargs='?', type=Path)
    parser.add_argument('--type', choices=['krak', 'dflt'], default='krak')
    parser.add_argument('--like', type=Path, help='Use the DCX compression type of this original file')
    parser.add_argument('--oodle', default='', help='Your own oo2core_6_win64.dll')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        status = configure_oodle(args.oodle)
        if args.mode == 'status':
            print(json.dumps(status)); return 0
        if not args.input or not args.output:
            parser.error('input and output are required for compress/decompress')
        source, output = safe_output(args.input, args.output, args.force)
        data = source.read_bytes()
        if args.mode == 'decompress':
            result, kind = unwrap(data)
        else:
            from soulstruct.dcx import compress, DCXType
            if data[:4] in (b'DCX\0', b'DCP\0'):
                raise ValueError('Input is already DCX compressed. Decompress it first.')
            kind = unwrap(args.like.read_bytes())[1] if args.like else (
                DCXType.DCX_KRAK if args.type == 'krak' else DCXType.DCX_DFLT_11000_44_9)
            if kind == DCXType.Null:
                raise ValueError('--like must refer to a DCX file.')
            result = compress(data, kind)
            # Verify a newly encoded wrapper before publishing it.
            if unwrap(result)[0] != data:
                raise ValueError('DCX readback differs from the input.')
        from bridge_runtime import atomic_copy
        import tempfile
        with tempfile.TemporaryDirectory(prefix='SekiroDCX-') as scratch:
            staging = Path(scratch) / 'payload'; staging.write_bytes(result)
            atomic_copy(staging, output)
        print(f'{kind.name}: {source.name} -> {output} ({len(result):,} bytes)')
        return 0
    except Exception as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
