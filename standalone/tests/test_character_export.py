"""A new Sekiro character: Havok tagfiles patched in place, bones merged to fit a model, and the requests that start it."""
import io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge_ui
import character_export
import havok_tagfile as hk
from havok_tagfile import ARRAY,CLASS,FLOAT,INT,STRING


def packed(n):
    """Havok's variable-length integer, the inverse of havok_tagfile.packed_int."""
    if n<0x80:return bytes([n])
    if n<0x4000:return bytes([0x80|n>>8,n&0xFF])
    if n<0x200000:return bytes([0xC0|n>>16,n>>8&0xFF,n&0xFF])
    return (0xE0000000|n).to_bytes(4,'big')


def section(tag,body,leaf=True):
    return ((len(body)+8)|(0x40000000 if leaf else 0)).to_bytes(4,'big')+tag.encode('ascii')+body


class Types:
    """A TYPE section built from type definitions; add returns the one-based number items and fields use."""
    def __init__(self):self.types=[]
    def add(self,name,format_info,size,alignment,subtype=0,fields=()):
        self.types.append(dict(name=name,format=format_info,size=size,alignment=alignment,subtype=subtype,fields=fields))
        return len(self.types)
    def section(self):
        type_names=[t['name'] for t in self.types]
        field_names=sorted({f[0] for t in self.types for f in t['fields']})
        names=section('TST1',b''.join(n.encode()+b'\0' for n in type_names))
        table=section('TNA1',packed(len(self.types))+b''.join(packed(i)+packed(0) for i in range(len(self.types))))
        fields=section('FST1',b''.join(n.encode()+b'\0' for n in field_names))
        body=bytearray()
        for i,t in enumerate(self.types,1):
            flags=hk.HAS_FORMAT|hk.HAS_SIZE|(hk.HAS_SUBTYPE if t['subtype'] else 0)|(hk.HAS_FIELDS if t['fields'] else 0)
            body+=packed(i)+packed(0)+packed(flags)+packed(t['format'])
            if t['subtype']:body+=packed(t['subtype'])
            body+=packed(t['size'])+packed(t['alignment'])
            if t['fields']:
                body+=bytes([len(t['fields'])])
                for name,offset,field_type in t['fields']:body+=packed(field_names.index(name))+packed(0)+packed(offset)+packed(field_type)
        return section('TYPE',names+table+fields+section('TBDY',bytes(body)),leaf=False)


def int_format(bits):return INT|0x200|bits<<10


def tagfile(types,data,items,patches):
    """items: (type, offset, count) after the null item; patches: {slot type: [offsets]}."""
    rows=struct.pack('<3I',0,0,0)+b''.join(struct.pack('<3I',t|0x10<<24,o,c) for t,o,c in items)
    table=b''.join(struct.pack('<iI',t,len(o))+struct.pack(f'<{len(o)}I',*sorted(o)) for t,o in sorted(patches.items()))
    data=bytes(data)+bytes(-len(data)%4)
    body=section('SDKV',b'20160200')+types.section()+section('DATA',data)+section('INDX',section('ITEM',rows)+section('PTCH',table),leaf=False)
    return section('TAG0',body,leaf=False)


def behavior():
    """A modifier with a leg's bone numbers, a ragdoll bone number, a bone list, per-bone weights and a name."""
    t=Types()
    char=t.add('char',int_format(8),1,1);int16=t.add('hkInt16',int_format(16),2,2);real=t.add('hkReal',FLOAT,4,4)
    text=t.add('hkStringPtr',STRING,8,8,subtype=char)
    shorts=t.add('hkArray<hkInt16>',ARRAY,16,8,subtype=int16);reals=t.add('hkArray<hkReal>',ARRAY,16,8,subtype=real)
    leg=t.add('hkbFootIkDriverInfoLeg',CLASS,8,2,fields=(('kneeIndex',0,int16),('hipIndex',2,int16),('ragdollBoneIndex',4,int16)))
    root=t.add('hkbTestModifier',CLASS,48,8,fields=(('name',0,text),('leg',8,leg),('boneIndices',16,shorts),('boneWeights',32,reals)))
    data=bytearray(96)
    struct.pack_into('<I',data,0,2);struct.pack_into('<3h',data,8,3,1,2);struct.pack_into('<I',data,16,3);struct.pack_into('<I',data,32,4)
    data[48:59]=b'c1010_test\0';struct.pack_into('<3h',data,64,0,2,3);struct.pack_into('<4f',data,80,.1,.2,.3,.4)
    return tagfile(t,data,[(root,0,1),(char,48,11),(int16,64,3),(real,80,4)],{text:[0],shorts:[16],reals:[32]})


