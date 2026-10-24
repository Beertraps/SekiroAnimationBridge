"""Control rig of the retarget add-on on owned synthetic bridge rigs. Run with Blender --background --factory-startup --python this_file.py.

An Elden Ring-style skeleton with turned rest frames, as game skeletons store
them, is imported through the bridge with a clip in which the elbows and knees
of three limbs bend around their rest hinges and the right forearm also twists.
A muscle helper is scaled unevenly, and a face bone lies almost along its
parent's -Y axis, where Blender snaps rest matrices.
Checked: adding the control rig leaves every game bone's pose unchanged at every
frame with FK, and with IK keeps joint positions and hand and foot rotations
(whole limbs where they bend around their hinges); the export samples the same
motion; the controls drive the game bones; switching between IK and FK matches
an edited pose; removal restores the original action or keeps the edited
motion; the retarget refuses a target with a control rig; keyed controls add
tracks to the keyed track set; and a rig without arms or legs gets FK controls.
"""
import json
import math
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import bl_to_game_trs, export_motion, import_motion, inspect_scene
import sekiro_retarget
from sekiro_retarget import control_rig, retarget

COUNT, RATE = 24, 30
LIMBS = (('L', 'upperarm', 'forearm', 'hand'), ('R', 'upperarm', 'forearm', 'hand'),
         ('L', 'thigh', 'calf', 'foot'), ('R', 'thigh', 'calf', 'foot'))


def turned_rest(bones, seed):
    """Rest matrices at the given heads with randomly turned frames."""
    rng = random.Random(seed)
    rest = {}
    for name, parent, head, label in bones:
        axis = Vector([rng.uniform(-1, 1) for _ in range(3)]).normalized()
        rest[name] = Matrix.LocRotScale(Vector(head), Quaternion(axis, rng.uniform(-math.pi, math.pi)), None)
    return rest


def pose(bones, rest, turns, travel=None):
    """Armature-space matrices with each bone turned in world space by turns[name] after its parent."""
    deltas, result = {}, {}
    for name, parent, head, label in bones:
        deltas[name] = (deltas[parent] if parent else Quaternion()) @ turns.get(name, Quaternion())
        if parent:
            position = result[parent] @ (rest[parent].inverted() @ rest[name]).translation
        else:
            position = rest[name].translation.copy()
        if travel and name in travel:
            position += travel[name]
        result[name] = Matrix.LocRotScale(position, deltas[name] @ rest[name].to_quaternion(), None)
    return result


def motion(bones, rest, poses, tracked):
    """Bridge motion JSON for a skeleton with these rest matrices and armature-space poses."""
    index = {bone[0]: i for i, bone in enumerate(bones)}

    def local(matrices, name, parent):
        return matrices[parent].inverted() @ matrices[name] if parent else matrices[name]
    skeleton = [dict(index=i, name=name, parent=index[parent] if parent else -1,
                     **bl_to_game_trs(*local(rest, name, parent).decompose()))
                for i, (name, parent, head, label) in enumerate(bones)]
    tracks = [index[name] for name in tracked]
    frames = [[bl_to_game_trs(*local(p, bones[i][0], bones[i][1]).decompose()) for i in tracks] for p in poses]
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip='a000_003000.hkx', skeletonName='Owned', game='er',
                skeleton=dict(name='Owned', boneCount=len(skeleton), bones=skeleton), frameCount=len(poses), frameRate=RATE,
                duration=(len(poses) - 1) / RATE, trackCount=len(tracks), trackBoneIndices=tracks,
                trackNames=[bones[i][0] for i in tracks], frames=frames,
                rootMotion=[[.01 * f, 0, .02 * f, .005 * f] for f in range(len(poses))], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


