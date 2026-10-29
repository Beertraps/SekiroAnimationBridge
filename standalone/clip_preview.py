"""Skeleton preview of a clip for the bridge UI, and the part clips that play with it.

The part view asks the other way round: the clips of a Sekiro weapon part, each
with the player clips that it plays with.

The HKX decoder reads the clip; each bone's world position per frame is sent to
the page in game space (Y up), rounded to 0.1 mm, with the root motion. Nothing is
written beside the inputs: decoded files go to a temporary folder, and results are
cached in the bridge's work folder by input file and decoder.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

# Joint samples per preview; a longer clip keeps only every second (third, ...) frame.
LIMIT = 250_000
VERSION = 2
_OODLE = []


def use_oodle(path=''):
    """Load the Oodle library once per UI session (and again if Setup names another DLL)."""
    if _OODLE != [path]:
        from dcx_codec import configure_oodle
        configure_oodle(path)
        _OODLE[:] = [path]


def matrix(sample):
    """Rows of the 3x4 matrix of a decoder sample: rotation (x, y, z, w) and scale, then translation."""
    x, y, z, w = sample['rotation']
    sx, sy, sz = sample['scale']
    tx, ty, tz = sample['translation']
    return ((sx * (1 - 2 * (y * y + z * z)), sy * 2 * (x * y - z * w), sz * 2 * (x * z + y * w), tx),
            (sx * 2 * (x * y + z * w), sy * (1 - 2 * (x * x + z * z)), sz * 2 * (y * z - x * w), ty),
            (sx * 2 * (x * z - y * w), sy * 2 * (y * z + x * w), sz * (1 - 2 * (x * x + y * y)), tz))


def matrices(rotation, scale, translation):
    """matrix() for arrays of samples: (..., 4), (..., 3) and (..., 3) give (..., 3, 4)."""
    import numpy as np
    x, y, z, w = np.moveaxis(rotation, -1, 0)
    sx, sy, sz = np.moveaxis(scale, -1, 0)
    tx, ty, tz = np.moveaxis(translation, -1, 0)
    rows = ((sx * (1 - 2 * (y * y + z * z)), sy * 2 * (x * y - z * w), sz * 2 * (x * z + y * w), tx),
            (sx * 2 * (x * y + z * w), sy * (1 - 2 * (x * x + z * z)), sz * 2 * (y * z - x * w), ty),
            (sx * 2 * (x * z - y * w), sy * 2 * (y * z + x * w), sz * (1 - 2 * (x * x + y * y)), tz))
    return np.stack([np.stack(row, axis=-1) for row in rows], axis=-2)


def joint_positions(motion):
    """World positions of every bone per frame, flattened as x, y, z per bone.

    All frames are composed at once, one bone at a time down the hierarchy.
    """
    import numpy as np
    bones = motion['skeleton']['bones']
    parents = [int(bone['parent']) for bone in bones]
    tracks = [int(index) for index in motion['trackBoneIndices']]
    frames = motion['frames']
    if not frames:
        return []
    rest = matrices(*(np.array([bone[key] for bone in bones], dtype=float) for key in ('rotation', 'scale', 'translation')))
    local = np.repeat(rest[None], len(frames), axis=0)
    if tracks:
        local[:, tracks] = matrices(*(np.array([[sample[key] for sample in frame] for frame in frames], dtype=float)
                                      for key in ('rotation', 'scale', 'translation')))
    world = np.empty_like(local)
    for index, parent in enumerate(parents):
        if parent < 0:
            world[:, index] = local[:, index]
            continue
        above = world[:, parent]
        world[:, index, :, :3] = above[:, :, :3] @ local[:, index, :, :3]
        world[:, index, :, 3] = np.einsum('fij,fj->fi', above[:, :, :3], local[:, index, :, 3]) + above[:, :, 3]
    return np.round(world[:, :, :, 3], 4).reshape(len(frames), -1).tolist()


def detached(positions, count):
    """Bones that a frame places far from the rest of the skeleton, such as Wolf's camera dummy 4 m away.

    The preview leaves them out, so that the body fills the view.
    """
    import numpy as np
    points = np.asarray(positions, dtype=float).reshape(len(positions), count, 3)
    spans = np.linalg.norm(points - np.median(points, axis=1, keepdims=True), axis=2).max(axis=0)
    return [int(index) for index in np.flatnonzero(spans > max(4 * float(np.median(spans)), .5))]


def cache_key(paths, decoder):
    parts = [VERSION, str(decoder)]
    for path in (decoder, *paths):
        if path and Path(path).is_file():
            stat = Path(path).stat()
            parts += [str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns]
        else:
            parts.append(str(path))
    return hashlib.sha1(json.dumps(parts).encode('utf-8')).hexdigest()[:24]


def decode(paths, decoder, oodle=''):
    """Decode a clip with its skeleton into the bridge's motion JSON, through a temporary folder."""
    animation, skeleton, compendium, skeleton_compendium = paths
    with tempfile.TemporaryDirectory(prefix='SekiroBridgePreview-') as scratch:
        temp = Path(scratch)
        inputs = []
        for path, name in ((animation, 'clip.hkx'), (skeleton, 'skeleton.hkx')):
            data = Path(path).read_bytes()
            if data[:4] in (b'DCX\0', b'DCP\0'):
                from dcx_codec import unwrap
                use_oodle(oodle)
                data = unwrap(data)[0]
            (temp / name).write_bytes(data)
            inputs.append(temp / name)
        output = temp / 'motion.json'
        args = [decoder, inputs[0], compendium or '-', inputs[1], output] + ([skeleton_compendium] if skeleton_compendium else [])
        run = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode or not output.is_file():
            lines = [line for line in (run.stdout + '\n' + run.stderr).splitlines() if line.strip()]
            raise ValueError('The decoder could not read this clip for the preview' + (': ' + lines[-1] if lines else '.'))
        return json.loads(output.read_text(encoding='utf-8-sig'))


