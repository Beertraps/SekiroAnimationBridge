"""The games the bridge reads: one registry for the UI, the CLI, the add-on and the code.

FromSoftware games are built in (games.fromsoft). Every other engine comes as a game package
(games.packages): a folder with a package.json, whose games join the registry when the bridge
starts or a package is installed. See docs/GAME_PACKAGES_PLAN.md and docs/PACKAGES.md.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from games.base import Capabilities, GameProfile

FROMSOFT_CAPABILITIES = Capabilities(export=True, add_to_binder=True, root_motion=True, weapons=True)

BUILTIN = (
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
)
DEFAULT_ENGINE = 'fromsoft'
PROFILES, BY_ID, ENGINES, PACKAGES = BUILTIN, {p.id: p for p in BUILTIN}, {DEFAULT_ENGINE: 'games.fromsoft'}, []


def reload():
    """Read the package folders again: the games of usable packages join the built-in ones."""
    global PROFILES, BY_ID, ENGINES, PACKAGES
    from games import packages
    found = packages.discover_packages()
    profiles, engines = list(BUILTIN), {DEFAULT_ENGINE: 'games.fromsoft'}
    for package in found:
        if not package.usable:
            continue
        taken = [p.id for p in package.profiles if p.id in {q.id for q in profiles}]
        if taken:
            package.error = f'Its games {", ".join(taken)} are already registered by the bridge or another package.'
            continue
        profiles += package.profiles
        engines[package.id] = packages.PackageEngine(package)
    PROFILES, BY_ID, ENGINES, PACKAGES = tuple(profiles), {p.id: p for p in profiles}, engines, found
    return found


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
    """The entry points of an engine: games.fromsoft, or the PackageEngine of a loaded package."""
    if engine not in ENGINES:
        raise ValueError(f'This needs the game package {engine!r}, which is not installed. Install it on the Setup page.')
    found = ENGINES[engine]
    return importlib.import_module(found) if isinstance(found, str) else found


def engine(document):
    """The engine a catalog, selection, request or motion JSON belongs to."""
    document = document or {}
    source = document.get('source') if isinstance(document.get('source'), dict) else {}
    return document.get('engine') or source.get('engine') or engine_of(document.get('game', ''))


def foreign(document):
    """The package engine of a document of another engine than FromSoftware's, or None.

    The FromSoftware code predates the registry and stays where it is; the generic entry points
    hand everything else to the package's engine.
    """
    kind = engine(document)
    return None if kind == DEFAULT_ENGINE else adapter(kind)


def detect(path, file_list='', options=None):
    """The first package that recognises a folder, or None. A package that fails is noted and skipped.

    options holds the values of the packages' declared source options, such as an AES key, by option ID.
    """
    for kind, found in ENGINES.items():
        if kind == DEFAULT_ENGINE:
            continue
        try:
            result = found.detect(path, file_list, options)
        except Exception as exc:  # A broken package must not hide the other engines.
            note = f'Detection failed: {type(exc).__name__}: {exc}'
            if note not in found.package.problems:
                found.package.problems.append(note)
            continue
        if result:
            return result
    return None


def public():
    """The registry as JSON for the UI, the CLI and the add-on."""
    return dict(games=[p.to_json() for p in PROFILES], engines=list(ENGINES),
                packages=[p.summary() for p in PACKAGES])


def write_registry(path):
    """Write games.json for the Blender add-on, which runs without this package."""
    Path(path).write_text(json.dumps(public(), indent=1), encoding='utf-8')


reload()
