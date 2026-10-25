"""Skeleton preview of a clip for the bridge UI, and the part clips that play with it.

The HKX decoder reads the clip; each bone's world position per frame is sent to
the page in game space (Y up), rounded to 0.1 mm, with the root motion. Nothing is
written beside the inputs: decoded files go to a temporary folder, and results are
cached in the bridge's work folder by input file and decoder.
"""
from __future__ import annotations
import hashlib
import json
import math
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


def multiply(a, b):
    return tuple(tuple(a[r][0] * b[0][c] + a[r][1] * b[1][c] + a[r][2] * b[2][c] + (a[r][3] if c == 3 else 0)
                       for c in range(4)) for r in range(3))


def joint_positions(motion):
    """World positions of every bone per frame, flattened as x, y, z per bone."""
    bones = motion['skeleton']['bones']
    parents = [int(bone['parent']) for bone in bones]
    rest = [matrix(bone) for bone in bones]
    tracks = [int(index) for index in motion['trackBoneIndices']]
    frames = []
    for frame in motion['frames']:
        local = list(rest)
        for track, index in enumerate(tracks):
            local[index] = matrix(frame[track])
        worlds, flat = [], []
        for index, parent in enumerate(parents):
            world = multiply(worlds[parent], local[index]) if parent >= 0 else local[index]
            worlds.append(world)
            flat += (round(world[0][3], 4), round(world[1][3], 4), round(world[2][3], 4))
        frames.append(flat)
    return frames


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


def preview(selection, decoder, cache, oodle=''):
    """Joint positions of a clip for the UI's skeleton preview, cached by its inputs."""
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
            return json.loads(stored.read_text(encoding='utf-8'))
        except ValueError:
            pass
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
