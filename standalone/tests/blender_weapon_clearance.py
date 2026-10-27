"""Weapon matching, weapon alignment and body clearance of the retarget add-on on owned synthetic rigs and meshes.
Run with Blender --background --factory-startup --python this_file.py, and again with -- BODY after it to check the
same with the full-body bake.

A FromSoftware-style source brings both hands together in front of its belly while its right hand holds a
sword, skinned to R_Katana, and a gun that the clip hides by scaling it to zero. The target has the same
skeleton, 1.25 times larger, with a torso box far thicker than the source's arms allow for, hand meshes and a
sword on a weapon socket whose blade lies along another bone axis than the source's. Checked: the match takes
the sword bone and leaves the hidden gun; the baked blades stay parallel; without body clearance the hands go
into the torso, with it nothing near them does; frames away from contact keep the plain bake exactly; the push
eases in and out; and both hands on the hilt move together. Then the source gets hands and a torso of its own,
5 cm thinner in front than the target's, that still takes in its hands: the target keeps that clipping at its
own size, and only what its thicker torso adds is moved out.
"""
import json
import math
import sys
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
import sekiro_retarget
from sekiro_retarget import retarget

COUNT, RATE, SIZE = 72, 30, 1.25
METHOD = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'BONES'  # The bake method, BONES or BODY.
# Wrists on one hilt with bent elbows, in armature space; the target torso's front lies 6 cm further forward.
GOALS = {'R': Vector((-.05, -.18, 1.18)), 'L': Vector((.03, -.19, 1.22))}


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


def box(name, low, high, cuts, group_of, parent, rig=None, matrix=Matrix.Identity(4)):
    """A closed box mesh between two corners, cut into a grid; group_of(point) names each vertex's only group."""
    work = bmesh.new()
    bmesh.ops.create_cube(work, size=1.0)
    bmesh.ops.subdivide_edges(work, edges=work.edges[:], cuts=cuts, use_grid_fill=True)
    for vertex in work.verts:
        vertex.co = matrix @ Vector([low[i] + (vertex.co[i] + .5) * (high[i] - low[i]) for i in range(3)])
    mesh = bpy.data.meshes.new(name)
    work.to_mesh(mesh)
    work.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    if rig:
        for vertex in mesh.vertices:
            group = obj.vertex_groups.get(group_of(vertex.co)) or obj.vertex_groups.new(name=group_of(vertex.co))
            group.add([vertex.index], 1.0, 'REPLACE')
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


def animate(rig, bones):
    """Hands meet on a hilt in front of the belly between frames 15 and 25, hold, and part again by frame 57."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda bone: len(bone.parent_recursive))
    hold = {}
    for side, s in (('L', 1), ('R', -1)):
        shoulder, elbow, wrist = (rest[f'{side}_{name}'].translation for name in ('UpperArm', 'Forearm', 'Hand'))
        upper, fore = solve_arm(shoulder, elbow, wrist, GOALS[side], shoulder + Vector((s * .3, .1, -.2)))
        hold[f'{side}_UpperArm'], hold[f'{side}_Forearm'] = upper, upper.inverted() @ fore
    hold['Spine'] = Quaternion((0, 0, 1), .15)
    for f in range(COUNT):
        x = min(max((f + 1 - 15) / 10, 0), 1) * min(max((57 - (f + 1)) / 10, 0), 1)
        weight = x * x * (3 - 2 * x)
        deltas, poses = {}, {}
        for bone in ordered:
            own = Quaternion().slerp(hold[bone.name], weight) if bone.name in hold else Quaternion()
            deltas[bone.name] = (deltas[bone.parent.name] if bone.parent else Quaternion()) @ own
            head = poses[bone.parent.name] @ (rest[bone.parent.name].inverted() @ rest[bone.name]).translation \
                if bone.parent else rest[bone.name].translation
            poses[bone.name] = Matrix.LocRotScale(head, deltas[bone.name] @ rest[bone.name].to_quaternion(), None)
            keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=rest[bone.parent.name]) if bone.parent else {}
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f + 1)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f + 1)
            if bone.name == 'R_Gun':
                pose_bone.scale = (0, 0, 0)  # FromSoftware clips hide unused weapons this way.
                pose_bone.keyframe_insert('scale', frame=f + 1)


def world_points(obj):
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def long_axis(points):
    """Direction of a point cloud's largest spread, by power iteration on its covariance."""
    centre = sum(points, Vector()) / len(points)
    covariance = Matrix(((0, 0, 0), (0, 0, 0), (0, 0, 0)))
    for point in points:
        offset = point - centre
        covariance += Matrix(((offset.x * offset.x, offset.x * offset.y, offset.x * offset.z),
                              (offset.y * offset.x, offset.y * offset.y, offset.y * offset.z),
                              (offset.z * offset.x, offset.z * offset.y, offset.z * offset.z)))
    axis = Vector((1, 1, 1)).normalized()
    for _ in range(100):
        axis = (covariance @ axis).normalized()
    return axis


