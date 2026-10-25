"""FromSoftware foot targets on owned synthetic rigs. Run with Blender --background --factory-startup --python this_file.py.

Each side of a FromSoftware rig hangs L_Foot_Target2 at hip height, L_Foot_Target1 at knee height and L_Foot_Target
on the foot from Master. In the game's clips the chain stands on the foot like a column: it keeps its rest pose and
its upright rest rotation, moved as one so that L_Foot_Target sits on the foot, which it also turns with. Checked: the
retarget bake stands each chain on its foot, from a Mixamo-style source without targets and from a FromSoftware source
whose targets stand still while its feet move, with the body's travel kept in the clip and taken out as root motion;
the bridge export writes the chains on the exported feet after an edit moved the feet in Blender and turned a chain,
also when root motion is taken from a bone.
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

COUNT, RATE = 24, 30
TARGETS = {'L_Foot_Target': 'L_Foot', 'R_Foot_Target': 'R_Foot'}
CHAINS = {'L_Foot_Target': ('L_Foot_Target2', 'L_Foot_Target1'), 'R_Foot_Target': ('R_Foot_Target2', 'R_Foot_Target1')}


def armature(name, bones):
    """An armature whose bones sit at the given positions."""
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
        edit.tail = tail if (tail - edit.head).length >= 1e-4 else edit.head + Vector((0, 0, .05))
        if parent:
            edit.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def own_rotations(t):
    """World-space joint rotations at clip time t (0..1): the legs swing, the left foot turns about the vertical."""
    w = 2 * math.pi * t
    return {'hips': Quaternion((0, 0, 1), .3 * t), 'L.thigh': Quaternion((1, 0, 0), .7 * math.sin(w)),
            'L.calf': Quaternion((1, 0, 0), -.8 * math.sin(w) ** 2), 'L.foot': Quaternion((0, 0, 1), .9 * math.sin(w)),
            'R.thigh': Quaternion((1, 0, 0), -.7 * math.sin(w)), 'R.foot': Quaternion((1, 0, 0), .5 * math.sin(w) ** 2)}


def animate(rig, bones):
    """Key world-space joint rotations and hip travel; bones without a label, such as foot targets, stay at rest."""
    label_of = {bone[0]: bone[3] for bone in bones}
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    ordered = sorted(rig.data.bones, key=lambda b: len(b.parent_recursive))
    for f in range(COUNT):
        t = f / (COUNT - 1)
        own, turns, poses = own_rotations(t), {}, {}
        for bone in ordered:
            parent = bone.parent
            turns[bone.name] = (turns[parent.name] if parent else Quaternion()) @ own.get(label_of[bone.name], Quaternion())
            head = poses[parent.name] @ (rest[parent.name].inverted() @ rest[bone.name]).translation if parent \
                else rest[bone.name].translation.copy()
            if label_of[bone.name] == 'hips':
                head += Vector((0, -.8 * t, .03 * math.sin(4 * math.pi * t)))
            poses[bone.name] = Matrix.LocRotScale(head, turns[bone.name] @ rest[bone.name].to_quaternion(), None)
            keywords = dict(parent_matrix=poses[parent.name], parent_matrix_local=rest[parent.name]) if parent else {}
            pose_bone = rig.pose.bones[bone.name]
            pose_bone.rotation_mode = 'QUATERNION'
            pose_bone.matrix_basis = bone.convert_local_to_pose(poses[bone.name], rest[bone.name], invert=True, **keywords)
            pose_bone.keyframe_insert('location', frame=f + 1)
            pose_bone.keyframe_insert('rotation_quaternion', frame=f + 1)


def bridge_rig(bones, turned=None):
    """A bridge rig imported from a still synthetic clip that tracks every bone; turned bones keep a turn about game X."""
    turned = turned or {}
    index = {bone[0]: i for i, bone in enumerate(bones)}

    def game(v):
        return Vector((v[0], v[2], v[1]))
    skeleton = []
    for i, (name, parent, head, label) in enumerate(bones):
        local = game(head) - (game(bones[index[parent]][2]) if parent else Vector())
        skeleton.append(dict(index=i, name=name, parent=index[parent] if parent else -1, translation=list(local),
                             rotation=[0, 0, 0, 1], scale=[1, 1, 1]))
    frames = [[dict(translation=bone['translation'], scale=[1, 1, 1],
                    rotation=[math.sin(turned.get(bone['name'], 0) / 2), 0, 0, math.cos(turned.get(bone['name'], 0) / 2)])
               for bone in skeleton] for f in range(COUNT)]
    motion = dict(format='sekiro-animation-bridge', formatVersion=1, clip='a000_003000.hkx', skeletonName='Owned', game='sekiro',
                  skeleton=dict(name='Owned', boneCount=len(skeleton), bones=skeleton), frameCount=COUNT, frameRate=RATE,
                  duration=(COUNT - 1) / RATE, trackCount=len(skeleton), trackBoneIndices=list(range(len(skeleton))),
                  trackNames=[bone['name'] for bone in skeleton], frames=frames,
                  rootMotion=[[0, 0, 0, 0] for f in range(COUNT)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])
    return import_motion(motion)


def degrees(a, b):
    """The angle between two matrices' rotations, whichever sign their quaternions have. Unlike acos of a dot
    product, it stays exact for the tiny angles that single-precision rounding leaves."""
    turn = a.to_quaternion().rotation_difference(b.to_quaternion())
    return math.degrees(2 * math.atan2(math.hypot(turn.x, turn.y, turn.z), abs(turn.w)))


def largest(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))


def upright(worlds, hanging, leaf):
    """How far the chain above a target leaves the column that hangs at rest and moves as one, without turning, so
    that the target sits where it is; and how far that column moved."""
    shift = Matrix.Translation(worlds[leaf].translation - hanging[leaf].translation)
    return max(largest(worlds[name], shift @ hanging[name]) for name in CHAINS[leaf]), shift.translation.length


def poses_at(rig, frame):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    return {bone.name: bone.matrix.copy() for bone in rig.pose.bones}


def bake(settings, **options):
    for key, value in options.items():
        setattr(settings, key, value)
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    return json.loads(scene['sekiro_retarget_report'])


def baked_targets(rig, label):
    """How far, at worst over the clip, the targets leave their feet and the chains above them their upright column,
    and how far the columns move."""
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    turn = gap = off = rise = 0.0
    for frame in range(1, COUNT + 1):
        poses = poses_at(rig, frame)
        for leaf, foot in TARGETS.items():
            turn, gap = max(turn, degrees(poses[leaf], poses[foot])), max(gap, (poses[leaf].translation - poses[foot].translation).length)
            top = rig.data.bones[CHAINS[leaf][0]].parent.name
            hanging = {name: poses[top] @ rest[top].inverted() @ rest[name] for name in (*CHAINS[leaf], leaf)}
            column, shift = upright(poses, hanging, leaf)
            off, rise = max(off, column), max(rise, shift)
    assert turn < .01 and gap < 1e-4, f'{label}: the targets leave the feet by {turn:.3f} degrees and {gap * 1000:.2f} mm'
    assert off < 1e-4, f'{label}: the chains above the targets leave their upright column by {off:.6f}'
    return turn, gap, off, rise


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.render.fps = RATE
fromsoftware = humanoids.with_foot_targets(humanoids.fromsoftware(45, 'elden'))
target = bridge_rig(fromsoftware)
settings = scene.sekiro_retarget

# A source without foot targets: the targets have no source bone and still follow the feet.
mixamo_bones = humanoids.mixamo(0)
mixamo = armature('Mixamo', mixamo_bones)
animate(mixamo, mixamo_bones)
settings.source, settings.target = mixamo, target
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row.source for row in settings.rows if row.enabled and row.source}
assert not any(name in rows for leaf, chain in CHAINS.items() for name in (leaf, *chain)), rows
report = bake(settings, root_motion='NONE')
assert report['foot_targets'] == TARGETS, report['foot_targets']
assert any('follow the feet' in note for note in report['notes']), report['notes']
first, last = poses_at(target, 1), poses_at(target, COUNT)
travel = (last['L_Foot'].translation - first['L_Foot'].translation).length
turned = max(degrees(poses_at(target, frame)['L_Foot'], first['L_Foot']) for frame in range(1, COUNT + 1))
assert travel > .5 and turned > 30, f'the left foot barely moves ({travel:.2f} m, {turned:.0f} degrees), so the checks prove little'
kept = baked_targets(target, 'Mixamo source, travel in the clip')
assert kept[3] > .5, f'the chains above the targets move only {kept[3]:.2f} m, so the checks prove little'
feet = last['L_Foot'].translation.copy()

report = bake(settings, root_motion='EXTRACT')
assert report['root_motion'] == 'EXTRACT', report['root_motion']
moved = (poses_at(target, COUNT)['L_Foot'].translation - feet).length
assert moved > .5, f'root motion moved the feet by only {moved:.2f} m'
extracted = baked_targets(target, 'Mixamo source, travel as root motion')

# A FromSoftware source whose targets stand still while its feet move: they match by name, but the bake does not copy them.
owl = armature('Owl', fromsoftware)
animate(owl, fromsoftware)
settings.source = owl
assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
rows = {row.target: row.source for row in settings.rows if row.enabled and row.source}
assert all(rows.get(name) == name for name in TARGETS), rows
bake(settings, root_motion='NONE')
matched = baked_targets(target, 'FromSoftware source with still targets')

# The bridge export after an edit: the left leg swings and the body travels in Blender, while the targets keep the
# imported clip and L_Foot_Target2 even stands turned. The export stands the chains upright on the feet again.
edited = bridge_rig(fromsoftware, turned={'L_Foot_Target2': .3})
scene['sekiro_bridge_export_rig'] = edited
scene['sekiro_bridge_active_rig'] = edited.name
thigh, calf, body = (edited.pose.bones[name] for name in ('L_Thigh', 'L_Calf', 'RootPos'))
for frame in range(1, COUNT + 1):
    t = (frame - 1) / (COUNT - 1)
    thigh.rotation_quaternion = Quaternion((1, 0, 0), .8 * math.sin(2 * math.pi * t))
    calf.rotation_quaternion = Quaternion((0, 0, 1), .6 * t)
    body.location = (0, -.7 * t, 0)
    for pose_bone, field in ((thigh, 'rotation_quaternion'), (calf, 'rotation_quaternion'), (body, 'location')):
        pose_bone.keyframe_insert(field, frame=frame)
poses = poses_at(edited, COUNT)
apart = (poses['L_Foot'].translation - poses['L_Foot_Target'].translation).length
assert apart > .3, f'the edit leaves the left foot only {apart:.2f} m from its target in Blender'


def exported_worlds(result):
    """Per frame, every bone's world matrix as the game builds it from the exported tracks."""
    skeleton = result['skeleton']['bones']
    tracks = {index: k for k, index in enumerate(result['trackBoneIndices'])}
    frames = []
    for samples in result['frames']:
        world = []
        for i, bone in enumerate(skeleton):
            local = trs_matrix(samples[tracks[i]]) if i in tracks else trs_matrix(bone)
            world.append(world[int(bone['parent'])] @ local if int(bone['parent']) >= 0 else local)
        frames.append(world)
    return frames


