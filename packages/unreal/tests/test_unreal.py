"""The Unreal package through the bridge's package API, with a stand-in decoder and made-up archives.

Run from the bridge folder: python -m unittest discover -s packages/unreal/tests
"""
import importlib
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
# A made-up dwarf in Deep Rock Galactic's folders, so the game's own part rules in package.json apply to it.
DWARF = '/Game/CharacterStructure/Rig/3P_Dwarf_Rig_Skeleton.3P_Dwarf_Rig_Skeleton'
DWARF_RUN = '/Game/Character/Animations/Run.Run'
RIG = '/Game/CharacterStructure/Rig/SK_3P_Dwarf_Rig.SK_3P_Dwarf_Rig'
STUBBLE = '/Game/CharacterStructure/Rig/Facial_Hair_Rig/SK_Stubble_Test.SK_Stubble_Test'
ARMOR = '/Game/Character/Vanity2/Armor/SK_Vanity_ArmorDriller001new.SK_Vanity_ArmorDriller001new'
ARMOR_BEARD = '/Game/Character/Vanity2/Armor/SK_Vanity_ArmorDriller001new_Beard.SK_Vanity_ArmorDriller001new_Beard'
DWARF_HEAD = '/Game/Character/Vanity2/Heads/SK_Vanity_Head001.SK_Vanity_Head001'
BROWS = '/Game/Character/Vanity2/Eyebrows/SK_Vanity_Eyebrows001_FuzzySlugs.SK_Vanity_Eyebrows001_FuzzySlugs'
RIFLE = '/Game/WeaponsNTools/AssaultRifle/SK_AssaultRifle_B.SK_AssaultRifle_B'
DRILL = '/Game/WeaponsNTools/Drills/SK_Drill_Left_B.SK_Drill_Left_B'
SKIN = '/Game/WeaponsNTools/AssaultRifle/Skins/SK_AssaultRifle_Skin_Test.SK_AssaultRifle_Skin_Test'
SENTRY = '/Game/WeaponsNTools/SentryGun/SK_SentryGun.SK_SentryGun'
SUIT_MATERIAL = '/Game/Character/Vanity2/Armor/Paintjobs_ArmorDefaults/M_Test_Suit.M_Test_Suit'
ITEMS = '/Game/Character/Vanity2/Armor/InUse/VAN_Armor_Test'
DWARF_BONES = ['Dwarf_RootBone', 'Dwarf_Pelvis', 'Dwarf_ArmRHand', 'Dwarf_HandR_Attach', 'Dwarf_ArmLHand', 'Dwarf_HandL_Attach']


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


def drg_document():
    """A scan of the made-up dwarf: its rig, armor, head and eyebrows, and weapons on skeletons of their own."""
    def mesh(path, skeleton=DWARF):
        return dict(path=path, name=path.rsplit('.', 1)[-1], skeleton=skeleton, archive='FSD-WinGDK.pak')
    return dict(scan_document(), project='FSD', engine='GAME_UE4_27',
                skeletons=[dict(path=DWARF, name='3P_Dwarf_Rig_Skeleton', archive='FSD-WinGDK.pak')],
                animations=[dict(path=DWARF_RUN, name='Run', skeleton=DWARF, archive='FSD-WinGDK.pak', frames=31, length=1.0)],
                meshes=[mesh(m) for m in (RIG, STUBBLE, ARMOR, ARMOR_BEARD, DWARF_HEAD, BROWS)]
                       + [mesh(m, m.rsplit('/', 1)[0] + '/SK_Weapon_Skeleton.SK_Weapon_Skeleton') for m in (RIFLE, DRILL, SKIN, SENTRY)])


