"""Two-character import on owned synthetic rigs. Run with Blender --background --factory-startup --python this_file.py.

A FromSoftware-style target and a larger donor of the same name come from one
import, as Sekiro and Elden Ring both call the player c0000. Checked: the
donor's names, its own action, root motion and embedded metadata, the target
keeping the scene's frame range, frame rate and export rig, the donor standing
clear of the target, an export of the target matching a single-character
import, the add-on filling the rig pair when the file opens, and a bake that
the donor's placement does not change.
"""
import json
import math
import sys
import tempfile
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import (character_span, embedded_motion, export_motion, import_donor, import_motion, inspect_scene,
                            paired_root_action, root_motion_object)
from blender_character import import_character
import sekiro_retarget
from sekiro_retarget import imported_pair

CLIP, ROOTS = 'a000_003000.hkx', ('Master', 'RootPos', 'RootRotY', 'RootRotXZ', 'Lower_Root', 'Upper_Root')


def game(v):
    return Vector((v[0], v[2], v[1]))


def motion(bones, animated, game_id, count, rate):
    """Synthetic motion JSON of c0000 in one game. Animated bones turn about X over the clip."""
    index = {bone[0]: i for i, bone in enumerate(bones)}
    skeleton = []
    for i, (name, parent, head, label) in enumerate(bones):
        local = game(head) - (game(bones[index[parent]][2]) if parent else Vector())
        skeleton.append(dict(index=i, name=name, parent=index[parent] if parent else -1, translation=list(local),
                             rotation=[0, 0, 0, 1], scale=[1, 1, 1]))
    tracks = [i for i, bone in enumerate(bones) if bone[3] or bone[0] in ROOTS or bone[0] in animated]
    frames = []
    for f in range(count):
        frame = []
        for i in tracks:
            angle = animated.get(bones[i][0], 0) * f / (count - 1)
            frame.append(dict(translation=skeleton[i]['translation'], rotation=[math.sin(angle / 2), 0, 0, math.cos(angle / 2)],
                              scale=[1, 1, 1]))
        frames.append(frame)
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip=CLIP, skeletonName='c0000', game=game_id,
                skeleton=dict(name='c0000', boneCount=len(skeleton), bones=skeleton), frameCount=count, frameRate=rate,
                duration=(count - 1) / rate, trackCount=len(tracks), trackBoneIndices=tracks,
                trackNames=[bones[i][0] for i in tracks], frames=frames,
                rootMotion=[[.02 * f, 0, .03 * f, .01 * f] for f in range(count)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


def character(folder, bones, tag, size):
    """A character manifest with one box part skinned to the pelvis, as the bridge prepares model parts."""
    pelvis = game(next(head for name, parent, head, label in bones if name == 'Pelvis'))
    low, high = (-.3 * size, 0, -.2 * size), (.3 * size, 1.8 * size, .2 * size)
    positions = np.array([[(high if i >> axis & 1 else low)[axis] for axis in range(3)] for i in range(8)], np.float32)
    faces = np.array([[0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5], [0, 1, 5], [0, 5, 4],
                      [2, 6, 7], [2, 7, 3], [0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6]], np.int32)
    data = folder / f'{tag}.npz'
    np.savez_compressed(data, positions=positions, faces=faces, bone_indices=np.zeros((8, 4), np.int32),
                        bone_weights=np.tile([1., 0, 0, 0], (8, 1)), bone_names=np.array(['Pelvis']), bone_parents=np.array([-1]),
                        bone_translations=np.array([list(pelvis)]), bone_rotations=np.zeros((1, 3)), bone_scales=np.ones((1, 3)),
                        uv_0=np.zeros((8, 2)), face_materials=np.zeros(len(faces), np.int32))
    manifest = folder / f'{tag}.json'
    model = dict(name='bd_owned', source='Owned fixture', data=str(data), stats={}, materials=[dict(name='Owned material')])
    manifest.write_text(json.dumps(dict(models=[model], texture_count=0, warnings=[])), encoding='utf-8')
    return manifest


def names(kind):
    return sorted(item.name for item in getattr(bpy.data, kind))


temp = Path(tempfile.mkdtemp(prefix='SekiroTwoCharacters-'))
target_bones = humanoids.fromsoftware(45, 'elden')
donor_bones = [(name, parent, tuple(1.4 * v for v in head), label) for name, parent, head, label in humanoids.fromsoftware(0, 'souls')]
target_motion = motion(target_bones, {'Spine': .4, 'L_UpperArm': .6}, 'sekiro', 24, 30)
donor_motion = motion(donor_bones, {'L_UpperArm': .9, 'R_Thigh': .5, 'Spine1': .3}, 'er', 40, 60)
target_manifest, donor_manifest = character(temp, target_bones, 'target', 1.0), character(temp, donor_bones, 'donor', 1.4)


def import_target():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = import_motion(target_motion)
    import_character(target_manifest, rig)
    return rig


# A single-character import of the target is the reference for its export.
import_target()
export_motion(temp / 'single.json')
single_actions = [action['name'] for action in inspect_scene(temp / 'single-scene.json')['actions']]

target = import_target()
donor = import_donor(donor_motion, target, donor_manifest)
scene = bpy.context.scene
assert (target.name, target.data.name, donor.name, donor.data.name) == ('c0000', 'c0000', 'Donor c0000', 'Donor c0000')
assert names('collections') == ['Donor - a000_003000', 'Donor | Character', 'Sekiro - a000_003000', 'Sekiro | Character'], names('collections')
assert names('actions') == ['Donor a000_003000_RootMotion', 'Donor a000_003000_Sekiro', 'a000_003000_RootMotion', 'a000_003000_Sekiro'], names('actions')
assert names('texts') == ['Sekiro Character Report - Donor.json', 'Sekiro Character Report.json',
                          'Sekiro Source - Donor - a000_003000.json', 'Sekiro Source - a000_003000.json'], names('texts')
donor_objects = sorted(obj.name for obj in bpy.data.collections['Donor - a000_003000'].all_objects)
assert donor_objects == ['Donor BD_OWNED | Torso', 'Donor HKX_RootMotion', 'Donor c0000'], donor_objects
assert json.loads(donor['sekiro_preview_meshes']) == ['Donor BD_OWNED | Torso'], donor['sekiro_preview_meshes']

# Each rig keeps its own action, root-motion object and embedded metadata.
for rig, text, root_name, game_id, count in ((target, 'Sekiro Source - a000_003000.json', 'HKX_RootMotion', 'sekiro', 24),
                                             (donor, 'Sekiro Source - Donor - a000_003000.json', 'Donor HKX_RootMotion', 'er', 40)):
    root = root_motion_object(rig)
    assert rig['sekiro_bridge_source_text'] == text and rig['sekiro_bridge_source_text_data'] == bpy.data.texts[text], rig.name
    assert root.name == root_name and rig['sekiro_root_motion_object'] == root_name, root.name
    assert (embedded_motion(rig)['game'], embedded_motion(rig)['frameCount']) == (game_id, count), rig.name
    assert rig['sekiro_game'] == game_id, rig.name  # The retarget add-on reads the game's bone names from it.
    action = rig.animation_data.action
    assert paired_root_action(action) == root.animation_data.action, action.name
    if hasattr(rig.animation_data, 'action_slot'):
        assert rig.animation_data.action_slot.identifier == 'OB' + rig.name, rig.animation_data.action_slot.identifier
        assert root.animation_data.action_slot.identifier == 'OB' + root.name, root.animation_data.action_slot.identifier
assert donor.animation_data.action.name == 'Donor a000_003000_Sekiro'

# The target keeps the scene as a single import leaves it.
assert (scene.frame_start, scene.frame_end, scene.render.fps / scene.render.fps_base) == (1, 24, 30)
assert scene['sekiro_bridge_export_rig'] == target and scene['sekiro_bridge_active_rig'] == 'c0000'
assert scene['sekiro_bridge_source_text'] == 'Sekiro Source - a000_003000.json'
assert scene['sekiro_bridge_retarget_source'] == donor
assert bpy.context.view_layer.objects.active == target and target.select_get() and not donor.select_get()

# The donor stands beside the target through delta transforms; its keys are untouched.
donor_root = root_motion_object(donor)
offset = donor.delta_location.x
assert offset > 0 and tuple(donor.delta_location) == tuple(donor_root.delta_location) == (offset, 0, 0)
scene.frame_set(40)
assert donor.location.length == 0 and (donor_root.location - Vector((.78, 1.17, 0))).length < 1e-6, donor_root.location
assert (donor_root.matrix_world.translation - Vector((.78 + offset, 1.17, 0))).length < 1e-5
scene.frame_set(1)
low, high = character_span(target)
donor_low, donor_high = character_span(donor)
assert donor_low > high + .4, (high, donor_low)

# Exporting the target gives what a single-character import gives.
export_motion(temp / 'pair.json')
assert json.loads((temp / 'pair.json').read_text()) == json.loads((temp / 'single.json').read_text()), 'The donor changed the target export'
pair_actions = [action['name'] for action in inspect_scene(temp / 'pair-scene.json')['actions']]
assert pair_actions == single_actions, (pair_actions, single_actions)

# Rig only: without meshes the donor clears the target's bones.
bpy.ops.wm.read_factory_settings(use_empty=True)
bare = import_motion(target_motion)
bare_donor = import_donor(donor_motion, bare)
assert bare_donor.name == 'Donor c0000' and character_span(bare_donor)[0] > character_span(bare)[1]
assert bpy.context.view_layer.objects.active == bare and bpy.context.scene['sekiro_bridge_export_rig'] == bare

# The add-on fills the pair when the file opens, and leaves a pair the user chose alone.
bpy.ops.wm.read_factory_settings(use_empty=True)
target = import_target()
import_donor(donor_motion, target, donor_manifest)
blend = temp / 'pair.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
sekiro_retarget.register()


def open_pair():
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    return bpy.context.scene, bpy.data.objects['c0000'], bpy.data.objects['Donor c0000']


scene, target, donor = open_pair()
settings = scene.sekiro_retarget
assert (settings.source, settings.target) == (donor, target), (settings.source, settings.target)
assert 'bridge import' in settings.status, settings.status
settings.source = None
assert not imported_pair.fill(scene) and settings.source is None and settings.target == target
settings.target = None
assert imported_pair.fill(scene) and (settings.source, settings.target) == (donor, target)


def bake(offset=None):
    """Bake the imported pair from the saved file, with the donor moved when an offset is given."""
    scene, target, donor = open_pair()
    if offset is not None:
        for obj in (donor, root_motion_object(donor)):
            obj.delta_location = (offset, 0, 0)
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}
    report = json.loads(scene['sekiro_retarget_report'])
    root, samples = root_motion_object(target), []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        samples.append([value for bone in target.pose.bones for row in bone.matrix_basis for value in row] +
                       [*root.location, *root.rotation_euler])
    return scene, report, np.array(samples)


scene, report, placed = bake()
assert (scene.frame_start, scene.frame_end, scene.render.fps / scene.render.fps_base) == (1, 40, 60), (scene.frame_end, scene.render.fps)
assert scene['sekiro_bridge_export_rig'].name == 'c0000' and np.ptp(placed, axis=0).max() > .1
for moved in (0.0, -3.0):
    other_scene, other_report, samples = bake(moved)
    assert (other_report['frames'], other_report['mapped']) == (report['frames'], report['mapped'])
    assert abs(other_report['scale'] - report['scale']) < 1e-9 and np.abs(samples - placed).max() < 1e-5, np.abs(samples - placed).max()
export_motion(temp / 'baked.json')
assert json.loads((temp / 'baked.json').read_text())['frameCount'] == 40
sekiro_retarget.unregister()
print(f'Two-character check passed: donor {offset:.2f} m beside the target, {report["mapped"]} mapped bones, {report["frames"]} baked frames')
