"""What a game package may use from the bridge: API version 1.

A package imports only this module. Its functions get plain dictionaries and paths and a Context as
their last argument; docs/PACKAGES.md describes them, and games.packages calls them.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from games.interchange import check_manifest, check_motion, with_source
from games.space import Space

API_VERSION = 1
# The API versions this bridge loads.
SUPPORTED = (1,)
REQUIRED = ('detect', 'scan', 'inventory', 'selection', 'preview', 'prepare')
OPTIONAL = ('refresh', 'validate', 'preview_key')
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

__all__ = ['API_VERSION', 'Context', 'Space', 'check_manifest', 'check_motion', 'dds_to_png', 'read_json', 'signature', 'with_source',
           'write_json']


def write_json(path, value):
    """Write JSON so that a reader never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + f'.{os.getpid()}.tmp')
    staging.write_text(json.dumps(value), encoding='utf-8')
    staging.replace(path)


def read_json(path):
    """A JSON file's content, or None when it is missing or broken."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def signature(path):
    """Size and modification time of a file, to notice when it changes."""
    stat = Path(path).stat()
    return f'{stat.st_size}:{stat.st_mtime_ns}'


def dds_to_png(paths, output):
    """Convert DDS images into PNG files of the same names in output. Returns a problem to report, or ''."""
    from soulstruct.base.textures.texconv import texconv
    paths = [str(p) for p in paths]
    for start in range(0, len(paths), 40):
        result = texconv('-ft', 'png', '-o', str(output), '-y', '-nologo', *paths[start:start + 40])
        if result.returncode:
            lines = result.stdout.decode(errors='replace').strip().splitlines()
            return 'Some textures could not be converted' + (': ' + lines[-1] if lines else '.')
    return ''


def tool_environment(environ=None):
    """The environment for a package's tool: the bridge's shared .NET runtime when there is one."""
    environ = dict(os.environ if environ is None else environ)
    try:
        from dotnet_runtime import configure
    except ImportError:
        return environ
    configure(environ)
    return environ


class Context:
    """What the bridge hands a package's functions: its cache, progress messages, its games and its tools."""

    def __init__(self, package, cache, notify=None):
        self.package = package
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._notify = notify or (lambda *args, **kwargs: None)

    @property
    def profiles(self):
        """The package's games, as GameProfile objects."""
        return list(self.package.profiles)

    def profile(self, game):
        found = next((p for p in self.package.profiles if p.id == game), None)
        if found is None:
            raise ValueError(f'{self.package.name} has no game {game!r}. Its games: '
                             f'{", ".join(p.id for p in self.package.profiles)}.')
        return found

    def notify(self, stage, message, percent=0):
        """Report progress: stage is one of inventory, decode, character; percent is 0 to 100."""
        self._notify(stage, message, int(percent))

    def tool(self, tool_id):
        """The path of one of the package's tools; a clear error when it is missing."""
        return self.package.tool_path(tool_id)

    def run(self, tool_id, *args, timeout=900):
        """Run one of the package's tools and return what it printed. A failure raises ValueError with its last line."""
        path = self.tool(tool_id)
        name = self.package.tool(tool_id).get('name') or tool_id
        label = f'{name} {args[0]}' if args else name
        command = [str(path), *[str(a) for a in args]]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    creationflags=HIDDEN, timeout=timeout, env=tool_environment())
        except subprocess.TimeoutExpired:
            raise ValueError(f'{label} did not finish within {timeout} seconds.') from None
        except OSError as exc:
            raise ValueError(f'{name} could not start: {exc}') from None
        if result.returncode:
            # A tool's error is its last line on stderr, or on stdout when it writes errors there.
            lines = ([line for line in result.stderr.splitlines() if line.strip()]
                     or [line for line in result.stdout.splitlines() if line.strip()])
            raise ValueError(f'{label} failed: ' + (lines[-1] if lines else f'exit code {result.returncode}'))
        return result.stdout
