"""The Retarget Assistant's Add weapon and the character export of the weapon it adds, on owned synthetic rigs. Run with
Blender --background --factory-startup --python-exit-code 1 --python this_file.py.

A humanoid swings its right arm over 20 frames. On frame 10 a sword of two meshes sits in the posed right hand: a
blade 1.2 long, an object scaled by 1.2 and turned, with a Bevel modifier, and a guard parented to the hand bone, as
Ctrl+P > Bone parents it. Checked:
- Add weapon gives the rig R_Weapon under R_Hand, from the point of the blade's axis nearest the hand to the blade's
  far end, with its roll following the hand's, and binds both meshes to it alone with an Armature modifier, the
  blade's bevel applied. The bone list lists R_Weapon with Only bones the clip animates on, although the rig's HKX
  tracks do not include it.
- On frame 10 every vertex is where it was before, within 0.01 mm; on frames 1 and 20 the sword follows the hand as
  one piece.
- A dagger in the left hand becomes L_Weapon, a knife in the right hand R_Weapon2, and a scabbard on Spine2 the bone
  named Scabbard. A taken name is refused, and a mesh bound already is not offered again.
- The character export writes the five meshes, bound to the rig and weighted wholly to their weapon bones, at their
  rest places, with nothing left out.
"""
import json
import sys
import tempfile
from pathlib import Path
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
import sekiro_retarget
from blender_character_export import export_character
from games.interchange import check_character_export


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


def swing(rig):
    """Key the right arm turning about X over frames 1 to 20, and the forearm bending."""
    rig.animation_data_create().action = bpy.data.actions.new('Swing')
    for name, angle in (('R_UpperArm', 1.0), ('R_Forearm', .6)):
        bone = rig.pose.bones[name]
        bone.rotation_mode = 'XYZ'
        for frame, value in ((1, 0.0), (20, angle)):
            bone.rotation_euler = (value, 0, 0)
            bone.keyframe_insert('rotation_euler', frame=frame)


def cuboid(name, low, high):
    """A box mesh object from corner low to corner high, linked to the scene."""
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    mesh.uv_layers.new(name='uv_0')
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def shown(obj):
    """The world positions of an object's evaluated vertices."""
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = np.array([evaluated.matrix_world @ v.co for v in mesh.vertices])
    evaluated.to_mesh_clear()
    return points


def hand_pose(rig, frame, name='R_Hand'):
    bpy.context.scene.frame_set(frame)
    return rig.matrix_world @ rig.pose.bones[name].matrix


def choose(rig, objects):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in objects or obj == rig)
    bpy.context.view_layer.objects.active = rig


def moved(points, change):
    return np.array([change @ Vector(p) for p in points])


bpy.ops.wm.read_factory_settings(use_empty=True)
sekiro_retarget.register()
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 20
rig = armature('Hero', humanoids.proportioned())
swing(rig)
settings = scene.sekiro_weapon
# HKX tracks on every bone but Spine2, as on a rig the bridge imports: Only bones the clip animates lists tracked bones.
for index, pose_bone in enumerate(rig.pose.bones):
    if pose_bone.name != 'Spine2':
        pose_bone['hkx_track_index'] = index

# The sword, placed in the posed hand on frame 10: the blade along a direction of the hand, scaled, with a bevel.
hand = hand_pose(rig, 10)
place = hand @ Matrix.Translation((0, .06, 0)) @ Euler((.3, .2, 1.1)).to_matrix().to_4x4()
blade = cuboid('Blade', (-.1, -.02, -.01), (.9, .02, .01))
blade.matrix_world = place @ Matrix.Scale(1.2, 4)
blade.modifiers.new('Bevel', 'BEVEL').width = .002
guard = cuboid('Guard', (-.01, -.06, -.03), (.01, .06, .03))
guard.parent, guard.parent_type, guard.parent_bone = rig, 'BONE', 'R_Hand'
bpy.context.view_layer.update()
guard.matrix_world = place
bpy.context.view_layer.update()
before = {obj.name: shown(obj) for obj in (blade, guard)}

choose(rig, [blade, guard])
assert sekiro_retarget.weapon.default_name(rig, 'RIGHT') == 'R_Weapon'
assert bpy.ops.sekiro_retarget.add_weapon() == {'FINISHED'}, scene.sekiro_retarget.status
status = scene.sekiro_retarget.status
assert status.startswith('Added R_Weapon under R_Hand with Blade, Guard') and 'Blade: its modifiers were applied.' in status, status
bone = rig.data.bones['R_Weapon']
assert bone.parent.name == 'R_Hand' and bone.use_deform, bone.parent
for obj in (blade, guard):
    assert [(m.type, m.object) for m in obj.modifiers] == [('ARMATURE', rig)], (obj.name, list(obj.modifiers))
    assert [g.name for g in obj.vertex_groups] == ['R_Weapon'], obj.vertex_groups.keys()
    assert all(len(v.groups) == 1 and v.groups[0].weight == 1.0 for v in obj.data.vertices), obj.name
    assert obj.parent == rig and obj.parent_type == 'OBJECT', (obj.name, obj.parent, obj.parent_type)
