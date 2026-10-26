"""Weapons that change hands, weapon bones that rest away from the hand, and weapons that the map hides, on owned
synthetic rigs. Run with Blender --background --factory-startup --python this_file.py, and again with -- BODY after
it to check the same with the full-body bake.

A Godfrey-like source holds an axe in its left hand and nothing in its right. Its clip hides the axe on the
first two frames, then slides it along the hand and tilts it, while the right hand goes into the belly. The
target is Isshin-like and 1.2 times larger: a katana with a scabbard below it at its right hand, and a spear and
a gun that rest 1.5 m and 1.2 m from its left hand and that its own clip hides by scaling them to zero. Checked:
the match gives the katana the axe from the other hand; the bake puts the katana in the target's left hand on the
axe's line, scaled, with its grip in the hand while the axe slides, turned like the axe and hidden at 0.1% while
the axe is, so that the scabbard keeps its own channels; keeping the right hand out of the torso leaves the katana
with the left hand; giving the axe to the spear takes it from the katana, which stays in the right hand, and shows
the spear in the left hand like the axe although the target clip hides it; an axe mesh along another bone axis
than the spear's turns the spear so that both stay parallel, with its grip in the hand along the axe mesh's line;
and hiding the katana and the spear in the map shrinks both to 0.1% on every frame where they would be, the
scabbard with the katana, and stays in the map through saving and loading it.
"""
import json
import math
import sys
import tempfile
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
import sekiro_retarget
from sekiro_retarget import retarget

COUNT, RATE, SIZE = 60, 30, 1.2
METHOD = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'BONES'  # The bake method, BONES or BODY.
# The right wrist on frames 25-45, in armature space: 4 cm inside the target torso's front.
GOAL = Vector((-.08, -.2, 1.15))


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


def smooth(frame, start, end):
    """0 before start, 1 after end, easing in and out between."""
    x = min(max((frame - start) / (end - start), 0), 1)
    return x * x * (3 - 2 * x)


def animate(rig):
    """The right wrist goes to GOAL between frames 15 and 25 and back between 45 and 55. The left arm swings
    forward and back while the axe slides along the hand and tilts; the clip hides the axe on frames 1 and 2."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda bone: len(bone.parent_recursive))
    shoulder, elbow, wrist = (rest[f'R_{name}'].translation for name in ('UpperArm', 'Forearm', 'Hand'))
    upper, fore = solve_arm(shoulder, elbow, wrist, GOAL, shoulder + Vector((-.3, .1, -.2)))
    grip = rest['L_Hand'].inverted() @ rest['L_Axe']
    for f in range(1, COUNT + 1):
        weight = smooth(f, 15, 25) * (1 - smooth(f, 45, 55))
        phase = 2 * math.pi * (f - 1) / (COUNT - 1)
        turns = {'R_UpperArm': Quaternion().slerp(upper, weight), 'R_Forearm': Quaternion().slerp(fore, weight),
                 'L_UpperArm': Quaternion((1, 0, 0), .5 * math.sin(phase))}
        deltas, poses = {}, {}
        for bone in ordered:
            deltas[bone.name] = turns.get(bone.name, deltas[bone.parent.name] if bone.parent else Quaternion())
            head = poses[bone.parent.name] @ (rest[bone.parent.name].inverted() @ rest[bone.name]).translation \
                if bone.parent else rest[bone.name].translation
            poses[bone.name] = Matrix.LocRotScale(head, deltas[bone.name] @ rest[bone.name].to_quaternion(), None)
        # The axe slides along its X axis in the hand, as Godfrey's does in his two-handed grip.
        poses['L_Axe'] = (poses['L_Hand'] @ grip @ Matrix.Translation((.15 * math.sin(2 * phase), 0, 0)) @
                          Quaternion((0, 0, 1), .6 * math.sin(phase)).to_matrix().to_4x4())
        for bone in ordered:
            keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=rest[bone.parent.name]) if bone.parent else {}
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f)
        axe = rig.pose.bones['L_Axe']
        axe.scale = (0, 0, 0) if f <= 2 else (1, 1, 1)
        axe.keyframe_insert('scale', frame=f)


def world(rig, name):
    return rig.matrix_world @ rig.pose.bones[name].matrix


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


def bake(**options):
    for key, value in options.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    report = json.loads(scene['sekiro_retarget_report'])
    values = [value for curve in retarget.action_curves(bpy.data.actions[report['action']])
              for point in curve.keyframe_points for value in point.co]
    assert all(math.isfinite(value) for value in values), 'the baked action has values that are not numbers'
    return report


def placement(name, axis=Vector((1, 0, 0))):
    """Per frame: how far a target weapon lies from where it belongs, which is the axe's offset from the left hand,
    scaled to the target, less its part along the axe's line, given by axis in the axe bone; how far its rotation
    differs from the axe's, in degrees; its scale; its world matrix; the right wrist."""
    rest = source.matrix_world.to_quaternion() @ source.data.bones['L_Axe'].matrix_local.to_quaternion()
    frames = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        weapon, axe = world(target, name), world(source, 'L_Axe')
        line = (axe.to_3x3().normalized().to_quaternion() if min(axe.to_scale()) > 1e-6 else rest) @ axis
        offset = weapon.translation - world(target, 'L_Hand').translation
        wanted = SIZE * (axe.translation - world(source, 'L_Hand').translation)
        wanted -= line * wanted.dot(line)
        turn = weapon.to_3x3().normalized().to_quaternion().rotation_difference(axe.to_3x3().normalized().to_quaternion())
        frames.append(dict(error=(offset - wanted).length, turn=math.degrees(min(turn.angle, 2 * math.pi - turn.angle)),
                           scale=target.pose.bones[name].matrix.to_scale(), matrix=weapon, right=world(target, 'R_Hand').translation))
    return frames


