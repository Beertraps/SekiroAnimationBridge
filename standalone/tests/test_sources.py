import sys,json,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asset_discovery
import bridge_ui
from asset_sources import detect,leading_id,kind_files,count_custom,resolve_folders
from asset_discovery import discover,index_source,selection,signature
from character_assets import PRESETS

# Owned stand-ins: empty files that only carry the names a game uses.
GAME_FILES=('chr/c0000.anibnd.dcx','chr/c0000_a000_lo.anibnd.dcx','chr/c0000_c5060.anibnd.dcx','chr/c5060.anibnd.dcx',
            'chr/c5060.chrbnd.dcx','chr/c5060.texbnd.dcx','chr/c0000.chrbnd.dcx','chr/a000_extra.anibnd.dcx',
            'parts/fc_m_0200.partsbnd.dcx','parts/am_m_9000.partsbnd.dcx','parts/am_m_9000_l.partsbnd.dcx','mtd/allmaterialbnd.mtdbnd.dcx')


def touch(root,*names):
    for name in names:
        path=Path(root)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'')
    return Path(root)


def game_tree(root,executable='sekiro.exe'):
    return touch(root,executable,*GAME_FILES)


class Detection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):
        self.temp.cleanup()
    def test_game_folder_is_identified_by_its_executable(self):
        found=detect(game_tree(self.root/'Sekiro'))
        self.assertEqual((found['layout'],found['game'],found['evidence']),('game','sekiro','sekiro.exe'))
        self.assertEqual(found['counts'],dict(animations=5,characters=2,parts=3,textures=1,materials=1))
        self.assertEqual(found['folders']['materials'],['mtd'])
    def test_chosen_chr_folder_stands_for_the_game_folder(self):
        root=game_tree(self.root/'Sekiro')
        found=detect(root/'chr')
        self.assertEqual(found['root'],str(root))
        self.assertEqual(found['note'],'Uses the folder that contains chr.')
    def test_data_subfolder_is_used_for_dark_souls_3(self):
        game_tree(self.root/'DS3'/'Game','DarkSoulsIII.exe')
        found=detect(self.root/'DS3')
        self.assertEqual((found['root'],found['game']),(str(self.root/'DS3'/'Game'),'ds3'))
    def test_material_library_identifies_elden_ring(self):
        touch(self.root/'ER','chr/c3000.anibnd.dcx','material/allmaterial.matbinbnd.dcx')
        found=detect(self.root/'ER')
        self.assertEqual((found['game'],found['folders']['materials']),('er',['material']))
    def test_collected_folder_counts_everything_below_it(self):
        touch(self.root/'Mine','Owl/c5060.anibnd.dcx','Owl/c5060.chrbnd.dcx','Wolf/c0000.anibnd.dcx','Wolf/fc_m_0200.partsbnd.dcx')
        found=detect(self.root/'Mine')
        self.assertEqual((found['layout'],found['counts']['animations'],found['counts']['parts']),('folder',2,1))
    def test_folder_of_games_lists_them(self):
        game_tree(self.root/'Games'/'Sekiro');game_tree(self.root/'Games'/'Elden Ring'/'Game','eldenring.exe')
        found=detect(self.root/'Games')
        self.assertEqual([(n['name'],n['game']) for n in found['nested']],[('Elden Ring','er'),('Sekiro','sekiro')])
    def test_missing_folder_is_refused(self):
        with self.assertRaises(ValueError):detect(self.root/'nowhere')


