"""Unreal Engine 4 and 5 games: skeletons, animation sequences and skeletal meshes from PAK and IoStore archives.

A game package for the Sekiro Animation Bridge, on package API version 1 (games.api, docs/PACKAGES.md). A source is
the game folder, the folder of its project (the one with Content/Paks) or the Paks folder. UnrealDecoder (decoder/,
built on CUE4Parse) mounts the archives in place, lists every skeleton with its animation sequences and skeletal
meshes from the game's asset registry, and writes the bridge's interchange in Unreal space: motion JSON version 2
and mesh arrays. A game that encrypts its archives needs its AES key, and one whose packages store properties
without names needs a mappings file (.usmap); both come from the user and stay on this computer.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from games.api import check_motion, read_json, signature, write_json

from . import archives as headers

CATALOG_SCHEMA = 1
OPTIONS = ('engineVersion', 'aesKey', 'mappings', 'oodle')
# Prefixes and suffixes of skeleton asset names that say nothing about the character.
SKELETON_AFFIXES = re.compile(r'^(?:SKEL|SK|S)_|_(?:Skeleton|Skel|SKEL)$', re.IGNORECASE)
ROLES = (('head', 'Head'), ('face', 'Head'), ('hair', 'Hair'), ('body', 'Body'))


# Detection

def profile_for(project, profiles):
    """The game profile of a project: by its folder name (formats.project) or an executable, else the generic one."""
    names = {p.name.lower() for p in headers.executables(project)}
    for profile in profiles:
        if profile.id == 'unreal':
            continue
        if str(profile.formats.get('project', '')).lower() == project.name.lower() or names & set(profile.executables):
            return profile
    return next(p for p in profiles if p.id == 'unreal')


def game_name(project, profile):
    """A source's name: the profile's, or the install folder's (Xbox installs keep the project in Game/Content)."""
    if profile.id != 'unreal':
        return profile.name
    folder = project.parent
    return folder.parent.name if folder.name.lower() == 'content' and folder.parent.name else folder.name or project.name


def resolve_engine(options, profile, detected):
    """(engine, evidence): the user's choice, else the profile's version, else the detected one."""
    chosen = options.get('engineVersion') or 'auto'
    if chosen != 'auto':
        return chosen, f'{headers.engine_label(chosen)}, as chosen'
    if profile.formats.get('engine'):
        return profile.formats['engine'], f'{headers.engine_label(profile.formats["engine"])} for {profile.name}'
    return detected


def detect(path, options, ctx):
    """Describe an Unreal source: the project folder with Content/Paks, found from the game folder or below it."""
    if not str(path or '').strip():
        return None
    chosen = Path(str(path)).expanduser()
    if not chosen.is_dir():
        return None
    project = headers.find_project(chosen.resolve())
    if not project:
        return None
    paks = project / 'Content' / 'Paks'
    files = headers.archive_files(paks)
    info = headers.read_archives(files)
    profile = profile_for(project, ctx.profiles)
    engine, evidence = resolve_engine(options, profile, headers.detected_engine(project, info))
    shown = ['engineVersion', 'mappings']
    if info['encrypted']:
        shown.append('aesKey')
    if 'Oodle' in info['methods']:
        shown.append('oodle')
    needs = ['aesKey'] if info['encrypted'] and not options.get('aesKey') else []
    count = len(files)
    kind = 'IoStore' if info['container'] == 'iostore' else 'PAK'
    notes = []
    if needs:
        notes.append(f'{len(info["encrypted"])} of its {count} archives are encrypted. Enter the game’s AES key below.')
    if not engine:
        notes.append('The engine version could not be read from the game. Choose it below.')
    elif 'suggests' in evidence and (options.get('engineVersion') or 'auto') == 'auto':
        notes.append(f'{evidence}; if the scan fails, choose the game’s version below.')
    if info['container'] == 'iostore' and not options.get('mappings'):
        notes.append('If its animations do not decode, choose the game’s mappings file (.usmap) below.')
    return dict(path=str(chosen.resolve()), root=str(paks), game=profile.id, name=game_name(project, profile),
                evidence=f'{project.name}/Content/Paks with {count} {kind} archive{"s" if count != 1 else ""}'
                         + (f'; {evidence}' if engine and 'suggests' not in evidence else ''),
                note=' '.join(notes), counts={}, container=info['container'], archives=[str(p) for p in files],
                options=shown, needs=needs, project=project.name, engineVersion=engine or '',
                encrypted=bool(info['encrypted']), compression=info['methods'],
                layoutNote=f'Reads {project.name}’s {kind} archives in place with CUE4Parse.')


# Scanning

