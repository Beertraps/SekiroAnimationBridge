"""Additive clips on an owned synthetic rig: Blender shows them on their base and export takes the same base off.

Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.py.
"""
import copy
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_bridge import import_motion, export_motion
from games import additive

COUNT = 9


def turn(axis, degrees):
    half = math.radians(degrees) / 2
    return [v * math.sin(half) for v in axis] + [math.cos(half)]


def bone(index, name, parent, translation, rotation=(0, 0, 0, 1)):
    return dict(index=index, name=name, parent=parent, translation=list(translation), rotation=list(rotation),
                scale=[1, 1, 1])


def sample(translation, rotation=(0, 0, 0, 1)):
    return dict(translation=list(translation), rotation=list(rotation), scale=[1, 1, 1])


# Turned rest bones, so a change in parent space and one in the bone's own space differ.
bones = [bone(0, 'Master', -1, [0, 0, 0]), bone(1, 'Pelvis', 0, [0, 1, 0], turn((0, 1, 0), 90)),
         bone(2, 'Spine', 1, [0, .3, 0], turn((1, 0, 0), 15)), bone(3, 'Head', 2, [0, .4, 0], turn((0, 0, 1), -20))]
NAMES = [b['name'] for b in bones]


def motion_of(frames, tracks, **extra):
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip='owned_add.hkx', skeletonName='Owned',
                game='sekiro', skeleton=dict(name='Owned', boneCount=len(bones), bones=copy.deepcopy(bones)),
                frameCount=len(frames), frameRate=30, duration=(len(frames) - 1) / 30, trackCount=len(tracks),
                trackBoneIndices=list(tracks), trackNames=[NAMES[i] for i in tracks], frames=frames, rootMotion=None,
                rootUp=None, rootForward=None, **extra)


# The flinch: Pelvis shifts and turns, Spine bends, and both come back. Master's track holds no change.
changes = []
for f in range(COUNT):
    amount = math.sin(math.pi * f / (COUNT - 1))
    changes.append([sample([0, 0, 0]), sample([.05 * amount, 0, .02 * amount], turn((0, 0, 1), 25 * amount)),
                    sample([0, 0, 0], turn((1, 0, 0), -35 * amount))])
# The base clip moves Pelvis and Head, which the additive clip has no track for. It is shorter, so it repeats.
base = dict(clip='owned_base.hkx', frameRate=30.0, trackBoneIndices=[1, 3],
            frames=[[sample([0, 1 + .02 * k, 0], additive.multiply(turn((1, 0, 0), 10 * k), bones[1]['rotation'])),
                     sample([0, .4, 0], additive.multiply(turn((0, 1, 0), 15 * k), bones[3]['rotation']))]
                    for k in (0, 1, 2, 0)])


def close(a, b, tolerance=1e-4):
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


def same_rotation(a, b, tolerance=1e-5):
    return abs(Quaternion((a[3], *a[:3])).dot(Quaternion((b[3], *b[:3])))) > 1 - tolerance


def same_sample(a, b):
    return close(a['translation'], b['translation']) and same_rotation(a['rotation'], b['rotation']) and close(
        a['scale'], b['scale'])


def poses(rig):
    """Every bone's armature-space matrix on every frame, as Blender shows the scene."""
    result = []
    for frame in range(1, COUNT + 1):
        bpy.context.scene.frame_set(frame)
        result.append([rig.pose.bones[name].matrix.copy() for name in NAMES])
    return result


def same_poses(a, b, tolerance=1e-4):
    return max(abs(m[r][c] - n[r][c]) for fa, fb in zip(a, b) for m, n in zip(fa, fb) for r in range(4)
               for c in range(4)) < tolerance


def fresh(motion):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return import_motion(motion)


def export(temp, name, **options):
    path = Path(temp) / (name + '.motion.json')
    summary = export_motion(path, **options)
    return json.loads(path.read_text(encoding='utf-8')), summary


def bend_spine(rig, frame=5, degrees=20):
    spine = rig.pose.bones['Spine']
    bpy.context.scene.frame_set(frame)
    spine.rotation_quaternion = Quaternion((0, 0, 1), math.radians(degrees)) @ spine.rotation_quaternion
    spine.keyframe_insert('rotation_quaternion', frame=frame)


def expect_error(text, **options):
    with tempfile.TemporaryDirectory() as temp:
        try:
            export(temp, 'refused', **options)
        except RuntimeError as error:
            assert text in str(error), str(error)
        else:
            raise AssertionError('Export did not refuse: ' + text)


