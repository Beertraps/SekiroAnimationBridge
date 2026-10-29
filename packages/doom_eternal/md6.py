"""DOOM Eternal's md6 skeletons (resource type skeleton) and animations (resource type anim).

Ported from Valen (https://github.com/jandk/valen, MIT, by Jan De Kock): Md6Skel, Md6Anim and
Md6AnimReader. Both formats keep local bone transforms in id Tech space: Z up, X forward, in game units.
"""
from __future__ import annotations

import struct

import numpy as np

QUATERNION_SCALE = np.sqrt(2.0) / 0x7FFF
NO_JOINT = 0xFF
# An additive animation holds changes that the game adds on top of another one, not a pose.
ADDITIVE = 0x1
# The game's unit in metres. Skeletons and almost every animation are in metres; a few dozen animations
# store their translations in game units instead: the imp's climb_up_128 climbs 128 units, 2.44 m.
GAME_UNIT = 0.01905


class Reader:
    """Little-endian reads from a bytes object, with an explicit position."""

    def __init__(self, data, position=0):
        self.data, self.position = data, position

    def take(self, size):
        if self.position + size > len(self.data):
            raise ValueError(f'The file ends at {len(self.data)} bytes; {size} more were expected at {self.position}.')
        chunk = self.data[self.position:self.position + size]
        self.position += size
        return chunk

    def array(self, dtype, count):
        dtype = np.dtype(dtype)
        return np.frombuffer(self.take(dtype.itemsize * count), dtype=dtype).copy()

    def shorts(self, count):
        return self.array('<i2', count)

    def short(self):
        return int(self.shorts(1)[0])

    def int(self):
        return struct.unpack('<i', self.take(4))[0]

    def string(self):
        size = self.int()
        if not 0 <= size < 4096:
            raise ValueError(f'A name of {size} bytes at {self.position - 4} is not plausible.')
        return self.take(size).decode('utf-8', 'replace')


class Skeleton:
    """Bone names, parents and the local rest pose of an md6 skeleton."""

    def __init__(self, names, parents, rotations, scales, translations):
        self.names, self.parents = names, parents
        self.rotations, self.scales, self.translations = rotations, scales, translations

    def __len__(self):
        return len(self.names)


def read_skeleton(data):
    reader = Reader(data, 4)  # a copy of the compressed size comes first
    size, joints, user_channels, parent_crc, base_pose, inverse_base_pose, parent_table = reader.shorts(7)
    reader.shorts(3 + 8 + 8 + 1)  # child, handle and weight tables, extra joints
    if reader.short() != 0:
        raise ValueError('This skeleton uses a remap table, which this package does not read.')
    reader.shorts(1 + 3)  # loaded data size, padding
    joints = int(joints)
    padded = joints + 7 & ~7
    rotations = reader.array('<f4', padded * 4).reshape(padded, 4)
    scales = reader.array('<f4', padded * 3).reshape(padded, 3)
    translations = reader.array('<f4', padded * 3).reshape(padded, 3)
    reader.position = int(parent_table) + 4
    parents = reader.shorts(padded)
    reader.position = int(inverse_base_pose) + 4 + padded * 48  # 3x4 inverse bind matrices, not needed
    names = [reader.string() for _ in range(padded)]
    return Skeleton(names[:joints], [int(p) for p in parents[:joints]],
                    rotations[:joints], scales[:joints], translations[:joints])


def without_bind_scale(skeleton):
    """The skeleton with every bone's bind scale 1, and the factors that carry its poses over: (skeleton, move, size).

    Blender's rest bones hold no scale, so a bone the game binds scaled (the Doom Slayer's hands, 1.2) would
    scale the skin of its children when posed. Taking each bone's uniform bind scale out keeps its bind position
    and rotation and leaves the skinning of every pose as it was: a local translation grows by the parent's bind
    scale (move), and a local scale shrinks by the bone's own over the parent's (size).
    """
    world = np.ones(len(skeleton))
    for i, parent in enumerate(skeleton.parents):  # parents come before their children
        world[i] = (world[parent] if parent >= 0 else 1.0) * float(np.mean(skeleton.scales[i]))
    move = np.array([world[p] if p >= 0 else 1.0 for p in skeleton.parents])
    size = move / world
    return (Skeleton(skeleton.names, skeleton.parents, skeleton.rotations, skeleton.scales * size[:, None],
                     skeleton.translations * move[:, None]), move, size)


