"""Part clip matching, TAE reading and the preview's joint math, on owned synthetic data."""
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import part_animations as pa
from clip_preview import detached, joint_positions, matrix


def tae(entries, version=0x1000D):
    """A minimal TAE: each animation gives (ID, 'own' | 'hkx' | 'other', source ID[, events]).

    An event is (type, start s, end s, slot, (dummy of model 0, ..., 3)), laid out as event 715.
    """
    data = bytearray(0x60 + 16 * len(entries))
    data[:4] = b'TAE '
    struct.pack_into('<i', data, 8, version)
    struct.pack_into('<i', data, 0x54, len(entries))
    struct.pack_into('<q', data, 0x58, 0x60)
    for index, (ident, kind, source, *rest) in enumerate(entries):
        events = rest[0] if rest else []
        animation = len(data); data += bytearray(48)
        block = len(data); data += bytearray(16)
        payload = len(data); data += bytearray(16)
        headers = len(data); data += bytearray(24 * len(events))
        for number, (event, start, end, slot, dummies) in enumerate(events):
            times = len(data); data += struct.pack('<ff', start, end)
            body = len(data); data += bytearray(16)
            parameters = len(data); data += struct.pack('<B3x4ii', slot, *dummies, 0)
            struct.pack_into('<qqq', data, headers + 24 * number, times, times + 4, body)
            struct.pack_into('<iiq', data, body, event, 0, parameters)
        struct.pack_into('<qq', data, 0x60 + 16 * index, ident, animation)
        struct.pack_into('<q', data, animation, headers)
        struct.pack_into('<i', data, animation + 0x20, len(events))
        struct.pack_into('<q', data, animation + 24, block)
        struct.pack_into('<qq', data, block, int(kind == 'other'), payload)
        if kind == 'other':
            struct.pack_into('<i', data, payload, source)
        else:
            data[payload + 9] = int(kind == 'hkx')
            struct.pack_into('<i', data, payload + 12, source if kind == 'hkx' else -1)
    return bytes(data)


def binder(members):
    from soulstruct.containers import Binder, BinderEntry
    from soulstruct.dcx import DCXType
    result = Binder(dcx_type=DCXType.Null)
    for index, (name, data) in enumerate(members):
        result.add_entry(BinderEntry(data=data, entry_id=index, path='N:\\FDP\\data\\Target\\INTERROOT_win64\\parts\\' + name))
    return result.to_bytes()


class TaeTests(unittest.TestCase):
    def test_reads_each_source_kind_and_category(self):
        data = tae([(405010, 'own', 0), (412000, 'hkx', 70412000), (412001, 'other', 76412000)])
        self.assertEqual(pa.read_tae(data, 76), {76405010: ('own', 76405010), 76412000: ('hkx', 70412000),
                                                 76412001: ('other', 76412000)})
        # Part TAE files use full IDs.
        self.assertEqual(pa.read_tae(tae([(76405033, 'hkx', 76421020)])), {76405033: ('hkx', 76421020)})

    def test_unknown_versions_and_other_files_read_as_empty(self):
        self.assertEqual(pa.read_tae(tae([(1, 'own', 0)], version=0x1000C)), {})
        self.assertEqual(pa.read_tae(b'BND4' + bytes(200)), {})

    def test_follows_references_to_the_played_hkx(self):
        index = {76412001: ('other', 76412000), 76412000: ('hkx', 70412000), 1: ('other', 2), 2: ('other', 1)}
        self.assertEqual(pa.played_hkx(index, 76412001), 70412000)
        self.assertEqual(pa.played_hkx(index, 5), 5)
        self.assertIn(pa.played_hkx(index, 1), (1, 2))

    def test_clip_names(self):
        self.assertEqual(pa.animation_id('a076_405010_1.hkx'), 76405010)
        self.assertEqual(pa.animation_id('N:\\parts\\a000_710200.HKX'), 710200)
        self.assertIsNone(pa.animation_id('skeleton_1.hkx'))
        self.assertEqual(pa.clip_name(999000000), 'a999_000000')