def inside(tree, point):
    """An odd number of surface crossings along a slanted ray: inside the closed torso box."""
    direction, crossings, origin = Vector((.31, .52, .8)).normalized(), 0, point.copy()
    for _ in range(50):
        location = tree.ray_cast(origin, direction)[0]
        if location is None:
            break
        crossings += 1
        origin = location + direction * 1e-5
    return crossings % 2 == 1


def deepest(tree, points):
    """How far the deepest of the points lies inside the closed mesh: its distance to the nearest surface."""
    return max((tree.find_nearest(point)[3] for point in points if inside(tree, point)), default=0.0)


def sample():
    """Per frame: pose matrices, hand heads, near-hand points inside the torso and how deep, and both blades' angle."""
    frames = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        wrists = {side: target.matrix_world @ target.pose.bones[f'{side}_Hand'].head for side in 'LR'}
        tree = BVHTree.FromPolygons(world_points(torso), [list(polygon.vertices) for polygon in torso.data.polygons])
        reach = .5 * ARM * SIZE
        points = world_points(hands[0]) + world_points(hands[1]) + world_points(sword)
        near = [p for p in points if min((p - w).length for w in wrists.values()) < reach]
        blade = target.matrix_world.to_quaternion().inverted() @ long_axis(world_points(sword))
        source_blade = source.matrix_world.to_quaternion().inverted() @ long_axis(world_points(source_sword))
        frames.append(dict(poses={bone.name: bone.matrix.copy() for bone in target.pose.bones}, wrists=wrists,
                           inside=sum(inside(tree, point) for point in near), depth=deepest(tree, near),
                           blades=math.degrees(min(blade.angle(source_blade), blade.angle(-source_blade)))))
    return frames


def source_depths():
    """Per frame, how deep the source's own hands and the sword near them go into the source torso."""
    depths = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        wrists = [source.matrix_world @ source.pose.bones[f'{side}_Hand'].head for side in 'LR']
        tree = BVHTree.FromPolygons(world_points(source_torso), [list(polygon.vertices) for polygon in source_torso.data.polygons])
        points = world_points(source_hands[0]) + world_points(source_hands[1]) + world_points(source_sword)
        depths.append(deepest(tree, [p for p in points if min((p - w).length for w in wrists) < .5 * ARM]))
    return depths


def hand(rig, side, name):
    """A box around a hand, between its wrist and its fingers, deformed by the hand bone alone."""
    centre = (Vector(heads[f'{side}_Hand']) + Vector(heads[f'{side}_Finger2'])) / 2
    return box(name, centre - Vector((.045, .025, .045)), centre + Vector((.045, .025, .045)), 1, lambda co: f'{side}_Hand', rig, rig)


def bake(**options):
    for key, value in options.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    return json.loads(scene['sekiro_retarget_report'])


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE

renamed = {'R_Weapon': 'R_Katana'}
source_bones = [(renamed.get(name, name), parent, head, label) for name, parent, head, label in humanoids.fromsoftware(45, 'elden')]
heads = {bone[0]: bone[2] for bone in source_bones}
source_bones.append(('R_Gun', 'R_Hand', heads['R_Katana'], None))
source = armature('Source', source_bones)
animate(source, source_bones)
katana = source.data.bones['R_Katana'].matrix_local
source_sword = box('Source sword', (-.015, -.12, -.006), (.015, .9, .006), 2, lambda co: 'R_Katana', source, source, katana)

target_bones = humanoids.fromsoftware(45, 'elden')
target = armature('Target', target_bones, Matrix.Translation((1.5, 0, 0)) @ Matrix.Scale(SIZE, 4))
ARM = (Vector(heads['R_Forearm']) - Vector(heads['R_UpperArm'])).length + (Vector(heads['R_Hand']) - Vector(heads['R_Forearm'])).length


def segment(co):
    return 'Pelvis' if co.z < 1.05 else 'Spine' if co.z < 1.2 else 'Spine1' if co.z < 1.33 else 'Spine2'


torso = box('Torso', (-.2, -.24, .95), (.2, .14, 1.45), 6, segment, target, target)
hands = [hand(target, side, f'{side} hand') for side in 'LR']
socket = bpy.data.objects.new('SWORD | Socket R_Weapon', None)
scene.collection.objects.link(socket)
socket.parent = target
constraint = socket.constraints.new('COPY_TRANSFORMS')
constraint.target, constraint.subtarget = target, 'R_Weapon'
sword = box('Sword', (-.12, -.006, -.015), (.9, .006, .015), 2, None, socket)  # Blade along the bone's X axis

settings = scene.sekiro_retarget
settings.method = METHOD
# The two swords lie along different axes of their bones, which the source's grip lines up from their shapes and the
# rest-relative grip, from the rest poses, does not.
settings.weapon_grip = 'SOURCE'
settings.source, settings.target = source, target
assert retarget.hidden_bones(source) == {'R_Gun'}, retarget.hidden_bones(source)
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row for row in settings.rows}
assert (rows['R_Weapon'].source, rows['R_Weapon'].reason) == ('R_Katana', 'Weapon in the matched hand'), \
    (rows['R_Weapon'].source, rows['R_Weapon'].reason)
