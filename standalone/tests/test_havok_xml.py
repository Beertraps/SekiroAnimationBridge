"""Havok tagfile <-> XML conversion on synthetic types and objects; no game files.

Ported with havok_xml from the sekiro-modding plugin (tests/test_havok.py, TagfileTests, on its branch
codex/optional-animation-tools, commit 72b960f), with the author's permission.
"""
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import havok_xml as havok
from havok_xml import ModdingError

INT8, INT32, UINT16, BOOL8 = 8708, 33284, 16388, 8194


def layout_builder():
    """(types, add): add(name, format, size, align, ...) defines a type in types by its full name, as a tagfile would."""
    types = {}

    def add(name, fmt=None, size=None, align=None, parent=None, subtype=None, params=(), fields=None, **extra):
        t = havok.HType(name)
        t.params = [(n, types[v] if n.startswith('t') else v) for n, v in params]
        t.parent = types[parent] if parent else None
        t.format, t.size, t.align = fmt, size, align
        t.subtype = types[subtype] if subtype else None
        t.fields = list(fields or [])
        t.version, t.flags, t.hash = extra.get('version'), extra.get('flags'), extra.get('hash')
        t.opt = ((havok.HAS_FORMAT if fmt is not None else 0)
                 | (havok.HAS_SUBTYPE if subtype or extra.get('null_subtype') else 0)
                 | (havok.HAS_VERSION if t.version is not None else 0)
                 | (havok.HAS_SIZE if size is not None else 0)
                 | (havok.HAS_FLAGS if t.flags is not None else 0)
                 | (havok.HAS_FIELDS if fields is not None else 0))
        types[t.full_name()] = t
        return t

    return types, add


def layouts_of(types):
    layouts = havok.Layouts()
    layouts.types = types
    return layouts


def synthetic_layouts():
    """Invented types in the shapes behaviors use: inheritance, strings, pointers (with a cycle), arrays of pointers
    and floats, a fixed-size array, a non-serialized field, a version and a hash."""
    types, add = layout_builder()
    add('char', INT8, 1, 1)
    add('int', INT32, 4, 4)
    add('unsigned short', UINT16, 2, 2)
    add('float', havok.FLOAT32, 4, 4)
    add('hkBool', BOOL8, 1, 1)
    add('const char*', havok.STRING, 8, 8)
    add('hkContainerHeapAllocator', havok.RECORD, 1, 1, fields=[])
    base = add('SynthBase', havok.RECORD, 8, 8, fields=[])
    node = add('SynthNode', havok.RECORD, 48, 8, parent='SynthBase', fields=[], version=2)
    pointer = add('T*', havok.POINTER, 8, 8, subtype='SynthNode', params=[('tT', 'SynthNode')])
    floats = add('hkArray', havok.ARRAY, 16, 8, subtype='float',
                 params=[('tT', 'float'), ('tAllocator', 'hkContainerHeapAllocator')])
    pointers = add('hkArray', havok.ARRAY, 16, 8, subtype=pointer.full_name(),
                   params=[('tT', pointer.full_name()), ('tAllocator', 'hkContainerHeapAllocator')])
    triple = add('T[N]', havok.TUPLE | 3 << 8, 12, 4, subtype='float', params=[('tT', 'float'), ('vN', 3)])
    base.fields = [('id', 32, 0, types['int'])]
    node.fields = [('label', 32, 8, types['const char*']), ('next', 32, 16, pointer), ('values', 32, 24, floats),
                   ('cache', 33, 40, types['int'])]
    add('SynthRoot', havok.RECORD, 64, 8, fields=[
        ('name', 32, 0, types['const char*']), ('count', 32, 8, types['int']), ('mask', 32, 12, types['unsigned short']),
        ('enabled', 32, 14, types['hkBool']), ('scale', 32, 16, types['float']), ('weights', 32, 20, triple),
        ('missing', 32, 32, types['const char*']), ('first', 32, 40, pointer), ('children', 32, 48, pointers)],
        hash=0x12345678)
    return layouts_of(types)


