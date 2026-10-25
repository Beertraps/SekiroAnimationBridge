"""Weapon grips and the second hand on a weapon, on owned synthetic rigs. Run with Blender --background
--factory-startup --python this_file.py.

An Isshin-like source holds a katana in its right hand, moved and turned in the fist away from its rest place, as
FromSoftware's clips hold weapons, with its fingers curled. On frames 20-41 it brings the right hand in front of its
belly and holds the hilt with its left hand too, behind the right one. The Wolf-like target is 1.1 times larger, its
blade along its weapon bone's Z axis, as Wolf's R_Weapon has it, and its own clip holds the weapon with another grip
and other finger curls. Checked: with the target's own grip, the default, the weapon sits in the hand as in the
target's own clip, with that clip's fingers, on every frame; with the blade following fully, the blade stays parallel
to the source's; with it off, the wrist turns as the source's does, as with the source's grip; halfway, the wrist
turns half as far; the source's grip puts the weapon where the source's sits in its palm, scaled to the hand, with
the source's blade direction and fingers; the left hand goes onto the hilt behind the right one on the frames where
the source's does, as far off the blade's axis as the source's, scaled, and leaves the left arm as it is elsewhere;
a target clip that does not animate the weapon takes the source's grip, with a note; and a target clip that hides the
weapon on every frame gets a warning. A target weapon that rests away from the hand, as Owl's katana rests a metre from
his, is placed in the hand where the source holds its weapon: with the target's own grip it then sits there as in the
target's own clip, with the source's grip it keeps that place, and so it does where the own clip hides it, with a note.
Last, a curved source katana and a target blade that curves toward another axis of its bone and is turned 130 degrees about
its own axis, held by a target whose fingers sit 15 degrees about the hand from the source's: with the source's grip
the blade lies in the target's palm as the source's lies in the source's palm, flat side, curve and all, and so
points away from the source's blade in the world.
"""
import json
import math
import sys
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
import sekiro_retarget

COUNT, RATE, SIZE = 60, 30, 1.1
# Where the source's right wrist goes on the two-handed frames, in front of its belly, and where its left hand's
# knuckles hold the hilt: this far behind the right hand's knuckles along the blade, and this far off its axis.
RIGHT_GOAL, BEHIND, OFF_AXIS = Vector((-.02, -.3, 1.22)), .09, .015
KNUCKLES = ('Finger1', 'Finger2', 'Finger3', 'Finger4')  # Index to little finger roots.
# The target's own grip: moved and turned in the hand away from the weapon bone's rest place.
OWN = Matrix.Translation((0, -.015, .01)) @ Quaternion((1, 0, 0), math.radians(15)).to_matrix().to_4x4()
LEFT_ARM = ('L_UpperArm', 'L_Forearm', 'L_Hand')


def armature(name, bones, matrix=Matrix.Identity(4)):
    """An armature whose bones sit at the given armature-space positions."""
    data = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    rig.matrix_world = matrix
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    children = {}
    for bone in bones:
        children.setdefault(bone[1], []).append(bone[0])
    heads = {bone[0]: Vector(bone[2]) for bone in bones}
    for name_, parent, head, label in bones:
        edit = data.edit_bones.new(name_)
        edit.head = heads[name_]
        tail = heads[children[name_][0]] if name_ in children else heads[name_] + Vector((0, 0, .05))
        edit.tail = tail if (tail - edit.head).length > 1e-4 else edit.head + Vector((0, 0, .05))
        if parent:
            edit.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def box(name, low, high, bone, rig, bend=None, turn=Matrix.Identity(4)):
    """A blade: a closed box between two corners in a bone's rest space, deformed by that bone alone. bend (along,
    toward, depth) curves it ahead of the bone, as a katana curves: depth along axis toward at the far end, growing
    with the square of the distance along axis along. turn then turns the box in the bone's space."""
    work = bmesh.new()
    bmesh.ops.create_cube(work, size=1.0)
    bmesh.ops.subdivide_edges(work, edges=work.edges[:], cuts=6 if bend else 2, use_grid_fill=True)
    matrix = rig.data.bones[bone].matrix_local
    for vertex in work.verts:
        local = Vector([low[i] + (vertex.co[i] + .5) * (high[i] - low[i]) for i in range(3)])
        if bend:
            along, toward, depth = bend
            local[toward] += depth * (max(local[along], 0) / high[along]) ** 2
        vertex.co = matrix @ turn @ local
    mesh = bpy.data.meshes.new(name)
    work.to_mesh(mesh)
    work.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = rig
    obj.vertex_groups.new(name=bone).add(list(range(len(mesh.vertices))), 1.0, 'REPLACE')
    obj.modifiers.new('Armature', 'ARMATURE').object = rig
    return obj


