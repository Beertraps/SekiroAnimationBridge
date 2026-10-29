"""DOOM Eternal (id Tech 7): md6 animations on their md6 skeletons, read in Python.

A game package for the Sekiro Animation Bridge, on package API version 1 (games.api, docs/PACKAGES.md).
A source is the game folder, with DOOMEternalx64vk.exe and base/packagemapspec.json. The package reads
the .resources archives in place, decompresses them with the game's own oo2core_8_win64.dll and never
writes into the game folder. The formats are ported from Valen (https://github.com/jandk/valen, MIT, by
Jan De Kock).

A character is a skeleton: every animation names the skeleton it plays on, so the clips of a character
are the animations that name its skeleton, wherever they are stored (a shield soldier's clips play on
the blaster soldier's skeleton, cinematics on the Doom Slayer's).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from games.api import check_motion, read_json, signature, with_source, write_json

from . import md6
from .formats import Game

# 2: readable character names, shorter clip names, and ready counts.
CATALOG_SCHEMA = 2
GAME = 'doom_eternal'
EXECUTABLE = 'doometernalx64vk.exe'
SPEC = Path('base') / 'packagemapspec.json'
KINDS = ('anim', 'skeleton', 'baseModel', 'image', 'rs_streamfile')
# Skeletons in these folders are characters; objects, cameras and level kit are left out.
CHARACTER_FOLDERS = ('md6/characters/', 'md6/player/')
ADDITIVE_ISSUE = ('An additive clip: the game adds it on top of another animation, so it has no pose of its own. '
                  'Choose the clip it is added to instead.')
UNIT_NOTE = 'The clip stores its positions in game units (0.01905 m); they were converted to metres.'
# Folders that clip names leave out, since so many clips share them.
SHARED_FOLDERS = {'md6', 'characters', 'humans', 'monsters', 'ambient', 'base', 'motion', 'mechanics', 'dlc_01', 'dlc_02'}
_GAMES = {}
_LOCK = threading.Lock()


# The game folder

def game_root(path):
    """The game folder: the chosen one, its parent or the one above, holding base/packagemapspec.json."""
    path = Path(path)
    for candidate in (path, path.parent, path.parent.parent):
        if (candidate / SPEC).is_file():
            return candidate
    return None


def game_of(root):
    """The game's archives, indexed once per bridge run and again after a game update."""
    root = Path(root)
    key = (str(root).lower(), signature(root / SPEC))
    with _LOCK:
        game = _GAMES.get(key)
        if game is None:
            game = _GAMES[key] = Game(root, KINDS)
        return game


def source_key(game):
    """Changes whenever the game's archives do, such as after an update."""
    files = [game.root / SPEC, *game.resources(*game.maps)]
    return hashlib.sha256(json.dumps([(str(p), signature(p)) for p in dict.fromkeys(files)]).encode()).hexdigest()[:24]


def is_character(skeleton):
    return skeleton.startswith(CHARACTER_FOLDERS)


def entries_of(game):
    return game.entries(*game.maps)


