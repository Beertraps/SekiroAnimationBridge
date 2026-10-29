"""RE Engine games: motlist animations, mesh models, mdf2 materials and tex textures.

A source is the game folder with its PAK archives, or a folder holding an extracted natives folder.
PAK archives store hashes, not names, so a packed source needs the game's file list (such as
DMC5_STM_Release.list); the bridge reads the names it needs from it and extracts those files into
its cache. ReEngineDecoder (tools/ReEngineDecoder, built on REE-Lib) reads the formats and writes
the bridge's interchange: motion JSON version 2 in RE Engine space, and mesh arrays.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import games
from games.interchange import check_motion, with_source
from games.space import RE_ENGINE

ENGINE = 're_engine'
SPACE = RE_ENGINE
CATALOG_SCHEMA = 4
NATIVES = 'natives/x64/'
DECODER_VERSION = 'ReEngineDecoder 0.1'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Characters are the players and enemies that have both animations and models. Weapons and props are left out.
KINDS = ('player', 'enemy')
OWNER = re.compile(r'(pl|em)\d{4}')
# A model folder's name after its ID: pl0100_dante is Dante. em0000_00 is a variant, not a name.
NAMED = re.compile(r'(?:pl|em)\d{4}(?:_c\d{2})?_([a-z][a-z_]*)')
HOME = Path(__file__).resolve().parents[3]
APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
_LOCK = threading.Lock()


def profiles():
    return games.games(ENGINE)


def game_name(game):
    return games.profile(game).name


def default_decoder():
    """The decoder shipped in a release ZIP, otherwise the one tools/ReEngineDecoder/build_decoder.cmd builds."""
    bundled = HOME / 're-decoder/ReEngineDecoder.exe'
    return bundled if bundled.is_file() else APP / 're-decoder/ReEngineDecoder.exe'


def decoder_path(decoder=''):
    path = Path(decoder) if decoder else default_decoder()
    if not path.is_file():
        raise ValueError('The RE Engine decoder is missing. Run tools/ReEngineDecoder/build_decoder.cmd, '
                         'or use a release that includes re-decoder/ReEngineDecoder.exe.')
    return path


def run_decoder(*args, decoder=''):
    """Run one ReEngineDecoder command; its last error line becomes the message."""
    command = [str(decoder_path(decoder)), *[str(a) for a in args]]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=HIDDEN, timeout=900)
    if result.returncode:
        lines = [line for line in (result.stderr + '\n' + result.stdout).splitlines() if line.strip()]
        raise ValueError(f'ReEngineDecoder {args[0]} failed: ' + (lines[-1] if lines else f'exit code {result.returncode}'))
    return result.stdout


def decoder_status(decoder=''):
    """Whether the RE Engine decoder runs, and what it reports, for the setup checks."""
    try:
        path = decoder_path(decoder)
    except ValueError as exc:
        return False, str(exc)
    try:
        result = subprocess.run([str(path), '--version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                creationflags=HIDDEN, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False, 'The RE Engine decoder could not start.'
    if result.returncode or not result.stdout.startswith(DECODER_VERSION):
        return False, 'The RE Engine decoder is from another version. Rebuild it with tools\\ReEngineDecoder\\build_decoder.cmd.'
    return True, result.stdout.strip()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + f'.{os.getpid()}.tmp')
    staging.write_text(json.dumps(value), encoding='utf-8')
    staging.replace(path)


def signature(path):
    stat = Path(path).stat()
    return f'{stat.st_size}:{stat.st_mtime_ns}'


# Detection

def archives(root):
    """The base PAK and its patches in load order: a later patch replaces a file of an earlier one."""
    root = Path(root)
    patches = sorted(root.glob('re_chunk_000.pak.patch_*.pak'),
                     key=lambda p: int(re.search(r'patch_(\d+)', p.name)[1]) if re.search(r'patch_(\d+)', p.name) else 0)
    base = root / 're_chunk_000.pak'
    return [base, *patches] if base.is_file() else []


def executable_profile(root):
    names = {p.name.lower() for p in Path(root).iterdir() if p.is_file()} if Path(root).is_dir() else set()
    return next((p for p in profiles() if any(e in names for e in p.executables)), None)


def natives_root(path):
    """The folder that holds natives/x64: the chosen one, its parent, or the one above a chosen x64."""
    path = Path(path)
    for candidate in (path, path.parent, path.parent.parent):
        if (candidate / 'natives' / 'x64').is_dir():
            return candidate
    return None


def version_profile(folder, limit=20000):
    """Identify an extracted folder by the file versions of its meshes and motlists."""
    by_mesh = {str(p.formats.get('mesh')): p for p in profiles()}
    seen = 0
    for base, dirs, files in os.walk(folder):
        dirs.sort()
        for name in files:
            seen += 1
            match = re.search(r'\.mesh\.(\d+)$', name.lower())
            if match and match[1] in by_mesh:
                return by_mesh[match[1]], f'{name} (mesh version {match[1]})'
            if seen >= limit:
                return None, ''
    return None, ''


def detect(path, file_list=''):
    """Describe an RE Engine source: a game folder with PAK archives, or a folder with an extracted natives folder."""
    chosen = Path(str(path or '')).expanduser()
    if not str(path or '').strip() or not chosen.is_dir():
        return None
    chosen = chosen.resolve()
    for root in (chosen, chosen.parent):
        found = executable_profile(root)
        paks = archives(root)
        if found and paks:
            counts, note = {}, ''
            if file_list and Path(file_list).is_file():
                try:
                    counts = packed_counts(root, found, file_list)
                except ValueError as exc:
                    note = str(exc)
            elif not file_list:
                note = (f'{found.name} keeps its files in PAK archives. Choose its file list, '
                        f'{found.formats.get("fileList", "the game’s .list file")}, below.')
            else:
                note = f'The file list was not found: {file_list}'
            exe = next(p.name for p in root.iterdir() if p.name.lower() in found.executables)
            return dict(path=str(chosen), root=str(root), layout='game', game=found.id, evidence=f'{exe} and {paks[0].name}',
                        note=note, folders={}, counts=counts, name=root.name, nested=[], limited=False,
                        engine=ENGINE, container='pak', archives=[str(p) for p in paks], needsFileList=True)
    root = natives_root(chosen)
    if root:
        found, evidence = version_profile(root / 'natives' / 'x64' / 'character')
        if not found:
            found, evidence = version_profile(root / 'natives' / 'x64')
        if not found:
            return None
        index = natives_index(root, found)
        return dict(path=str(chosen), root=str(root), layout='game', game=found.id, evidence=evidence, note='',
                    folders={}, counts=counts_of(index), name=root.name, nested=[], limited=False,
                    engine=ENGINE, container='natives', archives=[], needsFileList=False)
    return None


# The source index: the names of the files the bridge uses.

def wanted(profile):
    """The files a source index lists, as a regular expression over lower-case natives paths."""
    f = profile.formats
    return (rf'^natives/x64/(animation/({"|".join(KINDS)})/.+\.motlist\.{f["motlist"]}'
            rf'|character/({"|".join(KINDS)})/.+\.(mesh\.{f["mesh"]}|mdf2\.{f["mdf2"]}))$')


def natives_index(root, profile):
    pattern = re.compile(wanted(profile))
    files = []
    natives = Path(root) / 'natives' / 'x64'
    for kind in ('animation', 'character'):
        for base, dirs, names in os.walk(natives / kind):
            for name in names:
                full = Path(base) / name
                relative = 'natives/x64/' + full.relative_to(natives).as_posix().lower()
                if pattern.match(relative):
                    files.append(dict(path=relative, size=full.stat().st_size))
    return files


def packed_index(root, profile, file_list, work):
    """Ask the decoder which listed files the PAK archives hold, cached by the archives and the list."""
    paks = archives(root)
    key = hashlib.sha256(json.dumps([str(file_list), signature(file_list), wanted(profile)] +
                                    [(str(p), signature(p)) for p in paks]).encode()).hexdigest()[:24]
    stored = Path(work) / f'pak-index-{key}.json'
    if not stored.is_file():
        run_decoder('pak-list', file_list, stored, wanted(profile), *paks)
    return json.loads(stored.read_text(encoding='utf-8'))['files']


def packed_counts(root, profile, file_list):
    return counts_of(packed_index(root, profile, file_list, HOME / 'work/asset-cache/re_engine'))


def counts_of(files):
    paths = [f['path'] for f in files]
    return dict(animations=sum(p.endswith(tuple(f'.motlist.{v}' for v in {str(x.formats['motlist']) for x in profiles()})) for p in paths),
                characters=sum('.mesh.' in p for p in paths), materials=sum('.mdf2.' in p for p in paths))


def character_name(folder):
    match = NAMED.fullmatch(folder)
    return match[1].replace('_', ' ').title() if match else folder.upper()


def group(files):
    """Characters by ID: their motlists and the model folders of the same ID."""
    characters = {}
    for entry in files:
        parts = entry['path'].split('/')
        if parts[2] == 'animation' and len(parts) > 5:
            owner = OWNER.match(parts[4])
            if owner:
                item = characters.setdefault(owner[0], dict(kind=parts[3], motlists=[], models=[], names=[]))
                item['motlists'].append(entry)
        elif parts[2] == 'character' and len(parts) > 5:
            owner = OWNER.match(parts[4])
            if owner:
                item = characters.setdefault(owner[0], dict(kind=parts[3], motlists=[], models=[], names=[]))
                item['models'].append(entry)
                if NAMED.fullmatch(parts[4]) and '_c' not in parts[4][6:9]:
                    item['names'].append(character_name(parts[4]))
    return {k: v for k, v in characters.items() if v['motlists']}


def source_key(root, container, file_list):
    identity = json.dumps(dict(root=str(root), container=container, list=str(file_list or '')), sort_keys=True)
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def discover(root, cache, notify, found, game='auto', file_list=''):
    """List a source's characters: the players and enemies with motlists, by their ID."""
    root = Path(found['root'])
    profile = games.profile(found['game'] if game in ('', 'auto') else game)
    container = found['container']
    work = Path(cache) / 're_engine'
    notify('inventory', f'Listing the {profile.name} files', 10)
    if container == 'pak':
        if not file_list:
            raise ValueError(f'{profile.name} keeps its files in PAK archives. Edit the source and choose its file list '
                             f'({profile.formats.get("fileList", "the game’s .list file")}).')
        if not Path(file_list).is_file():
            raise ValueError(f'The file list was not found. Edit the source and choose it again.\n{file_list}')
        files = packed_index(root, profile, file_list, work)
    else:
        files = natives_index(root, profile)
    key = source_key(root, container, file_list)
    folder = work / key
    write_json(folder / 'index.json', dict(files=files))
    grouped = group(files)
    characters = []
    for owner, item in sorted(grouped.items()):
        body = body_mesh(owner, item['models'])
        characters.append(dict(id=owner, character=owner, game=profile.id, name=item['names'][0] if item['names'] else owner.upper(),
                               folder=item['kind'], archives=[m['path'] for m in item['motlists']], archiveCount=len(item['motlists']),
                               bytes=sum(m['size'] for m in item['motlists']), model=body or '', inventoried=False, count=None))
    warnings = []
    if not characters:
        warnings.append(f'No character animations found. {profile.name} keeps them in natives/x64/animation/player and enemy.')
    catalog = dict(schema=CATALOG_SCHEMA, engine=ENGINE, layout='game', container=container, folder=str(root), game=profile.id,
                   gameEvidence=found.get('evidence', ''), fileList=str(file_list or ''), archives=found.get('archives', []),
                   work=str(folder), characters=characters, clips=[], games=[profile.id], parts=[], models=[],
                   materialBinder='', textureDirectory='', referenceModel='', textureFolders=[], materialLibraries=[],
                   referenceModels=[], warnings=warnings, archiveCount=sum(c['archiveCount'] for c in characters),
                   errorCount=0, archiveSignatures={})
    destination = Path(cache) / 'catalogs' / (key + '.json')
    previous = read_json(destination)
    if previous and previous.get('schema') == CATALOG_SCHEMA and previous.get('archiveSignatures') == archive_signatures(catalog):
        # Characters read before keep their clips while the archives and the list are unchanged.
        read = {c['id']: c for c in previous['characters'] if c.get('inventoried')}
        for entry in characters:
            if entry['id'] in read and read[entry['id']]['archives'] == entry['archives']:
                entry.update({k: read[entry['id']][k] for k in ('inventoried', 'count', 'ready', 'errors') if k in read[entry['id']]})
        catalog['clips'] = [c for c in previous['clips'] if c['characterKey'] in read]
    catalog['archiveSignatures'] = archive_signatures(catalog)
    write_json(destination, catalog)
    notify('inventory', f'Found {len(characters)} characters with animations', 90)
    return destination, catalog


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def archive_signatures(catalog):
    if catalog['container'] == 'pak':
        paths = [*catalog['archives'], catalog['fileList']]
        return {p: signature(p) for p in paths if p and Path(p).is_file()}
    return {}