class ChooseTests(unittest.TestCase):
    part = dict(clips={76405010: 'a076_405010_1.hkx', 76412000: 'a076_412000_1.hkx', 73412000: 'a073_412000_1.hkx',
                       76421020: 'a076_421020_1.hkx', pa.REST: 'a999_000000_1.hkx'},
                tae={76405033: ('hkx', 76421020)})
    wolf = {70412000: ('own', 70412000), 73412000: ('hkx', 70412000), 76412000: ('hkx', 70412000), 76405010: ('own', 76405010)}

    def test_same_id_comes_first(self):
        self.assertEqual(pa.choose_clip(76405010, self.part, self.wolf), (76405010, 'same ID'))

    def test_shared_body_clip_takes_the_part_category(self):
        ident, reason = pa.choose_clip(70412000, self.part, self.wolf, 'c0000')
        self.assertEqual(ident, 76412000)
        self.assertIn('a076_412000 plays a070_412000', reason)

    def test_part_tae_redirects_an_id(self):
        self.assertEqual(pa.choose_clip(76405033, self.part, {})[0], 76421020)

    def test_rest_pose_without_a_clip(self):
        self.assertEqual(pa.choose_clip(100, self.part, self.wolf)[0], pa.REST)
        self.assertIsNone(pa.choose_clip(100, dict(clips={76405010: 'a.hkx'}, tae={}), {}))


class EntryTests(unittest.TestCase):
    """The character TAE ID that a pairing plays, whose events place the weapons."""
    part, wolf = ChooseTests.part, ChooseTests.wolf

    def test_each_kind_of_pairing_names_its_tae_id(self):
        self.assertEqual(pa.choose_entry(76405010, self.part, self.wolf), (76405010, 'same ID', 76405010))
        self.assertEqual(pa.choose_entry(70412000, self.part, self.wolf, 'c0000')[::2], (76412000, 76412000))
        # The part's own TAE redirects a clip of the body's ID, which stays the played ID.
        self.assertEqual(pa.choose_entry(76405033, self.part, {})[::2], (76421020, 76405033))
        self.assertEqual(pa.choose_entry(100, self.part, self.wolf)[::2], (pa.REST, None))


class LocationTests(unittest.TestCase):
    # Wolf's a076_405010: the sword sheathed for 0.867 s, the umbrella's model 1 in the left hand and model 0 hidden.
    umbrella = [(715, 0.0, 0.867, 0, (147, 147, -1, -1)), (715, 0.0, 3.067, 1, (-1, 21, -1, -1))]

    def test_reads_event_715_by_category(self):
        data = tae([(405010, 'own', 0, self.umbrella + [(710, .1, .2, 1, (0, 0, 0, 0))]), (412000, 'hkx', 70412000)])
        read = pa.read_locations(data, 76)
        self.assertEqual(list(read), [76405010])
        self.assertEqual([(round(start, 3), round(end, 3), slot, dummies) for start, end, slot, dummies in read[76405010]],
                         [(0.0, 0.867, 0, (147, 147, -1, -1)), (0.0, 3.067, 1, (-1, 21, -1, -1))])
        self.assertEqual(pa.read_tae(data, 76)[76412000], ('hkx', 70412000))
        self.assertEqual(pa.read_locations(tae([(1, 'own', 0, self.umbrella)], version=0x1000C)), {})

    def test_weapon_slots(self):
        names = ('wp_a_0760_1', 'WP_A_0300', 'wp_a_0310_1', 'wp_a_9500', 'wp_a_0201', 'bd_m_9000')
        self.assertEqual([pa.location_slot(name) for name in names], [1, 0, 2, 3, None, None])

    def test_changes_hold_between_events(self):
        axe = [(.233, 3.833, 1, (-1, 21, -1, -1))]
        self.assertEqual(pa.location_changes(axe, 1, 1, -1), [[0.0, -1], [.233, 21], [3.833, -1]])
        self.assertEqual(pa.location_changes(axe, 1, 0, 115), [[0.0, 115], [.233, -1], [3.833, 115]])
        # Another slot's events and a model beyond the event's four keep the default.
        self.assertEqual(pa.location_changes(axe, 0, 0, 20), [[0.0, 20]])
        self.assertEqual(pa.location_changes(axe, 1, 5, -1), [[0.0, -1]])

    def test_a_later_event_holds_where_events_overlap(self):
        art = [(0.0, 6.667, 0, (77, 77, -1, -1)), (.233, 2.8, 0, (76, 76, -1, -1))]
        self.assertEqual(pa.location_changes(art, 0, 0, 20), [[0.0, 77], [.233, 76], [2.8, 77], [6.667, 20]])