def solve_arm(shoulder, elbow, wrist, goal, pole):
    """World-space turns of the upper arm and forearm that put the wrist on goal, the elbow toward pole."""
    a, b = (elbow - shoulder).length, (wrist - elbow).length
    reach = goal - shoulder
    d, u = min(reach.length, a + b - 1e-4), reach.normalized()
    side = (pole - shoulder) - u * (pole - shoulder).dot(u)
    cosine = (a * a + d * d - b * b) / (2 * a * d)
    new_elbow = shoulder + (u * cosine + side.normalized() * math.sqrt(max(0.0, 1 - cosine * cosine))) * a
    upper = (elbow - shoulder).rotation_difference(new_elbow - shoulder)
    fore = (upper @ (wrist - elbow)).rotation_difference(shoulder + u * d - new_elbow) @ upper
    return upper, fore


def smooth(frame, start, end):
    """0 before start, 1 after end, easing in and out between."""
    x = min(max((frame - start) / (end - start), 0), 1)
    return x * x * (3 - 2 * x)


def curls(rig, degrees):
    """matrix_basis per finger bone of both hands: a turn about its own X axis by degrees[segment - 1], the thumb's
    half as far. FromSoftware names the segments L_Finger1, L_Finger11 and L_Finger12."""
    result = {}
    for bone in rig.data.bones:
        if '_Finger' in bone.name:
            digits = bone.name.split('_Finger')[1]
            angle = degrees[len(digits) - 1] * (.5 if digits[0] == '0' else 1)
            result[bone.name] = Quaternion((1, 0, 0), math.radians(angle)).to_matrix().to_4x4()
    return result


def forward(ordered, rest, turns, local, held):
    """Armature-space poses: a bone in held sits at held[name] relative to its parent, one in local turns by its
    matrix_basis local[name] under its parent, and any other bone turns in world space by turns[name], else by its
    parent's turn."""
    deltas, poses = {}, {}
    for bone in ordered:
        name, parent = bone.name, bone.parent.name if bone.parent else None
        if name in held:
            poses[name] = poses[parent] @ held[name]
        elif name in local:
            poses[name] = poses[parent] @ rest[parent].inverted() @ rest[name] @ local[name]
        else:
            delta = turns.get(name, deltas[parent] if parent else Quaternion())
            head = poses[parent] @ (rest[parent].inverted() @ rest[name]).translation if parent else rest[name].translation
            poses[name] = Matrix.LocRotScale(head, delta @ rest[name].to_quaternion(), None)
        deltas[name] = poses[name].to_quaternion() @ rest[name].to_quaternion().inverted()
    return poses


def knuckles(poses, side):
    return sum((poses[f'{side}_{name}'].translation for name in KNUCKLES), Vector()) / len(KNUCKLES)


def key(rig, ordered, rest, poses, frame):
    for bone in ordered:
        keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=rest[bone.parent.name]) if bone.parent else {}
        pose_bone = rig.pose.bones[bone.name]
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
        pose_bone.keyframe_insert('location', frame=frame)
        pose_bone.keyframe_insert('rotation_quaternion', frame=frame)


