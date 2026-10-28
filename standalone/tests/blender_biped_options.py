"""Biped-style options of the full-body bake on owned synthetic rigs. Run with Blender --background --factory-startup --python this_file.py.

A source of base proportions stands with its knees slightly bent and its left foot planted while that foot rolls
onto its ball and back, its toes flat, with 2 mm of jitter; slides its right foot 20 cm outward along the ground;
jumps 30 cm with both feet off the ground for twelve frames; and throws a prop from its right hand. The target has shorter legs, a longer foot and a prop of its
own. Checked:
- Body figures: Create figure places the parts on the joints and shows the rig's rest pose while the figure is open,
  when the bake refuses; a part linked to a missing bone cannot be saved; saving closes the figure and gives the rig
  back its pose position, as closing does; a saved figure is kept on the rig and in the figure folder, found there
  for another rig of the same skeleton, used by the bake, and deleted again.
- Planted, sliding, free: the target's planted ball stands still on its own through the roll, where the default
  contacts let it move with the scaled ankle; the slide is found and keeps the foot at its own height; no frame
  jumps further than with the default contacts.
- Jumps: the hips' rise above the line from lift-off to touchdown is the source's times the jump ratio, the target's
  height against the source's scaled by travel, and the travel scale without the option.
- Moving props: by height and by limb size, the target's prop moves from its hand as far as the source's, scaled
  by the heights or by the arm lengths, with both bake methods; kept in place without the option.
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
FOLDER = tempfile.mkdtemp(prefix='sekiro_figures_')
os.environ['SEKIRO_FIGURE_FOLDER'] = FOLDER
import humanoids
import sekiro_retarget
from sekiro_retarget import figure, retarget

COUNT, RATE = 48, 30
ROLL, SLIDE, JUMP, THROW = (4, 12), (14, 21), (24, 35), (38, 47)
CROUCH = .05  # The source stands with its knees bent, so that its legs reach the slide.


def with_prop(bones, toe=None):
    """The rig with a prop in the right hand, and optionally its toes moved forward to toe (y)."""
    result = []
    for name, parent, head, label in bones:
        if toe is not None and label and label.endswith('.toe'):
            head = (head[0], toe, head[2])
        result.append((name, parent, head, label))
    hand = next(head for name, parent, head, label in bones if label == 'R.hand')
    return result + [('R_Prop', 'R_Hand', (hand[0], hand[1] - .05, hand[2]), None)]


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


def ramp(value, start, end):
    x = min(1.0, max(0.0, (value - start) / (end - start)))
    return x * x * (3 - 2 * x)


def reach(root, rest, goal, pole, before):
    """World turns of a two-bone limb rooted at root so that its end lies on goal, bending toward pole."""
    upper, lower = rest[1] - rest[0], rest[2] - rest[1]
    a, b = upper.length, lower.length
    line = goal - root
    d = min(max(line.length, abs(a - b) + 1e-6), a + b - 1e-6)
    axis = line.normalized()
    bend = (pole - axis * pole.dot(axis)).normalized()
    cosine = (a * a + d * d - b * b) / (2 * a * d)
    middle = root + (axis * cosine + bend * math.sqrt(1 - cosine * cosine)) * a
    first = (before @ upper).rotation_difference(middle - root) @ before
    second = (first @ lower).rotation_difference(root + axis * d - middle) @ first
    return first, second


def rise(f):
    """The jump's rise on frame index f: 30 cm at the top, nothing at lift-off and touchdown."""
    if not JUMP[0] <= f <= JUMP[1]:
        return 0.0
    x = (f - JUMP[0] + 1) / (JUMP[1] - JUMP[0] + 2)
    return .3 * 4 * x * (1 - x)


