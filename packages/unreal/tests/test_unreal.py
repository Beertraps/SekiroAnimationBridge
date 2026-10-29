"""The Unreal package through the bridge's package API, with a stand-in decoder and made-up archives.

Run from the bridge folder: python -m unittest discover -s packages/unreal/tests
"""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

BRIDGE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BRIDGE / 'standalone'), str(BRIDGE / 'standalone' / 'tests')]
import games
from games import api, packages
from test_interchange import owned_motion

SKELETON = '/Game/Characters/Hero/SK_Hero_Skeleton.SK_Hero_Skeleton'
PROP = '/Game/Props/Crate/SK_Crate_Skeleton.SK_Crate_Skeleton'
RUN, IDLE = '/Game/Characters/Hero/Anims/Run.Run', '/Game/Characters/Hero/Anims/Idle.Idle'
BODY, HEAD = '/Game/Characters/Hero/SK_Hero.SK_Hero', '/Game/Characters/Hero/SK_Hero_Head.SK_Hero_Head'
UNREAL = [[1, 0, 0], [0, -1, 0], [0, 0, 1]]
TOC_MAGIC = b'-==--==--==--==-'


def pak(path, version=11, encrypted=False, methods=('Zlib',)):
    """A PAK file that is only its trailer: key GUID, encrypted-index flag, magic, version, index, hash and methods."""
    names = b''.join(m.encode().ljust(32, b'\0') for m in methods).ljust(5 * 32, b'\0')
    trailer = bytes(16) + bytes([encrypted]) + struct.pack('<IiqQ', 0x5A6F12E1, version, 1000, 50) + bytes(20) + names
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\0' * 64 + trailer)


def utoc(path, version=5, encrypted=False, methods=('Oodle',), seeds=2, unhashed=1):
    """An IoStore table of contents: its header, empty chunk tables and the compression method names."""
    entries, blocks, block_size = 3, 4, 12
    header = struct.pack('<16sBBHIIIIIIIII8s16sBBHIQII', TOC_MAGIC, version, 0, 0, 144, entries, blocks, block_size, len(methods),
                         32, 65536, 0, 1, bytes(8), bytes(16), 2 if encrypted else 0, 0, 0, seeds, 0, unhashed, 0).ljust(144, b'\0')
    body = bytes(entries * 22 + seeds * 4 + unhashed * 4 + blocks * block_size) + b''.join(m.encode().ljust(32, b'\0') for m in methods)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + body)


def executable(path, branch):
    """An executable that holds FEngineVersion's branch name, as UTF-16 like the engine stores it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'MZ' + bytes(300) + branch.encode('utf-16-le') + bytes(100))


def scan_document():
    animation = dict(skeleton=SKELETON, archive='Hero-Windows.pak', additive=False, rootMotion=False)
    return dict(format='unreal-scan', formatVersion=1, project='Hero', engine='GAME_UE4_26', mounted=1, closed=[], requiredKeys=[],
                files=120, registries=['Hero/AssetRegistry.bin'], headerScan=False,
                skeletons=[dict(path=SKELETON, name='SK_Hero_Skeleton', archive='Hero-Windows.pak'),
                           dict(path=PROP, name='SK_Crate_Skeleton', archive='Hero-Windows.pak')],
                animations=[dict(animation, path=RUN, name='Run', frames=31, length=1.0, rootMotion=True),
                            dict(animation, path=IDLE, name='Idle', frames=0, length=0.0),
                            dict(animation, path='/Game/Props/Crate/Open.Open', name='Open', skeleton=PROP, frames=11, length=0.5),
                            dict(animation, path='/Game/Lost/Spin.Spin', name='Spin', skeleton='', frames=5, length=0.2)],
                meshes=[dict(path=HEAD, name='SK_Hero_Head', skeleton=SKELETON, archive='Hero-Windows.pak'),
                        dict(path=BODY, name='SK_Hero', skeleton=SKELETON, archive='Hero-Windows.pak')])


def unreal_motion(member):
    motion = owned_motion(version=1)
    return dict(motion, formatVersion=2, source=dict(engine='unreal', container='package', version='GAME_UE4_26', member=member),
                basis=UNREAL, unitScale=0.01, clip=member.rsplit('.', 1)[-1] + '.uasset', rootMotion=None, rootUp=None, rootForward=None)


def write_mesh(stem, name, textures):
    """A one-triangle mesh in the decoder's layout: typed arrays in a .bin and a .json that describes them."""
    arrays = dict(positions=np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10]], np.float32), normals=np.tile(np.float32([0, -1, 0]), (3, 1)),
                  uv_0=np.array([[0, 0], [1, 0], [0, 1]], np.float32), bone_indices=np.array([[0, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]], np.int32),
                  bone_weights=np.array([[1, 0, 0, 0]] * 3, np.float32), faces=np.array([[0, 1, 2]], np.int32),
                  face_materials=np.array([0], np.int32), vertex_materials=np.zeros(3, np.int32))
    described, data = {}, b''
    for key, values in arrays.items():
        described[key] = dict(dtype='f4' if values.dtype == np.float32 else 'i4', shape=list(values.shape), offset=len(data),
                              length=values.nbytes)
        data += values.tobytes()
    Path(f'{stem}.bin').write_bytes(data)
    bones = [dict(index=0, name='root', parent=-1, translation=[0, 0, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1]),
             dict(index=1, name='pelvis', parent=0, translation=[0, 0, 95], rotation=[0, 0, 0, 1], scale=[1, 1, 1])]
    albedo = textures / 'T_Hero_D.png'
    albedo.write_bytes(b'png')
    material = dict(slot='M_Hero', name='MI_Hero', path='/Game/Characters/Hero/MI_Hero.MI_Hero', blendMode='BLEND_Masked',
                    albedo=dict(texture='/Game/Characters/Hero/T_Hero_D.T_Hero_D', file=str(albedo), srgb=True, normalMap=False),
                    normal=dict(texture='/Game/Characters/Hero/T_Hero_N.T_Hero_N', file=str(textures / 'T_Hero_N.png'), srgb=False,
                                normalMap=True),
                    mask=None, emissive=None, color=None)
    info = dict(format='unreal-mesh', formatVersion=1, name=name, bin=Path(f'{stem}.bin').name, basis=UNREAL, unitScale=0.01,
                bones=bones, materials=[material], arrays=described)
    Path(f'{stem}.json').write_text(json.dumps(info), encoding='utf-8')