def body_mesh(owner, models):
    """The base model of a character: pl0100_dante/pl0100_body/pl0100.mesh, or em0000/em0000.mesh."""
    meshes = [m['path'] for m in models if '.mesh.' in m['path']]
    exact = [p for p in meshes if Path(p).name.split('.')[0] == owner]
    return (exact or [''])[0]


def load_catalog(catalog, folder, check_sources=False):
    if catalog.get('schema') != CATALOG_SCHEMA:
        raise ValueError('This scan was created by an older bridge version. Scan the source again.')
    if Path(catalog['folder']).resolve() != Path(folder).resolve() and not Path(folder).resolve() in Path(catalog['folder']).resolve().parents:
        raise ValueError('This scan belongs to another folder. Scan the selected folder again.')
    if check_sources and catalog['archiveSignatures'] != archive_signatures(catalog):
        raise ValueError('The game was updated since the last scan. Scan the source again.')
    return catalog


# Files: extracted from the PAK archives into the cache, or read in place from a natives folder.

def local_file(catalog, path):
    """Where a natives path is on disk now, or None when it still has to be extracted."""
    path = path.lower()
    loose = Path(catalog['folder']) / path
    if loose.is_file():
        # A natives folder, or loose files beside the PAK archives that replace their files (as mods do).
        return loose
    cached = Path(catalog['work']) / 'files' / path
    return cached if catalog['container'] == 'pak' and cached.is_file() else None


