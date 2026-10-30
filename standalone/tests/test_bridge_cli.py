"""The JSON command line: one document per command, catalogs by path, and requests as the UI sends them."""
import io,json,sys,tempfile,unittest
from contextlib import redirect_stderr,redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asset_discovery
import bridge_cli
from asset_discovery import discover
from test_sources import game_tree

# Stands in for bridge_runtime.py: prints the lines and events the request names, then exits with its code.
RUNTIME='''import json,sys
request=json.loads(open(sys.argv[2],encoding='utf-8').read())
for line in request.get('lines',[]):print(line,flush=True)
for stage,message,progress,*extra in request.get('events',[]):
    print('BRIDGE_EVENT '+json.dumps(dict(stage=stage,message=message,progress=progress,**(extra[0] if extra else {}))),flush=True)
sys.exit(request.get('exit',0))
'''
SETTINGS=dict(blender='blender.exe',decoder='SekiroMotionDecoder.exe',oodle='',writer=sys.executable)


def call(*argv):
    """Run the command line in-process: (exit code, its JSON result, its stderr)."""
    out,err=io.StringIO(),io.StringIO()
    with redirect_stdout(out),redirect_stderr(err):code=bridge_cli.main([str(a) for a in argv])
    return code,json.loads(out.getvalue()),err.getvalue()