def animate_source(rig):
    """The right wrist goes in front of the belly between frames 12 and 20 and back between 41 and 49, the katana
    held in the fist by a grip of its own; meanwhile the left hand's knuckles go onto the hilt behind the right
    hand's. Returns where the left knuckles belong per frame."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda bone: len(bone.parent_recursive))
    curl = curls(rig, (50, 40, 30))
    # The blade lies along the bone's X axis, which this grip turns forward out of the fist and tilts up by 20°.
    grip = {'R_Katana': rest['R_Hand'].inverted() @ rest['R_Katana'] @ Matrix.Translation((.02, 0, -.01)) @
            (Quaternion((0, 1, 0), math.radians(-90)) @ Quaternion((0, 0, 1), math.radians(20))).to_matrix().to_4x4()}
    upper, fore = solve_arm(*(rest[f'R_{name}'].translation for name in ('UpperArm', 'Forearm', 'Hand')), RIGHT_GOAL,
                            rest['R_UpperArm'].translation + Vector((-.3, .1, -.2)))
    two_handed = forward(ordered, rest, {'R_UpperArm': upper, 'R_Forearm': fore}, curl, grip)
    katana = two_handed['R_Katana']
    axis, across = katana.to_quaternion() @ Vector((1, 0, 0)), katana.to_quaternion() @ Vector((0, 1, 0))
    along = (knuckles(two_handed, 'R') - katana.translation).dot(axis) - BEHIND
    goal = katana.translation + axis * along + across * OFF_AXIS
    # The left arm by two-bone IK: the knuckles turn with the hand, so a few rounds settle where the wrist goes.
    shoulder, elbow, wrist = (rest[name].translation for name in LEFT_ARM)
    offset, hand_turn = knuckles(rest, 'L') - wrist, Quaternion()
    for _ in range(12):
        left_upper, left_fore = solve_arm(shoulder, elbow, wrist, goal - hand_turn @ offset, shoulder + Vector((.3, .1, -.2)))
        hand_turn = left_fore
    goals = []
    for f in range(1, COUNT + 1):
        weight = smooth(f, 12, 20) * (1 - smooth(f, 41, 49))
        swing = Quaternion((0, 0, 1), .15 * math.sin(2 * math.pi * (f - 1) / (COUNT - 1)))
        turns = {'R_UpperArm': Quaternion().slerp(upper, weight), 'R_Forearm': Quaternion().slerp(fore, weight),
                 'L_UpperArm': Quaternion().slerp(left_upper, weight), 'L_Forearm': Quaternion().slerp(left_fore, weight)}
        if weight < 1e-9:
            turns['R_UpperArm'] = turns['R_Forearm'] = swing  # One-handed, the sword arm swings a little.
        key(rig, ordered, rest, forward(ordered, rest, turns, curl, grip), f)
        goals.append(goal if weight > 1 - 1e-9 else None)
    return goals


def target_rig(name, clip, x, away=(0, 0, 0), knuckle_turn=0.0, blade=None, thickness=.006):
    """A Wolf-like target with its own clip: 'own' holds the weapon by OWN with its own finger curls, 'hidden' also
    hides the weapon on every frame, 'bare' leaves the weapon unanimated. away moves the weapon bone's rest place from
    the hand; the clip still holds the weapon by OWN where it would rest in the hand. knuckle_turn turns the right
    hand's fingers by that many degrees about the line from the wrist to the knuckles, so that the bake turns this
    palm otherwise than the source's; blade gives box()'s bend and turn instead of a straight blade, and thickness
    half the blade's thickness."""
    bones = [(bone, parent, tuple(SIZE * value + (offset if bone == 'R_Weapon' else 0) for value, offset in zip(head, away)), label)
             for bone, parent, head, label in humanoids.fromsoftware(45, 'souls') if bone != 'L_Weapon']
    if knuckle_turn:
        heads = {bone: Vector(head) for bone, parent, head, label in bones}
        wrist = heads['R_Hand']
        line = (sum((heads[f'R_{finger}'] for finger in KNUCKLES), Vector()) / len(KNUCKLES) - wrist).normalized()
        turn = Matrix.Translation(wrist) @ Matrix.Rotation(math.radians(knuckle_turn), 4, line) @ Matrix.Translation(-wrist)
        bones = [(bone, parent, tuple(turn @ Vector(head)) if bone.startswith('R_Finger') else head, label)
                 for bone, parent, head, label in bones]
    rig = armature(name, bones, Matrix.Translation((x, 0, 0)))
    # Wolf's blade lies along his weapon bone's Z axis, with the hilt behind it.
    box(name + ' blade', (-thickness, -.015, -.2), (thickness, .015, .9), 'R_Weapon', rig, *(blade or ()))
    for bone_name, basis in curls(rig, (30, 20, 10)).items():
        pose_bone = rig.pose.bones[bone_name]
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = basis.to_quaternion()
        for frame in (1, COUNT):
            pose_bone.keyframe_insert('rotation_quaternion', frame=frame)
    if clip != 'bare':
        weapon = rig.pose.bones['R_Weapon']
        weapon.rotation_mode = 'QUATERNION'
        rest = rig.data.bones['R_Weapon'].matrix_local
        weapon.matrix_basis = rest.inverted() @ Matrix.Translation(-Vector(away)) @ rest @ OWN
        weapon.scale = (0, 0, 0) if clip == 'hidden' else (1, 1, 1)
        for frame in (1, COUNT):
            for field in ('location', 'rotation_quaternion', 'scale'):
                weapon.keyframe_insert(field, frame=frame)
    return rig