def follows(frames, name, turned=True):
    """Checks that a weapon sits where it belongs on every frame, is hidden at 0.1% where the axe is hidden at 0 and
    otherwise shown and, unless the bake turned it for its mesh, turned like the axe; returns the largest offset error."""
    for frame, item in enumerate(frames, 1):
        assert item['error'] < 1e-4, f"{name} lies {item['error'] * 1000:.2f} mm from where it belongs on frame {frame}"
        if frame <= 2:
            assert all(abs(value - retarget.HIDDEN) < 1e-6 for value in item['scale']), \
                f'{name} is not hidden at {retarget.HIDDEN} on frame {frame}, where the source hides the axe: {item["scale"]}'
            continue
        assert all(abs(value - 1) < 1e-4 for value in item['scale']), f"{name} has scale {item['scale']} on frame {frame}"
        assert not turned or item['turn'] < .05, f"{name} differs from the axe by {item['turn']:.3f} degrees on frame {frame}"
    return max(item['error'] for item in frames)


def scabbard_keeps_channels(stage):
    """Checks that the scabbard below the katana keeps its own channels on every frame, also where the katana is
    hidden: a katana scaled to 0 has no inverse to place it against."""
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        basis = target.pose.bones['R_Katana_Saya'].matrix_basis
        drift = max(abs(basis[r][c] - (r == c)) for r in range(4) for c in range(4))
        assert drift < 1e-3, f'{stage}: the scabbard is {drift} off its own channels on frame {frame}'


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE

source_bones = [('L_Axe' if name == 'L_Weapon' else name, parent, head, label)
                for name, parent, head, label in humanoids.fromsoftware(45, 'elden') if name != 'R_Weapon']
source = armature('Source', source_bones)
animate(source)

renamed = {'R_Weapon': 'R_Katana', 'L_Weapon': 'L_Yari'}
target_bones = [(renamed.get(name, name), parent, head, label) for name, parent, head, label in humanoids.fromsoftware(0, 'souls')]
wrist = Vector(next(head for name, parent, head, label in target_bones if name == 'L_Hand'))
away = {'L_Yari': wrist + Vector((.9, 0, -1.2)), 'L_Gun': wrist + Vector((.72, .4, -.9))}
target_bones = [(name, parent, tuple(away[name]) if name in away else head, label) for name, parent, head, label in target_bones]
target_bones.append(('L_Gun', 'L_Hand', tuple(away['L_Gun']), None))
# A scabbard below the katana, where the katana's tail would be without it, so that the katana keeps its rest frame.
katana_head = Vector(next(head for name, parent, head, label in target_bones if name == 'R_Katana'))
target_bones.append(('R_Katana_Saya', 'R_Katana', tuple(katana_head + Vector((0, 0, .05))), None))
target = armature('Target', target_bones, Matrix.Translation((1.5, 0, 0)) @ Matrix.Scale(SIZE, 4))
for name in ('L_Yari', 'L_Gun'):
    pose_bone = target.pose.bones[name]
    pose_bone.scale = (0, 0, 0)  # The target clip hides the weapons it does not use, as Isshin's clips do.
    for frame in (1, COUNT):
        pose_bone.keyframe_insert('scale', frame=frame)


