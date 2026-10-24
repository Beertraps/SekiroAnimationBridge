"""Discover character inputs without mixing games which reuse character IDs.

Original archives are read only. HKX/compendium members go to a private cache,
with generated directories rather than the absolute paths stored in binders.
Models, materials and texture packages are read directly by character_assets.
"""
from __future__ import annotations
import hashlib
import json
import re
import os
from pathlib import Path, PureWindowsPath
from dcx_codec import configure_oodle, unwrap
from character_assets import asset_id, ROLES, PRESETS
from game_profiles import GAMES, havok_info, resolve_game, player_parts

SCHEMA = 2


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix('.tmp')
    staging.write_text(json.dumps(value, indent=2), encoding='utf-8')
    staging.replace(path)


def signature(path):
    stat = path.stat()
    return f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'


def tag_ids(data):
    """Read top-level Havok tag sections, never search arbitrary payload bytes."""
    result = dict(requires=[], provides=[])
    if len(data) < 8 or data[4:8] not in (b'TAG0', b'TCM0'):
        return result
    end = int.from_bytes(data[:4], 'big') & 0x3fffffff
    if end > len(data) or end < 8:
        raise ValueError('Invalid Havok tagfile size.')
    pos = 8
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos+4], 'big') & 0x3fffffff
        magic = data[pos+4:pos+8]
        if size < 8 or pos + size > end:
            raise ValueError('Invalid Havok tag section size.')
        payload = data[pos+8:pos+size]
        if magic == b'TCRF':
            if len(payload) < 8:
                raise ValueError('Truncated Havok compendium reference.')
            result['requires'].append(payload[:8].hex())
        elif magic == b'TCID':
            result['provides'] += [payload[i:i+8].hex() for i in range(0, len(payload)-7, 8)]
        pos += size
    return result


def character_id(name, fallback=''):
    matches = re.findall(r'(?:^|[\\/_.-])(c\d{4})(?=$|[\\/_.-])', str(name).lower())
    return matches[-1] if matches else fallback


def inventory_binder(path, cache):
    from soulstruct.containers import Binder
    key = hashlib.sha256(signature(path).encode()).hexdigest()[:24]
    folder = cache / 'archives' / key
    manifest = folder / 'members.json'
    if manifest.is_file():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        if saved.get('schema') in (1, SCHEMA) and all(Path(e['path']).is_file() for e in saved['members']):
            if saved['schema'] == 1:
                for member in saved['members']:
                    member['sourceHavok'] = havok_info(Path(member['path']).read_bytes(), member['member'])
                saved['schema'] = SCHEMA
                write_json(manifest, saved)
            return saved['members']
    data, _ = unwrap(path.read_bytes())
    binder = Binder.from_bytes(data)
    members = []
    for i, entry in enumerate(binder.entries):
        name = PureWindowsPath(entry.path).name
        if not (name.lower().endswith('.compendium') or name.lower() == 'skeleton.hkx' or
                re.fullmatch(r'a\d+_\d+\.hkx(?:\.dcx)?', name, flags=re.I)):
            continue
        raw, _ = unwrap(entry.data)
        clean_name = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        if clean_name.lower().endswith('.dcx'):
            clean_name = clean_name[:-4]
        # A generated ordinal also distinguishes duplicate member basenames.
        target = folder / f'{i:05d}' / clean_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        kind = 'compendium' if name.lower().endswith('.compendium') else ('skeleton' if name.lower() == 'skeleton.hkx' else 'animation')
        members.append(dict(id=f'{key}:{i}', kind=kind, name=clean_name, path=str(target),
                            archive=str(path), member=entry.path,
                            character=character_id(entry.path, character_id(path.name)),
                            sourceHavok=havok_info(raw, entry.path), **tag_ids(raw)))
    write_json(manifest, dict(schema=SCHEMA, members=members))
    return members