def materialize(catalog, paths, notify=lambda *args: None, decoder=''):
    """Local files for natives paths; packed ones are extracted into the cache first. Missing paths are left out."""
    paths = list(dict.fromkeys(p.lower() for p in paths if p))
    result = {p: local_file(catalog, p) for p in paths}
    missing = [p for p, f in result.items() if f is None]
    if missing and catalog['container'] == 'pak':
        work = Path(catalog['work'])
        request = work / f'extract-{os.getpid()}-{threading.get_ident()}.txt'
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text('\n'.join(missing), encoding='utf-8')
        notify('inventory', f'Extracting {len(missing)} file{"s" if len(missing) != 1 else ""} from the PAK archives', 6)
        try:
            with _LOCK:
                run_decoder('pak-extract', catalog['fileList'], work / 'files', request, *catalog['archives'], decoder=decoder)
        finally:
            request.unlink(missing_ok=True)
        result.update({p: local_file(catalog, p) for p in missing})
    return {p: f for p, f in result.items() if f is not None}


# Characters and clips

def inventory_character(catalog_path, catalog, character, cache, notify=lambda *args: None):
    """Read a character's motlists: one clip per motion."""
    entry = next((c for c in catalog['characters'] if character in (c['id'], c['character'])), None)
    if not entry:
        raise ValueError(f'{character} has no animations in this source.')
    files = materialize(catalog, entry['archives'], notify)
    clips, errors = [], []
    listings = Path(catalog['work']) / 'motlists'
    for index, path in enumerate(entry['archives']):
        notify('inventory', f"Reading {entry['name']} · {Path(path).name} ({index + 1}/{len(entry['archives'])})",
               8 + int(80 * index / max(1, len(entry['archives']))))
        local = files.get(path)
        if not local:
            errors.append(f'{Path(path).name}: not in the archives')
            continue
        listing = listings / (hashlib.sha256(f'{local}|{signature(local)}'.encode()).hexdigest()[:24] + '.json')
        try:
            if not listing.is_file():
                listing.parent.mkdir(parents=True, exist_ok=True)
                run_decoder('motlist', local, listing)
            motions = json.loads(listing.read_text(encoding='utf-8'))['motions']
        except (ValueError, OSError) as exc:
            errors.append(f'{Path(path).name}: {exc}')
            continue
        stem = Path(path).name.split('.')[0]
        for motion in motions:
            issues = [] if motion.get('boneCount') else ['This entry holds no bone animation.']
            clips.append(dict(id=f"{entry['id']}/{stem}#{motion['index']}", name=motion['name'] or f"{stem} {motion['index']}",
                              archive=path, member=motion['name'], character=entry['character'], characterKey=entry['id'],
                              game=entry['game'], scope=catalog['folder'], ready=not issues, issues=issues,
                              compendium='', skeletonCompendium='', path=str(local), index=int(motion['index']),
                              frameCount=motion.get('frameCount'), frameRate=motion.get('frameRate'),
                              mirror=bool(motion.get('mirror')), inputArchives=[path]))
    catalog['clips'] = [c for c in catalog['clips'] if c['characterKey'] != entry['id']] + sorted(clips, key=lambda c: (c['name'], c['archive']))
    entry.update(inventoried=True, count=len(clips), ready=sum(c['ready'] for c in clips), errors=errors)
    write_json(catalog_path, catalog)
    return catalog