def sample(rig):
    frames = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        frames.append({bone.name: bone.matrix.copy() for bone in rig.pose.bones})
    return frames


def bake(**options):
    for name, value in options.items():
        setattr(settings, name, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    return json.loads(scene['sekiro_retarget_report']), sample(settings.target)


def rigid(matrix):
    return Matrix.LocRotScale(matrix.translation, matrix.to_quaternion(), None)


def angle(a, b):
    """Degrees between two rotations (matrices or quaternions), exact also for small angles."""
    a, b = (value if isinstance(value, Quaternion) else value.to_quaternion() for value in (a, b))
    turn = a.rotation_difference(b)
    return math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0])))


def lines(a, b):
    """Degrees between two directions."""
    return math.degrees(a.angle(b))


def palm(poses, side):
    """x from the wrist toward the knuckles, y from the little finger's root toward the index finger's, at the wrist."""
    wrist = poses[f'{side}_Hand'].translation
    roots = [poses[f'{side}_{name}'].translation for name in KNUCKLES]
    x = (sum(roots, Vector()) / len(roots) - wrist).normalized()
    across = roots[0] - roots[-1]
    y = (across - x * across.dot(x)).normalized()
    frame = Matrix((x, y, x.cross(y))).transposed().to_4x4()
    frame.translation = wrist
    return frame


def basis(rig, poses, name):
    bone = rig.data.bones[name]
    return bone.convert_local_to_pose(poses[name], bone.matrix_local, parent_matrix=poses[bone.parent.name],
                                      parent_matrix_local=bone.parent.matrix_local, invert=True)


def blade(frames, f):
    """The target's blade direction and the source's on frame f (0-based)."""
    return frames[f]['R_Weapon'].to_quaternion() @ Vector((0, 0, 1)), source_frames[f]['R_Katana'].to_quaternion() @ Vector((1, 0, 0))


def grip_errors(frames):
    """Largest (distance, degrees) of the weapon in the right hand from the target's own grip, over all frames."""
    distance = degrees = 0.0
    for poses in frames:
        held = rigid(poses['R_Hand']).inverted() @ rigid(poses['R_Weapon'])
        distance, degrees = max(distance, (held.translation - own_grip.translation).length), max(degrees, angle(held, own_grip))
    return distance, degrees


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE

source_bones = [('R_Katana' if name == 'R_Weapon' else name, parent, head, label)
                for name, parent, head, label in humanoids.fromsoftware(45, 'elden') if name != 'L_Weapon']
source = armature('Source', source_bones)
goals = animate_source(source)
box('Katana', (-.22, -.006, -.015), (1.0, .006, .015), 'R_Katana', source)
source_frames = sample(source)
reached = max((knuckles(poses, 'L') - goal).length for poses, goal in zip(source_frames, goals) if goal)
assert reached < 1e-4, f"the source's left knuckles miss the hilt by {reached * 1000:.2f} mm"
target = target_rig('Target', 'own', 1.5)
own_grip = target.data.bones['R_Hand'].matrix_local.inverted() @ target.data.bones['R_Weapon'].matrix_local @ OWN
own_fingers = curls(target, (30, 20, 10))
fingers = sorted(own_fingers)
right_fingers = [name for name in fingers if name.startswith('R_')]