def skeleton_file(names=('Master','Root'),partitions=0):
    t=Types()
    char=t.add('char',int_format(8),1,1);int16=t.add('hkInt16',int_format(16),2,2)
    text=t.add('hkStringPtr',STRING,8,8,subtype=char)
    bone=t.add('hkaBone',CLASS,16,8,fields=(('name',0,text),))
    transform=t.add('hkQsTransform',CLASS,48,16)
    parents=t.add('hkArray<hkInt16>',ARRAY,16,8,subtype=int16);bones=t.add('hkArray<hkaBone>',ARRAY,16,8,subtype=bone)
    poses=t.add('hkArray<hkQsTransform>',ARRAY,16,8,subtype=transform)
    skeleton=t.add('hkaSkeleton',CLASS,72,8,fields=(('name',0,text),('parentIndices',8,parents),('bones',24,bones),
                                                     ('referencePose',40,poses),('partitions',56,parents)))
    data=bytearray(80)
    struct.pack_into('<I',data,0,2);struct.pack_into('<I',data,8,3);struct.pack_into('<I',data,24,4);struct.pack_into('<I',data,40,5)
    data+=b'c1010\0'+bytes(10)
    items=[(skeleton,0,1),(char,80,6),(int16,96,len(names)),(bone,112,len(names)),(transform,0,len(names))]
    data+=b''.join(struct.pack('<h',-1 if i==0 else i-1) for i in range(len(names)));data+=bytes(-len(data)%16)
    bone_at=len(data);items[3]=(bone,bone_at,len(names))
    for i in range(len(names)):data+=struct.pack('<I',6+i)+bytes(12)
    data+=bytes(-len(data)%16);items[4]=(transform,len(data),len(names))
    for i in range(len(names)):data+=struct.pack('<12f',0,i*.5,0,0,0,0,0,1,1,1,1,0)
    patches={text:[0]+[bone_at+16*i for i in range(len(names))],parents:[8],bones:[24],poses:[40]}
    for name in names:
        items.append((char,len(data),len(name)+1));data+=name.encode()+b'\0'
    if partitions:
        struct.pack_into('<I',data,56,len(items)+1);items.append((int16,len(data),partitions));data+=bytes(2*partitions)
        patches[parents].append(56)
    return tagfile(t,data,items,patches)