def discover(source, cache, notify=lambda *args: None, oodle='', game='auto'):
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'Choose a folder containing the character’s DCX archives.\n{root}')
    cache = Path(cache).resolve()
    if root == cache or cache in root.parents:
        raise ValueError('Choose your original assets folder rather than the bridge cache.')
    configure_oodle(oodle)
    notify('inventory', 'Finding animation archives and character assets', 5)
    files = [p for p in sorted(root.rglob('*')) if p.is_file() and cache not in p.parents
             and not any(x.lower() in {'backup', '.git', '__pycache__', 'blender'} for x in p.relative_to(root).parts[:-1])]
    archives = [p for p in files if p.name.lower().endswith(('.anibnd', '.anibnd.dcx'))]
    members, warnings, errors = [], [], []
    for index, path in enumerate(archives):
        notify('inventory', f'Reading {path.name} ({index+1}/{len(archives)})', 8 + int(75*index/max(1,len(archives))))
        try:
            members += inventory_binder(path, cache)
        except Exception as exc:
            errors.append(f'{path.name}: {exc}')
    # Already unpacked folders can be mixed with DCX packages. Prefer original
    # archive members when both representations of the same clip are present.
    archive_keys = {(str(Path(m['archive']).parent), m['character'], m['name'].lower()) for m in members}
    for path in files:
        name = path.name.lower()
        if not (name.endswith('.compendium') or name == 'skeleton.hkx' or re.fullmatch(r'a\d+_\d+\.hkx', name)):
            continue
        ident = character_id(str(path.relative_to(root)))
        if (str(path.parent), ident, name) in archive_keys:
            continue
        try:
            raw = unwrap(path.read_bytes())[0]
            members.append(dict(id=hashlib.sha256(str(path).encode()).hexdigest()[:24],
                                kind='compendium' if name.endswith('.compendium') else ('skeleton' if name == 'skeleton.hkx' else 'animation'),
                                name=path.name, path=str(path), archive='', member=str(path.relative_to(root)), character=ident,
                                sourceHavok=havok_info(raw, str(path)), **tag_ids(raw)))
        except Exception as exc:
            errors.append(f'{path.name}: {exc}')
    for m in members:
        m['scope'] = str(Path(m['archive'] or m['path']).parent)
        info = m['sourceHavok']
        m['game'] = info.get('game', '')
        if not m['game'] and m['kind'] != 'compendium' and game != 'auto':
            m['game'] = resolve_game(info, game)
    scope_games = {}
    for m in members:
        if m['game']: scope_games.setdefault(m['scope'], set()).add(m['game'])
    def context(path):
        for parent in Path(path).parents:
            games = scope_games.get(str(parent), set())
            if len(games) == 1: return next(iter(games)), str(parent)
        return '', str(root)
    for m in members:
        if not m['game']: m['game'] = context(m['archive'] or m['path'])[0]
        m['characterKey'] = '|'.join((m['game'], m['scope'], m['character']))
    compendiums = [m for m in members if m['kind'] == 'compendium']
    skeletons = [m for m in members if m['kind'] == 'skeleton']
    skeleton_hashes = {s['path']: hashlib.sha256(Path(s['path']).read_bytes()).hexdigest() for s in skeletons}
    clips = [m for m in members if m['kind'] == 'animation']
    for m in members:
        known_ids = {s['character'] for s in skeletons if s['character'] and s['game']==m['game'] and s['scope']==m['scope']}
        if not m['character'] and len(known_ids)==1: m['character']=next(iter(known_ids))
        m['characterKey']='|'.join((m['game'], m['scope'], m['character']))
    def matching_compendium(member):
        if not member['requires']:
            return '', ''
        matches = [c for c in compendiums if c['game'] == member['game'] and c['scope'] == member['scope']
                   and set(member['requires']) <= set(c['provides'])]
        same_archive = [c for c in matches if c['archive'] and c['archive'] == member['archive']]
        same_character = [c for c in matches if c['character'] == member['character']]
        matches = same_archive or same_character or matches
        if not matches:
            return '', f"Missing matching compendium for {member['name']} (type ID {', '.join(member['requires'])}). Include its original ANIBND."
        # Same type IDs are equivalent for this purpose, including duplicated
        # original/extracted copies. Names are never used as a substitute for IDs.
        return matches[0]['path'], ''
    for clip in clips:
        issues = []
        compendium, issue = matching_compendium(clip)
        if issue:
            issues.append(issue)
        if not clip['game']:
            issues.append('Source game is unknown. Select the source game and scan again.')
        candidates = [s for s in skeletons if s['characterKey'] == clip['characterKey']]
        same_archive = [s for s in candidates if s['archive'] and s['archive'] == clip['archive']]
        base_archive = [s for s in candidates if Path(s['archive']).name.lower() in
                        (clip['character']+'.anibnd', clip['character']+'.anibnd.dcx')]
        same_directory = [s for s in candidates if str(PureWindowsPath(s['member']).parent).lower() == str(PureWindowsPath(clip['member']).parent).lower()]
        candidates = same_archive or base_archive or same_directory or candidates
        # Collapse duplicate copies, but leave genuinely different skeletons for
        # manual selection instead of borrowing another character's skeleton.
        unique = {}
        for s in candidates:
            digest = skeleton_hashes[s['path']]
            unique.setdefault(digest, s)
        skeleton = next(iter(unique.values())) if len(unique) == 1 else None
        skeleton_compendium = ''
        if not unique:
            issues.append(f"Missing skeleton for {clip['character'] or 'this character'}. Include the base cXXXX.anibnd.dcx with skeleton.hkx.")
        elif len(unique) > 1:
            issues.append('Several different skeletons match this character. Use a folder with one matching set, or select files manually.')
        if skeleton:
            skeleton_compendium, issue = matching_compendium(skeleton)
            if issue:
                issues.append(issue)
        clip.update(compendium=compendium, skeleton=skeleton['path'] if skeleton else '',
                    skeletonCompendium=skeleton_compendium, issues=issues, ready=not issues)
    model_map, conflicts = {}, set()
    for path in files:
        name = path.name.lower()
        if not name.endswith(('.chrbnd', '.chrbnd.dcx', '.partsbnd', '.partsbnd.dcx', '.flver', '.flver.dcx')):
            continue
        ident = asset_id(path)
        if ident == 'c0000' or ident.endswith(('_l', '_m')):
            continue
        source_game, scope = context(path)
        model_key = (source_game, scope, ident)
        if model_key in conflicts:
            continue
        previous = model_map.get(model_key)
        if previous and 'bnd' in name and 'bnd' in Path(previous['path']).name.lower():
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(Path(previous['path']).read_bytes()).digest():
                warnings.append(f'Conflicting model packages for {ident}: {previous["path"]} and {path}. Keep one matching version in the folder, or select your model manually.')
                conflicts.add(model_key); model_map.pop(model_key)
                continue
        # Prefer a package with its embedded textures to an extracted copy.
        if model_key not in model_map or 'bnd' in name:
            model_map[model_key] = dict(id=ident, name=ident.upper(), path=str(path), selected=False,
                                   game=source_game, scope=scope,
                                   role='Character' if re.fullmatch(r'c\d{4}', ident) else ROLES.get(ident.split('_')[0], 'Extra model'),
                                   container='Binder + textures' if 'bnd' in name else 'FLVER')
    materials = [p for p in files if p.name.lower().endswith(('.mtdbnd', '.mtdbnd.dcx', '.matbinbnd', '.matbinbnd.dcx'))]
    loose_materials = {}
    for p in files:
        if p.suffix.lower() not in ('.matbin', '.mtd'): continue
        key = (*context(p), p.suffix.lower())
        loose_materials.setdefault(key, []).append(p.parent)
    material_libraries = [dict(path=str(p), game=context(p)[0], scope=context(p)[1],
                               kind='matbin' if '.matbinbnd' in p.name.lower() else 'mtd', loose=False) for p in materials]
    material_libraries.extend(dict(path=os.path.commonpath(parents), game=g, scope=s, kind=kind[1:], loose=True)
                              for (g,s,kind), parents in loose_materials.items())
    libraries = [p for p in materials if p.name.lower().startswith(('allmaterialbnd.', 'allmaterial.'))]
    material = str((libraries or materials)[0]) if libraries or materials else ''
    references=[p for p in files if p.name.lower() in ('c0000.chrbnd.dcx','c0000.chrbnd','c0000.flver')]
    reference = str(references[0]) if references else ''
    companion_ds1_libraries = {p.name.lower() for p in materials} <= {'mtd.mtdbnd.dcx', 'mtdpatch.mtdbnd.dcx', 'mtd.mtdbnd', 'mtdpatch.mtdbnd'}
    if len(libraries or materials) > 1 and len(scope_games) <= 1 and not companion_ds1_libraries:
        warnings.append('Several material libraries were found; the selected path is shown under Textures & materials. Keep one library in the folder if they differ.')
    if not material and not material_libraries:
        warnings.append('No material library found. MTD games can use explicit FLVER paths. Elden Ring needs material/allmaterial.matbinbnd.dcx for empty texture assignments.')
    characters = sorted({c['characterKey'] for c in clips})
    if not clips:
        warnings.append('No animation clips found. Add cXXXX.anibnd.dcx and any split cXXXX_a*.anibnd.dcx archives containing the animations you need.')
    warnings += errors
    catalog = dict(schema=SCHEMA, folder=str(root), clips=sorted(clips, key=lambda c:(c['character'], c['name'], c['archive'])),
                   characters=[dict(id=c, character=next(m['character'] for m in clips if m['characterKey']==c),
                                    game=next(m['game'] for m in clips if m['characterKey']==c),
                                    name=(GAMES.get(c.split('|')[0], 'Unknown game')+' · '+c.split('|')[-1].upper()+' · '+Path(c.split('|')[1]).name),
                                    count=sum(m['characterKey']==c for m in clips)) for c in characters],
                   games=sorted({c['game'] for c in clips if c['game']}),
                   parts=list(model_map.values()), materialBinder=material, textureDirectory=str(root), referenceModel=reference, warnings=warnings,
                   materialLibraries=material_libraries,
                   referenceModels=[dict(path=str(p), game=context(p)[0], scope=context(p)[1]) for p in references],
                   archiveCount=len(archives), errorCount=len(errors),
                   sources=[dict(path=str(p), signature=signature(p)) for p in files
                            if p.name.lower().endswith(('.dcx', '.anibnd', '.hkx', '.compendium', '.flver', '.tpf', '.mtdbnd', '.matbinbnd', '.mtd', '.matbin', '.chrbnd', '.partsbnd', '.texbnd'))])
    key = hashlib.sha256(str(root).encode()).hexdigest()[:24]
    destination = cache / 'catalogs' / (key + '.json')
    write_json(destination, catalog)
    return destination, catalog