def synthetic_xml():
    """The source of the synthetic tagfile, as an editor would hand it in (whitespace, comments and type numbering are
    not what the writer produces)."""
    return """<?xml version="1.0" encoding="utf-8"?>
<hktagfile version="3">
  <type id="type1"><name value="SynthRoot"/></type>
  <type id="type2"><name value="SynthNode"/></type>
  <object id="object1" typeid="type1"> <!-- root -->
    <record>
      <field name="name"><string value="synthetic &amp; root"/></field>
      <field name="count"><integer value="-7"/></field>
      <field name="mask"><integer value="65535"/></field>
      <field name="enabled"><bool value="true"/></field>
      <field name="scale"><real dec="1.5" hex="#3ff8000000000000"/></field>
      <field name="weights"><array count="3" elementtypeid="type9"><real dec="0" hex="#0"/>
        <real dec="-2" hex="#c000000000000000"/><real dec="0.1" hex="#3fb99999a0000000"/></array></field>
      <field name="missing"><string/></field>
      <field name="first"><pointer id="object2"/></field>
      <field name="children"><array count="2" elementtypeid="type7">
        <pointer id="object3"/><pointer id="object0"/></array></field>
    </record>
  </object>
  <object id="object2" typeid="type2">
    <record>
      <field name="id"><integer value="1"/></field>
      <field name="label"><string value="first"/></field>
      <field name="next"><pointer id="object3"/></field>
      <field name="values"><array count="2" elementtypeid="type4"><real dec="2" hex="#4000000000000000"/>
        <real dec="3" hex="#4008000000000000"/></array></field>
    </record>
  </object>
  <object id="object3" typeid="type2">
    <record>
      <field name="id"><integer value="2"/></field>
      <field name="label"><string value=""/></field>
      <field name="next"><pointer id="object2"/></field>
      <field name="values"><array count="0" elementtypeid="type4"></array></field>
    </record>
  </object>
  <object id="object9" typeid="type2"> <!-- unreachable -->
    <record>
      <field name="id"><integer value="9"/></field>
      <field name="label"><string/></field>
      <field name="next"><pointer id="object0"/></field>
      <field name="values"><array count="0" elementtypeid="type4"></array></field>
    </record>
  </object>
</hktagfile>
"""


def sections(data, at=0, end=None, prefix=''):
    """Section paths in file order, read independently of the module under test."""
    end, found = len(data) if end is None else end, []
    while at < end:
        head = struct.unpack_from('>I', data, at)[0]
        key = prefix + data[at + 4:at + 8].decode()
        found.append(key)
        if not head & 0x40000000:
            found += sections(data, at + 8, at + (head & 0x3FFFFFFF), key + '/')
        at += head & 0x3FFFFFFF
    return found


