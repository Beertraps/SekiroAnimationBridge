"""The DOOM Eternal package's parts, weapons, looks and materials, with made-up decls, models and skeletons.

Run from the bridge folder: python -m unittest discover -s packages/doom_eternal/tests
"""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

BRIDGE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BRIDGE / 'standalone'), str(BRIDGE / 'blender_addon' / 'sekiro_retarget')]
import games
from games import packages

BRUTE = 'md6/characters/monsters/brute/base/assets/mesh/brute.md6mesh'
BRUTE_SKELETON = 'md6/characters/monsters/brute/base/assets/mesh/brute.md6skl'
GUN = 'md6/objects/ai_props/brute_gun/assets/mesh/brutegun.md6mesh'
BRUTE_DECL = 'generated/decls/md6def/md6def/characters/monsters/brute/base/brute.md6.decl'


def decl(mesh, looks=(), gore=(), props=()):
    """An md6def decl laid out as the game's: tabs, CRLF line ends, a props block and a meshKits block.

    props: (prop, visible, [(tag, parent, translation, rotation)])."""
    lines = ['{', '\tinit {', f'\t\tmesh "{mesh}"', '\t}', '\tprops {', '\t\tprop "_info" {', '\t\t\tvisibleByDefault false',
             '\t\t\ttag "focus" {', '\t\t\t\ttrans ( 0 0 1.5 )', '\t\t\t\trot ( 0 0 0 1 )', '\t\t\t\tparent "origin"', '\t\t\t}',
             '\t\t}']
    for prop, visible, tags in props:
        lines += [f'\t\tprop "{prop}" {{', f"\t\t\tvisibleByDefault {'true' if visible else 'false'}"]
        for tag, parent, trans, rot in tags:
            lines += [f'\t\t\ttag "{tag}" {{', f"\t\t\t\ttrans ( {' '.join(map(str, trans))} )",
                      f"\t\t\t\trot ( {' '.join(map(str, rot))} )", f'\t\t\t\tparent "{parent}"', '\t\t\t}']
        lines.append('\t\t}')
    lines += ['\t}', '\tmeshKits {', '\t\tHeads 0 {', '\t\t}', f'\t\tGore {len(gore)} {{']
    lines += [f'\t\t\t"{name}" = "{name}"' for name in gore]
    lines += ['\t\t}', f'\t\tBody {len(looks)} {{']
    lines += [f'\t\t\t"{name}" = "{" ".join(meshes)}"' for name, meshes in looks]
    lines += ['\t\t}', '\t}', '}']
    return '\r\n'.join(lines)


def skeleton(md6, names, parents, translations=None, rotations=None):
    count = len(names)
    rotations = np.tile([0.0, 0, 0, 1], (count, 1)) if rotations is None else np.asarray(rotations, float)
    translations = np.zeros((count, 3)) if translations is None else np.asarray(translations, float)
    return md6.Skeleton(list(names), list(parents), rotations, np.ones((count, 3)), translations)


