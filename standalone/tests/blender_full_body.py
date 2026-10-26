"""Full-body bake against the bone-by-bone bake on owned synthetic rigs. Run with Blender --background --factory-startup --python this_file.py.

A Mixamo-style source, stored the way FBX imports arrive, squats with both feet planted, bends its spine forward,
brings its hands together in front of its chest and steps forward with its left foot while the right one stays
planted. Two targets of other proportions and bone counts take the clip, with matched rest stances and no root
motion: one with a two-bone spine, no clavicles, twist bones in its arms and legs, short legs with long thighs,
long forearms and an A-pose; one with a four-bone spine, long legs with short thighs, hip joints closer together
and short forearms. Each is baked bone by bone from the matched bone list and with the full-body method, and the
two bakes are compared by numbers: how far a planted foot slides and floats or sinks, how far the planted feet stand
from the target's own hip width plus the source's spread, scaled, how far the hands are from the source's contact
scaled by arm length, and how far the spine, limbs, elbows and knees point from the source's. The full-body bake
also runs on the first target with scrambled bone names and no bone list, and has to find the same body and give
the same pose; and on the second target from the same clip carried by a root-motion object that moves and turns
under the rig, where the body has to land where the game puts it just where it lands without root motion. Last, the
sideways move that sets the hip width has to hold still where a foot stands and turn with a swinging pelvis between.
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
from sekiro_retarget import fullbody, retarget

COUNT, RATE = 40, 30
TARGETS = dict(
    # A two-bone spine, no clavicles, twist bones in series, short legs with long thighs, long forearms, an A-pose.
    twisted=humanoids.proportioned(2, clavicles=False, twists=True, legs=.85, thighs=.6, arms=(.9, 1.25), arm_angle=40),
    # A four-bone spine, long legs with short thighs, the hip joints closer together, short forearms.
    tall=humanoids.proportioned(4, legs=1.2, thighs=.42, arms=(1.1, .85), hips=.6))


def armature(name, bones, matrix=Matrix.Identity(4), roll=0.0):
    """An armature whose bones sit at the given world positions."""
    data = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    rig.matrix_world = matrix
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    inverse = matrix.inverted()
    heads = {bone[0]: inverse @ Vector(bone[2]) for bone in bones}
    children = {}
    for bone in bones:
        children.setdefault(bone[1], []).append(bone[0])
    for bone_name, parent, head, label in bones:
        edit = data.edit_bones.new(bone_name)
        edit.head = heads[bone_name]
        tail = heads[children[bone_name][0]] if bone_name in children else heads[bone_name] + inverse.to_3x3() @ Vector((0, 0, .05))
        if (tail - edit.head).length < 1e-4:
            tail = edit.head + inverse.to_3x3() @ Vector((0, 0, .05))
        edit.tail, edit.roll = tail, roll
        if parent:
            edit.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def ramp(value, start, end):
    """0 up to start, 1 from end on, easing smoothly in between."""
    x = min(1.0, max(0.0, (value - start) / (end - start)))
    return x * x * (3 - 2 * x)


def reach(root, rest, goal, pole, before):
    """World turns of a two-bone limb whose first head is at root, so that its end lies on goal.

    rest holds the limb's three rest heads. The middle joint bends toward pole, and both bones keep the twist of
    before, the turn of the limb's parent.
    """
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


def clip(rig, bones, root=None):
    """Key the source clip: the hips drop 18 cm and come back up by 12 cm, the spine bends forward by 20 degrees,
    the hands meet in front of the chest from frame 9 to 27, and the left foot steps 25 cm forward on frames 17 to
    29 while the hips follow half way and turn by up to 9 degrees. Each foot stands still while it is not
    stepping; the legs and arms reach their goals by two-bone IK. With a root-motion object, root carries the hips'
    travel forward and turns by 30 degrees over the clip, and the rig keys the rest, so that root and rig together
    put every bone where the clip without it does, as the game places a bone by both."""
    parent_of = {name: parent for name, parent, head, label in bones}
    label_of = {name: label for name, parent, head, label in bones}
    name_of = {label: name for name, parent, head, label in bones if label}
    rest = {name: Vector(head) for name, parent, head, label in bones}
    chest = name_of['spine.last']
    middle = (rest[name_of['L.upperarm']] + rest[name_of['R.upperarm']]) / 2
    turn = rig.matrix_world.to_quaternion()
    to_rig = rig.matrix_world.inverted()
    rest_matrices = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    for f in range(COUNT):
        drop = .18 * ramp(f, 0, 10) - .12 * ramp(f, 30, 39)
        step = ramp(f, 16, 28)
        bend = .35 * (ramp(f, 2, 12) - ramp(f, 30, 39))
        together = ramp(f, 0, 8) - ramp(f, 26, 34)
        yaw = Quaternion((0, 0, 1), .15 * math.sin(math.pi * step))
        own = {'hips': yaw, 'spine.first': Quaternion((1, 0, 0), .45 * bend), 'spine.mid': Quaternion((1, 0, 0), .35 * bend),
               'spine.last': Quaternion((1, 0, 0), .2 * bend), 'neck': Quaternion((1, 0, 0), -.3 * bend)}
        feet = dict(L=rest[name_of['L.foot']] + Vector((0, -.25 * step, .06 * math.sin(math.pi * step))), R=rest[name_of['R.foot']])
        turns, heads, solved = {}, {}, {}
        for name, parent, head, label in bones:
            heads[name] = heads[parent] + turns[parent] @ (rest[name] - rest[parent]) if parent else \
                rest[name] + Vector((0, -.125 * step, -drop))
            before = turns[parent] if parent else Quaternion()
            side, role = label.split('.', 1) if label and label[1:2] == '.' else ('', label)
            if label in own:
                turns[name] = before @ own[label]
            elif role in ('thigh', 'upperarm'):
                if role == 'thigh':
                    chain, goal, pole = ('thigh', 'calf', 'foot'), feet[side], yaw @ Vector((0, -1, 0))
                else:
                    s = 1 if side == 'L' else -1
                    shoulder = heads[chest] + turns[chest] @ (rest[name] - rest[chest])
                    apart = shoulder + turns[chest] @ Vector((s * .4, -.12, -.25))
                    meet = heads[chest] + turns[chest] @ (middle - rest[chest] + Vector((s * .025, -.3, -.1)))
                    chain, goal, pole = ('upperarm', 'forearm', 'hand'), apart.lerp(meet, together), turns[chest] @ Vector((s * .3, .3, -1))
                limb = [rest[name_of[f'{side}.{part}']] for part in chain]
                turns[name], solved[name_of[f'{side}.{chain[1]}']] = reach(heads[name], limb, goal, pole, before)
            elif name in solved:
                turns[name] = solved[name]
            elif role == 'foot':
                turns[name] = Quaternion()
            else:
                turns[name] = before
        if root is not None:
            carry, spin = Vector((0, -.125 * step, 0)), math.radians(30) * ramp(f, 0, 39)
            back = Quaternion((0, 0, 1), -spin)
            heads = {name: back @ (head - carry) for name, head in heads.items()}
            turns = {name: back @ value for name, value in turns.items()}
            root.location, root.rotation_euler = carry, (0, 0, spin)
            root.keyframe_insert('location', frame=f + 1)
            root.keyframe_insert('rotation_euler', frame=f + 1)
        for bone in rig.data.bones:
            pose = Matrix.LocRotScale(to_rig @ heads[bone.name], turn.inverted() @ turns[bone.name] @ turn @ rest_matrices[bone.name].to_quaternion(), None)
            keywords = {}
            if bone.parent:
                parent = bone.parent.name
                keywords = dict(parent_matrix=Matrix.LocRotScale(to_rig @ heads[parent], turn.inverted() @ turns[parent] @ turn @ rest_matrices[parent].to_quaternion(), None),
                                parent_matrix_local=rest_matrices[parent])
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(pose, rest_matrices[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f + 1)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f + 1)
    assert all(label_of[name] for name in name_of.values())


def track(rig):
    """The world matrices of a rig's bones on every frame."""
    result = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result.append({bone.name: rig.matrix_world @ bone.matrix for bone in rig.pose.bones})
    return result