def clip(rig, bones):
    """Key the source clip (see the module)."""
    label_of = {name: label for name, parent, head, label in bones}
    name_of = {label: name for name, parent, head, label in bones if label}
    rest = {name: Vector(head) for name, parent, head, label in bones}
    rest_matrices = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    for f in range(COUNT):
        lift = rise(f)
        roll = math.radians(25) * math.sin(math.pi * (f - ROLL[0]) / (ROLL[1] - ROLL[0])) if ROLL[0] <= f <= ROLL[1] else 0.0
        feet = {}
        for side in 'LR':
            ankle, ball = rest[name_of[f'{side}.foot']], rest[name_of[f'{side}.toe']]
            turn = Quaternion((1, 0, 0), roll) if side == 'L' else Quaternion()
            pivot = ball + Vector((0, 0, .002 * math.sin(1.7 * f) if side == 'L' and f < JUMP[0] else 0))
            pivot += Vector((-.2 * ramp(f, *SLIDE) if side == 'R' else 0, 0, 1.15 * lift))
            feet[side] = (pivot - turn @ (ball - ankle), turn)
        turns, heads = {}, {}
        for name, parent, head, label in bones:
            before = turns[parent] if parent else Quaternion()
            heads[name] = heads[parent] + turns[parent] @ (rest[name] - rest[parent]) if parent else rest[name].copy()
            if label == 'hips':
                heads[name] = rest[name] + Vector((0, 0, lift - CROUCH))
            side, role = label.split('.', 1) if label and label[1:2] == '.' else ('', label)
            if name == 'R_Prop':
                heads[name] += Vector((0, -.6 * ramp(f, *THROW), 0))
            if role == 'thigh':
                limb = [rest[name_of[f'{side}.{part}']] for part in ('thigh', 'calf', 'foot')]
                turns[name], turns[name_of[f'{side}.calf']] = reach(heads[name], limb, feet[side][0], Vector((0, -1, 0)), before)
            elif role == 'calf':
                pass
            elif role == 'foot':
                turns[name] = feet[side][1]
            elif role == 'toe':
                turns[name] = Quaternion()  # The toes stay flat as the foot rolls onto its ball.
            else:
                turns[name] = before
        for bone in rig.data.bones:
            pose = Matrix.LocRotScale(heads[bone.name], turns[bone.name] @ rest_matrices[bone.name].to_quaternion(), None)
            keywords = {}
            if bone.parent:
                parent = bone.parent.name
                keywords = dict(parent_matrix=Matrix.LocRotScale(heads[parent], turns[parent] @ rest_matrices[parent].to_quaternion(), None),
                                parent_matrix_local=rest_matrices[parent])
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(pose, rest_matrices[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f + 1)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f + 1)
    assert all(label_of[name] for name in name_of.values())


def track(rig):
    result = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result.append({bone.name: (rig.matrix_world @ bone.matrix).copy() for bone in rig.pose.bones})
    return result


def at(frames, name):
    return [frame[name].translation for frame in frames]


def bake(**options):
    for key, value in {**dict(method='BODY', foot_contacts='SPEED', jump_scale=False, prop_scale='NONE'), **options}.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, scene.sekiro_retarget.status
    return json.loads(scene['sekiro_retarget_report']), track(target)


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE
source_bones = with_prop(humanoids.proportioned(3))
source = armature('Source', source_bones)
clip(source, source_bones)
src = track(source)
# The target: shorter legs and a two-bone spine, its toes 8 cm further forward than its legs would put them.
target_bones = with_prop(humanoids.proportioned(2, legs=.85, thighs=.6, arms=(.9, 1.25)), toe=-.2)
target = armature('Target', target_bones)
names = {label: name for name, parent, head, label in target_bones if label}
settings = scene.sekiro_retarget
settings.source, settings.target = source, target
settings.rest_mode, settings.root_motion = 'ALIGN', 'NONE'
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
assert any(row.target == 'R_Prop' and row.source == 'R_Prop' for row in settings.rows)

# Body figures. Create figure places the parts on the joints, opens the figure in Edit Mode and shows the rig's rest
# pose, which the figure is fitted to.
assert figure.saved(target) is None
assert bpy.ops.sekiro_retarget.figure_create(role='target') == {'FINISHED'}
fitted = figure.edited(target)
assert fitted and fitted.mode == 'EDIT' and fitted.parent == target, fitted
assert target.data.pose_position == 'REST'
# While the figure is open, the bake would read the rest pose, so it refuses.
try:
    bpy.ops.sekiro_retarget.bake()
    raise AssertionError('baked with an open figure')
except RuntimeError as error:
    assert 'figure of Target is open' in str(error), error
bpy.ops.object.mode_set(mode='EDIT')
edit = fitted.data.edit_bones
for part, label in (('Pelvis', 'hips'), ('L Thigh', 'L.thigh'), ('L Calf', 'L.calf'), ('L Foot', 'L.foot'), ('R Hand', 'R.hand')):
    assert (edit[part].head - target.data.bones[names[label]].head_local).length < 1e-6, part
    assert edit[part][figure.LINK] == names[label], (part, edit[part][figure.LINK])
