"""tools/package_game_package.py: what a game package ZIP holds and what it refuses."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import package_game_package

TOOL = {'id': 'decoder', 'name': 'Example decoder', 'path': 'tools/example-decoder/ExampleDecoder.exe',
        'version': ['--version'], 'expect': 'ExampleDecoder 1', 'runtime': 'dotnet-9', 'build': 'decoder/build.cmd'}


class PackageGamePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.folder, self.built, self.output = base / 'example', base / 'built', base / 'dist/example.zip'
        self.write_manifest()
        for name in ['__init__.py', 'reader.py', 'README.md', 'decoder/build.cmd', 'decoder/Program.cs', 'tests/test_reader.py',
                     '__pycache__/reader.cpython-312.pyc', 'decoder/bin/Release/x.dll', 'decoder/obj/project.assets.json',
                     '.git/HEAD', 'tools/example-decoder/Stale.dll']:
            (self.folder / name).parent.mkdir(parents=True, exist_ok=True)
            (self.folder / name).write_text(name, encoding='utf-8')
        for name in ['ExampleDecoder.exe', 'ExampleDecoder.dll', 'runtimes/win-x64/native.dll']:
            (self.built / name).parent.mkdir(parents=True, exist_ok=True)
            (self.built / name).write_bytes(b'built ' + name.encode())

    def write_manifest(self, drop=(), **changes):
        data = {'id': 'example', 'name': 'Example', 'version': '1.2.0', 'apiVersion': 1, 'games': [], 'tools': [TOOL]}
        data.update(changes)
        for key in drop:
            del data[key]
        self.folder.mkdir(exist_ok=True)
        (self.folder / 'package.json').write_text(json.dumps(data), encoding='utf-8')

    def package(self, tools=()):
        with contextlib.redirect_stdout(io.StringIO()):
            return package_game_package.package(self.folder, self.output, tools)

    def test_zip_holds_the_package_and_its_built_tool(self):
        self.package([('decoder', self.built)])
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(names, ['example/README.md', 'example/__init__.py', 'example/decoder/Program.cs',
                                     'example/decoder/build.cmd', 'example/package.json', 'example/reader.py',
                                     'example/tests/test_reader.py', 'example/tools/example-decoder/ExampleDecoder.dll',
                                     'example/tools/example-decoder/ExampleDecoder.exe',
                                     'example/tools/example-decoder/runtimes/win-x64/native.dll'])
            self.assertTrue(all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist()))
            self.assertEqual(archive.read('example/tools/example-decoder/ExampleDecoder.exe'), b'built ExampleDecoder.exe')

    def test_without_tools_the_zip_has_no_tools_folder(self):
        self.package()
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(name.startswith('example/tools/') for name in archive.namelist()))
            self.assertIn('example/package.json', archive.namelist())

    def test_the_built_folder_must_hold_the_tool(self):
        (self.built / 'ExampleDecoder.exe').unlink()
        with self.assertRaisesRegex(ValueError, 'No ExampleDecoder.exe'):
            self.package([('decoder', self.built)])
        with self.assertRaisesRegex(ValueError, "no tool 'other'"):
            self.package([('other', self.built)])

    def test_tool_paths_stay_inside_the_package(self):
        for path in ['../outside/Tool.exe', 'C:/Tools/Tool.exe', '/tools/Tool.exe']:
            self.write_manifest(tools=[dict(TOOL, path=path)])
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'inside the package'):
                self.package([('decoder', self.built)])

    def test_manifest_needs_identity_and_a_valid_id(self):
        self.write_manifest(drop=('version', 'apiVersion'))
        with self.assertRaisesRegex(ValueError, 'lacks version, apiVersion'):
            self.package()
        for package_id in ['Example', '1example', 'ex-ample', '', 'example\n']:
            self.write_manifest(id=package_id)
            with self.subTest(id=package_id), self.assertRaisesRegex(ValueError, 'package ID'):
                self.package()

    def test_output_inside_the_package_is_refused(self):
        self.output = self.folder / 'example.zip'
        with self.assertRaisesRegex(ValueError, 'outside the package folder'):
            self.package()

    def test_tool_argument(self):
        self.assertEqual(package_game_package.tool_argument('decoder=C:\\built\\x'), ('decoder', Path('C:\\built\\x')))
        for text in ['decoder', '=C:\\built', 'decoder=']:
            with self.assertRaises(argparse.ArgumentTypeError):
                package_game_package.tool_argument(text)


if __name__ == '__main__':
    unittest.main()