def owners(game, entries, ctx, key=None):
    """{animation: [skeleton, flags]} for every animation of the game, read from each file's header and cached."""
    key = key or source_key(game)
    cached = Path(ctx.cache) / f'clips-{key}.json'
    found = read_json(cached)
    if isinstance(found, dict) and found:
        return found
    anims = [(name, entry) for (kind, name), entry in entries.items() if kind == 'anim']
    found, step = {}, 400
    with ThreadPoolExecutor(8) as pool:
        for start in range(0, len(anims), step):
            chunk = anims[start:start + step]
            ctx.notify('inventory', f'Reading which skeleton each animation uses ({start}/{len(anims)})',
                       15 + 75 * start // max(len(anims), 1))
            for (name, _), info in zip(chunk, pool.map(lambda item: header(game, item[1]), chunk)):
                if info:
                    found[name] = list(info)
    write_json(cached, found)
    return found


def header(game, entry):
    try:
        return md6.read_info(game.read(entry))
    except (ValueError, OSError):
        return None


def model_owners(game, entries, ctx, key=None):
    """{model: skeleton} for every md6 model of the game, read from each model's header and cached."""
    key = key or source_key(game)
    cached = Path(ctx.cache) / f'models-{key}.json'
    found = read_json(cached)
    if isinstance(found, dict) and found:
        return found
    found = {}
    for (kind, name), entry in entries.items():
        if kind == 'baseModel':
            try:
                found[name] = md6.read_header(game.read(entry))
            except (ValueError, OSError):
                continue
    write_json(cached, found)
    return found


def model_parts(catalog, skeleton, ctx):
    """The models that use a character's skeleton; the plainest one of its own folder is chosen."""
    game = game_of(catalog['folder'])
    owned = sorted(m for m, s in model_owners(game, entries_of(game), ctx, catalog.get('sourceKey')).items() if s == skeleton)
    folder = skeleton.rsplit('/', 1)[0]
    parts = []
    for model in owned:
        stem = model.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        where = model.split('/')[-5] if model.startswith('md6/customization/') and model.count('/') > 5 else ''
        parts.append(dict(id=model, name=f'{stem} · {where}' if where else stem, path=model, selected=False, game=GAME,
                          role='Body', container='Model', scope=catalog['folder'], own=model.rsplit('/', 1)[0] == folder))
    parts.sort(key=lambda p: (not p['own'], len(p['name']), p['name']))
    if parts:
        parts[0]['selected'] = True
    return parts


# Names

def character_name(skeleton):
    """Imp; Zombie Maykr chainsaw torso horizontal for a gore variant; Revenant 1P (first person)."""
    parts = skeleton.split('/')
    stem = parts[-1].rsplit('.', 1)[0]
    if skeleton.startswith('md6/player/'):
        return f"{stem.replace('_', ' ').title()} (first person)"
    creature, variant = (parts[3], parts[4]) if len(parts) > 5 else (stem, 'base')
    if variant == 'base' or stem == creature:
        return stem.replace('_', ' ').title()
    rest = stem[len(creature) + 1:] if stem.startswith(creature + '_') else stem
    return f"{creature.replace('_', ' ').title()} {in_words(rest)}"


def in_words(name):
    """chainsaw torso horizontal for cstorsohorizontal: a gore variant's file name in words."""
    name = re.sub(r'^cs_?(?=[a-z])', 'chainsaw_', name)
    name = re.sub(r'torso(?=[a-z])', 'torso_', name)
    return name.replace('lefttoright', 'left_to_right').replace('righttoleft', 'right_to_left').replace('_', ' ')


def character_folder(skeleton):
    """md6/characters/monsters/imp for the imp's skeleton; the folder its own clips are under."""
    parts = skeleton.split('/')
    return '/'.join(parts[:4]) if skeleton.startswith('md6/characters/') else '/'.join(parts[:3])


def clip_name(anim, skeleton):
    """The clip's path without the folders that many clips share.

    combat/idle_01 for the character's own motions, doom1/core/energy/bfg/idle for those of its doom1 variant;
    player/syncmelee/kill/kill_front_leftarm for the Doom Slayer's glory kill of an imp, without the imp's name;
    cine/e1m1_intro/intro_game/s080_player for a cinematic shot, without the shot's scene name repeated.
    """
    stem = anim.rsplit('.', 1)[0]
    own = character_folder(skeleton) + '/'
    if stem.startswith(own) and '/motion/' in stem:
        before, after = stem.split('/motion/', 1)
        variant = before[len(own):].split('/')[0] if len(before) > len(own) else 'base'
        return after if variant == 'base' else f'{variant}/{after}'
    names = {own.rstrip('/').rsplit('/', 1)[-1], skeleton.rsplit('/', 1)[-1].rsplit('.', 1)[0]}
    *folders, last = stem.split('/')
    kept = []
    for folder in folders:
        if folder in SHARED_FOLDERS or folder in names or (folder == 'human' and kept[-1:] == ['player']):
            continue
        kept.append('cine' if folder == 'cineractive' else folder)
    if folders and last.startswith(folders[-1] + '_'):
        last = last[len(folders[-1]) + 1:]
    elif folders:
        last = re.sub(f'_{re.escape(folders[-1])}(?=_|$)', '', last) or last
    for name in sorted(names, key=len, reverse=True):
        if last.endswith('_' + name):
            last = last[:-len(name) - 1]
        elif last.startswith(name + '_'):
            last = last[len(name) + 1:]
    return '/'.join(kept + [last])


def clip_names(anims, skeleton):
    """{anim: name} for one character's clips; clips whose short names collide keep their longer paths."""
    names = {anim: clip_name(anim, skeleton) for anim in anims}
    seen = {}
    for name in names.values():
        seen[name] = seen.get(name, 0) + 1
    for anim, name in names.items():
        if seen[name] > 1:
            stem = anim.rsplit('.', 1)[0]
            names[anim] = stem[4:] if stem.startswith('md6/') else stem
    return names


def unique_names(skeletons):
    names = {s: character_name(s) for s in skeletons}
    seen = {}
    for skeleton, name in names.items():
        seen.setdefault(name, []).append(skeleton)
    for name, group in seen.items():
        if len(group) > 1:
            for skeleton in group:
                names[skeleton] = f"{name} ({'/'.join(skeleton.split('/')[2:-3]) or skeleton})"
    return names


# Package API

def detect(path, options, ctx):
    """A DOOM Eternal game folder, or a folder inside it."""
    if not str(path or '').strip() or not Path(path).is_dir():
        return None
    root = game_root(Path(path).resolve())
    if root is None:
        return None
    executables = [p.name for p in root.iterdir() if p.is_file() and p.name.lower() == EXECUTABLE]
    if not executables and not (root / 'oo2core_8_win64.dll').is_file():
        return None
    game = game_of(root)
    entries = entries_of(game)
    animations = sum(1 for kind, _ in entries if kind == 'anim')
    characters = sum(1 for kind, name in entries if kind == 'skeleton' and is_character(name))
    evidence = f"{executables[0] if executables else 'oo2core_8_win64.dll'} and {SPEC.as_posix()}"
    note = '' if (root / 'oo2core_8_win64.dll').is_file() else 'oo2core_8_win64.dll is missing; check the game files in Steam.'
    return dict(game=GAME, root=str(root), evidence=evidence, note=note, options=[], needs=[],
                counts=dict(animations=animations, characters=characters, materials=0))


def scan(detection, options, ctx, previous=None):
    """The characters: each character skeleton that clips play on, with its number of clips."""
    root = Path(detection['root'])
    ctx.notify('inventory', 'Reading the archive indexes', 5)
    game = game_of(root)
    key = source_key(game)
    if previous and previous.get('schema') == CATALOG_SCHEMA and previous.get('sourceKey') == key:
        ctx.notify('inventory', 'DOOM Eternal is unchanged since the last scan', 100)
        return previous
    entries = entries_of(game)
    found = owners(game, entries, ctx, key)
    clips = {}
    for anim, (skeleton, _) in found.items():
        if is_character(skeleton) and ('skeleton', skeleton) in entries and ('anim', anim) in entries:
            clips.setdefault(skeleton, []).append(anim)
    names = unique_names(clips)
    # The list shows the character field; the skeleton's path stays its id.
    characters = [dict(id=skeleton, character=names[skeleton], name=names[skeleton],
                       archives=sorted({str(entries[('anim', a)].path) for a in anims}), inventoried=False, count=len(anims),
                       ready=sum(1 for a in anims if not found[a][1] & md6.ADDITIVE),
                       bytes=sum(entries[('anim', a)].size for a in anims), skeleton=skeleton)
                  for skeleton, anims in sorted(clips.items(), key=lambda item: names[item[0]].lower())]
    ctx.notify('inventory', f'Found {len(characters)} characters with animations', 95)
    return dict(schema=CATALOG_SCHEMA, game=GAME, folder=str(root), characters=characters, clips=[], sourceKey=key)


def inventory(catalog, character, ctx):
    entry = next((c for c in catalog['characters'] if c['id'] == character), None)
    if not entry:
        raise ValueError(f'{character} has no animations in this source.')
    game = game_of(catalog['folder'])
    entries = entries_of(game)
    found = owners(game, entries, ctx, catalog.get('sourceKey'))
    clips = []
    owned = [anim for anim, (skeleton, _) in found.items() if skeleton == entry['id'] and ('anim', anim) in entries]
    names = clip_names(owned, entry['id'])
    for anim in owned:
        issues = [ADDITIVE_ISSUE] if found[anim][1] & md6.ADDITIVE else []
        clips.append(dict(id=anim, name=names[anim], character=entry['name'], characterKey=entry['id'],
                          game=GAME, ready=not issues, issues=issues, archive=str(entries[('anim', anim)].path),
                          member=anim, path=anim))
    clips.sort(key=lambda c: c['name'])
    catalog['clips'] = [c for c in catalog['clips'] if c['characterKey'] != entry['id']] + clips
    entry.update(inventoried=True, count=len(clips), ready=sum(1 for c in clips if c['ready']))
    return catalog


def selection(catalog, clip_id, preset, ctx):
    clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
    if not clip:
        raise ValueError('Choose an animation from the scanned source.')
    if clip['issues']:
        raise ValueError('\n'.join(clip['issues']))
    return dict(animation=clip['path'], archive=clip['archive'], skeleton=clip['characterKey'], root=catalog['folder'],
                game=GAME, character=clip['character'], clipName=clip['name'], layout='game', preset='npc',
                parts=model_parts(catalog, clip['characterKey'], ctx))


def preview_key(selection, ctx):
    """The preview changes with the archive that holds the clip and with this package's readers."""
    archive = selection.get('archive', '')
    code = [signature(p) for p in sorted(Path(__file__).parent.glob('*.py'))]
    return json.dumps([selection.get('animation'), selection.get('skeleton'), archive,
                       signature(archive) if archive and Path(archive).is_file() else '', code])


def validate(catalog, folder, check_sources, ctx):
    if catalog.get('schema') != CATALOG_SCHEMA:
        raise ValueError('This scan was made by an older version of the DOOM Eternal package. Scan the source again.')
    if check_sources and catalog.get('sourceKey') != source_key(game_of(catalog['folder'])):
        raise ValueError('DOOM Eternal changed since the last scan, probably by an update. Scan the source again.')


def motion(selection, ctx, notes=None):
    """Motion JSON version 2 of the selected clip, sampled at every frame, in id Tech space.

    Notes for the user, such as a clip converted from game units, are added to notes."""
    game = game_of(selection['root'])
    entries = entries_of(game)
    anim_entry = entries.get(('anim', selection['animation']))
    skeleton_entry = entries.get(('skeleton', selection['skeleton']))
    if anim_entry is None or skeleton_entry is None:
        raise ValueError(f"{selection['clipName']} is no longer in the game's archives. Scan the source again.")
    skeleton = md6.read_skeleton(game.read(skeleton_entry))
    _, anim = md6.read_animation(game.read(anim_entry), skeleton)
    if anim.frame_count < 1:
        raise ValueError(f"{selection['clipName']} has no frames.")
    scale = anim.unit_scale()
    if scale != 1.0:
        anim.scale_translations(scale)
        if notes is not None:
            notes.append(UNIT_NOTE)
    names = unique_bone_names(skeleton.names)
    tracks = anim.bones()
    samples = np.empty((anim.frame_count, len(tracks), 10))
    for column, bone in enumerate(tracks):
        rotations = anim.sample('r', bone, skeleton.rotations[bone])
        # Keep each rotation in the hemisphere of the frame before, so Blender interpolates the short way.
        signs = np.sign(np.cumprod(np.where((rotations[1:] * rotations[:-1]).sum(1) < 0, -1.0, 1.0)))
        rotations[1:] *= signs[:, None]
        samples[:, column, 0:3] = anim.sample('t', bone, skeleton.translations[bone])
        samples[:, column, 3:7] = rotations
        samples[:, column, 7:10] = anim.sample('s', bone, skeleton.scales[bone])
    skeleton, move, size = md6.without_bind_scale(skeleton)
    samples[:, :, 0:3] *= move[tracks][None, :, None]
    samples[:, :, 7:10] *= size[tracks][None, :, None]
    samples = np.round(samples, 6).tolist()
    frames = [[dict(translation=s[0:3], rotation=s[3:7], scale=s[7:10]) for s in frame] for frame in samples]
    bones = [dict(index=i, name=names[i], parent=skeleton.parents[i], translation=_list(skeleton.translations[i]),
                  rotation=_list(skeleton.rotations[i]), scale=_list(skeleton.scales[i])) for i in range(len(skeleton))]
    skeleton_name = selection['skeleton'].rsplit('/', 1)[-1]
    document = dict(format='sekiro-animation-bridge', clip=selection['animation'].rsplit('/', 1)[-1],
                    skeletonName=skeleton_name, skeleton=dict(name=skeleton_name, boneCount=len(bones), bones=bones),
                    frameCount=anim.frame_count, frameRate=anim.frame_rate,
                    duration=(anim.frame_count - 1) / anim.frame_rate if anim.frame_rate else 0.0,
                    trackCount=len(tracks), trackBoneIndices=tracks, trackNames=[names[b] for b in tracks],
                    frames=frames, compression='md6anim', blockCount=0, rootMotion=None, rootUp=None, rootForward=None)
    document = with_source(document, ctx.profile(GAME).space(), GAME, GAME, 'resources', version=anim_entry.version,
                           archive=str(anim_entry.path), member=selection['animation'])
    return check_motion(dict(document, game=GAME), f"{selection['clipName']}")


def unique_bone_names(names):
    seen, result = {}, []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if not count else f'{name}.{count:03d}')
    return result