assert len(blade.data.vertices) > 8, 'the bevel was not applied'
# The bone list lists the weapon bone with Only bones the clip animates on, although it has no track.
listed = [b.name for b in sekiro_retarget.retarget.bone_infos(rig, tracked_only=True)]
assert 'R_Weapon' in listed and 'Spine2' not in listed, listed

# Where it was placed on frame 10, and with the hand as one piece on the other frames.
worst = 0.0
for frame in (10, 1, 20):
    change = hand_pose(rig, frame) @ hand.inverted()
    for obj in (blade, guard):
        worst = max(worst, float(np.abs(shown(obj) - moved(before[obj.name], change)).max()))
assert worst < 1e-5, worst

# The bone: from the blade's axis at the hand to the blade's far end, rolled like the hand.
rest = rig.matrix_world @ rig.data.bones['R_Hand'].matrix_local
carry = rest @ hand.inverted()
axis = (carry @ place).to_3x3() @ Vector((1, 0, 0))
far_end = carry @ place @ Vector((.9 * 1.2, 0, 0))
head, tail = rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local
assert (tail - far_end).length < 1e-4, (tail, far_end)
assert abs((tail - head).normalized().dot(axis)) > .9999, (tail - head, axis)
grip = carry @ place @ Vector((0, 0, 0))
off_axis = (head - grip) - axis * (head - grip).dot(axis)
assert off_axis.length < 1e-4, off_axis
hand_z = rest.to_3x3().col[2]
along = bone.matrix_local.to_3x3().col[1]
upright = (hand_z - along * hand_z.dot(along)).normalized()
assert bone.matrix_local.to_3x3().col[2].dot(upright) > .9999, 'the roll does not follow the hand'

# Further weapons: the left hand, the right hand again, a bone of the body with a name of its own.
scene.frame_set(1)
dagger = cuboid('Dagger', (0, -.01, -.01), (.3, .01, .01))
dagger.matrix_world = hand_pose(rig, 1, 'L_Hand')
choose(rig, [dagger])
settings.hand = 'LEFT'
assert bpy.ops.sekiro_retarget.add_weapon() == {'FINISHED'} and rig.data.bones['L_Weapon'].parent.name == 'L_Hand'
knife = cuboid('Knife', (0, -.01, -.01), (.2, .01, .01))
knife.matrix_world = hand_pose(rig, 1)
choose(rig, [knife])
settings.hand = 'RIGHT'
assert sekiro_retarget.weapon.default_name(rig, 'RIGHT') == 'R_Weapon2'
assert bpy.ops.sekiro_retarget.add_weapon() == {'FINISHED'} and rig.data.bones['R_Weapon2'].parent.name == 'R_Hand'
scabbard = cuboid('Scabbard', (-.4, -.03, -.03), (.4, .03, .03))
scabbard.matrix_world = Matrix.Translation((0, .15, 1.2))
choose(rig, [scabbard])
settings.hand, settings.bone, settings.bone_name = 'BONE', 'Spine2', 'R_Weapon'
try:
    bpy.ops.sekiro_retarget.add_weapon()
    raise AssertionError('a taken name was accepted')
except RuntimeError as error:  # Blender raises the operator's error report from a script.
    assert 'Hero has a bone named R_Weapon already' in str(error), error
settings.bone_name = 'Scabbard'
assert bpy.ops.sekiro_retarget.add_weapon() == {'FINISHED'} and rig.data.bones['Scabbard'].parent.name == 'Spine2'
assert settings.bone_name == ''
choose(rig, [blade])
assert not bpy.ops.sekiro_retarget.add_weapon.poll(), 'a bound mesh was offered again'

# The character export: every weapon mesh bound to the rig, weighted wholly to its bone, at its rest place.
with tempfile.TemporaryDirectory() as temp:
    scene.frame_set(7)
    manifest = export_character(Path(temp) / 'out', rig)
    check_character_export(json.loads((Path(temp) / 'out' / 'manifest.json').read_text(encoding='utf-8')))
    names = [b['name'] for b in manifest['bones']]
    meshes = {m['name']: m for m in manifest['meshes']}
    assert sorted(meshes) == ['Blade', 'Dagger', 'Guard', 'Knife', 'Scabbard'] and manifest['leftOut'] == [], \
        (sorted(meshes), manifest['leftOut'])
    expected = {'Blade': 'R_Weapon', 'Guard': 'R_Weapon', 'Dagger': 'L_Weapon', 'Knife': 'R_Weapon2', 'Scabbard': 'Scabbard'}
    for name, weapon_bone in expected.items():
        obj = bpy.data.objects[name]
        with np.load(meshes[name]['data']) as data:
            assert meshes[name]['bound'] == 'rig', meshes[name]
            assert (data['bone_indices'][:, 0] == names.index(weapon_bone)).all() and (data['bone_weights'][:, 0] == 1).all()
            resting = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
            assert np.abs(data['positions'] - resting).max() < 1e-5, name
    assert not [w for w in manifest['warnings'] if 'Left out' in w], manifest['warnings']

sekiro_retarget.unregister()
print(f'blender_add_weapon: R_Weapon from the grip to the blade\'s end, the sword where it was placed and following the '
      f'hand within {worst * 1000:.4f} mm; L_Weapon, R_Weapon2 and Scabbard; the export writes all five meshes at rest')
