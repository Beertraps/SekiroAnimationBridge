"""Registering a new animation ID: TAE readback, behavior XML, plans and the export's slot step, on owned synthetic
TAE files, behaviors and binders. The behavior tests run the SDT HKB Duplicator when it is set up and skip otherwise;
SekiroCharacterWriter's tae command stands in as a function that writes the expected TAE."""
import hashlib
import io
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path, PureWindowsPath
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import animation_slots as slots
import bridge_runtime
import character_export
import havok_xml
from binder_members import Binder, add_member
from test_binder_members import anibnd
from test_havok_xml import INT8, INT32, layout_builder, layouts_of

ROOT = 'N:\\FDP\\data\\INTERROOT_win64\\chr\\'


# TAE ---------------------------------------------------------------------------------------------------------------------

def tae(entries):
    """A minimal TAE (version 0x1000D): each entry is (ID, 'own' | 'hkx' | 'other', source ID, events), and each event
    (start s, end s, type). An imported ID ('other') is the second field of its file data, after the name offset."""
    data = bytearray(0x60 + 16 * len(entries))
    data[:4] = b'TAE '
    struct.pack_into('<i', data, 8, 0x1000D)
    struct.pack_into('<i', data, 0x54, len(entries))
    struct.pack_into('<q', data, 0x58, 0x60)
    for index, (ident, kind, source, events) in enumerate(entries):
        animation = len(data); data += bytearray(48)
        header = len(data); data += bytearray(16)
        payload = len(data); data += bytearray(16)
        headers = len(data); data += bytearray(24 * len(events))
        for number, (start, end, kind_of_event) in enumerate(events):
            times = len(data); data += struct.pack('<ff', start, end)
            block = len(data); data += struct.pack('<iiq', kind_of_event, 0, 0)
            struct.pack_into('<qqq', data, headers + 24 * number, times, times + 4, block)
        struct.pack_into('<qq', data, 0x60 + 16 * index, ident, animation)
        struct.pack_into('<q', data, animation, headers)
        struct.pack_into('<i', data, animation + 0x20, len(events))
        struct.pack_into('<q', data, animation + 24, header)
        struct.pack_into('<qq', data, header, int(kind == 'other'), payload)
        struct.pack_into('<q', data, payload, 0x1234)  # the file name offset, which a reader must skip
        if kind == 'other':
            struct.pack_into('<i', data, payload + 8, source)
        else:
            data[payload + 9] = int(kind == 'hkx')
            struct.pack_into('<i', data, payload + 12, source if kind == 'hkx' else -1)
    return bytes(data)


SWING = [(0.0, 0.5, 0), (0.2, 0.4, 1), (0.25, 0.3, 128)]
IDLE = [(0.0, 1.0, 0)]
ENEMY = [(0, 'own', 0, IDLE), (3008, 'own', 0, SWING), (5010, 'other', 405010, []), (6000, 'hkx', 3008, IDLE)]


class TaeReadback(unittest.TestCase):
    def test_kinds_and_events(self):
        data = tae(ENEMY)
        self.assertEqual(slots.tae_kinds(data), {0: ('own', 0), 3008: ('own', 3008), 5010: ('other', 405010),
                                                 6000: ('hkx', 3008)})
        self.assertEqual(slots.tae_events(data, 3008), [(0.0, 0.5, 0), (0.20000000298023224, 0.4000000059604645, 1),
                                                        (0.25, 0.30000001192092896, 128)])
        self.assertIsNone(slots.tae_events(data, 100003008))

    def test_a_right_rewrite_passes(self):
        after = tae(ENEMY + [(100003008, 'own', 0, SWING)])
        self.assertEqual(slots.check_tae(tae(ENEMY), tae(ENEMY), after, 100003008, 3008),
                         'entry 100003008 plays its own HKX with 3 events; the other 4 entries are unchanged')

    def test_a_wrong_rewrite_is_refused(self):
        before = tae(ENEMY)
        cases = {
            'does not play its own HKX': ENEMY + [(100003008, 'hkx', 3008, SWING)],
            'does not have the events of 3008': ENEMY + [(100003008, 'own', 0, SWING[:2])],
            'changed 1 other entries, such as 5010': ENEMY[:2] + [(5010, 'other', 5010, []), ENEMY[3],
                                                                   (100003008, 'own', 0, SWING)],
            'not have the same other entries': ENEMY[:3] + [(100003008, 'own', 0, SWING)],
        }
        for message, entries in cases.items():
            with self.subTest(message), self.assertRaisesRegex(RuntimeError, message):
                slots.check_tae(before, before, tae(entries), 100003008, 3008)