class Tagfiles(unittest.TestCase):
    def test_packed_integers_read_back(self):
        for n in (0,5,0x7F,0x80,0x3FFF,0x4000,0x1FFFFF,0x200000,0x7FFFFFF):
            self.assertEqual(hk.packed_int(packed(n)+b'\xff',0),(n,len(packed(n))))
    def test_an_unchanged_file_is_written_byte_for_byte(self):
        data=behavior();tag=hk.Tagfile(data)
        self.assertEqual(tag.write(),data)
        self.assertEqual(tag.unpatched(),([],[]))
        self.assertEqual(hk.Tagfile(skeleton_file()).write(),skeleton_file())
    def test_bone_fields_skip_ragdoll_bones_and_lists_of_other_lengths(self):
        found={f['field']:f for f in hk.bone_fields(hk.Tagfile(behavior()),4)}
        self.assertEqual({k:(f['kind'],f.get('value',f.get('values'))) for k,f in found.items() if k!='boneWeights'},
                         dict(kneeIndex=('index',3),hipIndex=('index',1),boneIndices=('indices',[0,2,3])))
        self.assertEqual(found['boneWeights']['kind'],'weights')
        self.assertNotIn('boneWeights',{f['field'] for f in hk.bone_fields(hk.Tagfile(behavior()),5)})
    def test_a_behavior_gets_new_bone_numbers_lists_and_names(self):
        old=behavior()
        new,changes=hk.edit_behavior(old,None,bone_map=[0,5,1,2],weight_source=[0,2,3,-1,-1,1],mirror=None,bone_count=6,
                                     renames=[('c1010','c1800')])
        tag=hk.Tagfile(new);found={f['field']:f for f in hk.bone_fields(tag,6)}
        self.assertEqual((found['hipIndex']['value'],found['kneeIndex']['value'],found['boneIndices']['values']),(5,2,[0,1,2]))
        np.testing.assert_allclose(found['boneWeights']['values'],[.1,.3,.4,0,0,.2],rtol=1e-6)
        self.assertEqual(struct.unpack_from('<h',tag.data,tag.base+12)[0],2,'the ragdoll bone keeps its number')
        self.assertEqual([text for _,text in hk.strings(tag)],['c1800_test'])
        self.assertEqual(tag.unpatched(),([],[]))
        self.assertEqual(sorted((c['kind'],c['field']) for c in changes),
                         [('index','boneIndices'),('index','boneIndices'),('index','hipIndex'),('index','kneeIndex'),
                          ('string','name'),('weights','boneWeights')])
        # Only the patched values differ inside the template's data; the longer list follows it.
        self.assertEqual(tag.items[4].offset,96)
        differ=[i for i in range(96) if old[hk.Tagfile(old).base+i]!=tag.data[tag.base+i]]
        self.assertEqual(differ,[8,10,50,51,66,68])
    def test_renames_keep_the_length(self):
        with self.assertRaisesRegex(ValueError,'as many characters'):hk.edit_behavior(behavior(),None,[0,1,2,3],[0,1,2,3],None,4,[('c1010','c18000')])
    def test_a_skeleton_gets_new_bones_with_their_names_in_the_patch_table(self):
        bones=[dict(name=n,parent=p,translation=[0,i,0],rotation=[0,0,0,1],scale=[1,1,1])
               for i,(n,p) in enumerate((('Master',-1),('Root',0),('Spine',1)))]
        new=hk.write_skeleton(skeleton_file(),bones,renames=[('c1010','c1800')])
        found=hk.skeleton(new)
        self.assertEqual((found['name'],[b['name'] for b in found['bones']],[b['parent'] for b in found['bones']]),
                         ('c1800',['Master','Root','Spine'],[-1,0,1]))
        self.assertEqual([b['translation'] for b in found['bones']],[[0,0,0],[0,1,0],[0,2,0]])
        self.assertEqual(hk.Tagfile(new).unpatched(),([],[]))
    def test_a_skeleton_with_partitions_is_refused(self):
        self.assertEqual(hk.skeleton(skeleton_file(partitions=2))['partitions'],2)
        with self.assertRaisesRegex(ValueError,'partitions'):hk.write_skeleton(skeleton_file(partitions=2),[])
    def test_a_file_that_is_not_a_tagfile_is_refused(self):
        with self.assertRaisesRegex(ValueError,'TAG0'):hk.Tagfile(section('TCM0',b''))
    def test_a_clip_names_the_bones_its_tracks_move(self):
        def clip(indices,tracks):
            t=Types()
            int16=t.add('hkInt16',int_format(16),2,2);int32=t.add('hkInt32',int_format(32),4,4)
            shorts=t.add('hkArray<hkInt16>',ARRAY,16,8,subtype=int16)
            root=t.add('hkaTestClip',CLASS,24,8,fields=(('numberOfTransformTracks',0,int32),('transformTrackToBoneIndices',8,shorts)))
            data=bytearray(24);struct.pack_into('<i',data,0,tracks)
            items=[(root,0,1)]
            if indices:
                struct.pack_into('<I',data,8,2);items.append((int16,24,len(indices)))
                data+=b''.join(struct.pack('<h',i) for i in indices)
            return tagfile(t,data,items,{shorts:[8]} if indices else {})
        # c5000's idle moves 169 of its 223 bones, by a list; a clip without a list moves its first bones in order.
        self.assertEqual(hk.track_bones(clip([0,1,5,2],4)),[0,1,5,2])
        self.assertEqual(hk.track_bones(clip([],3)),[0,1,2])


