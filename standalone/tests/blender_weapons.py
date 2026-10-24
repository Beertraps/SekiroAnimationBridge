"""Blender integration on owned triangles, independent of game assets.

Run Blender --background --factory-startup --python THIS -- OUTPUT_DIRECTORY
"""
import sys,json,tempfile
from pathlib import Path
import bpy,numpy as np
from mathutils import Matrix,Vector,Euler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from blender_character import import_character
from weapon_assets import bone_worlds
from types import SimpleNamespace as S

out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True,exist_ok=True)
rig=bpy.data.objects.new('Owned character',bpy.data.armatures.new('Owned skeleton'));bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(('RightSocket','HipSocket')):
    b=rig.data.edit_bones.new(name);b.length=.1;b.matrix=Matrix.Translation((i,.5,1))
bpy.ops.object.mode_set(mode='POSE')
for frame in (1,2,3):
    for i,b in enumerate(rig.pose.bones):
        b.rotation_mode='XYZ';b.location=(frame*.15,i*.1,frame*.08);b.rotation_euler=(.1*frame,.2*frame,.3*frame)
        b.keyframe_insert('location',frame=frame);b.keyframe_insert('rotation_euler',frame=frame)
bpy.ops.object.mode_set(mode='OBJECT');rig.location=(2,3,4);rig.rotation_euler=(.1,.2,.3)
scene=bpy.context.scene;scene.frame_end=3
positions=np.array([[0,0,0],[.1,0,0],[0,.25,0]],np.float32)
models=[];offset=Matrix.Translation((.12,-.04,.03))@Euler((.1,-.2,.3),'XYZ').to_matrix().to_4x4()
for i,bone_name in enumerate(('RightSocket','HipSocket')):
    file=out/f'owned-{i}.npz'
    np.savez_compressed(file,positions=positions,faces=np.array([[0,1,2]],np.int32),
        bone_indices=np.zeros((3,4),np.int32),bone_weights=np.tile([1.,0,0,0],(3,1)),
        bone_names=np.array(['Blade00']),bone_parents=np.array([-1]),bone_translations=np.array([[0,-.3,0]]),
        bone_rotations=np.array([[.2,.3,.4]]),bone_scales=np.ones((1,3)),uv_0=np.zeros((3,2)),
        normals=np.tile([0,0,1],(3,1)),face_materials=np.array([0]))
    models.append(dict(name=f'wp_owned_{i}',source='Owned fixture',data=str(file),stats={},materials=[dict(name='Owned material')],
                       attachment=dict(bone=bone_name,dummy=20+i,matrix=[list(r) for r in offset])))
manifest=out/'owned-character.json';manifest.write_text(json.dumps(dict(models=models,texture_count=0,warnings=[])),encoding='utf-8')
objects=import_character(manifest,rig)
assert len(rig.data.bones)==2,'Weapon bones leaked into the export skeleton'
assert len({o.modifiers[0].object for o in objects})==2,'Different weapons share their local skeleton'
errors=[];samples=[]
for frame in (1,2,3):
    scene.frame_set(frame);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get()
    for i,obj in enumerate(objects):
        e=obj.evaluated_get(deps);mesh=e.to_mesh()
        expected=rig.matrix_world@rig.pose.bones[models[i]['attachment']['bone']].matrix@offset
        points=[obj.matrix_world@v.co for v in mesh.vertices]
        errors += [(p-(expected@Vector(source[[0,2,1]]))).length for p,source in zip(points,positions)]
        if i==0:samples.append(points[0].copy())
        e.to_mesh_clear()
assert max(errors)<2e-5,errors
assert (samples[0]-samples[-1]).length>.1,'Weapon did not follow the animated socket'
# The NumPy attachment math must match Blender's FLVER XZY rest transforms.
sample=S(name='Owned',parent_bone_index=-1,translate=(1,2,3),rotate=(.2,.3,.4),scale=(1,1,1))
expected=Matrix.LocRotScale(Vector(sample.translate),Euler(sample.rotate,'XZY').to_quaternion(),Vector(sample.scale))
np.testing.assert_allclose(bone_worlds([sample])[0],np.asarray(expected),atol=2e-7)
report=dict(frames=3,weapons=2,maximum_socket_error=max(errors),moved_distance=(samples[0]-samples[-1]).length,
            main_bones=len(rig.data.bones),local_rigs=2)
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('OWNED WEAPON CHECK '+json.dumps(report),flush=True)
