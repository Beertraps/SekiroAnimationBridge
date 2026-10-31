"""Additive clips: changes that the game puts on top of the pose below them, not a pose of their own.

A motion JSON with an `additive` object holds such changes in `frames` (docs/INTERCHANGE.md). Havok's blendHint 1
(ADDITIVE_DEPRECATED, SoulsAssetPipeline's ADDITIVE_PARENT_SPACE) applies a change D to a pose B as Havok's
hkQsTransform product D * B, per bone and in the bone's parent space:

    translation = D.t + D.r * B.t      rotation = D.r * B.r      scale = D.s * B.s

so a clip that was made from a pose A on a base B holds D = A * B^-1:

    rotation = A.r * B.r^-1            translation = A.t - rotation * B.t      scale = A.s / B.s

Sekiro's additive clips follow this (docs/LAYERED_ANIMATIONS.md, 2026-10-31). Their translations are B.t - D.r * B.t on
every bone of constant length, which only D = A * B^-1 gives. blendHint 2 (child space, B * D) is Havok's newer form;
no Sekiro clip uses it, and its formula here is *inferred* from Havok's names.

DOOM Eternal's additive md6 clips keep the three parts apart ('separate', docs/games/doom_eternal.md, 2026-10-31):

    translation = B.t + D.t            rotation = D.r * B.r      scale = D.s * B.s

Five first-person idle clips are their normal idle minus its first frame in this form, to the rotations' precision.

Samples are dictionaries with `translation` [3], `rotation` [x, y, z, w] and `scale` [3], in source space. This module
has no dependencies, so the bridge, Blender's Python and the tests use the same arithmetic.
"""
from __future__ import annotations

SPACES = {1: 'parent', 2: 'child'}
BLEND_HINTS = {space: hint for hint, space in SPACES.items()}
SEPARATE = 'separate'


def multiply(a, b):
    """The Hamilton product a * b of two quaternions [x, y, z, w]: b turns first, then a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def inverse(q):
    """The inverse of a quaternion; its conjugate when it has unit length."""
    x, y, z, w = q
    norm = x * x + y * y + z * z + w * w or 1.0
    return [-x / norm, -y / norm, -z / norm, w / norm]


def rotate(q, v):
    """A vector turned by a unit quaternion."""
    x, y, z, w = q
    # v + 2 u x (u x v + w v), with u the vector part.
    cx, cy, cz = y * v[2] - z * v[1] + w * v[0], z * v[0] - x * v[2] + w * v[1], x * v[1] - y * v[0] + w * v[2]
    return [v[0] + 2 * (y * cz - z * cy), v[1] + 2 * (z * cx - x * cz), v[2] + 2 * (x * cy - y * cx)]


def normalized(q):
    length = sum(value * value for value in q) ** 0.5 or 1.0
    return [value / length for value in q]


def sample(translation, rotation, scale):
    return dict(translation=[float(v) for v in translation], rotation=[float(v) for v in rotation],
                scale=[float(v) for v in scale])


def space_of(motion):
    """'parent', 'child' or 'separate' for an additive motion, None for a normal one."""
    additive = motion.get('additive') if motion else None
    if not additive:
        return None
    space = additive.get('space') or SPACES.get(int(additive.get('blendHint', 1)))
    if space not in ('parent', 'child', SEPARATE):
        raise ValueError(f'Unknown additive space: {space!r}.')
    return space


def havok_space(space):
    """The space an HKX export writes a change in. Havok has no separate form, so such a change is written in the
    parent space: the same pose on the same base."""
    return space if space in BLEND_HINTS else 'parent'


def compose(change, base, space='parent'):
    """The pose that a change gives on a base pose, as the game composes them."""
    d, b = change, base
    # Decoded rotations are unit length only to their compression's precision.
    turn, rest = normalized(d['rotation']), normalized(b['rotation'])
    if space == SEPARATE:
        rotation = multiply(turn, rest)
        translation = [b['translation'][i] + d['translation'][i] for i in range(3)]
    elif space == 'parent':
        rotation = multiply(turn, rest)
        moved = rotate(turn, b['translation'])
        translation = [d['translation'][i] + moved[i] for i in range(3)]
    else:
        rotation = multiply(rest, turn)
        moved = rotate(rest, d['translation'])
        translation = [b['translation'][i] + moved[i] for i in range(3)]
    return sample(translation, normalized(rotation), [d['scale'][i] * b['scale'][i] for i in range(3)])


def difference(pose, base, space='parent'):
    """The change that turns a base pose into this pose: compose(difference(pose, base), base) == pose."""
    p, b = pose, base
    posed, rest = normalized(p['rotation']), normalized(b['rotation'])
    if space == SEPARATE:
        rotation = normalized(multiply(posed, inverse(rest)))
        translation = [p['translation'][i] - b['translation'][i] for i in range(3)]
    elif space == 'parent':
        rotation = normalized(multiply(posed, inverse(rest)))
        moved = rotate(rotation, b['translation'])
        translation = [p['translation'][i] - moved[i] for i in range(3)]
    else:
        turn = inverse(rest)
        rotation = normalized(multiply(turn, posed))
        translation = rotate(turn, [p['translation'][i] - b['translation'][i] for i in range(3)])
    # A bone the base scales to nothing has no change to give; it keeps the base's scale.
    scale = [p['scale'][i] / b['scale'][i] if abs(b['scale'][i]) > 1e-8 else 1.0 for i in range(3)]
    return sample(translation, rotation, scale)


def rest_pose(motion):
    """Each bone's rest transform, the base that Blender shows an additive clip on by default."""
    return [sample(bone['translation'], bone['rotation'], bone['scale']) for bone in motion['skeleton']['bones']]


