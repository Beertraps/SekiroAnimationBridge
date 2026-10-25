"""Part animation on an owned weapon rig, independent of game assets.

A 30 fps part clip keys a weapon rig in a 60 fps scene. Its skeleton parents two
bones differently from the FLVER, holds one bone the FLVER lacks and leaves one
bone without a track; the FLVER has bones the skeleton lacks. Every bone must take
the skeleton's pose, and the export must give back the clip's samples, also after
the scene is saved and opened again. A second character with the same weapon stays
out of the export.

Run Blender --background --factory-startup --python THIS -- OUTPUT_DIRECTORY
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_bridge import action_curves  # noqa: E402
from blender_character import import_character  # noqa: E402
from blender_parts import export_parts, part_rigs  # noqa: E402

out = Path(sys.argv[sys.argv.index('--') + 1]); out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.render.fps, scene.render.fps_base = 60, 1.0
CONVERSION = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))

# FLVER bones in game space: name, parent, translation and XZY rotation.
FLVER = [('W_Root', -1, (0, 0, 0), (0, 0, 0)),
         ('W_Mid', 0, (0, .1, 0), (.1, 0, 0)),
         ('W_Tip', 1, (0, .12, .01), (0, .2, 0)),
         ('W_Wing', 0, (.05, .05, 0), (0, 0, .3)),
         ('W_Flap', 0, (.1, .06, 0), (0, .1, .2)),
         ('W_Tassel', 4, (0, -.05, .02), (.2, 0, 0))]
# The part skeleton: W_Tip and W_Flap have other parents, W_Flap has no track, W_Extra is not in the FLVER.
SKELETON = [('W_Root', -1), ('W_Wing', 0), ('W_Tip', 0), ('W_Flap', 1), ('W_Extra', 0)]
TRACKS, FRAMES = [0, 1, 2], 5

bind = []
for name, parent, translation, rotation in FLVER:
    local = Matrix.LocRotScale(Vector(translation), Euler(rotation, 'XZY').to_quaternion(), Vector((1, 1, 1)))
    bind.append(bind[parent] @ local if parent >= 0 else local)
flver_index = {bone[0]: index for index, bone in enumerate(FLVER)}
reference = []
for name, parent in SKELETON:
    world = bind[flver_index[name]] if name in flver_index else bind[0] @ Matrix.Translation((0, .2, 0))
    parent_world = bind[flver_index[SKELETON[parent][0]]] if parent >= 0 else Matrix()
    reference.append(parent_world.inverted() @ world)


def animated(index, frame):
    """A track on a clip frame: its reference pose moved and turned, and W_Wing also grown."""
    turn = Euler((.15 * frame * (index + 1), .1 * frame, -.05 * frame * index), 'XYZ').to_matrix().to_4x4()
    move = Matrix.Translation((.01 * frame, .02 * frame * (index == 0), -.01 * frame * index))
    grow = Matrix.Scale(1 + .1 * frame, 4) if SKELETON[index][0] == 'W_Wing' else Matrix()
    return move @ reference[index] @ turn @ grow


def sample(matrix):
    translation, rotation, scale = matrix.decompose()
    return dict(translation=list(translation), rotation=[rotation.x, rotation.y, rotation.z, rotation.w], scale=list(scale))


def skeleton_worlds(frame):
    """Game-space world matrices of the skeleton on a clip frame."""
    worlds = []
    for index, (name, parent) in enumerate(SKELETON):
        local = animated(index, frame) if index in TRACKS else reference[index]
        worlds.append(worlds[parent] @ local if parent >= 0 else local)
    return worlds


motion = dict(format='sekiro-animation-bridge', formatVersion=1, game='sekiro', clip='a076_405010_1.hkx',
              frameCount=FRAMES, frameRate=30.0, duration=(FRAMES - 1) / 30, skeletonName='Owned part skeleton',
              skeleton=dict(name='Owned part skeleton', boneCount=len(SKELETON),
                            bones=[dict(index=i, name=name, parent=parent, **sample(reference[i])) for i, (name, parent) in enumerate(SKELETON)]),
              trackCount=len(TRACKS), trackBoneIndices=TRACKS, trackNames=[SKELETON[i][0] for i in TRACKS],
              frames=[[sample(animated(i, f)) for i in TRACKS] for f in range(FRAMES)], rootMotion=None,
              part=dict(model='wp_a_9990_1', binder='WP_A_9990_1.anibnd', id='a076_405010', reason='same ID'))
clip = out / 'part-clip.json'
clip.write_text(json.dumps(motion), encoding='utf-8')

def character(name, x):
    """An owned character rig with a weapon socket, marked as the bridge's."""
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name + ' skeleton')); scene.collection.objects.link(rig)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = rig; rig.select_set(True); bpy.ops.object.mode_set(mode='EDIT')
    socket = rig.data.edit_bones.new('R_Weapon'); socket.length = .1; socket.matrix = Matrix.Translation((.3 + x, .1, 1.2))
    bpy.ops.object.mode_set(mode='OBJECT')
    rig['sekiro_animation_bridge'] = True
    return rig