class Bones(unittest.TestCase):
    def test_the_lightest_leaves_give_their_weights_to_their_parents(self):
        # 0 root, 1 spine, 2 head, 3 jaw (under head), 4 eye (under head), 5 unweighted finger under spine.
        parents=[-1,0,1,2,2,1]
        mesh=dict(bone_indices=np.array([[1,2],[3,4],[4,2]]),bone_weights=np.array([[.5,.5],[.1,.9],[.3,.7]]))
        target,merged=character_export.reduce_weighted_bones([mesh],parents,4)
        self.assertEqual((target.tolist(),merged),([0,1,2,2,4,5],[3]))
        target,merged=character_export.reduce_weighted_bones([mesh],parents,2)
        self.assertEqual((target.tolist(),merged),([0,1,1,1,1,5],[2,3,4]))
    def test_bones_that_fit_stay_apart(self):
        mesh=dict(bone_indices=np.array([[1,2]]),bone_weights=np.array([[.5,.5]]))
        target,merged=character_export.reduce_weighted_bones([mesh],[-1,0,1],256)
        self.assertEqual((target.tolist(),merged),([0,1,2],[]))
    def test_a_game_package_names_the_bones_of_its_rigs(self):
        # Eight frame bones the matcher skips, then a pelvis, legs and a spine; FromSoftware space, +X the left side.
        body=[('Pelvis',1,(0,1,0)),('L_Thigh',8,(.1,.95,0)),('L_Calf',9,(.1,.5,0)),('L_Foot',10,(.1,.08,0)),
              ('R_Thigh',8,(-.1,.95,0)),('R_Calf',12,(-.1,.5,0)),('R_Foot',13,(-.1,.08,0)),('Spine',8,(0,1.2,0))]
        template=[(f'frame{i}',i-1,(0,0,0)) for i in range(8)]+body
        def world(position):
            m=np.eye(4);m[:3,3]=position;return m
        bones=[dict(name=n,parent=p) for n,p,_ in template]
        german={'Pelvis':'Becken','Spine':'Ruecken'}
        source=[(german.get(n,n.replace('Thigh','Oberschenkel').replace('Calf','Wade').replace('Foot','Fuss')),p-8 if p>=8 else -1,world(t))
                for n,p,t in body]
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'games.json').write_text(json.dumps(dict(games=[dict(id='testgame',bones=dict(
                names={'Becken':'Pelvis','Ruecken':'Spine'},patterns=[dict(match='([LR])_Oberschenkel',**{'as':r'\1_Thigh'}),
                dict(match='([LR])_Wade',**{'as':r'\1_Calf'}),dict(match='([LR])_Fuss',**{'as':r'\1_Foot'})]))])),encoding='utf-8')
            with mock.patch.object(character_export,'APP',Path(temp)):
                pair=lambda game:character_export.pair_bones(source,bones,[world(t) for _,_,t in template],
                                                            character_export.load_mapping(),game=game)[0]
                pairs,plain=pair('testgame'),pair('')
        self.assertEqual(pairs,{n:s for (n,_,_),(s,_,_) in zip(body,source)})
        # The legs pair by their sides and heights alone; only the package's names make Ruecken the spine.
        self.assertNotIn('Spine',plain)
    def test_mirror_names_and_ids(self):
        self.assertEqual([character_export.mirror_name(n) for n in ('L_Thigh','R_Hand','LeftEye','Spine')],
                         ['R_Thigh','L_Hand','RightEye','Spine'])
        with self.assertRaisesRegex(ValueError,'four digits'):character_export.check_ids('c1010','c180')
        with self.assertRaisesRegex(ValueError,'differs'):character_export.check_ids('c1010','c1010')
    def test_a_model_only_export_gives_extra_bones_to_their_skeleton_ancestor(self):
        # The skeleton: Master, Pelvis, Spine, R_Hand. The scene adds a weapon bone under R_Hand and a blade under it.
        skeleton=[dict(name=n) for n in ('Master','Pelvis','Spine','R_Hand')]
        manifest=dict(bones=[dict(name='Master',parent=-1),dict(name='Pelvis',parent=0),dict(name='Spine',parent=1),
                             dict(name='R_Hand',parent=2),dict(name='R_Weapon',parent=3),dict(name='Blade',parent=4)])
        target,gave=character_export.model_bones(manifest,skeleton,'c1010')
        self.assertEqual((target.tolist(),gave),([0,1,2,3,3,3],[4,5]))
        # The scene's bones may come in another order; they map by name.
        manifest['bones']=[dict(name='Pelvis',parent=-1),dict(name='Master',parent=-1),dict(name='R_Hand',parent=3),
                           dict(name='Spine',parent=0)]
        self.assertEqual(character_export.model_bones(manifest,skeleton,'c1010')[0].tolist(),[1,0,3,2])
    def test_weapon_bones_join_the_skeleton_after_its_last_bone(self):
        # The skeleton: Master, Pelvis, R_Hand. The scene: a hammer under a gun under R_Hand, listed before the gun; a
        # bone of the character's own model; an unweighted helper.
        skeleton=[dict(name=n,parent=p,translation=[0,i,0],rotation=[0,0,0,1],scale=[1,1,1])
                  for i,(n,p) in enumerate((('Master',-1),('Pelvis',0),('R_Hand',1)))]
        manifest=dict(bones=[dict(name='Master',parent=-1),dict(name='Pelvis',parent=0),dict(name='R_Hand',parent=1),
                             dict(name='Hammer',parent=5),dict(name='Sleeve',parent=1),dict(name='Gun',parent=2),
                             dict(name='Helper',parent=2)])
        mesh=dict(bone_indices=np.array([[3,1],[4,0],[2,6]]),bone_weights=np.array([[1.,0],[.5,.5],[1.,0]]))
        appended=character_export.scene_weapon_bones(manifest,skeleton,{'Sleeve'},[mesh])
        self.assertEqual(appended,[5,3],'the gun carries the weighted hammer and comes first')
        rest=[placed(0,0,0),placed(0,1,0),placed(0,2,0)]
        scene=rest+[placed(.5,2,0),placed(0,1,0),placed(.2,2,0),placed(0,2,0)]
        bones,worlds=character_export.appended_skeleton(skeleton,manifest,appended,rest,scene)
        self.assertEqual([(b['name'],b['parent']) for b in bones[3:]],[('Gun',2),('Hammer',3)])
        self.assertEqual(bones[:3],skeleton,"the skeleton's own bones keep their values")
        np.testing.assert_allclose(bones[3]['scale'],[.001]*3);np.testing.assert_allclose(bones[4]['scale'],[1]*3)
        np.testing.assert_allclose(bones[3]['translation'],[.2,0,0],atol=1e-9)
        np.testing.assert_allclose(bones[4]['translation'],[.3,0,0],atol=1e-9)
        self.assertEqual(len(worlds),5)
        self.assertEqual(character_export.nearest_of([b['parent'] for b in bones],3),[0,1,2,2,2])
        # The helper and the model's own bone still give their weights to a bone of the grown skeleton.
        target,gave=character_export.model_bones(manifest,bones,'c1010')
        self.assertEqual((target.tolist(),gave),([0,1,2,4,1,3,2],[4,6]))
    def test_a_model_only_export_needs_the_characters_skeleton(self):
        skeleton=[dict(name=f'b{i}') for i in range(10)]
        manifest=dict(bones=[dict(name=f'b{i}',parent=i-1) for i in range(8)])
        with self.assertRaisesRegex(ValueError,"8 of c1010's 10 bones"):
            character_export.model_bones(manifest,skeleton,'c1010')
        manifest['bones']+=[dict(name='b8',parent=7),dict(name='b9',parent=8),dict(name='Prop',parent=-1)]
        with self.assertRaisesRegex(ValueError,"Prop hangs below no bone of c1010's skeleton"):
            character_export.model_bones(manifest,skeleton,'c1010')
    def test_the_me3_profile_names_the_mod_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            profile=character_export.me3_profile(Path(temp)/'dante','dante')
            self.assertEqual((profile.name,'path = "dante"' in profile.read_text(encoding='utf-8')),('dante.me3',True))


