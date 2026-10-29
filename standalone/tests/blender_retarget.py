"""Retarget add-on on owned synthetic rigs. Run with Blender --background --factory-startup --python this_file.py.

A Mixamo-style T-pose source, stored the way FBX imports arrive (Y-up armature
space in centimetres under a rotated, 0.01-scaled object), drives an Elden
Ring-style A-pose bridge rig that is 1.3 times larger. Checked: limb directions
follow the source, body travel scales by leg length, connectors and bones above
the body hold their rest pose, unmapped bones keep or drop their animation, the
root-motion modes, the HKX metadata, and a round trip back onto a third rig.
"""
import json
import math
import sys
import tempfile
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import import_motion, export_motion, trs_matrix
import sekiro_retarget
from sekiro_retarget import retarget

COUNT, RATE, SIZE = 24, 30, 1.3


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


def bridge_rig(bones, animated):
    """A bridge rig built by the importer from synthetic motion JSON; animated bones get extra motion."""
    index = {bone[0]: i for i, bone in enumerate(bones)}
    def game(v):
        return Vector((v[0], v[2], v[1]))
    skeleton = []
    for i, (name, parent, head, label) in enumerate(bones):
        local = game(head) - (game(bones[index[parent]][2]) if parent else Vector())
        skeleton.append(dict(index=i, name=name, parent=index[parent] if parent else -1, translation=list(local),
                             rotation=[0, 0, 0, 1], scale=[1, 1, 1]))
    tracks = [i for i, bone in enumerate(bones) if bone[3] or bone[0] in ('Master', 'RootPos', 'RootRotY', 'RootRotXZ') or bone[0] in animated]
    frames = []
    for f in range(COUNT):
        frame = []
        for i in tracks:
            angle = animated.get(bones[i][0], 0) * f / (COUNT - 1)
            s = math.sin(angle / 2)
            frame.append(dict(translation=skeleton[i]['translation'], rotation=[s, 0, 0, math.cos(angle / 2)], scale=[1, 1, 1]))
        frames.append(frame)
    motion = dict(format='sekiro-animation-bridge', formatVersion=1, clip='a000_003000.hkx', skeletonName='Owned', game='er',
                  skeleton=dict(name='Owned', boneCount=len(skeleton), bones=skeleton), frameCount=COUNT, frameRate=RATE,
                  duration=(COUNT - 1) / RATE, trackCount=len(tracks), trackBoneIndices=tracks,
                  trackNames=[bones[i][0] for i in tracks], frames=frames,
                  rootMotion=[[.01 * f, 0, .02 * f, .005 * f] for f in range(COUNT)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])
    return import_motion(motion)


def own_rotations(t):
    """Joint rotations in world space at clip time t (0..1); the first frame is the rest pose."""
    w = 2 * math.pi * t
    return {'hips': Quaternion((0, 0, 1), .3 * t), 'spine.first': Quaternion((0, 0, 1), .2 * math.sin(w)),
            'neck': Quaternion((1, 0, 0), .3 * math.sin(w)), 'L.upperarm': Quaternion((0, 1, 0), -.8 * math.sin(w)),
            'L.forearm': Quaternion((0, 0, 1), .9 * math.sin(w) ** 2), 'R.upperarm': Quaternion((1, 0, 0), .6 * math.sin(w)),
            'L.thigh': Quaternion((1, 0, 0), .7 * math.sin(w)), 'L.calf': Quaternion((1, 0, 0), -.8 * math.sin(w) ** 2),
            'R.thigh': Quaternion((1, 0, 0), -.7 * math.sin(w)), 'L.index.1': Quaternion((0, 1, 0), .6 * math.sin(w) ** 2)}


def animate(rig, bones):
    """Key world-space joint rotations and hip travel on a rig, whatever its object transform."""
    label_of = {bone[0]: bone[3] for bone in bones}
    turn = rig.matrix_world.to_quaternion()
    scale = rig.matrix_world.to_scale()[0]
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda b: len(b.parent_recursive))
    for f in range(COUNT):
        t = f / (COUNT - 1)
        own, deltas, poses = own_rotations(t), {}, {}
        travel = turn.inverted() @ Vector((0, -.8 * t, .03 * math.sin(4 * math.pi * t))) / scale
        for bone in ordered:
            parent = bone.parent
            world = (deltas[parent.name] if parent else Quaternion()) @ own.get(label_of[bone.name], Quaternion())
            deltas[bone.name] = world
            delta = turn.inverted() @ world @ turn
            if parent:
                head = poses[parent.name] @ (rest[parent.name].inverted() @ rest[bone.name]).translation
            else:
                head = rest[bone.name].translation + (travel if label_of[bone.name] == 'hips' else Vector())
            poses[bone.name] = Matrix.LocRotScale(head, delta @ rest[bone.name].to_quaternion(), None)
            keywords = dict(parent_matrix=poses[parent.name], parent_matrix_local=rest[parent.name]) if parent else {}
            basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = basis
            pose_bone.keyframe_insert('location', frame=f + 1)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f + 1)