class Package(unittest.TestCase):
    """The DOOM Eternal package from this folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name).resolve() / 'cache'
        self.cache.mkdir()
        for name, value in (('ROOTS', [BRIDGE / 'packages']), ('CACHE', self.cache)):
            patcher = mock.patch.object(packages, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(games.reload)
        games.reload()
        self.module = games.adapter('doom_eternal').module
        self.characters = importlib.import_module('bridge_packages.doom_eternal.characters')
        self.models = importlib.import_module('bridge_packages.doom_eternal.models')
        self.md6 = importlib.import_module('bridge_packages.doom_eternal.md6')
        self.profile = games.profile('doom_eternal')
        self.ctx = SimpleNamespace(cache=str(self.cache), notify=lambda *args, **kwargs: None)


class Definitions(Package):
    def test_a_decl_gives_its_looks_gore_and_tagged_props(self):
        text = decl(BRUTE, looks=[('Base', ['body_low_base', 'eyes_low_base']), ('Shield', ['body_low_base', 'shield_base'])],
                    gore=['arm_chunk_lf_base'],
                    props=[('md6def/objects/ai_props/brutegun.md6', False,
                            [('left_hand', 'weapon_part01_lf', (0, 0, 0), (0, 0, 0, 1)),
                             ('holster', 'gunholster_part01_lf', (0.1, 0, -0.2), (0, 0.5, 0, 0.866025))])])
        found = self.models.read_md6def(text)
        self.assertEqual(found['mesh'], BRUTE)
        self.assertEqual(found['looks'], [['Base', ['body_low_base', 'eyes_low_base']], ['Shield', ['body_low_base', 'shield_base']]])
        self.assertEqual(found['gore'], ['arm_chunk_lf_base'])
        self.assertEqual([p['prop'] for p in found['props']], ['md6def/objects/ai_props/brutegun.md6'])
        holster = found['props'][0]['tags'][1]
        self.assertEqual((holster['id'], holster['bone'], holster['translation'], holster['rotation']),
                         ('holster', 'gunholster_part01_lf', [0.1, 0.0, -0.2], [0.0, 0.5, 0.0, 0.866025]))
        self.assertEqual(self.models.prop_decls('md6def/objects/ai_props/brutegun.md6')[0],
                         'generated/decls/md6def/md6def/objects/ai_props/brutegun.md6.decl')
        self.assertEqual(self.models.mesh_group('body_low_base$1'), 'body_low_base')

    def test_weapons_are_props_that_are_models_of_their_own(self):
        texts = {
            BRUTE_DECL: decl(BRUTE, props=[
                ('md6def/objects/ai_props/brutegun.md6', True, [('left_hand', 'weapon_part01_lf', (0, 0, 0), (0, 0, 0, 1))]),
                # An effect prop and a stand-in that only carries tags are not weapons.
                ('md6def/fx/brute_glow.md6', True, [('glow', 'head_part01_md', (0, 0, 0), (0, 0, 0, 1))]),
                ('md6def/objects/ai_props/sync.md6', False, [('sync', 'origin', (0, 0, 0), (0, 0, 0, 1))])]),
            # A variant decl of the same model loses to the decl named after the model.
            'generated/decls/md6def/md6def/characters/monsters/brute/base/brute_darklord.md6.decl': decl(BRUTE, looks=[('Dark', ['x'])]),
            'generated/decls/md6def/md6def/objects/ai_props/brutegun.md6.decl': decl(GUN),
            'generated/decls/md6def/md6def/fx/brute_glow.md6.decl': decl('md6/fx/glow.md6mesh'),
            'generated/decls/md6def/md6def/objects/ai_props/sync.md6.decl': decl('md6/objects/ai_props/syncentity2.md6mesh')}
        entries = {('rs_streamfile', name): name for name in texts}
        entries.update({('baseModel', path): path for path in (BRUTE, GUN, 'md6/fx/glow.md6mesh',
                                                               'md6/objects/ai_props/syncentity2.md6mesh')})
        game = SimpleNamespace(read=lambda entry: texts[entry].encode())
        found = self.module.definitions(game, entries, self.ctx, 'test')
        self.assertEqual(found[BRUTE]['decl'], BRUTE_DECL)
        self.assertEqual([w['model'] for w in found[BRUTE]['weapons']], [GUN])
        self.assertTrue(found[BRUTE]['weapons'][0]['visible'])
        self.assertTrue((self.cache / 'md6defs-test.json').is_file())


class Parts(Package):
    def setUp(self):
        super().setUp()
        self.weapon = dict(model=GUN, visible=False, tags=[
            dict(id='left_hand', bone='weapon_part01_lf', translation=[0, 0, 0], rotation=[0, 0, 0, 1]),
            dict(id='holster', bone='gunholster_part01_lf', translation=[0, 0, 0], rotation=[0, 0, 0, 1]),
            dict(id='world', bone='origin', translation=[0, 0, 0], rotation=[0, 0, 0, 1]),
            dict(id='tail', bone='tail_part01_md', translation=[0, 0, 0], rotation=[0, 0, 0, 1])])
        self.defs = {BRUTE: dict(looks=[['Base', ['body']], ['Shield', ['body', 'shield']]], gore=[], weapons=[self.weapon])}
        names = ['origin', 'hips_part01_md', 'weapon_part01_lf', 'gunholster_part01_lf']
        self.skeleton = skeleton(self.md6, names, [-1, 0, 1, 1])
        self.game = SimpleNamespace(read=lambda entry: b'')
        self.entries = {('skeleton', BRUTE_SKELETON): 'skeleton'}

    def parts(self):
        other = 'md6/customization/characters/monsters/brute/set2/base/assets/mesh/brute_set2.md6mesh'
        owners = {BRUTE: BRUTE_SKELETON, other: BRUTE_SKELETON, 'md6/other.md6mesh': 'md6/other.md6skl'}
        notes = {BRUTE: {'Base': 'with head', 'Shield': 'with head'}, other: {'': 'without head'}}
        with mock.patch.object(self.module, 'game_of', return_value=self.game), \
                mock.patch.object(self.module, 'entries_of', return_value=self.entries), \
                mock.patch.object(self.module, 'model_owners', return_value=owners), \
                mock.patch.object(self.module, 'definitions', return_value=self.defs), \
                mock.patch.object(self.characters, 'head_notes', side_effect=lambda game, entries, path, definition: notes[path]), \
                mock.patch.object(self.md6, 'read_skeleton', return_value=self.skeleton):
            return self.module.model_parts(dict(folder='game', sourceKey='test'), BRUTE_SKELETON, self.ctx)

    def test_each_look_is_a_part_and_the_first_one_is_chosen(self):
        parts = self.parts()
        bodies = [p for p in parts if p['role'] == 'Body']
        self.assertEqual([p['path'] for p in bodies][:2], [f'{BRUTE}#Base', f'{BRUTE}#Shield'])
        self.assertEqual([p['name'] for p in bodies], ['brute · Base', 'brute · Shield', 'brute_set2 · set2'])
        self.assertEqual([p['note'] for p in bodies], ['with head', 'with head', 'without head'])
        self.assertEqual([p['selected'] for p in parts], [True, False, False, False])

    def test_a_weapon_offers_the_tags_on_joints_of_the_character(self):
        weapon = self.parts()[-1]
        self.assertEqual((weapon['role'], weapon['path'], weapon['name'], weapon['joint']), ('Weapon', GUN, 'brutegun', 'left_hand'))
        # A tag on origin only places the gun in the world; one on a joint the skeleton lacks cannot hold it.
        self.assertEqual(weapon['joints'], [dict(id='left_hand', label='Left hand · weapon_part01_lf'),
                                            dict(id='holster', label='Holster · gunholster_part01_lf')])
        self.assertFalse(weapon['selected'])
        self.assertEqual(weapon['note'], 'hidden until the game shows it')

    def test_the_chosen_joint_falls_back_to_the_default(self):
        weapon = self.parts()[-1]
        picked = self.module.chosen_joints(dict(weaponAttachments={GUN: 'holster'}), [weapon])
        self.assertEqual(picked[GUN]['bone'], 'gunholster_part01_lf')
        picked = self.module.chosen_joints(dict(weaponAttachments={GUN: 'world'}), [weapon])
        self.assertEqual(picked[GUN]['bone'], 'weapon_part01_lf')

    def test_bone_names_pair_the_humanik_skeletons(self):
        import mapping
        alias = mapping.alias_rule(self.profile.bones)
        self.assertEqual([mapping.semantic(alias(n)) for n in ('leftclav', 'rightshoulder', 'leftweapon', 'arm_upper_lf')],
                         [('L', 'clavicle'), ('R', 'clavicle'), ('L', 'weapon'), ('L', 'upperarm')])


class Looks(Package):
    def model(self, *names):
        return SimpleNamespace(meshes=[SimpleNamespace(name=name) for name in names])

    def test_a_look_keeps_its_meshes_and_drops_the_gore(self):
        model = self.model('body_low_base$0', 'body_low_base$1', 'shield_base', 'arm_chunk_lf_base')
        definition = dict(looks=[['Base', ['body_low_base']], ['Shield', ['body_low_base', 'shield_base']]],
                          gore=['arm_chunk_lf_base'])
        self.assertEqual(self.characters.chosen_meshes(model, definition), [True, True, False, False])
        self.assertEqual(self.characters.chosen_meshes(model, definition, 'Shield'), [True, True, True, False])
        self.assertEqual(self.characters.chosen_meshes(model, dict(looks=[], gore=['arm_chunk_lf_base'])),
                         [True, True, True, False])
        self.assertEqual(self.characters.chosen_meshes(model, None), [True, True, True, True])

    def test_a_body_holds_the_head_when_enough_vertices_follow_it(self):
        bones = skeleton(self.md6, ['origin', 'hips_part01_md', 'head_part01_md', 'jaw_part01_md', 'arm_hand_lf'],
                         [-1, 0, 1, 2, 1])
        below = self.characters.head_joints(bones)
        self.assertEqual(below, {2, 3})
        joints = np.zeros((20, 4), int)
        weights = np.tile([1.0, 0, 0, 0], (20, 1))
        joints[:2, 0] = 3
        self.assertTrue(self.characters.holds_head(below, [dict(joints=joints, weights=weights)]))
        self.assertFalse(self.characters.holds_head(below, [dict(joints=np.zeros((20, 4), int), weights=weights)]))
        self.assertIsNone(self.characters.holds_head(set(), [dict(joints=joints, weights=weights)]))


def worlds(characters, bones):
    """Each bone's rest matrix in model space."""
    found = []
    for i, parent in enumerate(bones.parents):
        local = np.eye(4)
        local[:3, :3] = characters.rotation_matrix(bones.rotations[i])
        local[:3, 3] = bones.translations[i]
        found.append(found[parent] @ local if parent >= 0 else local)
    return found