def refresh_clip(catalog_path, catalog, clip_id, cache, notify=lambda *args: None):
    clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
    if clip and not Path(clip['path']).is_file():
        catalog = inventory_character(catalog_path, catalog, clip['characterKey'], cache, notify)
    return catalog, clip_id


def model_parts(catalog, owner):
    """The meshes of a character's model folders: the same ID first, then the variants of its family (pl01xx)."""
    index = read_json(Path(catalog['work']) / 'index.json') or dict(files=[])
    family = owner[:4]
    parts = []
    for entry in index['files']:
        path = entry['path']
        bits = path.split('/')
        if bits[2] != 'character' or '.mesh.' not in path or len(bits) < 6:
            continue
        folder = bits[4]
        if not folder.startswith(family):
            continue
        stem = Path(path).name.split('.')[0]
        sub = bits[5] if len(bits) > 6 else ''
        role = ('Body' if sub.endswith('_body') or stem == folder[:6] else 'Head' if '_head' in sub
                else 'Hair' if '_hair' in sub else 'Model')
        parts.append(dict(id=stem, name=f'{stem.upper()} · {character_name(folder)}', path=path, selected=False,
                          game=catalog['game'], role=role, container='Mesh', scope=catalog['folder'],
                          folder=folder, size=entry['size'], exact=OWNER.match(folder)[0] == owner if OWNER.match(folder) else False))
    parts.sort(key=lambda p: (not p['exact'], '_c' in p['folder'][6:9], p['folder'], ['Body', 'Head', 'Hair', 'Model'].index(p['role']), p['id']))
    # The default look: the body, the first head and the first hair of the character's own folder.
    for role in ('Body', 'Head', 'Hair'):
        first = next((p for p in parts if p['exact'] and p['role'] == role and '_c' not in p['folder'][6:9]
                      and not re.search(r'event|light|eyelash', p['path'])), None)
        if first:
            first['selected'] = True
    if not any(p['selected'] for p in parts) and parts:
        parts[0]['selected'] = True
    return parts