class Files(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):
        self.temp.cleanup()
    def test_leading_id_names_the_owner(self):
        for name,owner in [('c0000_c5060.anibnd.dcx','c0000'),('c5060.anibnd.dcx','c5060'),('C1000-alt.anibnd','c1000'),
                           ('a000_extra.anibnd.dcx',''),('c00001.anibnd.dcx','')]:
            self.assertEqual(leading_id(name),owner,name)
    def test_kind_files_skip_backups_unless_listed_directly(self):
        folder=touch(self.root/'anims','c1000.anibnd.dcx','backup/c1000.anibnd.dcx','more/c1010.anibnd.dcx','c1000.chrbnd.dcx')
        self.assertEqual([p.name for p in kind_files([folder],'animations')],['c1000.anibnd.dcx'])
        self.assertEqual([p.relative_to(folder).as_posix() for p in kind_files([folder],'animations',True)],['c1000.anibnd.dcx','more/c1010.anibnd.dcx'])
    def test_custom_folders_are_relative_or_absolute(self):
        touch(self.root/'base','anims/c1000.anibnd.dcx','anims/deep/c1010.anibnd.dcx');touch(self.root/'elsewhere','c1000.chrbnd.dcx')
        folders=dict(animations=['anims','anims','missing'],characters=[str(self.root/'elsewhere')])
        resolved=resolve_folders(self.root/'base',folders)
        self.assertEqual((resolved['animations'],resolved['characters']),([self.root/'base'/'anims'],[self.root/'elsewhere']))
        self.assertEqual(count_custom(self.root/'base',folders)[0],dict(animations=1,characters=1,parts=0,textures=0,materials=0))
        self.assertEqual(count_custom(self.root/'base',folders,True)[0]['animations'],2)
        self.assertTrue(count_custom(self.root/'base',folders,True,limit=1)[1])
    def test_earlier_folder_hides_the_same_file_name(self):
        mod=touch(self.root/'mod','c1000.anibnd','deep/c1010.anibnd.dcx','c1000.texbnd.dcx')
        game=touch(self.root/'game','C1000.ANIBND.DCX','c1010.anibnd.dcx','c1020.anibnd.dcx','deep/c1020.anibnd.dcx','c1000.texbnd.dcx','c1000_l.texbnd.dcx')
        names=lambda found:[p.relative_to(self.root).as_posix() for p in found]
        self.assertEqual(names(kind_files([mod,game],'animations')),['mod/c1000.anibnd','game/c1010.anibnd.dcx','game/c1020.anibnd.dcx'])
        # A file in a subfolder hides others only when subfolders are read; copies within one folder are kept.
        self.assertEqual(names(kind_files([mod,game],'animations',True)),['mod/c1000.anibnd','mod/deep/c1010.anibnd.dcx','game/c1020.anibnd.dcx','game/deep/c1020.anibnd.dcx'])
        self.assertEqual(names(kind_files([mod,game],'textures')),['mod/c1000.texbnd.dcx','game/c1000_l.texbnd.dcx'])
        self.assertEqual(count_custom(self.root,dict(animations=['mod','game'],textures=['mod','game']),True)[0],dict(animations=4,characters=0,parts=0,textures=2,materials=0))