def heads(rig, frame):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return {bone.name: rig.matrix_world @ bone.head for bone in rig.pose.bones}


def angle(a, b):
    return math.degrees(a.angle(b)) if a.length > 1e-9 and b.length > 1e-9 else 0.0


LINKS = [('L.upperarm', 'L.forearm'), ('L.forearm', 'L.hand'), ('R.upperarm', 'R.forearm'), ('R.forearm', 'R.hand'),
         ('L.thigh', 'L.calf'), ('L.calf', 'L.foot'), ('R.thigh', 'R.calf'), ('R.calf', 'R.foot'),
         ('L.index.1', 'L.index.2'), ('spine.last', 'neck'), ('neck', 'head'), ('L.clavicle', 'L.upperarm')]


def worst_direction(source, source_names, target, target_names, links=LINKS, frames=range(1, COUNT + 1)):
    worst = 0.0
    for frame in frames:
        s, t = heads(source, frame), heads(target, frame)
        for a, b in links:
            worst = max(worst, angle(s[source_names[b]] - s[source_names[a]], t[target_names[b]] - t[target_names[a]]))
    return worst


def bake(settings, **options):
    for key, value in options.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}
    return json.loads(bpy.context.scene['sekiro_retarget_report'])


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE

source_bones = humanoids.mixamo(0)
fbx = Matrix.Rotation(math.pi / 2, 4, 'X') @ Matrix.Scale(.01, 4)
source = armature('Source', source_bones, fbx, roll=.4)
animate(source, source_bones)
target_bones = [(name, parent, tuple(SIZE * v for v in head), label) for name, parent, head, label in humanoids.fromsoftware(45, 'elden')]
target = bridge_rig(target_bones, {'Master': .4, 'R_Weapon': .8})
original = {name: [] for name in ('R_Weapon', 'Master')}
for frame in range(1, COUNT + 1):
    scene.frame_set(frame)
    for name in original:
        original[name].append(target.pose.bones[name].matrix_basis.copy())
# Bridge imports leave untracked bones at their HKX reference pose, a fraction of a millimetre
# from the edit-bone rest. A bake must neither key that pose nor reset it.
reference = Matrix.Translation((4e-5, 0, 0))
target.pose.bones['L_Weapon'].matrix_basis = reference


def holds_reference():
    held = target.pose.bones['L_Weapon'].matrix_basis
    return max(abs(held[r][c] - reference[r][c]) for r in range(4) for c in range(4)) < 1e-7
source_names = {label: name for name, parent, head, label in source_bones if label}
target_names = {label: name for name, parent, head, label in target_bones if label}

settings = scene.sekiro_retarget
settings.source, settings.target = source, target
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row.source for row in settings.rows if row.enabled and row.source}
for label, name in target_names.items():
    if label in source_names and name in rows:
        assert rows[name] == source_names[label], (name, rows[name])
assert rows['Pelvis'] == 'mixamorig:Hips' and rows['L_Finger12'] == 'mixamorig:LeftHandIndex3'

# The importer stores the clip's game. The bone names that the bridge's games.json gives that game become aliases
# that the matcher reads, while the rows keep the real names; without games.json, or bone names in it, there are none.
from sekiro_retarget import export
assert target['sekiro_game'] == 'er' and 'sekiro_game' not in source
registry = export.GAMES_FILE
with tempfile.TemporaryDirectory() as folder:
    export.GAMES_FILE = Path(folder) / 'games.json'
    assert not any(bone.alias for bone in retarget.rig_bones(target))
    export.GAMES_FILE.write_text(json.dumps({'games': [{'id': 'er', 'name': 'Elden Ring', 'bones': dict(
        names={'Pelvis': 'Hips'}, patterns=[{'match': '(', 'as': 'broken'}, {'match': r'([LR])_Toe0', 'as': r'\1_ToeBase'}])}]}),
        encoding='utf-8')
    aliases = {bone.name: bone.alias for bone in retarget.rig_bones(target)}
    assert (aliases['Pelvis'], aliases['L_Toe0'], aliases['Spine']) == ('Hips', 'L_ToeBase', ''), aliases
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    aliased = {row.target: row for row in settings.rows if row.enabled and row.source}
    assert {name: row.source for name, row in aliased.items()} == rows
    assert (aliased['Pelvis'].reason, aliased['R_Toe0'].reason) == ('Same normalized name', 'Same normalized name')