def selection(catalog, clip_id, preset='auto'):
    matches = [c for c in catalog['clips'] if c['id'] == clip_id]
    if not matches:
        raise ValueError('Choose an animation from the scanned source.')
    clip = matches[0]
    if clip['issues']:
        raise ValueError('\n'.join(clip['issues']))
    entry = next((c for c in catalog['characters'] if c['id'] == clip['characterKey']), {})
    return dict(animation=clip['path'], skeleton='', compendium='', skeletonCompendium='', materialBinder='',
                textureDirectory='', characterSource='', textureFolders=[], textureRecursive=False, layout='game',
                preset='player' if entry.get('folder') == 'player' else 'npc', game=clip['game'], referenceModel='',
                parts=model_parts(catalog, clip['characterKey']), missing=[], character=clip['character'],
                clipName=clip['name'], engine=ENGINE, motion=clip['index'], archive=clip['archive'],
                model=entry.get('model', ''), mirror=clip.get('mirror', False))


# Decoding

def decode(selection, output, skeleton='', decoder='', notes=None):
    """Motion JSON version 2 of the selected clip, with the bridge's source fields.

    The decoder's NOTE lines, such as animated bones the skeleton lacks, are added to notes.
    """
    args = ['decode', selection['animation'], int(selection.get('motion') or 0), output]
    if skeleton:
        args += ['--skeleton', skeleton]
    printed = run_decoder(*args, decoder=decoder)
    if notes is not None:
        notes += [line[4:].strip(' :') for line in printed.splitlines() if line.startswith('NOTE')]
    document = json.loads(Path(output).read_text(encoding='utf-8-sig'))
    if document.get('formatVersion') != 2:
        raise ValueError('The RE Engine decoder wrote an older motion format. Rebuild it with tools/ReEngineDecoder/build_decoder.cmd.')
    source = dict(document.get('source') or {}, engine=ENGINE, game=selection.get('game', ''))
    archive, member = selection.get('archive', ''), document.get('source', {}).get('member', '')
    document = dict(document, source=source, game=selection.get('game', ''), archive=archive, member=member)
    return check_motion(document, 'The decoded motion')