def source_document(root, engine, options):
    """What the decoder reads from source.json."""
    return dict(root=str(root), engine=engine, aesKey=options.get('aesKey', ''), mappings=options.get('mappings', ''),
                oodle=options.get('oodle', ''))


def work_folder(ctx, document):
    identity = json.dumps(document, sort_keys=True)
    return ctx.cache / hashlib.sha256(identity.encode()).hexdigest()[:24]


def archive_signatures(catalog):
    """Signatures of the archives and of the files the options name; any change means a new scan."""
    paths = [*catalog['archives'], *(catalog['options'].get(k, '') for k in ('mappings', 'oodle'))]
    return {p: signature(p) for p in paths if p and Path(p).is_file()}


def short_name(skeleton):
    """SK_Mannequin_Skeleton as Mannequin: the label the character list shows."""
    name = skeleton.rsplit('.', 1)[-1] or skeleton.rsplit('/', 1)[-1]
    for _ in range(2):
        name = SKELETON_AFFIXES.sub('', name)
    return name or skeleton.rsplit('/', 1)[-1]


def package_folder(path):
    return path.rsplit('/', 1)[0] if '/' in path else ''


def frame_rate(entry):
    frames, length = entry.get('frames'), entry.get('length')
    return round((frames - 1) / length, 3) if frames and frames > 1 and length else None


def clips_of(animations, entry, catalog):
    """The clips of one skeleton, from the scan's animations on it."""
    clips = []
    for animation in animations:
        issues = ['The clip has no frames.'] if animation.get('frames') == 0 else []
        clips.append(dict(id=animation['path'], name=animation['name'], archive=animation.get('archive', ''),
                          member=animation['path'], character=entry['character'], characterKey=entry['id'],
                          game=catalog['game'], scope=catalog['folder'], ready=not issues, issues=issues,
                          path=animation['path'], folder=package_folder(animation['path']), frameCount=animation.get('frames'),
                          frameRate=frame_rate(animation), additive=bool(animation.get('additive')),
                          rootMotion=bool(animation.get('rootMotion'))))
    return sorted(clips, key=lambda c: (c['name'].lower(), c['id']))


def main_mesh(skeleton, meshes):
    """The mesh named most like the skeleton, such as SK_Hero for SK_Hero_Skeleton, else the first."""
    if not meshes:
        return ''
    want = short_name(skeleton).lower()
    named = [m for m in meshes if short_name(m['path']).lower() == want]
    return (named or sorted(meshes, key=lambda m: (len(m['name']), m['path'])))[0]['path']