def _list(values):
    return [round(float(v), 6) for v in values]


def preview(selection, ctx):
    return motion(selection, ctx)


def prepare(request, catalog, temp, ctx):
    clip_id = request.get('assetClip', '')
    read = None
    if not any(c['id'] == clip_id for c in catalog['clips']):
        character = request.get('assetCharacter') or ''
        if not character:
            found = owners(game_of(catalog['folder']), entries_of(game_of(catalog['folder'])), ctx, catalog.get('sourceKey'))
            character = (found.get(clip_id) or [''])[0]
        catalog = read = inventory(catalog, character, ctx)
    chosen = selection(catalog, clip_id, request.get('preset', 'auto'), ctx)
    requested = request.get('game', 'auto')
    if requested not in ('', 'auto', GAME):
        raise ValueError('The selected clip belongs to a different game. Choose Auto detect or DOOM Eternal.')
    ctx.notify('decode', 'Reading the animation and its skeleton', 15)
    notes = []
    document = motion(chosen, ctx, notes)
    path = Path(temp) / 'motion.json'
    write_json(path, document)
    report = dict(clip=chosen['clipName'], frames=document['frameCount'], tracks=document['trackCount'],
                  game=ctx.profile(GAME).name, compression='md6anim', parts=0, textures=0, warnings=notes)
    chosen_models = request.get('models') or [p['path'] for p in chosen['parts'] if p['selected']]
    manifests = []
    if request.get('includeCharacter', True) and chosen_models:
        from . import characters
        ctx.notify('character', 'Reading the model, its skin and materials', 32)
        game = game_of(chosen['root'])
        manifest = characters.prepare_character(game, entries_of(game), chosen_models, Path(temp) / 'character',
                                                ctx.profile(GAME), ctx)
        character = json.loads(manifest.read_text(encoding='utf-8'))
        report.update(parts=len(character['models']), textures=character['texture_count'],
                      warnings=report['warnings'] + character['warnings'],
                      vertices=sum(m['stats']['vertices'] for m in character['models']),
                      triangles=sum(m['stats']['triangles'] for m in character['models']))
        manifests.append(manifest)
    return dict(motion=path, characters=manifests, report=report, catalog=read,
                request=dict(game=GAME, animation=chosen['animation']))