def placed(rig, root):
    """Where the game puts a rig's bones on every frame: its world matrices moved and turned by its root-motion object."""
    result = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        carry = Matrix.Translation(root.location) @ Matrix.Rotation(root.rotation_euler.z, 4, 'Z')
        result.append({bone.name: carry @ rig.matrix_world @ bone.matrix for bone in rig.pose.bones})
    return result


def apart(frames, other):
    """How far two takes of the same bones lie apart on their worst frame: (metres, degrees)."""
    def degrees(a, b):
        turn = a.to_quaternion().rotation_difference(b.to_quaternion())
        return math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0])))
    pairs = [(frame[name], other_frame[name]) for frame, other_frame in zip(frames, other) for name in frame]
    return max((a.translation - b.translation).length for a, b in pairs), max(degrees(a, b) for a, b in pairs)


def at(frames, name):
    return [frame[name].translation for frame in frames]


def angle(a, b):
    return math.degrees(a.angle(b)) if a.length > 1e-9 and b.length > 1e-9 else 0.0


def bend_plane(frame, chain):
    """Which way a limb's middle joint points: the normal of the plane it bends in, as long as the sine of the bend."""
    a, b, c = (frame[name].translation for name in chain)
    return (b - a).normalized().cross((c - b).normalized())


def bake(method):
    settings.method = method
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}
    return json.loads(scene['sekiro_retarget_report'])