def drg_item(path):
    """An item as the decoder dumps it: an armor has its name, a mesh for each armor kind and the material for empty slots."""
    if path.startswith(ITEMS):
        meshes = [dict(Key='EArmorMeshType::Default', Value=dict(AssetPathName=ARMOR, SubPathString='')),
                  dict(Key='EArmorMeshType::DefaultBeardCompatible', Value=dict(AssetPathName=ARMOR_BEARD, SubPathString=''))]
        return dict(Type='ArmorVanityItem', Properties=dict(TPArmorMesh=meshes, ItemName=dict(SourceString='Test Suit'),
                                                            MaterialOverride=dict(AssetPathName=SUIT_MATERIAL, SubPathString='')))
    return dict(Type='HeadVanityItem', Properties=dict(Mesh=dict(AssetPathName=DWARF_HEAD), ItemName=dict(SourceString='Test Head')))


def write_mesh(stem, name, textures, bone_names=('root', 'pelvis')):
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
    bones = [dict(index=index, name=bone, parent=index - 1, translation=[0, 0, 95 if index else 0], rotation=[0, 0, 0, 1],
                  scale=[1, 1, 1]) for index, bone in enumerate(bone_names)]
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
        Path(args[2]).write_text(json.dumps(drg_document() if 'FSD' in CALLS[-1][1]['root'] else scan_document()), encoding='utf-8')
        return SCAN_PRINTED
    if command == 'list':
        return f'{ITEMS}\n/Game/Character/Vanity2/Heads/InUse/VAN_Head_Test\n/Game/Character/Vanity2/Heads/T_Head_Test\n'
    if command == 'dump':
        objects = [dict(path=str(a), object=drg_item(str(a)), error='') for a in args[2:]]
        return json.dumps(objects if len(objects) > 1 else objects[0]['object'])
    if command == 'decode':
        Path(args[3]).write_text(json.dumps(unreal_motion(str(args[2]))), encoding='utf-8')
        return 'NOTE 2 animated bones are not in the mesh: ik_foot_l, ik_foot_r\n'
    if command == 'mesh':
        out = Path(args[2])
        textures = out / 'textures'
        textures.mkdir(parents=True, exist_ok=True)
        meshes = []
        for index, argument in enumerate(args[3:]):
            # MESH|MATERIAL names the material for the mesh's empty slots.
            path = str(argument).split('|')[0]
            name = path.rsplit('.', 1)[-1]
            stem = out / f'{index:02d}_{name}'
            write_mesh(stem, name, textures, DWARF_BONES if '/Game/Character' in path and '/Characters/' not in path else ('root', 'pelvis'))
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
        # Resolved, as the bridge resolves the paths it stores: the temporary folder can be named in its 8.3 short
        # form (C:\Users\RUNNER~1 on the release runner).
        temp = Path(self.temp.name).resolve()
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
        self.temp = Path(temp.name).resolve()
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



