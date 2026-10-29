"""Game packages: engines outside the bridge, each a folder with a package.json and a Python module.

The bridge loads them from its own packages folder (a source checkout, where authors work) and from
%LOCALAPPDATA%/SekiroAnimationBridge/packages (where installed packages go). PackageEngine serves the
bridge's engine entry points (games.base.GameAdapter) from a package's API version 1 (games.api):
it stores catalogs, caches previews and checks every result against its schema. See docs/PACKAGES.md.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import threading
import types
import zipfile
from pathlib import Path

from games import api
from games.base import Capabilities, GameProfile
from games.interchange import check_manifest, check_motion, check_preview, validate
from games.space import Space

HOME = Path(__file__).resolve().parents[2]
APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
# The bridge's own packages first, so that an author's working copy wins over an installed release.
ROOTS = [HOME / 'packages', APP / 'packages']
CACHE = HOME / 'work' / 'asset-cache'
ID = re.compile(r'[a-z][a-z0-9_]*')
RESERVED = {'fromsoft', 'games', 'packages', 'bridge'}
CAPABILITIES = set(Capabilities.__dataclass_fields__)
# A package ZIP is read whole before anything is extracted; these keep a broken one from filling the disk.
MAX_FILES = 20000
MAX_BYTES = 2 << 30
_LOCK = threading.RLock()


def installed_root():
    """Where installed packages go: the user's packages folder."""
    return Path(ROOTS[-1])


# package.json

def check_package_data(data, label='package.json'):
    """Raise ValueError when a package.json cannot be used by this bridge."""
    if not isinstance(data, dict):
        raise ValueError(f'{label} is not a JSON object.')
    validate(data, 'package.schema.json', label)
    if not ID.fullmatch(data['id']) or data['id'] in RESERVED:
        raise ValueError(f'{label}: the id must be lower case letters, digits and _, starting with a letter, and not '
                         f'{", ".join(sorted(RESERVED))}.')
    if data['apiVersion'] not in api.SUPPORTED:
        raise ValueError(f'{data["name"]} needs package API version {data["apiVersion"]}; this bridge supports '
                         f'{", ".join(map(str, api.SUPPORTED))}. Update the bridge or the package.')
    games = [g['id'] for g in data['games']]
    if len(set(games)) != len(games) or not all(ID.fullmatch(g) for g in games):
        raise ValueError(f'{label}: game ids must be unique lower case names.')
    for game in data['games']:
        unknown = set(game.get('capabilities') or {}) - CAPABILITIES
        if unknown:
            raise ValueError(f'{label}: unknown capabilities {", ".join(sorted(unknown))}.')
        Space(game.get('basis', ((1, 0, 0), (0, 1, 0), (0, 0, 1))), game.get('unitScale', 1.0))
    tools = [t['id'] for t in data.get('tools') or []]
    if len(set(tools)) != len(tools):
        raise ValueError(f'{label}: tool ids must be unique.')
    for tool in data.get('tools') or []:
        parts = Path(tool['path']).parts
        if Path(tool['path']).is_absolute() or '..' in parts or (parts and ':' in parts[0]):
            raise ValueError(f'{label}: the path of tool {tool["id"]} must stay inside the package.')
    for pattern in (data.get('bones') or {}).get('patterns') or []:
        try:
            re.compile(pattern['match'])
        except re.error as exc:
            raise ValueError(f'{label}: the bone pattern {pattern["match"]!r} is not a valid regular expression ({exc}).') from None
    return data


def read_manifest(folder):
    folder = Path(folder)
    try:
        data = json.loads((folder / 'package.json').read_text(encoding='utf-8-sig'))
    except ValueError as exc:
        raise ValueError(f'{folder.name}/package.json is not valid JSON: {exc}') from None
    return check_package_data(data, f'{folder.name}/package.json')


def profile_from_json(data, package, bones=None):
    """A package's game as a GameProfile. Package games never export."""
    defaults = dict(export=False, add_to_binder=False, weapons=False, part_animations=False)
    return GameProfile(
        id=data['id'], name=data['name'], short=data['short'], engine=package,
        executables=tuple(e.lower() for e in data.get('executables', [])),
        capabilities=Capabilities(**{**defaults, **(data.get('capabilities') or {})}),
        basis=tuple(tuple(float(v) for v in row) for row in data.get('basis', ((1, 0, 0), (0, 1, 0), (0, 0, 1)))),
        unit_scale=float(data.get('unitScale', 1.0)), formats=dict(data.get('formats') or {}), hint=data.get('hint', ''),
        verified=bool(data.get('verified', False)), documentation=data.get('documentation', ''), package=package,
        bones=dict(bones or {}))