def exported_targets(result, label):
    """As baked_targets, on the world matrices the game builds from the exported tracks and the skeleton's reference
    pose; also where the left foot ends."""
    skeleton = result['skeleton']['bones']
    index = {bone['name']: i for i, bone in enumerate(skeleton)}
    turn = gap = off = rise = 0.0
    for world in exported_worlds(result):
        worlds = {name: world[i] for name, i in index.items()}
        for leaf, foot in TARGETS.items():
            a, b = worlds[leaf], worlds[foot]
            turn, gap = max(turn, degrees(a, b)), max(gap, (a.translation - b.translation).length)
            matrix, hanging = world[int(skeleton[index[CHAINS[leaf][0]]]['parent'])], {}
            for name in (*CHAINS[leaf], leaf):
                matrix = hanging[name] = matrix @ trs_matrix(skeleton[index[name]])
            column, shift = upright(worlds, hanging, leaf)
            off, rise = max(off, column), max(rise, shift)
    assert turn < .01 and gap < 1e-4, f'{label}: the exported targets leave the feet by {turn:.3f} degrees and {gap * 1000:.2f} mm'
    assert off < 1e-4, f'{label}: the exported chains above the targets leave their upright column by {off:.6f}'
    return turn, gap, off, rise, worlds['L_Foot'].translation.copy()


