"""Run with Blender --background --factory-startup --python this_file.py."""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_character import setup_view

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
rig = bpy.data.objects.new('Preview rig', bpy.data.armatures.new('Preview rig'))
scene.collection.objects.link(rig)
mesh = bpy.data.meshes.new('Preview mesh')
mesh.from_pydata([(-0.5, 0, 0), (0.5, 0, 0), (0, 0, 2)], [], [(0, 1, 2)])
model = bpy.data.objects.new('Preview model', mesh)
model['sekiro_flver_preview'] = True
scene.collection.objects.link(model)

setup_view(rig)
lights = {obj.name: obj for obj in scene.objects if obj.type == 'LIGHT'}
assert set(lights) == {'Sekiro Preview Key', 'Sekiro Preview Fill', 'Sekiro Preview Rim'}
assert all(obj.data.type == 'AREA' and obj.data.energy > 0 for obj in lights.values())
assert all(area.spaces.active.shading.use_scene_lights and area.spaces.active.shading.use_scene_world
           for screen in bpy.data.screens for area in screen.areas if area.type == 'VIEW_3D')
old_location = lights['Sekiro Preview Key'].location.copy()
model.location.x = 3
setup_view(rig)
assert len([obj for obj in scene.objects if obj.type == 'LIGHT']) == 3
assert (lights['Sekiro Preview Key'].location - old_location - Vector((3, 0, 0))).length < 1e-5
print('PASS: preview lights and Material Preview shading follow the imported models', flush=True)
