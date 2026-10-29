"""The games the bridge reads: one registry for the UI, the CLI, the add-on and the code.

Each game is a GameProfile (data). Each engine has an adapter (code) in a subpackage:
games.fromsoft for Havok and FLVER, games.re_engine for RE Engine files. Adding a game of a
known engine is a profile here; a new engine also needs an adapter. See docs/MULTI_GAME_IMPORT_PLAN.md.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from games.base import Capabilities, GameProfile
from games.space import RE_ENGINE_BASIS

FROMSOFT_CAPABILITIES = Capabilities(export=True, add_to_binder=True, root_motion=True, weapons=True)
RE_ENGINE_CAPABILITIES = Capabilities(packed_archives=True)

PROFILES = (
    GameProfile('sekiro', 'Sekiro', 'SEK', 'fromsoft', ('sekiro.exe',),
                Capabilities(export=True, add_to_binder=True, root_motion=True, weapons=True, part_animations=True),
                formats=dict(havok='2016 tagfile', sdk='20160200'),
                hint='sekiro.exe, or Havok 2016 inside an animation archive',
                documentation='docs/OTHER_GAMES.md'),
    GameProfile('ds1', 'Dark Souls: Prepare to Die', 'DS1', 'fromsoft', ('darksouls.exe',), FROMSOFT_CAPABILITIES,
                formats=dict(havok='2010 packfile', sdk='20100100'),
                hint='DarkSouls.exe, or Havok 2010 inside an animation archive',
                documentation='docs/OTHER_GAMES.md'),
    GameProfile('ds1r', 'Dark Souls Remastered', 'DSR', 'fromsoft', ('darksoulsremastered.exe',), FROMSOFT_CAPABILITIES,
                formats=dict(havok='2015 tagfile', sdk='20150100'),
                hint='DarkSoulsRemastered.exe, or Havok 2015 inside an animation archive',
                documentation='docs/OTHER_GAMES.md'),
    GameProfile('ds3', 'Dark Souls III', 'DS3', 'fromsoft', ('darksoulsiii.exe',), FROMSOFT_CAPABILITIES,
                formats=dict(havok='2014 packfile'),
                hint='DarkSoulsIII.exe, or the authoring paths inside an animation archive',
                documentation='docs/OTHER_GAMES.md'),
    GameProfile('er', 'Elden Ring', 'ER', 'fromsoft', ('eldenring.exe',), FROMSOFT_CAPABILITIES,
                formats=dict(havok='2018 tagfile', sdk='20180100'),
                hint='eldenring.exe, its MATBIN library, or Havok 2018 inside an animation archive',
                documentation='docs/OTHER_GAMES.md'),
    GameProfile('dmc5', 'Devil May Cry 5', 'DMC5', 're_engine', ('devilmaycry5.exe',), RE_ENGINE_CAPABILITIES,
                basis=RE_ENGINE_BASIS,
                formats=dict(motlist=85, mot=65, mesh=1808282334, tex=11, mdf2=10, fbxskel=3, chunk='re_chunk_000.pak',
                             fileList='DMC5_STM_Release.list'),
                hint='DevilMayCry5.exe and re_chunk_000.pak, or an extracted natives folder with DMC5 file versions',
                documentation='docs/games/dmc5.md'),
    GameProfile('re2', 'Resident Evil 2 (DX11)', 'RE2', 're_engine', ('re2.exe',), RE_ENGINE_CAPABILITIES,
                basis=RE_ENGINE_BASIS,
                formats=dict(motlist=85, mot=65, mesh=1808312334, tex=10, mdf2=10, chunk='re_chunk_000.pak',
                             fileList='RE2_STM_Release.list'),
                hint='re2.exe of the DX11 (non-ray-tracing) version, or an extracted natives folder with its file versions',
                verified=False, documentation='docs/games/re2.md'),
)
BY_ID = {profile.id: profile for profile in PROFILES}
ENGINES = {'fromsoft': 'games.fromsoft', 're_engine': 'games.re_engine'}
DEFAULT_ENGINE = 'fromsoft'


def profile(game):
    try:
        return BY_ID[game]
    except KeyError:
        raise ValueError(f'Unknown game {game!r}. Supported: {", ".join(BY_ID)}.') from None


def games(engine=None):
    return [p for p in PROFILES if engine is None or p.engine == engine]


def names(engine=None):
    return {p.id: p.name for p in games(engine)}


def engine_of(game, default=DEFAULT_ENGINE):
    return BY_ID[game].engine if game in BY_ID else default


def adapter(engine):
    """The adapter module of an engine, imported when first needed."""
    if engine not in ENGINES:
        raise ValueError(f'Unknown engine {engine!r}.')
    return importlib.import_module(ENGINES[engine])


def engine(document):
    """The engine a catalog, selection, request or motion JSON belongs to."""
    document = document or {}
    source = document.get('source') if isinstance(document.get('source'), dict) else {}
    return document.get('engine') or source.get('engine') or engine_of(document.get('game', ''))


def foreign(document):
    """The adapter for a document of another engine than FromSoftware's, or None.

    The FromSoftware code predates the registry and stays where it is; the generic entry points
    hand everything else to the engine's adapter.
    """
    kind = engine(document)
    return None if kind == DEFAULT_ENGINE else adapter(kind)


def detect(path, file_list=''):
    """The first adapter other than FromSoftware's that recognises a folder, or None."""
    for kind in ENGINES:
        if kind == DEFAULT_ENGINE:
            continue
        found = adapter(kind).detect(path, file_list)
        if found:
            return found
    return None


def public():
    """The registry as JSON for the UI and the CLI."""
    return dict(games=[p.to_json() for p in PROFILES], engines=list(ENGINES))


def write_registry(path):
    """Write games.json for the Blender add-on, which runs without this package."""
    Path(path).write_text(json.dumps(public(), indent=1), encoding='utf-8')