class Names(unittest.TestCase):
    def test_clip_names(self):
        self.assertEqual(slots.parse('a100_003008.hkx'), (100, 3008))
        self.assertEqual(slots.parse('C:\\mods\\A000_000000'), (0, 0))
        self.assertIsNone(slots.parse('idle.hkx'))
        self.assertIsNone(slots.parse(''))
        self.assertEqual(slots.clip_name(5, 12), 'a005_000012')

    def test_tae_members_by_category(self):
        class Holder:
            members = [(3000000, ROOT + 'c0000\\tae\\a00.tae', b''), (3000001, ROOT + 'c0000\\tae\\a100.tae', b''),
                       (1000000000, ROOT + 'c0000\\hkx\\a000_000000.hkx', b'')]
        player = list(slots.tae_members(Holder))
        self.assertEqual([(i, c) for i, _, c in player], [(0, 0), (1, 100)])
        self.assertEqual(slots.tae_for(player, 100)[2], 100)
        self.assertIsNone(slots.tae_for(player, 50))
        self.assertEqual(slots.local_id(slots.tae_for(player, 100), 100, 3008), 3008)
        enemy = [(0, ROOT + 'c1010\\tae\\c1010.tae', None)]
        self.assertEqual(slots.local_id(slots.tae_for(enemy, 100), 100, 3008), 100003008)


# Behaviors ---------------------------------------------------------------------------------------------------------------

def behavior_layouts():
    """Binary layouts of a small behavior: states, selectors (CMSG) and clip generators, and the graph's string and
    event data, in the shapes and type names the game's behaviors use."""
    types, add = layout_builder()
    add('char', INT8, 1, 1)
    add('int', INT32, 4, 4)
    add('const char*', havok_xml.STRING, 8, 8)
    add('hkContainerHeapAllocator', havok_xml.RECORD, 1, 1, fields=[])
    records = [add('hkbGenerator', havok_xml.RECORD, 16, 8, fields=[]),
               add('hkbStateMachine::StateInfo', havok_xml.RECORD, 16, 8, fields=[]),
               add('hkbBehaviorGraphStringData', havok_xml.RECORD, 32, 8, fields=[]),
               add('hkbBehaviorGraphData', havok_xml.RECORD, 16, 8, fields=[])]
    pointer = {t.name: add('T*', havok_xml.POINTER, 8, 8, subtype=t.name, params=[('tT', t.name)]) for t in records}

    def array(element):
        return add('hkArray', havok_xml.ARRAY, 16, 8, subtype=element,
                   params=[('tT', element), ('tAllocator', 'hkContainerHeapAllocator')])

    strings, ints, generators = array('const char*'), array('int'), array(pointer['hkbGenerator'].full_name())
    states = array(pointer['hkbStateMachine::StateInfo'].full_name())
    text, number = types['const char*'], types['int']
    generator, state, string_data, graph_data = records
    generator.fields = [('name', 32, 0, text), ('userData', 32, 8, number)]
    add('CustomManualSelectorGenerator', havok_xml.RECORD, 40, 8, parent='hkbGenerator', fields=[
        ('generators', 32, 16, generators), ('animId', 32, 32, number)])
    add('hkbClipGenerator', havok_xml.RECORD, 32, 8, parent='hkbGenerator', fields=[
        ('animationName', 32, 16, text), ('animationInternalId', 32, 24, number)])
    state.fields = [('name', 32, 0, text), ('generator', 32, 8, pointer['hkbGenerator'])]
    string_data.fields = [('eventNames', 32, 0, strings), ('animationNames', 32, 16, strings)]
    graph_data.fields = [('eventInfos', 32, 0, ints)]
    add('SynthBehaviorGraph', havok_xml.RECORD, 32, 8, fields=[
        ('states', 32, 0, states), ('stringData', 32, 16, pointer['hkbBehaviorGraphStringData']),
        ('data', 32, 24, pointer['hkbBehaviorGraphData'])])
    return layouts_of(types)