class PairingTests(unittest.TestCase):
    """The part view reads the pairing backwards: which body clips key each part clip."""
    part, wolf = ChooseTests.part, ChooseTests.wolf

    def test_players_of_groups_the_ids_by_the_hkx_they_play(self):
        self.assertEqual(pa.players_of(self.wolf), {70412000: [70412000, 73412000, 76412000], 76405010: [76405010]})

    def test_each_body_clip_is_listed_under_the_part_clip_it_keys(self):
        pairs = pa.pairings(self.part, [76405010, 70412000, 76405033, 100, 76405010], self.wolf, 'c0000')
        # The rest pose plays with a000_000100 and is not listed; a073_412000 loses a070_412000 to the part's own category.
        self.assertEqual(pairs, {76405010: [(76405010, 'same ID')],
                                 76412000: [(70412000, 'TAE of C0000: a076_412000 plays a070_412000')],
                                 76421020: [(76405033, 'its TAE plays a076_421020 for a076_405033')]})

    def test_the_reverse_agrees_with_the_forward_pairing(self):
        bodies = [70412000, 73412000, 76412000, 76405010, 76405033, 76421020, 100, pa.REST]
        players = pa.players_of(self.wolf)
        listed = {body: ident for ident, pairs in pa.pairings(self.part, bodies, self.wolf, 'c0000').items() for body, _ in pairs}
        for body in bodies:
            chosen = pa.choose_clip(body, self.part, self.wolf, 'c0000')
            self.assertEqual(pa.choose_clip(body, self.part, self.wolf, 'c0000', players), chosen)
            self.assertEqual(listed.get(body), chosen[0] if chosen[0] != pa.REST else None, body)


class PartFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        animated = binder([('skeleton_1.hkx', b'SKEL'), ('WP_A_0760_1.compendium', b'COMP'),
                           ('WP_A_0760_1.tae', tae([(76405010, 'own', 0), (999000000, 'own', 0)])),
                           ('a076_405010_1.hkx', b'CLIP'), ('a999_000000_1.hkx', b'REST')])
        resting = binder([('skeleton.hkx', b'SKEL'), ('a999_000000.hkx', b'REST')])
        self.parts = self.folder / 'wp_a_0760.partsbnd'
        self.parts.write_bytes(binder([('WP_A_0760_1.flver', b'not read'), ('WP_A_0760_1.anibnd', animated),
                                       ('WP_A_0760.anibnd', resting)]))
        # An outfit binder is never opened for part clips.
        self.outfit = self.folder / 'bd_m_9000.partsbnd'
        self.outfit.write_bytes(b'not a binder')

    def model(self, name, bones):
        import numpy as np
        data = self.folder / (name + '.npz')
        np.savez(data, bone_names=np.array(bones))
        return dict(name=name, source=str(self.parts), data=str(data), attachment=dict(bone='R_Weapon', dummy=118))

    def test_plan_reads_only_weapon_binders(self):
        rows = pa.plan([str(self.outfit), str(self.parts)], 'a076_405010.hkx', {}, 'c0000')
        self.assertEqual([(r['name'], r['member'], r['rest'], r['entry']) for r in rows],
                         [('WP_A_0760_1', 'a076_405010_1.hkx', False, 76405010), ('WP_A_0760', 'a999_000000.hkx', True, None)])

    def test_locate_records_where_event_715_puts_each_weapon(self):
        from unittest import mock
        own = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

        def weapon(name, dummy, index, placement='auto'):
            return dict(name=name, source=str(self.parts), attachment=dict(kind='dummy', dummy=dummy, bone='L_Forearm', matrix=own,
                                                                            placement=placement, modelIndex=index))
        manifest = self.folder / 'character.json'
        models = [weapon('wp_a_0760', 118, 0), weapon('wp_a_0760_1', 118, 1), weapon('wp_a_0300', 20, 0),
                  weapon('wp_a_0310', 149, 0, 'right'), dict(name='bd_m_9000', source=str(self.outfit))]
        manifest.write_text(json.dumps(dict(models=models, attachment_reference='c0000.flver')), encoding='utf-8')

        def attachment(reference, dummy, source, game):
            if dummy == 147:
                raise ValueError('Attachment dummy 147 has 0 matches in the reference model; choose an unambiguous socket.')
            return dict(bone='L_Weapon', matrix=[[dummy]])
        rows = pa.plan([str(self.parts)], 'a076_405010.hkx', {}, 'c0000')
        with mock.patch('weapon_assets.read_reference', return_value='reference') as read, \
                mock.patch('weapon_assets.attachment', side_effect=attachment):
            report, notices = pa.locate(manifest, rows, 'a076_405010.hkx', {76405010: [e[1:] for e in LocationTests.umbrella]})
        read.assert_called_once_with('c0000.flver')
        placed = {m['name']: m.get('attachment', {}).get('locations') for m in json.loads(manifest.read_text(encoding='utf-8'))['models']}
        self.assertEqual(placed['wp_a_0760'], dict(entry='a076_405010', changes=[[0.0, -1], [3.067, 118]], sockets={}))
        self.assertEqual(placed['wp_a_0760_1'], dict(entry='a076_405010', changes=[[0.0, 21], [3.067, -1]],
                                                     sockets={'21': dict(dummy=21, bone='L_Weapon', matrix=[[21]])}))
        # A dummy missing from the reference keeps the sword where it was; a placement chosen by hand is not moved.
        self.assertIsNone(placed['wp_a_0300'])
        self.assertIn('WP_A_0300', notices[0])
        self.assertIsNone(placed['wp_a_0310'])
        self.assertEqual([r['model'] for r in report], ['WP_A_0760', 'WP_A_0760_1'])

    def test_locate_needs_events_of_sekiro(self):
        manifest = self.folder / 'character.json'
        manifest.write_text(json.dumps(dict(models=[])), encoding='utf-8')
        self.assertEqual(pa.locate(manifest, [], 'a076_405010.hkx', {}), ([], []))
        self.assertEqual(pa.locate(manifest, [], 'a076_405010.hkx', {76405010: LocationTests.umbrella}, 'ds3'), ([], []))

    def test_prepare_decodes_the_clip_into_the_manifest(self):
        manifest = self.folder / 'character.json'
        manifest.write_text(json.dumps(dict(models=[self.model('wp_a_0760_1', ['W_Root', 'W_Wing', 'Ctrl_Root']),
                                                    self.model('wp_a_0760', ['W_Root'])])), encoding='utf-8')
        calls = []

        def decode(clip, compendium, skeleton, output):
            calls.append((Path(clip).read_bytes(), Path(compendium).read_bytes(), Path(skeleton).read_bytes()))
            Path(output).write_text(json.dumps(dict(format='sekiro-animation-bridge', formatVersion=1, frameCount=2, frameRate=30.0,
                                                    trackNames=['W_Root', 'W_Wing'])), encoding='utf-8')
        rows = pa.plan([str(self.parts)], 'a076_405010.hkx', {}, 'c0000')
        report, notices = pa.prepare(manifest, rows, decode, self.folder / 'work')
        self.assertEqual(calls, [(b'CLIP', b'COMP', b'SKEL')])
        self.assertEqual(notices, [])
        models = {m['name']: m for m in json.loads(manifest.read_text(encoding='utf-8'))['models']}
        animation = models['wp_a_0760_1']['animation']
        self.assertEqual((animation['clip'], animation['frames'], animation['frameRate'], animation['reason']),
                         ('a076_405010_1.hkx', 2, 30.0, 'same ID'))
        motion = json.loads(Path(animation['motion']).read_text(encoding='utf-8'))
        self.assertEqual((motion['clip'], motion['part']['binder']), ('a076_405010_1.hkx', 'WP_A_0760_1.anibnd'))
        # The rest pose is shared by every ID without a clip: it is reported, never keyed.
        self.assertNotIn('animation', models['wp_a_0760'])
        self.assertEqual([r.get('rest', False) for r in report], [False, True])

    def test_a_clip_moving_missing_bones_keeps_the_rest_pose(self):
        manifest = self.folder / 'character.json'
        manifest.write_text(json.dumps(dict(models=[self.model('wp_a_0760_1', ['W_Root'])])), encoding='utf-8')

        def decode(clip, compendium, skeleton, output):
            Path(output).write_text(json.dumps(dict(frameCount=2, frameRate=30.0, trackNames=['W_Root', 'W_Wing'])), encoding='utf-8')
        report, notices = pa.prepare(manifest, pa.plan([str(self.parts)], 'a076_405010.hkx', {}), decode, self.folder / 'work')
        self.assertEqual(report, [])
        self.assertIn('W_Wing', notices[0])
        self.assertNotIn('animation', json.loads(manifest.read_text(encoding='utf-8'))['models'][0])

    def test_character_binder_and_tae(self):
        base = self.folder / 'c0000.anibnd'
        base.write_bytes(binder([('a076.tae', tae([(412000, 'hkx', 70412000)])), ('a070.tae', tae([(412000, 'own', 0)]))]))
        clips = self.folder / 'c0000_a07x.anibnd'
        clips.write_bytes(b'')
        catalog = dict(characters=[dict(id='c0000', archives=[str(clips), str(base)])], sources=[])
        clip = dict(character='c0000', characterKey='c0000', archive=str(clips), inputArchives=[str(clips)])
        self.assertEqual(pa.character_binder(catalog, clip), base)
        self.assertEqual(pa.character_tae(base), {76412000: ('hkx', 70412000), 70412000: ('own', 70412000)})
        self.assertEqual(pa.character_locations(base), {})
        self.assertIsNone(pa.character_binder(catalog, dict(clip, character='')))


