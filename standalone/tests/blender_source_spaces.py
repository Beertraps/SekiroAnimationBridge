"""Source spaces in Blender on owned synthetic data. Run with Blender --background --factory-startup --python this_file.py.

Checks that FromSoftware's conversion is unchanged, that an RE Engine motion (and one with a unit scale)
imports, exports and round-trips in its own space, and that a version 5 character manifest builds its
meshes, model bones and materials in that space.
"""
import json
import math
import random
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_bridge import bl_to_game_trs, export_motion, game_to_bl_trs, import_motion  # noqa: E402
from blender_character import import_character  # noqa: E402
from games.space import RE_ENGINE, RE_ENGINE_BASIS, Space  # noqa: E402

COUNT = 8


def turn(axis, angle):
    s = math.sin(angle / 2)
    return [s if axis == 'x' else 0, s if axis == 'y' else 0, s if axis == 'z' else 0, math.cos(angle / 2)]


def bone(index, name, parent, translation, rotation=(0, 0, 0, 1)):
    return dict(index=index, name=name, parent=parent, translation=list(translation), rotation=list(rotation), scale=[1, 1, 1])


def sample(translation, rotation=(0, 0, 0, 1), scale=(1, 1, 1)):
    return dict(translation=list(translation), rotation=list(rotation), scale=list(scale))


def game_matrix(entry):
    """A source TRS as a matrix in the source's own coordinates."""
    x, y, z, w = entry['rotation']
    return Matrix.LocRotScale(Vector(entry['translation']), Quaternion((w, x, y, z)), Vector(entry['scale']))


def close(a, b, tolerance=1e-4):
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


def same_rotation(a, b, tolerance=1e-5):
    return abs(Quaternion((a[3], *a[:3])).dot(Quaternion((b[3], *b[:3])))) > 1 - tolerance


def matrix_error(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))


# FromSoftware: the conversion before source spaces (0.13), compared exactly.
random.seed(7)
for _ in range(200):
    x, y, z, w = (random.uniform(-1, 1) for _ in range(4))
    entry = sample([random.uniform(-3, 3) for _ in range(3)], (x, y, z, w), [random.uniform(.5, 2) for _ in range(3)])
    old = Quaternion((w, -x, -z, -y))
    old.normalize()
    translation, rotation, scale = game_to_bl_trs(entry)
    assert tuple(rotation) == tuple(old), (rotation, old)
    assert tuple(translation) == tuple(Vector((entry['translation'][0], entry['translation'][2], entry['translation'][1])))
    assert tuple(scale) == tuple(Vector((entry['scale'][0], entry['scale'][2], entry['scale'][1])))
    back = bl_to_game_trs(translation, rotation, scale)
    normalized = rotation.normalized()
    assert back['rotation'] == [float(-normalized.x), float(-normalized.z), float(-normalized.y), float(normalized.w)]
    assert back['translation'] == [float(translation.x), float(translation.z), float(translation.y)]


def owned_motion(space):
    """A walking three-bone clip in a source space: up is Y, forward is Z, as in RE Engine."""
    bones = [bone(0, 'root', -1, [0, 0, 0]), bone(1, 'Hip', 0, [0, 95, 0] if space.unit != 1 else [0, .95, 0], turn('y', .4)),
             bone(2, 'Spine', 1, [0, 12, 3] if space.unit != 1 else [0, .12, .03], turn('x', -.2))]
    step = 100 if space.unit != 1 else 1
    frames = [[sample([0, 0, 0]), sample([.01 * i * step, (.95 + .02 * math.sin(i)) * step, .1 * i * step], turn('y', .4 + .1 * i)),
               sample([0, .12 * step, .03 * step], turn('z', .07 * i), (1, 1 + .01 * i, 1))] for i in range(COUNT)]
    return dict(format='sekiro-animation-bridge', formatVersion=2, clip='owned.motlist.85', skeletonName='Owned', game='dmc5',
                skeleton=dict(name='Owned', boneCount=3, bones=bones), frameCount=COUNT, frameRate=60.0,
                duration=(COUNT - 1) / 60, trackCount=3, blockCount=0, compression='decoded', trackBoneIndices=[0, 1, 2],
                trackNames=['root', 'Hip', 'Spine'], frames=frames,
                rootMotion=[[.05 * i * step, 0, .2 * i * step, .03 * i] for i in range(COUNT)], rootUp=[0, 1, 0, 0],
                rootForward=[0, 0, 1, 0], archive='owned.motlist.85', member='owned',
                source=dict(engine='re_engine', game='dmc5', container='motlist', version=85, archive='owned.motlist.85',
                            member='owned', index=0), **space.to_json())