def behavior_xml(moves, clips, character='c9997'):
    """XML of a behavior with a state per move. moves: [(state, selector, animId, [clip generator names])]; clips:
    {clip generator name: animation}. A clip generator named in two moves is one object in both selectors."""
    animations = sorted(set(clips.values()))
    paths = [f'..\\..\\..\\..\\..\\Model\\chr\\{character}\\hkx\\{a[:4]}\\{a}.hkx' for a in animations]
    ids = {name: f'object{4 + index}' for index, name in enumerate(clips)}
    number = 4 + len(clips)

    def field(name, element):
        return f'<field name="{name}">{element}</field>'

    def record(oid, type_id, *fields):
        return f'  <object id="{oid}" typeid="{type_id}">\n    <record>\n      ' + '\n      '.join(fields) + '\n    </record>\n  </object>'

    def array(elements):
        return f'<array count="{len(elements)}">' + ''.join(elements) + '</array>'

    def string(value):
        return f'<string value="{value}"/>'

    objects, states = [], []
    for state, selector, anim_id, held in moves:
        state_id, selector_id = f'object{number}', f'object{number + 1}'
        number += 2
        states.append(state_id)
        objects.append(record(state_id, 'type4', field('name', string(state)), field('generator', f'<pointer id="{selector_id}"/>')))
        objects.append(record(selector_id, 'type5', field('name', string(selector)), field('userData', '<integer value="0"/>'),
                              field('generators', array([f'<pointer id="{ids[name]}"/>' for name in held])),
                              field('animId', f'<integer value="{anim_id}"/>')))
    for name, animation in clips.items():
        objects.append(record(ids[name], 'type6', field('name', string(name)), field('userData', '<integer value="0"/>'),
                              field('animationName', string(animation)),
                              field('animationInternalId', f'<integer value="{animations.index(animation)}"/>')))
    head = [record('object1', 'type1', field('states', array([f'<pointer id="{s}"/>' for s in states])),
                   field('stringData', '<pointer id="object2"/>'), field('data', '<pointer id="object3"/>')),
            record('object2', 'type2', field('eventNames', array([string('W_Attack3008')])),
                   field('animationNames', array([string(path) for path in paths]))),
            record('object3', 'type3', field('eventInfos', array(['<integer value="0"/>'])))]
    types = ['SynthBehaviorGraph', 'hkbBehaviorGraphStringData', 'hkbBehaviorGraphData', 'hkbStateMachine::StateInfo',
             'CustomManualSelectorGenerator', 'hkbClipGenerator']
    return ('<?xml version="1.0" encoding="utf-8"?>\n<hktagfile version="3">\n'
            + ''.join(f'  <type id="type{i + 1}"><name value="{name}"/></type>\n' for i, name in enumerate(types))
            + '\n'.join(head + objects) + '\n</hktagfile>\n')


ATTACK = ('Attack3008', 'Attack3008_CMSG', 3008, ['a000_003008_hkx_AutoSet_01'])
IDLES = [('Idle', 'IdleDefault_CMSG', 0, ['a000_000000_hkx_AutoSet_00']),
         ('Init', 'Init_CMSG', 0, ['a000_000000_hkx_AutoSet_00'])]
CLIPS = {'a000_003008_hkx_AutoSet_01': 'a000_003008', 'a000_000000_hkx_AutoSet_00': 'a000_000000'}


def behavior_tagfile(moves=(ATTACK, *IDLES), clips=None):
    return havok_xml.to_hkx(behavior_xml(list(moves), clips or CLIPS), behavior_layouts())[0]


def duplicator_ready():
    """The Duplicator's folder when it and lxml are set up for this Python, else None."""
    root = slots.duplicator_root()
    found = subprocess.run([sys.executable, '-E', '-c', 'import lxml'], capture_output=True).returncode == 0
    return root if root and found else None


