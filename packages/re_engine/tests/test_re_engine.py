"""The RE Engine package through the bridge's package API, with a stand-in decoder and made-up files.

Run from the bridge folder: python -m unittest discover -s packages/re_engine/tests
"""
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BRIDGE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BRIDGE / 'standalone'), str(BRIDGE / 'standalone' / 'tests')]
import games
from games import api, packages
from test_interchange import owned_motion

MESH = 'natives/x64/character/player/pl0100_dante/{}/{}.mesh.1808282334'
FILES = (MESH.format('pl0100_body', 'pl0100'), MESH.format('pl0100_01_head', 'pl0100_01_head'),
         MESH.format('pl0100_03_hair', 'pl0100_03_hair'), MESH.format('pl0100_01_head', 'pl0100_01_head_eyelash'),
         'natives/x64/character/player/pl0100_dante/pl0100_body/pl0100.mdf2.10',
         'natives/x64/animation/player/pl0100/base/pl0100_base.motlist.85',
         'natives/x64/animation/enemy/em0000/em0000_base.motlist.85',
         'natives/x64/character/enemy/em0000_00/em0000.mesh.1808282334')


def fake_decoder(ctx, tool, *args, timeout=900):
    """The ReEngineDecoder commands the package uses, answered with made-up data."""
    command = args[0]
    if command == 'motlist':
        motions = [dict(index=0, id=1, name='pl0100_Idle', frameCount=3, frameRate=60.0, boneCount=2, mirror=False),
                   dict(index=1, id=2, name='pl0100_Event', frameCount=3, frameRate=60.0, boneCount=0, mirror=True)]
        Path(args[2]).write_text(json.dumps(dict(version=85, motions=motions)), encoding='utf-8')
    elif command == 'decode':
        Path(args[3]).write_text(json.dumps(owned_motion(version=2)), encoding='utf-8')
        return 'NOTE: Coat_L is animated but not in the skeleton\n'
    else:
        raise AssertionError(f'unexpected decoder command {command}')
    return ''