def preview(selection, cache, decoder='', stored_only=False):
    """Gzipped preview JSON of a clip on its own bone list, cached by the motlist and the motion."""
    from clip_preview import LIMIT, detached, joint_positions
    import math
    animation = Path(selection.get('animation') or '')
    if not animation.is_file():
        raise ValueError('Choose an animation first.')
    tool = decoder_path(decoder)
    key = hashlib.sha256(json.dumps([str(animation), signature(animation), selection.get('motion'),
                                     str(tool), signature(tool)]).encode()).hexdigest()[:32]
    stored = Path(cache) / f're-{key}.json.gz'
    try:
        data = stored.read_bytes()
        os.utime(stored)
        return data
    except OSError:
        if stored_only:
            return None
    import tempfile
    with tempfile.TemporaryDirectory(prefix='ReEnginePreview-') as temp:
        motion = decode(selection, Path(temp) / 'motion.json', decoder=decoder)
    bones = motion['skeleton']['bones']
    count = int(motion['frameCount'])
    step = max(1, math.ceil(count * len(bones) / LIMIT))
    positions = joint_positions(dict(motion, frames=motion['frames'][::step]))
    result = dict(clip=motion['clip'], skeleton=motion['skeletonName'], frameCount=count, frameRate=float(motion['frameRate']),
                  duration=float(motion.get('duration') or (count - 1) / float(motion['frameRate'])), frameStep=step,
                  bones=[b['name'] for b in bones], parents=[int(b['parent']) for b in bones], tracks=motion['trackCount'],
                  positions=positions, detached=detached(positions, len(bones)), root=None, **SPACE.to_json())
    data = gzip.compress(json.dumps(result, separators=(',', ':')).encode('utf-8'), compresslevel=1)
    stored.parent.mkdir(parents=True, exist_ok=True)
    staging = stored.with_name(stored.name + f'.{os.getpid()}-{threading.get_ident()}.tmp')
    staging.write_bytes(data)
    staging.replace(stored)
    return data


def prepare(request, catalog_path, catalog, temp, event):
    """Decode the requested clip and its character for Blender: motion JSON 2 and a version 5 manifest."""
    from games.re_engine import characters as character_assets
    clip_id = request.get('assetClip', '')
    if not any(c['id'] == clip_id for c in catalog['clips']):
        character = request.get('assetCharacter') or clip_id.split('/')[0]
        catalog = inventory_character(catalog_path, catalog, character, None, event)
    chosen = selection(catalog, clip_id, request.get('preset', 'auto'))
    requested = request.get('game', 'auto')
    if requested not in ('', 'auto', chosen['game']):
        raise ValueError('The selected clip belongs to a different game. Choose Auto detect or the matching source game.')
    # The motlist and the motion in it name the clip, so that a donor can be told apart from the target.
    request.update(game=chosen['game'], animation=chosen['animation'], motionIndex=chosen['motion'])
    profile = games.profile(chosen['game'])
    models = request.get('models') or [p['path'] for p in chosen['parts'] if p['selected']]
    include = request.get('includeCharacter', True) and bool(models)
    # The body's skeleton holds every bone of the character, also those the clip does not animate.
    skeleton_path = chosen['model'] or ''
    needed = [skeleton_path, *(models if include else [])]
    event('decode', 'Extracting the character files', 8)
    files = materialize(catalog, needed, event)
    skeleton = files.get(skeleton_path.lower(), '') if skeleton_path else ''
    event('decode', 'Decoding animation and skeleton', 15)
    motion_path = Path(temp) / 'motion.json'
    notes = []
    document = decode(chosen, motion_path, skeleton, notes=notes)
    motion_path.write_text(json.dumps(document), encoding='utf-8')
    report = dict(clip=document['clip'], frames=document['frameCount'], tracks=document['trackCount'], game=profile.name,
                  compression=document.get('compression', 're-mot'), parts=0, textures=0, warnings=notes, catalogRefreshed=False)
    if chosen.get('mirror'):
        report['warnings'].append('The game plays this motion mirrored. The scene holds it as stored, not mirrored.')
    character_args = []
    if include:
        event('character', 'Preparing model parts, skin weights and textures', 32)
        manifest = character_assets.prepare_character(catalog, [(p, files.get(p.lower())) for p in models],
                                                      Path(temp) / 'character', profile, event)
        character = json.loads(manifest.read_text(encoding='utf-8'))
        report.update(parts=len(character['models']), textures=character['texture_count'], warnings=report['warnings'] + character['warnings'],
                      vertices=sum(m['stats']['vertices'] for m in character['models']),
                      triangles=sum(m['stats']['triangles'] for m in character['models']))
        character_args = ['--character-manifest', manifest]
    return motion_path, character_args, report
