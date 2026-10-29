"""Cache cleanup: what no source uses goes, what a source or a running scan may need stays."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache_cleanup
from cache_cleanup import catalogs_in_use, clean, unused, usage

OLD = time.time() - 2 * cache_cleanup.RECENT


class CacheCleanupTests(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp(prefix='BridgeCacheTest-'))
        self.addCleanup(shutil.rmtree, self.cache, ignore_errors=True)

    def archive(self, key, age=OLD):
        member = self.cache / 'archives' / key / '00000' / 'a000_000000.hkx'
        member.parent.mkdir(parents=True)
        member.write_bytes(b'x' * 100)
        for path in (member, member.parent, member.parent.parent):
            os.utime(path, (age, age))
        return member

    def catalog(self, name, members, age=OLD):
        path = self.cache / 'catalogs' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(clips=[dict(path=str(m)) for m in members])), encoding='utf-8')
        os.utime(path, (age, age))
        return path

    def test_a_catalog_and_its_archives_stay_while_a_source_names_it(self):
        used, stale = self.archive('a' * 24), self.archive('b' * 24)
        kept = self.catalog('k.json', [used])
        dropped = self.catalog('d.json', [stale])
        settings = dict(sources=[dict(catalog=str(kept))])
        found = unused(self.cache, settings)
        self.assertEqual(found['catalogs'], [dropped])
        self.assertEqual(found['archives'], [self.cache / 'archives' / ('b' * 24)])
        self.assertGreater(clean(self.cache, settings), 0)
        self.assertTrue(used.is_file() and kept.is_file())
        self.assertFalse(stale.exists() or dropped.exists())

    def test_the_selection_and_the_donor_keep_their_catalogs(self):
        settings = dict(sources=[{}], assetCatalog='C:\\x\\One.json', donor=dict(assetCatalog='C:\\x\\two.json'))
        self.assertEqual(catalogs_in_use(settings), {'one.json', 'two.json'})

    def test_recent_files_stay_for_a_scan_that_is_not_saved_yet(self):
        self.archive('c' * 24, age=time.time())
        self.catalog('new.json', [self.archive('d' * 24)], age=time.time())
        found = unused(self.cache, {})
        self.assertEqual(found, dict(catalogs=[], archives=[], previews=[]))

    def test_previews_over_the_limit_go_least_recently_shown_first(self):
        folder = self.cache / 'previews'
        folder.mkdir()
        for index, name in enumerate(('newest', 'older', 'oldest')):
            path = folder / f'{name}.json.gz'
            path.write_bytes(b'x' * 60)
            os.utime(path, (OLD - index, OLD - index))
        with unittest.mock.patch.object(cache_cleanup, 'PREVIEW_LIMIT', 130):
            self.assertEqual([p.name for p in unused(self.cache, {})['previews']], ['oldest.json.gz'])
            # Aggressive caching keeps more.
            self.assertEqual(unused(self.cache, dict(previewCache='aggressive'))['previews'], [])

    def test_previews_of_an_older_bridge_and_staging_files_go(self):
        folder = self.cache / 'previews'
        folder.mkdir()
        for name, age in (('old.json', OLD), ('left.json.gz.1-2.tmp', OLD), ('writing.json.gz.3-4.tmp', time.time()), ('kept.json.gz', OLD)):
            (folder / name).write_bytes(b'x')
            os.utime(folder / name, (age, age))
        self.assertEqual(sorted(p.name for p in unused(self.cache, {})['previews']), ['left.json.gz.1-2.tmp', 'old.json'])

    def test_cleanup_stops_when_it_is_no_longer_allowed(self):
        self.archive('e' * 24)
        self.assertEqual(clean(self.cache, {}, allowed=lambda: False), 0)
        self.assertTrue((self.cache / 'archives' / ('e' * 24)).is_dir())
        self.assertEqual(usage(self.cache, {})['unused'], 100)


if __name__ == '__main__':
    unittest.main()