settings = scene.sekiro_retarget
settings.source, settings.target = source, target
settings.body_clearance = settings.arm_gap = False
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row for row in settings.rows}
assert rows['R_Weapon'].source == 'R_Katana', (rows['R_Weapon'].source, rows['R_Weapon'].reason)

# The target's own grip with the blade following fully, the default.
full, full_frames = bake()
assert (full['weapon_grip'], full['blade_follow']) == ('OWN', 1.0), (full['weapon_grip'], full['blade_follow'])
assert full['grips']['R_Weapon']['mode'] == 'OWN' and full['grips']['R_Weapon']['frame'] == 1, full['grips']
assert any(note.startswith("R_Weapon sits in R_Hand as in the target's own clip on frame 1, with its fingers; the wrist "
                           "turns by up to") and note.endswith("so that the blade points as the source's does.")
           for note in full['notes']), full['notes']
assert not any('turned' in note and 'points like the source' in note for note in full['notes']), full['notes']
full_grip = grip_errors(full_frames)
assert full_grip[0] < 1e-4 and full_grip[1] < .05, ('the weapon should sit in the hand by the own grip', full_grip)
parallel = max(lines(*blade(full_frames, f)) for f in range(COUNT))
assert parallel < .1, f'the blade should point as the source\'s does, not {parallel:.3f} degrees off'
finger_error = max(angle(basis(target, poses, name), own_fingers[name]) for poses in full_frames for name in right_fingers)
assert finger_error < .05, f"the right hand's fingers should take the own clip's pose, not {finger_error:.3f} degrees off"

# With the blade not following, the wrist turns as the source's does: as with the source's grip, which does not turn it.
zero, zero_frames = bake(blade_follow=0)
assert "the wrist turns as the source's does." in ' '.join(zero['notes']) and zero['grips']['R_Weapon']['turn'] == 0
zero_grip = grip_errors(zero_frames)
assert zero_grip[0] < 1e-4 and zero_grip[1] < .05, ('the weapon should sit in the hand by the own grip', zero_grip)
borrowed, borrowed_frames = bake(weapon_grip='SOURCE', blade_follow=100)
same_wrist = max(max((a['R_Hand'].translation - b['R_Hand'].translation).length, 1e-3 * angle(a['R_Hand'], b['R_Hand']))
                 for a, b in zip(zero_frames, borrowed_frames))
assert same_wrist < 1e-5, f'without the blade following, the wrist should turn as with the source\'s grip: {same_wrist}'
off_line = max(lines(*blade(zero_frames, f)) for f in range(COUNT))
assert off_line > 5, f'the own grip should point the blade away from the source\'s without the blade following: {off_line:.2f}'

# Halfway, the wrist turns half as far about the same wrist.
half, half_frames = bake(weapon_grip='OWN', blade_follow=50)
halved = max(abs(angle(h['R_Hand'], z['R_Hand']) - .5 * angle(f['R_Hand'], z['R_Hand'])) +
             (h['R_Hand'].translation - z['R_Hand'].translation).length for h, f, z in zip(half_frames, full_frames, zero_frames))
assert halved < .02, f'at 50% the wrist should turn half as far as at 100%: off by {halved:.4f}'
assert "50% of the way to the source's" in ' '.join(half['notes']), half['notes']
assert abs(half['grips']['R_Weapon']['turn'] - .5 * full['grips']['R_Weapon']['turn']) < .05, (half['grips'], full['grips'])

# The source's grip: the weapon sits where the source's sits in its palm, scaled to the hand, pointing as the source's,
# and the fingers keep the source's curl.
assert borrowed['grips']['R_Weapon']['mode'] == 'SOURCE', borrowed['grips']
assert any(note.startswith("R_Weapon sits in R_Hand where the source's R_Katana sits in its hand, scaled to the hand")
           for note in borrowed['notes']), borrowed['notes']
