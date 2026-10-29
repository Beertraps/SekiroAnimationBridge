"""RE Engine games: motlist animations, mesh models, mdf2 materials and tex textures.

A game package for the Sekiro Animation Bridge, on package API version 1 (games.api, docs/PACKAGES.md).
A source is the game folder with its PAK archives, or a folder holding an extracted natives folder.
PAK archives store hashes, not names, so a packed source needs the game's file list (such as
DMC5_STM_Release.list); the package reads the names it needs from it and extracts those files into
its cache. ReEngineDecoder (decoder/, built on REE-Lib) reads the formats and writes the bridge's
interchange: motion JSON version 2 in RE Engine space, and mesh arrays.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from games.api import check_motion, read_json, signature, write_json

CATALOG_SCHEMA = 5
NATIVES = 'natives/x64/'
# Characters are the players and enemies that have both animations and models. Weapons and props are left out.
KINDS = ('player', 'enemy')
OWNER = re.compile(r'(pl|em)\d{4}')
# A model folder's name after its ID: pl0100_dante is Dante. em0000_00 is a variant, not a name.
NAMED = re.compile(r'(?:pl|em)\d{4}(?:_c\d{2})?_([a-z][a-z_]*)')
_LOCK = threading.Lock()


# Detection

def archives(root):
    """The base PAK and its patches in load order: a later patch replaces a file of an earlier one."""
    root = Path(root)
    patches = sorted(root.glob('re_chunk_000.pak.patch_*.pak'),
                     key=lambda p: int(re.search(r'patch_(\d+)', p.name)[1]) if re.search(r'patch_(\d+)', p.name) else 0)
    base = root / 're_chunk_000.pak'
    return [base, *patches] if base.is_file() else []


def executable_profile(root, profiles):
    names = {p.name.lower() for p in Path(root).iterdir() if p.is_file()} if Path(root).is_dir() else set()
    return next((p for p in profiles if any(e in names for e in p.executables)), None)


def natives_root(path):
    """The folder that holds natives/x64: the chosen one, its parent, or the one above a chosen x64."""
    path = Path(path)
    for candidate in (path, path.parent, path.parent.parent):
        if (candidate / 'natives' / 'x64').is_dir():
            return candidate
    return None


def version_profile(folder, profiles, limit=20000):
    """Identify an extracted folder by the file versions of its meshes."""
    by_mesh = {str(p.formats.get('mesh')): p for p in profiles}
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


def detect(path, options, ctx):
    """Describe an RE Engine source: a game folder with PAK archives, or a folder with an extracted natives folder."""
    file_list = options.get('fileList', '')
    chosen = Path(str(path or '')).expanduser()
    if not str(path or '').strip() or not chosen.is_dir():
        return None
    chosen = chosen.resolve()
    for root in (chosen, chosen.parent):
        found = executable_profile(root, ctx.profiles)
        paks = archives(root)
        if found and paks:
            counts, note = {}, ''
            if file_list and Path(file_list).is_file():
                try:
                    counts = counts_of(packed_index(root, found, file_list, ctx.cache, ctx), ctx.profiles)
                except ValueError as exc:
                    note = str(exc)
            elif not file_list:
                note = (f'{found.name} keeps its files in PAK archives. Choose its file list, '
                        f'{found.formats.get("fileList", "the game’s .list file")}, below.')
            else:
                note = f'The file list was not found: {file_list}'
            exe = next(p.name for p in root.iterdir() if p.name.lower() in found.executables)
            return dict(path=str(chosen), root=str(root), game=found.id, evidence=f'{exe} and {paks[0].name}', note=note,
                        counts=counts, name=root.name, container='pak', archives=[str(p) for p in paks],
                        options=['fileList'], needs=[] if file_list else ['fileList'])
    root = natives_root(chosen)
    if root:
        found, evidence = version_profile(root / 'natives' / 'x64' / 'character', ctx.profiles)
        if not found:
            found, evidence = version_profile(root / 'natives' / 'x64', ctx.profiles)
        if not found:
            return None
        index = natives_index(root, found)
        return dict(path=str(chosen), root=str(root), game=found.id, evidence=evidence, note='',
                    counts=counts_of(index, ctx.profiles), name=root.name, container='natives', archives=[],
                    options=[], needs=[])
    return None


# The source index: the names of the files the package uses.

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


def packed_index(root, profile, file_list, work, ctx):
    """Ask the decoder which listed files the PAK archives hold, cached by the archives and the list."""
    paks = archives(root)
    key = hashlib.sha256(json.dumps([str(file_list), signature(file_list), wanted(profile)] +
                                    [(str(p), signature(p)) for p in paks]).encode()).hexdigest()[:24]
    stored = Path(work) / f'pak-index-{key}.json'
    if not stored.is_file():
        stored.parent.mkdir(parents=True, exist_ok=True)
        ctx.run('decoder', 'pak-list', file_list, stored, wanted(profile), *paks)
    return json.loads(stored.read_text(encoding='utf-8'))['files']


def counts_of(files, profiles):
    paths = [f['path'] for f in files]
    versions = tuple(f'.motlist.{v}' for v in {str(p.formats['motlist']) for p in profiles})
    return dict(animations=sum(p.endswith(versions) for p in paths),
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


def scan(detection, options, ctx, previous=None):
    """List a source's characters: the players and enemies with motlists, by their ID."""
    root = Path(detection['root'])
    profile = ctx.profile(detection['game'])
    container = detection['container']
    file_list = options.get('fileList', '')
    ctx.notify('inventory', f'Listing the {profile.name} files', 10)
    if container == 'pak':
        if not file_list:
            raise ValueError(f'{profile.name} keeps its files in PAK archives. Edit the source and choose its file list '
                             f'({profile.formats.get("fileList", "the game’s .list file")}).')
        if not Path(file_list).is_file():
            raise ValueError(f'The file list was not found. Edit the source and choose it again.\n{file_list}')
        files = packed_index(root, profile, file_list, ctx.cache, ctx)
    else:
        files = natives_index(root, profile)
    folder = ctx.cache / source_key(root, container, file_list)
    write_json(folder / 'index.json', dict(files=files))
    characters = []
    for owner, item in sorted(group(files).items()):
        body = body_mesh(owner, item['models'])
        characters.append(dict(id=owner, character=owner, game=profile.id, name=item['names'][0] if item['names'] else owner.upper(),
                               folder=item['kind'], archives=[m['path'] for m in item['motlists']], archiveCount=len(item['motlists']),
                               bytes=sum(m['size'] for m in item['motlists']), model=body or '', inventoried=False, count=None))
    warnings = []
    if not characters:
        warnings.append(f'No character animations found. {profile.name} keeps them in natives/x64/animation/player and enemy.')
    catalog = dict(schema=CATALOG_SCHEMA, layout='game', container=container, folder=str(root), game=profile.id,
                   gameEvidence=detection.get('evidence', ''), fileList=str(file_list or ''), archives=detection.get('archives', []),
                   work=str(folder), characters=characters, clips=[], warnings=warnings, archiveSignatures={})
    catalog['archiveSignatures'] = archive_signatures(catalog)
    if previous and previous.get('schema') == CATALOG_SCHEMA and previous.get('archiveSignatures') == catalog['archiveSignatures']:
        # Characters read before keep their clips while the archives and the list are unchanged.
        read = {c['id']: c for c in previous['characters'] if c.get('inventoried')}
        for entry in characters:
            if entry['id'] in read and read[entry['id']]['archives'] == entry['archives']:
                entry.update({k: read[entry['id']][k] for k in ('inventoried', 'count', 'ready', 'errors') if k in read[entry['id']]})
        catalog['clips'] = [c for c in previous['clips'] if c['characterKey'] in read]
    ctx.notify('inventory', f'Found {len(characters)} characters with animations', 90)
    return catalog


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