def check_motion(space, temp):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    motion = owned_motion(space)
    rig = import_motion(motion)
    to_blender, to_source = Matrix(space.matrix()), Matrix(space.inverse_matrix())
    bones = motion['skeleton']['bones']
    for name, entry in zip(('root', 'Hip', 'Spine'), bones):
        world = game_matrix(entry) if entry['parent'] < 0 else None
        if world is None:
            world = Matrix.Identity(4)
            index = entry['index']
            chain = []
            while index >= 0:
                chain.append(bones[index])
                index = bones[index]['parent']
            for item in reversed(chain):
                world = world @ game_matrix(item)
        assert matrix_error(rig.data.bones[name].matrix_local, to_blender @ world @ to_source) < 1e-4, (space, name)
    for frame in (0, COUNT - 1):
        bpy.context.scene.frame_set(frame + 1)
        bpy.context.view_layer.update()
        world = Matrix.Identity(4)
        for track, name in enumerate(('root', 'Hip', 'Spine')):
            world = world @ game_matrix(motion['frames'][frame][track])
            expected = to_blender @ world @ to_source
            assert matrix_error(rig.pose.bones[name].matrix, expected) < 1e-4, (space, frame, name)
        root = next(obj for obj in bpy.data.objects if obj.get('sekiro_root_motion'))
        sample_ = motion['rootMotion'][frame]
        assert close(root.location, space.point(sample_[:3])), (space, root.location, sample_)
        assert abs(root.rotation_euler.z - space.yaw(sample_[3])) < 1e-5
    # Blender's height of the hip is the source's Y, scaled.
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    assert abs(rig.pose.bones['Hip'].head.z - motion['frames'][0][1]['translation'][1] * space.unit) < 1e-4

    output = Path(temp) / 'owned.motion.json'
    export_motion(output)
    result = json.loads(output.read_text())
    assert result['basis'] == motion['basis'] and result['unitScale'] == motion['unitScale'], 'The export lost the source space'
    assert result['source']['engine'] == 're_engine'
    for i in range(COUNT):
        for track in range(3):
            a, b = motion['frames'][i][track], result['frames'][i][track]
            assert close(a['translation'], b['translation'], 1e-3 if space.unit != 1 else 1e-5), (space, i, track, a, b)
            assert same_rotation(a['rotation'], b['rotation']), (space, i, track, a, b)
            assert close(a['scale'], b['scale'], 1e-5), (space, i, track)
        assert close(result['rootMotion'][i], motion['rootMotion'][i], 1e-3), (space, i, result['rootMotion'][i])
    return rig, motion


