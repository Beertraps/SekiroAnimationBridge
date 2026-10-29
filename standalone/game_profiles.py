"""Identify the supported PC games and preserve their native Havok container."""
from __future__ import annotations
from games import games as registered
# The Havok games. Other engines' games are in the registry (standalone/games) only.
GAMES = {p.id: p.name for p in registered('fromsoft')}
SDK_GAMES = {p.formats['sdk']: p.id for p in registered('fromsoft') if 'sdk' in p.formats}


def path_game(path):
    """Original authoring paths disambiguate titles sharing Havok versions."""
    value = str(path).replace('\\', '/').lower()
    for token, game in [('/fdp/', 'ds3'), ('/frpg/', 'ds1'), ('/gr/', 'er'), ('/ntc/', 'sekiro')]:
        if token in value: return game
    return ''


def havok_info(data, origin=''):
    info = dict(container='', version='', game='', pointerSize=0, littleEndian=True)
    if data[4:8] == b'TAG0':
        end = min(len(data), int.from_bytes(data[:4], 'big') & 0x3fffffff)
        pos = 8
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos+4], 'big') & 0x3fffffff
            if size < 8 or pos + size > end: break
            if data[pos+4:pos+8] == b'SDKV':
                version = data[pos+8:pos+size].decode('ascii').rstrip('\0')
                info.update(container='tagfile', version=version, game=SDK_GAMES.get(version, ''))
                return info
            pos += size
    elif data[:8] == bytes.fromhex('57e0e05710c0c010') and len(data) >= 64:
        little = data[17] == 1
        version = data[40:56].split(b'\0', 1)[0].decode('ascii')
        game = 'ds1' if version.startswith('hk_2010.') else ''
        if version.startswith('hk_2014.') and path_game(origin) == 'ds3': game = 'ds3'
        info.update(container='packfile', version=version, game=game, pointerSize=data[16],
                    littleEndian=little, headerVersion=int.from_bytes(data[12:16], 'little' if little else 'big'),
                    reusePadding=data[18], flags=int.from_bytes(data[56:60], 'little' if little else 'big'))
    return info


def resolve_game(info, requested='auto'):
    detected = info.get('game', '')
    if requested and requested != 'auto':
        if requested not in GAMES: raise ValueError('Choose a supported source game.')
        expected = {'ds1': '2010', 'ds1r': '2015', 'ds3': '2014', 'sekiro': '2016', 'er': '2018'}[requested]
        if expected not in info.get('version', ''):
            raise ValueError(f"Selected {GAMES[requested]}, but this HKX uses {info.get('version') or 'an unknown Havok version'}.")
        if detected and detected != requested:
            raise ValueError(f'Selected {GAMES[requested]}, but the source identifies {GAMES[detected]}.')
        return requested
    if not detected:
        raise ValueError('Cannot identify this source game from the HKX header and original path. Choose the game explicitly. Supported: Sekiro, DS1/PTDE, DS1 Remastered, DS3 and Elden Ring.')
    return detected


def model_game(flver):
    hints = {path_game(mesh.material.mat_def_path) for mesh in flver.meshes} - {''}
    if len(hints) == 1:
        game = hints.pop()
        # FLVER does not distinguish original and remastered Dark Souls reliably.
        return game if game != 'ds1' else ''
    return ''


def animation_class(game):
    from importlib import import_module
    modules = {'sekiro': 'sekiro', 'ds1': 'darksouls1ptde', 'ds1r': 'darksouls1r',
               'ds3': 'darksouls3', 'er': 'eldenring'}
    if game not in modules: raise ValueError(f'Unsupported export game: {game}')
    return import_module('soulstruct.havok.fromsoft.' + modules[game]).AnimationHKX


def player_parts(parts):
    """Select one available piece per region; leave competing outfits for the user."""
    roles = ('hd', 'fc', 'hr', 'am', 'bd', 'lg')
    for role in roles:
        candidates = [p for p in parts if p['id'].split('_')[0] == role]
        if len(candidates) == 1: candidates[0]['selected'] = True
    return parts