class Meshes(unittest.TestCase):
    def test_triangles_wind_against_their_normals_as_sekiros_do(self):
        # Two triangles wound alike in Blender: material 0's normals follow the winding, as a DMC5 import's do;
        # material 1's point the other way, as a FromSoftware import's do.
        buffer=io.BytesIO()
        np.savez(buffer,positions=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[1,0,1],[0,1,1]],np.float32),loop_vertex=np.arange(6),
                 normals=np.array([[0,0,1]]*3+[[0,0,-1]]*3,np.float32),tangents=np.tile(np.float32([1,0,0,1]),(6,1)),
                 bone_indices=np.zeros((6,4),np.int64),bone_weights=np.tile(np.float32([1,0,0,0]),(6,1)),
                 triangles=np.array([[0,1,2],[3,4,5]]),triangle_materials=np.array([0,1]))
        buffer.seek(0)
        parts=character_export.mesh_parts(buffer,np.array([0]))
        self.assertEqual([p[0] for p in parts],[0,1])
        for material,floats,_,triangles in parts:
            a,b,c=(floats[triangles[:,k],0:3] for k in range(3))
            facing=np.einsum('ij,ij->i',np.cross(b-a,c-a),floats[triangles,3:6].sum(axis=1))
            self.assertTrue(np.all(facing<0),material)