class Tagfile(unittest.TestCase):
    def setUp(self):
        self.layouts = synthetic_layouts()
        self.binary, self.report = havok.to_hkx(synthetic_xml(), self.layouts)

    def test_values_go_where_the_layouts_put_them(self):
        self.assertEqual(sections(self.binary),
                         ['TAG0', 'TAG0/SDKV', 'TAG0/DATA', 'TAG0/TYPE', 'TAG0/TYPE/TPTR', 'TAG0/TYPE/TSTR']
                         + ['TAG0/TYPE/TNA1', 'TAG0/TYPE/FSTR', 'TAG0/TYPE/TBDY', 'TAG0/TYPE/THSH', 'TAG0/TYPE/TPAD']
                         + ['TAG0/INDX', 'TAG0/INDX/ITEM', 'TAG0/INDX/PTCH'])
        self.assertEqual(self.binary[8:24], b'\x40\x00\x00\x10SDKV20160200')
        data = havok.TagFile(self.binary).data
        # The root is the first object, at offset 0 of DATA; SynthRoot's layout gives the offsets.
        self.assertEqual(struct.unpack_from('<iHB', data, 8), (-7, 65535, 1))
        self.assertEqual(struct.unpack_from('<4f', data, 16), (1.5, 0.0, -2.0, struct.unpack('<f', struct.pack('<f', 0.1))[0]))
        self.assertEqual(struct.unpack_from('<I', data, 32), (0,))  # the null string
        tagfile = havok.TagFile(self.binary)
        objects = [item for item in tagfile.items if item.pointed]
        self.assertEqual([item.type.full_name() for item in objects], ['SynthRoot', 'SynthNode', 'SynthNode'])
        self.assertEqual(self.report['objects'], 3)
        self.assertEqual(self.report['unreachable_objects'], 1)
        self.assertEqual([t.hash for t in tagfile.types[1:] if t.hash], [0x12345678])

    def test_the_xml_follows_hkxconverter_numbering(self):
        text = havok.to_xml(self.binary, {})
        names = [line.split('"')[1] for line in text.split('\n') if line.startswith('    <name value=')]
        self.assertEqual(names, ['SynthRoot', 'const char*', 'int', 'unsigned short', 'hkBool', 'float', 'T[N]', 'T*', 'hkArray']
                         + ['char', 'SynthNode', 'hkContainerHeapAllocator', 'SynthBase', 'hkArray'])
        self.assertIn('<field name="name"><string value="synthetic &amp; root"/></field>', text)
        self.assertIn('<real dec="0.1" hex="#3fb99999a0000000"/>', text)
        self.assertIn('<array count="2" elementtypeid="type8"> <!-- ArrayOf T*< SynthNode > -->', text)
        self.assertNotIn('cache', text)  # not serialized
        self.assertNotIn('object4', text)  # the unreachable object is left out
        self.assertTrue(text.endswith('</hktagfile>'))

    def test_a_rebuild_reads_back_the_same_and_is_byte_identical(self):
        text = havok.to_xml(self.binary, {})
        self.assertIsNone(havok.graph_difference(havok.object_graph(synthetic_xml()), havok.object_graph(text)))
        self.assertEqual(havok.to_hkx(text, self.layouts)[0], self.binary)
        stored = havok.Layouts.from_json(json.loads(json.dumps(self.layouts.to_json())))
        self.assertEqual(havok.to_hkx(text, stored)[0], self.binary)
        learned = havok.Layouts.merged([havok.TagFile(self.binary)])
        self.assertEqual(havok.to_hkx(text, learned)[0], self.binary)
        self.assertEqual(learned.conflicts, set())

    def test_core_types_replace_stripped_definitions(self):
        core = havok.core_types()
        self.assertEqual(len(core), 19)
        self.assertEqual(core['hkPropertyBag'].subtype, 'hkDefaultPropertyBag')
        stripped = {'SynthBase': havok.XType('SynthBase', format=7, version=5, fields=[('id', 'int', 32)])}
        self.assertIn('<version value="5"/>', havok.to_xml(self.binary, stripped))

    def test_a_negative_value_in_an_unsigned_field_reads_back_as_the_same_bits(self):
        text = synthetic_xml().replace('<integer value="65535"/>', '<integer value="-1"/>')
        binary, _ = havok.to_hkx(text, self.layouts)
        self.assertEqual(binary, self.binary)
        self.assertIsNone(havok.graph_difference(havok.object_graph(text), havok.object_graph(havok.to_xml(binary, {}))))

    def test_hex_is_used_while_it_agrees_with_dec_and_an_edited_dec_wins(self):
        # 0.1 is not exact in float32: dec rounds it, and hex keeps the exact bits.
        text = synthetic_xml().replace('dec="0.1" hex="#3fb99999a0000000"', 'dec="0.100000001" hex="#3fb99999a0000000"')
        self.assertEqual(havok.to_hkx(text, self.layouts), (self.binary, self.report))
        text = synthetic_xml().replace('dec="1.5"', 'dec="9"')
        binary, report = havok.to_hkx(text, self.layouts)
        self.assertEqual(struct.unpack_from('<f', havok.TagFile(binary).data, 16), (9.0,))
        self.assertEqual(report['real_dec_hex_mismatches'], 1)
        self.assertEqual(report['mismatch_examples'][0]['object'], 'object1')
        self.assertIsNone(havok.graph_difference(havok.object_graph(text), havok.object_graph(havok.to_xml(binary, {}))))
        binary, report = havok.to_hkx(text.replace(' hex="#3ff8000000000000"', ''), self.layouts)
        self.assertEqual(struct.unpack_from('<f', havok.TagFile(binary).data, 16), (9.0,))
        self.assertEqual(report['real_dec_hex_mismatches'], 0)

    def test_the_elements_win_over_a_stale_array_count_and_it_is_reported(self):
        # A real mod's XML removed an element and left the count, so this is reported, not refused.
        text = synthetic_xml().replace('<array count="2" elementtypeid="type4">', '<array count="3">')
        binary, report = havok.to_hkx(text, self.layouts)
        self.assertEqual(binary, self.binary)
        self.assertEqual(report['array_count_mismatches'], 1)
        self.assertEqual(report['mismatch_examples'], [{'kind': 'array count', 'object': 'object2', 'count': '3', 'elements': 2}])

    def test_xml_that_does_not_fit_the_layouts_is_refused(self):
        cases = {
            "No binary layout for Havok type 'Missing'": ('value="SynthRoot"', 'value="Missing"'),
            'do not match its layout': ('<field name="missing"><string/></field>', ''),
            'needs <integer>': ('<integer value="-7"/>', '<string value="-7"/>'),
            'points to missing object object5': ('<pointer id="object2"/></field>', '<pointer id="object5"/></field>'),
            'needs 3 elements': ('<real dec="0" hex="#0"/>', ''),
            'never declare a DOCTYPE': ('<hktagfile', '<!DOCTYPE x><hktagfile'),
            'Not well-formed XML': ('</hktagfile>', ''),
        }
        for message, (old, new) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ModdingError, message):
                self.assertIn(old, synthetic_xml())
                havok.to_hkx(synthetic_xml().replace(old, new, 1), self.layouts)

    def test_damaged_binaries_are_refused(self):
        with self.assertRaisesRegex(ModdingError, 'A Havok packfile'):
            havok.TagFile(b'\x57\xe0\xe0\x57' + bytes(60))
        with self.assertRaisesRegex(ModdingError, 'no TAG0'):
            havok.TagFile(b'<?xml version')
        for damaged in (self.binary[:300], self.binary[:40] + bytes(len(self.binary) - 40)):
            with self.assertRaises(ModdingError):
                havok.to_xml(damaged, {})
        with self.assertRaisesRegex(ModdingError, 'SDK 20150100 is not supported'):
            havok.TagFile(self.binary.replace(b'20160200', b'20150100'))


if __name__ == '__main__':
    unittest.main()
