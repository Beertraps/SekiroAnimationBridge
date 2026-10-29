"""Preview cache: gzipped results, cached-only requests, and one decode for clips asked for twice at once."""
import gzip
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clip_preview


class PreviewCacheTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='BridgePreviewTest-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in ('a000_000100.hkx', 'skeleton.hkx', 'decoder.exe'):
            (self.root / name).write_bytes(b'x')
        self.selection = dict(animation=str(self.root / 'a000_000100.hkx'), skeleton=str(self.root / 'skeleton.hkx'))
        self.calls = 0

        def decode(paths, decoder, oodle='', samples=0):
            self.calls += 1
            time.sleep(.2)
            return json.dumps(dict(clip=Path(paths[0]).name, samples=samples)).encode('utf-8')
        for name, value in (('decode', decode), ('preview_mode', lambda decoder: True)):
            patcher = unittest.mock.patch.object(clip_preview, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_preview(self, **options):
        return clip_preview.preview(self.selection, str(self.root / 'decoder.exe'), self.root / 'cache', **options)

    def test_a_preview_is_stored_gzipped_and_read_back_without_decoding(self):
        self.assertIsNone(self.run_preview(stored_only=True))
        first = self.run_preview()
        self.assertEqual(json.loads(gzip.decompress(first)), dict(clip='a000_000100.hkx', samples=clip_preview.LIMIT))
        self.assertEqual(self.run_preview(stored_only=True), first)
        self.assertEqual(self.run_preview(), first)
        self.assertEqual(self.calls, 1)
        self.assertEqual([p.suffixes for p in (self.root / 'cache').iterdir()], [['.json', '.gz']])

    def test_two_requests_at_once_decode_the_clip_once(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.run_preview())) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(set(results)), 1)


if __name__ == '__main__':
    unittest.main()