class Textures(unittest.TestCase):
    def test_a_cutouts_mips_keep_the_texels_that_pass_the_alpha_test(self):
        # Alpha mostly below the test: averaging alone leaves almost no texel above it a few mips down.
        pixels=np.zeros((64,64,4),np.uint8);pixels[...,:3]=200
        pixels[...,3]=np.random.default_rng(1).integers(0,161,(64,64))
        passing=np.mean(pixels[...,3]>=128)
        levels=character_export.coverage_mips(pixels)
        self.assertEqual([l.shape[:2] for l in levels[:2]]+[levels[-1].shape[:2]],[(64,64),(32,32),(1,1)])
        for level in levels[1:4]:
            self.assertAlmostEqual(np.mean(level[...,3]>=128),passing,delta=0.03)
        self.assertEqual(struct.unpack_from('<I',character_export.dds_header(64,64,29,len(levels)),28)[0],7)

    def test_empty_texels_do_not_darken_a_cutouts_mips(self):
        pixels=np.zeros((64,64,4),np.uint8);pixels[:,::8,:3]=200;pixels[:,::8,3]=255
        self.assertTrue(np.all(character_export.coverage_mips(pixels)[3][...,:3]==200))


def placed(x,y,z):
    world=np.eye(4);world[:3,3]=(x,y,z)
    return world


class Ragdolls(unittest.TestCase):
    def test_a_turn_takes_one_direction_onto_the_other(self):
        for old,new in (([0,1,0],[1,0,0]),([0,0,2],[0,1,1]),([1,0,0],[-3,0,0]),([0,1,0],[0,2,0])):
            turn=character_export.turn_between(old,new)
            self.assertTrue(np.allclose(turn@np.array(old,float)/np.linalg.norm(old),np.array(new,float)/np.linalg.norm(new)),(old,new))
            self.assertTrue(np.allclose(turn@turn.T,np.eye(3)) and np.isclose(np.linalg.det(turn),1),(old,new))

    def test_ragdoll_bones_follow_their_drivers_and_turn_with_the_limb(self):
        # A template limb up the Y axis, and a new one along X twice as long. Ragdoll bones 0 and 1 rest on the
        # limb's bones; bone 2 has no driver and keeps its place on bone 1.
        template=[placed(0,0,0),placed(0,1,0)]
        new=[placed(0,0,0),placed(2,0,0)]
        rest=[placed(0,0,0),placed(0,1,0),placed(0,1.5,0)]
        rests=character_export.ragdoll_rest([-1,0,1],rest,{0:0,1:1},template,new,[0,1])
        self.assertTrue(np.allclose(rests[0][:3,:3]@[0,1,0],[1,0,0]),'the root turns onto the new limb')
        self.assertTrue(np.allclose(rests[1][:3,3],[2,0,0]),'the child moves to its driver')
        self.assertTrue(np.allclose(rests[1][:3,:3],rests[0][:3,:3]),'a bone without ragdoll children turns as its parent')
        self.assertTrue(np.allclose(rests[2][:3,3],[2.5,0,0]),'a bone without a driver keeps its place on its parent')

    def test_the_pwv_gets_one_row_per_new_bone(self):
        header=struct.pack('<I4h',1,0,2,3,2).ljust(32,b'\0')
        rows=[bytes([i])*8 for i in range(3)]
        data=header+b'\xff\xff\0\0'*2+b''.join(rows)+b'\x07'*32
        new=character_export.edit_pwv(data,[0,1,1,2])
        self.assertEqual(struct.unpack_from('<I4h',new,0),(1,0,2,4,2))
        self.assertEqual(new[40:72],rows[0]+rows[1]+rows[1]+rows[2])
        self.assertEqual((new[72:],len(new)),(b'\x07'*32,32+8+32+32))
        with self.assertRaises(ValueError):
            character_export.edit_pwv(data[:-1],[0,1,2])


class Requests(unittest.TestCase):
    def test_the_character_page_keeps_its_own_fields(self):
        request=dict(mode='character-export',writer='python.exe',blender='blender.exe',inputBlend='other.blend',frameStart='3',
                     characterBlend='dante.blend',characterFrameStart='',characterGameFolder='Sekiro',characterId='c1800',
                     characterTemplate='',characterMap='m11_00_00_00',characterParts=['c1010_0000'],characterOutput='mods/dante',
                     characterTextureSize='2048',force=True)
        self.assertEqual(bridge_ui.character_job(request),
                         dict(mode='character-export',writer='python.exe',blender='blender.exe',characterId='c1800',force=True,
                              inputBlend='dante.blend',gameFolder='Sekiro',map='m11_00_00_00',parts=['c1010_0000'],
                              outputFolder='mods/dante',textureSize='2048'))
        listing=bridge_ui.character_job(dict(request,mode='character-parts'))
        self.assertNotIn('parts',listing)
        self.assertTrue(bridge_ui.character_job(dict(request,mode='character-model',characterWeaponBones=True))['weaponBones'])


if __name__=='__main__':
    unittest.main()