def measure(src, tgt, names, rest, scale):
    """The comparison's numbers for one bake: target frames against the source's. scale is the bake's travel scale."""
    s, t = source_names, names
    result = dict(slide=0.0, worst=0.0, float=0.0, width=0.0, hands=0.0, spine=0.0, arms=0.0, legs=0.0, elbows=0.0, knees=0.0)
    standing = {}
    for side in 'LR':
        source_foot, target_foot = at(src, s[f'{side}.foot']), at(tgt, t[f'{side}.foot'])
        standing[side] = {i for i in range(1, COUNT) if (source_foot[i] - source_foot[i - 1]).length < 1e-5}
        for i in sorted(standing[side]):
            moved = (target_foot[i] - target_foot[i - 1]).length
            result['slide'] += moved
            result['worst'] = max(result['worst'], moved)
            result['float'] = max(result['float'], abs(target_foot[i].z - rest[t[f'{side}.foot']].z))
    # Where both feet stand, they should be the target's own hip joints apart plus the source's spread beyond its hip
    # joints, scaled; sideways is X, which the clip's steps keep square to.
    hip_joints = [rig_rest[n['L.thigh']].x - rig_rest[n['R.thigh']].x for rig_rest, n in ((source_rest, s), (rest, t))]
    for i in standing['L'] & standing['R']:
        apart = [frames[i][n['L.foot']].translation.x - frames[i][n['R.foot']].translation.x for frames, n in ((src, s), (tgt, t))]
        result['width'] = max(result['width'], abs(apart[1] - (hip_joints[1] + scale * (apart[0] - hip_joints[0]))))
    apart = [(frame[s['R.hand']].translation - frame[s['L.hand']].translation) for frame in src]
    close = [vector.length < .6 * source_forearm for vector in apart]
    for i in range(COUNT):
        if all(close[max(0, i - 5):i + 6]):  # Where the bake's contact weight, averaged over 0.05 s, is whole.
            gap = tgt[i][t['R.hand']].translation - tgt[i][t['L.hand']].translation
            result['hands'] = max(result['hands'], (gap - apart[i] * arm_ratio).length)
    for frame_s, frame_t in zip(src, tgt):
        def link(a, b, frame, n):
            return frame[n[b]].translation - frame[n[a]].translation
        result['spine'] = max(result['spine'], angle(link('spine.first', 'neck', frame_s, s), link('spine.first', 'neck', frame_t, t)))
        for key, links in (('arms', [('upperarm', 'forearm'), ('forearm', 'hand')]), ('legs', [('thigh', 'calf'), ('calf', 'foot')])):
            for side in 'LR':
                for a, b in links:
                    a, b = f'{side}.{a}', f'{side}.{b}'
                    result[key] = max(result[key], angle(link(a, b, frame_s, s), link(a, b, frame_t, t)))
        for key, chain in (('elbows', ('upperarm', 'forearm', 'hand')), ('knees', ('thigh', 'calf', 'foot'))):
            for side in 'LR':
                bent = bend_plane(frame_s, [s[f'{side}.{part}'] for part in chain])
                if bent.length > math.sin(math.radians(10)):  # A straighter limb points nowhere in particular.
                    result[key] = max(result[key], angle(bent, bend_plane(frame_t, [t[f'{side}.{part}'] for part in chain])))
    for key in ('slide', 'worst', 'float', 'width', 'hands'):
        result[key] *= 100
    return result


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE
source_bones = humanoids.mixamo(0)
source = armature('Source', source_bones, Matrix.Rotation(math.pi / 2, 4, 'X') @ Matrix.Scale(.01, 4), roll=.4)
clip(source, source_bones)
source_names = {label: name for name, parent, head, label in source_bones if label}
source_rest = {name: Vector(head) for name, parent, head, label in source_bones}
source_forearm = (source_rest[source_names['L.hand']] - source_rest[source_names['L.forearm']]).length
source_arm = source_forearm + (source_rest[source_names['L.forearm']] - source_rest[source_names['L.upperarm']]).length
src = track(source)
settings = scene.sekiro_retarget
settings.source = source
settings.rest_mode, settings.root_motion = 'ALIGN', 'NONE'

