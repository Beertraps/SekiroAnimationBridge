"""Part clips written into weapon part binders in a mod folder, on owned BND4 binders built in memory with Soulstruct."""
import json
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_runtime
import part_export
from binder_members import Binder, PART_CLIP, clip_id, plan_member

ROOT = 'N:\\NTC\\data\\Target\\INTERROOT_win64\\parts\\Weapon\\WP_A_0760\\'
CLIPS = ROOT + 'hkx_compendium\\'


def bnd(members):
    """BND4 bytes of (ID, path, data) members, like the game's part and animation binders."""
    from soulstruct.containers import Binder as Built, BinderEntry
    from soulstruct.dcx import DCXType
    result = Built(dcx_type=DCXType.Null)
    for ident, path, data in members:
        result.add_entry(BinderEntry(data=data, entry_id=ident, path=path))
    return result.to_bytes()


def animation_binder(model, clips):
    """An animation binder like WP_A_0760_1.anibnd: skeleton, TAE, compendium and clips named with the model's suffix."""
    suffix = model[len('WP_A_0760'):]
    return bnd([(1000000, f'{CLIPS}skeleton{suffix}.hkx', b'SKEL' + model.encode()), (3000000, f'{ROOT}tae\\{model}.tae', b'TAE'),
                (7000000, f'{CLIPS}{model}.compendium', b'COMP'),
                *[(clip_id(name, PART_CLIP), CLIPS + name, data) for name, data in clips]])


def part_binder(name='WP_A_0760'):
    return bnd([(100, f'{ROOT}{name}.tpf', b'TPF'), (200, f'{ROOT}{name}.flver', b'FLVER'), (201, f'{ROOT}{name}_1.flver', b'FLVER1'),
                (400, f'{ROOT}WP_A_0760.anibnd', animation_binder('WP_A_0760', [('a999_000000.hkx', b'REST0')])),
                (401, f'{ROOT}WP_A_0760_1.anibnd', animation_binder('WP_A_0760_1', [('a076_405010_1.hkx', b'CLIP'),
                                                                                    ('a999_000000_1.hkx', b'REST1')]))])


def clips_of(path, binder='WP_A_0760_1.anibnd'):
    """{member name: (ID, data)} of the clips in one animation binder of a written part binder."""
    outer = Binder(Path(path).read_bytes())
    entry = next(m for m in outer.members if PureWindowsPath(m[1]).name == binder)
    inner = Binder(entry[2])
    return {PureWindowsPath(m[1]).name: (inner.member_id(m), m[2]) for m in inner.members if PART_CLIP.fullmatch(PureWindowsPath(m[1]).name)}


class PartBinderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # Resolved, as the bridge resolves the paths it stores: the temporary folder can be named in its 8.3 short
        # form (C:\Users\RUNNER~1 on the release runner).
        self.root = Path(temp.name).resolve()
        self.game = self.root / 'Sekiro' / 'parts'
        self.game.mkdir(parents=True)
        self.source = self.game / 'wp_a_0760.partsbnd.dcx'
        self.source.write_bytes(part_binder())
        self.original = self.source.read_bytes()
        self.mod = self.root / 'mods' / 'umbrella'

    def clip(self, member, data, binder='WP_A_0760_1.anibnd', source=None):
        return dict(source=str(source or self.source), binder=binder, member=member, data=data)

    def test_part_clip_ids_ignore_the_models_suffix(self):
        self.assertEqual(clip_id('a076_405010_1.hkx', PART_CLIP), 1076405010)
        self.assertIsNone(clip_id('a076_405010_1.hkx'))
        binder = Binder(animation_binder('WP_A_0760_1', [('a999_000000_1.hkx', b'REST')]))
        self.assertEqual(plan_member(binder, 'a000_003000_1.hkx', pattern=PART_CLIP), (None, CLIPS + 'a000_003000_1.hkx', 1000003000))

    def test_a_new_clip_goes_into_the_mod_folder(self):
        written, notices, profile = part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        target = self.mod / 'parts' / 'wp_a_0760.partsbnd.dcx'
        self.assertEqual(notices, [])
        self.assertEqual([(w['file'], w['base']) for w in written], [(str(target), str(self.source))])
        self.assertEqual(written[0]['clips'], [dict(binder='WP_A_0760_1.anibnd', member='a000_003000_1.hkx', id=1000003000, replaced=False)])
        clips = clips_of(target)
        self.assertEqual(clips['a000_003000_1.hkx'], (1000003000, b'NEW'))
        self.assertEqual(list(clips), ['a000_003000_1.hkx', 'a076_405010_1.hkx', 'a999_000000_1.hkx'], 'members stay in ID order')
        # The other animation binder, the models and the game's file stay as they were.
        self.assertEqual(clips_of(target, 'WP_A_0760.anibnd'), {'a999_000000.hkx': (1999000000, b'REST0')})
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(Path(profile), self.mod.parent / 'umbrella.me3')
        self.assertIn('path = "umbrella"', Path(profile).read_text(encoding='utf-8'))

    def test_clips_add_up_and_replace_by_name(self):
        part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        written, _, _ = part_export.write([self.clip('a076_405010_1.hkx', b'EDITED'), self.clip('a000_003000.hkx', b'ROOT', 'WP_A_0760.anibnd')],
                                          self.mod)
        target = self.mod / 'parts' / 'wp_a_0760.partsbnd.dcx'
        self.assertEqual(written[0]['base'], str(target), 'the mod folder\'s copy is read the second time')
        self.assertEqual({k: v[1] for k, v in clips_of(target).items()},
                         {'a000_003000_1.hkx': b'NEW', 'a076_405010_1.hkx': b'EDITED', 'a999_000000_1.hkx': b'REST1'})
        self.assertEqual(clips_of(target, 'WP_A_0760.anibnd')['a000_003000.hkx'], (1000003000, b'ROOT'))
        self.assertEqual([row['replaced'] for row in written[0]['clips']], [True, False])

    def test_the_far_copy_gets_the_clip_too(self):
        far = self.game / 'wp_a_0760_l.partsbnd.dcx'
        far.write_bytes(part_binder('WP_A_0760_L'))
        self.assertEqual(part_export.copies(self.source), [self.source, far])
        self.assertEqual(part_export.copies(far), [far, self.source])
        written, _, _ = part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        self.assertEqual([Path(w['file']).name for w in written], ['wp_a_0760.partsbnd.dcx', 'wp_a_0760_l.partsbnd.dcx'])
        self.assertEqual(clips_of(self.mod / 'parts' / 'wp_a_0760_l.partsbnd.dcx')['a000_003000_1.hkx'][1], b'NEW')

    def test_a_copy_without_the_animation_binder_is_left_out(self):
        (self.game / 'wp_a_0760_l.partsbnd.dcx').write_bytes(bnd([(100, ROOT + 'WP_A_0760_L.tpf', b'TPF')]))
        written, notices, _ = part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        self.assertEqual(len(written), 1)
        self.assertIn('wp_a_0760_l.partsbnd.dcx has no WP_A_0760_1.anibnd', notices[0])
        self.assertFalse((self.mod / 'parts' / 'wp_a_0760_l.partsbnd.dcx').exists())

    def test_never_writes_into_the_game(self):
        (self.root / 'Sekiro' / 'sekiro.exe').write_bytes(b'')
        with self.assertRaises(ValueError):
            part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.root / 'Sekiro')
        self.assertEqual(self.source.read_bytes(), self.original)

    def decode(self, fail=()):
        """A stand-in decoder: a clip decodes unless its data is in fail."""
        def run(clip, compendium, skeleton, output):
            if Path(clip).read_bytes() in fail:
                raise RuntimeError('SekiroMotionDecoder failed: no animation')
            Path(output).write_text(json.dumps(dict(frameCount=2, skeleton=dict(bones=[{}, {}]), trackBoneIndices=[0, 1])),
                                    encoding='utf-8')
        return run

    def test_verify_reads_a_written_folder_back(self):
        (self.game / 'wp_a_0760_l.partsbnd.dcx').write_bytes(part_binder('WP_A_0760_L'))
        part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        report = part_export.verify(self.mod, self.decode(), self.root / 'work')
        self.assertTrue(all(c['passed'] for c in report['checks']), report['checks'])
        self.assertEqual([c['name'] for c in report['checks']],
                         ['wp_a_0760.partsbnd.dcx reads back', 'wp_a_0760.partsbnd.dcx clip names', 'wp_a_0760.partsbnd.dcx clips decode',
                          'wp_a_0760_l.partsbnd.dcx reads back', 'wp_a_0760_l.partsbnd.dcx clip names',
                          'wp_a_0760_l.partsbnd.dcx clips decode', 'wp_a_0760.partsbnd.dcx and its _l copy agree'])
        self.assertEqual([b['clips'] for b in report['binders']], [4, 4])

    def test_verify_names_what_is_wrong(self):
        (self.game / 'wp_a_0760_l.partsbnd.dcx').write_bytes(part_binder('WP_A_0760_L'))
        part_export.write([self.clip('a000_003000_1.hkx', b'NEW')], self.mod)
        # A clip without the model's suffix, written into the main copy only, that does not decode.
        part_export.write([self.clip('a000_004000.hkx', b'BROKEN')], self.mod.parent / 'other')
        (self.mod / 'parts' / 'wp_a_0760.partsbnd.dcx').write_bytes((self.mod.parent / 'other' / 'parts' / 'wp_a_0760.partsbnd.dcx').read_bytes())
        report = {c['name']: c for c in part_export.verify(self.mod, self.decode(fail=(b'BROKEN',)), self.root / 'work')['checks']}
        self.assertFalse(report['wp_a_0760.partsbnd.dcx clip names']['passed'])
        self.assertIn('WP_A_0760_1.anibnd/a000_004000.hkx', report['wp_a_0760.partsbnd.dcx clip names']['detail'])
        self.assertIn('no animation', report['wp_a_0760.partsbnd.dcx clips decode']['detail'])
        self.assertFalse(report['wp_a_0760.partsbnd.dcx and its _l copy agree']['passed'])
        self.assertTrue(report['wp_a_0760_l.partsbnd.dcx clips decode']['passed'])

    def test_verify_needs_part_binders(self):
        report = part_export.verify(self.mod, self.decode(), self.root / 'work')
        self.assertEqual([c['passed'] for c in report['checks']], [False])


