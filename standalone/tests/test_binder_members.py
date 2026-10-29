"""Adding an exported HKX to an animation binder, on BND4 binders built in memory with Soulstruct."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_runtime
from binder_members import Binder, add_member, backup, path_hash, plan_member

FOLDER = 'N:\\NTC\\data\\Target\\INTERROOT_win64\\chr\\c0000\\hkx\\a05x_compendium\\'
OTHER = 'N:\\NTC\\data\\Target\\INTERROOT_win64\\chr\\c0000\\hkx\\other\\'


def anibnd(members):
    """BND4 bytes of an animation binder like Wolf's: (ID, path, data) members, IDs in order."""
    from soulstruct.containers import Binder as Built, BinderEntry
    from soulstruct.dcx import DCXType
    result = Built(dcx_type=DCXType.Null)
    for ident, path, data in members:
        result.add_entry(BinderEntry(data=data, entry_id=ident, path=path))
    return result.to_bytes()


def wolf_like():
    return anibnd([(7000000, FOLDER + 'a05x.compendium', b'C' * 40),
                   (1050002000, FOLDER + 'a050_002000.hkx', b'A' * 100),
                   (1050002010, FOLDER + 'a050_002010.hkx', b'B' * 30),
                   (1050400000, OTHER + 'a050_400000.hkx', b'D' * 50)])


def names(binder):
    return [PureWindowsPath(member[1]).name for member in binder.members]


class BinderLayout(unittest.TestCase):
    def test_rewrite_keeps_members_and_aligns_data(self):
        binder = Binder(wolf_like())
        written = Binder(binder.to_bytes())
        self.assertEqual([(m[1], m[2], binder.member_id(m)) for m in binder.members],
                         [(m[1], m[2], written.member_id(m)) for m in written.members])
        data = binder.to_bytes()
        offsets = [struct.unpack_from('<I', m[0], written.data_at)[0] for m in written.members]
        self.assertTrue(all(offset % 16 == 0 for offset in offsets), offsets)
        # Rewriting what it wrote gives the same bytes.
        self.assertEqual(Binder(data).to_bytes(), data)

    def test_path_table_finds_every_member(self):
        data = Binder(wolf_like()).to_bytes()
        table, = struct.unpack_from('<q', data, 0x38)
        hashes, groups = struct.unpack_from('<qI', data, table)
        pairs = [struct.unpack_from('<Ii', data, hashes + 8 * i) for i in range(4)]
        binder = Binder(data)
        self.assertEqual(sorted(index for _, index in pairs), [0, 1, 2, 3])
        for value, index in pairs:
            self.assertEqual(value, path_hash(binder.members[index][1]))
        self.assertEqual(path_hash('A\\b'), path_hash('/a/b'))

    def test_not_a_binder(self):
        with self.assertRaisesRegex(ValueError, 'not a BND4'):
            Binder(b'BND3' + bytes(60))


class AddMember(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.source = self.folder / 'c0000_a05x.anibnd'
        self.source.write_bytes(wolf_like())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_replace_member_of_the_same_name(self):
        data, report = add_member(self.source, 'a050_002010.hkx', b'new clip')
        binder = Binder(data)
        self.assertTrue(report['replaced'])
        self.assertEqual(report['id'], 1050002010)
        self.assertEqual(names(binder), names(Binder(wolf_like())))
        self.assertEqual(binder.members[2][2], b'new clip')
        self.assertEqual(binder.members[1][2], b'A' * 100)

    def test_new_member_in_the_clips_folder_with_its_id_in_order(self):
        data, report = add_member(self.folder / 'missing.anibnd', 'a050_300000.hkx', b'new', self.source,
                                  FOLDER + 'a050_002000.hkx')
        binder = Binder(data)
        self.assertFalse(report['replaced'])
        self.assertEqual(report['base'], str(self.source))
        self.assertEqual(names(binder), ['a05x.compendium', 'a050_002000.hkx', 'a050_002010.hkx', 'a050_300000.hkx',
                                         'a050_400000.hkx'])
        self.assertEqual(binder.members[3][1], FOLDER + 'a050_300000.hkx')
        self.assertEqual(binder.member_id(binder.members[3]), 1050300000)

    def test_new_member_goes_where_most_clips_are_without_its_clip(self):
        index, path, ident = plan_member(Binder(wolf_like()), 'a051_000100.hkx')
        self.assertIsNone(index)
        self.assertEqual((path, ident), (FOLDER + 'a051_000100.hkx', 1051000100))

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'aXXX_YYYYYY'):
            add_member(self.source, 'idle.hkx', b'x')
        odd = self.folder / 'odd.anibnd'
        odd.write_bytes(anibnd([(5, FOLDER + 'a050_002000.hkx', b'A')]))
        with self.assertRaisesRegex(ValueError, 'ID scheme'):
            add_member(odd, 'a050_002001.hkx', b'x')
        with self.assertRaisesRegex(ValueError, 'not found'):
            add_member(self.folder / 'missing.anibnd', 'a050_002000.hkx', b'x')

    def test_backup_once(self):
        self.assertEqual(backup(self.source), str(self.source) + '.bak')
        self.source.write_bytes(b'changed')
        self.assertEqual(backup(self.source), '')
        self.assertEqual(Path(str(self.source) + '.bak').read_bytes(), wolf_like())


class ExportRequest(unittest.TestCase):
    def test_binder_request(self):
        self.assertIsNone(bridge_runtime.binder_request({'binder': 'x.anibnd.dcx'}))
        with self.assertRaisesRegex(ValueError, 'Choose the animation binder'):
            bridge_runtime.binder_request({'addToBinder': True})
        with self.assertRaisesRegex(ValueError, 'ending in .anibnd.dcx'):
            bridge_runtime.binder_request({'addToBinder': True, 'binder': 'c0000.chrbnd.dcx'})
        with self.assertRaisesRegex(ValueError, 'aXXX_YYYYYY'):
            bridge_runtime.binder_request({'addToBinder': True, 'binder': 'c0000_a05x.anibnd.dcx', 'binderMember': 'idle'})
        path, name = bridge_runtime.binder_request({'addToBinder': True, 'binder': 'c0000_a05x.anibnd.dcx'})
        self.assertEqual((path.name, name), ('c0000_a05x.anibnd.dcx', ''))

    def test_binder_member_defaults_to_the_clip_and_needs_a_start(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'c0000_a05x.anibnd.dcx'
            archive.write_bytes(b'')
            target = (Path(folder) / 'mod' / 'c0000_a05x.anibnd.dcx', '')
            self.assertEqual(bridge_runtime.binder_member(target, dict(clip='a050_002000.hkx', archive=str(archive))),
                             ('a050_002000.hkx', str(archive)))
            with self.assertRaisesRegex(ValueError, 'does not record the archive'):
                bridge_runtime.binder_member(target, dict(clip='a050_002000.hkx'))
            with self.assertRaisesRegex(ValueError, 'not one the game uses'):
                bridge_runtime.binder_member((archive, ''), dict(clip='edited.hkx'))

    def test_game_folder_is_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'sekiro.exe').write_bytes(b'')
            with self.assertRaisesRegex(ValueError, 'outside the game installation'):
                bridge_runtime.binder_request({'addToBinder': True, 'binder': str(Path(folder) / 'chr' / 'c0000.anibnd.dcx')})


if __name__ == '__main__':
    unittest.main()
