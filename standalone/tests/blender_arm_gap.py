"""Keep arms close to the body: the retarget add-on's arm distance on owned synthetic rigs and meshes.
Run with Blender --background --factory-startup --python this_file.py.

The source's torso box is far wider than its shoulders, so it holds its arms out to clear it, as a bulky
character does. The target has the same skeleton, 1.1 times larger, with a slim torso box. Both have box forearms
and hands. The source's clip holds its rest stance, swings its left arm up overhead, brings both hands together
in front of its belly and returns to rest. Checked: the plain bake leaves the target's arms far from its torso;
with the option, wherever the source's arm stands close to its body, the target's forearm and hand stand as
close to the target's torso at the target's size; the arm turns in at the shoulder with the elbow's bend and the
wrist as they were, and eases in and out; frames where the source's arm swings far from its body, or where both
hands are together, keep the plain bake; with Keep hands out of the body as well, the arms stand as close and no
hand goes into the torso; without a source body mesh the bake is the plain one; and a target whose torso is wider
than the source's is left alone.
"""
import json
import math
import sys
import time
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

COUNT, RATE, SIZE = 110, 30, 1.1
# Wrists together in front of the belly on frames 64-87, in armature space.
GOALS = {'L': Vector((.04, -.32, 1.2)), 'R': Vector((-.04, -.32, 1.2))}
# How far the bake's averaging carries a turn beyond its own frame: twice 0.1 s on either side.
REACH = 2 * round(.1 * RATE)


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


def box(name, low, high, group_of, rig, matrix=Matrix.Identity(4)):
    """A closed box mesh between two corners, cut once along each edge, skinned to the rig; group_of(point) names
    each vertex's only group."""
    work = bmesh.new()
    bmesh.ops.create_cube(work, size=1.0)
    bmesh.ops.subdivide_edges(work, edges=work.edges[:], cuts=1, use_grid_fill=True)
    for vertex in work.verts:
        vertex.co = matrix @ Vector([low[i] + (vertex.co[i] + .5) * (high[i] - low[i]) for i in range(3)])
    mesh = bpy.data.meshes.new(name)
    work.to_mesh(mesh)
    work.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = rig
    for vertex in mesh.vertices:
        group = obj.vertex_groups.get(group_of(vertex.co)) or obj.vertex_groups.new(name=group_of(vertex.co))
        group.add([vertex.index], 1.0, 'REPLACE')
    obj.modifiers.new('Armature', 'ARMATURE').object = rig
    return obj


def segment(co):
    return 'Pelvis' if co.z < 1.05 else 'Spine' if co.z < 1.2 else 'Spine1' if co.z < 1.33 else 'Spine2'


def torso(rig, name, half_width, half_depth):
    return box(name, (-half_width, -half_depth, .95), (half_width, half_depth, 1.45), segment, rig)


def arm_meshes(rig, prefix):
    """Per side, a box along the forearm and a box around the hand, each deformed by its bone alone."""
    result = {}
    for side in 'LR':
        forearm = rig.data.bones[f'{side}_Forearm']
        fore = box(f'{prefix} {side} forearm', (-.03, .02, -.03), (.03, forearm.length - .02, .03),
                   lambda co, name=forearm.name: name, rig, forearm.matrix_local)
        centre = (rig.data.bones[f'{side}_Hand'].head_local + rig.data.bones[f'{side}_Finger2'].head_local) / 2
        hand = box(f'{prefix} {side} hand', centre - Vector((.045, .025, .045)), centre + Vector((.045, .025, .045)),
                   lambda co, name=f'{side}_Hand': name, rig)
        result[side] = [fore, hand]
    return result


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


def ramp(frame, start, end):
    x = min(max((frame - start) / (end - start), 0.0), 1.0)
    return x * x * (3 - 2 * x)


def phases(frame):
    """How far the left arm's swing and the hands' meeting have come on a frame, 0 to 1."""
    return ramp(frame, 21, 29) * (1 - ramp(frame, 47, 55)), ramp(frame, 56, 64) * (1 - ramp(frame, 87, 95))