def humanoid():
    """The synthetic humanoid's bones, rest matrices and clip."""
    bones = humanoids.fromsoftware(45, 'elden')
    rest = turned_rest(bones, 7)
    # A face bone lying almost along its parent's -Y axis, which Blender snaps onto that axis at rest.
    rest['Face_Root'] = Matrix.LocRotScale(rest['Face_Root'].translation,
                                           rest['Head'].to_quaternion() @ Quaternion((1, 0, 0), math.pi - 1e-4), None)
    name = {label: bone for bone, parent, head, label in bones if label}
    hinge = {}
    for side, upper, lower, end in LIMBS:
        s, e, w = (rest[name[f'{side}.{role}']].translation for role in (upper, lower, end))
        hinge[f'{side}.{lower}'] = (e - s).cross(w - e).normalized()
    poses = []
    for f in range(COUNT):
        t = f / (COUNT - 1)
        w = 2 * math.pi * t
        turns = {
            'hips': Quaternion((0, 0, 1), .4 * math.sin(w)), 'spine.first': Quaternion((1, 0, 0), .25 * math.sin(w)),
            'spine.mid': Quaternion((0, 1, 0), .15 * math.sin(2 * w)), 'neck': Quaternion((1, 0, 0), .3 * math.sin(w)),
            'head': Quaternion((0, 0, 1), .4 * math.sin(w)), 'L.clavicle': Quaternion((0, 1, 0), .2 * math.sin(w)),
            'L.upperarm': Quaternion(Vector((.3, 1, .2)).normalized(), -.9 * math.sin(w)),
            'L.forearm': Quaternion(hinge['L.forearm'], .2 + 1.1 * math.sin(w) ** 2),
            'L.hand': Quaternion(Vector((1, .5, .3)).normalized(), .7 * math.sin(w)),
            'R.upperarm': Quaternion((1, 0, 0), .8 * math.sin(w)),
            # The right forearm also twists about itself, which no hinge reproduces.
            'R.forearm': Quaternion(hinge['R.forearm'], .3 + .9 * math.sin(w) ** 2) @ Quaternion(Vector((-1, 0, -1)).normalized(), .5 * math.sin(w)),
            'R.hand': Quaternion((0, 1, 0), -.5 * math.sin(w)),
            'L.thigh': Quaternion((1, 0, 0), .7 * math.sin(w)), 'L.calf': Quaternion(hinge['L.calf'], .1 + 1.2 * math.sin(w) ** 2),
            'L.foot': Quaternion((1, 0, 0), .3 * math.sin(w)),
            'R.thigh': Quaternion(Vector((1, 0, .3)).normalized(), -.7 * math.sin(w)),
            'R.calf': Quaternion(hinge['R.calf'], .1 + 1.2 * math.cos(w / 2) ** 2), 'R.foot': Quaternion((0, 0, 1), .2 * math.sin(w)),
            'L.index.1': Quaternion((0, 1, 0), .6 * math.sin(w) ** 2)}
        turns = {name[label]: turn for label, turn in turns.items()}
        poses.append(pose(bones, rest, turns, {'RootPos': Vector((0, -.6 * t, .03 * math.sin(2 * w)))}))
        # A muscle helper without children that the clip scales unevenly along its own axes.
        poses[-1]['L_Shoulder'] = poses[-1]['L_Shoulder'] @ Matrix.Diagonal((1 + .15 * math.sin(w), 1, 1 - .1 * math.sin(w), 1))
    tracked = [bone for bone, parent, head, label in bones
               if label or bone in ('Master', 'RootPos', 'RootRotY', 'RootRotXZ', 'L_Shoulder')]
    return bones, rest, motion(bones, rest, poses, tracked)


def evaluate(rig, names, frames=range(1, COUNT + 1)):
    scene = bpy.context.scene
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = {name: rig.pose.bones[name].matrix.copy() for name in names}
    return result


def difference(a, b):
    """(distance, angle in degrees) between two matrices."""
    # atan2 of the half-angle sine stays exact for small angles, where acos of a dot product rounds to steps.
    turn = a.to_quaternion().rotation_difference(b.to_quaternion())
    return (a.translation - b.translation).length, math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0])))


def worst(first, second, names=None):
    """Largest (distance, angle) between two evaluations over all frames and the given bones."""
    distance = angle = 0.0
    for frame, matrices in first.items():
        for name in names or matrices:
            d, a = difference(matrices[name], second[frame][name])
            distance, angle = max(distance, d), max(angle, a)
    return distance, angle


def heads_worst(first, second, names):
    return max((first[f][n].translation - second[f][n].translation).length for f in first for n in names)


def set_switch(rig, value):
    for limb in control_rig.layout(rig)['limbs']:
        rig.pose.bones[limb['control']][control_rig.SWITCH] = value
    rig.update_tag()  # Drivers re-read custom properties only when the rig is tagged, as the UI slider does.


def frames_of(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))['frames']