class Weapons(Package):
    def test_a_tag_moves_the_weapon_and_names_its_bones(self):
        rotation = np.array([0.2, -0.5, 0.3, 0.8])
        rotation /= np.linalg.norm(rotation)
        tag = dict(id='holster', bone='gunholster_part01_lf', translation=[0.1, -0.25, 0.05], rotation=list(rotation))
        bones = skeleton(self.md6, ['origin', 'barrel'], [-1, 0], translations=[[0, 0, 0.1], [0.3, 0, 0]],
                         rotations=[[0, 0, 0.6, 0.8], [0, 0, 0, 1]])
        meshes = [dict(positions=np.array([[0.0, 0, 0], [1.0, 0, 0]]), normals=np.array([[1.0, 0, 0], [0, 0, 1.0]])), None]
        placed, moved = self.characters.on_tag(bones, meshes, tag, 'brutegun')
        self.assertEqual(placed.names, ['brutegun_origin', 'brutegun_barrel'])
        offset = np.eye(4)
        offset[:3, :3] = self.characters.rotation_matrix(rotation)
        offset[:3, 3] = tag['translation']
        for before, after in zip(worlds(self.characters, bones), worlds(self.characters, placed)):
            np.testing.assert_allclose(after, offset @ before, atol=1e-9)
        np.testing.assert_allclose(moved[0]['positions'], meshes[0]['positions'] @ offset[:3, :3].T + offset[:3, 3])
        np.testing.assert_allclose(moved[0]['normals'], meshes[0]['normals'] @ offset[:3, :3].T)
        self.assertIsNone(moved[1])