export.GAMES_FILE = registry
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
assert {row.target: row.source for row in settings.rows if row.enabled and row.source} == rows

# Matched stances, no root motion: limbs point like the source in world space.
report = bake(settings, rest_mode='ALIGN', root_motion='NONE', unmapped='KEEP')
assert report['carrier'] == 'RootPos', report
swing = max(angle(heads(source, f)[source_names['L.forearm']] - heads(source, f)[source_names['L.upperarm']],
                  heads(source, 1)[source_names['L.forearm']] - heads(source, 1)[source_names['L.upperarm']]) for f in range(1, COUNT + 1))
assert swing > 30, f'the source arm barely moves ({swing:.1f} degrees), so the direction checks would prove little'
assert abs(report['scale'] - SIZE) < 1e-3, report['scale']
worst = worst_direction(source, source_names, target, target_names)
assert worst < .5, f'limb directions differ by {worst:.3f} degrees'
for frame in (1, 9, 17, COUNT):
    s, t = heads(source, frame), heads(target, frame)
    s0, t0 = heads(source, 1), heads(target, 1)
    travel_source = s[source_names['hips']] - s0[source_names['hips']]
    travel_target = t[target_names['hips']] - t0[target_names['hips']]
    assert (travel_target - SIZE * travel_source).length < 1e-3, (frame, travel_source, travel_target)
    # Legs and upper body move together: the spine stays attached at its rest distance from the pelvis.
    assert abs((t['Spine'] - t['Pelvis']).length - (t0['Spine'] - t0['Pelvis']).length) < 1e-4, frame
for frame in range(1, COUNT + 1):
    scene.frame_set(frame)
    for name in ('RootRotY', 'RootRotXZ', 'Master'):
        basis = target.pose.bones[name].matrix_basis
        assert max(abs(basis[r][c] - (r == c)) for r in range(4) for c in range(4)) < 1e-5, (name, frame)
    kept = target.pose.bones['R_Weapon'].matrix_basis
    assert max(abs(kept[r][c] - original['R_Weapon'][frame - 1][r][c]) for r in range(4) for c in range(4)) < 1e-5, frame
    assert holds_reference(), frame
assert 'L_Weapon' not in retarget.action_bones(target.animation_data.action), 'the bake keyed an untouched bone'
root = retarget.root_object(target)
assert all(abs(v) < 1e-6 for v in root.location) and abs(root.rotation_euler.z) < 1e-6, 'NONE did not hold the root still'
document = retarget.read_motion(target)
assert document['frameCount'] == COUNT and document['rootMotion'] is None and len(document['frames']) == COUNT
assert document['trackBoneIndices'] == [i for i, b in enumerate(target_bones) if b[3] or b[0] in (
    'Master', 'RootPos', 'RootRotY', 'RootRotXZ', 'R_Weapon')]
none_hips = [heads(target, frame)['Pelvis'] for frame in range(1, COUNT + 1)]

# The bridge exporter extracts travel from the bone that carries the whole body (RootPos, above
# both Pelvis and Spine), so the game rebuilds legs and upper body together over the root.
with tempfile.TemporaryDirectory() as temp:
    summary = export_motion(Path(temp) / 'bone.motion.json', root_motion='bone', root_yaw=True)
    exported = json.loads((Path(temp) / 'bone.motion.json').read_text())