def scan(detection, options, ctx, previous=None):
    """List the skeletons that have animations: each is a character, with its clips and skeletal meshes."""
    root = Path(detection['root'])
    profile = ctx.profile(detection['game'])
    engine, _ = resolve_engine(options, profile, (detection.get('engineVersion', ''), ''))
    if not engine:
        raise ValueError(f'The Unreal Engine version of {detection.get("name") or "this game"} is unknown. '
                         'Edit the source and choose it under Engine version.')
    if detection.get('encrypted') and not options.get('aesKey'):
        raise ValueError(f'{detection.get("name") or "This game"} encrypts its archives. Edit the source and enter its AES key.')
    for key, label in (('mappings', 'mappings file'), ('oodle', 'Oodle library')):
        if options.get(key) and not Path(options[key]).is_file():
            raise ValueError(f'The {label} was not found. Edit the source and choose it again.\n{options[key]}')
    document = source_document(root, engine, options)
    folder = work_folder(ctx, document)
    catalog = dict(schema=CATALOG_SCHEMA, layout='game', container=detection.get('container', 'pak'), folder=str(root),
                   game=profile.id, gameEvidence=detection.get('evidence', ''), project=detection.get('project', ''),
                   engineVersion=engine, options={k: options.get(k, '') for k in OPTIONS}, archives=detection.get('archives', []),
                   work=str(folder), source=str(folder / 'source.json'), characters=[], clips=[], warnings=[],
                   archiveSignatures={})
    catalog['archiveSignatures'] = archive_signatures(catalog)
    index_path = folder / 'index.json'
    write_json(catalog['source'], document)
    reuse = (previous and previous.get('schema') == CATALOG_SCHEMA and previous.get('archiveSignatures') == catalog['archiveSignatures']
             and previous.get('engineVersion') == engine and previous.get('decoder') == tool_signature(ctx) and index_path.is_file())
    if not reuse:
        ctx.notify('inventory', f'Reading the {headers.engine_label(engine)} archives of {detection.get("name") or profile.name}', 10)
        printed = ctx.run('decoder', 'scan', catalog['source'], index_path, timeout=3600)
        catalog['warnings'] += notes_of(printed)
    catalog['decoder'] = tool_signature(ctx)
    index = read_json(index_path) or {}
    if index.get('format') != 'unreal-scan':
        raise ValueError('The Unreal decoder wrote no scan. Rebuild it with decoder/build_decoder.cmd.')
    if index.get('closed'):
        catalog['warnings'].append(f"{len(index['closed'])} archives stay closed: their AES key is missing or wrong.")

    meshes, animations = {}, {}
    for mesh in index.get('meshes', []):
        meshes.setdefault(mesh.get('skeleton', ''), []).append(mesh)
    for animation in index.get('animations', []):
        if animation.get('skeleton'):
            animations.setdefault(animation['skeleton'], []).append(animation)
    names = {s['path']: s['name'] for s in index.get('skeletons', [])}
    for skeleton in sorted(animations):
        entry = dict(id=skeleton, character=short_name(skeleton), name=names.get(skeleton, short_name(skeleton)),
                     game=profile.id, folder=package_folder(skeleton), archives=[], bytes=0,
                     model=main_mesh(skeleton, meshes.get(skeleton, [])), meshCount=len(meshes.get(skeleton, [])),
                     inventoried=True, count=0, ready=0, errors=[])
        clips = clips_of(animations[skeleton], entry, catalog)
        entry.update(count=len(clips), ready=sum(c['ready'] for c in clips),
                     archives=sorted({c['archive'] for c in clips if c['archive']}))
        catalog['characters'].append(entry)
        catalog['clips'] += clips
    unowned = sum(1 for a in index.get('animations', []) if not a.get('skeleton'))
    if unowned:
        catalog['warnings'].append(f'{unowned} animations name no skeleton and are left out.')
    unread = next((n for n in catalog['warnings'] if 'headers could not be read' in n), '')
    if not catalog['characters'] and unowned and unread:
        # The skeletons came from package headers, and none could be read: say why instead of listing nothing.
        raise ValueError(hint(unread) if 'mapping file' in unread.lower() else
                         f'{unread}\nIf the game uses another engine version, edit the source and choose it under Engine version.')
    if not catalog['characters']:
        catalog['warnings'].append('No animation sequences found. '
                                   + ('The asset registry may be missing; ' if not index.get('registries') else '')
                                   + 'check the engine version and, for an IoStore game, its mappings file.')
    catalog['characters'].sort(key=lambda c: (c['character'].lower(), c['id']))
    ctx.notify('inventory', f"Found {len(catalog['characters'])} skeletons with {len(catalog['clips'])} animations", 90)
    return catalog


def tool_signature(ctx):
    """The decoder's path and signature, or '' while it is not built; a new build means a new scan and new previews."""
    try:
        tool = ctx.tool('decoder')
    except ValueError:
        return ''
    return f'{tool}|{signature(tool)}'


def notes_of(printed):
    return [line[4:].strip(' :') for line in (printed or '').splitlines() if line.startswith('NOTE')]


def validate(catalog, folder, check_sources, ctx):
    if catalog.get('schema') != CATALOG_SCHEMA:
        raise ValueError('This scan was created by an older version of the Unreal package. Scan the source again.')
    if check_sources and catalog['archiveSignatures'] != archive_signatures(catalog):
        raise ValueError('The game was updated since the last scan. Scan the source again.')


# Characters and clips

def inventory(catalog, character, ctx):
    """Characters are read with the scan; this only checks that the character is there."""
    if not any(character in (c['id'], c['character']) for c in catalog['characters']):
        raise ValueError(f'{character} has no animations in this source.')
    return catalog


def role(name, index):
    lowered = name.lower()
    return next((label for word, label in ROLES if word in lowered), 'Body' if index == 0 else 'Model')


def model_parts(catalog, entry):
    """The skeletal meshes on a character's skeleton; the main one is chosen."""
    index = read_json(Path(catalog['work']) / 'index.json') or {}
    meshes = sorted((m for m in index.get('meshes', []) if m.get('skeleton') == entry['id']),
                    key=lambda m: (m['path'] != entry.get('model'), m['name'].lower(), m['path']))
    return [dict(id=m['path'], name=m['name'], path=m['path'], selected=m['path'] == entry.get('model'), game=catalog['game'],
                 role=role(m['name'], position), container='SkeletalMesh', scope=catalog['folder'], folder=package_folder(m['path']),
                 size=0, exact=m['path'] == entry.get('model'))
            for position, m in enumerate(meshes)]