assert not any(row.source == 'R_Gun' for row in settings.rows)

plain = bake(body_clearance=False)
# The source's blade lies along its bone's Y axis, flat side Z; the target's along X, flat side Y. Laying blade on blade
# and flat side on flat side takes X to Y, Y to Z and Z to X: 120 degrees about (1, 1, 1).
assert plain['weapons'] and abs(plain['weapons']['R_Weapon'] - 120) < 1, plain['weapons']
assert not plain['placed'], plain['placed']  # The socket rests at the hand that holds the sword: its own grip.
assert not plain['clearance'], plain['clearance']
before = sample()
contact = [i + 1 for i, frame in enumerate(before) if frame['inside']]
assert contact and contact[0] > 12 and contact[-1] < 60, f'the plain bake should clip while the hands meet: {contact}'

report = bake(body_clearance=True)
after = sample()
assert report['weapons'] == plain['weapons'], (report['weapons'], plain['weapons'])
worst_blades = max(frame['blades'] for frame in before + after)
assert worst_blades < 1, f'blades differ by {worst_blades:.2f} degrees'
clipping = [i + 1 for i, frame in enumerate(after) if frame['inside']]
assert not clipping, f'points near the hands stay inside the torso on frames {clipping}'
assert {item['side'] for item in report['clearance']} == {'L', 'R'}, report['clearance']
assert not any(item['unresolved'] for item in report['clearance']), report['clearance']
assert any('kept out of the body' in note for note in report['notes']), report['notes']
# The source has a sword but no torso: nothing to compare with, so all clipping goes.
assert report['source_clipping'] is False and any('no body mesh' in note for note in report['notes']), report

moved = [{side: frame['wrists'][side] - plain_frame['wrists'][side] for side in 'LR'} for frame, plain_frame in zip(after, before)]
# Each bake starts from the target as it was before any bake, so frames away from contact come out the same.
still = [i + 1 for i, shift in enumerate(moved) if max(vector.length for vector in shift.values()) < 1e-5]
assert still[:3] == [1, 2, 3] and still[-3:] == [COUNT - 2, COUNT - 1, COUNT], still
for frame in still:
    for name, matrix in after[frame - 1]['poses'].items():
        difference = max(abs(matrix[r][c] - before[frame - 1]['poses'][name][r][c]) for r in range(4) for c in range(4))
        assert difference < 1e-5, f'{name} changed on frame {frame}, away from any contact'
largest = max(shift['R'].length for shift in moved)
steepest = max(abs(moved[i + 1]['R'].length - moved[i]['R'].length) for i in range(COUNT - 1))
assert largest > .02 * SIZE and steepest < .25 * largest, (largest, steepest)
for i, frame in enumerate(before):
    if (frame['wrists']['L'] - frame['wrists']['R']).length < .4 * ARM * SIZE:
        assert (moved[i]['L'] - moved[i]['R']).length < 1e-4, f'the hands part on frame {i + 1}'

# The source clips on purpose: its torso front lies 5 cm behind the target's and still takes in its hands.
source_torso = box('Source torso', (-.2, -.19, .95), (.2, .14, 1.45), 6, segment, source, source)
source_hands = [hand(source, side, f'Source {side} hand') for side in 'LR']
own = source_depths()
report = bake(body_clearance=True)
kept = sample()
assert report['source_clipping'] is True, report
assert any("where the source's own hand goes into its body" in note for note in report['notes']), report['notes']
held = range(30, 43)  # Frames well inside the hold, where the push is steady.
expected = [SIZE * own[f - 1] for f in held]
actual = [kept[f - 1]['depth'] for f in held]
assert min(own[f - 1] for f in held) > .03, f'the source should clip by several centimetres: {own}'
assert all(abs(a - e) < .002 * SIZE for a, e in zip(actual, expected)), list(zip(expected, actual))
reported = max(item['kept'] for item in report['clearance'])
assert abs(reported - max(frame['depth'] for frame in kept)) < .002, (reported, max(frame['depth'] for frame in kept))
cleared = [f for f in range(1, COUNT + 1) if not own[f - 1] and kept[f - 1]['inside']]
assert not cleared, f'clipping that the source does not have stays on frames {cleared}'
print(f'Weapon and clearance checks passed{" with the full-body bake" if METHOD == "BODY" else ""}: blades within {worst_blades:.3f} degrees; plain bake clipped on frames '
      f'{contact[0]}-{contact[-1]}; hands moved by up to {largest * 100:.1f} cm, at most {steepest * 100:.2f} cm per frame; '
      f'{len(still)} frames unchanged; source clipping of {own[35] * 100:.1f} cm kept as {actual[6] * 100:.1f} cm on the '
      f'{SIZE} times larger target, within {max(abs(a - e) for a, e in zip(actual, expected)) * 1000:.1f} mm on frames 30-42 '
      f'(plain bake {before[35]["depth"] * 100:.1f} cm).')