def animate(rig):
    """Rest stance on frames 1-20 and 96-110; the left arm swings up overhead on 21-55; the hands meet on 56-95."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda bone: len(bone.parent_recursive))
    swing = {'L_UpperArm': Quaternion((0, 1, 0), math.radians(-130))}
    hilt = {}
    for side, s in (('L', 1), ('R', -1)):
        shoulder, elbow, wrist = (rest[f'{side}_{name}'].translation for name in ('UpperArm', 'Forearm', 'Hand'))
        upper, fore = solve_arm(shoulder, elbow, wrist, GOALS[side], shoulder + Vector((s * .4, .1, -.2)))
        hilt[f'{side}_UpperArm'], hilt[f'{side}_Forearm'] = upper, upper.inverted() @ fore
    for f in range(1, COUNT + 1):
        weights = tuple(zip((swing, hilt), phases(f)))
        deltas, poses = {}, {}
        for bone in ordered:
            own = Quaternion()
            for hold, weight in weights:
                if bone.name in hold and weight:
                    own = Quaternion().slerp(hold[bone.name], weight)
            deltas[bone.name] = (deltas[bone.parent.name] if bone.parent else Quaternion()) @ own
            head = poses[bone.parent.name] @ (rest[bone.parent.name].inverted() @ rest[bone.name]).translation \
                if bone.parent else rest[bone.name].translation
            poses[bone.name] = Matrix.LocRotScale(head, deltas[bone.name] @ rest[bone.name].to_quaternion(), None)
            keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=rest[bone.parent.name]) if bone.parent else {}
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f)


def world_points(obj):
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def surface(obj):
    return BVHTree.FromPolygons(world_points(obj), [list(polygon.vertices) for polygon in obj.data.polygons])


def inside(tree, point):
    """An odd number of surface crossings along a slanted ray: inside the closed box."""
    direction, crossings, origin = Vector((.31, .52, .8)).normalized(), 0, point.copy()
    for _ in range(50):
        location = tree.ray_cast(origin, direction)[0]
        if location is None:
            break
        crossings += 1
        origin = location + direction * 1e-5
    return crossings % 2 == 1


def sample(rig, arms, body):
    """Per frame: pose matrices and, per side, the nearest approach of the arm boxes to the torso box in world units
    and how many hand vertices lie inside the torso."""
    frames = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        tree = surface(body)
        item = dict(poses={bone.name: bone.matrix.copy() for bone in rig.pose.bones}, inside=0)
        for side, objects in arms.items():
            item[side] = min(tree.find_nearest(point)[3] for obj in objects for point in world_points(obj))
            item['inside'] += sum(inside(tree, point) for point in world_points(objects[1]))
        frames.append(item)
    return frames


def bake(**options):
    for key, value in options.items():
        setattr(settings, key, value)
    started = time.perf_counter()
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    report = json.loads(scene['sekiro_retarget_report'])
    report['seconds'] = time.perf_counter() - started
    return report


def steady(flags):
    """Frames whose whole neighbourhood, as far as the bake's averaging reaches, has the flag."""
    return [f for f in range(1, COUNT + 1) if all(flags[g - 1] for g in range(max(1, f - REACH), min(COUNT, f + REACH) + 1))]


def same(frames, other, names, frame_numbers, tolerance=1e-5):
    for f in frame_numbers:
        for name in names:
            a, b = frames[f - 1]['poses'][name], other[f - 1]['poses'][name]
            difference = max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))
            assert difference < tolerance, f'{name} differs by {difference} on frame {f}'


def bend(poses, side):
    shoulder, elbow, wrist = (poses[f'{side}_{name}'].translation for name in ('UpperArm', 'Forearm', 'Hand'))
    return math.degrees((elbow - shoulder).angle(wrist - elbow))


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE

bones = humanoids.fromsoftware(45, 'elden')
source = armature('Source', bones)
animate(source)
target = armature('Target', bones, Matrix.Translation((1.5, 0, 0)) @ Matrix.Scale(SIZE, 4))
heads = {bone[0]: Vector(bone[2]) for bone in bones}
ARM = (heads['L_Forearm'] - heads['L_UpperArm']).length + (heads['L_Hand'] - heads['L_Forearm']).length
source_torso = torso(source, 'Source torso', .24, .15)
target_torso = torso(target, 'Target torso', .13, .12)
source_arms, target_arms = arm_meshes(source, 'Source'), arm_meshes(target, 'Target')
arm_bones = {side: {bone.name for bone in [target.data.bones[f'{side}_UpperArm'], *target.data.bones[f'{side}_UpperArm'].children_recursive]}
             for side in 'LR'}

