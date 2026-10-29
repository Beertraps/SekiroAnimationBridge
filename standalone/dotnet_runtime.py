"""The .NET 9 runtime that the bridge's framework-dependent tools share.

A release ZIP holds it in dotnet-runtime/; a source checkout prepares it with tools/prepare_dotnet_runtime.cmd.
The tools find it through DOTNET_ROOT, which configure() sets for every program the bridge starts."""
import os
import re
import subprocess
from pathlib import Path

ROOTS = [Path(__file__).resolve().parents[1] / 'dotnet-runtime',
         Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge' / 'dotnet-runtime']
SYSTEM_RUNTIME = re.compile(r'^Microsoft\.NETCore\.App (9\.\d+\.\d+\S*) \[(.+)\]\s*$', re.M)


def _version(name):
    return tuple(int(part) for part in re.findall(r'\d+', name)[:3])


def find():
    """The first runtime folder with a host/fxr/<version>/hostfxr.dll, else None."""
    for root in ROOTS:
        if any((root / 'host' / 'fxr').glob('*/hostfxr.dll')):
            return root
    return None


def configure(environ=os.environ):
    """Point DOTNET_ROOT at the shared runtime and return the runtime folder the tools will use.

    A DOTNET_ROOT or DOTNET_ROOT_X64 that already names an existing folder is kept and returned."""
    for key in ('DOTNET_ROOT_X64', 'DOTNET_ROOT'):
        if environ.get(key) and Path(environ[key]).is_dir():
            return Path(environ[key])
    root = find()
    if root:
        environ['DOTNET_ROOT'] = environ['DOTNET_ROOT_X64'] = str(root)
    return root


def status():
    """(ready, detail) for the Setup card ".NET runtime"."""
    root = find()
    if root:
        versions = sorted((p.name for p in (root / 'shared' / 'Microsoft.NETCore.App').glob('9.*') if p.is_dir()), key=_version)
        if versions:
            return True, f'Shared runtime {versions[-1]} · {root}'
    try:
        result = subprocess.run(['dotnet', '--list-runtimes'], capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        found = SYSTEM_RUNTIME.findall(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        found = []
    if found:
        version, folder = max(found, key=lambda item: _version(item[0]))
        return True, f'System runtime {version} · {folder}'
    return False, ('The .NET tools need the .NET 9 runtime. Use a release ZIP, which includes it, '
                   'or run tools\\prepare_dotnet_runtime.cmd.')
