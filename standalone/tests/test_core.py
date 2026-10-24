"""Owned synthetic fixtures only; integration evidence is recorded separately."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flver_geometry import influences, extract_model
from character_assets import scan_character, sampler_priority, material_uses_alpha
from bridge_runtime import output_file, sampling_arguments, writer_arguments


class Stream:
    def __init__(self,array): self.array=array
    def __len__(self): return len(self.array)


def fixture():
    position=np.zeros(3,dtype=[('position','f4',(3,)),('normal','f4',(3,))])
    position['position']=[[0,0,0],[1,0,0],[0,1,0]]
    position['normal']=[0,0,1]
    skin=np.zeros(3,dtype=[('bone_indices','i4',(4,)),('bone_weights','f4',(4,)),('uv_0','f4',(2,)),('uv_1','f4',(2,))])
    skin['bone_indices']=[[0,1,255,-1]]*3;skin['bone_weights']=[[.75,.25,0,0]]*3
    skin['uv_1']=[[.1,.2],[.3,.4],[.5,.6]]
    mesh=S(vertex_arrays=[Stream(position),Stream(skin)],bone_indices=np.array([1,3]),default_bone_index=1,
           material=S(name='Owned triangle'),triangulate_flver2=lambda:np.array([[0,1,2]]))
    bones=[S(name=f'Bone {i}',parent_bone_index=i-1,translate=(0,0,0),rotate=(0,0,0),scale=(1,1,1)) for i in range(4)]
    return S(bones=bones,meshes=[mesh],version=S(is_flver0=lambda:False))


class Geometry(unittest.TestCase):
    def test_split_streams_and_unused_sentinels(self):
        f=fixture()
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'preview.npz';extract_model(f,target,'Owned fixture')
            with np.load(target,allow_pickle=False) as a:
                np.testing.assert_array_equal(a['bone_indices'][0],[1,3,0,0])
                np.testing.assert_allclose(a['bone_weights'][0],[.75,.25,0,0])
                np.testing.assert_allclose(a['uv_1'][2],[.5,.6])
                self.assertEqual(a['faces'].tolist(),[[0,1,2]])
    def test_active_invalid_weight_is_rejected(self):
        f=fixture();f.meshes[0].vertex_arrays[1].array['bone_indices'][0,0]=255
        with self.assertRaises(ValueError): influences(f.meshes[0],4,3)
    def test_skeleton_only_is_explained(self):
        f=fixture();f.meshes=[]
        with self.assertRaisesRegex(ValueError,'skeleton reference'):extract_model(f,Path('unused.npz'))


class Discovery(unittest.TestCase):
    def test_fur_alpha_test_does_not_require_alpha_blend_mode(self):
        self.assertTrue(material_uses_alpha({'g_BlendMode':0,'g_AlphaRef':[128,70]},'owned_fur.mtd'))
        self.assertFalse(material_uses_alpha({'g_BlendMode':0,'g_AlphaRef':[0,0]},'owned_skin.mtd'))
        self.assertTrue(material_uses_alpha({'g_AlphaRef':70},'owned_cutout.mtd'))
    def test_npc_folder_selects_one_model_without_wolf_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'c5060.flver').touch()
            for preset in ('auto','npc'):
                result=scan_character(root,preset)
                self.assertFalse(result['missing'])
                self.assertEqual(result['characterType'],'npc')
                self.assertEqual(result['parts'][0]['role'],'Character')
                self.assertTrue(result['parts'][0]['selected'])
    def test_npc_variants_require_an_explicit_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('c5060.flver','c5061.chrbnd.dcx'):(root/name).touch()
            result=scan_character(root,'npc')
            self.assertFalse(result['missing'])
            self.assertFalse(any(p['selected'] for p in result['parts']))
    def test_auto_detect_keeps_wolf_outfit_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('fc_m_0200','am_m_9000','bd_m_9000','lg_m_9000'):(root/(name+'.partsbnd.dcx')).touch()
            result=scan_character(root,'auto')
            self.assertEqual(result['characterType'],'wolf')
            self.assertFalse(result['missing'])
            self.assertEqual(sum(p['selected'] for p in result['parts']),4)
    def test_base_surface_precedes_damage_overlay(self):
        damage=S(texture_type='Shader_Texture2D_7_AlbedoMap')
        base=S(texture_type='Shader_Texture2D_2_AlbedoMap_0')
        self.assertIs(sorted([damage,base],key=sampler_priority)[0],base)
    def test_preset_selects_one_body_per_role_and_prefers_binder(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['fc_m_0200.flver','am_m_9000.flver','bd_m_9000.flver','lg_m_9000.flver',
                         'am_m_9010.partsbnd.dcx','bd_m_9030.partsbnd.dcx','bd_m_9000.partsbnd.dcx','bd_m_9000_l.partsbnd.dcx','c0000.flver']:
                (root/name).touch()
            result=scan_character(root,'tutorial')
            selected=[p for p in result['parts'] if p['selected']]
            self.assertEqual(len(selected),4);self.assertFalse(result['missing'])
            self.assertIn('am_m_9010',{p['id'] for p in selected})
            bd=next(p for p in result['parts'] if p['id']=='bd_m_9000')
            self.assertTrue(bd['path'].endswith('.partsbnd.dcx'))
            self.assertNotIn('c0000',{p['id'] for p in result['parts']})
    def test_existing_output_requires_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scene.blend';path.write_bytes(b'owned original')
            with self.assertRaisesRegex(ValueError,'already exists'):output_file(path,'.blend',False)
            self.assertEqual(path.read_bytes(),b'owned original')


class ExportRequest(unittest.TestCase):
    def test_defaults_keep_scene_range_tracks_and_root_empty(self):
        self.assertEqual(sampling_arguments({}),['--frame-range','scene','--tracks','original','--root-motion','auto'])
        self.assertEqual(writer_arguments({},'interleaved','stats.json'),
                         ['--format','interleaved','--game','auto','--stats-json','stats.json','--verify'])
    def test_options_reach_blender_and_writer(self):
        args=sampling_arguments(dict(frameRange='custom',frameStart='5',frameEnd=40,frameRate='60',exportAction=' Take 2 ',
                                     trackSet='keyed',rootMotion='bone',rootBone='Pelvis',rootVertical=True,rootYaw=True))
        self.assertEqual(args,['--frame-range','custom','--frame-start','5','--frame-end','40','--frame-rate','60',
                               '--action','Take 2','--tracks','keyed','--root-motion','bone','--root-bone','Pelvis',
                               '--root-axes','xyz','--root-yaw'])
        args=writer_arguments(dict(quantization='threecomp48',tolerance='0.0005',verify=False,exportGame='ds3'),'spline','s.json')
        self.assertEqual(args,['--format','spline','--game','ds3','--stats-json','s.json','--quantization','threecomp48','--tolerance','0.0005'])
    def test_invalid_options_are_rejected_before_blender_starts(self):
        for request,message in ((dict(frameRange='custom',frameStart=10,frameEnd=10),'end frame'),(dict(frameRate='500'),'frame rate'),
                                (dict(trackSet='bones'),'Track set'),(dict(rootMotion='mixamo'),'Root motion'),(dict(frameRate='fast'),'number')):
            with self.subTest(request=request),self.assertRaisesRegex(ValueError,message):sampling_arguments(request)
        with self.assertRaisesRegex(ValueError,'quantization'):writer_arguments(dict(quantization='polar32'),'spline','s.json')
        with self.assertRaisesRegex(ValueError,'tolerance'):writer_arguments(dict(tolerance='2'),'spline','s.json')


if __name__=='__main__': unittest.main()