def selection(catalog, clip_id, preset, ctx):
    matches = [c for c in catalog['clips'] if c['id'] == clip_id]
    if not matches:
        raise ValueError('Choose an animation from the scanned source.')
    clip = matches[0]
    if clip['issues']:
        raise ValueError('\n'.join(clip['issues']))
    entry = next((c for c in catalog['characters'] if c['id'] == clip['characterKey']), {})
    digest = hashlib.sha256(json.dumps([catalog['archiveSignatures'], catalog['engineVersion']], sort_keys=True).encode()).hexdigest()[:24]
    return dict(animation=clip['path'], layout='game', preset=preset if preset in ('player', 'npc') else 'npc', game=clip['game'],
                parts=model_parts(catalog, entry), character=clip['character'], clipName=clip['name'], archive=clip['archive'],
                model=entry.get('model', ''), source=catalog['source'], sourceDigest=digest, characterKey=clip['characterKey'])


# Decoding

def decode(selection, output, ctx, mesh='', notes=None):
    """Motion JSON version 2 of the selected clip, retargeted to a mesh's bones when one is given."""
    args = ['decode', selection['source'], selection['animation'], output]
    if mesh:
        args += ['--mesh', mesh]
    try:
        printed = ctx.run('decoder', *args)
    except ValueError as exc:
        raise ValueError(hint(str(exc))) from None
    if notes is not None:
        notes += notes_of(printed)
    document = json.loads(Path(output).read_text(encoding='utf-8-sig'))
    if document.get('formatVersion') != 2:
        raise ValueError('The Unreal decoder wrote an older motion format. Rebuild it with decoder/build_decoder.cmd.')
    source = dict(document.get('source') or {}, engine='unreal', game=selection.get('game', ''))
    document = dict(document, source=source, game=selection.get('game', ''), archive=selection.get('archive', ''),
                    member=selection['animation'])
    return check_motion(document, 'The decoded motion')


def hint(message):
    """A decoder error with what the user can do about it."""
    lowered = message.lower()
    if 'mapping' in lowered:
        return f'{message}\nThis game stores properties without names. Edit the source and choose its mappings file (.usmap).'
    if 'aes' in lowered or 'encrypt' in lowered:
        return f'{message}\nEdit the source and check its AES key.'
    if 'acl' in lowered:
        return message
    if 'serializ' in lowered or 'deserializ' in lowered or 'version' in lowered:
        return f'{message}\nIf the game uses another engine version, edit the source and choose it under Engine version.'
    return message


def preview_key(selection, ctx):
    """The preview changes with the archives, the engine version, the clip, its mesh and the decoder."""
    source = Path(selection.get('source') or '')
    if not selection.get('animation') or not source.is_file():
        raise ValueError('Choose an animation first.')
    return json.dumps([selection.get('sourceDigest'), signature(source), selection['animation'], selection.get('model', ''),
                       tool_signature(ctx)])


def preview(selection, ctx):
    """The clip on its main mesh's bones, for the skeleton preview."""
    with tempfile.TemporaryDirectory(prefix='UnrealPreview-') as temp:
        return decode(selection, Path(temp) / 'motion.json', ctx, selection.get('model', ''))


def prepare(request, catalog, temp, ctx):
    """Decode the requested clip and its character for Blender: motion JSON 2 and a version 5 manifest."""
    from . import characters as character_assets
    clip_id = request.get('assetClip', '')
    chosen = selection(catalog, clip_id, request.get('preset', 'auto'), ctx)
    requested = request.get('game', 'auto')
    if requested not in ('', 'auto', chosen['game']):
        raise ValueError('The selected clip belongs to a different game. Choose Auto detect or the matching source game.')
    profile = ctx.profile(chosen['game'])
    models = request.get('models') or [p['path'] for p in chosen['parts'] if p['selected']]
    include = request.get('includeCharacter', True) and bool(models)
    # The clip plays on the bones of the first model, as the game plays it on that mesh.
    mesh = models[0] if include else chosen['model']
    ctx.notify('decode', 'Decoding animation and skeleton', 15)
    motion_path = Path(temp) / 'motion.json'
    notes = []
    document = decode(chosen, motion_path, ctx, mesh, notes=notes)
    motion_path.write_text(json.dumps(document), encoding='utf-8')
    report = dict(clip=document['clip'], frames=document['frameCount'], tracks=document['trackCount'], game=profile.name,
                  compression=document.get('compression', 'unreal'), parts=0, textures=0, warnings=notes)
    manifests = []
    if include:
        ctx.notify('character', 'Preparing model parts, skin weights and textures', 32)
        manifest = character_assets.prepare_character(chosen, models, Path(temp) / 'character', profile, ctx)
        character = json.loads(manifest.read_text(encoding='utf-8'))
        report.update(parts=len(character['models']), textures=character['texture_count'], warnings=report['warnings'] + character['warnings'],
                      vertices=sum(m['stats']['vertices'] for m in character['models']),
                      triangles=sum(m['stats']['triangles'] for m in character['models']))
        manifests.append(manifest)
    return dict(motion=motion_path, characters=manifests, report=report,
                request=dict(game=chosen['game'], animation=chosen['animation']))