spot = max(((palm(t, 'R').inverted() @ t['R_Weapon'].translation) - SIZE * (palm(s, 'R').inverted() @ s['R_Katana'].translation)).length
           for t, s in zip(borrowed_frames, source_frames))
assert spot < 1e-4, f"the weapon should sit where the source's sits in its palm, scaled to the hand: {spot * 1000:.3f} mm off"
borrowed_line = max(lines(*blade(borrowed_frames, f)) for f in range(COUNT))
assert borrowed_line < .1, f'with the source\'s grip the blade should point as the source\'s does: {borrowed_line:.3f} degrees'
rest_turn = {rig: {bone.name: bone.matrix_local.to_quaternion() for bone in rig.data.bones} for rig in (source, target)}
source_curl = max(angle(t[name].to_quaternion() @ rest_turn[target][name].inverted(), s[name].to_quaternion() @ rest_turn[source][name].inverted())
                  for t, s in zip(borrowed_frames, source_frames) for name in right_fingers)
assert source_curl < .05, f"with the source's grip the fingers should turn as the source's: {source_curl:.3f} degrees off"

# The second hand: the left hand's knuckles go onto the hilt behind the right hand's on the source's two-handed frames,
# as far off the blade's axis as the source's, scaled, and the arm stays as it is far from them.
seconds = {item['hand']: item for item in full['second_hands']}
assert set(seconds) == {'L_Hand'} and seconds['L_Hand']['weapon'] == 'R_Weapon' and seconds['L_Hand']['source'] == 'R_Katana', seconds
held = seconds['L_Hand']
both = [f for f, goal in enumerate(goals, 1) if goal]
assert set(range(both[0], both[-1] + 1)) <= set(held['frames']) and not held['short'] and held['gap'] < .01, held
assert f"Left hand goes onto R_Weapon on frames " in ' '.join(full['notes']), full['notes']
radial = along_error = 0.0
for f in both[4:-4]:  # Weights ease over 0.05 s, averaged twice: two frames each way, twice.
    poses = full_frames[f - 1]
    origin, axis = poses['R_Weapon'].translation, poses['R_Weapon'].to_quaternion() @ Vector((0, 0, 1))
    point = knuckles(poses, 'L') - origin
    along, main = point.dot(axis), (knuckles(poses, 'R') - origin).dot(axis)
    radial = max(radial, abs((point - axis * along).length - SIZE * OFF_AXIS))
    assert -.2 < along < main, f'the left hand should hold the hilt behind the right one on frame {f}: {along:.3f} m, right {main:.3f} m'
assert radial < .003, f"the left knuckles should sit as far off the blade's axis as the source's, scaled: {radial * 1000:.2f} mm off"
one, one_frames = bake(blade_follow=100, second_hand=False)
assert not one['second_hands'] and not any('goes onto' in note for note in one['notes']), one['second_hands']
left = [name for name in target.data.bones.keys() if name in LEFT_ARM or name.startswith('L_Finger')]
far = [f for f in range(1, COUNT + 1) if not both[0] - 10 <= f <= both[-1] + 10]
kept = max((full_frames[f - 1][name].translation - one_frames[f - 1][name].translation).length + 1e-3 * angle(
    full_frames[f - 1][name], one_frames[f - 1][name]) for f in far for name in left)
assert kept < 1e-6, f'the left arm should stay as it is far from the two-handed frames: {kept}'
alone = max(((knuckles(poses, 'L') - poses['R_Weapon'].translation) -
             (poses['R_Weapon'].to_quaternion() @ Vector((0, 0, 1))) * (knuckles(poses, 'L') - poses['R_Weapon'].translation).dot(
                 poses['R_Weapon'].to_quaternion() @ Vector((0, 0, 1)))).length for poses in (one_frames[f - 1] for f in both))

# A target clip that does not animate its weapon takes the source's grip, with a note.
bare = target_rig('Bare target', 'bare', 3.0)
settings.target = bare
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
assert {row.target: row.source for row in settings.rows}['R_Weapon'] == 'R_Katana'
fallback, fallback_frames = bake(weapon_grip='OWN', second_hand=True)
assert fallback['grips']['R_Weapon']['mode'] == 'SOURCE', fallback['grips']
assert "The target's own clip does not animate R_Weapon, so it takes the source's grip." in fallback['notes'], fallback['notes']

