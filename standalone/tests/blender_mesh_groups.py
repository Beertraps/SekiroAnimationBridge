"""NPC mask objects preserve skinning and retarget behavior. Run in background Blender.

Compare the same owned geometry imported as one legacy mesh and as numbered
groups, both directly on the rig and through a mismatched bind adapter.
"""
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1] / 'blender_addon')]
import humanoids
from blender_bridge import import_motion, export_motion
from blender_character import import_character
import sekiro_retarget
from sekiro_retarget import retarget, mirror, control_rig

COUNT = 4
WORK = Path(tempfile.mkdtemp(prefix='SekiroMeshGroups-'))


def motion(name, size, turn):
    bones = humanoids.fromsoftware(30, 'souls')
    indices = {bone[0]: i for i, bone in enumerate(bones)}
    heads = {name: np.asarray(head)[[0, 2, 1]] * size for name, _, head, _ in bones}
    skeleton = [dict(index=i, name=name, parent=indices[parent] if parent else -1,
                     translation=list(heads[name] - (heads[parent] if parent else 0)),
                     rotation=[0, 0, 0, 1], scale=[1, 1, 1]) for i, (name, parent, _, _) in enumerate(bones)]
    frames = []
    for frame in range(COUNT):
        values = []
        for bone in skeleton:
            angle = turn * frame / (COUNT - 1) if bone['name'] in ('Spine', 'R_UpperArm', 'R_Finger1', 'R_Weapon') else 0
            values.append(dict(translation=bone['translation'], rotation=[math.sin(angle / 2), 0, 0, math.cos(angle / 2)],
                               scale=[1, 1, 1]))
        frames.append(values)
    return dict(format='sekiro-animation-bridge', formatVersion=1, skeletonName=name, clip='a000_003000.hkx', game='sekiro',
                skeleton=dict(name=name, bones=skeleton, boneCount=len(skeleton)), frames=frames, frameCount=COUNT,
                frameRate=30, duration=(COUNT - 1) / 30, trackCount=len(skeleton), trackBoneIndices=list(range(len(skeleton))),
                trackNames=[bone['name'] for bone in skeleton], rootMotion=[[.01 * f, 0, 0, 0] for f in range(COUNT)])


def character(clip, split, adapter):
    bones = clip['skeleton']['bones']
    indices = {bone['name']: i for i, bone in enumerate(bones)}
    heads = {}
    for bone in bones:
        heads[bone['name']] = np.asarray(bone['translation']) + (heads[bones[bone['parent']]['name']] if bone['parent'] >= 0 else 0)
    size = heads['Head'][1] / 1.65
    pos, faces, materials, vertex_materials, influences = [], [], [], [], []

    def box(bone, low, high, material, other=None):
        start = len(pos)
        origin = heads[bone]
        pos.extend(origin + np.array([(high if i >> axis & 1 else low)[axis] for axis in range(3)]) * size for i in range(8))
        faces.extend(np.array([[0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5], [0, 1, 5], [0, 5, 4],
                               [2, 6, 7], [2, 7, 3], [0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6]]) + start)
        materials.extend([material] * 12)
        vertex_materials.extend([material] * 8)
        influences.extend([{bone: .7, other: .3} if other else {bone: 1.0} for _ in range(8)])

    box('Head', (-.06, -.06, -.06), (.06, .06, .06), 0)
    box('Spine', (-.15, -.05, -.09), (.15, .30, .09), 1, 'Pelvis')
    box('R_Finger1', (-.02, -.01, -.01), (.02, .01, .01), 2, 'R_Hand')
    box('R_Weapon', (-.10, -.008, -.012), (.75, .008, .012), 3)
    box('L_Hand', (-.015, -.02, -.01), (.015, .02, .01), 4)
    # A loose weighted vertex has no face but must still contribute to retarget geometry.
    pos.append(heads['R_Weapon'] + np.array([.85, 0, 0]) * size)
    influences.append({'R_Weapon': 1.0}); vertex_materials.append(3)
    ix, weights = np.zeros((len(pos), 4), np.int32), np.zeros((len(pos), 4), np.float32)
    for row, groups in enumerate(influences):
        for column, (name, weight) in enumerate(groups.items()):
            ix[row, column], weights[row, column] = indices[name], weight
    translations = np.array([bone['translation'] for bone in bones])
    if adapter:
        translations[0, 0] += .08
    uv = np.arange(len(pos) * 2, dtype=np.float32).reshape(-1, 2) / (len(pos) * 2)
    arrays = dict(positions=np.array(pos, np.float32), faces=np.array(faces, np.int32), bone_indices=ix, bone_weights=weights,
                  bone_names=np.array(list(indices)), bone_parents=np.array([bone['parent'] for bone in bones]),
                  bone_translations=translations, bone_rotations=np.zeros((len(bones), 3)), bone_scales=np.ones((len(bones), 3)),
                  uv_0=uv, uv_1=uv * .5, normals=np.tile([0., 0., 1.], (len(pos), 1)), face_materials=np.array(materials))
    if split:
        arrays['vertex_materials'] = np.array(vertex_materials)
    data = WORK / (clip['skeletonName'] + '.npz'); np.savez_compressed(data, **arrays)
    specs = [dict(name=name) for name in ('Shared face', '#10# body', '#10# fingers', '#00# sword', '#11# alternate hand')]
    model = dict(name=clip['skeletonName'], source='Owned fixture', data=str(data), materials=specs, stats={})
    manifest = WORK / (clip['skeletonName'] + '.json')
    manifest.write_text(json.dumps(dict(models=[model], texture_count=0, warnings=[])), encoding='utf-8')
    return manifest, arrays