class StructuredIndex(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name).resolve()
        self.game,self.cache=game_tree(base/'Sekiro'),base/'cache'
        patch=mock.patch.object(asset_discovery,'configure_oodle');patch.start();self.addCleanup(patch.stop)
    def tearDown(self):
        self.temp.cleanup()
    def test_game_layout_groups_archives_by_their_leading_character(self):
        _,catalog=discover(self.game,self.cache,layout='auto')
        self.assertEqual((catalog['layout'],catalog['game'],catalog['gameEvidence']),('game','sekiro','sekiro.exe'))
        characters={c['id']:c for c in catalog['characters']}
        self.assertEqual(sorted(characters),['c0000','c5060'])
        self.assertEqual([Path(a).name for a in characters['c0000']['archives']],['c0000.anibnd.dcx','c0000_a000_lo.anibnd.dcx','c0000_c5060.anibnd.dcx'])
        self.assertFalse(characters['c5060']['inventoried'])
        self.assertEqual(Path(characters['c5060']['model']).name,'c5060.chrbnd.dcx')
        self.assertEqual([Path(r['path']).name for r in catalog['referenceModels']],['c0000.chrbnd.dcx'])
        self.assertEqual(sorted(p['id'] for p in catalog['parts']),['am_m_9000','fc_m_0200'])
        self.assertEqual([Path(f).name for f in catalog['textureFolders']],['chr','parts'])
        self.assertIn('a000_extra.anibnd.dcx',' '.join(catalog['warnings']))
    def test_chosen_chr_folder_scans_the_game_folder(self):
        _,catalog=discover(self.game/'chr',self.cache,layout='game')
        self.assertEqual(catalog['folder'],str(self.game))
    def test_inventoried_characters_carry_over_until_their_archives_change(self):
        path,catalog=discover(self.game,self.cache,layout='game')
        archive=self.game/'chr'/'c5060.anibnd.dcx'
        entry=next(c for c in catalog['characters'] if c['id']=='c5060')
        entry.update(inventoried=True,count=1,ready=1)
        catalog['clips']=[dict(id='c5060:0',name='a000_003011',characterKey='c5060',game='sekiro',inputArchives=[str(archive)])]
        catalog['archiveSignatures']={str(archive):signature(archive)}
        path.write_text(json.dumps(catalog),encoding='utf-8')
        _,again=discover(self.game,self.cache,layout='game')
        self.assertTrue(next(c for c in again['characters'] if c['id']=='c5060')['inventoried'])
        self.assertEqual([c['name'] for c in again['clips']],['a000_003011'])
        archive.write_bytes(b'changed')
        _,changed=discover(self.game,self.cache,layout='game')
        self.assertFalse(next(c for c in changed['characters'] if c['id']=='c5060')['inventoried'])
        self.assertEqual(changed['clips'],[])
    def test_custom_layout_reads_its_own_folders(self):
        mods=touch(Path(self.temp.name).resolve()/'Mods','Owl/c5060.anibnd.dcx','Owl/deep/c5060_a100.anibnd.dcx')
        folders=dict(animations=[str(mods)],characters=[str(self.game/'chr')],parts=[],textures=[str(mods/'Owl')],materials=[str(self.game/'mtd')])
        _,catalog=discover(Path(self.temp.name).resolve(),self.cache,layout='custom',folders=folders,recursive=True)
        self.assertEqual([c['id'] for c in catalog['characters']],['c5060'])
        self.assertEqual(catalog['characters'][0]['archiveCount'],2)
        self.assertEqual(Path(catalog['characters'][0]['model']).name,'c5060.chrbnd.dcx')
        self.assertTrue(catalog['recursive'])
    def test_custom_layout_first_folder_wins_for_every_kind(self):
        base=Path(self.temp.name).resolve()
        mod=touch(base/'Mod','chr/c5060.anibnd.dcx','chr/c5060.chrbnd','chr/c0000.flver','parts/fc_m_0200.partsbnd.dcx','mtd/allmaterialbnd.mtdbnd.dcx')
        kinds=dict(animations='chr',characters='chr',parts='parts',textures='chr',materials='mtd')
        folders={kind:[str(mod/sub),str(self.game/sub)] for kind,sub in kinds.items()}
        _,catalog=discover(base,self.cache,layout='custom',folders=folders,recursive=False)
        where=lambda path:Path(path).relative_to(base).as_posix()
        characters={c['id']:c for c in catalog['characters']}
        self.assertEqual([where(a) for a in characters['c5060']['archives']],['Mod/chr/c5060.anibnd.dcx'])
        self.assertEqual(where(characters['c5060']['model']),'Mod/chr/c5060.chrbnd')
        self.assertEqual(characters['c0000']['archiveCount'],3)
        # The game's c0000.chrbnd.dcx has another name, but the mod's folder comes first.
        self.assertEqual([where(r['path']) for r in catalog['referenceModels']],['Mod/chr/c0000.flver'])
        self.assertEqual(sorted((p['id'],where(p['path'])) for p in catalog['parts']),[('am_m_9000','Sekiro/parts/am_m_9000.partsbnd.dcx'),('fc_m_0200','Mod/parts/fc_m_0200.partsbnd.dcx')])
        self.assertEqual([where(m['path']) for m in catalog['materialLibraries']],['Mod/mtd/allmaterialbnd.mtdbnd.dcx'])
        self.assertEqual([where(f) for f in catalog['textureFolders']],['Mod/chr','Sekiro/chr'])
    def test_custom_layout_needs_an_animation_folder(self):
        with self.assertRaisesRegex(ValueError,'animation folder'):
            discover(self.game,self.cache,layout='custom',folders={})
    def test_cache_is_not_a_source(self):
        self.cache.mkdir()
        with self.assertRaises(ValueError):discover(self.cache,self.cache,layout='auto')