def validate(catalog, folder, check_sources, ctx):
    if catalog.get('schema') != CATALOG_SCHEMA:
        raise ValueError('This scan was created by an older version of the RE Engine package. Scan the source again.')
    if check_sources and catalog['archiveSignatures'] != archive_signatures(catalog):
        raise ValueError('The game was updated since the last scan. Scan the source again.')


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


def materialize(catalog, paths, ctx):
    """Local files for natives paths; packed ones are extracted into the cache first. Missing paths are left out."""
    paths = list(dict.fromkeys(p.lower() for p in paths if p))
    result = {p: local_file(catalog, p) for p in paths}
    missing = [p for p, f in result.items() if f is None]
    if missing and catalog['container'] == 'pak':
        work = Path(catalog['work'])
        request = work / f'extract-{os.getpid()}-{threading.get_ident()}.txt'
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text('\n'.join(missing), encoding='utf-8')
        ctx.notify('inventory', f'Extracting {len(missing)} file{"s" if len(missing) != 1 else ""} from the PAK archives', 6)
        try:
            with _LOCK:
                ctx.run('decoder', 'pak-extract', catalog['fileList'], work / 'files', request, *catalog['archives'])
        finally:
            request.unlink(missing_ok=True)
        result.update({p: local_file(catalog, p) for p in missing})
    return {p: f for p, f in result.items() if f is not None}