def decode_quaternions(raw):
    """id Tech's 48-bit quaternions: three components in 15 bits each, the largest one left out."""
    raw = np.asarray(raw, dtype='<u2').reshape(-1, 3)
    values = (raw & 0x7FFF).astype(np.float64) * QUATERNION_SCALE - np.sqrt(0.5)
    missing = np.sqrt(np.clip(1.0 - (values * values).sum(1), 0.0, 1.0))
    index = (raw[:, 1] >> 15 & 1) << 1 | (raw[:, 0] >> 15 & 1)
    a, b, c, d = values[:, 0], values[:, 1], values[:, 2], missing
    order = {0: (a, b, c, d), 1: (b, c, d, a), 2: (c, d, a, b), 3: (d, a, b, c)}
    result = np.empty((len(raw), 4))
    for key, components in order.items():
        rows = index == key
        result[rows] = np.stack([component[rows] for component in components], 1)
    return result


def read_rle(reader):
    """A list of bone IDs, run-length encoded; NO_JOINT marks a channel without a bone."""
    size = reader.take(1)[0]
    result = []
    while len(result) < size:
        count = reader.take(1)[0]
        if count & 0x80:
            result += [NO_JOINT] * (count & 0x7F)
            continue
        value = reader.take(1)[0]
        result += range(value, value + count)
    return result[:size]


class Animation:
    """Sparse keys per bone and channel, with the skeleton they play on."""

    def __init__(self, skeleton, frame_count, frame_rate, keys):
        self.skeleton, self.frame_count, self.frame_rate = skeleton, frame_count, frame_rate
        self.keys = keys  # {'r'|'s'|'t': {bone: ([frames], [values])}}

    def bones(self):
        return sorted({bone for channel in self.keys.values() for bone in channel})

    def unit_scale(self):
        """GAME_UNIT when the translations are in game units, 1.0 when they are in metres like the skeleton.

        Bones keep their length in a clip, so the first key of each child bone's translation, divided by its
        rest length, is about 1 in metres and about 52.49 (1 / GAME_UNIT) in game units."""
        ratios = []
        for bone, (frames, values) in self.keys['t'].items():
            rest = float(np.linalg.norm(self.skeleton.translations[bone]))
            if self.skeleton.parents[bone] > 0 and rest > 0.02:
                ratios.append(float(np.linalg.norm(values[0])) / rest)
        if ratios and abs(np.median(ratios) * GAME_UNIT - 1.0) < 0.02:
            return GAME_UNIT
        return 1.0

    def scale_translations(self, factor):
        for bone, (frames, values) in self.keys['t'].items():
            self.keys['t'][bone] = (frames, [np.asarray(v) * factor for v in values])

    def sample(self, channel, bone, rest):
        """Dense values of one channel over every frame; the rest value where the clip has no keys."""
        found = self.keys[channel].get(bone)
        if not found:
            return np.repeat(np.asarray(rest, dtype=np.float64)[None], self.frame_count, 0)
        frames, values = found
        frames = np.asarray(frames, dtype=np.float64)
        values = np.asarray(values, dtype=np.float64)
        order = np.argsort(frames, kind='stable')
        frames, values = frames[order], values[order]
        keep = np.append(frames[1:] != frames[:-1], True)  # a later key at the same frame wins
        frames, values = frames[keep], values[keep]
        target = np.arange(self.frame_count, dtype=np.float64)
        upper = np.clip(np.searchsorted(frames, target, side='right'), 1, max(len(frames) - 1, 1))
        lower = upper - 1
        if len(frames) == 1:
            return np.repeat(values[:1], self.frame_count, 0)
        span = frames[upper] - frames[lower]
        t = np.clip((target - frames[lower]) / np.where(span > 0, span, 1), 0.0, 1.0)[:, None]
        if channel != 'r':
            return values[lower] + (values[upper] - values[lower]) * t
        return slerp(values[lower], values[upper], t)