class Package:
    """A package folder: its manifest, games and tools. error says why it cannot be used."""

    def __init__(self, folder, manifest=None, error=''):
        self.folder = Path(folder)
        self.manifest = manifest or {}
        self.error = error
        self.id = self.manifest.get('id') or self.folder.name
        self.name = self.manifest.get('name') or self.id
        self.version = self.manifest.get('version', '')
        # The folder of another package with the same ID, which is used instead of this one.
        self.duplicate = ''
        self.problems = []
        self.profiles = () if error else tuple(profile_from_json(g, self.id, self.manifest.get('bones'))
                                                 for g in self.manifest.get('games', []))
        self._module = None

    @property
    def installed(self):
        """True for a package in the user's packages folder, which the Setup page may remove."""
        try:
            return self.folder.resolve().parent == installed_root().resolve()
        except OSError:
            return False

    @property
    def usable(self):
        return not self.error and not self.duplicate

    @property
    def source_options(self):
        return list(self.manifest.get('sourceOptions') or [])

    @property
    def tools(self):
        return list(self.manifest.get('tools') or [])

    def tool(self, tool_id):
        found = next((t for t in self.tools if t['id'] == tool_id), None)
        if found is None:
            raise ValueError(f'{self.name} declares no tool {tool_id!r} in its package.json.')
        return found

    def tool_path(self, tool_id):
        tool = self.tool(tool_id)
        path = (self.folder / tool['path']).resolve()
        if not path.is_file():
            build = tool.get('build')
            how = (f'Build it with {(self.folder / build)}.' if build and (self.folder / build).is_file()
                   else 'Install the package again from its release ZIP.')
            raise ValueError(f'{tool["name"]} is missing: {path}. {how}')
        return path

    def tool_status(self, tool):
        """(ready, detail) of one tool, for the Setup page."""
        try:
            path = self.tool_path(tool['id'])
        except ValueError as exc:
            return False, str(exc)
        if not tool.get('version'):
            return True, str(path)
        import subprocess
        try:
            result = subprocess.run([str(path), *tool['version']], capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', creationflags=api.HIDDEN, timeout=15, env=api.tool_environment())
        except (OSError, subprocess.TimeoutExpired):
            return False, f'{tool["name"]} could not start. If it is a .NET program, check the .NET runtime card.'
        line = next((l.strip() for l in result.stdout.splitlines() if l.strip()), '')
        if result.returncode or not line.startswith(tool.get('expect', '')):
            build = f' Rebuild it with {self.folder / tool["build"]}.' if tool.get('build') else ''
            return False, f'{tool["name"]} is from another version ({line or "no version"}).{build}'
        return True, line

    def module(self):
        with _LOCK:
            if self._module is None:
                self._module = load_module(self)
            return self._module

    def summary(self):
        """The package as the Setup page lists it."""
        m = self.manifest
        return dict(id=self.id, name=self.name, version=self.version, description=m.get('description', ''),
                    authors=m.get('authors', []), license=m.get('license', ''), homepage=m.get('homepage', ''),
                    apiVersion=m.get('apiVersion'), folder=str(self.folder), installed=self.installed,
                    games=[dict(id=p.id, name=p.name, verified=p.verified) for p in self.profiles],
                    tools=[dict(id=t['id'], name=t['name']) for t in self.tools], error=self.error,
                    duplicate=self.duplicate, problems=list(self.problems))


def discover_packages(roots=None):
    """Every package folder in the package roots, usable or not. The first folder of an ID is used."""
    found, used = [], {}
    for root in roots or ROOTS:
        root = Path(root)
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(('.', '_'))):
            if not (folder / 'package.json').is_file():
                continue
            try:
                package = Package(folder, read_manifest(folder))
            except (OSError, ValueError) as exc:
                package = Package(folder, error=str(exc))
            if package.id in used:
                package.duplicate = str(used[package.id].folder)
            elif package.usable:
                used[package.id] = package
            found.append(package)
    return found


def unload(package_id):
    """Forget a package's imported modules, so that a reinstalled version is imported afresh."""
    name = f'bridge_packages.{package_id}'
    for key in [k for k in sys.modules if k == name or k.startswith(name + '.')]:
        del sys.modules[key]


