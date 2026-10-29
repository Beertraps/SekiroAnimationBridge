"""tools/package_release.py: the release ZIP holds the files that the bridge and its tests read."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import package_release


class PackageReleaseTests(unittest.TestCase):
    def test_the_release_holds_the_schemas_and_the_test_fixtures(self):
        # The bridge checks package.json and what a package returns against the schemas, and the release workflow runs
        # these tests from the unpacked ZIP, so a file type that the ZIP leaves out breaks both.
        shipped = set(package_release.members().values())
        needed = [p.relative_to(ROOT).as_posix() for folder in ('standalone/schemas', 'standalone/tests/fixtures')
                  for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        self.assertIn('standalone/schemas/package.schema.json', needed)
        self.assertEqual([name for name in needed if name not in shipped], [])


if __name__ == '__main__':
    unittest.main()