# Characters and clips

def inventory(catalog, character, ctx):
    """Read a character's motlists: one clip per motion."""
    entry = next((c for c in catalog['characters'] if character in (c['id'], c['character'])), None)
    if not entry:
        raise ValueError(f'{character} has no animations in this source.')
    files = materialize(catalog, entry['archives'], ctx)
    clips, errors = [], []
    listings = Path(catalog['work']) / 'motlists'
    for index, path in enumerate(entry['archives']):
        ctx.notify('inventory', f"Reading {entry['name']} · {Path(path).name} ({index + 1}/{len(entry['archives'])})",
                   8 + int(80 * index / max(1, len(entry['archives']))))
        local = files.get(path)
        if not local:
            errors.append(f'{Path(path).name}: not in the archives')
            continue
        listing = listings / (hashlib.sha256(f'{local}|{signature(local)}'.encode()).hexdigest()[:24] + '.json')
        try:
            if not listing.is_file():
                listing.parent.mkdir(parents=True, exist_ok=True)
                ctx.run('decoder', 'motlist', local, listing)
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
                              path=str(local), index=int(motion['index']), frameCount=motion.get('frameCount'),
                              frameRate=motion.get('frameRate'), mirror=bool(motion.get('mirror')), inputArchives=[path]))
    catalog['clips'] = [c for c in catalog['clips'] if c['characterKey'] != entry['id']] + sorted(clips, key=lambda c: (c['name'], c['archive']))
    entry.update(inventoried=True, count=len(clips), ready=sum(c['ready'] for c in clips), errors=errors)
    return catalog


def refresh(catalog, clip_id, ctx):
    clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
    if clip and not Path(clip['path']).is_file():
        catalog = inventory(catalog, clip['characterKey'], ctx)
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


def selection(catalog, clip_id, preset, ctx):
    matches = [c for c in catalog['clips'] if c['id'] == clip_id]
    if not matches:
        raise ValueError('Choose an animation from the scanned source.')
    clip = matches[0]
    if clip['issues']:
        raise ValueError('\n'.join(clip['issues']))
    entry = next((c for c in catalog['characters'] if c['id'] == clip['characterKey']), {})
    return dict(animation=clip['path'], layout='game', preset='player' if entry.get('folder') == 'player' else 'npc',
                game=clip['game'], parts=model_parts(catalog, clip['characterKey']), character=clip['character'],
                clipName=clip['name'], motion=clip['index'], archive=clip['archive'], model=entry.get('model', ''),
                mirror=clip.get('mirror', False))


# Decoding

