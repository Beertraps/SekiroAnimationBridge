"""Export options on an owned synthetic rig. Run with Blender --background --factory-startup --python this_file.py."""
import sys, tempfile, json, math
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_bridge import (import_motion, export_motion, inspect_scene, extract_root_motion, action_curves,
                            trs_matrix)

COUNT = 10


def turn(axis, angle):
    s = math.sin(angle / 2)
    return [s if axis == 'x' else 0, s if axis == 'y' else 0, s if axis == 'z' else 0, math.cos(angle / 2)]


def bone(index, name, parent, translation):
    return dict(index=index, name=name, parent=parent, translation=translation, rotation=[0, 0, 0, 1], scale=[1, 1, 1])


def sample(translation, rotation=(0, 0, 0, 1)):
    return dict(translation=list(translation), rotation=list(rotation), scale=[1, 1, 1])


# Pelvis walks forward along game Z, bobs up and turns about game Y. Extra has no track.
bones = [bone(0, 'Master', -1, [0, 0, 0]), bone(1, 'Pelvis', 0, [0, 1, 0]), bone(2, 'Spine', 1, [0, .3, 0]),
         bone(3, 'Extra', 0, [.2, 0, 0]), bone(4, 'Extra child', 3, [0, .1, 0])]
frames = [[sample([0, 0, 0]), sample([0, 1 + .01 * i, .1 * i], turn('y', .1 * i)), sample([0, .3, 0], turn('x', .05 * i)),
           sample([0, .1, 0])] for i in range(COUNT)]