def slerp(a, b, t):
    dot = (a * b).sum(1, keepdims=True)
    b = np.where(dot < 0, -b, b)
    dot = np.abs(dot)
    angle = np.arccos(np.clip(dot, -1.0, 1.0))
    sine = np.sin(angle)
    near = sine < 1e-6
    wa = np.where(near, 1 - t, np.sin((1 - t) * angle) / np.where(near, 1, sine))
    wb = np.where(near, t, np.sin(t * angle) / np.where(near, 1, sine))
    result = wa * a + wb * b
    return result / np.linalg.norm(result, axis=1, keepdims=True)


def read_header(data):
    """The skeleton name an animation plays on; reads only the start of the file."""
    return Reader(data).string()


def read_info(data):
    """(skeleton name, flags) of an animation; flags & ADDITIVE marks an additive one."""
    reader = Reader(data)
    skeleton = reader.string()
    reader.take(24 + 24 + 4 + 8 + 4 + 2)  # bounds, size, padding, total size, size
    return skeleton, reader.short() & 0xFFFF


def read_animation(data, skeleton):
    reader = Reader(data)
    skeleton_name = reader.string()
    reader.take(24 + 24 + 4)  # translated and normalized bounds, size
    start = reader.position
    if reader.take(8) != bytes(8):
        raise ValueError(f'The animation for {skeleton_name} does not start as expected.')
    reader.int()  # total size
    (_, flags, frame_count, frame_rate, frame_sets, frame_set_table, frame_set_offsets,
     const_r, const_s, const_t, const_u, _, weights, _) = reader.shorts(14)
    reader.take(12 * 4 * 2 + 8)  # start and end deltas, padding
    maps_start = reader.position
    map_count = reader.short()
    reader.shorts(map_count)  # table CRCs
    offsets = reader.shorts(8)  # the first map; later ones are for other skeleton variants
    channels = []
    for offset in offsets:
        reader.position = maps_start + int(offset)
        channels.append(read_rle(reader))
    const_r_bones, const_s_bones, const_t_bones, _, anim_r, anim_s, anim_t, _ = channels
    keys = {'r': {}, 's': {}, 't': {}}

    def constant(channel, bones, offset, rotation):
        reader.position = start + int(offset)
        values = decode_quaternions(reader.array('<u2', len(bones) * 3)) if rotation else \
            reader.array('<f4', len(bones) * 3).reshape(-1, 3).astype(np.float64)
        for bone, value in zip(bones, values):
            if bone < len(skeleton):
                keys[channel][bone] = ([0], [value])

    constant('r', const_r_bones, const_r, True)
    constant('s', const_s_bones, const_s, False)
    constant('t', const_t_bones, const_t, False)
    reader.position = start + int(frame_set_offsets)
    set_offsets = reader.array('<i4', int(frame_sets) + 1)
    for index in range(int(frame_sets)):
        base = start + int(set_offsets[index]) * 16
        reader.position = base
        header = reader.shorts(19)
        first, ranges, bits = header[0:3], header[4:7], header[8:11]
        frame_start, frame_range = int(header[17]), int(header[18])
        per_bone = frame_range + 7 >> 3
        for slot, (channel, bones) in enumerate((('r', anim_r), ('s', anim_s), ('t', anim_t))):
            rotation = channel == 'r'
            reader.position = base + int(bits[slot])
            mask = np.unpackbits(reader.array('u1', per_bone * len(bones))).reshape(len(bones), per_bone * 8)
            reader.position = base + int(first[slot])
            firsts = _values(reader, len(bones), rotation)
            reader.position = base + int(ranges[slot])
            rest = _values(reader, int(mask.sum()), rotation)
            used = 0
            for i, bone in enumerate(bones):
                set_frames = np.flatnonzero(mask[i, :frame_range])
                values = rest[used:used + len(set_frames)]
                used += len(set_frames)
                if bone >= len(skeleton):
                    continue
                frames, found = keys[channel].setdefault(bone, ([], []))
                frames.append(frame_start)
                found.append(firsts[i])
                frames.extend(int(frame_start + f) for f in set_frames)
                found.extend(values)
    return skeleton_name, Animation(skeleton, int(frame_count), float(frame_rate), keys)


def _values(reader, count, rotation):
    if rotation:
        return decode_quaternions(reader.array('<u2', count * 3))
    return reader.array('<f4', count * 3).reshape(-1, 3).astype(np.float64)
