"""Weapons and props that leave the source's hands, fly and land in another, on owned synthetic rigs. Run with
Blender --background --factory-startup --python this_file.py.

The source walks forward and swings both arms. It throws the weapon in its right hand to its left hand in an arc,
carries it there, and throws it back. A torch rests on the ground below the rig's root; the right hand picks it up,
carries it and puts it down again. The target has shorter legs and other arms, a weapon of its own in its right
hand and a torch on the ground. Checked:
- The weapon, a weapon by its name: it keeps the target's own grip in the right hand while the source's keeps its
  place there; it rides in the left hand, as far from it as the source's, scaled, on the frames the source carries
  it there; in flight it follows the source's path from where it left the hand toward where it lands, blending from
  the one to the other, exactly as carry says.
- The torch, below the root and an Other bone by its name: with the role Other it keeps its place on the root and
  the bake suggests the role Prop; as a Prop, on the ground it takes the source's place, scaled, rides in the right
  hand as far from it as the source's, and flies between.
- Extracting the body's travel as root motion moves the weapon with the body on every frame, also in flight.
- Keep its place keeps the weapon in the target's own grip on every frame.
"""
import json
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
import sekiro_retarget
from sekiro_retarget import retarget

COUNT, RATE = 60, 30
THROW, CAUGHT, BACK = (10, 20), (21, 40), (41, 50)  # Frames of the weapon's flight, its ride in the left hand, its way back.
PICK, CARRIED, DOWN = (16, 24), (25, 45), (46, 54)  # Frames of the torch's way up, its ride in the right hand, its way down.
WALK = .6  # How far the source walks forward over the clip.


def with_carried(bones):
    """The rig with a weapon in its right hand and a torch on the ground below its root."""
    hand = Vector(next(head for name, parent, head, label in bones if label == 'R.hand'))
    return bones + [('R_Weapon', 'R_Hand', tuple(hand + Vector((-.02, 0, -.01))), None), ('Torch', 'Root', (.3, -.3, 0), None)]


def armature(name, bones):
    data = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    heads = {bone[0]: Vector(bone[2]) for bone in bones}
    children = {}
    for bone in bones:
        children.setdefault(bone[1], []).append(bone[0])
    for bone_name, parent, head, label in bones:
        edit = data.edit_bones.new(bone_name)
        edit.head = heads[bone_name]
        tail = heads[children[bone_name][0]] if bone_name in children else heads[bone_name] + Vector((0, 0, .05))
        edit.tail = tail if (tail - edit.head).length > 1e-4 else edit.head + Vector((0, 0, .05))
        if parent:
            edit.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def arc(start, end, x, height):
    """From start to end on a parabola rising height above the line between them, turning from one to the other."""
    point = start.translation.lerp(end.translation, x) + Vector((0, 0, height * 4 * x * (1 - x)))
    return Matrix.LocRotScale(point, start.to_quaternion().slerp(end.to_quaternion(), x), None)