class PartRequestTests(unittest.TestCase):
    def test_part_options_apply_only_with_part_export(self):
        self.assertEqual(bridge_runtime.part_request(dict(partId='bad', writeParts=True)), ('', None))
        self.assertEqual(bridge_runtime.part_request(dict(exportParts=True, partId='A000_003000.hkx')), ('a000_003000', None))
        with self.assertRaises(ValueError):
            bridge_runtime.part_request(dict(exportParts=True, partId='a000_3000'))
        with self.assertRaises(ValueError):
            bridge_runtime.part_request(dict(exportParts=True, writeParts=True, partsFolder=''))
        ident, mod = bridge_runtime.part_request(dict(exportParts=True, writeParts=True, partsFolder='work/mods/umbrella'))
        self.assertEqual((ident, mod), ('', Path('work/mods/umbrella').resolve()))

    def test_part_clip_names(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp).resolve()
            motion = temp / 'edited.motion.json'
            motion.write_text(json.dumps(dict(export=dict(frameStart=1, frameEnd=61))), encoding='utf-8')
            index = [dict(model='wp_a_0760_1', name='WP_A_0760_1', clip='a076_405010_1.hkx', motion='', frames=61, frameRate=30.0,
                          missingBones=[], new=False),
                     dict(model='wp_a_0760', name='WP_A_0760', clip='a999_000000.hkx', motion='', frames=61, frameRate=30.0,
                          missingBones=['Wing004'], new=True)]

            def sampled(args):
                (temp / 'parts').mkdir(exist_ok=True)
                (temp / 'parts' / 'parts.json').write_text(json.dumps(index), encoding='utf-8')
            output = temp / 'out' / 'a000_003000.hkx'
            with mock.patch.object(bridge_runtime, 'run', side_effect=sampled):
                names = lambda *ids: [(e['member'], Path(t).relative_to(output.parent).as_posix())
                                      for e, t in bridge_runtime.part_outputs('blender', 'scene.blend', motion, output, False, temp, *ids)]
                # A clip that came with the part keeps its name; a new one takes the character clip's ID, in a folder
                # of its model where that is the character HKX's name.
                self.assertEqual(names('a000_003000'), [('a076_405010_1.hkx', 'a076_405010_1.hkx'),
                                                        ('a999_000000.hkx', 'WP_A_0760/a000_003000.hkx')])
                self.assertEqual(names('', 'a050_002000'), [('a076_405010_1.hkx', 'a050_002000_1.hkx'), ('a999_000000.hkx', 'a050_002000.hkx')])
                with self.assertRaisesRegex(ValueError, 'WP_A_0760 has a new clip'):
                    names('')


if __name__ == '__main__':
    unittest.main()