class Character(Package):
    """prepare_character with stand-ins for the archives: models, skeletons and geometry by name."""

    def setUp(self):
        super().setUp()
        body_names = ['origin', 'hips_part01_md', 'head_part01_md', 'weapon_part01_lf']
        self.skeletons = {'brute.md6skl': skeleton(self.md6, body_names, [-1, 0, 1, 1]),
                          'gun.md6skl': skeleton(self.md6, ['origin', 'barrel'], [-1, 0])}
        disk = [(0, 64, 64, 0)] * 5
        self.models_by_name = {
            BRUTE: SimpleNamespace(skeleton='brute.md6skl', disk=disk,
                                   meshes=[SimpleNamespace(name='body_low_base', material='models/brute/body'),
                                           SimpleNamespace(name='arm_chunk_lf_base', material='models/brute/gore')]),
            GUN: SimpleNamespace(skeleton='gun.md6skl', disk=disk,
                                 meshes=[SimpleNamespace(name='gun_base', material='models/brute/gun')])}
        self.entries = {(kind, name): SimpleNamespace(name=name, hash=index) for index, (kind, name) in enumerate(
            (('baseModel', BRUTE), ('baseModel', GUN), ('skeleton', 'brute.md6skl'), ('skeleton', 'gun.md6skl')))}
        self.game = SimpleNamespace(read=lambda entry: entry.name.encode(), stream=lambda key, size: b'geometry')
        self.head_vertices = 2

    def geometry(self, model, data, lod):
        meshes = []
        for mesh in model.meshes:
            joints = np.zeros((10, 4), int)
            joints[:self.head_vertices, 0] = 2
            meshes.append(dict(positions=np.random.default_rng(1).random((10, 3)), normals=np.tile([0, 0, 1.0], (10, 1)),
                               uvs=np.zeros((10, 2)), joints=joints, weights=np.tile([1.0, 0, 0, 0], (10, 1)),
                               faces=np.array([[0, 1, 2], [2, 3, 4]])))
        return meshes

    def prepare(self, joint='weapon_part01_lf'):
        tag = dict(id='left_hand', bone=joint, translation=[0, 0, 0], rotation=[0, 0, 0, 1])
        out = Path(self.temp.name) / 'character'
        models = self.models
        with mock.patch.object(models, 'read_model', side_effect=lambda data: self.models_by_name[data.decode()]), \
                mock.patch.object(models, 'read_geometry', side_effect=self.geometry), \
                mock.patch.object(models, 'read_material', side_effect=lambda read, name: models.Material(name, {}, [], '')), \
                mock.patch.object(self.md6, 'read_skeleton', side_effect=lambda data: self.skeletons[data.decode()]), \
                mock.patch.object(self.characters, 'convert_textures', return_value={}):
            path = self.characters.prepare_character(self.game, self.entries, [BRUTE, GUN], out, self.profile, self.ctx,
                                                     {GUN: tag}, {BRUTE: dict(looks=[], gore=['arm_chunk_lf_base'])})
        return json.loads(path.read_text(encoding='utf-8'))

    def test_a_weapon_hangs_on_its_joint_with_its_own_bone_names(self):
        manifest = self.prepare()
        body, gun = manifest['models']
        self.assertEqual((body['role'], body['attachment']), ('Body', None))
        self.assertEqual((gun['role'], gun['attachment']), ('Weapon', dict(kind='joint', bone='weapon_part01_lf')))
        self.assertEqual(list(np.load(gun['data'])['bone_names']), ['brutegun_origin', 'brutegun_barrel'])
        # The gore piece is left out of the body.
        self.assertEqual(body['stats']['vertices'], 10)
        self.assertEqual(manifest['warnings'], [])

    def test_a_missing_joint_and_a_missing_head_are_reported(self):
        self.head_vertices = 0
        manifest = self.prepare(joint='weapon_part01_rt')
        self.assertEqual([m['name'] for m in manifest['models']], ['brute'])
        self.assertEqual(manifest['warnings'], ['brutegun: the character has no joint weapon_part01_rt; the weapon is left out.',
                                                self.characters.HEAD_NOTICE])


