"""The character export manifest on an owned synthetic scene. Run with
Blender --background --factory-startup --python-exit-code 1 --python this_file.py.

A box skinned to a three-bone rig has three materials. The importer makes the first from a spec whose images carry
data in their alpha channels, as RE Engine's ALBM and NRMR do (metalness and roughness). The second is wired by hand:
an image's color and alpha and an OpenGL normal map. The third has no image and is transparent, as an eye overlay.
The manifest names each texture's role and channel, the overlay's alpha and color, every bone and the sampled action,
and matches standalone/schemas/character_export.schema.json.

Then, with the head turned on the current frame: a helmet parented to the head bone comes back to where it rests,
weighted wholly to the head; a weapon rig on a socket that follows the head, as the bridge builds one, adds its two
bones below the head, its Root renamed SWORD_Root, with their rest and their part clip's motion, and its sword mesh
keeps its weights on them. A mesh bound to another armature, one bound to a bind adapter, one parented to the rig
object and one bound to nothing are left out with their reasons; an unrendered mesh and a body figure are not listed.
"""
import json
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_character import make_material  # noqa: E402
from blender_character_export import export_character  # noqa: E402
from games.interchange import check_character_export  # noqa: E402


def write_image(path, rgba):
    image = bpy.data.images.new(Path(path).stem, 4, 4, alpha=True)
    image.pixels[:] = list(rgba) * 16
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    return str(path)


def rig_with_bones():
    armature = bpy.data.armatures.new('Rig')
    rig = bpy.data.objects.new('Rig', armature)
    rig['sekiro_game'] = 'dmc5'  # As the import records it; the export passes it on for the package's bone names.
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, parent, head, tail in (('Root', None, (0, 0, 0), (0, 0, .5)), ('Spine', 'Root', (0, 0, .5), (0, 0, 1)),
                                     ('Head', 'Spine', (0, 0, 1), (0, 0, 1.3))):
        bone = armature.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = armature.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.animation_data_create().action = action = bpy.data.actions.new('Nod')
    for frame, angle in ((1, 0), (11, .4)):
        rig.pose.bones['Head'].rotation_mode = 'XYZ'
        rig.pose.bones['Head'].rotation_euler = (angle, 0, 0)
        rig.pose.bones['Head'].keyframe_insert('rotation_euler', frame=frame)
    return rig, action


