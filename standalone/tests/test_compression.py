import sys,json,math,struct,subprocess,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from soulstruct.havok.fromsoft.sekiro.core import AnimationHKX
from soulstruct.havok.utilities.maths.trs_transform import TRSTransform
from hkx_compression import prepare_2010,compress_spline,QUANTIZATION
from build_animation import build,decoded_frames,compare
from havok_compat import pad_packfile_sections,readable
from game_profiles import GAMES

# Native PC packfile headers recorded on import.
SOURCE_HAVOK={'ds1':dict(container='packfile',pointerSize=4,littleEndian=True,reusePadding=0,flags=0),
              'ds3':dict(container='packfile',pointerSize=8,littleEndian=True,reusePadding=0,flags=0)}


def turning(i):
    # Owned motion: a slow turn about Y with a forward slide.
    angle=i*.08;return (0,math.sin(angle/2),0,math.cos(angle/2))


def packfile_objects(data):
    """Map class names to object offsets in a version 11 (DS3) packfile."""
    sections=[struct.unpack_from('<7I',data,80+i*64+20) for i in range(3)]
    names,base=sections[0][0],sections[2][0]
    result={}
    for pos in range(base+sections[2][3],base+sections[2][4]-11,12):
        offset,_,name=struct.unpack_from('<3I',data,pos)
        if offset!=0xFFFFFFFF: result[data[names+name:data.index(b'\0',names+name)].decode()]=base+offset
    return result


class Compression(unittest.TestCase):
    def fixture(self,count=4):
        frames=[[TRSTransform((i*.01,0,0),turning(i),(1,1,1)),TRSTransform((0,.5,0),(0,0,0,1),(1,1,1))] for i in range(count)]
        return AnimationHKX.from_minimal_data_interleaved(frames,[0,1],original_skeleton_name='Owned',frame_rate=30,track_names=['Owned root','Owned child'])
    def test_2010_header_does_not_contain_tagfile_version(self):
        data=prepare_2010(self.fixture()).to_bytes()
        self.assertEqual(data[40:54].rstrip(b'\0'),b'hk_2010.2.0-r1')
    @unittest.skipUnless(sys.platform=='win32','Bundled compressor is a Windows program')
    def test_owned_animation_compresses_to_spline(self):
        spline=compress_spline(self.fixture())
        self.assertTrue(spline.animation_container.is_spline)
        self.assertGreater(len(spline.to_bytes()),100)
    @unittest.skipUnless(sys.platform=='win32','Bundled compressor is a Windows program')
    def test_every_offered_quantization_reads_back(self):
        source=self.fixture(24);expected=decoded_frames(source)
        for name in QUANTIZATION:
            with self.subTest(quantization=name):
                spline=compress_spline(source,name,.0005)
                written=readable(AnimationHKX).from_bytes(spline.to_bytes())
                self.assertLess(compare(expected,decoded_frames(written),['root','child'])['maxRotationDegrees'],.5)
    def test_missing_visual_cpp_runtime_is_named(self):
        # Windows reports STATUS_DLL_NOT_FOUND when MSVCR100.dll (Visual C++ 2010, x86) is missing.
        missing=subprocess.CompletedProcess([],0xC0000135,'','')
        with mock.patch('hkx_compression.subprocess.run',return_value=missing):
            with self.assertRaisesRegex(RuntimeError,r'Visual C\+\+ 2010'):compress_spline(self.fixture())
    def test_invalid_spline_settings_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'quantization'):compress_spline(self.fixture(),'straight16')
        with self.assertRaisesRegex(ValueError,'tolerance'):compress_spline(self.fixture(),'threecomp40',1.0)


class Writer(unittest.TestCase):
    def motion(self,count=12,game='sekiro'):
        frames=[[dict(translation=[i*.01,0,0],rotation=list(turning(i)),scale=[1,1,1])] for i in range(count)]
        document=dict(format='sekiro-animation-bridge',formatVersion=1,game=game,frames=frames,trackBoneIndices=[0],
                      trackNames=['Owned root'],skeletonName='Owned',frameRate=30.0,
                      rootMotion=[[i*.02,0,0,i*.01] for i in range(count)])
        if game in SOURCE_HAVOK: document['sourceHavok']=SOURCE_HAVOK[game]
        return document
    def write(self,document,fmt,**options):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'motion.json';source.write_text(json.dumps(document),encoding='utf-8')
            output=Path(temp)/'out.hkx'
            stats=build(source,output,fmt,'auto',verify=True,**options)
            return stats,output.read_bytes()
    def test_every_game_reads_back_its_samples(self):
        for game in GAMES:
            with self.subTest(game=game):
                readback=self.write(self.motion(game=game),'interleaved')[0]['readback']
                self.assertLess(readback['maxRotationDegrees'],1e-3)
                self.assertLess(readback['maxTranslation'],1e-6)
                self.assertLess(readback['maxRootMotion'],1e-6)
    @unittest.skipUnless(sys.platform=='win32','Bundled compressor is a Windows program')
    def test_spline_readback_reports_quantization(self):
        for game in ('sekiro','ds3','er'):
            with self.subTest(game=game):
                stats=self.write(self.motion(game=game),'spline',quantization='threecomp48',tolerance=.0001)[0]
                self.assertEqual(stats['quantization'],'threecomp48')
                self.assertLess(stats['readback']['maxRotationDegrees'],.5)
    def test_single_frame_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'two frames'):self.write(self.motion(1),'interleaved')
    def test_ds3_sections_and_objects_match_pc_files(self):
        data=self.write(self.motion(game='ds3'),'interleaved')[1]
        # Each 48-byte section header is followed by 16 0xFF bytes, as in game files.
        for header in (80,144,208):self.assertEqual(data[header+48:header+64],b'\xff'*16)
        self.assertEqual(pad_packfile_sections(data),data)
        objects=packfile_objects(data)
        animation,frame=objects['hkaInterleavedUncompressedAnimation'],objects['hkaDefaultAnimatedReferenceFrame']
        # Base objects fill 16 bytes (no reused padding): type and duration follow at 16 and 20.
        padding,kind,duration=struct.unpack_from('<IIf',data,animation+12)
        self.assertEqual((padding,kind),(0,1));self.assertAlmostEqual(duration,11/30,places=6)
        self.assertEqual(struct.unpack_from('<4f4f',data,frame+32),(0,1,0,0,0,0,1,0))
    def test_er_property_flags_use_the_havok_type_name(self):
        data=self.write(self.motion(game='er'),'interleaved')[1]
        self.assertIn(b'\0hkFlags\0',data);self.assertNotIn(b'hkFlags[',data);self.assertNotIn(b'hkFlags_',data)


if __name__=='__main__': unittest.main()