class BehaviorXml(unittest.TestCase):
    def test_the_synthetic_behavior_reads_back(self):
        text = havok_xml.to_xml(behavior_tagfile())
        index = slots.behavior_index(text)
        self.assertEqual(sorted(clip['name'] for clip in index['clips'].values()), sorted(CLIPS))
        self.assertEqual(sorted(s['name'] for s in index['selectors'].values()),
                         ['Attack3008_CMSG', 'IdleDefault_CMSG', 'Init_CMSG'])
        self.assertEqual([PureWindowsPath(path).name for path in index['paths']], ['a000_000000.hkx', 'a000_003008.hkx'])
        self.assertEqual(slots.selectors_playing(index, 'A000_000000'), ['IdleDefault_CMSG', 'Init_CMSG'])
        self.assertEqual(slots.selectors_playing(index, 'a100_003008'), [])

    def test_variation_names_are_free_and_keep_the_source_pattern(self):
        moves = (ATTACK, *IDLES, ('Other', 'Other_CMSG', 1, ['a100_003008_hkx_AutoSet_01']))
        clips = dict(CLIPS, a100_003008_hkx_AutoSet_01='a050_000001')
        index = slots.behavior_index(havok_xml.to_xml(behavior_tagfile(moves, clips)))
        jobs, present = slots.variation_names(index, 'a000_003008', 'a100_003008')
        self.assertEqual((jobs, present), ([dict(selector='Attack3008_CMSG', sourceClip='a000_003008_hkx_AutoSet_01',
                                                 clipName='a100_003008_hkx_AutoSet_02')], []))
        jobs, _ = slots.variation_names(index, 'a000_000000', 'a100_000000')
        self.assertEqual([(job['selector'], job['clipName']) for job in jobs],
                         [('IdleDefault_CMSG', 'a100_000000_hkx_AutoSet_00'), ('Init_CMSG', 'a100_000000_hkx_AutoSet_01')])

    def test_a_selector_that_plays_the_clip_already_is_left_alone(self):
        moves = [('Attack3008', 'Attack3008_CMSG', 3008, ['a000_003008_hkx_AutoSet_01', 'a100_003008_hkx_AutoSet_01'])]
        clips = {'a000_003008_hkx_AutoSet_01': 'a000_003008', 'a100_003008_hkx_AutoSet_01': 'a100_003008'}
        index = slots.behavior_index(havok_xml.to_xml(behavior_tagfile(moves, clips)))
        self.assertEqual(slots.variation_names(index, 'a000_003008', 'a100_003008'), ([], ['Attack3008_CMSG']))

    def test_a_missing_clip_generator_fails_the_check(self):
        index = slots.behavior_index(havok_xml.to_xml(behavior_tagfile()))
        plan = dict(clip='a000_003008')
        job = dict(selector='Attack3008_CMSG', sourceClip='a000_003008_hkx_AutoSet_01', clipName='a100_003008_hkx_AutoSet_01')
        with self.assertRaisesRegex(RuntimeError, 'does not hold a100_003008_hkx_AutoSet_01'):
            slots.check_variations(index, plan, [job])
        with self.assertRaisesRegex(RuntimeError, 'does not list the animation a100_003008'):
            slots.check_variations(index, dict(clip='a100_003008'), [job])


# Binders and plans -------------------------------------------------------------------------------------------------------

def enemy_anibnd(entries=ENEMY):
    return anibnd([(3000000, ROOT + 'c1010\\tae\\c1010.tae', tae(entries)),
                   (1000000000, ROOT + 'c1010\\hkx\\a000_000000.hkx', b'I' * 64),
                   (1000003008, ROOT + 'c1010\\hkx\\a000_003008.hkx', b'S' * 64)])


def behbnd(*tagfiles):
    return anibnd([(index, f'N:\\FDP\\data\\INTERROOT_win64\\chr\\c1010\\Behaviors\\{name}.hkx', data)
                   for index, (name, data) in enumerate(tagfiles)])


def digest(folder):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(Path(folder).rglob('*')) if path.is_file()}