CALLS = []
SCAN_PRINTED = 'Scanned Hero: 1 archives\nNOTE 3 package headers could not be read\n'


def fake_decoder(ctx, tool, *args, timeout=900):
    """The UnrealDecoder commands the package uses, answered with made-up data."""
    command = args[0]
    CALLS.append((command, json.loads(Path(args[1]).read_text(encoding='utf-8')), [str(a) for a in args[2:]]))
    if command == 'scan':
        Path(args[2]).write_text(json.dumps(scan_document()), encoding='utf-8')
        return SCAN_PRINTED
    if command == 'decode':
        Path(args[3]).write_text(json.dumps(unreal_motion(str(args[2]))), encoding='utf-8')
        return 'NOTE 2 animated bones are not in the mesh: ik_foot_l, ik_foot_r\n'
    if command == 'mesh':
        out = Path(args[2])
        textures = out / 'textures'
        textures.mkdir(parents=True, exist_ok=True)
        meshes = []
        for index, path in enumerate(args[3:]):
            name = path.rsplit('.', 1)[-1]
            stem = out / f'{index:02d}_{name}'
            write_mesh(stem, name, textures)
            meshes.append(dict(path=path, json=f'{stem}.json', error=''))
        Path(out / 'meshes.json').write_text(json.dumps(dict(format='unreal-meshes', formatVersion=1, meshes=meshes,
                                                             textures={'/Game/Characters/Hero/T_Hero_D.T_Hero_D': str(textures / 'T_Hero_D.png')})),
                                             encoding='utf-8')
        return 'NOTE Texture T_Hero_N could not be decoded: unsupported format\n'
    raise AssertionError(f'unexpected decoder command {command}')


