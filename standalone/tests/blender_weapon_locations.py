"""Weapon models that the character's TAE moves between dummies (event 715), on an owned rig.

Model 0 sits on the forearm's dummy and is hidden while the tool is out; model 1
has no dummy of its own, so it is hidden except while the event puts it in the
hand. The rig must follow the hand while the hand moves, keep each change on its
frame at the scene's rate, survive saving and opening the scene, and stay below
the character so that the part export still finds it.

Run Blender --background --factory-startup --python THIS -- OUTPUT_DIRECTORY
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_character import import_character  # noqa: E402

out = Path(sys.argv[sys.argv.index('--') + 1]); out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.render.fps, scene.render.fps_base = 60, 1.0

rig = bpy.data.objects.new('Owned character', bpy.data.armatures.new('Owned skeleton')); scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig; rig.select_set(True); bpy.ops.object.mode_set(mode='EDIT')
forearm = rig.data.edit_bones.new('L_Forearm'); forearm.length = .25; forearm.matrix = Matrix.Translation((.3, 0, 1.2))
hand = rig.data.edit_bones.new('L_Weapon'); hand.length = .1; hand.parent = forearm
hand.matrix = Matrix.Translation((.3, .25, 1.2)) @ Euler((0, 0, .4)).to_matrix().to_4x4()
bpy.ops.object.mode_set(mode='OBJECT')
rig['sekiro_animation_bridge'] = True
# The hand turns while the clip plays, so a weapon in it must follow the bone, not a frame baked at import.
pose = rig.pose.bones['L_Weapon']; pose.rotation_mode = 'XYZ'
for frame, angle in ((1, 0), (30, 1.2)):
    pose.rotation_euler = (angle, 0, 0); pose.keyframe_insert('rotation_euler', frame=frame)

data = out / 'owned-tool.npz'
np.savez_compressed(data, positions=np.array([[0, 0, 0], [0, .2, 0], [.05, 0, 0]], np.float32), faces=np.array([[0, 1, 2]], np.int32),
                    bone_indices=np.zeros((3, 4), np.int32), bone_weights=np.tile([1., 0, 0, 0], (3, 1)), bone_names=np.array(['W_Root']),
                    bone_parents=np.array([-1]), bone_translations=np.zeros((1, 3)), bone_rotations=np.zeros((1, 3)),
                    bone_scales=np.ones((1, 3)), uv_0=np.zeros((3, 2)), normals=np.tile([0, 0, 1], (3, 1)), face_materials=np.array([0]))
on_arm = Matrix.Translation((.02, 0, .01)) @ Euler((0, .3, 0)).to_matrix().to_4x4()
in_hand = Matrix.Translation((0, .03, 0)) @ Euler((.5, 0, 0)).to_matrix().to_4x4()
rows = lambda matrix: [list(row) for row in matrix]
# 0.05 s and 0.15 s are scene frames 4 and 10 at 60 fps.
models = [dict(name='wp_a_9990', changes=[[0.0, 118], [.05, -1], [.15, 118]], sockets={}),
          dict(name='wp_a_9990_1', changes=[[0.0, -1], [.05, 21], [.15, -1]],
               sockets={'21': dict(dummy=21, bone='L_Weapon', matrix=rows(in_hand))})]
manifest = out / 'owned-character.json'
manifest.write_text(json.dumps(dict(texture_count=0, warnings=[], models=[
    dict(name=m['name'], source='Owned fixture', data=str(data), stats={}, materials=[dict(name='Owned material')],
         attachment=dict(kind='dummy', bone='L_Forearm', dummy=118, matrix=rows(on_arm),
                         locations=dict(entry='a076_405010', changes=m['changes'], sockets=m['sockets']))) for m in models])),
    encoding='utf-8')
import_character(manifest, rig)


def check(label):
    weapons = {obj.get('sekiro_model_id'): obj for obj in scene.objects if obj.get('sekiro_weapon_preview')}
    worst = 0.0
    for frame in range(1, 14):
        scene.frame_set(frame); bpy.context.view_layer.update()
        for name, obj in weapons.items():
            changes = next(m['changes'] for m in models if m['name'] == name)
            dummy = [d for time, d in changes if 1 + time * 60 <= frame][-1]
            assert obj.hide_viewport == obj.hide_render == (dummy < 0), (label, name, frame, obj.hide_viewport, dummy)
            if dummy < 0:
                continue
            bone, offset = ('L_Forearm', on_arm) if dummy == 118 else ('L_Weapon', in_hand)
            want = rig.matrix_world @ rig.pose.bones[bone].matrix @ offset
            got = obj.parent.matrix_world
            worst = max(worst, max(abs(a - b) for row_a, row_b in zip(got, want) for a, b in zip(row_a, row_b)))
            assert obj.parent in rig.children_recursive, (label, name)
    assert worst < 1e-5, (label, worst)
    return worst


first = check('imported')
blend = out / 'owned-locations.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.open_mainfile(filepath=str(blend))
scene = bpy.context.scene
rig = bpy.data.objects['Owned character']
second = check('reopened')
report = dict(sceneRate=60, frames=13, changes={m['name']: m['changes'] for m in models}, maximum_error=first, maximum_reopened_error=second)
(out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('OWNED WEAPON LOCATION CHECK ' + json.dumps(report), flush=True)