settings = scene.sekiro_retarget
settings.source, settings.target = source, target
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row.source for row in settings.rows}
assert all(rows[f'{side}_{name}'] == f'{side}_{name}' for side in 'LR' for name in ('UpperArm', 'Forearm', 'Hand')), rows

own = sample(source, source_arms, source_torso)
plain = bake(arm_gap=False, body_clearance=False)
assert not plain['closeness'] and plain['arm_gaps'] is False, plain
before = sample(target, target_arms, target_torso)
wrists = [(frame['poses']['L_Hand'].translation - frame['poses']['R_Hand'].translation).length for frame in before]
together = [distance < .4 * ARM for distance in wrists]
close = {side: steady([frame[side] <= .25 * ARM and not apart for frame, apart in zip(own, together)]) for side in 'LR'}
far = steady([frame['L'] > .5 * ARM for frame in own])
gripped = steady(together)
assert len(close['R']) > 50 and len(close['L']) > 25 and len(far) > 8 and len(gripped) > 8, (close, far, gripped)
apart_before = min(before[f - 1][side] - SIZE * own[f - 1][side] for side in 'LR' for f in close[side])
assert apart_before > .05, f'the plain bake should leave the target arms well away from the torso: {apart_before}'

report = bake(arm_gap=True, body_clearance=False)
after = sample(target, target_arms, target_torso)
assert report['arm_gaps'] is True and {item['side'] for item in report['closeness']} == {'L', 'R'}, report['closeness']
assert any('arm turned in toward the body' in note for note in report['notes']), report['notes']
# Where the source's arm holds still, the gap matches; where it moves, averaging the turns over neighbouring frames
# leaves a small difference.
still = {'L': steady([phases(f) == (0, 0) for f in range(1, COUNT + 1)]), 'R': steady([phases(f)[1] == 0 for f in range(1, COUNT + 1)])}
errors = {side: {f: after[f - 1][side] - SIZE * own[f - 1][side] for f in close[side]} for side in 'LR'}
resting = [abs(errors[side][f]) for side in 'LR' for f in close[side] if f in still[side]]
moving = [abs(errors[side][f]) for side in 'LR' for f in close[side] if f not in still[side]]
assert len(resting) > 50 and max(resting) < .0005, (len(resting), max(resting))
assert moving and max(moving) < .01, errors
same(after, before, arm_bones['L'], far)
same(after, before, arm_bones['L'] | arm_bones['R'], gripped)
for item in report['closeness']:
    assert set(gripped) <= set(item['gripped']), (item['side'], item['gripped'])
for f in range(1, COUNT + 1):
    for side in 'LR':
        assert abs(bend(after[f - 1]['poses'], side) - bend(before[f - 1]['poses'], side)) < .01, f'{side} elbow bends on frame {f}'
        assert (after[f - 1]['poses'][f'{side}_UpperArm'].translation - before[f - 1]['poses'][f'{side}_UpperArm'].translation).length < 1e-6
        wrist = (after[f - 1]['poses'][f'{side}_Forearm'].inverted() @ after[f - 1]['poses'][f'{side}_Hand']).to_quaternion()
        plain_wrist = (before[f - 1]['poses'][f'{side}_Forearm'].inverted() @ before[f - 1]['poses'][f'{side}_Hand']).to_quaternion()
        assert math.degrees(wrist.rotation_difference(plain_wrist).angle) < .01, f'{side} wrist turns on frame {f}'
for side, s in (('L', 1), ('R', -1)):
    for f in close[side]:
        assert s * after[f - 1]['poses'][f'{side}_Hand'].translation.x < s * before[f - 1]['poses'][f'{side}_Hand'].translation.x - .01, \
            f'the {side} hand should come in toward the body on frame {f}'
moved = [{side: (frame['poses'][f'{side}_Hand'].translation - plain_frame['poses'][f'{side}_Hand'].translation).length
          for side in 'LR'} for frame, plain_frame in zip(after, before)]