def load_module(package):
    """Import a package folder as the module bridge_packages.<id>, so its relative imports work."""
    init = package.folder / '__init__.py'
    if not init.is_file():
        raise ValueError(f'{package.name} has no __init__.py in {package.folder}.')
    if 'bridge_packages' not in sys.modules:
        namespace = types.ModuleType('bridge_packages')
        namespace.__path__ = []
        sys.modules['bridge_packages'] = namespace
    unload(package.id)
    name = f'bridge_packages.{package.id}'
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(package.folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        unload(package.id)
        raise ValueError(f'{package.name} could not be loaded: {type(exc).__name__}: {exc}') from exc
    missing = [f for f in api.REQUIRED if not callable(getattr(module, f, None))]
    if missing:
        unload(package.id)
        raise ValueError(f'{package.name} lacks the package API functions {", ".join(missing)}.')
    return module


# The bridge's engine entry points, served from a package

CHARACTER_DEFAULTS = dict(folder='', bytes=0, model='', count=None)
CLIP_DEFAULTS = dict(archive='', member='', compendium='', skeletonCompendium='')
CATALOG_DEFAULTS = dict(layout='game', warnings=[], parts=[], models=[], materialBinder='', textureDirectory='',
                        referenceModel='', textureFolders=[], materialLibraries=[], referenceModels=[], errorCount=0)
SELECTION_DEFAULTS = dict(skeleton='', compendium='', skeletonCompendium='', materialBinder='', textureDirectory='',
                          characterSource='', textureFolders=[], textureRecursive=False, layout='game', preset='auto',
                          referenceModel='', parts=[], missing=[], model='')


def fresh(defaults):
    """Defaults with their own lists, so that no two documents share one."""
    return {k: list(v) if isinstance(v, list) else v for k, v in defaults.items()}


class PackageEngine:
    """The bridge's engine entry points (games.base.GameAdapter) for one game package."""

    def __init__(self, package):
        self.package = package
        self.ENGINE = package.id

    @property
    def module(self):
        return self.package.module()

    def context(self, cache=None, notify=None):
        return api.Context(self.package, Path(cache or CACHE) / 'packages' / self.package.id, notify)

    def games(self):
        return {p.id for p in self.package.profiles}

    def finish(self, catalog, label):
        """A package's catalog with the bridge's fields, checked against the catalog schema."""
        if not isinstance(catalog, dict):
            raise ValueError(f'{self.package.name} returned no catalog.')
        catalog = {**fresh(CATALOG_DEFAULTS), **catalog, 'engine': self.package.id, 'package': self.package.id}
        catalog.setdefault('games', [catalog.get('game', '')])
        for entry in catalog.get('characters') or []:
            for key, value in CHARACTER_DEFAULTS.items():
                entry.setdefault(key, value)
            entry.setdefault('character', entry.get('id', ''))
            entry.setdefault('game', catalog.get('game', ''))
            entry.setdefault('archiveCount', len(entry.get('archives') or []))
        for clip in catalog.get('clips') or []:
            for key, value in CLIP_DEFAULTS.items():
                clip.setdefault(key, value)
            clip.setdefault('scope', catalog.get('folder', ''))
        catalog.setdefault('archiveCount', sum(c.get('archiveCount', 0) for c in catalog.get('characters') or []))
        validate(catalog, 'catalog.schema.json', f'{self.package.name}: {label}')
        if catalog['game'] not in self.games():
            raise ValueError(f'{self.package.name}: {label} names the game {catalog["game"]!r}, which the package does not declare.')
        return catalog

    def detect(self, path, file_list=''):
        found = self.module.detect(str(path), dict(fileList=str(file_list or '')), self.context())
        if not found:
            return None
        if found.get('game') not in self.games():
            raise ValueError(f'{self.package.name} detected the game {found.get("game")!r}, which its package.json does not declare.')
        root = str(found.get('root') or path)
        options = list(found.get('options') or [])
        defaults = dict(path=str(Path(path).resolve()), root=root, layout='game', folders={}, nested=[], limited=False,
                        name=Path(root).name, counts={}, note='', evidence='', archives=[])
        return {**defaults, **found, 'engine': self.package.id, 'package': self.package.id, 'needsFileList': 'fileList' in options}

    def catalog_path(self, cache, found, options):
        identity = json.dumps(dict(package=self.package.id, root=str(found['root']), options=options), sort_keys=True)
        return Path(cache) / 'catalogs' / f'{self.package.id}-{hashlib.sha256(identity.encode()).hexdigest()[:24]}.json'

    def discover(self, root, cache, notify, found, game='auto', file_list=''):
        chosen = found['game'] if game in ('', 'auto') else game
        if chosen not in self.games():
            raise ValueError(f'{self.package.name} does not read {chosen!r}.')
        options = dict(fileList=str(file_list or ''))
        destination = self.catalog_path(cache, found, options)
        previous = api.read_json(destination)
        if not previous or previous.get('package') != self.package.id:
            previous = None
        catalog = self.module.scan(dict(found, game=chosen), options, self.context(cache, notify), previous)
        catalog = self.finish(catalog, 'the scan')
        api.write_json(destination, catalog)
        return destination, catalog

    def inventory_character(self, catalog_path, catalog, character, cache, notify=lambda *args: None):
        catalog = self.finish(self.module.inventory(catalog, character, self.context(cache, notify)), 'the character list')
        api.write_json(catalog_path, catalog)
        return catalog

    def refresh_clip(self, catalog_path, catalog, clip_id, cache, notify=lambda *args: None):
        refresh = getattr(self.module, 'refresh', None)
        if not refresh:
            return catalog, clip_id
        updated, clip_id = refresh(catalog, clip_id, self.context(cache, notify))
        if updated is not catalog:
            updated = self.finish(updated, 'the refreshed catalog')
            api.write_json(catalog_path, updated)
        return updated, clip_id

    def load_catalog(self, catalog, folder, check_sources=False):
        if catalog.get('package') != self.package.id:
            raise ValueError('This scan was created by an older bridge version. Scan the source again.')
        validate(catalog, 'catalog.schema.json', 'The stored scan')
        stored, chosen = Path(catalog['folder']).resolve(), Path(folder).resolve()
        if stored != chosen and chosen not in stored.parents:
            raise ValueError('This scan belongs to another folder. Scan the selected folder again.')
        check = getattr(self.module, 'validate', None)
        if check:
            check(catalog, folder, check_sources, self.context())
        return catalog

    def selection(self, catalog, clip_id, preset='auto'):
        chosen = self.module.selection(catalog, clip_id, preset, self.context())
        missing = [k for k in ('animation', 'game', 'character', 'clipName') if not isinstance(chosen.get(k), str)]
        if missing:
            raise ValueError(f'{self.package.name}: the selection lacks {", ".join(missing)}.')
        return {**fresh(SELECTION_DEFAULTS), **chosen, 'engine': self.package.id}

    def preview_key(self, selection, ctx):
        custom = getattr(self.module, 'preview_key', None)
        if custom:
            return str(custom(selection, ctx))
        files = []
        for path in [selection.get('animation', '')] + [str(self.package.folder / t['path']) for t in self.package.tools]:
            files.append((path, api.signature(path) if path and Path(path).is_file() else ''))
        return json.dumps([self.package.id, self.package.version, selection, files], sort_keys=True, default=str)

    def preview(self, selection, cache, decoder='', oodle='', stored_only=False):
        ctx = self.context()
        key = hashlib.sha256(self.preview_key(selection, ctx).encode()).hexdigest()[:32]
        stored = Path(cache) / f'{self.package.id}-{key}.json.gz'
        try:
            data = stored.read_bytes()
            os.utime(stored)
            return data
        except OSError:
            if stored_only:
                return None
        motion = check_motion(self.module.preview(selection, ctx), f'{self.package.name}: the preview motion')
        from clip_preview import motion_preview
        result = check_preview(motion_preview(motion), f'{self.package.name}: the preview')
        data = gzip.compress(json.dumps(result, separators=(',', ':')).encode('utf-8'), compresslevel=1)
        stored.parent.mkdir(parents=True, exist_ok=True)
        staging = stored.with_name(stored.name + f'.{os.getpid()}-{threading.get_ident()}.tmp')
        staging.write_bytes(data)
        staging.replace(stored)
        return data

    def prepare(self, request, catalog_path, catalog, temp, event):
        result = self.module.prepare(request, catalog, Path(temp), self.context(CACHE, event))
        if not isinstance(result, dict) or not result.get('motion'):
            raise ValueError(f'{self.package.name}: prepare returned no motion.')
        if result.get('catalog') is not None:
            api.write_json(catalog_path, self.finish(result['catalog'], 'the catalog after the import'))
        updates = result.get('request') or {}
        if updates.get('game', request.get('game')) not in (*self.games(), 'auto', '', None):
            raise ValueError(f'{self.package.name}: prepare named a game it does not declare.')
        request.update(updates)
        motion_path = Path(result['motion'])
        check_motion(json.loads(motion_path.read_text(encoding='utf-8')), f'{self.package.name}: the motion JSON')
        manifests = [Path(p) for p in result.get('characters') or []]
        if len(manifests) > 1:
            raise ValueError(f'{self.package.name}: package API version 1 imports one character manifest per clip.')
        for manifest in manifests:
            check_manifest(json.loads(manifest.read_text(encoding='utf-8')), f'{self.package.name}: the character manifest')
        game = request.get('game', '')
        report = dict(parts=0, textures=0, warnings=[], catalogRefreshed=False, compression='',
                      game=next((p.name for p in self.package.profiles if p.id == game), game))
        report.update(result.get('report') or {})
        character_args = [arg for manifest in manifests for arg in ('--character-manifest', manifest)]
        return motion_path, character_args, report


# Installing and removing

def zip_layout(archive):
    """The files of a package ZIP and the folder prefix of its package.json, checked for path tricks."""
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
        raise ValueError('This ZIP is too large for a game package.')
    names = []
    for info in infos:
        name = info.filename.replace('\\', '/')
        parts = name.split('/')
        if name.startswith('/') or '..' in parts or ':' in parts[0]:
            raise ValueError(f'The ZIP holds an unsafe path: {info.filename}')
        names.append(name)
    manifests = [n for n in names if n == 'package.json' or (n.count('/') == 1 and n.endswith('/package.json'))]
    if len(manifests) != 1:
        raise ValueError('A package ZIP holds one package.json, at its root or in one top folder.')
    prefix = manifests[0][:-len('package.json')]
    if any(not n.startswith(prefix) for n in names):
        raise ValueError('Every file of a package ZIP must be inside the package folder.')
    return list(zip(infos, names)), prefix, manifests[0]


def inspect_zip(path):
    """What a package ZIP holds, read without running anything from it."""
    path = Path(path)
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise ValueError(f'Choose a game package ZIP file.\n{path}')
    with zipfile.ZipFile(path) as archive:
        files, prefix, manifest = zip_layout(archive)
        try:
            data = json.loads(archive.read(manifest).decode('utf-8-sig'))
        except ValueError as exc:
            raise ValueError(f'The package.json in the ZIP is not valid JSON: {exc}') from None
    check_package_data(data, 'The package.json in the ZIP')
    current = next((p for p in discover_packages() if p.id == data['id'] and not p.duplicate), None)
    return dict(id=data['id'], name=data['name'], version=data['version'], description=data.get('description', ''),
                authors=data.get('authors', []), license=data.get('license', ''), homepage=data.get('homepage', ''),
                games=[g['name'] for g in data['games']], tools=[t['name'] for t in data.get('tools') or []],
                files=len(files), bytes=sum(i.file_size for i, _ in files),
                replaces=current.version if current and current.installed else '',
                shadowedBy=str(current.folder) if current and not current.installed else '')


def install_zip(path):
    """Extract a package ZIP into the user's packages folder, replacing an installed version of it."""
    info = inspect_zip(path)
    root = installed_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / info['id']
    staging = root / f'.staging-{info["id"]}-{os.getpid()}'
    old = root / f'.old-{info["id"]}-{os.getpid()}'
    shutil.rmtree(staging, ignore_errors=True)
    with _LOCK:
        try:
            with zipfile.ZipFile(path) as archive:
                files, prefix, _ = zip_layout(archive)
                for item, name in files:
                    destination = (staging / name[len(prefix):]).resolve()
                    if staging.resolve() not in destination.parents:
                        raise ValueError(f'The ZIP holds an unsafe path: {item.filename}')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, open(destination, 'wb') as output:
                        shutil.copyfileobj(source, output)
            check_package_data(json.loads((staging / 'package.json').read_text(encoding='utf-8-sig')))
            unload(info['id'])
            if target.exists():
                target.rename(old)
            staging.rename(target)
        except OSError as exc:
            raise ValueError(f'The package could not be installed: {exc}. Close programs that use its files and try again.') from None
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
    return info


def remove(package_id):
    """Delete an installed package's folder. Packages in the bridge's own folder stay."""
    package = next((p for p in discover_packages() if p.id == package_id and p.installed), None)
    if package is None:
        raise ValueError(f'No installed package {package_id!r}. Packages in the bridge folder are removed by deleting their folder.')
    with _LOCK:
        unload(package_id)
        try:
            shutil.rmtree(package.folder)
        except OSError as exc:
            raise ValueError(f'{package.name} could not be removed: {exc}. Close programs that use its files and try again.') from None
    return package.summary()