class StructuredSelection(unittest.TestCase):
    def catalog(self):
        clip=lambda character:dict(id=character+':0',name='a000_003011',issues=[],game='sekiro',character=character,scope='game',
                                   path='anim.hkx',skeleton='skeleton.hkx',compendium='c.compendium',skeletonCompendium='')
        part=lambda ident:dict(id=ident,name=ident.upper(),path=ident+'.partsbnd.dcx',selected=False)
        return dict(layout='game',recursive=False,clips=[clip('c5060'),clip('c0000')],textureFolders=['chr','parts'],
                    parts=[part(p) for p in ('fc_m_0200','am_m_9000','bd_m_9000','lg_m_9000','fc_m_0100')],
                    models=[dict(id='c5060',name='C5060',path='c5060.chrbnd.dcx',selected=False),dict(id='c1000',name='C1000',path='c1000.chrbnd.dcx',selected=False)],
                    referenceModels=[dict(path='c0000.chrbnd.dcx')],
                    materialLibraries=[dict(path='mtd/mtd.mtdbnd.dcx',kind='mtd',loose=False),dict(path='mtd/allmaterialbnd.mtdbnd.dcx',kind='mtd',loose=False)])
    def test_character_model_is_found_by_its_id(self):
        chosen=selection(self.catalog(),'c5060:0')
        self.assertEqual([(p['id'],p['selected']) for p in chosen['parts']],[('c5060',True)])
        self.assertEqual((chosen['textureFolders'],chosen['textureDirectory'],chosen['characterSource']),(['chr','parts'],'',''))
        self.assertEqual((chosen['materialBinder'],chosen['referenceModel']),('mtd/allmaterialbnd.mtdbnd.dcx','c0000.chrbnd.dcx'))
    def test_wolf_uses_its_standard_parts(self):
        chosen=selection(self.catalog(),'c0000:0')
        self.assertEqual(chosen['preset'],'wolf')
        self.assertEqual(sorted(p['id'] for p in chosen['parts'] if p['selected']),sorted(PRESETS['wolf']))
        self.assertEqual(chosen['missing'],[])
        catalog=self.catalog()
        catalog['parts'].append(dict(id='wp_a_0300',name='WP_A_0300',path='wp_a_0300.partsbnd.dcx',selected=False))
        selected=selection(catalog,'c0000:0')['parts']
        self.assertTrue(next(p for p in selected if p['id']=='wp_a_0300')['selected'])
    def test_material_library_tie_follows_folder_order(self):
        catalog=self.catalog()
        catalog['materialLibraries']=[dict(path='b_mod/mtd/allmaterialbnd.mtdbnd.dcx',kind='mtd',loose=False),dict(path='a_game/material/allmaterial.matbinbnd.dcx',kind='matbin',loose=False)]
        self.assertEqual(selection(catalog,'c5060:0')['materialBinder'],'b_mod/mtd/allmaterialbnd.mtdbnd.dcx')


class SettingsMigration(unittest.TestCase):
    SAVED=[dict(id='a1',name='Sekiro',path=r'C:\Games\Sekiro',layout='auto',folders={},state={})]
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.settings_file,self.sources_file=Path(temp.name)/'ui-settings.json',Path(temp.name)/'ui-sources.json'
        for name,value in (('SETTINGS',self.settings_file),('SOURCES',self.sources_file),('CONFIG',{})):
            patch=mock.patch.object(bridge_ui,name,value);patch.start();self.addCleanup(patch.stop)
    def load(self,settings,sources=None):
        self.settings_file.write_text(json.dumps(settings),encoding='utf-8')
        if sources is not None:self.sources_file.write_text(json.dumps(sources),encoding='utf-8')
        return bridge_ui.defaults()
    def test_single_assets_folder_becomes_the_first_source(self):
        result=self.load(dict(inputMethod='folder',assetFolder=r'D:\Assets\Owl',assetCatalog='owl.json',game='sekiro'))
        [source]=result['sources']
        self.assertEqual((source['path'],source['layout'],source['catalog'],source['game']),(r'D:\Assets\Owl','folder','owl.json','sekiro'))
        self.assertEqual(result['activeSource'],source['id'])
    def test_saved_sources_are_kept(self):
        result=self.load(dict(inputMethod='folder',assetFolder=r'D:\Old'),dict(sources=self.SAVED,activeSource='a1'))
        self.assertEqual((result['sources'],result['activeSource']),(self.SAVED,'a1'))
    def test_sources_survive_an_older_bridge_rewriting_the_settings(self):
        bridge_ui.persist(dict(self.load(dict(inputMethod='folder')),sources=self.SAVED,activeSource='a1'))
        self.assertNotIn('sources',json.loads(self.settings_file.read_text(encoding='utf-8')))
        # An older bridge writes only the keys it knows.
        result=self.load(dict(inputMethod='folder',assetFolder=r'D:\Old',assetCatalog='old.json'))
        self.assertEqual((result['sources'],result['activeSource']),(self.SAVED,'a1'))


if __name__=='__main__':
    unittest.main()