class Plans(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.game = self.base / 'Sekiro' / 'chr'
        self.game.mkdir(parents=True)
        (self.base / 'Sekiro' / 'sekiro.exe').write_bytes(b'')
        (self.game / 'c1010.anibnd.dcx').write_bytes(enemy_anibnd())
        (self.game / 'c1010.behbnd.dcx').write_bytes(behbnd(('c9997', b'x')))
        self.tool = self.base / 'duplicator'
        (self.tool / 'src').mkdir(parents=True)
        for name in ('behavior.py', 'project.py'):
            (self.tool / 'src' / name).write_text('', encoding='utf-8')
        self.mod = self.base / 'mod' / 'chr' / 'c1010.anibnd.dcx'

    def plan(self, member='a100_003008.hkx', source='', scene='a000_003008.hkx', binder=None, base=None):
        base = self.game / 'c1010.anibnd.dcx' if base is None else base
        return slots.plan(binder or self.mod, member, str(base), source, scene, str(self.tool))

    def test_an_enemy_plan_writes_beside_the_binder_and_reads_the_game(self):
        plan = self.plan()
        self.assertEqual((plan['clip'], plan['source'], plan['character']), ('a100_003008', 'a000_003008', 'c1010'))
        self.assertEqual({k: plan['tae'][k] for k in ('member', 'sourceMember', 'id', 'sourceId', 'shared')},
                         dict(member=ROOT + 'c1010\\tae\\c1010.tae', sourceMember=ROOT + 'c1010\\tae\\c1010.tae',
                              id=100003008, sourceId=3008, shared=True))
        self.assertEqual(plan['behavior'], dict(read=str(self.game / 'c1010.behbnd.dcx'),
                                                write=str(self.mod.parent / 'c1010.behbnd.dcx')))
        self.assertEqual(self.plan(source='a000_003008', scene='')['source'], 'a000_003008')

    def test_a_clip_the_binder_holds_needs_no_registration(self):
        self.assertIsNone(self.plan(member='a000_003008.hkx'))

    def test_only_another_category_of_the_same_number_is_a_variation(self):
        for member, source in (('a100_003009.hkx', ''), ('a100_003008.hkx', 'a100_003008')):
            with self.subTest(member), self.assertRaisesRegex(ValueError, 'keeps the number of its source'):
                self.plan(member=member, source=source)
        with self.assertRaisesRegex(ValueError, 'the scene does not record its clip'):
            self.plan(scene='')
        with self.assertRaisesRegex(ValueError, "the scene's clip edited.hkx is not one"):
            self.plan(scene='edited.hkx')

    def test_missing_sources_are_named(self):
        (self.game / 'c1010.anibnd.dcx').write_bytes(enemy_anibnd([entry for entry in ENEMY if entry[0] != 3008]))
        with self.assertRaisesRegex(ValueError, 'no entry for the source clip a000_003008'):
            self.plan()
        (self.game / 'c1010.anibnd.dcx').write_bytes(enemy_anibnd())
        (self.game / 'c1010.behbnd.dcx').unlink()
        with self.assertRaisesRegex(ValueError, 'No c1010.behbnd.dcx was found'):
            self.plan()

    def test_the_duplicator_must_be_set_up(self):
        with mock.patch.object(slots, 'APP', self.base / 'nowhere'), mock.patch.dict('os.environ', SEKIRO_HKB_DUPLICATOR=''):
            self.assertIsNone(slots.duplicator_root())
            with self.assertRaisesRegex(ValueError, 'setup_hkb_duplicator.cmd'):
                slots.plan(self.mod, 'a100_003008.hkx', str(self.game / 'c1010.anibnd.dcx'), '', 'a000_003008.hkx')
            self.assertEqual(slots.duplicator_status(sys.executable)[0], False)

    def test_nothing_is_planned_into_the_game_folder(self):
        with self.assertRaisesRegex(ValueError, 'outside the game installation'):
            self.plan(binder=self.game / 'c1010.anibnd.dcx')

    def test_the_player_tae_is_in_the_base_binder_one_file_per_category(self):
        folder = self.base / 'mod' / 'chr'
        folder.mkdir(parents=True)
        (folder / 'c0000_a10x.anibnd.dcx').write_bytes(anibnd([(1100002000, ROOT + 'c0000\\hkx\\a100_002000.hkx', b'P')]))
        (folder / 'c0000.anibnd.dcx').write_bytes(anibnd([(3000000, ROOT + 'c0000\\tae\\a00.tae', tae(ENEMY)),
                                                          (3000100, ROOT + 'c0000\\tae\\a100.tae', tae(ENEMY[:1]))]))
        (folder / 'c0000.behbnd.dcx').write_bytes(b'x')
        plan = self.plan(binder=folder / 'c0000_a10x.anibnd.dcx', base='', source='a000_003008')
        self.assertEqual({k: plan['tae'][k] for k in ('write', 'member', 'sourceMember', 'id', 'sourceId', 'shared')},
                         dict(write=str(folder / 'c0000.anibnd.dcx'), member=ROOT + 'c0000\\tae\\a100.tae',
                              sourceMember=ROOT + 'c0000\\tae\\a00.tae', id=3008, sourceId=3008, shared=False))
        with self.assertRaisesRegex(ValueError, r'no TAE for category a110 \(a110.tae\)'):
            self.plan(binder=folder / 'c0000_a10x.anibnd.dcx', base='', member='a110_003008.hkx', source='a000_003008')


class Requests(unittest.TestCase):
    def test_slot_request(self):
        self.assertIsNone(bridge_runtime.slot_request({'addToBinder': True}))
        self.assertIsNone(bridge_runtime.slot_request({'registerSlot': True, 'slotSource': 'a000_003008'}))
        self.assertEqual(bridge_runtime.slot_request({'registerSlot': True, 'addToBinder': True}), '')
        self.assertEqual(bridge_runtime.slot_request({'registerSlot': True, 'addToBinder': True, 'slotSource': ' a000_003008 '}),
                         'a000_003008')
        with self.assertRaisesRegex(ValueError, 'aXXX_YYYYYY'):
            bridge_runtime.slot_request({'registerSlot': True, 'addToBinder': True, 'slotSource': 'idle'})

    def test_add_member_replaces_other_members_only_when_asked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'c1010.anibnd.dcx'
            path.write_bytes(enemy_anibnd())
            plain, _ = add_member(path, 'a100_003008.hkx', b'N' * 32)
            self.assertEqual(add_member(path, 'a100_003008.hkx', b'N' * 32, replace={})[0], plain)
            new = tae(ENEMY + [(100003008, 'own', 0, SWING)])
            data, _ = add_member(path, 'a100_003008.hkx', b'N' * 32, replace={ROOT + 'c1010\\tae\\c1010.tae': new})
            members = {PureWindowsPath(p).name: d for _, p, d in Binder(data).members}
            self.assertEqual((members['c1010.tae'], members['a100_003008.hkx']), (new, b'N' * 32))
            self.assertEqual(Binder(plain).members[0][2], tae(ENEMY))
            with self.assertRaisesRegex(ValueError, 'no member x.tae to replace'):
                add_member(path, 'a100_003008.hkx', b'N', replace={'x.tae': b''})


# The whole step, with the Duplicator -------------------------------------------------------------------------------------

class Registration(unittest.TestCase):
    def setUp(self):
        self.duplicator = duplicator_ready()
        if self.duplicator is None:
            self.skipTest('The SDT HKB Duplicator or lxml is not set up (tools\\setup_hkb_duplicator.cmd).')
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.game = self.base / 'Sekiro' / 'chr'
        self.game.mkdir(parents=True)
        (self.base / 'Sekiro' / 'sekiro.exe').write_bytes(b'')
        (self.game / 'c1010.anibnd.dcx').write_bytes(enemy_anibnd())
        (self.game / 'c1010.behbnd.dcx').write_bytes(behbnd(('c1010', behavior_tagfile([IDLES[0]], {'a000_000000_hkx_AutoSet_00': 'a000_000000'})),
                                                            ('c9997', behavior_tagfile())))
        self.mod = self.base / 'mod' / 'chr' / 'c1010.anibnd.dcx'
        self.jobs = []

    def writer(self, command, job, folder, name=None):
        """SekiroCharacterWriter's tae command as the bridge sees it: the TAE with the new entry, and its report."""
        self.jobs.append((command, job))
        Path(job['output']).write_bytes(tae(ENEMY + [(job['id'], 'own', 0, SWING)]))
        return dict(kind='added', changed=True, id=job['id'], sourceId=job['sourceId'], eventsFrom=job['sourceId'],
                    unchangedIdentical=False)

    def export(self, name='a100_003008.hkx'):
        temp = self.base / 'temp'
        temp.mkdir(exist_ok=True)
        hkx = temp / 'edited.hkx'
        hkx.write_bytes(b'H' * 48)
        into, motion, out = (self.mod, ''), dict(clip='a000_003008.hkx'), io.StringIO()
        with mock.patch.object(character_export, 'run_writer', self.writer), redirect_stdout(out):
            slot = bridge_runtime.prepare_slot('', into, name, str(self.game / 'c1010.anibnd.dcx'), motion, sys.executable, temp)
            report = bridge_runtime.add_to_binder(into, name, str(self.game / 'c1010.anibnd.dcx'), motion, hkx, temp, slot)
        return report, out.getvalue()

    def test_export_adds_the_tae_entry_and_the_clip_generator_and_reads_them_back(self):
        game = digest(self.game)
        report, log = self.export()
        self.assertEqual(self.jobs[0][1]['id'], 100003008)
        slot = report['slot']
        self.assertTrue(slot['passed'], log)
        self.assertEqual([check['name'] for check in slot['checks']], ['TAE entry', 'Behavior clip generator'])
        self.assertEqual(slot['behavior']['files'][0]['added'], [dict(selector='Attack3008_CMSG', clipGenerator='a100_003008_hkx_AutoSet_01',
                                                                      copiedFrom='a000_003008_hkx_AutoSet_01')])
        self.assertEqual(len(slot['behavior']['files']), 1)  # c1010.hkx does not play a000_003008
        self.assertIn('New animation ID checks: 2 of 2 pass', log)
        self.assertIn('not yet tested', log)
        members = {PureWindowsPath(p).name: d for _, p, d in Binder(self.mod.read_bytes()).members}
        self.assertEqual(slots.tae_kinds(members['c1010.tae'])[100003008], ('own', 100003008))
        self.assertEqual(members['a100_003008.hkx'], b'H' * 48)
        behavior = Binder((self.mod.parent / 'c1010.behbnd.dcx').read_bytes())
        index = slots.behavior_index(havok_xml.to_xml(behavior.members[1][2]))
        self.assertEqual(slots.selectors_playing(index, 'a100_003008'), ['Attack3008_CMSG'])
        self.assertIn('..\\..\\..\\..\\..\\Model\\chr\\c9997\\hkx\\a100\\a100_003008.hkx', index['paths'])
        self.assertEqual(behavior.members[0][2], Binder((self.game / 'c1010.behbnd.dcx').read_bytes()).members[0][2])
        self.assertEqual(digest(self.game), game)
        # Exporting the same name again replaces the clip; its TAE entry and behavior stay as they are.
        report, log = self.export()
        self.assertNotIn('slot', report)
        self.assertIn('holds a100_003008.hkx already', log)

    def test_a_clip_in_several_selectors_gets_a_variation_in_each(self):
        plan = dict(clip='a100_000000', source='a000_000000', duplicator=str(self.duplicator),
                    behavior=dict(read=str(self.game / 'c1010.behbnd.dcx'), write=str(self.base / 'out.behbnd.dcx')))
        result = slots.prepare_behavior(plan, self.base / 'behavior', sys.executable)
        self.assertEqual([[row['clipGenerator'] for row in entry['added']] for entry in result['files']],
                         [['a100_000000_hkx_AutoSet_00'], ['a100_000000_hkx_AutoSet_00', 'a100_000000_hkx_AutoSet_01']])
        rebuilt = Binder(result['data'])
        index = slots.behavior_index(havok_xml.to_xml(rebuilt.members[1][2]))
        self.assertEqual(slots.selectors_playing(index, 'a100_000000'), ['IdleDefault_CMSG', 'Init_CMSG'])
        self.assertEqual(sum(PureWindowsPath(path).name == 'a100_000000.hkx' for path in index['paths']), 1)

    def test_an_old_writer_is_named_before_anything_is_written(self):
        def old(command, job, folder, name=None):
            raise RuntimeError('SekiroCharacterWriter tae: tae failed: Unknown command tae.')
        self.writer = old
        with self.assertRaisesRegex(RuntimeError, 'older than 0.3.0.*build_decoder.cmd'):
            self.export()
        self.assertFalse(self.mod.parent.exists())

    def test_a_source_that_no_selector_plays_is_refused(self):
        plan = dict(clip='a100_001000', source='a000_001000', duplicator=str(self.duplicator),
                    behavior=dict(read=str(self.game / 'c1010.behbnd.dcx'), write=str(self.base / 'out.behbnd.dcx')))
        with self.assertRaisesRegex(ValueError, 'No selector in c1010.behbnd.dcx plays a000_001000'):
            slots.prepare_behavior(plan, self.base / 'behavior', sys.executable)


if __name__ == '__main__':
    unittest.main()