largest = max(shift[side] for shift in moved for side in 'LR')
steepest = max(abs(moved[i + 1][side] - moved[i][side]) for i in range(COUNT - 1) for side in 'LR')
assert steepest < .25 * largest, (largest, steepest)
# The turns ease out before the hands meet, so none is left on any frame with the hands together, also at the edges.
same(after, before, arm_bones['L'] | arm_bones['R'], [f for f in range(1, COUNT + 1) if together[f - 1]])

# The averaging carries turns onto frames that need less. Where the right arm already stands close to the torso on
# a few frames, as another body shape can leave it, the turn carried over from the frames around stops at 2% of the
# arm's length. The frames come from both bakes: on frames 30-33 the arm stands where the option put it, and only
# the frames around ask to come in, all the way.
from sekiro_retarget import mapping, retarget
body = mapping.anatomy(retarget.rig_bones(target))
with retarget.rest_pose(target):
    geometry = retarget.body_geometry(target, body, bpy.context.evaluated_depsgraph_get())
near, floor = range(30, 34), .02 * geometry['sides']['R']['arm']
mixed = [dict((after if f in near else before)[f - 1]['poses']) for f in range(1, COUNT + 1)]


def limb_gaps(frames):
    return [retarget.nearest_gap(tree, arms['R'], 10)[0] for turn, tree, arms in retarget.limb_frames(target, body, geometry, frames)]


standing = limb_gaps(mixed)
assert all(standing[f - 1] > floor + .002 for f in near), ([standing[f - 1] for f in near], floor)
retarget.keep_close(target, body, geometry, mixed, RATE, {'R': [None if f in near else (0.0, 0.0) for f in range(1, COUNT + 1)]})
capped = limb_gaps(mixed)
assert min(capped) > floor - 1e-4, (min(capped), floor)
assert all(abs(capped[f - 1] - floor) < 5e-4 for f in near), ([capped[f - 1] for f in near], floor)

both = bake(arm_gap=True, body_clearance=True)
cleared = sample(target, target_arms, target_torso)
assert all(abs(cleared[f - 1][side] - after[f - 1][side]) < 1e-4 for side in 'LR' for f in close[side])
assert not any(frame['inside'] for frame in cleared), [f + 1 for f, frame in enumerate(cleared) if frame['inside']]

# Without the source's body mesh there is nothing to compare with.
source_torso.modifiers['Armature'].object = None
alone = bake(arm_gap=True, body_clearance=False)
assert alone['arm_gaps'] is False and not alone['closeness'], alone['closeness']
assert any('the source has no body mesh' in note for note in alone['notes']), alone['notes']
same(sample(target, target_arms, target_torso), before, [bone.name for bone in target.pose.bones], range(1, COUNT + 1), 1e-6)
source_torso.modifiers['Armature'].object = source

# A target wider than the source holds its arms against its torso already: nothing turns.
target_torso.modifiers['Armature'].object = None
wide = torso(target, 'Wide target torso', .34, .2)
untouched = bake(arm_gap=True, body_clearance=False)
assert untouched['arm_gaps'] is True and not any(item['frames'] for item in untouched['closeness']), untouched['closeness']
same(sample(target, target_arms, wide), before, [bone.name for bone in target.pose.bones], range(1, COUNT + 1), 1e-6)

turned = {item['side']: item for item in report['closeness']}
print(f"Arm distance checks passed: the plain bake left the target arms at least {apart_before * 100:.1f} cm farther from "
      f"its torso than the source's at its size; with the option, the gap matched within {max(resting) * 1000:.2f} mm on "
      f"{len(resting)} arm frames at rest and within {max(moving) * 1000:.1f} mm on {len(moving)} moving ones, the arms turned by up to "
      f"{max(item['angle'] for item in turned.values()):.1f} degrees and the hands moved by up to {largest * SIZE * 100:.1f} cm, "
      f"at most {steepest * SIZE * 100:.2f} cm per frame; {len(far)} frames of the left arm's swing and {sum(together)} frames with "
      f"the hands together kept the plain bake; on frames where the arm already stood close, the turns carried over from "
      f"the frames around stopped {min(capped[f - 1] for f in near) * SIZE * 1000:.1f} mm from the torso, at 2% of the arm "
      f"({floor * SIZE * 1000:.1f} mm); bake {plain['seconds']:.2f} s plain, {report['seconds']:.2f} s with the option.")