def preview(selection, decoder, cache, oodle='', stored_only=False):
    """Joint positions of a clip for the UI's skeleton preview, cached by its inputs.

    With stored_only, only a cached preview is returned, and None when there is none.
    """
    paths = [selection.get(key, '') for key in ('animation', 'skeleton', 'compendium', 'skeletonCompendium')]
    for path, label in ((paths[0], 'animation'), (paths[1], 'skeleton')):
        if not path or not Path(path).is_file():
            raise ValueError(f'Choose the {label} first.')
    for path in paths[2:]:
        if path and not Path(path).is_file():
            raise ValueError(f'Compendium not found: {path}')
    if not decoder or not Path(decoder).is_file():
        raise ValueError('The HKX decoder is missing. Open Setup to choose it.')
    cache = Path(cache)
    stored = cache / (cache_key(paths, decoder) + '.json')
    if stored.is_file():
        try:
            result = json.loads(stored.read_text(encoding='utf-8'))
            # Cache cleanup removes the previews shown least recently first.
            os.utime(stored)
            return result
        except (OSError, ValueError):
            pass
    if stored_only:
        return None
    motion = decode(paths, decoder, oodle)
    bones = motion['skeleton']['bones']
    count = int(motion['frameCount'])
    step = max(1, math.ceil(count * len(bones) / LIMIT))
    positions = joint_positions(dict(motion, frames=motion['frames'][::step]))
    root = motion.get('rootMotion')
    result = dict(clip=Path(paths[0]).name, skeleton=motion['skeletonName'], frameCount=count,
                  frameRate=float(motion['frameRate']), duration=float(motion.get('duration') or (count - 1) / float(motion['frameRate'])),
                  frameStep=step, bones=[bone['name'] for bone in bones], parents=[int(bone['parent']) for bone in bones],
                  tracks=len(motion['trackBoneIndices']), positions=positions, detached=detached(positions, len(bones)),
                  root=[[round(float(v), 4) for v in sample[:4]] for sample in root[::step]] if root else None)
    cache.mkdir(parents=True, exist_ok=True)
    staging = stored.with_suffix('.tmp')
    staging.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    staging.replace(stored)
    return result


def part_rows(catalog, clip_id, animation, models, oodle=''):
    """The clip each selected animated weapon part plays with a character clip, for the UI.

    With a source catalog the character's TAE adds the IDs that share a body clip;
    for individual files only the same ID and the part's own TAE pair a clip.
    """
    from part_animations import character_binder, character_tae, plan
    use_oodle(oodle)
    character, tae = '', {}
    if catalog is not None:
        clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
        if clip is None:
            raise ValueError('Choose an animation from the scanned source.')
        animation, character = clip['name'], clip.get('character', '')
        tae = character_tae(character_binder(catalog, clip))
    rows = plan(models, Path(animation).name, tae, character)
    return dict(clip=Path(animation).name, character=character, tae=bool(tae),
                parts=[{k: row[k] for k in ('name', 'binder', 'member', 'id', 'reason', 'rest')} for row in rows])