def clip(rig):
    """Key the source clip (see the module)."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda bone: len(bone.parent_recursive))
    frames = []
    for f in range(1, COUNT + 1):
        phase = 2 * math.pi * (f - 1) / (COUNT - 1)
        turns = {'L_UpperArm': Quaternion((0, 0, 1), .4 * math.sin(phase)), 'R_UpperArm': Quaternion((0, 0, 1), .4 * math.sin(phase))}
        deltas, poses = {}, {}
        for bone in ordered:
            deltas[bone.name] = turns.get(bone.name, deltas[bone.parent.name] if bone.parent else Quaternion())
            head = poses[bone.parent.name] @ (rest[bone.parent.name].inverted() @ rest[bone.name]).translation \
                if bone.parent else rest[bone.name].translation
            if bone.name == 'Hips':
                head = head + Vector((0, -WALK * (f - 1) / (COUNT - 1), 0))
            poses[bone.name] = Matrix.LocRotScale(head, deltas[bone.name] @ rest[bone.name].to_quaternion(), None)
        frames.append(poses)
    grip = rest['R_Hand'].inverted() @ rest['R_Weapon']
    other = Matrix.Translation((0, .03, 0)) @ grip  # Where the left hand holds it.
    held = Matrix.Translation((0, -.04, 0)) @ rest['R_Hand'].inverted() @ Matrix.Translation(rest['R_Hand'].translation)
    usual, caught = (lambda i: frames[i]['R_Hand'] @ grip), (lambda i: frames[i]['L_Hand'] @ other)
    in_hand = lambda i: frames[i]['R_Hand'] @ held  # noqa: E731
    for i, poses in enumerate(frames):
        f = i + 1
        if THROW[0] <= f <= THROW[1]:
            poses['R_Weapon'] = arc(usual(THROW[0] - 2), caught(CAUGHT[0] - 1), (f - THROW[0] + 1) / (THROW[1] - THROW[0] + 2), .3)
        elif CAUGHT[0] <= f <= CAUGHT[1]:
            poses['R_Weapon'] = caught(i)
        elif BACK[0] <= f <= BACK[1]:
            poses['R_Weapon'] = arc(caught(CAUGHT[1] - 1), usual(BACK[1]), (f - BACK[0] + 1) / (BACK[1] - BACK[0] + 2), .3)
        if PICK[0] <= f <= PICK[1]:
            poses['Torch'] = arc(rest['Torch'], in_hand(CARRIED[0] - 1), (f - PICK[0] + 1) / (PICK[1] - PICK[0] + 2), .1)
        elif CARRIED[0] <= f <= CARRIED[1]:
            poses['Torch'] = in_hand(i)
        elif DOWN[0] <= f <= DOWN[1]:
            poses['Torch'] = arc(in_hand(CARRIED[1] - 1), rest['Torch'], (f - DOWN[0] + 1) / (DOWN[1] - DOWN[0] + 2), .1)
        else:
            poses['Torch'] = rest['Torch']
        for bone in ordered:
            keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=rest[bone.parent.name]) if bone.parent else {}
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f)


def track(rig):
    result = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result.append({bone.name: (rig.matrix_world @ bone.matrix).copy() for bone in rig.pose.bones})
    return result


def bake(**options):
    for key, value in options.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    return json.loads(scene['sekiro_retarget_report']), track(target)


def flights(free):
    """(index before, index after) of each flight, from its frames counted from 1."""
    return [(start - 1, end) for start, end in retarget.runs(f in set(free) for f in range(1, COUNT + 1))]


def follows_flight(frames, name, free, air):
    """The largest distance over a flight's frames from where carry puts the bone: the source's path from both ends,
    scaled by air, blended from the one end to the other by a smooth step."""
    worst = 0.0
    for before, after in flights(free):
        assert before >= 0 and after < COUNT, (name, before, after)
        for i in range(before + 1, after):
            x = (i - before) / (after - before)
            weights = 1 - x * x * (3 - 2 * x), x * x * (3 - 2 * x)
            wanted = sum(((frames[end][name].translation + (src[i][name].translation - src[end][name].translation) * air) * weight
                          for end, weight in zip((before, after), weights)), Vector())
            worst = max(worst, (frames[i][name].translation - wanted).length)
    return worst


def distances(frames, name, hand, indices):
    """Per frame, how far a bone lies from a hand in the target against the source's, scaled by travel."""
    return [abs((frames[i][name].translation - frames[i][hand].translation).length -
                travel * (src[i][name].translation - src[i][hand].translation).length) for i in indices]


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE
source = armature('Source', with_carried(humanoids.proportioned(3)))
clip(source)
src = track(source)
target = armature('Target', with_carried(humanoids.proportioned(2, legs=.85, arms=(.9, 1.2))))
settings = scene.sekiro_retarget
settings.source, settings.target = source, target
settings.rest_mode, settings.root_motion, settings.method = 'REST', 'NONE', 'BONES'
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row for row in settings.rows}
assert (rows['R_Weapon'].source, rows['R_Weapon'].role) == ('R_Weapon', 'WEAPON'), (rows['R_Weapon'].source, rows['R_Weapon'].role)
assert (rows['Torch'].source, rows['Torch'].role) == ('Torch', 'OTHER'), (rows['Torch'].source, rows['Torch'].role)

# The torch as an Other bone keeps its place on the root, and the bake suggests the role Prop.
report, frames = bake()
travel = report['scale']
assert set(report['carried']) == {'R_Weapon'}, report['carried']
place = target.data.bones['Torch'].head_local
assert max((frame['Torch'].translation - place).length for frame in frames) < 1e-5
assert "Torch moves far from its parent in the source's clip: set its Role to Prop in the bone list if it is something " \
       "held or thrown." in report['notes'], report['notes']