def same_frames(a, b, tolerance=2e-5):
    worst_value = 0.0
    for frame_a, frame_b in zip(a, b):
        for track_a, track_b in zip(frame_a, frame_b):
            for key in ('translation', 'rotation', 'scale'):
                values = [abs(x - y) for x, y in zip(track_a[key], track_b[key])]
                if key == 'rotation':  # q and -q are the same rotation
                    values = [min(v, abs(x + y)) for v, x, y in zip(values, track_a[key], track_b[key])]
                worst_value = max(worst_value, *values)
    assert len(a) == len(b) and worst_value < tolerance, ('export differs', len(a), len(b), worst_value)
    return worst_value


def check_removed(rig, names):
    assert not control_rig.present(rig)
    assert not [bone.name for bone in rig.data.bones if control_rig.is_control(bone)]
    assert sorted(bone.name for bone in rig.data.bones) == sorted(names)
    assert not any(bone.constraints for bone in rig.pose.bones), 'constraints left on game bones'
    assert not rig.data.collections, [c.name for c in rig.data.collections]
    assert not [obj.name for obj in bpy.data.objects if obj.get('sekiro_control_widget')]
    assert not (rig.animation_data and rig.animation_data.drivers), 'drivers left'


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sekiro_retarget.register()
    scene = bpy.context.scene
    bones, rest, clip = humanoid()
    rig = import_motion(clip)
    names = [bone[0] for bone in bones]
    label = {bone: lab for bone, parent, head, lab in bones}
    by_label = {lab: bone for bone, lab in label.items() if lab}
    rest_before = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    in_front = rig.show_in_front
    original = evaluate(rig, names)
    original_action = rig.animation_data.action
    work = Path(tempfile.mkdtemp(prefix='ControlRigTest-'))
    export_motion(work / 'before.motion.json')

    # Add: the game bones keep their pose at every frame with FK.
    started = time.perf_counter()
    result = control_rig.add(bpy.context, rig)
    added_seconds = time.perf_counter() - started
    data = control_rig.layout(rig)
    assert [limb['label'] for limb in data['limbs']] == ['Left arm', 'Right arm', 'Left leg', 'Right leg'], data['limbs']
    assert result['frames'] == COUNT and result['controls'] == len(names) + 1 + 2 * 4, result
    assert all(not bone.use_deform for bone in rig.data.bones if control_rig.is_control(bone))
    assert all(max(abs(a - b) for ra, rb in zip(rig.data.bones[n].matrix_local, m) for a, b in zip(ra, rb)) < 1e-7
               for n, m in rest_before.items()), 'game bone rest changed'
    assert rig.animation_data.action != original_action and original_action.use_fake_user
    assert rig.mode == 'POSE' and rig.show_in_front, 'controls should draw in front of the mesh'
    shapes = [bone for bone in rig.pose.bones if control_rig.is_control(bone.bone) and bone.custom_shape]
    assert len(shapes) == result['controls'], (len(shapes), result['controls'])
    # Both awkward bones occur: Blender snapped the face bone's rest, which its socket's pose corrects, and the
    # unevenly scaled helper's control lies on the helper's own axes.
    assert Vector(rig.pose.bones[data['sockets']['Face_Root']].rotation_quaternion[1:]).length > 1e-5
    helper = rig.data.bones[data['fk']['L_Shoulder']].matrix_local, rig.data.bones['L_Shoulder'].matrix_local
    assert max(abs(a - b) for ra, rb in zip(*helper) for a, b in zip(ra.to_3d(), rb.to_3d())) < 1e-5, helper
    fk = evaluate(rig, names)
    fk_error = worst(original, fk)
    assert fk_error[0] < 1e-5 and fk_error[1] < 1e-3, ('FK pose differs', fk_error)
    export_motion(work / 'controls.motion.json')
    export_error = same_frames(frames_of(work / 'before.motion.json'), frames_of(work / 'controls.motion.json'))

    # IK: joints, hands and feet stay; limbs that bend around their hinges stay whole.
    set_switch(rig, 1.0)
    ik = evaluate(rig, names)
    joints = [by_label[f'{side}.{role}'] for side, *roles in LIMBS for role in roles]
    ends = [by_label[f'{side}.{roles[-1]}'] for side, *roles in LIMBS]
    joint_error = heads_worst(original, ik, joints)
    end_error = worst(original, ik, ends)
    hinged = [by_label[f'{side}.{role}'] for side, *roles in LIMBS if (side, roles[0]) != ('R', 'upperarm') for role in roles]
    hinged_error = worst(original, ik, hinged)
    right_forearm = by_label['R.forearm']
    twisted = {right_forearm, by_label['R.upperarm']} | {b.name for b in rig.data.bones[by_label['R.upperarm']].children_recursive
                                                         if not control_rig.is_control(b)} - {by_label['R.hand']} \
        - {b.name for b in rig.data.bones[by_label['R.hand']].children_recursive}
    others = [n for n in names if n not in twisted and n not in joints]
    others_error = worst(original, ik, others)
    assert joint_error < 2e-4, ('IK joint positions differ', joint_error)
    assert end_error[0] < 2e-4 and end_error[1] < .05, ('IK hand or foot differs', end_error)
    assert hinged_error[0] < 2e-4 and hinged_error[1] < .05, ('IK limbs that bend around their hinges differ', hinged_error)
    assert others_error[0] < 2e-4 and others_error[1] < .05, ('IK moved other bones', others_error)
    twist = worst(original, ik, [right_forearm])[1]
    assert twist > 1.0, ('the twisted forearm should show the IK twist difference', twist)
    set_switch(rig, 0.0)

    # The controls drive the game bones.
    scene.frame_set(8)
    arm = [by_label['L.upperarm'], by_label['L.forearm'], by_label['L.hand']]
    before = {n: rig.pose.bones[n].matrix.copy() for n in arm}
    control = rig.pose.bones[data['fk'][arm[1]]]
    control.rotation_quaternion = control.rotation_quaternion @ Quaternion((1, 0, 0), math.radians(20))
    bpy.context.view_layer.update()
    after = {n: rig.pose.bones[n].matrix.copy() for n in arm}
    unmoved = difference(before[arm[0]], after[arm[0]])
    assert unmoved[0] < 1e-6 and unmoved[1] < 1e-3, unmoved
    assert abs(difference(before[arm[1]], after[arm[1]])[1] - 20) < .01, difference(before[arm[1]], after[arm[1]])
    assert difference(before[arm[2]], after[arm[2]])[0] > .05

    # Removal through the operator restores the original action and the original pose.
    assert bpy.ops.sekiro_retarget.remove_control_rig(keep='ORIGINAL') == {'FINISHED'}
    check_removed(rig, names)
    assert rig.show_in_front == in_front
    assert rig.animation_data.action == original_action
    restored_error = worst(original, evaluate(rig, names))
    assert restored_error[0] < 1e-6 and restored_error[1] < 1e-4, restored_error

    # Add again through the operator, edit an FK control and switch the arm to IK and back.
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert bpy.ops.sekiro_retarget.add_control_rig() == {'FINISHED'}
    data = control_rig.layout(rig)
    left_arm = [limb['label'] for limb in data['limbs']].index('Left arm')
    control = rig.pose.bones[data['fk'][arm[1]]]
    scene.frame_set(10)
    control.rotation_quaternion = control.rotation_quaternion @ Quaternion((1, 0, 0), math.radians(25))
    control.keyframe_insert('rotation_quaternion', frame=10)
    edited = evaluate(rig, names)
    assert difference(edited[10][arm[1]], original[10][arm[1]])[1] > 20
    control_rig.switch(bpy.context, rig, left_arm, 'IK', every_frame=True)
    assert rig.pose.bones[data['limbs'][left_arm]['control']][control_rig.SWITCH] == 1.0
    switched = evaluate(rig, names)
    switch_ik = heads_worst(edited, switched, arm), worst(edited, switched, [arm[2]])
    assert switch_ik[0] < 2e-4 and switch_ik[1][1] < .05, ('switching to IK changed the arm', switch_ik)
    control_rig.switch(bpy.context, rig, left_arm, 'FK', every_frame=True)
    back = evaluate(rig, names)
    switch_fk = worst(switched, back, arm)
    assert switch_fk[0] < 2e-5 and switch_fk[1] < .01, ('switching back to FK changed the arm', switch_fk)
    # One frame only: the IK hand is matched where it is animated, at the current frame.
    scene.frame_set(5)
    control_rig.switch(bpy.context, rig, left_arm, 'IK', every_frame=False)
    single = evaluate(rig, arm, [5])
    assert heads_worst(single, {5: back[5]}, arm) < 2e-4
    control_rig.switch(bpy.context, rig, left_arm, 'FK', every_frame=False)
    set_switch(rig, 0.0)

    # A keyed control of an untracked bone adds its track to the keyed track set.
    weapon = rig.pose.bones[data['fk']['L_Weapon']]
    assert 'hkx_track_index' not in rig.pose.bones['L_Weapon']
    weapon.rotation_quaternion = Quaternion((0, 0, 1), .4)
    weapon.keyframe_insert('rotation_quaternion', frame=1)
    weapon.rotation_quaternion = Quaternion((0, 0, 1), -.4)
    weapon.keyframe_insert('rotation_quaternion', frame=COUNT)
    keyed = export_motion(work / 'keyed.motion.json', tracks='keyed')
    assert keyed['addedTracks'] == ['L_Weapon'], keyed['addedTracks']
    plain = export_motion(work / 'plain.motion.json')
    assert any('L_Weapon' in warning for warning in plain['warnings']), plain['warnings']
    listed = inspect_scene(work / 'scene.json')['actions']
    assert [a['name'] for a in listed] == [rig.animation_data.action.name], listed
    try:
        export_motion(work / 'wrong.motion.json', action=original_action.name)
        raise AssertionError('exporting an action that does not move the controls should fail')
    except RuntimeError as exc:
        assert 'control rig' in str(exc), exc

    # The retarget refuses a target with a control rig.
    other = bpy.data.objects.new('Other', bpy.data.armatures.new('Other'))
    scene.collection.objects.link(other)
    settings = scene.sekiro_retarget
    settings.source, settings.target = other, rig
    try:
        retarget.bake(scene, settings)
        raise AssertionError('the retarget should refuse a target with a control rig')
    except ValueError as exc:
        assert 'control rig' in str(exc), exc

    # Removal keeping the edits bakes the controls' motion onto the game bones.
    edited = evaluate(rig, names)
    action = control_rig.remove(bpy.context, rig, keep_edits=True)
    check_removed(rig, names)
    assert rig.show_in_front == in_front
    assert action.name == original_action.name + ' Edited' and action.get('sekiro_control_rig_base') == original_action
    kept_error = worst(edited, evaluate(rig, names))
    assert kept_error[0] < 1e-5 and kept_error[1] < 1e-3, ('removal changed the edited motion', kept_error)
    assert 'L_Weapon' in retarget.action_bones(action)

    # A skeleton without arms or legs gets FK controls only.
    chain = [('Base', '', (0, 0, 0), None), ('Link_1', 'Base', (0, .2, .1), None), ('Link_2', 'Link_1', (.1, .4, .3), None),
             ('Link_3', 'Link_2', (.1, .5, .6), None), ('Tip', 'Link_3', (.15, .55, .62), None)]
    chain_rest = turned_rest(chain, 3)
    chain_poses = [pose(chain, chain_rest, {n: Quaternion(Vector((1, i, .5)).normalized(), .5 * math.sin(f / 4 + i))
                                            for i, n in enumerate(c[0] for c in chain)}) for f in range(COUNT)]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    chain_rig = import_motion(motion(chain, chain_rest, chain_poses, [c[0] for c in chain]))
    chain_names = [c[0] for c in chain]
    chain_before = evaluate(chain_rig, chain_names)
    chain_result = control_rig.add(bpy.context, chain_rig)
    assert chain_result['limbs'] == [] and chain_result['controls'] == len(chain) + 1, chain_result
    chain_error = worst(chain_before, evaluate(chain_rig, chain_names))
    assert chain_error[0] < 1e-5 and chain_error[1] < 1e-3, chain_error
    control_rig.remove(bpy.context, chain_rig, keep_edits=False)
    check_removed(chain_rig, chain_names)
    shutil.rmtree(work, ignore_errors=True)

    print(f'Added {result["controls"]} controls and baked {COUNT} frames in {added_seconds:.2f} s')
    print(f'FK pose: {fk_error[0]:.2e} m, {fk_error[1]:.2e} deg; export frames differ by {export_error:.2e}')
    print(f'IK: joints {joint_error:.2e} m, hands and feet {end_error[0]:.2e} m / {end_error[1]:.3f} deg, '
          f'hinged limbs {hinged_error[1]:.3f} deg, twisted forearm {twist:.1f} deg (expected), other bones {others_error[1]:.3f} deg')
    print(f'Switch to IK: joints {switch_ik[0]:.2e} m, hand {switch_ik[1][1]:.3f} deg; back to FK: {switch_fk[0]:.2e} m, {switch_fk[1]:.3f} deg')
    print(f'Removal: original restored within {restored_error[0]:.1e} m, edits kept within {kept_error[0]:.1e} m / {kept_error[1]:.1e} deg')
    print('Control rig check passed')


main()