class NormalMaps(Package):
    def image(self, green_down=False, flat=False):
        """A 64 x 64 normal map of the bumps h = 0.3 sin(rows) sin(columns), green up the image unless green_down."""
        rows, columns = np.mgrid[0:64, 0:64] * (2 * np.pi / 32)
        slope_rows = 0.3 * np.cos(rows) * np.sin(columns) * (0 if flat else 1)
        slope_columns = 0.3 * np.sin(rows) * np.cos(columns) * (0 if flat else 1)
        length = np.sqrt(slope_rows ** 2 + slope_columns ** 2 + 1)
        rgba = np.full((64, 64, 4), 255, np.uint8)
        rgba[..., 0] = np.round((-slope_columns / length + 1) * 127.5)
        rgba[..., 1] = np.round((slope_rows / length + 1) * 127.5)
        if green_down:
            rgba[..., 1] = 255 - rgba[..., 1]
        image = self.models.Image()
        image.kind, image.format, image.width, image.height, image.data = 3, self.models.RGBA8, 64, 64, rgba.tobytes()
        return image

    def test_the_reading_with_less_curl_wins(self):
        self.assertEqual(self.models.normal_convention(self.image()), 'opengl')
        self.assertEqual(self.models.normal_convention(self.image(green_down=True)), 'directx')

    def test_a_flat_or_undecoded_map_counts_as_opengl(self):
        self.assertEqual(self.models.normal_convention(self.image(flat=True)), 'opengl')
        image = self.image(green_down=True)
        image.format = self.models.BC5
        self.assertEqual(self.models.normal_convention(image), 'opengl')

    def test_the_measured_convention_reaches_the_material(self):
        material = self.models.Material('models/brute/gore', dict(normal='models/brute/gore_local.tga'), [], '')
        images = {'models/brute/gore_local.tga': dict(path='C:/textures/gore_local.png', stem='gore_local', convention='directx')}
        self.assertEqual(self.characters.material_spec(material, images, self.profile)['normal']['convention'], 'directx')