with tempfile.TemporaryDirectory() as temp:
    results = {}
    for mode in ('none', 'bone'):
        path = Path(temp) / f'{mode}.motion.json'
        summary = export_motion(path, frame_range='clip', root_motion=mode)
        assert summary['footTargets'] == TARGETS, summary['footTargets']
        results[mode] = exported_targets(json.loads(path.read_text()), f'export, root motion {mode}')
    assert summary['rootBone'] == 'RootPos', summary['rootBone']
    taken = (results['none'][4] - results['bone'][4]).length
    assert taken > .5, f'root motion from a bone moved the exported feet by only {taken:.2f} m'
    assert results['none'][3] > .3, f"the exported chains move only {results['none'][3]:.2f} m, so the checks prove little"

baked, written = (kept, extracted, matched), (results['none'], results['bone'])
print(f'Foot targets: OK. Baked from Mixamo, the left foot travels {travel:.2f} m and turns up to {turned:.0f} degrees; '
      f'the targets stay on the feet within {max(r[0] for r in baked):.1e} degrees and {max(r[1] for r in baked) * 1000:.1e} mm, '
      f'with the travel in the clip, as root motion ({moved:.2f} m) and from a FromSoftware source whose targets stand still, '
      f'and the chains above them keep their upright column within {max(r[2] for r in baked) * 1000:.1e} mm while it moves '
      f'up to {kept[3]:.2f} m. Exported after an edit that left the left foot {apart:.2f} m from its target and turned '
      f'L_Foot_Target2, the targets sit on the feet within {max(r[0] for r in written):.1e} degrees and '
      f'{max(r[1] for r in written) * 1000:.1e} mm, also with root motion from RootPos ({taken:.2f} m), and the chains keep '
      f"their column within {max(r[2] for r in written) * 1000:.1e} mm while it moves up to {results['none'][3]:.2f} m.")