# The weapon: thrown to the left hand, carried there, thrown back.
weapon = report['carried']['R_Weapon']
caught = set(weapon['hands'].get('L_Hand', ()))
assert set(range(CAUGHT[0] + 1, CAUGHT[1])) <= caught <= set(range(THROW[1] - 1, BACK[0] + 2)), weapon
assert set(weapon['free']) & set(range(*THROW)) and set(weapon['free']) & set(range(*BACK)), weapon
assert set(weapon['free']) <= set(range(THROW[0], BACK[1] + 1)), weapon
assert f"R_Weapon rides in L_Hand on frames" in ' '.join(report['notes']), report['notes']
grip = target.data.bones['R_Hand'].matrix_local.inverted() @ target.data.bones['R_Weapon'].matrix_local
still = [i for i in range(COUNT) if i + 1 not in set(weapon['free']) | caught]
assert len(still) >= 15
gripped = max(((frames[i]['R_Hand'].inverted() @ frames[i]['R_Weapon']).translation - grip.translation).length for i in still)
assert gripped < 1e-4, f'the weapon left its grip in the right hand by {gripped * 1000:.2f} mm'
riding = max(distances(frames, 'R_Weapon', 'L_Hand', sorted(f - 1 for f in caught)))
assert riding < 1e-4, f'the weapon rides {riding * 1000:.2f} mm off its scaled place in the left hand'
flown = follows_flight(frames, 'R_Weapon', weapon['free'], travel)
assert flown < 1e-4, f'the weapon flies {flown * 1000:.2f} mm off the blended paths'

# The torch as a Prop: on the ground at the source's place, scaled, in the right hand, and in flight between.
rows['Torch'].role = 'PROP'
report, frames = bake()
torch = report['carried']['Torch']
carried = set(torch['hands'].get('R_Hand', ()))
assert set(range(CARRIED[0] + 1, CARRIED[1])) <= carried <= set(range(PICK[1] - 1, DOWN[0] + 2)), torch
grounded = [i for i in range(COUNT) if i + 1 not in set(torch['free']) | carried]
assert set(range(PICK[0] - 1)) <= set(grounded), torch
ground = max((frames[i]['Torch'].translation - src[i]['Torch'].translation * travel).length for i in grounded)
assert ground < 1e-5, f'the torch lies {ground * 1000:.2f} mm off the source\'s scaled place on the ground'
held = max(distances(frames, 'Torch', 'R_Hand', sorted(f - 1 for f in carried)))
assert held < 1e-4, f'the torch rides {held * 1000:.2f} mm off its scaled place in the right hand'
lifted = follows_flight(frames, 'Torch', torch['free'], travel)
assert lifted < 1e-4, f'the torch flies {lifted * 1000:.2f} mm off the blended paths'
assert 'Torch moves with Root as the source\'s Torch moves with Root.' in report['notes'], report['notes']
assert not any('moves far from its parent' in note for note in report['notes']), report['notes']

# Extracting the body's travel as root motion moves the weapon with the body on every frame, also in flight.
plain = frames
report, extracted = bake(root_motion='EXTRACT')
assert report['root_motion'] == 'EXTRACT' and report['carrier'], (report['root_motion'], report['carrier'])
carrier = report['carrier']
moved = max((plain[i]['R_Weapon'].translation -
             (plain[i][carrier] @ extracted[i][carrier].inverted() @ extracted[i]['R_Weapon']).translation).length
            for i in range(COUNT))
assert moved < 1e-4, f'with root motion, the weapon is {moved * 1000:.2f} mm off where the body takes it'
travelled = (plain[-1][carrier].translation - plain[0][carrier].translation).length
assert travelled > .3, travelled

# Keep its place: the weapon keeps its own grip on every frame.
rows['R_Weapon'].hold = 'KEEP'
report, frames = bake(root_motion='NONE')
assert 'R_Weapon' not in report['carried'], report['carried']
kept = max(((frame['R_Hand'].inverted() @ frame['R_Weapon']).translation - grip.translation).length for frame in frames)
assert kept < 1e-4, f'the kept weapon left its grip by {kept * 1000:.2f} mm'
print(f"Carried check passed: the weapon rode in the left hand on frames {min(caught)}-{max(caught)} within "
      f"{riding * 1000:.3f} mm of its scaled place and flew within {flown * 1000:.3f} mm of the blended paths; the torch, "
      f"an Other bone that the bake suggested as a Prop, rode in the right hand on frames {min(carried)}-{max(carried)} "
      f"within {held * 1000:.3f} mm, lay on the ground within {ground * 1000:.4f} mm of the source's scaled place and flew "
      f"within {lifted * 1000:.3f} mm; with {travelled:.2f} of body travel taken as root motion the weapon stayed within "
      f"{moved * 1000:.3f} mm of the body; Keep its place kept the grip within {kept * 1000:.3f} mm.")
sekiro_retarget.unregister()