def decode(selection, output, ctx, skeleton='', notes=None):
    """Motion JSON version 2 of the selected clip, with the bridge's source fields.

    The decoder's NOTE lines, such as animated bones the skeleton lacks, are added to notes.
    """
    args = ['decode', selection['animation'], int(selection.get('motion') or 0), output]
    if skeleton:
        args += ['--skeleton', skeleton]
    printed = ctx.run('decoder', *args)
    if notes is not None:
        notes += [line[4:].strip(' :') for line in printed.splitlines() if line.startswith('NOTE')]
    document = json.loads(Path(output).read_text(encoding='utf-8-sig'))
    if document.get('formatVersion') != 2:
        raise ValueError('The RE Engine decoder wrote an older motion format. Rebuild it with decoder/build_decoder.cmd.')
    source = dict(document.get('source') or {}, engine='re_engine', game=selection.get('game', ''))
    archive, member = selection.get('archive', ''), document.get('source', {}).get('member', '')
    document = dict(document, source=source, game=selection.get('game', ''), archive=archive, member=member)
    return check_motion(document, 'The decoded motion')


def preview_key(selection, ctx):
    """The preview changes with the motlist, the motion in it and the decoder."""
    animation, tool = Path(selection.get('animation') or ''), ctx.tool('decoder')
    if not animation.is_file():
        raise ValueError('Choose an animation first.')
    return json.dumps([str(animation), signature(animation), selection.get('motion'), str(tool), signature(tool)])


def preview(selection, ctx):
    """The clip on its own bone list, for the skeleton preview."""
    with tempfile.TemporaryDirectory(prefix='ReEnginePreview-') as temp:
        return decode(selection, Path(temp) / 'motion.json', ctx)


def prepare(request, catalog, temp, ctx):
    """Decode the requested clip and its character for Blender: motion JSON 2 and a version 5 manifest."""
    from . import characters as character_assets
    clip_id = request.get('assetClip', '')
    read = None
    if not any(c['id'] == clip_id for c in catalog['clips']):
        character = request.get('assetCharacter') or clip_id.split('/')[0]
        catalog = read = inventory(catalog, character, ctx)
    chosen = selection(catalog, clip_id, request.get('preset', 'auto'), ctx)
    requested = request.get('game', 'auto')
    if requested not in ('', 'auto', chosen['game']):
        raise ValueError('The selected clip belongs to a different game. Choose Auto detect or the matching source game.')
    profile = ctx.profile(chosen['game'])
    models = request.get('models') or [p['path'] for p in chosen['parts'] if p['selected']]
    include = request.get('includeCharacter', True) and bool(models)
    # The body's skeleton holds every bone of the character, also those the clip does not animate.
    skeleton_path = chosen['model'] or ''
    needed = [skeleton_path, *(models if include else [])]
    ctx.notify('decode', 'Extracting the character files', 8)
    files = materialize(catalog, needed, ctx)
    skeleton = files.get(skeleton_path.lower(), '') if skeleton_path else ''
    ctx.notify('decode', 'Decoding animation and skeleton', 15)
    motion_path = Path(temp) / 'motion.json'
    notes = []
    document = decode(chosen, motion_path, ctx, skeleton, notes=notes)
    motion_path.write_text(json.dumps(document), encoding='utf-8')
    report = dict(clip=document['clip'], frames=document['frameCount'], tracks=document['trackCount'], game=profile.name,
                  compression=document.get('compression', 're-mot'), parts=0, textures=0, warnings=notes)
    if chosen.get('mirror'):
        report['warnings'].append('The game plays this motion mirrored. The scene holds it as stored, not mirrored.')
    manifests = []
    if include:
        ctx.notify('character', 'Preparing model parts, skin weights and textures', 32)
        manifest = character_assets.prepare_character(catalog, [(p, files.get(p.lower())) for p in models],
                                                      Path(temp) / 'character', profile, ctx)
        character = json.loads(manifest.read_text(encoding='utf-8'))
        report.update(parts=len(character['models']), textures=character['texture_count'], warnings=report['warnings'] + character['warnings'],
                      vertices=sum(m['stats']['vertices'] for m in character['models']),
                      triangles=sum(m['stats']['triangles'] for m in character['models']))
        manifests.append(manifest)
    # The motlist and the motion in it name the clip, so that a donor can be told apart from the target.
    return dict(motion=motion_path, characters=manifests, report=report, catalog=read,
                request=dict(game=chosen['game'], animation=chosen['animation'], motionIndex=chosen['motion']))