class Package(unittest.TestCase):
    """The RE Engine package from this folder, as the only package."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolved, as the bridge resolves the paths it stores: the temporary folder can be named in its 8.3 short
        # form (C:\Users\RUNNER~1 on the release runner).
        temp = Path(self.temp.name).resolve()
        self.root = temp / 'extracted'
        for path in FILES:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'stand-in')
        self.cache = temp / 'cache'
        for name, value in (('ROOTS', [BRIDGE / 'packages']), ('CACHE', self.cache)):
            patcher = mock.patch.object(packages, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(games.reload)
        games.reload()
        self.engine = games.adapter('re_engine')
        self.module = self.engine.module
        decoder = mock.patch.object(api.Context, 'run', autospec=True, side_effect=fake_decoder)
        decoder.start()
        self.addCleanup(decoder.stop)
        self.notes = []

    def notify(self, stage, message, progress=None, **extra):
        self.notes.append(message)


class Source(Package):
    def test_the_package_loads_with_its_games(self):
        self.assertEqual(self.engine.package.error, '')
        self.assertEqual([p.id for p in games.games('re_engine')], ['dmc5', 're2'])
        self.assertTrue(games.profile('dmc5').verified)
        self.assertFalse(games.profile('re2').verified)
        self.assertEqual(games.profile('dmc5').space().basis, ((1, 0, 0), (0, 0, -1), (0, 1, 0)))

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
        from asset_discovery import discover
        with self.assertRaisesRegex(ValueError, 'choose its file list'):
            discover(game, self.cache, self.notify, '', 'auto', 'game', None, True, '')

    def test_scan_inventory_selection_and_import(self):
        from asset_discovery import discover, inventory_character, load_catalog, selection
        path, catalog = discover(self.root, self.cache, self.notify, '', 'auto', 'game', None, True, '')
        self.assertEqual((catalog['engine'], catalog['game'], catalog['schema']), ('re_engine', 'dmc5', self.module.CATALOG_SCHEMA))
        self.assertTrue(Path(catalog['work']).is_relative_to(self.cache / 'packages' / 're_engine'))
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
        motion = self.module.decode(chosen, Path(self.temp.name) / 'motion.json', self.engine.context(self.cache), notes=notes)
        self.assertEqual((motion['formatVersion'], motion['source']['engine'], motion['source']['game']), (2, 're_engine', 'dmc5'))
        self.assertEqual(motion['archive'], idle['archive'])
        self.assertEqual(notes, ['Coat_L is animated but not in the skeleton'])

        # A clip of a character not read yet: the import reads it, and the bridge stores the catalog.
        _, fresh = discover(self.root, self.cache, self.notify, '', 'auto', 'game', None, True, '')
        fresh = dict(fresh, characters=[dict(c, inventoried=False) for c in fresh['characters']], clips=[])
        request = dict(assetClip=idle['id'], assetCharacter='pl0100', includeCharacter=False, game='auto')
        temp = Path(self.temp.name) / 'job'
        temp.mkdir()
        motion_path, character_args, report = self.engine.prepare(request, path, fresh, temp, self.notify)
        self.assertEqual((character_args, report['game'], report['warnings']),
                         ([], 'Devil May Cry 5', ['Coat_L is animated but not in the skeleton']))
        self.assertEqual((request['game'], request['motionIndex'], request['animation']), ('dmc5', 0, idle['path']))
        self.assertEqual(len(json.loads(Path(path).read_text(encoding='utf-8'))['clips']), 2)

    def test_a_missing_decoder_is_reported(self):
        copy = Path(self.temp.name) / 'copy' / 're_engine'
        copy.mkdir(parents=True)
        shutil.copy(BRIDGE / 'packages' / 're_engine' / 'package.json', copy / 'package.json')
        package = packages.Package(copy, packages.read_manifest(copy))
        ready, detail = package.tool_status(package.tool('decoder'))
        self.assertFalse(ready)
        self.assertIn('RE Engine decoder is missing', detail)

    def test_loose_files_replace_packed_ones(self):
        catalog = dict(folder=str(self.root), work=str(self.cache / 'work'), container='pak')
        self.assertEqual(self.module.local_file(catalog, FILES[0].upper().replace('NATIVES', 'natives')), self.root / FILES[0])
        self.assertIsNone(self.module.local_file(catalog, 'natives/x64/character/player/none.mesh.1808282334'))


class Materials(Package):
    def setUp(self):
        super().setUp()
        self.profile = games.profile('dmc5')
        self.characters = importlib.import_module('bridge_packages.re_engine.characters')

    def material(self, shader, textures, params=()):
        return dict(name='Owned', shader=shader, textures=[dict(slot=s, path=p) for s, p in textures],
                    params=[dict(name=n, value=v) for n, v in params])

    def images(self, *paths):
        return {p: dict(path=f'C:/owned/{Path(p).stem}.png', stem=Path(p).stem) for p in paths}

    def test_albedo_normal_and_hair_cut_out(self):
        material = self.material('Character/Hair.mmtr', [('BaseShiftMap', 'hair_ALBM.tex'), ('NormalRoughnessMap', 'hair_NRMR.tex'),
                                                         ('AlphaTranslucentOcclusionSSSMap', 'hair_ATOS.tex')],
                                 [('BaseColor', [.5, .4, .3, 1])])
        spec = self.characters.material_spec(material, 'Owned', self.images('hair_ALBM.tex', 'hair_NRMR.tex', 'hair_ATOS.tex'), self.profile)
        self.assertEqual(spec['family'], 'Devil May Cry 5')
        self.assertEqual(spec['albedo']['stem'], 'hair_ALBM')
        # The shift map's alpha is data, as are roughness in NRMR and subsurface in ATOS.
        self.assertTrue(spec['albedo']['packedAlpha'] and spec['normal']['packedAlpha'] and spec['opacity']['packedAlpha'])
        self.assertFalse(spec['alpha'])
        self.assertEqual((spec['normal']['convention'], spec['normal']['channels']), ('directx', 'xyz'))
        self.assertEqual((spec['opacity']['stem'], spec['opacity']['channel']), ('hair_ATOS', 'R'))
        self.assertEqual(spec['color'], [.5, .4, .3])
        self.assertNotIn('opacityValue', spec)

    def test_null_textures_and_hidden_overlays(self):
        material = self.material('Character/EyeTransparent.mmtr', [('BaseMetalMap', 'systems/rendering/NullBlack.tex')])
        spec = self.characters.material_spec(material, 'Owned', {}, self.profile)
        self.assertIsNone(spec['albedo'])
        self.assertEqual(spec['opacityValue'], 0.0)
        self.assertEqual(self.characters.material_spec(None, 'Missing', {}, self.profile)['color'], [.6, .6, .6])

    def test_texture_paths_prefer_streaming(self):
        self.assertEqual(self.characters.texture_paths('Character\\Player\\pl0100_ALBM.tex', self.profile),
                         ['natives/x64/streaming/character/player/pl0100_albm.tex.11', 'natives/x64/character/player/pl0100_albm.tex.11'])
        self.assertEqual(self.characters.role(MESH.format('pl0100_03_hair', 'pl0100_03_hair')), 'Hair')


if __name__ == '__main__':
    unittest.main()