def write_png(path):
    image = bpy.data.images.new('owned-atos', 2, 2, alpha=True)
    image.pixels = [1, 0, 0, 1] * 4
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def check_character(rig, motion, temp):
    space = RE_ENGINE
    bones = motion['skeleton']['bones']
    extra = dict(name='Model extra', parent=2, translation=[0, .1, .05], rotation=turn('x', .3), scale=[1, 1, 1])
    names = [b['name'] for b in bones] + [extra['name']]
    # A triangle facing source +Z, weighted to the hip and the model-only bone.
    positions = np.asarray([[0, 1, .1], [.1, 1, .1], [0, 1.1, .1]], np.float32)
    data = Path(temp) / '00_pl0100.npz'
    np.savez(data, positions=positions, normals=np.asarray([[0, 0, 1]] * 3, np.float32), uvs=np.zeros((3, 2), np.float32),
             uv_0=np.zeros((3, 2), np.float32), bone_indices=np.asarray([[1, 0, 0, 0], [1, 0, 0, 0], [3, 0, 0, 0]], np.int32),
             bone_weights=np.asarray([[1, 0, 0, 0]] * 3, np.float32), faces=np.asarray([[0, 1, 2]], np.int32),
             face_materials=np.asarray([0], np.int32), vertex_materials=np.asarray([0, 0, 0], np.int32),
             bone_names=np.asarray(names), bone_parents=np.asarray([b['parent'] for b in bones] + [extra['parent']], np.int32),
             bone_translations=np.asarray([b['translation'] for b in bones] + [extra['translation']], np.float32),
             bone_quaternions=np.asarray([b['rotation'] for b in bones] + [extra['rotation']], np.float32),
             bone_scales=np.ones((4, 3), np.float32), material_names=np.asarray(['hair', 'eye']))
    png = Path(temp) / 'owned_ATOS.png'
    write_png(png)
    hair = dict(name='hair', mtd='Hair.mmtr', family='Devil May Cry 5', albedo=None, normal=None, emissive=None, samplers=[],
                alpha=False, color=[.5, .4, .3], opacity=dict(path=str(png), linear=True, uv=0, scale=[1, 1], channel='R', stem='owned_ATOS'))
    eye = dict(name='eye', mtd='EyeTransparent.mmtr', family='Devil May Cry 5', albedo=None, normal=None, emissive=None, samplers=[],
               alpha=False, color=[1, 1, 1], opacityValue=0.0)
    manifest = dict(version=5, game='dmc5', boneRotation='quaternion', warnings=[], material_library='', texture_count=1,
                    models=[dict(name='pl0100', source='natives/x64/character/player/pl0100_dante/pl0100_body/pl0100.mesh.1808282334',
                                 data=str(data), materials=[hair, eye], stats=dict(vertices=3, triangles=1), attachment=None, role='Body')],
                    **space.to_json())
    path = Path(temp) / 'character.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    objects = import_character(path, rig)
    assert [obj.name for obj in objects] == ['PL0100 | Body'], [obj.name for obj in objects]
    mesh = objects[0].data
    for vertex, source in zip(mesh.vertices, positions):
        assert close(vertex.co, space.point(source), 1e-6), (vertex.co, source)
    # A rotation keeps the winding: the face still points along the source's +Z, which is Blender -Y.
    assert close(mesh.polygons[0].normal, space.vector((0, 0, 1)), 1e-5), mesh.polygons[0].normal
    to_blender, to_source = Matrix(space.matrix()), Matrix(space.inverse_matrix())
    world = Matrix.Identity(4)
    for item in (bones[0], bones[1], bones[2], extra):
        world = world @ game_matrix(item)
    model_bone = rig.data.bones['Model extra']
    expected = to_blender @ world @ to_source
    assert close(model_bone.head_local, expected.to_translation(), 1e-5), (model_bone.head_local, expected.to_translation())
    assert abs(model_bone.matrix_local.to_quaternion().dot(expected.to_quaternion())) > 1 - 1e-5
    assert not any(obj.name.endswith('Bind adapter') for obj in bpy.data.objects), 'A matching bind pose received an adapter'
    materials = {material.name: material for material in mesh.materials}
    assert set(materials) == {'Devil May Cry 5 / hair', 'Devil May Cry 5 / eye'}, set(materials)
    hair_shader = materials['Devil May Cry 5 / hair'].node_tree.nodes['Principled BSDF']
    alpha_link = hair_shader.inputs['Alpha'].links[0]
    assert alpha_link.from_node.type == 'SEPARATE_COLOR' and alpha_link.from_socket.name == 'Red', alpha_link.from_node.type
    eye_shader = materials['Devil May Cry 5 / eye'].node_tree.nodes['Principled BSDF']
    assert eye_shader.inputs['Alpha'].default_value == 0.0 and not eye_shader.inputs['Alpha'].links


with tempfile.TemporaryDirectory() as temp:
    check_motion(Space(RE_ENGINE_BASIS, .01), temp)
    rig, motion = check_motion(RE_ENGINE, temp)
    check_character(rig, motion, temp)
print('PASS: FromSoftware conversion unchanged; RE Engine and scaled motions import, export and round-trip in their space; '
      'manifest 5 meshes, model bones and materials follow it', flush=True)