assert (edit['L Toe'].head - target.data.bones[names['L.toe']].head_local).length < 1e-6
assert edit['L Heel'].head.y > edit['L Foot'].head.y and edit['L Toe'].tail.y < edit['L Toe'].head.y  # Heel behind, tip ahead.
automatic = figure.measures(target)
# A part linked to a bone the skeleton does not have cannot be saved.
edit['L Calf'][figure.LINK] = 'No_Such_Bone'
try:
    bpy.ops.sekiro_retarget.figure_save(role='target')
    raise AssertionError('saved a figure part linked to a missing bone')
except RuntimeError as error:
    assert 'No_Such_Bone' in str(error), error
assert figure.saved(target) is None
bpy.ops.object.mode_set(mode='EDIT')
edit = fitted.data.edit_bones
edit['L Calf'][figure.LINK] = names['L.calf']
# The head reaches 25 cm higher than the automatic fit puts it: a tall helmet, say.
edit['Head'].tail += Vector((0, 0, .25))
assert bpy.ops.sekiro_retarget.figure_save(role='target') == {'FINISHED'}
assert figure.edited(target) is None and target.data.pose_position == 'POSE'  # Saving closes the figure.
kept = figure.saved(target)
files = list(Path(FOLDER).glob('*.json'))
assert kept and len(files) == 1 and files[0].name.endswith(figure.signature(target) + '.json'), files
measured = figure.measures(target, kept)
assert abs(measured['height'] - automatic['height'] - .25) < 1e-6, (measured['height'], automatic['height'])
assert abs(measured['leg'] - automatic['leg']) < 1e-9
# Another rig of the same skeleton finds it in the figure folder; one of another skeleton does not.
twin = armature('Twin', target_bones)
assert figure.KEY not in twin and figure.saved(twin)['parts'] == kept['parts']
assert figure.saved(source) is None
# Edit figure opens the saved one; opening it twice and closing it gives the rig back the pose position it had before.
for _ in range(2):
    assert bpy.ops.sekiro_retarget.figure_create(role='target') == {'FINISHED'} and target.data.pose_position == 'REST'
reopened = figure.read(figure.edited(target), target)['parts']
assert reopened.keys() == kept['parts'].keys() and all((Vector(reopened[part][1]) - Vector(tail)).length < 1e-6
                                                       for part, (head, tail, link) in kept['parts'].items())
assert bpy.ops.sekiro_retarget.figure_remove(role='target') == {'FINISHED'} and figure.edited(target) is None
assert target.data.pose_position == 'POSE' and figure.saved(target) is not None  # Closing keeps what was saved.
source.data.pose_position = 'REST'
assert bpy.ops.sekiro_retarget.figure_create(role='source') == {'FINISHED'}
assert bpy.ops.sekiro_retarget.figure_remove(role='source') == {'FINISHED'} and source.data.pose_position == 'REST'
source.data.pose_position = 'POSE'

# Planted, sliding, free, against the default contacts.
plain, plain_frames = bake()
assert plain['figures'] == [False, True], plain['figures']
pivot, pivot_frames = bake(foot_contacts='PIVOT')
steps = {item['side']: item for item in pivot['body']['footsteps']}
assert steps['L']['steps'] >= 1 and steps['L']['pivots'].get('ball'), steps['L']
# The slide's fast middle, in frames from 1, slides; its slow ends stay within the tolerance and stand.
assert steps['R']['slides'] >= 1 and set(range(SLIDE[0] + 3, SLIDE[1] - 1)) <= set(steps['R']['sliding']), steps['R']
ball = names['L.toe']
rolling = range(ROLL[0] + 2, ROLL[1] - 1)  # Inside the roll, away from where the ball's weight eases in.


def drift(frames):
    places = [frames[i][ball].translation for i in rolling]
    middle = sum(places, Vector()) / len(places)
    return max((place - middle).length for place in places)