class Materials(Package):
    def images(self, *paths):
        return {path: dict(path=f'C:/textures/{Path(path).stem}.png', stem=Path(path).stem) for path in paths}

    def test_albedo_normal_and_glow(self):
        material = self.models.Material('models/brute/body', dict(
            albedo='models/brute/body.tga', normal='models/brute/body_n.tga', bloommaskmap='models/brute/body_e.tga',
            specular='models/brute/body_s.tga', smoothness='models/brute/body_g.tga'), ['template/character'], '')
        spec = self.characters.material_spec(material, self.images('models/brute/body.tga', 'models/brute/body_n.tga',
                                                                   'models/brute/body_e.tga'), self.profile)
        self.assertEqual((spec['alpha'], spec['albedo']['packedAlpha'], spec['albedo']['linear']), (False, True, False))
        self.assertEqual((spec['normal']['convention'], spec['normal']['linear']), ('opengl', True))
        self.assertEqual((spec['emissive']['stem'], spec['emissive']['linear']), ('body_e', False))
        # Specular colour and smoothness are not metalness or roughness, so the export gets neither.
        self.assertNotIn('metalness', spec)
        self.assertNotIn('roughness', spec)
        self.assertNotIn('opacityValue', spec)

    def test_alpha_test_cuts_out_and_constant_images_stay_out(self):
        material = self.models.Material('models/brute/hair', dict(
            albedo='models/brute/hair.tga', bloommaskmap='textures/system/constant_color/black_noalpha.tga'),
            ['template/hair'], 'alphatest true')
        spec = self.characters.material_spec(material, self.images('models/brute/hair.tga'), self.profile)
        self.assertEqual((spec['alpha'], spec['albedo']['packedAlpha'], spec['emissive']), (True, False, None))

    def test_glow_cards_and_eye_overlays_are_hidden(self):
        for name, templates, hidden in (('models/brute/axe_blade_effect', ['template/emissive'], True),
                                        ('art/kit/spear_blade_card_a', ['template/emissive'], True),
                                        ('models/brute/axe_blade', ['template/emissive_rt', 'template/emissive'], False),
                                        ('models/brute/brute_eye_occ', ['template/character'], True)):
            spec = self.characters.material_spec(self.models.Material(name, {}, templates, ''), {}, self.profile)
            self.assertEqual(spec.get('opacityValue') == 0.0, hidden, name)