# A target clip that hides its weapon on every frame still gives the grip, with a warning.
hiding = target_rig('Hiding target', 'hidden', 4.5)
settings.target = hiding
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
hidden, hidden_frames = bake(weapon_grip='OWN')
assert hidden['grips']['R_Weapon']['mode'] == 'OWN', hidden['grips']
# The weapon shows on no frame, so the wrist has no blade to point.
assert "R_Weapon sits in R_Hand as in the target's own clip on frame 1, with its fingers; the wrist turns as the source's does." \
    in hidden['notes'], hidden['notes']
assert any(warning.startswith("The target's own clip hides R_Weapon on every frame") for warning in hidden['warnings']), hidden['warnings']

# A weapon that rests away from the hand is placed where the source holds its weapon. With the target's own grip it
# then sits in the hand as in the target's own clip, which holds it by the same grip as the first target's.
AWAY = (0, .8, -.3)
away = target_rig('Placed target', 'own', 6.0, AWAY)
settings.target = away
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
placed, placed_frames = bake(weapon_grip='OWN', blade_follow=100)
assert placed['placed'] == {'R_Weapon': 'R_Hand'} and placed['grips']['R_Weapon']['mode'] == 'OWN', (placed['placed'], placed['grips'])
assert not any(note.startswith('R_Weapon is placed in') for note in placed['notes']), placed['notes']
placed_grip = grip_errors(placed_frames)
assert placed_grip[0] < 1e-4 and placed_grip[1] < .05, ('the placed weapon should sit in the hand by the own grip', placed_grip)
placed_line = max(lines(*blade(placed_frames, f)) for f in range(COUNT))
assert placed_line < .1, f'the placed blade should point as the source\'s does, not {placed_line:.3f} degrees off'
# With the source's grip it keeps the place where the source holds its weapon.
kept_place, kept_frames = bake(weapon_grip='SOURCE')
assert not kept_place['grips'] and 'R_Weapon is placed in R_Hand, where the source holds R_Katana.' in kept_place['notes'], \
    (kept_place['grips'], kept_place['notes'])
assert grip_errors(kept_frames)[0] > .005, 'the source\'s place in the hand should differ from the own grip'
# An own clip that hides it on every frame leaves it there too, with a note instead of the warning.
away_hidden = target_rig('Placed hiding target', 'hidden', 7.5, AWAY)
settings.target = away_hidden
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
stays, stays_frames = bake(weapon_grip='OWN')
assert not stays['grips'], stays['grips']
assert "The target's own clip hides R_Weapon on every frame, so it stays where the source holds R_Katana; a target clip " \
       "that shows it gives its own grip." in stays['notes'], stays['notes']
assert not any(warning.startswith("The target's own clip hides") for warning in stays['warnings']), stays['warnings']
same_place = max((a['R_Weapon'].translation - b['R_Weapon'].translation).length + 1e-3 * angle(a['R_Weapon'], b['R_Weapon'])
                 for a, b in zip(stays_frames, kept_frames))
assert same_place < 1e-5, f'where the own clip hides it, the weapon should keep the source\'s place: {same_place}'

