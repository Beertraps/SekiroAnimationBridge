"""The game registry, engine dispatch and the RE Engine adapter, with a stand-in decoder and made-up files."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import games
from games import re_engine
from games.re_engine import characters
from games.space import FROMSOFT, RE_ENGINE
from test_interchange import owned_motion

ADAPTER_FUNCTIONS = ('detect', 'discover', 'inventory_character', 'refresh_clip', 'load_catalog', 'selection', 'preview', 'prepare')
MESH = 'natives/x64/character/player/pl0100_dante/{}/{}.mesh.1808282334'
FILES = (MESH.format('pl0100_body', 'pl0100'), MESH.format('pl0100_01_head', 'pl0100_01_head'),
         MESH.format('pl0100_03_hair', 'pl0100_03_hair'), MESH.format('pl0100_01_head', 'pl0100_01_head_eyelash'),
         'natives/x64/character/player/pl0100_dante/pl0100_body/pl0100.mdf2.10',
         'natives/x64/animation/player/pl0100/base/pl0100_base.motlist.85',
         'natives/x64/animation/enemy/em0000/em0000_base.motlist.85',
         'natives/x64/character/enemy/em0000_00/em0000.mesh.1808282334')


def fake_decoder(*args, decoder=''):
    """The ReEngineDecoder commands the adapter uses, answered with made-up data."""
    command = args[0]
    if command == 'motlist':
        motions = [dict(index=0, id=1, name='pl0100_Idle', frameCount=3, frameRate=60.0, boneCount=2, mirror=False),
                   dict(index=1, id=2, name='pl0100_Event', frameCount=3, frameRate=60.0, boneCount=0, mirror=False)]
        Path(args[2]).write_text(json.dumps(dict(version=85, motions=motions)), encoding='utf-8')
    elif command == 'decode':
        motion = owned_motion(version=2)
        Path(args[3]).write_text(json.dumps(motion), encoding='utf-8')
        return 'NOTE: Coat_L is animated but not in the skeleton\n'
    else:
        raise AssertionError(f'unexpected decoder command {command}')
    return ''


class Registry(unittest.TestCase):
    def test_profiles_name_known_engines_and_unique_ids(self):
        ids = [profile.id for profile in games.PROFILES]
        self.assertEqual(len(ids), len(set(ids)))
        for profile in games.PROFILES:
            self.assertIn(profile.engine, games.ENGINES, profile.id)
            self.assertTrue(profile.name and profile.short and profile.hint, profile.id)

    def test_only_fromsoft_games_export(self):
        for profile in games.PROFILES:
            self.assertEqual(profile.capabilities.export, profile.engine == 'fromsoft', profile.id)
        self.assertEqual(games.profile('dmc5').space(), RE_ENGINE)
        self.assertEqual(games.profile('sekiro').space(), FROMSOFT)

    def test_public_registry_is_json(self):
        registry = json.loads(json.dumps(games.public()))
        self.assertEqual({g['id'] for g in registry['games']}, set(games.BY_ID))
        self.assertIn('re_engine', registry['engines'])

    def test_every_adapter_has_the_contract(self):
        for engine in games.ENGINES:
            adapter = games.adapter(engine)
            if engine == games.DEFAULT_ENGINE:
                continue
            for name in ADAPTER_FUNCTIONS:
                self.assertTrue(callable(getattr(adapter, name, None)), f'{engine}.{name}')

    def test_foreign_dispatch(self):
        self.assertIsNone(games.foreign(dict(engine='fromsoft')))
        self.assertIsNone(games.foreign(dict(game='sekiro')))
        self.assertIsNone(games.foreign({}))
        self.assertIs(games.foreign(dict(engine='re_engine')), re_engine)
        self.assertIs(games.foreign(dict(game='dmc5')), re_engine)
        self.assertIs(games.foreign(dict(source=dict(engine='re_engine'))), re_engine)
        with self.assertRaises(ValueError):
            games.adapter('unknown')


class GameChecks(unittest.TestCase):
    def test_requests_name_registered_games(self):
        from bridge_runtime import check_games
        check_games(dict(mode='import', game='dmc5'))
        check_games(dict(mode='export', exportGame='sekiro'))
        with self.assertRaisesRegex(ValueError, 'Unknown game'):
            check_games(dict(mode='import', game='dmc6'))
        with self.assertRaisesRegex(ValueError, 'Unknown donor game'):
            check_games(dict(mode='import', donor=dict(game='dmc6')))
        with self.assertRaisesRegex(ValueError, 'cannot write its animation format'):
            check_games(dict(mode='export', exportGame='dmc5'))


class ReEngineSource(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'extracted'
        for path in FILES:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'stand-in')
        self.cache = Path(self.temp.name) / 'cache'
        self.notes = []
        decoder = mock.patch.object(re_engine, 'run_decoder', side_effect=fake_decoder)
        decoder.start()
        self.addCleanup(decoder.stop)

    def notify(self, stage, message, progress=None, **extra):
        self.notes.append(message)

    def test_natives_folder_is_detected_by_file_versions(self):
        for chosen in (self.root, self.root / 'natives', self.root / 'natives' / 'x64'):
            found = games.detect(chosen)
            self.assertEqual((found['game'], found['engine'], found['container']), ('dmc5', 're_engine', 'natives'), chosen)
            self.assertFalse(found['needsFileList'])
            self.assertEqual(found['counts'], dict(animations=2, characters=5, materials=1))

    def test_game_folder_needs_a_file_list(self):
        game = Path(self.temp.name) / 'game'
        game.mkdir()
        for name in ('DevilMayCry5.exe', 're_chunk_000.pak', 're_chunk_000.pak.patch_010.pak',
                     're_chunk_000.pak.patch_002.pak', 're_chunk_000.pak.patch_001.pak'):
            (game / name).write_bytes(b'')
        found = games.detect(game)
        self.assertEqual((found['game'], found['container']), ('dmc5', 'pak'))
        self.assertTrue(found['needsFileList'])
        self.assertIn('DMC5_STM_Release.list', found['note'])
        self.assertEqual([Path(p).name for p in found['archives']],
                         ['re_chunk_000.pak', 're_chunk_000.pak.patch_001.pak', 're_chunk_000.pak.patch_002.pak',
                          're_chunk_000.pak.patch_010.pak'])
        self.assertIsNone(games.detect(Path(self.temp.name) / 'missing'))

    def test_scan_inventory_selection_and_decode(self):
        from asset_discovery import discover, inventory_character, load_catalog, selection
        path, catalog = discover(self.root, self.cache, self.notify, '', 'auto', 'game', None, True, '')
        self.assertEqual((catalog['engine'], catalog['game'], catalog['schema']), ('re_engine', 'dmc5', re_engine.CATALOG_SCHEMA))
        people = {c['id']: c for c in catalog['characters']}
        self.assertEqual(set(people), {'pl0100', 'em0000'})
        self.assertEqual(people['pl0100']['name'], 'Dante')
        # A folder without a letter-initial name keeps the ID.
        self.assertEqual(people['em0000']['name'], 'EM0000')
        self.assertEqual(people['pl0100']['model'], MESH.format('pl0100_body', 'pl0100'))

        catalog = inventory_character(path, 'pl0100', self.cache, self.notify)
        entry = next(c for c in catalog['characters'] if c['id'] == 'pl0100')
        self.assertEqual((entry['count'], entry['ready']), (2, 1))
        catalog = load_catalog(path, self.root, True)
        idle = next(c for c in catalog['clips'] if c['name'] == 'pl0100_Idle')
        self.assertEqual(idle['id'], 'pl0100/pl0100_base#0')
        with self.assertRaisesRegex(ValueError, 'no bone animation'):
            selection(catalog, 'pl0100/pl0100_base#1')

        chosen = selection(catalog, idle['id'])
        self.assertEqual((chosen['engine'], chosen['game'], chosen['preset'], chosen['motion']), ('re_engine', 'dmc5', 'player', 0))
        picked = [(p['id'], p['role']) for p in chosen['parts'] if p['selected']]
        self.assertEqual(picked, [('pl0100', 'Body'), ('pl0100_01_head', 'Head'), ('pl0100_03_hair', 'Hair')])

        notes = []
        motion = re_engine.decode(chosen, Path(self.temp.name) / 'motion.json', notes=notes)
        self.assertEqual((motion['formatVersion'], motion['source']['engine'], motion['source']['game']), (2, 're_engine', 'dmc5'))
        self.assertEqual(motion['archive'], idle['archive'])
        self.assertEqual(notes, ['Coat_L is animated but not in the skeleton'])

    def test_missing_decoder_is_reported(self):
        ready, detail = re_engine.decoder_status(str(Path(self.temp.name) / 'missing.exe'))
        self.assertFalse(ready)
        self.assertIn('build_decoder.cmd', detail)

    def test_loose_files_replace_packed_ones(self):
        catalog = dict(folder=str(self.root), work=str(self.cache / 'work'), container='pak')
        self.assertEqual(re_engine.local_file(catalog, FILES[0].upper().replace('NATIVES', 'natives')), self.root / FILES[0])
        self.assertIsNone(re_engine.local_file(catalog, 'natives/x64/character/player/none.mesh.1808282334'))


class ReEngineMaterials(unittest.TestCase):
    profile = games.profile('dmc5')

    def material(self, shader, textures, params=()):
        return dict(name='Owned', shader=shader, textures=[dict(slot=s, path=p) for s, p in textures],
                    params=[dict(name=n, value=v) for n, v in params])

    def images(self, *paths):
        return {p: dict(path=f'C:/owned/{Path(p).stem}.png', stem=Path(p).stem) for p in paths}

    def test_albedo_normal_and_hair_cut_out(self):
        material = self.material('Character/Hair.mmtr', [('BaseShiftMap', 'hair_ALBM.tex'), ('NormalRoughnessMap', 'hair_NRMR.tex'),
                                                         ('AlphaTranslucentOcclusionSSSMap', 'hair_ATOS.tex')],
                                 [('BaseColor', [.5, .4, .3, 1])])
        spec = characters.material_spec(material, 'Owned', self.images('hair_ALBM.tex', 'hair_NRMR.tex', 'hair_ATOS.tex'), self.profile)
        self.assertEqual(spec['family'], 'Devil May Cry 5')
        self.assertEqual(spec['albedo']['stem'], 'hair_ALBM')
        self.assertFalse(spec['alpha'])
        self.assertEqual((spec['normal']['convention'], spec['normal']['channels']), ('directx', 'xyz'))
        self.assertEqual((spec['opacity']['stem'], spec['opacity']['channel']), ('hair_ATOS', 'R'))
        self.assertEqual(spec['color'], [.5, .4, .3])
        self.assertNotIn('opacityValue', spec)

    def test_null_textures_and_hidden_overlays(self):
        material = self.material('Character/EyeTransparent.mmtr', [('BaseMetalMap', 'systems/rendering/NullBlack.tex')])
        spec = characters.material_spec(material, 'Owned', {}, self.profile)
        self.assertIsNone(spec['albedo'])
        self.assertEqual(spec['opacityValue'], 0.0)
        self.assertEqual(characters.material_spec(None, 'Missing', {}, self.profile)['color'], [.6, .6, .6])

    def test_texture_paths_prefer_streaming(self):
        self.assertEqual(characters.texture_paths('Character\\Player\\pl0100_ALBM.tex', self.profile),
                         ['natives/x64/streaming/character/player/pl0100_albm.tex.11', 'natives/x64/character/player/pl0100_albm.tex.11'])
        self.assertEqual(characters.role(MESH.format('pl0100_03_hair', 'pl0100_03_hair')), 'Hair')


if __name__ == '__main__':
    unittest.main()