assert summary['rootBone'] == 'RootPos', summary
assert not summary['warnings'], summary['warnings']
skeleton = exported['skeleton']['bones']
index = {bone['name']: i for i, bone in enumerate(skeleton)}
tracks = {bone_index: k for k, bone_index in enumerate(exported['trackBoneIndices'])}
for f in (0, COUNT // 2, COUNT - 1):
    world = []
    for i, bone in enumerate(skeleton):
        local = trs_matrix(exported['frames'][f][tracks[i]] if i in tracks else bone)
        world.append(world[bone['parent']] @ local if bone['parent'] >= 0 else local)
    s = exported['rootMotion'][f]
    in_game = Matrix.Translation((s[0], s[2], s[1])) @ Matrix.Rotation(-s[3], 4, 'Z')
    expected = heads(target, f + 1)
    for name in ('Pelvis', 'Spine2', 'Head', 'L_Hand', 'R_Foot'):
        assert ((in_game @ world[index[name]]).translation - expected[name]).length < 1e-3, (f, name)
assert abs(exported['rootMotion'][-1][2] + .8 * SIZE) < 1e-3, exported['rootMotion'][-1]

# Unmapped bones at rest; the target keeps its own A-pose stance under the source rotations.
bake(settings, rest_mode='REST', unmapped='REST')
for frame in (1, COUNT):
    scene.frame_set(frame)
    basis = target.pose.bones['R_Weapon'].matrix_basis
    assert max(abs(basis[r][c] - (r == c)) for r in range(4) for c in range(4)) < 1e-5, frame
    assert holds_reference(), frame
s, t = heads(source, 1), heads(target, 1)
stance = angle(s[source_names['L.forearm']] - s[source_names['L.upperarm']], t['L_Forearm'] - t['L_UpperArm'])
assert abs(stance - 45) < .5, stance

# Body travel becomes root motion; the root carries the travel and the heading, the body stays over it.
report = bake(settings, rest_mode='ALIGN', root_motion='EXTRACT', root_yaw=True, unmapped='KEEP')
assert report['root_motion'] == 'EXTRACT'
for frame in range(1, COUNT + 1):
    scene.frame_set(frame)
    # Baking again starts from the original clip, not from the previous bake that held this bone at rest.
    kept = target.pose.bones['R_Weapon'].matrix_basis
    assert max(abs(kept[r][c] - original['R_Weapon'][frame - 1][r][c]) for r in range(4) for c in range(4)) < 1e-5, frame
    world = Matrix.Translation(root.location) @ Matrix.Rotation(root.rotation_euler.z, 4, 'Z')
    carried = world @ target.pose.bones['Pelvis'].head
    assert (carried - none_hips[frame - 1]).length < 1e-4, (frame, carried, none_hips[frame - 1])
    assert abs(root.rotation_euler.z - .3 * (frame - 1) / (COUNT - 1)) < 1e-4, (frame, root.rotation_euler.z)
    local = target.pose.bones['RootPos'].head
    assert abs(local.x - target.data.bones['RootPos'].head_local.x) < 1e-4 and abs(local.y - target.data.bones['RootPos'].head_local.y) < 1e-4
document = retarget.read_motion(target)
last = document['rootMotion'][-1]
assert abs(last[0] - root.location.x) < 1e-5 and abs(last[2] - root.location.y) < 1e-5 and abs(last[3] + root.rotation_euler.z) < 1e-5
with tempfile.TemporaryDirectory() as temp:
    summary = export_motion(Path(temp) / 'retarget.motion.json')
    exported = json.loads((Path(temp) / 'retarget.motion.json').read_text())
    assert summary['rootMotion'] == 'object' and summary['action'] == report['action'], summary
    assert all(abs(a - b) < 1e-4 for a, b in zip(exported['rootMotion'][-1], last)), (exported['rootMotion'][-1], last)

# Automatic root motion: a source root object is copied, scaled by leg length.
empty = bpy.data.objects.new('Source root', None)
scene.collection.objects.link(empty)
for frame in (1, COUNT):
    empty.location = (0, -.5 * (frame - 1) / (COUNT - 1), 0)
    empty.rotation_euler = (0, 0, .25 * (frame - 1) / (COUNT - 1))
    empty.keyframe_insert('location', frame=frame)
    empty.keyframe_insert('rotation_euler', frame=frame)
source['sekiro_root_motion_data'] = empty
report = bake(settings, root_motion='AUTO')
assert report['root_motion'] == 'SOURCE', report
scene.frame_set(COUNT)
assert abs(root.location.y + .5 * SIZE) < 1e-4 and abs(root.rotation_euler.z - .25) < 1e-4, (root.location, root.rotation_euler)
del source['sekiro_root_motion_data']
report = bake(settings, root_motion='AUTO')
assert report['root_motion'] == 'EXTRACT' and report['warnings'], report  # 0.8 m of travel
report = bake(settings, root_motion='TARGET')
scene.frame_set(COUNT)
assert abs(root.location.x - .01 * (COUNT - 1)) < 1e-5 and abs(root.location.y - .02 * (COUNT - 1)) < 1e-5, root.location

# Round trip: the Elden-style result drives a third rig in a 30 degree A-pose with other bone rolls.
bake(settings, rest_mode='ALIGN', root_motion='NONE')
third_bones = humanoids.unreal(30)
third = armature('Third', third_bones, roll=-.7)
settings.source, settings.target = target, third
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
report = bake(settings, rest_mode='ALIGN', root_motion='NONE')
third_names = {label: name for name, parent, head, label in third_bones if label}
worst = worst_direction(source, source_names, third, third_names)
assert worst < .5, f'round trip limb directions differ by {worst:.3f} degrees'
for frame in (1, 12, COUNT):
    s, t = heads(source, frame), heads(third, frame)
    s0, t0 = heads(source, 1), heads(third, 1)
    assert ((t['pelvis'] - t0['pelvis']) - (s[source_names['hips']] - s0[source_names['hips']])).length < 1e-3, frame
print(f'Retarget check passed: worst limb direction {worst:.4f} degrees, {report["keyed"]} keyed bones')