# Weapons authored otherwise and a palm that the bake turns otherwise. The source's katana curves toward its bone's Z
# axis, its flat side along Y; the target's blade curves toward its bone's Y axis, its flat side along X, and the
# whole blade is turned 130 degrees about its Z axis, so that the smallest turn from one long axis to the other leaves
# the edge facing elsewhere. The target's fingers sit 15 degrees about the line to the knuckles from the source's.
# With the source's grip, the blade lies in the palm as the source's lies in its palm: along the same line, its flat
# side the same way and its curve toward the same side.
curved_source = armature('Curved source', source_bones, Matrix.Translation((-1.5, 0, 0)))
animate_source(curved_source)
box('Curved katana', (-.22, -.003, -.015), (1.0, .003, .015), 'R_Katana', curved_source, (0, 2, .06))
curved_frames = sample(curved_source)
ROLL = Matrix.Rotation(math.radians(130), 4, 'Z')
rolled = target_rig('Rolled target', 'own', 9.0, knuckle_turn=15, blade=((2, 1, .05), ROLL), thickness=.003)
settings.source, settings.target = curved_source, rolled
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
assert {row.target: row.source for row in settings.rows}['R_Weapon'] == 'R_Katana'
laid, laid_frames = bake(weapon_grip='SOURCE')
assert laid['grips']['R_Weapon']['mode'] == 'SOURCE', laid['grips']
# The target's blade, flat side and curve in its bone's space, and the source's in its own.
model = {'blade': (ROLL @ Vector((0, 0, 1)), Vector((1, 0, 0))), 'flat': (ROLL @ Vector((1, 0, 0)), Vector((0, 1, 0))),
         'curve': (ROLL @ Vector((0, 1, 0)), Vector((0, 0, 1)))}
in_palm = dict.fromkeys(model, 0.0)
world_blade = 0.0
for t, s in zip(laid_frames, curved_frames):
    target_turn, source_turn = rigid(t['R_Weapon']).to_quaternion(), rigid(s['R_Katana']).to_quaternion()
    target_palm, source_palm = palm(t, 'R').to_quaternion(), palm(s, 'R').to_quaternion()
    for part, (target_line, source_line) in model.items():
        a = target_palm.inverted() @ target_turn @ target_line
        b = source_palm.inverted() @ source_turn @ source_line
        off = lines(a, b)
        in_palm[part] = max(in_palm[part], min(off, 180 - off) if part == 'flat' else off)
    world_blade = max(world_blade, lines(target_turn @ model['blade'][0], source_turn @ model['blade'][1]))
# The bake lays the meshes' long axes on each other, which the two curves tilt off their bones' axes by a little more
# and less; the flat sides lie square to both.
assert in_palm['flat'] < .1 and in_palm['blade'] < .5 and in_palm['curve'] < .5, \
    f"the blade should lie in the palm as the source's lies in its palm: {in_palm}"
assert world_blade > 5, f'the turned palm should turn the blade away from the source\'s in the world: {world_blade:.2f} degrees'
laid_spot = max(((palm(t, 'R').inverted() @ t['R_Weapon'].translation) - SIZE * (palm(s, 'R').inverted() @ s['R_Katana'].translation)).length
                for t, s in zip(laid_frames, curved_frames))
assert laid_spot < 1e-4, f"the weapon should sit where the source's sits in its palm, scaled to the hand: {laid_spot * 1000:.3f} mm off"

print(f"Weapon grip checks passed: own grip kept within {full_grip[0] * 1000:.4f} mm / {full_grip[1]:.4f} deg with the "
      f"wrist turned up to {full['grips']['R_Weapon']['turn']:.0f} deg, blade parallel within {parallel:.4f} deg, fingers "
      f"within {finger_error:.4f} deg; without blade follow the blade is up to {off_line:.0f} deg off and the wrist "
      f"matches the source grip's within {same_wrist:.1e}; halfway within {halved:.1e}; source grip in the palm within "
      f"{spot * 1000:.4f} mm, blade within {borrowed_line:.4f} deg; left hand on the hilt on frames {held['frames'][0]}-"
      f"{held['frames'][-1]}, off the axis as the source within {radial * 1000:.2f} mm (up to {alone * 100:.1f} cm without "
      f"the second hand), arm kept elsewhere within {kept:.1e}; fallback note and hidden-clip warning given; a weapon "
      f"resting away from the hand takes the own grip within {placed_grip[0] * 1000:.4f} mm, blade within "
      f"{placed_line:.4f} deg, and keeps the source's place with the source's grip or a hiding own clip; a curved blade "
      f"authored turned 130 deg about its axis, in a palm turned 15 deg, lies in the palm as the source's: flat side "
      f"within {in_palm['flat']:.4f} deg, blade and curve within {max(in_palm['blade'], in_palm['curve']):.2f} deg, place "
      f"within {laid_spot * 1000:.4f} mm, {world_blade:.1f} deg from the source's blade in the world.")
