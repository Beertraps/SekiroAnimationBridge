"""Finding the shared .NET runtime, pointing DOTNET_ROOT at it and its Setup card."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dotnet_runtime

SYSTEM = ('Microsoft.AspNetCore.App 9.0.22 [C:\\Program Files\\dotnet\\shared\\Microsoft.AspNetCore.App]\n'
          'Microsoft.NETCore.App 8.0.15 [C:\\Program Files\\dotnet\\shared\\Microsoft.NETCore.App]\n'
          'Microsoft.NETCore.App 9.0.6 [C:\\Program Files\\dotnet\\shared\\Microsoft.NETCore.App]\n'
          'Microsoft.NETCore.App 9.0.22 [C:\\Program Files\\dotnet\\shared\\Microsoft.NETCore.App]\n')


def runtime(root, version='9.0.22'):
    """A folder in the layout of tools/prepare_dotnet_runtime.ps1."""
    (root / 'host/fxr' / version).mkdir(parents=True)
    (root / 'host/fxr' / version / 'hostfxr.dll').write_bytes(b'')
    (root / 'shared/Microsoft.NETCore.App' / version).mkdir(parents=True)
    return root


class DotnetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bridge, self.local = self.base / 'bridge/dotnet-runtime', self.base / 'local/dotnet-runtime'
        patcher = mock.patch.object(dotnet_runtime, 'ROOTS', [self.bridge, self.local])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_prefers_the_bridge_folder_and_needs_hostfxr(self):
        self.assertIsNone(dotnet_runtime.find())
        (self.bridge / 'host/fxr/9.0.22').mkdir(parents=True)
        runtime(self.local)
        self.assertEqual(dotnet_runtime.find(), self.local)
        (self.bridge / 'host/fxr/9.0.22/hostfxr.dll').write_bytes(b'')
        self.assertEqual(dotnet_runtime.find(), self.bridge)

    def test_configure_sets_both_variables(self):
        runtime(self.local)
        environ = {}
        self.assertEqual(dotnet_runtime.configure(environ), self.local)
        self.assertEqual(environ, {'DOTNET_ROOT': str(self.local), 'DOTNET_ROOT_X64': str(self.local)})

    def test_configure_keeps_an_existing_user_root(self):
        runtime(self.local)
        user = self.base / 'user-dotnet'
        user.mkdir()
        environ = {'DOTNET_ROOT': str(user)}
        self.assertEqual(dotnet_runtime.configure(environ), user)
        self.assertEqual(environ, {'DOTNET_ROOT': str(user)})
        # A DOTNET_ROOT that names a missing folder is replaced.
        environ = {'DOTNET_ROOT': str(self.base / 'missing')}
        self.assertEqual(dotnet_runtime.configure(environ), self.local)
        self.assertEqual(environ['DOTNET_ROOT_X64'], str(self.local))

    def test_configure_without_a_runtime_changes_nothing(self):
        environ = {}
        self.assertIsNone(dotnet_runtime.configure(environ))
        self.assertEqual(environ, {})

    def test_status_names_the_shared_runtime(self):
        runtime(self.bridge, '9.0.6')
        (self.bridge / 'shared/Microsoft.NETCore.App/9.0.22').mkdir()
        with mock.patch('subprocess.run') as run:
            ready, detail = dotnet_runtime.status()
        self.assertTrue(ready)
        self.assertIn('9.0.22', detail)
        self.assertIn(str(self.bridge), detail)
        run.assert_not_called()

    def test_status_accepts_a_system_runtime(self):
        with mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, SYSTEM, '')):
            ready, detail = dotnet_runtime.status()
        self.assertTrue(ready)
        self.assertIn('System runtime 9.0.22', detail)

    def test_status_explains_what_to_do(self):
        older = SYSTEM.replace('9.0.', '8.0.')
        for outcome in [dict(return_value=subprocess.CompletedProcess([], 0, older, '')),
                        dict(side_effect=FileNotFoundError('dotnet')), dict(side_effect=subprocess.TimeoutExpired('dotnet', 15))]:
            with mock.patch('subprocess.run', **outcome):
                ready, detail = dotnet_runtime.status()
            self.assertFalse(ready)
            self.assertIn('prepare_dotnet_runtime.cmd', detail)
            self.assertIn('release ZIP', detail)


if __name__ == '__main__':
    unittest.main()