def box(rig, materials):
    corners = [(x, y, z) for x in (-.2, .2) for y in (-.2, .2) for z in (.6, 1.2)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new('Box')
    mesh.from_pydata(corners, [], faces)
    mesh.uv_layers.new(name='uv_0')
    for material in materials:
        mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = polygon.index // 2
    obj = bpy.data.objects.new('Box', mesh)
    bpy.context.scene.collection.objects.link(obj)
    spine, head = obj.vertex_groups.new(name='Spine'), obj.vertex_groups.new(name='Head')
    spine.add(range(8), 1.0, 'REPLACE')
    head.add([1, 3, 5, 7], .5, 'REPLACE')
    obj.modifiers.new('Armature', 'ARMATURE').object = rig
    return obj


def box_object(name, centre, size, stretch=(1, 1, 1)):
    """A cube of edge 2·size around centre, stretched per axis, linked to the scene without a binding."""
    corners = [(centre[0] + x * size * stretch[0], centre[1] + y * size * stretch[1], centre[2] + z * size * stretch[2])
               for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def by_hand(color_path, normal_path):
    material = bpy.data.materials.new('Skin')
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes['Principled BSDF']
    color = nodes.new('ShaderNodeTexImage')
    color.image = bpy.data.images.load(color_path)
    links.new(color.outputs['Color'], shader.inputs['Base Color'])
    links.new(color.outputs['Alpha'], shader.inputs['Alpha'])
    normal = nodes.new('ShaderNodeTexImage')
    normal.image = bpy.data.images.load(normal_path)
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(normal.outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs['Normal'], shader.inputs['Normal'])
    return material


def overlay():
    material = bpy.data.materials.new('EyeWet')
    material.use_nodes = True
    shader = material.node_tree.nodes['Principled BSDF']
    shader.inputs['Alpha'].default_value = 0
    shader.inputs['Base Color'].default_value = (.2, .3, .4, 1)
    return material


with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    albm = write_image(temp / 'coat_albm.png', (.5, .4, .3, .8))
    nrmr = write_image(temp / 'coat_nrmr.png', (.5, .5, 1, .6))
    skin = write_image(temp / 'skin.png', (.8, .6, .5, 1))
    skin_normal = write_image(temp / 'skin_normal.png', (.5, .5, 1, 1))
    coat = make_material(dict(name='coat', albedo=dict(path=albm, packed={'A': 'metalness'}, packedAlpha=True),
                              normal=dict(path=nrmr, packed={'A': 'roughness'}, packedAlpha=True, convention='directx')),
                         ['uv_0'], {})
    rig, action = rig_with_bones()
    box(rig, [coat, by_hand(skin, skin_normal), overlay()])
    manifest = export_character(temp / 'out', rig)

    assert [(b['name'], b['parent']) for b in manifest['bones']] == [('Root', -1), ('Spine', 0), ('Head', 1)], manifest['bones']
    assert manifest['game'] == 'dmc5', manifest['game']
    materials = {m['name']: m for m in manifest['materials']}
    roles = {name: {k: (Path(v['path']).stem, v['channel']) for k, v in m['roles'].items()} for name, m in materials.items()}
    assert roles['FromSoftware / coat'] == dict(albedo=('coat_albm', 'RGB'), normal=('coat_nrmr', 'RGB'),
                                                metalness=('coat_albm', 'A'), roughness=('coat_nrmr', 'A')), roles
    assert materials['FromSoftware / coat']['roles']['normal']['convention'] == 'directx'
    assert roles['Skin'] == dict(albedo=('skin', 'RGB'), opacity=('skin', 'A'), normal=('skin_normal', 'RGB')), roles
    assert materials['Skin']['roles']['normal']['convention'] == 'opengl'
    assert materials['Skin']['alpha'] is None and materials['Skin']['color'] is None, materials['Skin']
    assert materials['EyeWet']['alpha'] == 0 and materials['EyeWet']['color'] == [.2, .3, .4, 1], materials['EyeWet']
    assert all(Path(v['path']).is_file() for m in materials.values() for v in m['roles'].values())

    with np.load(manifest['meshes'][0]['data']) as mesh:
        assert sorted(set(mesh['triangle_materials'].tolist())) == [0, 1, 2], mesh['triangle_materials']
    motion = manifest['motion']
    assert (motion['action'], motion['frameStart'], motion['frameEnd'], motion['frames']) == ('Nod', 1, 11, 11), motion
    with np.load(motion['data']) as data:
        matrices = data['matrices']
    assert matrices.shape == (11, 3, 4, 4), matrices.shape
    assert not np.allclose(matrices[0, 2], matrices[-1, 2]) and np.allclose(matrices[0, 1], matrices[-1, 1])
    written = json.loads((temp / 'out' / 'manifest.json').read_text(encoding='utf-8'))
    check_character_export(written)
    assert written['leftOut'] == [] and [m['bound'] for m in written['meshes']] == ['rig'], written['meshes']

    # Meshes that move with a bone as a whole, a weapon rig on a socket, and meshes the export leaves out.
    scene = bpy.context.scene
    scene.frame_set(1)  # The head rests on frame 1.
    helmet = box_object('Helmet', (0, 0, 0), .1)
    helmet.parent, helmet.parent_type, helmet.parent_bone = rig, 'BONE', 'Head'
    bpy.context.view_layer.update()
    helmet.matrix_world = Matrix.Translation((0, 0, 1.4))
    socket = bpy.data.objects.new('SWORD | Socket 20', None)
    scene.collection.objects.link(socket)
    socket.parent = rig
    follow = socket.constraints.new('COPY_TRANSFORMS')
    follow.target, follow.subtarget, follow.target_space, follow.owner_space = rig, 'Head', 'WORLD', 'WORLD'
    weapon_rig = bpy.data.objects.new('SWORD | Weapon rig', bpy.data.armatures.new('SWORD local bones'))
    scene.collection.objects.link(weapon_rig)
    weapon_rig.parent, weapon_rig.matrix_basis = socket, Matrix.Translation((0, .1, .05))
    bpy.context.view_layer.objects.active = weapon_rig
    bpy.ops.object.mode_set(mode='EDIT')
    lower = weapon_rig.data.edit_bones.new('Root')  # Root is a bone of the character too.
    lower.head, lower.tail = (0, 0, 0), (0, 0, .1)
    upper = weapon_rig.data.edit_bones.new('Blade')
    upper.head, upper.tail, upper.parent = (0, 0, .1), (0, 0, .6), lower
    bpy.ops.object.mode_set(mode='OBJECT')
    weapon_rig.animation_data_create().action = bpy.data.actions.new('SWORD part clip')
    blade = weapon_rig.pose.bones['Blade']
    blade.rotation_mode = 'XYZ'
    for frame, angle in ((1, 0), (11, .5)):
        blade.rotation_euler = (angle, 0, 0)
        blade.keyframe_insert('rotation_euler', frame=frame)
    sword = box_object('Sword', (0, 0, .3), .05, stretch=(1, 1, 6))
    sword.parent = weapon_rig
    sword.vertex_groups.new(name='Root').add([0, 2, 4, 6], 1.0, 'REPLACE')
    sword.vertex_groups.new(name='Blade').add([1, 3, 5, 7], 1.0, 'REPLACE')
    sword.modifiers.new('Armature', 'ARMATURE').object = weapon_rig
    donor = bpy.data.objects.new('Donor', bpy.data.armatures.new('Donor'))
    scene.collection.objects.link(donor)
    cape = box_object('Cape', (1, 0, 1), .2)
    cape.modifiers.new('Armature', 'ARMATURE').object = donor
    adapter = bpy.data.objects.new('Coat | Bind adapter', bpy.data.armatures.new('Coat bind'))
    adapter['sekiro_internal_bind_adapter'] = True
    scene.collection.objects.link(adapter)
    adapter.parent = rig
    coat = box_object('Coat', (0, 0, 1), .25)
    coat.modifiers.new('Armature', 'ARMATURE').object = adapter
    badge = box_object('Badge', (0, .2, 1), .02)
    badge.parent = rig
    box_object('Floor', (0, 0, 0), 2)
    box_object('Unrendered', (0, 0, 0), 1).hide_render = True
    box_object('Figure', (0, 0, 1), .3)['sekiro_figure_of'] = rig.name
    bpy.context.view_layer.update()
    resting = {obj.name: np.array([obj.matrix_world @ v.co for v in obj.data.vertices]) for obj in (helmet, sword)}
    socket_rest = weapon_rig.matrix_world.copy()

    scene.frame_set(11)  # The head has turned; the export carries the helmet and the sword back to rest.
    blade_pose = np.array(weapon_rig.matrix_world @ weapon_rig.pose.bones['Blade'].matrix)
    parts = export_character(temp / 'parts', rig)
    check_character_export(json.loads((temp / 'parts' / 'manifest.json').read_text(encoding='utf-8')))
    assert [(b['name'], b['parent']) for b in parts['bones']] == \
        [('Root', -1), ('Spine', 0), ('Head', 1), ('SWORD_Root', 2), ('Blade', 3)], parts['bones']
    for index, bone in ((3, 'Root'), (4, 'Blade')):
        wanted = socket_rest @ weapon_rig.data.bones[bone].matrix_local
        assert np.allclose(np.reshape(parts['bones'][index]['rest'], (4, 4)), np.array(wanted), atol=1e-5), bone
    found = {m['name']: m for m in parts['meshes']}
    assert {name: (m['bound'], m.get('bone')) for name, m in found.items()} == \
        {'Box': ('rig', None), 'Helmet': ('bone', 'Head'), 'Sword': ('armature', 'Head')}, found
    with np.load(found['Helmet']['data']) as data:
        assert np.abs(data['positions'] - resting['Helmet']).max() < 1e-5
        assert (data['bone_indices'][:, 0] == 2).all() and (data['bone_weights'][:, 0] == 1).all()
    with np.load(found['Sword']['data']) as data:
        assert np.abs(data['positions'] - resting['Sword']).max() < 1e-5
        assert sorted(set(data['bone_indices'][:, 0].tolist())) == [3, 4] and (data['bone_weights'][:, 0] == 1).all()
    with np.load(parts['motion']['data']) as data:
        assert data['matrices'].shape == (11, 5, 4, 4) and np.allclose(data['matrices'][10, 4], blade_pose, atol=1e-5)
    left = {item['name']: item['reason'] for item in parts['leftOut']}
    assert left == {'Cape': 'bound to another armature, Donor',
                    'Coat': 'bound to Coat | Bind adapter, which keeps a cutscene bind pose that the export does not convert',
                    'Badge': 'moves with Rig but with none of its bones: bind it to a bone with Add weapon in the Retarget '
                             'Assistant, or with an Armature modifier',
                    'Floor': 'not bound to Rig'}, left
    assert 'Left out, not bound to Rig: Floor.' in parts['warnings'], parts['warnings']

print('blender_character_export: texture roles, overlay alpha and color, bones and action pass; a mesh on a bone and a '
      'weapon rig on a socket come back to rest with their bones and motion, and four meshes are left out with reasons')