class DeepRockGalactic(Package):
    """Deep Rock Galactic's dwarves: parts from the game's items, weapons on joints, and the materials of its items."""

    def setUp(self):
        super().setUp()
        self.drg = Path(self.temp.name).resolve() / 'Deep Rock Galactic'
        pak(self.drg / 'Content' / 'FSD' / 'Content' / 'Paks' / 'FSD-WinGDK.pak')
        (self.drg / 'Content' / 'Engine').mkdir(parents=True)
        self.characters = importlib.import_module(self.module.__name__ + '.characters')

    def prepare(self, models, attachments=None):
        temp = Path(tempfile.mkdtemp(dir=self.temp.name))
        request = dict(assetClip=DWARF_RUN, includeCharacter=True, models=models, game='auto', weaponAttachments=attachments or {})
        _, character_args, report = self.engine.prepare(request, self.path, self.catalog, temp, self.notify)
        return json.loads(Path(character_args[1]).read_text(encoding='utf-8')), report

    def test_parts_come_with_item_names_notes_and_weapons(self):
        from asset_discovery import load_catalog, selection
        path, catalog = self.discover(self.drg)
        self.assertEqual(catalog['game'], 'deep_rock_galactic')
        self.assertEqual([(c[0], c[2]) for c in CALLS[1:]], [('list', ['/Game/Character/Vanity2']),
                                                             ('dump', [f'{ITEMS}.VAN_Armor_Test',
                                                                       '/Game/Character/Vanity2/Heads/InUse/VAN_Head_Test.VAN_Head_Test'])])
        items = json.loads((Path(catalog['work']) / 'items.json').read_text(encoding='utf-8'))['items']
        self.assertEqual(items[ARMOR_BEARD], dict(item='Test Suit', material=SUIT_MATERIAL, kind='EArmorMeshType::DefaultBeardCompatible',
                                                  asset=f'{ITEMS}.VAN_Armor_Test'))
        self.assertEqual(items[DWARF_HEAD]['item'], 'Test Head')
        parts = selection(load_catalog(path, self.drg, True), DWARF_RUN)['parts']
        self.assertEqual([(p['name'], p['role'], p.get('note', ''), p['selected']) for p in parts], [
            ('SK_Stubble_Test', 'Hair', 'stubble', False),
            ('SK_3P_Dwarf_Rig', 'Body', 'with head, no armor', False),
            ('SK_Vanity_ArmorDriller001new · Test Suit', 'Body', 'without head', True),
            ('SK_Vanity_ArmorDriller001new_Beard · Test Suit', 'Body', 'without head, cut out for a beard', False),
            ('SK_Vanity_Head001 · Test Head', 'Head', '', True),
            ('SK_Vanity_Eyebrows001_FuzzySlugs', 'Hair', 'eyebrows', True),
            ('SK_AssaultRifle_B · Assault Rifle', 'Weapon', '', False),
            ('SK_Drill_Left_B · Drills', 'Weapon', '', False)])
        # An item's material, else the folder's: Deep Rock Galactic colors hair with the hair color the player picks.
        self.assertEqual((parts[2]['material'], parts[5]['material'].rsplit('.', 1)[-1]), (SUIT_MATERIAL, 'M_HairColor_Brown03'))
        rifle, drill = parts[-2:]
        self.assertEqual([j['id'] for j in rifle['joints']][:3], ['Dwarf_HandR_Attach', 'Dwarf_HandL_Attach', 'Dwarf_BackHigh_Attach'])
        self.assertEqual((rifle['joint'], drill['joint']), ('Dwarf_HandR_Attach', 'Dwarf_HandL_Attach'))
        # A single item comes from the decoder without the list around it.
        ctx = self.engine.context(self.cache)
        index = json.loads((Path(catalog['work']) / 'index.json').read_text(encoding='utf-8'))
        single = self.module.read_items(catalog, index, dict(folders=['/Game/Character/Vanity2'], prefix='VAN_'), ctx, batch=1)
        self.assertEqual(single['items'], items)

    def test_weapons_hang_on_joints_and_armor_gets_its_item_material(self):
        self.path, self.catalog = self.discover(self.drg)
        # The clip plays on the first chosen model that is not a weapon.
        manifest, report = self.prepare([RIFLE, ARMOR, DWARF_HEAD, DRILL], {DRILL: 'Dwarf_BackHigh_Attach'})
        decode = next(c for c in reversed(CALLS) if c[0] == 'decode')
        self.assertEqual(decode[2][-2:], ['--mesh', ARMOR])
        mesh = next(c for c in reversed(CALLS) if c[0] == 'mesh')
        self.assertEqual(mesh[2][1:], [RIFLE, f'{ARMOR}|{SUIT_MATERIAL}', DWARF_HEAD, DRILL])
        self.assertEqual([(m['name'], m['role'], m['attachment']) for m in manifest['models']], [
            ('SK_AssaultRifle_B', 'Weapon', dict(kind='joint', bone='Dwarf_HandR_Attach')),
            ('SK_Vanity_ArmorDriller001new', 'Body', None), ('SK_Vanity_Head001', 'Head', None)])
        with np.load(manifest['models'][0]['data'], allow_pickle=False) as arrays:
            self.assertEqual(list(arrays['bone_names']), ['SK_AssaultRifle_B_root', 'SK_AssaultRifle_B_pelvis'])
        self.assertIn('SK_Drill_Left_B: the character has no joint Dwarf_BackHigh_Attach; the weapon is left out.', report['warnings'])
        self.assertEqual(report['parts'], 3)
        self.assertFalse(any('has a head' in w for w in report['warnings']))

    def test_a_character_without_a_head_says_so(self):
        self.path, self.catalog = self.discover(self.drg)
        _, report = self.prepare([ARMOR, BROWS])
        self.assertIn('None of the chosen parts has a head. Tick a Head part, or a body marked "with head".', report['warnings'])
        _, report = self.prepare([RIG])
        self.assertFalse(any('has a head' in w for w in report['warnings']))

    def test_masks_whose_names_spell_a_layout_give_metalness_and_roughness(self):
        layout = self.characters.mask_layout
        self.assertEqual(layout('ORM'), dict(G='roughness', B='metalness'))
        self.assertEqual(layout('', 'T_Hero_MRA'), dict(R='metalness', G='roughness'))
        self.assertEqual(layout('SpecularMasks', 'T_Hero_SpecularMasks'), {})
        self.assertEqual(layout('PM_SpecularMasks', 'T_Hero_D'), {})
        textures = Path(self.temp.name)
        for name in ('T_Base_Tiger01', 'T_Hero_MRA'):
            (textures / f'{name}.png').write_bytes(b'png')
        material = dict(slot='M_Armor', path='/Game/M_Armor.M_Armor', color=[0.5, 0.25, 0.125, 1], blendMode='BLEND_Opaque',
                        albedo=dict(texture='/Game/T_Base_Tiger01.T_Base_Tiger01', file=str(textures / 'T_Base_Tiger01.png'),
                                    parameter='Texture'),
                        mask=dict(texture='/Game/T_Hero_MRA.T_Hero_MRA', file=str(textures / 'T_Hero_MRA.png'), srgb=False,
                                  parameter='Masks'))
        spec = self.characters.material_spec(material, games.profile('deep_rock_galactic'))
        # Deep Rock Galactic lays tiling patterns over a tint: the tint is the color, the pattern no base color.
        self.assertEqual((spec['albedo'], spec['color']), (None, [0.5, 0.25, 0.125]))
        self.assertEqual((spec['metalness']['channel'], spec['roughness']['channel'], spec['roughness']['linear']), ('R', 'G', True))
        self.assertEqual(spec['metalness']['stem'], 'T_Hero_MRA')
        spec = self.characters.material_spec(material, games.profile('unreal'))
        self.assertEqual(spec['albedo']['stem'], 'T_Base_Tiger01')

    def test_dwarf_bones_have_names_the_matcher_knows(self):
        spec = importlib.util.spec_from_file_location('retarget_mapping', BRIDGE / 'blender_addon/sekiro_retarget/mapping.py')
        mapping = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mapping)
        alias = mapping.alias_rule(games.profile('deep_rock_galactic').bones)
        self.assertEqual([alias(n) for n in ('Dwarf_Pelvis', 'Dwarf_ArmLShoulder', 'Dwarf_ArmR21', 'Dwarf_ArmLDigit02', 'Dwarf_ArmRDigit010',
                                             'Dwarf_ArmLDigit019', 'Dwarf_LegRHeel', 'Dwarf_HandR_Attach', 'Dwarf_BackHigh_Attach')],
                         ['Pelvis', 'L_Clavicle', 'R_Forearm', 'L_Thumb2', 'R_Middle3', 'L_Pinky4', 'R_Foot', 'R_Weapon', ''])


if __name__ == '__main__':
    unittest.main()