# The clip does what the comparison needs: both feet stand still for most of it, the hands meet, the knees bend.
planted = {side: sum((a - b).length < 1e-5 for a, b in zip(at(src, source_names[f'{side}.foot'])[1:], at(src, source_names[f'{side}.foot'])))
           for side in 'LR'}
assert planted['R'] == COUNT - 1 and 20 < planted['L'] < COUNT - 1, planted
meeting = min((frame[source_names['R.hand']].translation - frame[source_names['L.hand']].translation).length for frame in src)
assert abs(meeting - .05) < 1e-3, meeting
knee = max(angle(*(frame[source_names[f'L.{b}']].translation - frame[source_names[f'L.{a}']].translation
                   for a, b in (('thigh', 'calf'), ('calf', 'foot')))) for frame in src)
assert knee > 60, knee

rows, results = [], {}
for label, target_bones in TARGETS.items():
    target = armature('Target_' + label, target_bones)
    names = {tag: name for name, parent, head, tag in target_bones if tag}
    rest = {name: Vector(head) for name, parent, head, tag in target_bones}
    arm_ratio = sum((rest[names[f'L.{b}']] - rest[names[f'L.{a}']]).length for a, b in (('upperarm', 'forearm'), ('forearm', 'hand'))) / source_arm
    settings.target = target
    settings.method = 'BONES'
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    for method in ('BONES', 'BODY'):
        report = bake(method)
        assert report['bake_method'] == method, report
        frames = track(target)
        results[label, method] = dict(measure(src, frames, names, rest, report['scale']), report=report, frames=frames)
        rows.append((label, method.lower(), results[label, method]))
    body = results[label, 'BODY']['report']['body']
    assert body['unpaired'] == [] and body['target_shape'] == [] and body['source_shape'] == [], body

# Without names and without a bone list, the full-body bake finds the same body and bakes the same pose.
named = TARGETS['twisted']
scrambled = humanoids.scrambled(named, 7, 'Joint')
alias = {first[0]: second[0] for first, second in zip(named, scrambled)}
target = armature('Target_scrambled', scrambled)
settings.target = target
settings.rows.clear()
report = bake('BODY')
assert fullbody.parts(report['body']['target_shape']) == ['hips', 'spine', 'neck', 'head', 'arms', 'legs', 'fingers'], report['body']['target_shape']
frames = track(target)
reference = results['twisted', 'BODY']['frames']
differ = max((frames[i][alias[name]].translation - reference[i][name].translation).length for i in range(COUNT) for name in alias)
turned = max(frames[i][alias[name]].to_quaternion().rotation_difference(reference[i][name].to_quaternion()).angle
             for i in range(COUNT) for name in alias)
assert differ < 1e-5 and math.degrees(turned) < .01, (differ, math.degrees(turned))

# With root motion: the same clip on a root that moves and turns under the rig. Baked with the source's root motion,
# the tall target's bones land where the game puts them just where they land without it, at its own hip width and
# without sliding, so the feet are measured where the game puts them.
carried = armature('Carried source', source_bones, source.matrix_world, roll=.4)
root = bpy.data.objects.new('Carried root', None)
scene.collection.objects.link(root)
carried['sekiro_root_motion_data'] = root
clip(carried, source_bones, root)
assert max(apart(placed(carried, root), src)) < 1e-4, apart(placed(carried, root), src)
target = armature('Target_carried', TARGETS['tall'])
settings.source, settings.target, settings.root_motion = carried, target, 'SOURCE'
report = bake('BODY')
assert report['root_motion'] == 'SOURCE', report['root_motion']
# The Root bone above the hips keeps its rest pose in the rig, so the root motion carries it away; the body does not.
body_bones = {bone.name for bone in target.data.bones if 'Hips' in [bone.name] + [parent.name for parent in bone.parent_recursive]}
along = apart([{name: frame[name] for name in body_bones} for frame in placed(target, retarget.root_object(target))],
              results['tall', 'BODY']['frames'])