class Jobs(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        (Path(temp.name)/'bridge_runtime.py').write_text(RUNTIME,encoding='utf-8')
        patch=mock.patch.object(bridge_cli,'HERE',Path(temp.name));patch.start();self.addCleanup(patch.stop)
    def run_job(self,**request):
        err=io.StringIO()
        with redirect_stderr(err):result=bridge_cli.run_job(request)
        return result,err.getvalue()
    def test_done_event_is_the_result_and_the_log_goes_to_stderr(self):
        result,log=self.run_job(lines=['Decoding c5060','NOTICE: No base-color image.','NOTICE: No base-color image.'],
                                events=[('decode','Decoding animation',15),('done','Blender scene ready',100,dict(output='x.blend',report=dict(frames=3)))])
        self.assertEqual(result,dict(output='x.blend',report=dict(frames=3),notices=['No base-color image.']))
        self.assertIn('Decoding c5060',log);self.assertIn('[decode 15%] Decoding animation',log)
    def test_error_event_is_the_failure(self):
        with self.assertRaisesRegex(bridge_cli.Failure,'Choose an existing folder'):
            self.run_job(events=[('error','Choose an existing folder.',0)],exit=1)
    def test_a_run_without_done_fails(self):
        with self.assertRaisesRegex(bridge_cli.Failure,'stopped with exit code 0'):
            self.run_job(events=[('decode','Decoding animation',15)])


class Commands(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve();self.cache=self.base/'cache'
        for target,name,value in ((bridge_cli,'CACHE',self.cache),(bridge_cli,'tools',lambda args:(dict(SETTINGS),{})),
                                  (asset_discovery,'configure_oodle',lambda *args:None)):
            patch=mock.patch.object(target,name,value);patch.start();self.addCleanup(patch.stop)
        patch=mock.patch('dotnet_runtime.configure');patch.start();self.addCleanup(patch.stop)
        self.path,self.catalog=discover(game_tree(self.base/'Sekiro'),self.cache,layout='game')
        self.jobs=[]
    def inventory(self,*characters):
        """Mark characters as read, each with one clip a000_003011, as inventory leaves the catalog."""
        catalog=json.loads(self.path.read_text(encoding='utf-8'))
        for entry in catalog['characters']:
            if entry['id'] in characters:
                entry.update(inventoried=True,count=1,ready=1,errors=[])
                catalog['clips'].append(dict(id=entry['id']+':0',name='a000_003011',character=entry['id'],characterKey=entry['id'],
                                             game='sekiro',scope='game',ready=True,issues=[],path='anim.hkx',skeleton='skeleton.hkx',
                                             compendium='',skeletonCompendium='',archive=entry['archives'][0],member='a000_003011.hkx'))
        self.path.write_text(json.dumps(catalog),encoding='utf-8')
    def job(self,request):
        self.jobs.append(request)
        if request['mode']=='inventory':self.inventory(request['assetCharacter'])
        return dict(output=str(self.path) if request['mode']=='discover' else 'done',report=dict(frames=3),notices=[])
    def call(self,*argv):
        with mock.patch.object(bridge_cli,'run_job',self.job):return call(*argv)
    def test_failure_is_one_json_document(self):
        code,result,_=self.call('clips',self.base/'nowhere.json')
        self.assertEqual((code,result['ok']),(1,False))
        self.assertIn('Scan the source first',result['error'])
    def test_scan_and_detect_pass_a_package_its_source_options(self):
        code,result,_=self.call('scan',self.base/'Sekiro','--option','engineVersion=GAME_UE4_27','--option','aesKey=0x1=2')
        self.assertEqual((code,result['catalog'],[c['id'] for c in result['characters']]),(0,str(self.path),['c0000','c5060']))
        self.assertEqual((self.jobs[-1]['mode'],self.jobs[-1]['sourceOptions']),('discover',dict(engineVersion='GAME_UE4_27',aesKey='0x1=2')))
        with mock.patch.object(asset_discovery,'detect_source',lambda *args:dict(options=args[-1])):
            result=self.call('detect',self.base/'Sekiro','--option','engineVersion=GAME_UE4_27')[1]
        self.assertEqual(result['options'],dict(engineVersion='GAME_UE4_27'))
    def test_catalog_outside_the_cache_is_refused(self):
        copy=self.base/'copy.json';copy.write_text(self.path.read_text(encoding='utf-8'),encoding='utf-8')
        self.assertFalse(self.call('clips',copy)[1]['ok'])
    def test_clips_read_a_character_once(self):
        code,result,_=self.call('clips',self.path,'--character','C5060','--match','3011')
        self.assertEqual((code,result['character'],result['total']),(0,'c5060',1))
        self.assertEqual(result['clips'][0]['id'],'c5060:0')
        request=self.jobs[0]
        self.assertEqual((request['mode'],request['assetCharacter'],request['assetFolder'],request['assetCatalog']),
                         ('inventory','c5060',self.catalog['folder'],str(self.path)))
        self.call('clips',self.path,'--character','c5060')
        self.assertEqual(len(self.jobs),1,'A character already read is not read again')
    def test_clips_without_a_character_list_the_characters(self):
        result=self.call('clips',self.path)[1]
        self.assertEqual((result['total'],[c['id'] for c in result['characters']]),(0,['c0000','c5060']))
        self.assertFalse(result['characters'][1]['inventoried'])
    def test_unknown_character_names_the_ones_there_are(self):
        result=self.call('clips',self.path,'--character','c9999')[1]
        self.assertIn('Its characters: c0000, c5060',result['error'])
    def test_a_repeated_clip_name_needs_its_character(self):
        self.inventory('c0000','c5060')
        result=self.call('select',self.path,'a000_003011')[1]
        self.assertIn('2 clips are named a000_003011',result['error'])
        result=self.call('select',self.path,'a000_003011','--character','c5060')[1]
        self.assertEqual((result['clip'],result['selection']['character']),('c5060:0','c5060'))
        self.assertEqual([p['id'] for p in result['selection']['parts'] if p['selected']],['c5060'])
    def test_import_sends_the_request_the_ui_sends(self):
        self.inventory('c0000','c5060')
        model=self.base/'Sekiro'/'chr'/'c5060.chrbnd.dcx'
        code,result,_=self.call('import',self.path,'a000_003011','--character','c5060','--output',self.base/'owl.blend',
                                '--mask',f'{model}=1, 2','--donor-clip','c0000:0','--rig-only')
        self.assertEqual((code,result['scene'],result['report']),(0,'done',dict(frames=3)))
        request=self.jobs[-1]
        expected=dict(mode='import',inputMethod='folder',game='auto',assetFolder=self.catalog['folder'],assetCatalog=str(self.path),
                      assetClip='c5060:0',assetCharacter='c5060',sourceLayout='game',includeCharacter=False,models=[],
                      outputBlend=str(self.base/'owl.blend'),modelMasks={str(model):['1','2']},partAnimations=True,force=False,**SETTINGS)
        self.assertEqual({k:request[k] for k in expected},expected)
        self.assertEqual((request['donor']['assetClip'],request['donor']['assetCatalog'],request['donor']['includeCharacter']),
                         ('c0000:0',str(self.path),True))
    def test_donor_options_need_a_donor_clip(self):
        self.inventory('c5060')
        code,result,_=self.call('import',self.path,'c5060:0','--output',self.base/'owl.blend','--donor-character','c0000')
        self.assertEqual(code,1);self.assertIn('--donor-clip',result['error'])
        self.assertEqual(self.jobs,[])
    def test_export_passes_only_the_options_given(self):
        self.call('export',self.base/'owl.blend','--output',self.base/'owl.hkx','--frame-start','3','--binder',self.base/'c5060.anibnd.dcx')
        request=self.jobs[-1]
        self.assertEqual((request['mode'],request['frameStart'],request['exportGame'],request['verify'],request['addToBinder']),
                         ('export',3.0,'auto',True,True))
        self.assertNotIn('frameEnd',request)
        self.assertEqual(request['binder'],str(self.base/'c5060.anibnd.dcx'))
    def test_verify_never_needs_an_output_but_takes_a_picture(self):
        self.call('verify',self.base/'owl.blend','--render',self.base/'owl.png','--frames','5')
        request=self.jobs[-1]
        self.assertEqual((request['mode'],request['inputBlend'],request['render'],request['frames']),
                         ('verify',str(self.base/'owl.blend'),str(self.base/'owl.png'),5))
    def test_run_fills_in_the_tools(self):
        file=self.base/'request.json';file.write_text(json.dumps(dict(mode='inspect',inputBlend='owl.blend',blender='')),encoding='utf-8')
        self.call('run',file)
        self.assertEqual((self.jobs[-1]['blender'],self.jobs[-1]['inputBlend']),('blender.exe','owl.blend'))
        self.assertFalse(self.call('run','{"inputBlend": "owl.blend"}')[1]['ok'])


class Options(unittest.TestCase):
    def test_masks_name_resolved_models(self):
        chosen=bridge_cli.masks(['a.flver=1, 2','b.chrbnd.dcx='])
        self.assertEqual(chosen,{str(Path('a.flver').resolve()):['1','2'],str(Path('b.chrbnd.dcx').resolve()):[]})
        with self.assertRaises(bridge_cli.Failure):bridge_cli.masks(['a.flver'])
    def test_source_options_resolve_the_files_they_name(self):
        with tempfile.TemporaryDirectory() as temp:
            mappings=Path(temp)/'game.usmap';mappings.write_text('',encoding='utf-8')
            chosen=bridge_cli.source_options(['aesKey=0x00','mappings='+str(mappings),'oodle='])
            self.assertEqual(chosen,dict(aesKey='0x00',mappings=str(mappings.resolve()),oodle=''))
        with self.assertRaises(bridge_cli.Failure):bridge_cli.source_options(['GAME_UE4_27'])
    def test_json_option_reads_text_or_a_file(self):
        self.assertEqual(bridge_cli.json_option('{"animations": ["anims"]}','--folders'),dict(animations=['anims']))
        with self.assertRaisesRegex(bridge_cli.Failure,'--folders'):bridge_cli.json_option('anims','--folders')


if __name__=='__main__':
    unittest.main()
