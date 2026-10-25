"""Retarget donor options of a two-character import, without Blender or game files."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_ui
from bridge_runtime import EVENT_PREFIX, add_donor_report, discover_source, donor_event, donor_request


class DonorRequest(unittest.TestCase):
    def test_donor_shares_the_tools_and_keeps_its_own_inputs(self):
        request = dict(decoder='decoder.exe', oodle='oo2core_6_win64.dll', weaponAttachments={'wp_a_0300': 'right'},
                       game='sekiro', assetClip='a000_000100', outputBlend='target.blend', partAnimations=True,
                       donor=dict(inputMethod='folder', assetFolder=r'D:\Elden Ring', game='er', assetClip='a000_003000'))
        donor = donor_request(request)
        self.assertEqual((donor['decoder'], donor['oodle'], donor['weaponAttachments']),
                         ('decoder.exe', 'oo2core_6_win64.dll', {'wp_a_0300': 'right'}))
        self.assertEqual((donor['inputMethod'], donor['assetFolder'], donor['game'], donor['assetClip']),
                         ('folder', r'D:\Elden Ring', 'er', 'a000_003000'))
        self.assertNotIn('outputBlend', donor)
        # The bake reads no part clips.
        self.assertIs(donor['partAnimations'], False)

    def test_donor_weapon_placement_overrides_the_targets(self):
        donor = donor_request(dict(weaponAttachments={'wp_a_0300': 'right'}, donor=dict(weaponAttachments={'wp_a_0300': 'back'})))
        self.assertEqual(donor['weaponAttachments'], {'wp_a_0300': 'back'})

    def test_donor_must_be_a_set_of_input_options(self):
        with self.assertRaisesRegex(ValueError, 'retarget donor must be a set of input options'):
            donor_request(dict(donor='a000_003000'))

    def test_donor_progress_runs_between_the_targets_character_and_blender(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for progress in (0, 15, 32, 100):
                donor_event('decode', 'Decoding animation and skeleton', progress)
        events = [json.loads(line[len(EVENT_PREFIX):]) for line in output.getvalue().splitlines()]
        self.assertEqual([event['message'] for event in events], ['Donor: Decoding animation and skeleton'] * 4)
        self.assertEqual([event['progress'] for event in events], [40, 47, 56, 60])

    def test_donor_folder_scan_reports_as_the_donors(self):
        def discover(folder, cache, notify, *args):
            notify('inventory', 'Reading c5060.anibnd.dcx (1/1)', 8)
            return Path('catalog.json'), dict(layout='folder')
        output = io.StringIO()
        with mock.patch('asset_discovery.discover', discover), contextlib.redirect_stdout(output):
            discover_source(dict(assetFolder=r'D:\Owl'), donor_event)
        scanned = json.loads(output.getvalue()[len(EVENT_PREFIX):])
        self.assertEqual((scanned['message'], scanned['progress']), ('Donor: Reading c5060.anibnd.dcx (1/1)', 44))

    def test_donor_warnings_join_the_targets_marked_as_the_donors(self):
        report = add_donor_report(dict(clip='a000_000100.hkx', frames=24, warnings=['Target notice']),
                                  dict(clip='a000_003000.hkx', frames=40, warnings=['No material library']))
        self.assertEqual(report['warnings'], ['Target notice', 'Donor: No material library'])
        self.assertEqual(report['donor'], dict(clip='a000_003000.hkx', frames=40))


class DonorSettings(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for name, value in (('SETTINGS', Path(temp.name) / 'ui-settings.json'), ('SOURCES', Path(temp.name) / 'ui-sources.json'),
                            ('CONFIG', {})):
            patch = mock.patch.object(bridge_ui, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_pinned_donor_is_kept_and_reaches_the_job(self):
        donor = dict(inputMethod='folder', assetFolder=r'D:\Owl', assetClip='a000_003041', label='a000_003041')
        bridge_ui.persist(dict(bridge_ui.defaults(), donor=donor))
        self.assertEqual(bridge_ui.defaults()['donor'], donor)
        self.assertIn('donor', bridge_ui.KEYS)
        bridge_ui.persist(dict(bridge_ui.defaults(), donor=None))
        self.assertIsNone(bridge_ui.defaults()['donor'])


if __name__ == '__main__':
    unittest.main()