class Package(unittest.TestCase):
    """The Unreal package from this folder, as the only package, and a made-up UE 4.26 game."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        temp = Path(self.temp.name)
        self.game = temp / 'Hero Game'
        self.project = self.game / 'Hero'
        self.paks = self.project / 'Content' / 'Paks'
        pak(self.paks / 'Hero-Windows.pak')
        pak(self.game / 'Engine' / 'Programs' / 'CrashReportClient' / 'Content' / 'Paks' / 'CrashReportClient.pak')
        executable(self.project / 'Binaries' / 'Win64' / 'Hero-Win64-Shipping.exe', '++UE4+Release-4.26')
        (self.game / 'Hero.exe').write_bytes(b'MZ')
        self.cache = temp / 'cache'
        for name, value in (('ROOTS', [BRIDGE / 'packages']), ('CACHE', self.cache)):
            patcher = mock.patch.object(packages, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(games.reload)
        games.reload()
        self.engine = games.adapter('unreal')
        self.module = self.engine.module
        CALLS.clear()
        decoder = mock.patch.object(api.Context, 'run', autospec=True, side_effect=fake_decoder)
        decoder.start()
        self.addCleanup(decoder.stop)
        self.notes = []

    def notify(self, stage, message, progress=None, **extra):
        self.notes.append(message)

    def discover(self, root=None, **options):
        from asset_discovery import discover
        return discover(root or self.game, self.cache, self.notify, '', 'auto', 'game', options=options)


class Detection(Package):
    def test_the_package_loads_with_its_games_and_options(self):
        self.assertEqual(self.engine.package.error, '')
        self.assertEqual([p.id for p in games.games('unreal')], ['unreal', 'deep_rock_galactic'])
        space = games.profile('unreal').space()
        self.assertEqual((space.basis, space.unit, space.reflects), (((1, 0, 0), (0, -1, 0), (0, 0, 1)), 0.01, True))
        self.assertEqual([o['id'] for o in self.engine.package.source_options], ['engineVersion', 'aesKey', 'mappings', 'oodle'])

    def test_any_folder_of_the_game_finds_its_project(self):
        for chosen in (self.game, self.project, self.project / 'Content', self.paks, self.project / 'Binaries' / 'Win64'):
            found = games.detect(chosen)
            self.assertEqual((found['engine'], found['game'], found['root'], found['container'], found['name']),
                             ('unreal', 'unreal', str(self.paks), 'pak', 'Hero Game'), chosen)
            # The crash reporter's archive is the engine's, not the game's.
            self.assertEqual([Path(p).name for p in found['archives']], ['Hero-Windows.pak'])
            self.assertEqual(found['engineVersion'], 'GAME_UE4_26')
            self.assertIn('Hero-Win64-Shipping.exe was built with Unreal Engine 4.26', found['evidence'])
            self.assertEqual(([f['id'] for f in found['optionFields']], found['needs'], found['needsFileList']),
                             (['engineVersion', 'mappings'], [], False))
        self.assertIsNone(games.detect(self.game / 'Engine' / 'Programs'))
        self.assertIsNone(games.detect(Path(self.temp.name) / 'missing'))

    def test_an_encrypted_iostore_game_needs_its_key(self):
        game = Path(self.temp.name) / 'Locked'
        utoc(game / 'Locked' / 'Content' / 'Paks' / 'Locked-Windows.utoc', version=5, encrypted=True)
        pak(game / 'Locked' / 'Content' / 'Paks' / 'Locked-Windows.pak', version=11, methods=())
        found = games.detect(game)
        self.assertEqual((found['container'], found['engineVersion'], found['needs']), ('iostore', 'GAME_UE5_1', ['aesKey']))
        # The fields keep the package's order.
        self.assertEqual([f['id'] for f in found['optionFields']], ['engineVersion', 'aesKey', 'mappings', 'oodle'])
        for words in ('AES key', 'IoStore version 5 suggests Unreal Engine 5.1', 'mappings file'):
            self.assertIn(words, found['note'])
        with self.assertRaisesRegex(ValueError, 'enter its AES key'):
            self.discover(game)
        found = games.detect(game, options=dict(aesKey='0x' + '0' * 64, engineVersion='GAME_UE5_3'))
        self.assertEqual((found['needs'], found['engineVersion']), ([], 'GAME_UE5_3'))
        self.assertNotIn('suggests', found['note'])

    def test_a_profile_names_its_game_and_engine(self):
        # Xbox installs keep the project one folder down: Deep Rock Galactic/Content/FSD/Content/Paks.
        game = Path(self.temp.name) / 'Deep Rock Galactic'
        pak(game / 'Content' / 'FSD' / 'Content' / 'Paks' / 'FSD-WinGDK.pak')
        (game / 'Content' / 'Engine').mkdir(parents=True)
        found = games.detect(game)
        self.assertEqual((found['game'], found['name'], found['engineVersion'], found['project']),
                         ('deep_rock_galactic', 'Deep Rock Galactic', 'GAME_UE4_27', 'FSD'))
        self.assertIn('Unreal Engine 4.27 for Deep Rock Galactic', found['evidence'])


class Archives(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        sys.path.insert(0, str(BRIDGE))
        self.addCleanup(sys.path.remove, str(BRIDGE))
        from packages.unreal import archives
        self.archives = archives

    def test_headers_give_version_encryption_and_compression(self):
        pak(self.temp / 'a.pak', version=8, encrypted=True, methods=('Oodle', 'Zlib'))
        utoc(self.temp / 'b.utoc', version=7, methods=('Zstd',), seeds=5, unhashed=2)
        self.assertEqual({k: v for k, v in self.archives.read_pak(self.temp / 'a.pak').items() if k != 'keyGuid'},
                         dict(kind='pak', version=8, encrypted=True, methods=['Oodle', 'Zlib']))
        self.assertEqual({k: v for k, v in self.archives.read_toc(self.temp / 'b.utoc').items() if k != 'keyGuid'},
                         dict(kind='iostore', version=7, encrypted=False, methods=['Zstd']))
        info = self.archives.read_archives([self.temp / 'a.pak', self.temp / 'b.utoc'])
        self.assertEqual((info['container'], info['encrypted'], info['methods'], self.archives.guessed_engine(info)),
                         ('iostore', ['a.pak'], ['Oodle', 'Zlib', 'Zstd'], 'GAME_UE5_4'))
        (self.temp / 'c.pak').write_bytes(b'not an archive')
        self.assertIsNone(self.archives.read_pak(self.temp / 'c.pak'))

    def test_the_branch_name_in_an_executable_gives_the_engine(self):
        for branch, engine in (('++UE5+Release-5.3', 'GAME_UE5_3'), ('++UE4+Release-4.27', 'GAME_UE4_27'),
                               ('++UE5+Release-5.10', 'GAME_UE5_10'), ('++Fortnite+Release-30.00', '')):
            executable(self.temp / f'{len(branch)}{engine}.exe', branch)
            self.assertEqual(self.archives.branch_engine(self.temp / f'{len(branch)}{engine}.exe'), engine, branch)
        self.assertEqual(self.archives.branch_engine(self.temp / 'missing.exe'), '')
        self.assertEqual(self.archives.engine_label('GAME_UE4_27'), 'Unreal Engine 4.27')


class Scan(Package):
    def test_scan_selection_preview_and_import(self):
        from asset_discovery import load_catalog, selection
        mappings = Path(self.temp.name) / 'Hero.usmap'
        mappings.write_bytes(b'usmap')
        path, catalog = self.discover(mappings=str(mappings))
        command, source, _ = CALLS[0]
        self.assertEqual((command, source['root'], source['engine'], source['mappings'], source['aesKey']),
                         ('scan', str(self.paks), 'GAME_UE4_26', str(mappings), ''))
        self.assertEqual((catalog['engine'], catalog['game'], catalog['schema']), ('unreal', 'unreal', self.module.CATALOG_SCHEMA))
        self.assertIn('3 package headers could not be read', catalog['warnings'])
        self.assertIn('1 animations name no skeleton and are left out.', catalog['warnings'])
        people = {c['id']: c for c in catalog['characters']}
        self.assertEqual(list(people), [PROP, SKELETON])
        hero = people[SKELETON]
        self.assertEqual((hero['character'], hero['model'], hero['count'], hero['ready'], hero['archives'], hero['inventoried']),
                         ('Hero', BODY, 2, 1, ['Hero-Windows.pak'], True))
        run = next(c for c in catalog['clips'] if c['id'] == RUN)
        self.assertEqual((run['frameCount'], run['frameRate'], run['rootMotion'], run['characterKey']), (31, 30.0, True, SKELETON))

        catalog = load_catalog(path, self.game, True)
        with self.assertRaisesRegex(ValueError, 'no frames'):
            selection(catalog, IDLE)
        chosen = selection(catalog, RUN)
        self.assertEqual((chosen['engine'], chosen['game'], chosen['animation'], chosen['model']), ('unreal', 'unreal', RUN, BODY))
        self.assertEqual([(p['name'], p['role'], p['selected']) for p in chosen['parts']],
                         [('SK_Hero', 'Body', True), ('SK_Hero_Head', 'Head', False)])

        ctx = self.engine.context(self.cache)
        motion = self.module.preview(chosen, ctx)
        self.assertEqual((motion['source']['engine'], motion['source']['game'], motion['member'], motion['rootMotion']),
                         ('unreal', 'unreal', RUN, None))
        self.assertEqual(CALLS[-1][2][0], RUN)
        self.assertEqual(CALLS[-1][2][-2:], ['--mesh', BODY])
        self.assertEqual(self.module.preview_key(chosen, ctx), self.module.preview_key(dict(chosen), ctx))

        request = dict(assetClip=RUN, includeCharacter=True, models=[BODY, HEAD], game='auto')
        temp = Path(self.temp.name) / 'job'
        temp.mkdir()
        motion_path, character_args, report = self.engine.prepare(request, path, catalog, temp, self.notify)
        self.assertEqual(character_args[0], '--character-manifest')
        manifest = json.loads(Path(character_args[1]).read_text(encoding='utf-8'))
        self.assertEqual((manifest['version'], manifest['basis'], manifest['unitScale'], manifest['texture_count']), (5, UNREAL, 0.01, 1))
        self.assertEqual([(m['name'], m['role'], m['source']) for m in manifest['models']], [('SK_Hero', 'Body', BODY), ('SK_Hero_Head', 'Head', HEAD)])
        material = manifest['models'][0]['materials'][0]
        self.assertEqual((material['name'], material['alpha'], material['albedo']['packedAlpha'], material['normal']), ('M_Hero', True, False, None))
        self.assertEqual([s['semantic'] for s in material['samplers']], ['albedo', 'normal'])
        with np.load(manifest['models'][0]['data'], allow_pickle=False) as arrays:
            self.assertEqual((list(arrays['bone_names']), arrays['bone_quaternions'].shape, list(arrays['material_names'])),
                             (['root', 'pelvis'], (2, 4), ['M_Hero']))
        self.assertEqual((report['parts'], report['game'], request['animation'], request['game']), (2, 'Unreal Engine game', RUN, 'unreal'))
        self.assertIn('2 animated bones are not in the mesh: ik_foot_l, ik_foot_r', report['warnings'])
        self.assertIn('Texture T_Hero_N could not be decoded: unsupported format', report['warnings'])
        self.assertEqual(json.loads(motion_path.read_text(encoding='utf-8'))['source']['engine'], 'unreal')

    def test_a_second_scan_reuses_the_first_until_the_archives_change(self):
        self.discover()
        self.discover()
        self.assertEqual([c[0] for c in CALLS], ['scan'])
        pak(self.paks / 'Hero-Windows.pak', methods=('Zlib', 'Oodle'))
        self.discover()
        self.assertEqual([c[0] for c in CALLS], ['scan', 'scan'])

    def test_each_set_of_options_has_its_own_scan(self):
        first, _ = self.discover(engineVersion='GAME_UE4_26')
        second, catalog = self.discover(engineVersion='GAME_UE4_25')
        self.assertNotEqual(first, second)
        self.assertEqual((catalog['engineVersion'], CALLS[-1][1]['engine']), ('GAME_UE4_25', 'GAME_UE4_25'))
        with self.assertRaisesRegex(ValueError, 'mappings file was not found'):
            self.discover(mappings=str(Path(self.temp.name) / 'missing.usmap'))

    def test_a_scan_that_links_no_animation_to_a_skeleton_says_why(self):
        document = scan_document()
        document['animations'] = [dict(a, skeleton='') for a in document['animations']]
        unread = 'NOTE 4 of 4 package headers could not be read, so their assets name no skeleton. 4 of them fail like this: '
        for engine, reason, advice in (('GAME_UE5_6', "Package has unversioned properties but mapping file is missing, can't serialize",
                                        r'choose its mappings file \(\.usmap\)'),
                                       ('GAME_UE5_5', 'Read size is bigger than remaining archive length', 'choose it under Engine version')):
            with mock.patch(f'{__name__}.scan_document', return_value=document), \
                    mock.patch(f'{__name__}.SCAN_PRINTED', unread + reason + '\n'), \
                    self.assertRaisesRegex(ValueError, advice):
                self.discover(engineVersion=engine)

    def test_decoder_errors_say_what_to_do(self):
        self.assertIn('choose its mappings file (.usmap)',
                      self.module.hint('decode failed: Package has unversioned properties but mapping file is missing'))
        self.assertIn('Engine version', self.module.hint('decode failed: Failed to deserialize FPackageFileSummary'))
        self.assertEqual(self.module.hint('decode failed: Run uses ACL compression'), 'decode failed: Run uses ACL compression')

    def test_character_labels_drop_skeleton_affixes(self):
        for path, label in ((SKELETON, 'Hero'), ('/Game/M/UE4_Mannequin_Skeleton.UE4_Mannequin_Skeleton', 'UE4_Mannequin'),
                            ('/Game/M/SK_Mannequin.SK_Mannequin', 'Mannequin'), ('/Game/M/Skeleton.Skeleton', 'Skeleton')):
            self.assertEqual(self.module.short_name(path), label, path)


if __name__ == '__main__':
    unittest.main()