motion = dict(format='sekiro-animation-bridge', formatVersion=1, clip='owned.hkx', skeletonName='Owned', game='sekiro',
              skeleton=dict(name='Owned', boneCount=len(bones), bones=bones), frameCount=COUNT, frameRate=30,
              duration=(COUNT - 1) / 30, trackCount=4, trackBoneIndices=[0, 1, 2, 4],
              trackNames=['Master', 'Pelvis', 'Spine', 'Extra child'], frames=frames,
              rootMotion=[[.05 * i, 0, 0, 0] for i in range(COUNT)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


def close(a, b, tolerance=1e-4):
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


def same_rotation(a, b, tolerance=1e-4):
    return abs(Quaternion((a[3], *a[:3])).dot(Quaternion((b[3], *b[:3])))) > 1 - tolerance


def export(temp, name, **options):
    path = Path(temp) / (name + '.motion.json')
    summary = export_motion(path, **options)
    return json.loads(path.read_text()), summary


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
rig = import_motion(motion)
clip_action = rig.animation_data.action
# Key the untracked Extra bone: it turns 0.5 rad about Blender X by the last frame.
extra = rig.pose.bones['Extra']
for frame, angle in ((1, 0.0), (COUNT, .5)):
    extra.rotation_quaternion = Quaternion((1, 0, 0), angle)
    extra.keyframe_insert('rotation_quaternion', frame=frame)
assert rig.animation_data.action == clip_action, 'Keying created a new action'

with tempfile.TemporaryDirectory() as temp:
    # Defaults: scene range, source tracks, root empty.
    result, summary = export(temp, 'default')
    assert result['frameCount'] == COUNT and result['trackBoneIndices'] == [0, 1, 2, 4]
    for i in range(COUNT):
        for track in (0, 1, 2):
            assert close(result['frames'][i][track]['translation'], frames[i][track]['translation']), (i, track)
            assert same_rotation(result['frames'][i][track]['rotation'], frames[i][track]['rotation']), (i, track)
        assert close(result['rootMotion'][i], motion['rootMotion'][i])
    assert any('Extra' in warning for warning in summary['warnings']), 'Keyed untracked bone was not reported'
    # Extra keeps its reference pose in game, so its tracked child absorbs Extra's Blender motion.
    for i in (0, COUNT - 1):
        scene.frame_set(i + 1)
        child_world = trs_matrix(bones[3]) @ trs_matrix(result['frames'][i][3])
        expected = rig.pose.bones['Extra child'].matrix
        assert max(abs(child_world[r][c] - expected[r][c]) for r in range(4) for c in range(4)) < 1e-4, i
    assert not same_rotation(result['frames'][COUNT - 1][3]['rotation'], [0, 0, 0, 1]), 'Child did not absorb parent motion'

    # Keyed bones become extra tracks after the original ones.
    result, summary = export(temp, 'keyed', tracks='keyed')
    assert result['trackBoneIndices'] == [0, 1, 2, 4, 3] and result['trackNames'][-1] == 'Extra'
    assert summary['addedTracks'] == ['Extra'] and not summary['warnings']
    assert same_rotation(result['frames'][COUNT - 1][3]['rotation'], [0, 0, 0, 1]), 'Child should keep its own motion'
    result, _ = export(temp, 'all', tracks='all')
    assert result['trackCount'] == 5

    # Custom range and resampling by time.
    result, _ = export(temp, 'custom', frame_range='custom', frame_start=3, frame_end=7)
    assert result['frameCount'] == 5 and close(result['frames'][0][1]['translation'], frames[2][1]['translation'])
    assert close(result['rootMotion'][0], motion['rootMotion'][2])
    result, _ = export(temp, 'sixty', frame_rate=60)
    assert result['frameCount'] == 2 * (COUNT - 1) + 1 and result['frameRate'] == 60
    assert abs(result['duration'] - (COUNT - 1) / 30) < 1e-9
    assert close(result['frames'][2][1]['translation'], frames[1][1]['translation'])
    assert close(result['frames'][1][1]['translation'], [0, 1.005, .05]), result['frames'][1][1]['translation']
    assert same_rotation(result['frames'][1][1]['rotation'], turn('y', .05))
    scene.frame_end = 6
    assert export(temp, 'scene_end')[0]['frameCount'] == 6
    result, _ = export(temp, 'clip', frame_range='clip')
    assert result['frameCount'] == COUNT
    scene.frame_end = COUNT

    # Ground travel and heading move from the pelvis into root motion; Master is untouched.
    result, summary = export(temp, 'extract', root_motion='bone', root_yaw=True)
    assert summary['rootBone'] == 'Pelvis' and summary['rootMotion'] == 'bone'
    for i in range(COUNT):
        assert close(result['rootMotion'][i], [0, 0, .1 * i, .1 * i]), (i, result['rootMotion'][i])
        pelvis = result['frames'][i][1]
        assert close(pelvis['translation'], [0, 1 + .01 * i, 0]) and same_rotation(pelvis['rotation'], [0, 0, 0, 1]), (i, pelvis)
        assert close(result['frames'][i][0]['translation'], [0, 0, 0]) and same_rotation(result['frames'][i][0]['rotation'], [0, 0, 0, 1])
        assert same_rotation(result['frames'][i][2]['rotation'], frames[i][2]['rotation'])
    result, _ = export(temp, 'vertical', root_motion='bone', root_bone='Pelvis', root_axes='xyz')
    assert close(result['rootMotion'][COUNT - 1], [0, .01 * (COUNT - 1), .1 * (COUNT - 1), 0])
    assert close(result['frames'][COUNT - 1][1]['translation'], [0, 1, 0])
    result, _ = export(temp, 'none', root_motion='none')
    assert result['rootMotion'] is None

    # Headings past 180 degrees stay continuous.
    turns = [Matrix.Translation((0, 0, 1)) @ Matrix.Rotation(.5 * i, 4, 'Z') for i in range(12)]
    yaws = [s[3] for s in extract_root_motion(turns, 'xy', True)[1]]
    assert all(abs(yaw + .5 * i) < 1e-5 for i, yaw in enumerate(yaws)), yaws

    # A second take with its own root-motion action, exported without reassigning it.
    take = clip_action.copy(); take.name = 'take2_Sekiro'
    root_object = bpy.data.objects['HKX_RootMotion']
    root_take = root_object.animation_data.action.copy(); root_take.name = 'take2_RootMotion'
    for curve in action_curves(take):
        if curve.data_path == 'pose.bones["Master"].location' and curve.array_index == 0:
            for point in curve.keyframe_points: point.co[1] += .5
    for curve in action_curves(root_take):
        if curve.data_path == 'location' and curve.array_index == 0:
            for point in curve.keyframe_points: point.co[1] *= 2
    for item in (take, root_take):
        for curve in action_curves(item): curve.update()
    result, summary = export(temp, 'take2', action='take2_Sekiro')
    assert summary['action'] == 'take2_Sekiro' and not any('root object' in w for w in summary['warnings'])
    assert close(result['frames'][4][0]['translation'], [.5, 0, 0]), result['frames'][4][0]
    assert close(result['rootMotion'][4], [.4, 0, 0, 0]), result['rootMotion'][4]
    assert rig.animation_data.action == clip_action and root_object.animation_data.action.name.startswith('owned_RootMotion')
    try:
        export(temp, 'missing', action='No such action')
        raise AssertionError('A missing action was accepted')
    except RuntimeError as exc:
        assert 'No such action' in str(exc)

    info = inspect_scene(Path(temp) / 'scene.json')
    names = {action['name']: action for action in info['actions']}
    assert set(names) == {clip_action.name, 'take2_Sekiro'}, names.keys()
    assert names[clip_action.name]['active'] and names[clip_action.name]['rootAction'] == root_object.animation_data.action.name
    assert names['take2_Sekiro']['rootAction'] == 'take2_RootMotion' and names[clip_action.name]['untracked'] == ['Extra']
    assert info['defaultRootBone'] == 'Pelvis' and info['rootObject']['name'] == 'HKX_RootMotion' and info['frameCount'] == COUNT
print('PASS: export defaults, track sets, parent compensation, frame ranges, resampling, root extraction, takes and inspect', flush=True)
