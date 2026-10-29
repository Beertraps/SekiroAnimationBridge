"""Example engine: a template game package on package API version 1 (docs/PACKAGES.md).

Its made-up game keeps one clip per file: motions/<character>/<clip>.json, each already a motion JSON
version 2 in the game's space. A real package reads the game's own formats instead, usually with a
tool declared in package.json and run through ctx.run.
"""
from __future__ import annotations

import json
from pathlib import Path

from games.api import Space, check_motion, with_source

CATALOG_SCHEMA = 1


def detect(path, options, ctx):
    """A folder with example.game is a source of this package's game."""
    root = Path(path)
    if not (root / 'example.game').is_file():
        return None
    clips = sorted((root / 'motions').glob('*/*.json'))
    return dict(game='example', root=str(root), evidence='example.game', note='', options=[], needs=[],
                counts=dict(animations=len(clips), characters=len({c.parent.name for c in clips}), materials=0))


def scan(detection, options, ctx, previous=None):
    """One character per folder under motions; its clips are read when the character is chosen."""
    root = Path(detection['root'])
    ctx.notify('inventory', 'Listing the characters', 10)
    characters = [dict(id=folder.name, name=folder.name.title(), archives=[str(p) for p in sorted(folder.glob('*.json'))],
                       inventoried=False) for folder in sorted((root / 'motions').iterdir()) if folder.is_dir()]
    return dict(schema=CATALOG_SCHEMA, game=detection['game'], folder=str(root), characters=characters, clips=[])


def inventory(catalog, character, ctx):
    entry = next((c for c in catalog['characters'] if c['id'] == character), None)
    if not entry:
        raise ValueError(f'{character} has no animations in this source.')
    clips = [dict(id=f"{entry['id']}/{Path(p).stem}", name=Path(p).stem, character=entry['id'], characterKey=entry['id'],
                  game=catalog['game'], ready=True, issues=[], archive=p, path=p) for p in entry['archives']]
    catalog['clips'] = [c for c in catalog['clips'] if c['characterKey'] != entry['id']] + clips
    entry.update(inventoried=True, count=len(clips))
    return catalog


def selection(catalog, clip_id, preset, ctx):
    clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
    if not clip:
        raise ValueError('Choose an animation from the scanned source.')
    return dict(animation=clip['path'], game=clip['game'], character=clip['character'], clipName=clip['name'], parts=[])


def read_motion(path, game):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    document = with_source(document, Space.of(document), 'example', game, 'json', archive=path)
    return check_motion(dict(document, game=game), f'{Path(path).name}')


def preview(selection, ctx):
    return read_motion(selection['animation'], selection['game'])


def prepare(request, catalog, temp, ctx):
    chosen = selection(catalog, request.get('assetClip', ''), request.get('preset', 'auto'), ctx)
    ctx.notify('decode', 'Reading the clip', 15)
    motion = read_motion(chosen['animation'], chosen['game'])
    path = Path(temp) / 'motion.json'
    path.write_text(json.dumps(motion), encoding='utf-8')
    report = dict(clip=motion['clip'], frames=motion['frameCount'], tracks=motion['trackCount'], warnings=[])
    return dict(motion=path, characters=[], report=report, request=dict(game=chosen['game'], animation=chosen['animation']))