class Additive(Package):
    """An additive md6 clip becomes an additive motion: its changes, and no change where a channel has no keys."""

    HAND = 'md6/characters/owned/base/motion/additive/hand.md6anim'
    SKELETON = 'md6/characters/owned/base/assets/mesh/owned.md6skl'

    def setUp(self):
        super().setUp()
        # The game binds the hand at scale 1.2, which the Blender skeleton takes out.
        self.skeleton = skeleton(self.md6, ['origin', 'hips_part01_md', 'hand'], [-1, 0, 1], [[0, 0, 0], [0, 0, 1], [0, .5, 0]])
        self.skeleton.scales[2] = 1.2
        self.turned = np.array([0, 0, np.sin(.25), np.cos(.25)])
        entry = SimpleNamespace(path=Path('gameresources.resources'), version=12)
        self.entries = {('anim', self.HAND): entry, ('skeleton', self.SKELETON): entry}
        self.ctx = SimpleNamespace(cache=str(self.cache), notify=lambda *args, **kwargs: None,
                                   profile=lambda game: self.profile)

    def patched(self, flags):
        keys = {'r': {2: ([0, 1], [np.array([0, 0, 0, 1.0]), self.turned])}, 's': {2: ([0], [np.array([2.0, 2, 2])])}, 't': {}}
        anim = self.md6.Animation(self.skeleton, 2, 30.0, keys)
        found = {self.HAND: [self.SKELETON, flags]}
        return [mock.patch.object(self.module, 'game_of', return_value=SimpleNamespace(read=lambda entry: b'')),
                mock.patch.object(self.module, 'entries_of', return_value=self.entries),
                mock.patch.object(self.module, 'owners', return_value=found),
                mock.patch.object(self.md6, 'read_skeleton', return_value=self.skeleton),
                mock.patch.object(self.md6, 'read_animation', return_value=(self.SKELETON, anim)),
                mock.patch.object(self.md6, 'read_info', return_value=(self.SKELETON, flags))]

    def motion(self, flags):
        notes = []
        patches = self.patched(flags)
        for patch in patches:
            patch.start()
        try:
            document = self.module.motion(dict(animation=self.HAND, skeleton=self.SKELETON, root='game', clipName='hand'),
                                          self.ctx, notes)
        finally:
            for patch in patches:
                patch.stop()
        return document, notes

    def test_an_additive_clip_holds_changes(self):
        document, notes = self.motion(0x41F)
        self.assertEqual(document['additive'], dict(space='separate'))
        self.assertIn(self.module.ADDITIVE_NOTE, notes)
        self.assertEqual(document['trackBoneIndices'], [2])
        first, second = (frame[0] for frame in document['frames'])
        # No translation keys: no change, where a normal clip would hold the rest offset.
        self.assertEqual(first['translation'], [0, 0, 0])
        self.assertEqual(first['rotation'], [0, 0, 0, 1])
        np.testing.assert_allclose(second['rotation'], self.turned, atol=1e-6)
        # A change of scale keeps its value: the bind scale that the Blender skeleton takes out cancels out of it.
        self.assertEqual(first['scale'], [2, 2, 2])

    def test_a_normal_clip_stays_as_it_was(self):
        document, notes = self.motion(0x41E)
        self.assertNotIn('additive', document)
        self.assertEqual(notes, [])
        first = document['frames'][0][0]
        self.assertEqual(first['translation'], [0, .5, 0])
        np.testing.assert_allclose(first['scale'], [2 / 1.2] * 3, atol=1e-6)

    def test_additive_clips_can_be_chosen(self):
        catalog = dict(folder='game', characters=[dict(id=self.SKELETON, name='Owned')], clips=[])
        patches = self.patched(0x41F)
        for patch in patches:
            patch.start()
        try:
            catalog = self.module.inventory(catalog, self.SKELETON, self.ctx)
        finally:
            for patch in patches:
                patch.stop()
        clip = catalog['clips'][0]
        self.assertEqual((clip['ready'], clip['issues'], catalog['characters'][0]['ready']), (True, [], 1))


if __name__ == '__main__':
    unittest.main()