def ordered(values):
    values = np.asarray(values)
    # Symmetric corners can differ by a float rounding bit after controls are added.
    return values[np.lexsort(np.round(values, 5).T[::-1])]


def points(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    return ordered(np.concatenate([retarget.evaluated_points(obj, graph) for obj in objects]))


def exported(tag):
    path = WORK / (tag + '.motion.json'); export_motion(path)
    return json.loads(path.read_text(encoding='utf-8'))


def check(split, adapter):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    clips = [motion('c9998', 1.0, .25), motion('c9999', 1.2, .05)]
    rigs, objects, probes = [], [], []
    for clip in clips:
        rig = import_motion(clip)
        manifest, preview = character(clip, split, adapter)
        pieces = import_character(manifest, rig)
        assert len(pieces) == (4 if split else 1)
        assert sum(len(obj.data.vertices) for obj in pieces) == len(preview['positions'])
        assert sum(len(obj.data.polygons) for obj in pieces) == len(preview['faces'])
        assert len({obj.modifiers[0].object for obj in pieces}) == 1
        assert (pieces[0].modifiers[0].object != rig) == adapter
        assert json.loads(rig['sekiro_preview_meshes']) == [obj.name for obj in pieces]
        rigs.append(rig); objects.append(pieces)
        # Vertex weights, both UV streams, material indices and custom normals survive the split.
        material_counts = np.zeros(5, int)
        for obj in pieces:
            assert obj.parent == rig and obj.data.has_custom_normals
            for polygon in obj.data.polygons: material_counts[polygon.material_index] += 1
            for vertex in obj.data.vertices:
                at = np.flatnonzero(np.linalg.norm(preview['positions'][:, [0, 2, 1]] - np.array(vertex.co), axis=1) < 1e-7)[0]
                expected = {str(preview['bone_names'][i]): w for i, w in zip(preview['bone_indices'][at], preview['bone_weights'][at]) if w > 0}
                actual = {obj.vertex_groups[g.group].name: g.weight for g in vertex.groups}
                assert actual == expected, (actual, expected)
            for loop in obj.data.loops:
                at = np.flatnonzero(np.linalg.norm(preview['positions'][:, [0, 2, 1]] - np.array(obj.data.vertices[loop.vertex_index].co), axis=1) < 1e-7)[0]
                for key in ('uv_0', 'uv_1'):
                    expected = preview[key][at].copy(); expected[1] = 1 - expected[1]
                    np.testing.assert_allclose(obj.data.uv_layers[key].data[loop.index].uv, expected, atol=1e-7)
        np.testing.assert_array_equal(material_counts, [12] * 5)
        samples = []
        for frame in range(1, COUNT + 1):
            bpy.context.scene.frame_set(frame); bpy.context.view_layer.update(); samples.append(points(pieces))
        graph = bpy.context.evaluated_depsgraph_get()
        weapon = ordered(retarget.weapon_points(rig, 'R_Weapon', graph))
        fingers = retarget.finger_skin(rig, ['R_Finger1'])['R_Finger1']
        body = retarget.matching.anatomy(retarget.rig_bones(rig))
        geometry = retarget.body_geometry(rig, body, graph)
        assert geometry and len(geometry['faces']) == 12
        torso = retarget.skin(geometry['chunks'], {bone.name: bone.matrix for bone in rig.pose.bones})
        probes.append((samples, weapon, ordered(fingers[0]), fingers[1], ordered(torso), mirror.skins(rig)))
    scene = bpy.context.scene
    target, source = rigs[1], rigs[0]
    before = exported('visible')
    objects[1][-1].hide_set(True); objects[1][-1].hide_render = True
    assert all(obj.visible_get() for obj in objects[1][:-1])
    assert exported('hidden') == before, 'Hiding a mesh changed animation export'
    objects[1][-1].hide_set(False); objects[1][-1].hide_render = False
    settings = scene.sekiro_retarget; settings.source, settings.target = source, target
    settings.weapon_grip = 'SOURCE'; settings.finger_fit = False
    settings.body_clearance = settings.arm_gap = True
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    bakes = []
    for method in ('BONES', 'BODY'):
        settings.method = method
        assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
        samples = []
        for frame in range(1, COUNT + 1):
            scene.frame_set(frame)
            samples.append([value for bone in target.pose.bones for row in bone.matrix_basis for value in row])
        bakes.append(np.array(samples))
    # The generated controls keep all of the split objects on the animated game rig.
    original = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame); bpy.context.view_layer.update(); original.append(points(objects[1]))
    control_rig.add(bpy.context, target)
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame); bpy.context.view_layer.update()
        np.testing.assert_allclose(points(objects[1]), original[frame - 1], atol=2e-5)
    return probes, bakes


sekiro_retarget.register()
for adapter in (False, True):
    combined, combined_bakes = check(False, adapter)
    split, split_bakes = check(True, adapter)
    for expected, actual in zip(combined, split):
        for a, b in zip(expected[:5], actual[:5]): np.testing.assert_allclose(a, b, atol=2e-6)
        assert expected[5] == actual[5], 'Mesh splitting changed the mirror skin relationships'
    for a, b in zip(combined_bakes, split_bakes): np.testing.assert_allclose(a, b, atol=2e-5)
sekiro_retarget.unregister()
print('PASS: NPC groups hide independently; geometry, weights, UVs, normals, direct/adapter skinning, weapon/finger/torso reads, '
      'mirror skin relationships, both retarget bakes, controls and export match the combined mesh')