def sekiro_parts(catalog):
    """A source's weapon parts from Sekiro, the only game whose part clips the part view pairs.

    A structured source with Auto detect learns its game when the player is read.
    """
    from part_animations import PLAYER, WEAPON
    player = next((c for c in catalog.get('characters', []) if c.get('id') == PLAYER), {})
    fallback = (player.get('game') or '') if catalog.get('layout') in ('game', 'custom') else ''
    return [p for p in catalog.get('parts', []) if WEAPON.fullmatch(p['id']) and (p.get('game') or fallback) == 'sekiro']


def animated_parts(catalog, oodle=''):
    """The Sekiro weapon parts of a source that hold animated models, for the UI's part view."""
    from part_animations import REST, WEAPON, part_binders
    use_oodle(oodle)
    parts, notices, read = [], [], 0
    for part in sekiro_parts(catalog):
        path = Path(part['path'])
        if not path.is_file():
            continue
        read += 1
        try:
            binders = part_binders(path)
        except Exception as exc:
            notices.append(f'{path.name}: {exc}')
            continue
        models = [dict(model=model, name=model.upper(), clips=sum(ident != REST for ident in binder['clips']))
                  for model, binder in sorted(binders.items()) if WEAPON.fullmatch(model)]
        models = [m for m in models if m['clips']]
        if models:
            parts.append(dict(id=part['id'], name=part['name'], path=part['path'], role=part.get('role', ''),
                              models=models, clips=sum(m['clips'] for m in models)))
    return dict(parts=parts, notices=notices, read=read)


def part_matches(catalog, path, oodle=''):
    """Each clip of a Sekiro weapon part with the player clips it plays with, for the UI's part view.

    The part is looked up by its path in the catalog, so a request cannot name
    another file. A clip is listed under a player clip only when the import of
    that player clip keys it: the pairing is the import's, asked for every
    player clip. A collected folder pairs a part with the player clips beside it.
    """
    from part_animations import (PLAYER, REST, WEAPON, animation_id, character_binder, character_tae, clip_name,
                                 pairings, part_binders, players_of)
    part = next((p for p in sekiro_parts(catalog) if p['path'] == str(path)), None)
    if part is None:
        raise ValueError('Choose a Sekiro weapon part from the scanned source.')
    use_oodle(oodle)
    if catalog.get('layout') in ('game', 'custom'):
        entry = next((c for c in catalog['characters'] if c.get('id') == PLAYER), None)
        key, inventoried = (PLAYER, bool(entry.get('inventoried'))) if entry else ('', False)
    else:
        key, inventoried = '|'.join(('sekiro', part['scope'], PLAYER)), True
    clips = [c for c in catalog['clips'] if key and c.get('characterKey') == key and c.get('game') == 'sekiro']
    # The import reads the TAE that character_binder() finds for its clip; a source
    # whose folders hold several base archives can give clips different ones.
    found, groups = {}, {}
    for clip in clips:
        ident = animation_id(clip['name'])
        if ident is None:
            continue
        place = (tuple(clip.get('inputArchives') or ()), str(Path(clip.get('archive') or clip.get('path') or '.').parent))
        if place not in found:
            found[place] = character_binder(catalog, clip)
        groups.setdefault(found[place], {}).setdefault(ident, []).append(clip)
    taes = {binder: character_tae(binder) for binder in groups}
    players, models = {binder: players_of(tae) for binder, tae in taes.items()}, []
    for model, part_binder in sorted(part_binders(part['path']).items()):
        if not WEAPON.fullmatch(model):
            continue
        matches = {}
        for binder, bodies in groups.items():
            for ident, pairs in pairings(part_binder, bodies, taes[binder], PLAYER, players[binder]).items():
                matches.setdefault(ident, []).extend(
                    dict(clip=c['id'], name=c['name'], archive=Path(c.get('archive') or c.get('path') or '').name,
                         reason=reason, ready=bool(c.get('ready'))) for body, reason in pairs for c in bodies[body])
        rows = []
        for ident in sorted(i for i in part_binder['clips'] if i != REST):
            listed = sorted(matches.get(ident, ()), key=lambda m: (m['reason'] != 'same ID', m['name'].lower(), m['archive'].lower()))
            rows.append(dict(id=clip_name(ident), member=part_binder['clips'][ident], matches=listed))
        if rows:
            models.append(dict(model=model, name=model.upper(), binder=part_binder['binder'],
                               rest=part_binder['clips'].get(REST), clips=rows))
    return dict(part=part['id'], name=part['name'], path=part['path'], characterKey=key, character=PLAYER,
                inventoried=inventoried, playerClips=len(clips), tae=any(taes.values()), models=models)