assert drift(pivot_frames) < 1e-4 and drift(plain_frames) > 5e-3, (drift(pivot_frames), drift(plain_frames))
# The rest stance tilts the target's longer foot; sliding, it stands as high as when it stood before the slide.
rest_height = pivot_frames[SLIDE[0] - 1][names['R.foot']].translation.z
sliding = [abs(pivot_frames[i][names['R.foot']].translation.z - rest_height) for i in (f - 1 for f in steps['R']['sliding'])]
assert max(sliding) < 1e-3, sliding


def largest_step(frames, label):
    places = at(frames, names[label])
    return max((b - a).length for a, b in zip(places, places[1:]))
for label in ('L.foot', 'R.foot'):
    assert largest_step(pivot_frames, label) < largest_step(plain_frames, label) + .01, label

# Jumps: by the target's height against the source's, scaled by travel, with the time in the air kept.
for scaled in (True, False):  # The scaled run first: it finds the jump's frames.
    report, frames = bake(foot_contacts='PIVOT', jump_scale=scaled)
    travel = report['scale']
    ratio = report['jump_ratio'] if scaled else 1.0
    if scaled:
        jump_ratio = ratio
        jumps = report['body']['jumps']
        assert len(jumps) == 1, jumps
        start, end = jumps[0]['frames']
        expected = figure.measures(target, kept)['height'] / (travel * figure.measures(source)['height'])
        assert abs(ratio - expected) < 1e-6 and ratio > 1.1, (ratio, expected)
    hips_t, hips_s = at(frames, names['hips']), at(src, 'Hips')
    before, after = start - 2, end  # The frames on the ground at either end, by index.
    worst = 0.0
    for i in range(start - 1, end):
        share = (i - before) / (after - before)
        mine = hips_t[i].z - (hips_t[before].z + (hips_t[after].z - hips_t[before].z) * share)
        theirs = hips_s[i].z - (hips_s[before].z + (hips_s[after].z - hips_s[before].z) * share)
        worst = max(worst, abs(mine - ratio * travel * theirs))
    assert worst < 1e-4, (scaled, worst)
    if scaled:
        apex = (jumps[0]['rise'], jumps[0]['scaled'])

# Moving props.
hand, prop = names['R.hand'], 'R_Prop'
source_measures, target_measures = figure.measures(source), figure.measures(target, kept)
throwing = range(THROW[0] + 1, COUNT)
for method, mode, scale in [(method, *choice) for method in ('BODY', 'BONES') for choice in (
        ('NONE', None), ('HEIGHT', target_measures['height'] / source_measures['height']),
        ('LIMB', target_measures['arms']['R'] / source_measures['arms']['R']))]:
    report, frames = bake(prop_scale=mode, method=method)
    offsets = [frames[i][prop].translation - frames[i][hand].translation for i in throwing]
    if scale is None:
        rest = target.data.bones[prop].head_local - target.data.bones[hand].head_local
        assert not report['props'] and max((offset - rest).length for offset in offsets) < 1e-5, report['props']
        continue
    assert report['props'] == {prop: dict(holder=hand, anchor='R_Hand', ratio=report['props'][prop]['ratio'])}, report['props']
    assert abs(report['props'][prop]['ratio'] - scale) < 1e-6, (mode, report['props'][prop]['ratio'], scale)
    wanted = [(src[i][prop].translation - src[i]['R_Hand'].translation) * scale for i in throwing]
    assert max((a - b).length for a, b in zip(offsets, wanted)) < 1e-5, (method, mode)

# Without saved figures, the bake measures the automatic ones; deleting the figure removes its file.
report, frames = bake(foot_contacts='PIVOT', use_figures=False)
assert report['figures'] == [False, False]
settings.use_figures = True
assert bpy.ops.sekiro_retarget.figure_forget(role='target') == {'FINISHED'}
assert figure.saved(target) is None and figure.saved(twin) is None and not list(Path(FOLDER).glob('*.json'))
print(f"Biped options check passed: figures saved, found for the same skeleton and deleted; the planted ball drifts "
      f"{drift(pivot_frames) * 1000:.3f} mm with Biped contacts and {drift(plain_frames) * 1000:.1f} mm without; the slide "
      f"keeps the foot within {max(sliding) * 1000:.3f} mm of its height; the jump rises {apex[1] * 100:.1f} cm for "
      f"{apex[0] * 100:.1f} cm by leg length (ratio {jump_ratio:.3f}); props follow by height and by limb size within 0.01 mm "
      "with both bake methods.")
