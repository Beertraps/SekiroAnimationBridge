"""Run with Blender --background --factory-startup --python this_file.py."""
import sys, tempfile, json, math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Quaternion,Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from blender_bridge import import_motion,export_motion,trs_matrix
from blender_character import skin_rig_for_part,ensure_model_bones

root=dict(index=0,name='Owned root',parent=-1,translation=[0,0,0],rotation=[0,math.sqrt(.5),0,math.sqrt(.5)],scale=[1,1,1])
child=dict(index=1,name='Owned child',parent=0,translation=[0,1,0],rotation=[0,0,0,1],scale=[1,1,1])
motion=dict(format='sekiro-animation-bridge',formatVersion=1,clip='owned.hkx',skeletonName='Owned',
    skeleton=dict(name='Owned',boneCount=2,bones=[root,child]),frameCount=2,frameRate=30,duration=1/30,
    trackCount=2,trackBoneIndices=[0,1],trackNames=['Owned root','Owned child'],rootMotion=[[0,0,0,0],[.1,0,0,.2]],
    frames=[[dict(translation=b['translation'],rotation=b['rotation'],scale=b['scale']) for b in [root,child]],
            [dict(translation=[.1,0,0],rotation=root['rotation'],scale=[1,1,1]),dict(translation=[0,1.1,0],rotation=child['rotation'],scale=[1,1,1])]])
bpy.ops.wm.read_factory_settings(use_empty=True)
rig=import_motion(motion)
expected=trs_matrix(root)
actual=rig.data.bones['Owned root'].matrix_local
assert max(abs(expected[r][c]-actual[r][c]) for r in range(4) for c in range(4))<1e-5,'Bone rest orientation was lost'
preview=dict(bone_names=np.asarray(['Owned root','Owned extra']),bone_parents=np.asarray([-1,0]),
    bone_translations=np.asarray([[0,0,0],[0,1,0]],dtype=float),bone_rotations=np.zeros((2,3)),bone_scales=np.ones((2,3)))
ensure_model_bones(rig,preview,{1})
assert 'Owned extra' in rig.data.bones
adapter=skin_rig_for_part(rig,preview,{0},rig.users_collection[0],'Owned fixture')
assert adapter!=rig,'The mismatched bind pose did not receive an adapter'
mesh=bpy.data.meshes.new('Owned triangle');mesh.from_pydata([(1,0,0),(0,0,0),(0,1,0)],[],[(0,1,2)])
obj=bpy.data.objects.new('Owned triangle',mesh);rig.users_collection[0].objects.link(obj)
group=obj.vertex_groups.new(name='Owned root');group.add([0,1,2],1,'REPLACE')
modifier=obj.modifiers.new('Owned skin','ARMATURE');modifier.object=adapter
for frame in (1,2):
    bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());geometry=evaluated.to_mesh()
    expected=rig.pose.bones['Owned root'].matrix@Vector((1,0,0))
    assert (geometry.vertices[0].co-expected).length<1e-5,'Bind adapter did not follow the edited animation rig'
    evaluated.to_mesh_clear()
with tempfile.TemporaryDirectory() as temp:
    output=Path(temp)/'owned.motion.json';export_motion(output);result=json.loads(output.read_text())
    for frame_a,frame_b in zip(motion['frames'],result['frames']):
        for a,b in zip(frame_a,frame_b):
            for field in ['translation','scale']:
                assert max(abs(x-y) for x,y in zip(a[field],b[field]))<1e-5,(field,a,b)
            qa=Quaternion((a['rotation'][3],*a['rotation'][:3]));qb=Quaternion((b['rotation'][3],*b['rotation'][:3]))
            assert abs(qa.dot(qb))>1-1e-5,'Rotation round trip failed'
    assert result['rootMotion'][1][0]>.099
print('PASS: owned rest orientation, sampled curves, embedded source, extra model bones, driven bind adapter and animation round trip',flush=True)