def segment(co):
    return 'Pelvis' if co.z < 1.05 else 'Spine' if co.z < 1.2 else 'Spine1' if co.z < 1.33 else 'Spine2'


def hand(side):
    """A box around a target hand, between its wrist and its fingers, deformed by the hand bone alone."""
    centre = (target.data.bones[f'{side}_Hand'].head_local + target.data.bones[f'{side}_Finger2'].head_local) / 2
    return box(f'{side} hand', centre - Vector((.045, .025, .045)), centre + Vector((.045, .025, .045)), 1,
               lambda co: f'{side}_Hand', target, target)


torso = box('Torso', (-.2, -.24, .95), (.2, .14, 1.45), 6, segment, target, target)
hands = [hand(side) for side in 'LR']
# Both blades lie along their bone's X axis, as FromSoftware's do.
katana = box('Katana', (-.12, -.006, -.015), (.9, .006, .015), 2, lambda co: 'R_Katana', target, target,
             target.data.bones['R_Katana'].matrix_local)
spear = box('Spear', (-.5, -.012, -.012), (1.5, .012, .012), 2, lambda co: 'L_Yari', target, target,
            target.data.bones['L_Yari'].matrix_local)

settings = scene.sekiro_retarget
settings.method = METHOD
settings.source, settings.target = source, target
assert retarget.hidden_bones(target) == {'L_Yari', 'L_Gun'} and not retarget.hidden_bones(source), retarget.hidden_bones(target)
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row for row in settings.rows}
assert (rows['R_Katana'].source, rows['R_Katana'].reason) == ('L_Axe', 'Weapon from the other hand'), \
    (rows['R_Katana'].source, rows['R_Katana'].reason)
assert abs(rows['R_Katana'].confidence - .8) < 1e-6
assert rows['L_Yari'].source == rows['L_Gun'].source == rows['R_Katana_Saya'].source == '' and not any(row.hidden for row in settings.rows)

plain = bake(body_clearance=False)
assert plain['placed'] == {'R_Katana': 'L_Hand'} and plain['hidden'] == [], (plain['placed'], plain['hidden'])
assert 'R_Katana is placed in L_Hand, where the source holds L_Axe.' in plain['notes'], plain['notes']
assert abs(plain['scale'] - SIZE) < 1e-3, plain['scale']
switched = placement('R_Katana')
switch_error = follows(switched, 'R_Katana')
scabbard_keeps_channels('placed katana')

# The right hand goes into the torso and is moved out; the katana in the left hand stays where it was.
cleared = bake(body_clearance=True)
kept = placement('R_Katana')
pushed = {item['side']: item for item in cleared['clearance']}
assert set(pushed) == {'R'} and pushed['R']['frames'], cleared['clearance']
follows(kept, 'R_Katana with body clearance')
moved = max((item['right'] - other['right']).length for item, other in zip(kept, switched))
assert moved > .02 * SIZE, f'the right hand should be moved out of the torso: {moved}'
shift = max(abs(item['matrix'][r][c] - other['matrix'][r][c]) for item, other in zip(kept, switched) for r in range(4) for c in range(4))
assert shift < 1e-5, f'the katana in the left hand moved by {shift} with the right hand'

# Giving the axe to the spear takes it from the katana.
rows['L_Yari'].source = 'L_Axe'
assert (rows['L_Yari'].reason, rows['R_Katana'].source, rows['R_Katana'].reason, rows['R_Katana'].enabled) == \
    ('Manual mapping', '', 'Source moved to L_Yari', False), (rows['L_Yari'].reason, rows['R_Katana'].source, rows['R_Katana'].reason)