with tempfile.TemporaryDirectory() as temp:
    for with_base in (False, True):
        clip = motion_of(copy.deepcopy(changes), [0, 1, 2],
                         additive=dict(blendHint=1, space='parent', **(dict(base=base) if with_base else {})))
        # The same poses as a normal clip: the changes composed on the base, and the bones only the base moves.
        rest = additive.rest_pose(clip)
        composed = [row + [additive.base_pose(clip, f / 30, rest)[3]]
                    for f, row in enumerate(additive.posed_frames(clip))]
        normal = motion_of(composed, [0, 1, 2, 3])

        normal_rig = fresh(normal)
        expected = poses(normal_rig)
        bend_spine(normal_rig)
        bent_normal = export(temp, 'bent_normal')[0]

        rig = fresh(clip)
        assert rig.get('sekiro_additive') == 'parent', dict(rig)
        assert same_poses(poses(rig), expected), f'The additive clip does not show on its base (base: {with_base})'

        # Unchanged, export gives the clip's own changes back, with the same additive object.
        result, summary = export(temp, f'unchanged_{with_base}')
        assert result['trackBoneIndices'] == [0, 1, 2] and result['frameCount'] == COUNT
        assert result['additive']['blendHint'] == 1 and result['additive']['space'] == 'parent'
        assert (result['additive'].get('base') or {}).get('clip') == ('owned_base.hkx' if with_base else None)
        assert result['rootMotion'] is None
        for f in range(COUNT):
            for track in range(3):
                assert same_sample(result['frames'][f][track], changes[f][track]), (with_base, f, track)
        assert summary['additive']['space'] == 'parent'

        # An edit is written as the change from the same base.
        bend_spine(rig)
        edited = export(temp, f'edited_{with_base}')[0]
        for f in range(COUNT):
            base_pose = additive.base_pose(clip, f / 30, rest)
            for track in range(3):
                wanted = additive.difference(bent_normal['frames'][f][track], base_pose[track])
                assert same_sample(edited['frames'][f][track], wanted), (with_base, f, track)
        assert not same_sample(edited['frames'][4][2], changes[4][2]), 'The edit is missing'

        # No root motion, and no second base.
        expect_error('cannot carry root motion', root_motion='object')
        expect_error('additive clip already', additive='rest')

    # A normal clip written as an additive clip: its changes to the rest pose or to its first exported frame.
    plain = motion_of(copy.deepcopy(composed), [0, 1, 2, 3])
    fresh(plain)
    rest = additive.rest_pose(plain)
    to_rest = export(temp, 'to_rest', additive='rest')[0]
    assert to_rest['additive'] == dict(blendHint=1, space='parent'), to_rest['additive']
    first = export(temp, 'to_first', additive='first-frame')[0]
    assert first['additive']['base']['frames'] and len(first['additive']['base']['frames']) == 1
    for f in range(COUNT):
        for track, index in enumerate(plain['trackBoneIndices']):
            assert same_sample(to_rest['frames'][f][track], additive.difference(composed[f][track], rest[index])), (f, track)
            assert same_sample(first['frames'][f][track], additive.difference(composed[f][track], composed[0][track]))
    for track in range(4):
        assert same_sample(first['frames'][0][track], sample([0, 0, 0])), track
    # Both read back onto their bases as the clip they came from.
    for written in (to_rest, first):
        for f, row in enumerate(additive.posed_frames(dict(plain, **{k: written[k] for k in ('frames', 'additive')}))):
            for track in range(4):
                assert same_sample(row[track], composed[f][track]), (f, track)
    expect_error('root motion', additive='rest', root_motion='bone')

    # DOOM Eternal's form, each part on its own, shows on its base the same way. Havok has no such form, so export
    # writes the changes in Havok's parent space, which gives the same pose on the same base.
    separate = motion_of(copy.deepcopy(changes), [0, 1, 2], additive=dict(space='separate', base=base))
    rest = additive.rest_pose(separate)
    on_base = [row + [additive.base_pose(separate, f / 30, rest)[3]] for f, row in enumerate(additive.posed_frames(separate))]
    assert not same_sample(on_base[4][1], composed[4][1]), 'The separate parts compose as the parent space does'
    expected = poses(fresh(motion_of(on_base, [0, 1, 2, 3])))
    rig = fresh(separate)
    assert rig.get('sekiro_additive') == 'separate', dict(rig)
    assert same_poses(poses(rig), expected), 'The separate clip does not show on its base'
    result, summary = export(temp, 'separate')
    assert result['additive']['blendHint'] == 1 and result['additive']['space'] == 'parent', result['additive']
    assert result['additive']['base']['clip'] == 'owned_base.hkx'
    assert summary['additive'] == {'space': 'parent', 'base': 'owned_base.hkx', 'from': 'separate'}, summary['additive']
    for f in range(COUNT):
        base_pose = additive.base_pose(separate, f / 30, rest)
        for track in range(3):
            assert same_sample(result['frames'][f][track], additive.difference(on_base[f][track], base_pose[track])), (f, track)
    for f, row in enumerate(additive.posed_frames(dict(separate, **{k: result[k] for k in ('frames', 'additive')}))):
        for track in range(3):
            assert same_sample(row[track], on_base[f][track]), (f, track)

print('blender_additive: additive clips show on their base and export takes it off again: passed')