def base_frame(base, time):
    """The frame of a base clip at a time in seconds. The base repeats from its start when the clip runs longer,
    as Havok loops a clip: its last frame is its first again."""
    count = len(base['frames'])
    index = max(0, round(float(time) * float(base['frameRate'])))
    return index % (count - 1) if count > 1 else 0


def base_pose(motion, time, rest=None):
    """Each bone's base transform at a time in seconds: the base clip's frame where it has a track, else the rest pose."""
    pose = list(rest or rest_pose(motion))
    base = (motion.get('additive') or {}).get('base')
    if base:
        frame = base['frames'][base_frame(base, time)]
        for track, bone in enumerate(base['trackBoneIndices']):
            if 0 <= int(bone) < len(pose):
                pose[int(bone)] = frame[track]
    return pose


def base_tracks(motion):
    """The bones that the base clip moves, as indices; none for the rest pose."""
    base = (motion.get('additive') or {}).get('base')
    count = len(motion['skeleton']['bones'])
    return {int(bone) for bone in base['trackBoneIndices'] if 0 <= int(bone) < count} if base else set()


def posed_frames(motion):
    """The clip's frames composed onto its base: what the game shows when nothing else plays below it."""
    space = space_of(motion)
    if space is None:
        return motion['frames']
    rest = rest_pose(motion)
    rate = float(motion['frameRate'])
    tracks = [int(bone) for bone in motion['trackBoneIndices']]
    result = []
    for index, frame in enumerate(motion['frames']):
        base = base_pose(motion, index / rate, rest)
        result.append([compose(change, base[bone], space) if 0 <= bone < len(base) else change
                       for change, bone in zip(frame, tracks)])
    return result


def base_clip(motion):
    """The part of a decoded normal clip that an additive clip keeps as its base."""
    if motion.get('additive'):
        raise ValueError(f"{motion['clip']} is an additive clip itself. Choose a normal clip as the base.")
    return dict(clip=motion['clip'], frameRate=float(motion['frameRate']),
                trackBoneIndices=[int(bone) for bone in motion['trackBoneIndices']], frames=motion['frames'])