substituted = bake(body_clearance=False)
assert substituted['placed'] == {'L_Yari': 'L_Hand'}, substituted['placed']
spear_error = follows(placement('L_Yari'), 'L_Yari')
grip = target.data.bones['R_Hand'].matrix_local.inverted() @ target.data.bones['R_Katana'].matrix_local
for frame in range(1, COUNT + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    relative = target.pose.bones['R_Hand'].matrix.inverted() @ target.pose.bones['R_Katana'].matrix
    assert max(abs(relative[r][c] - grip[r][c]) for r in range(4) for c in range(4)) < 1e-4, f'R_Katana left the right hand on frame {frame}'
    assert max(target.pose.bones['L_Gun'].matrix.to_scale()) < 1e-6, f'the gun shows on frame {frame}'

# An axe mesh along its bone's Y axis: the spear, along its bone's X axis, turns to stay parallel to it.
axe = box('Axe', (-.015, -.25, -.006), (.015, .75, .006), 2, lambda co: 'L_Axe', source, source, source.data.bones['L_Axe'].matrix_local)
turned = bake(body_clearance=False)
assert abs(turned['weapons']['L_Yari'] - 90) < 1, turned['weapons']
follows(placement('L_Yari', Vector((0, 1, 0))), 'turned L_Yari', turned=False)
lines = []
for frame in range(3, COUNT + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    blade, haft = long_axis(world_points(spear)), long_axis(world_points(axe))
    lines.append(math.degrees(min(blade.angle(haft), blade.angle(-haft))))
assert max(lines) < 1, f'the spear and the axe differ by up to {max(lines):.2f} degrees'

# Hiding the katana, which the spear took the axe from, and the spear itself in the map: both shrink to 0.1% on every
# frame where they would be, the katana at its grip in the right hand and the spear where the axe puts it, and the
# scabbard shrinks with the katana.
rows['R_Katana'].hidden = rows['L_Yari'].hidden = True
hidden = bake(body_clearance=False)
assert set(hidden['hidden']) == {'R_Katana', 'L_Yari'} and hidden['placed'] == {'L_Yari': 'L_Hand'}, (hidden['hidden'], hidden['placed'])
assert all(f'{name} is hidden on every frame.' in hidden['notes'] for name in ('R_Katana', 'L_Yari')), hidden['notes']
for frame, item in enumerate(placement('L_Yari', Vector((0, 1, 0))), 1):
    assert item['error'] < 1e-4, f"the hidden spear lies {item['error'] * 1000:.2f} mm from where it belongs on frame {frame}"
    assert all(abs(value - retarget.HIDDEN) < 1e-6 for value in item['scale']), f"the spear has scale {item['scale']} on frame {frame}"
for frame in range(1, COUNT + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    location, orientation, unused = (target.pose.bones['R_Hand'].matrix.inverted() @ target.pose.bones['R_Katana'].matrix).decompose()
    turn = orientation.rotation_difference(grip.to_quaternion())
    assert (location - grip.translation).length < 1e-4 and min(turn.angle, 2 * math.pi - turn.angle) < 1e-3, \
        f'the hidden katana left its grip in the right hand on frame {frame}'
    for name in ('R_Katana', 'R_Katana_Saya'):
        size = target.pose.bones[name].matrix.to_scale()
        assert all(abs(value - retarget.HIDDEN) < 1e-6 for value in size), f'{name} has scale {size} on frame {frame}'
scabbard_keeps_channels('hidden katana')

# The map keeps hidden weapons; a new match shows them again.
with tempfile.TemporaryDirectory() as temp:
    path = str(Path(temp) / 'hidden weapons.json')
    assert bpy.ops.sekiro_retarget.save_map(filepath=path) == {'FINISHED'}
    saved = {item['target']: item for item in json.loads(Path(path).read_text(encoding='utf-8'))['mappings']}
    assert saved['R_Katana']['hidden'] and saved['L_Yari']['hidden'] and not saved['L_Gun']['hidden'], saved['R_Katana']
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    assert not any(row.hidden for row in settings.rows), 'a new match kept hidden weapons'
    assert bpy.ops.sekiro_retarget.load_map(filepath=path) == {'FINISHED'}
rows = {row.target: row for row in settings.rows}  # The match and the load made new rows.
assert {name for name, row in rows.items() if row.hidden} == {'R_Katana', 'L_Yari'}
assert (rows['L_Yari'].source, rows['R_Katana'].source) == ('L_Axe', ''), (rows['L_Yari'].source, rows['R_Katana'].source)
assert set(bake(body_clearance=False)['hidden']) == {'R_Katana', 'L_Yari'}
print(f"Weapon hand checks passed{' with the full-body bake' if METHOD == 'BODY' else ''}: the katana took the axe from the other hand and followed it within "
      f"{switch_error * 1000:.3f} mm, hidden at {retarget.HIDDEN} on frames 1-2 with its scabbard in place; the right "
      f"hand was moved out on frames {pushed['R']['frames'][0]}-{pushed['R']['frames'][-1]} by up to {moved * 100:.1f} cm "
      f"without moving the katana; the spear took the axe within {spear_error * 1000:.3f} mm and turned "
      f"{turned['weapons']['L_Yari']:.0f} degrees for the axe mesh, parallel within {max(lines):.3f} degrees; hiding the "
      f"katana and the spear in the map shrank both and the scabbard to {retarget.HIDDEN} on all {COUNT} frames, and "
      f"the map kept them hidden.")