rig = character('Owned character', 0)
scene['sekiro_bridge_export_rig'] = rig
data = out / 'owned-part.npz'
# The mesh weights W_Root, W_Tip and W_Tassel; the rig must also build the skeleton's W_Wing and W_Flap.
np.savez_compressed(data, positions=np.array([[0, 0, 0], [0, .22, .01], [.1, .01, .02]], np.float32),
                    faces=np.array([[0, 1, 2]], np.int32), bone_indices=np.array([[0, 0, 0, 0], [2, 0, 0, 0], [5, 0, 0, 0]], np.int32),
                    bone_weights=np.tile([1., 0, 0, 0], (3, 1)), bone_names=np.array([b[0] for b in FLVER]),
                    bone_parents=np.array([b[1] for b in FLVER]), bone_translations=np.array([b[2] for b in FLVER], float),
                    bone_rotations=np.array([b[3] for b in FLVER], float), bone_scales=np.ones((len(FLVER), 3)),
                    uv_0=np.zeros((3, 2)), normals=np.tile([0, 0, 1], (3, 1)), face_materials=np.array([0]))
attachment = dict(bone='R_Weapon', dummy=118, matrix=[list(r) for r in Matrix.Translation((.02, 0, .01))])
model = dict(name='wp_a_9990_1', source='Owned fixture', data=str(data), stats={}, materials=[dict(name='Owned material')],
             attachment=attachment, animation=dict(motion=str(clip), clip='a076_405010_1.hkx', binder='WP_A_9990_1.anibnd',
                                                   id='a076_405010', reason='same ID', frames=FRAMES, frameRate=30.0))
manifest = out / 'owned-character.json'
manifest.write_text(json.dumps(dict(models=[model], texture_count=0, warnings=[])), encoding='utf-8')
import_character(manifest, rig)

rigs = part_rigs(scene)
assert len(rigs) == 1, rigs
weapon = rigs[0]
assert set(weapon.pose.bones.keys()) == {'W_Root', 'W_Mid', 'W_Tip', 'W_Wing', 'W_Flap', 'W_Tassel'}, weapon.pose.bones.keys()
assert len(rig.data.bones) == 1, 'Part bones leaked into the character skeleton'
action = weapon.animation_data.action
assert action.name == 'WP_A_9990_1 | a076_405010_1', action.name
keyed = {curve.data_path.split('"')[1] for curve in action_curves(action)}
assert keyed == {'W_Root', 'W_Wing', 'W_Tip', 'W_Flap'}, keyed
times = sorted({point.co[0] for curve in action_curves(action) for point in curve.keyframe_points})
# 30 fps keys in a 60 fps scene fall on every second frame.
assert times == [1, 3, 5, 7, 9], times

weapon.hide_set(False)
errors = []
for frame in range(FRAMES):
    scene.frame_set(1 + 2 * frame); bpy.context.view_layer.update()
    worlds = skeleton_worlds(frame)
    expected = {name: CONVERSION @ worlds[i] @ CONVERSION for i, (name, _) in enumerate(SKELETON) if name in weapon.pose.bones}
    # A FLVER bone outside the skeleton keeps its rest offset from its parent.
    tassel = weapon.pose.bones['W_Tassel']
    expected['W_Tassel'] = expected['W_Flap'] @ tassel.parent.bone.matrix_local.inverted() @ tassel.bone.matrix_local
    for name, matrix in expected.items():
        errors.append(max(abs(a - b) for row_a, row_b in zip(weapon.pose.bones[name].matrix, matrix) for a, b in zip(row_a, row_b)))
assert max(errors) < 2e-5, errors
weapon.hide_set(True)

# A second character with the same animated weapon, such as a retarget donor appended by hand, stays out of the export.
donor = character('Owned donor', 2)
import_character(manifest, donor)
animated = [obj for obj in scene.objects if obj.get('sekiro_part_source_text_data')]
assert len(animated) == 2 and part_rigs(scene) == [weapon], (animated, part_rigs(scene))


def exported(folder, start, end):
    index = export_parts(folder, start, end)
    assert [row['name'] for row in index] == ['WP_A_9990_1'] and not index[0]['missingBones'], index
    return json.loads(Path(index[0]['motion']).read_text(encoding='utf-8'))


def sample_error(frames, source):
    worst = 0.0
    for got_frame, source_frame in zip(frames, source):
        for got, want in zip(got_frame, source_frame):
            sign = 1 if sum(a * b for a, b in zip(got['rotation'], want['rotation'])) >= 0 else -1
            worst = max([worst] + [abs(a - b) for key in ('translation', 'scale') for a, b in zip(got[key], want[key])]
                        + [abs(sign * a - b) for a, b in zip(got['rotation'], want['rotation'])])
    return worst


full = exported(out / 'parts', 1, 9)
assert (full['frameCount'], full['frameRate'], full['trackBoneIndices']) == (FRAMES, 30.0, TRACKS), full['frameCount']
assert full['export']['action'] == action.name and full['rootMotion'] is None
first = sample_error(full['frames'], motion['frames'])
assert first < 2e-5, first
part = exported(out / 'parts-short', 1, 5)
assert part['frameCount'] == 3 and sample_error(part['frames'], motion['frames'][:3]) < 2e-5, part['frameCount']
assert weapon.hide_get(), 'The export left the weapon rig shown'

# The clip travels with the scene: the rig and its stored source survive saving and opening it.
blend = out / 'owned-part.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.open_mainfile(filepath=str(blend))
reopened = exported(out / 'parts-reopened', 1, 9)
second = sample_error(reopened['frames'], motion['frames'])
assert second < 2e-5, second
report = dict(frames=FRAMES, clipRate=30, sceneRate=60, keyedBones=sorted(keyed), donorWeaponsExported=0, maximum_pose_error=max(errors),
              maximum_export_error=first, maximum_reopened_error=second)
(out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('OWNED PART ANIMATION CHECK ' + json.dumps(report), flush=True)