class PreviewMathTests(unittest.TestCase):
    def test_joint_positions_follow_parents_with_rotation_and_scale(self):
        half = math.sqrt(.5)
        rest = dict(translation=[0, 0, 1], rotation=[0, 0, 0, 1], scale=[1, 1, 1])
        motion = dict(skeleton=dict(bones=[dict(rest, parent=-1, translation=[1, 0, 0]), dict(rest, parent=0)]),
                      trackBoneIndices=[0],
                      frames=[[dict(translation=[1, 0, 0], rotation=[0, half, 0, half], scale=[1, 1, 1])],
                              [dict(translation=[1, 0, 0], rotation=[0, half, 0, half], scale=[2, 2, 2])]])
        first, second = joint_positions(motion)
        # A quarter turn about Y carries the child's +Z offset onto +X; the root's scale doubles it.
        self.assertEqual(first, [1, 0, 0, 2, 0, 0])
        self.assertEqual(second, [1, 0, 0, 3, 0, 0])

    def test_a_bone_far_from_the_body_leaves_the_view(self):
        body = [[x * .1, y * .3, 0] for x in range(3) for y in range(4)]
        frames = [sum(body + [[0, 2, 4.2]], []), sum([[x + 5, y, z] for x, y, z in body] + [[5, 2.2, 4]], [])]
        self.assertEqual(detached(frames, len(body) + 1), [len(body)])
        # A spread skeleton with long limbs keeps every bone.
        self.assertEqual(detached([sum(body, [])], len(body)), [])

    def test_matrix_scales_columns(self):
        rows = matrix(dict(translation=[1, 2, 3], rotation=[0, 0, 0, 1], scale=[2, 3, 4]))
        self.assertEqual(rows, ((2, 0, 0, 1), (0, 3, 0, 2), (0, 0, 4, 3)))


if __name__ == '__main__':
    unittest.main()