assert along[0] < 1e-4 and along[1] < .01, along

# The sideways move that sets the hip width holds still where a foot stands and turns with the pelvis while it steps,
# however far the pelvis swings: here it turns 8 degrees over the first stand, swings 80 degrees one way and 160 back
# while the foot steps, and turns 8 more over the second stand.
up = Vector((0, 0, 1))
yaws = list(range(9)) + [8 - 10 * i for i in range(1, 9)] + [-72 + 16 * i for i in range(1, 11)] + [88 + i for i in range(9)]
stands = [True] * 9 + [False] * 18 + [True] * 9
sides = fullbody.held([Quaternion(up, math.radians(yaw)) @ Vector((1, 0, 0)) for yaw in yaws], stands, up)
turns = [math.degrees(math.atan2(side.y, side.x)) for side in sides]
assert max(abs(turn - 4) for turn in turns[:9]) < 1e-4 and max(abs(turn - 92) for turn in turns[-9:]) < 1e-4, turns
# Off the pelvis by no more than it is off at the ends of the stands, and no step larger than the pelvis's own.
swing = max(abs(turn - yaw) for turn, yaw in zip(turns, yaws))
steps = max(abs(b - a) for a, b in zip(turns, turns[1:]))
assert swing < 4 + 1e-4 and steps < max(abs(b - a) for a, b in zip(yaws, yaws[1:])) + 1, (swing, steps, turns)

# slide: how far the planted feet move in all, worst: on one frame, float: how far a planted foot rises or sinks
# from its rest height, width: how far the planted feet's distance apart is from the target's own hip width plus the
# source's spread, scaled, hands: how far the hands are from the source's contact scaled by arm length, spine: the
# chord from the first spine bone to the neck, arms and legs: each limb bone's direction, elbows and knees: the
# plane each limb bends in, where the source's bends by 10 degrees or more.
KEYS = ('slide', 'worst', 'float', 'width', 'hands', 'spine', 'arms', 'legs', 'elbows', 'knees')
print(f'Full body against bone by bone, {COUNT} frames; feet and hands in cm, directions in degrees, each on its worst frame:')
print(f'{"target":8} {"method":6} ' + ' '.join(f'{key:>6}' for key in KEYS))
for label, method, numbers in rows:
    print(f'{label:8} {method:6} ' + ' '.join(f'{numbers[key]:6.2f}' for key in KEYS))
print('Pelvis lowered by up to ' + ', '.join(f"{results[label, 'BODY']['report']['body']['drop'] * 100:.2f} cm ({label})" for label in TARGETS))
for label in TARGETS:
    bones, body = results[label, 'BONES'], results[label, 'BODY']
    # Bone by bone, the limbs point exactly like the source's, so with other proportions the feet slide and float,
    # and the hands miss each other.
    assert bones['arms'] < .01 and bones['legs'] < .01 and bones['elbows'] < .01 and bones['knees'] < .01, (label, bones)
    assert bones['slide'] > 10 and bones['float'] > 1 and bones['hands'] > 1, (label, bones)
    # Full body, the feet stand where the source's stand, scaled, at the target's own hip width, the hands meet as the
    # source's do and the spine's chord points like the source's. The limbs give up some of their direction for that,
    # hardly where they bend to.
    assert body['slide'] < .01 and body['float'] < .05 and body['width'] < .05 and body['hands'] < .05 and \
        body['spine'] < min(.05, bones['spine']), (label, body)
    assert body['arms'] < 10 and body['legs'] < 15 and body['elbows'] < 10 and body['knees'] < 1, (label, body)
print(f"Full-body check passed: planted feet slide up to {max(results[label, 'BONES']['slide'] for label in TARGETS):.1f} cm "
      f"bone by bone and {max(results[label, 'BODY']['slide'] for label in TARGETS):.2f} cm full body, at the target's own hip "
      f"width within {max(results[label, 'BODY']['width'] for label in TARGETS):.2f} cm, hands miss by up to "
      f"{max(results[label, 'BONES']['hands'] for label in TARGETS):.1f} and {max(results[label, 'BODY']['hands'] for label in TARGETS):.2f} cm, "
      f"the scrambled target bakes the same pose without names, with root motion the body lands where it does without "
      f"it within {along[0] * 1000:.3f} mm and {along[1]:.3f} degrees, and the hip-width move stays within {swing:.1f} "
      f"degrees of a pelvis that swings 160 degrees between two stands")