def load_catalog(path, folder, check_sources=False):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    if catalog.get('schema') != SCHEMA:
        raise ValueError('This scan was created by an older bridge version. Click Scan folder to rebuild it with game-aware matching.')
    if Path(catalog['folder']).resolve() != Path(folder).resolve():
        raise ValueError('This scan belongs to another folder. Scan the selected folder again.')
    if check_sources:
        for source in catalog['sources']:
            p = Path(source['path'])
            if not p.is_file() or signature(p) != source['signature']:
                raise ValueError(f'Assets changed since the last scan: {p.name}. Scan the folder again.')
    return catalog


def selection(catalog, clip_id, preset='auto'):
    matches = [c for c in catalog['clips'] if c['id'] == clip_id or c['name'].lower() == str(clip_id).lower()]
    if len(matches) > 1:
        raise ValueError('Several archives contain that animation name. Choose its unique clip ID from the folder catalog.')
    clip = matches[0] if matches else None
    if not clip:
        raise ValueError('Choose an animation from the scanned folder.')
    if clip['issues']:
        raise ValueError('\n'.join(clip['issues']))
    source_game = clip['game']
    wolf = clip['character'] == 'c0000' and source_game == 'sekiro'
    player = clip['character'] == 'c0000'
    if not wolf and preset in PRESETS: preset = 'auto'
    preset = ('wolf' if wolf else 'player' if player else 'npc') if preset == 'auto' else preset
    available = [p for p in catalog['parts'] if p['game'] == source_game and p['scope'] == clip['scope']]
    if player:
        parts = [dict(p) for p in available if not re.fullmatch(r'c\d{4}', p['id'])]
        wanted = PRESETS.get(preset, PRESETS['wolf'])
        if wolf:
            for p in parts: p['selected'] = p['id'] in wanted
            missing = [p for p in wanted if not any(m['id'] == p for m in parts)]
        else:
            player_parts(parts)
            missing = [] if any(p['selected'] for p in parts) else ['Player outfit PARTSBND files (c0000.chrbnd is a skeleton reference)']
    else:
        parts = [dict(p, selected=True) for p in available if p['id'] == clip['character']]
        # Unknown IDs require an explicit model choice rather than a Wolf preset.
        if not clip['character']:
            parts = [dict(p, selected=len(available)==1) for p in available]
        missing = []
    references=[r['path'] for r in catalog['referenceModels'] if r['game']==source_game and r['scope']==clip['scope']]
    reference=references[0] if len(references)==1 else ''
    libraries=[m for m in catalog['materialLibraries'] if m['game']==source_game and m['scope']==clip['scope']]
    if source_game=='er': libraries=[m for m in libraries if m.get('kind')=='matbin' or '.matbinbnd' in m['path'].lower()]
    libraries.sort(key=lambda m:(m.get('loose',False), not Path(m['path']).name.lower().startswith(('allmaterial.', 'allmaterialbnd.')), m['path']))
    return dict(animation=clip['path'], skeleton=clip['skeleton'], compendium=clip['compendium'],
                skeletonCompendium=clip['skeletonCompendium'], materialBinder=libraries[0]['path'] if libraries else '',
                textureDirectory=clip['scope'], characterSource=clip['scope'], preset=preset, game=source_game,
                referenceModel=reference,
                parts=parts, missing=missing, character=clip['character'], clipName=clip['name'])
