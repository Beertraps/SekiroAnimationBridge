"""Discover character inputs without mixing games which reuse character IDs.

Original archives are read only. HKX/compendium members go to a private cache,
with generated directories rather than the absolute paths stored in binders.
Models, materials and texture packages are read directly by character_assets.

A collected folder is inventoried completely and matched by the directory its
files share. A source in the game's own structure is indexed by file name, and
a character's archives are inventoried when that character is chosen: a whole
game holds hundreds of animation archives.
"""
from __future__ import annotations
import hashlib
import json
import re
import os
from pathlib import Path, PureWindowsPath
from dcx_codec import configure_oodle, unwrap
from character_assets import asset_id, ROLES, PRESETS
from game_profiles import GAMES, havok_info, resolve_game, player_parts, path_game
from asset_sources import (KINDS, LAYOUTS, detect, executable_game, material_game, game_folders,
                           find_game_root, resolve_folders, kind_files, leading_id)

SCHEMA = 2  # archive member manifests
CATALOG_SCHEMA = 3  # schema 2 catalogs are collected folders
STRUCTURED = ('game', 'custom')


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


def archive_members(path, cache):
    """Members with the character the archive's name gives them, when their path names it too.

    c0000_c5060.anibnd holds c0000's motions against c5060 under chr/c0000/hkx/c5060_compendium;
    the last ID in that path alone would pair them with c5060's skeleton.
    """
    members = inventory_binder(path, cache)
    owner = leading_id(path)
    named = re.compile(rf'(?:^|[\\/_.-]){owner}(?=$|[\\/_.-])') if owner else None
    return [dict(m, character=owner) if named and m['character'] != owner and named.search(m['member'].lower()) else m
            for m in members]


def match_clips(members):
    """Pair each clip with its skeleton and compendiums of the same game, scope and character.

    Compendiums are matched by Havok type IDs; names are never used as a substitute.
    """
    compendiums = [m for m in members if m['kind'] == 'compendium']
    skeletons = [m for m in members if m['kind'] == 'skeleton']
    skeleton_hashes = {s['path']: hashlib.sha256(Path(s['path']).read_bytes()).hexdigest() for s in skeletons}
    clips = [m for m in members if m['kind'] == 'animation']
    def matching_compendium(member):
        if not member['requires']:
            return None, ''
        matches = [c for c in compendiums if c['game'] == member['game'] and c['scope'] == member['scope']
                   and set(member['requires']) <= set(c['provides'])]
        same_archive = [c for c in matches if c['archive'] and c['archive'] == member['archive']]
        same_character = [c for c in matches if c['character'] == member['character']]
        matches = same_archive or same_character or matches
        if not matches:
            return None, f"Missing matching compendium for {member['name']} (type ID {', '.join(member['requires'])}). Include its original ANIBND."
        # Same type IDs are equivalent for this purpose, including duplicated
        # original/extracted copies. Names are never used as a substitute for IDs.
        return matches[0], ''
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
        skeleton_compendium = None
        if not unique:
            issues.append(f"Missing skeleton for {clip['character'] or 'this character'}. Include the base cXXXX.anibnd.dcx with skeleton.hkx.")
        elif len(unique) > 1:
            issues.append('Several different skeletons match this character. Use a folder with one matching set, or select files manually.')
        if skeleton:
            skeleton_compendium, issue = matching_compendium(skeleton)
            if issue:
                issues.append(issue)
        clip.update(compendium=compendium['path'] if compendium else '', skeleton=skeleton['path'] if skeleton else '',
                    skeletonCompendium=skeleton_compendium['path'] if skeleton_compendium else '', issues=issues, ready=not issues,
                    inputArchives=sorted({m['archive'] for m in (clip, compendium, skeleton, skeleton_compendium) if m and m['archive']}))
    return clips


def probe_game(folders):
    """Identify the game from the smallest animation archive: authoring paths, then the Havok version."""
    archives = [p for folder in folders for p in Path(folder).glob('*.anibnd*')]
    if not archives:
        return '', ''
    from soulstruct.containers import Binder
    archive = min(archives, key=lambda p: p.stat().st_size)
    binder = Binder.from_bytes(unwrap(archive.read_bytes())[0])
    hint = next((game for entry in binder.entries if (game := path_game(entry.path))), '')
    for entry in binder.entries:
        if entry.path.lower().endswith(('.hkx', '.hkx.dcx')):
            game = havok_info(unwrap(entry.data)[0], entry.path).get('game', '')
            if game:
                return game, f'{archive.name} (Havok version)'
    # Authoring paths do not separate Prepare to Die from Remastered.
    return (hint, f'{archive.name} (authoring paths)') if hint and hint != 'ds1' else ('', '')


def detect_source(path, oodle=''):
    """Folder detection for the UI, with one small archive read when no executable names the game."""
    def probe(root):
        configure_oodle(oodle)
        return probe_game([Path(root) / 'chr'])
    found = detect(path, probe)
    found['scenes'] = default_scenes(found)
    # The UI can switch the layout before saving; both defaults are offered.
    found['sceneFolders'] = {layout: default_scenes(dict(found, layout=layout)) for layout in ('folder', 'game')}
    return found


def default_scenes(found):
    """New scenes go beside a collected folder, and to Documents for a game or mod folder."""
    if found['layout'] == 'folder':
        return str(Path(found['root']) / 'Blender')
    name = re.sub(r'[<>:"/\\|?*]+', '_', found.get('name') or 'Source').strip() or 'Source'
    return str(Path.home() / 'Documents' / 'Animation Bridge' / name)


def discover(source, cache, notify=lambda *args: None, oodle='', game='auto', layout='folder', folders=None, recursive=True):
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'Choose a folder containing the character’s DCX archives.\n{root}')
    cache = Path(cache).resolve()
    if root == cache or cache in root.parents:
        raise ValueError('Choose your original assets folder rather than the bridge cache.')
    if layout not in LAYOUTS:
        raise ValueError('Choose the source layout: auto, folder, game or custom.')
    configure_oodle(oodle)
    if layout == 'auto':
        notify('inventory', 'Detecting the folder layout', 3)
        found = detect(root)
        layout, root = found['layout'], Path(found['root'])
    elif layout == 'game':
        # The chosen chr, parts or Game folder stands for the game folder that holds it.
        root = find_game_root(root)[0] or root
    if layout in STRUCTURED:
        return index_source(root, cache, notify, game, layout, folders, recursive)
    return discover_folder(root, cache, notify, game)


def discover_folder(root, cache, notify, game='auto'):
    notify('inventory', 'Finding animation archives and character assets', 5)
    files = [p for p in sorted(root.rglob('*')) if p.is_file() and cache not in p.parents
             and not any(x.lower() in {'backup', '.git', '__pycache__', 'blender'} for x in p.relative_to(root).parts[:-1])]
    archives = [p for p in files if p.name.lower().endswith(('.anibnd', '.anibnd.dcx'))]
    members, warnings, errors = [], [], []
    for index, path in enumerate(archives):
        notify('inventory', f'Reading {path.name} ({index+1}/{len(archives)})', 8 + int(75*index/max(1,len(archives))))
        try:
            members += archive_members(path, cache)
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
    skeletons = [m for m in members if m['kind'] == 'skeleton']
    for m in members:
        known_ids = {s['character'] for s in skeletons if s['character'] and s['game']==m['game'] and s['scope']==m['scope']}
        if not m['character'] and len(known_ids)==1: m['character']=next(iter(known_ids))
        m['characterKey']='|'.join((m['game'], m['scope'], m['character']))
    clips = match_clips(members)
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
    catalog = dict(schema=CATALOG_SCHEMA, layout='folder', folder=str(root), clips=sorted(clips, key=lambda c:(c['character'], c['name'], c['archive'])),
                   characters=[dict(id=c, character=next(m['character'] for m in clips if m['characterKey']==c),
                                    game=next(m['game'] for m in clips if m['characterKey']==c),
                                    name=(GAMES.get(c.split('|')[0], 'Unknown game')+' · '+c.split('|')[-1].upper()+' · '+Path(c.split('|')[1]).name),
                                    folder=Path(c.split('|')[1]).name, inventoried=True,
                                    archiveCount=len({m['archive'] for m in clips if m['characterKey']==c and m['archive']}),
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


def structured_folders(root, game, layout, folders):
    """The folders to read per kind, and the game they belong to with how it was identified."""
    requested = game if game not in ('', 'auto') else ''
    evidence = 'chosen for this source' if requested else ''
    if layout == 'game':
        found, evidence = (requested, evidence) if requested else executable_game(root)
        if not found:
            found, evidence = material_game(root)
        if not found:
            try:
                found, evidence = probe_game([root / 'chr'])
            except Exception:
                found, evidence = '', ''
        return resolve_folders(root, game_folders(found)), found, evidence
    if not folders or not any(folders.get(kind) for kind in KINDS):
        raise ValueError('A custom layout needs at least one animation folder. Edit the source and add its folders.')
    return resolve_folders(root, folders), requested, evidence


def index_source(root, cache, notify, game, layout, folders=None, recursive=True):
    """List a structured source by file name. Characters are inventoried when chosen."""
    notify('inventory', 'Listing the source folders', 10)
    resolved, source_game, evidence = structured_folders(root, game, layout, folders)
    recursive = bool(recursive) and layout == 'custom'
    if not resolved['animations']:
        raise ValueError('No animation folder found. A game folder keeps its ANIBND archives in chr; choose the game or mod folder that contains chr, or edit the source’s folders.')
    archives = kind_files(resolved['animations'], 'animations', recursive, cache)
    notify('inventory', f'Indexing {len(archives)} animation archives', 40)
    groups, unnamed, warnings = {}, [], []
    for path in archives:
        owner = leading_id(path)
        if owner:
            groups.setdefault(owner, []).append(path)
        else:
            unnamed.append(path.name)
    if unnamed:
        warnings.append(f"{len(unnamed)} animation archive{'s do' if len(unnamed) != 1 else ' does'} not start with a character ID and {'were' if len(unnamed) != 1 else 'was'} skipped: {', '.join(unnamed[:5])}{', …' if len(unnamed) > 5 else ''}.")
    models, references = {}, []
    for path in kind_files(resolved['characters'], 'characters', recursive, cache):
        ident = asset_id(path)
        if ident == 'c0000':
            references.append(path)
        elif re.fullmatch(r'c\d{4}', ident):
            # The first folder wins; within it a binder (with its textures) beats an extracted FLVER.
            previous = models.get(ident)
            if not previous or ('bnd' in path.name.lower() and 'bnd' not in previous.name.lower() and previous.parent == path.parent):
                models[ident] = path
    parts = {}
    for path in kind_files(resolved['parts'], 'parts', recursive, cache):
        ident = asset_id(path)
        if ident.endswith(('_l', '_m')) or ident in parts:
            continue
        parts[ident] = dict(id=ident, name=ident.upper(), path=str(path), selected=False, game=source_game, scope=str(root),
                            role=ROLES.get(ident.split('_')[0], 'Extra model'), container='Binder + textures')
    libraries = [dict(path=str(p), game=source_game, scope=str(root), loose=False,
                      kind='matbin' if '.matbinbnd' in p.name.lower() else 'mtd')
                 for p in kind_files(resolved['materials'], 'materials', recursive, cache)]
    if not libraries:
        warnings.append('No material library found in the source’s material folders. Elden Ring needs material/allmaterial.matbinbnd.dcx; older games mtd/*.mtdbnd.dcx.')
    if not groups:
        warnings.append('No animation archives found. A game folder keeps cXXXX.anibnd.dcx files in chr.')
    textures = [str(f) for f in resolved['textures']]
    characters = [dict(id=owner, character=owner, game=source_game, name=owner.upper(), folder='',
                       archives=[str(p) for p in paths], archiveCount=len(paths), bytes=sum(p.stat().st_size for p in paths),
                       model=str(models[owner]) if owner in models else '', inventoried=False, count=None)
                  for owner, paths in sorted(groups.items())]
    catalog = dict(schema=CATALOG_SCHEMA, layout=layout, folder=str(root), game=source_game, gameEvidence=evidence,
                   recursive=recursive, folders={k: [str(f) for f in v] for k, v in resolved.items()},
                   characters=characters, clips=[], games=[source_game] if source_game else [],
                   parts=list(parts.values()),
                   models=[dict(id=k, name=k.upper(), path=str(p), selected=False, game=source_game, scope=str(root),
                                role='Character', container='Binder + textures' if 'bnd' in p.name.lower() else 'FLVER')
                           for k, p in sorted(models.items())],
                   materialBinder='', textureDirectory='', referenceModel='', textureFolders=textures,
                   materialLibraries=libraries,
                   referenceModels=[dict(path=str(p), game=source_game, scope=str(root)) for p in references],
                   warnings=warnings, archiveCount=len(archives), errorCount=0, archiveSignatures={})
    destination = structured_catalog_path(cache, root, layout, catalog['folders'], recursive)
    # Characters already inventoried keep their clips while their archives are unchanged.
    if destination.is_file():
        try:
            previous = json.loads(destination.read_text(encoding='utf-8'))
            if previous.get('schema') == CATALOG_SCHEMA and previous.get('game') == source_game:
                carried = {}
                for entry in previous.get('characters', []):
                    current = next((c for c in characters if c['id'] == entry['id']), None)
                    if (current and entry.get('inventoried') and entry['archives'] == current['archives']
                            and all(previous['archiveSignatures'].get(a) == signature(Path(a)) for a in current['archives'])):
                        current.update({k: entry[k] for k in ('inventoried', 'count', 'ready', 'game', 'errors') if k in entry})
                        carried[entry['id']] = True
                catalog['clips'] = [c for c in previous.get('clips', []) if c['characterKey'] in carried
                                    and all(Path(a).is_file() and previous['archiveSignatures'].get(a) == signature(Path(a)) for a in c.get('inputArchives', []))]
                kept = {a for c in catalog['characters'] if c['inventoried'] for a in c['archives']}
                kept |= {a for c in catalog['clips'] for a in c.get('inputArchives', [])}
                catalog['archiveSignatures'] = {a: s for a, s in previous['archiveSignatures'].items() if a in kept}
                catalog['games'] = sorted({c['game'] for c in catalog['clips'] if c['game']} | set(catalog['games']))
        except (OSError, ValueError, KeyError):
            pass
    write_json(destination, catalog)
    notify('inventory', f'Found {len(characters)} characters with animations', 90)
    return destination, catalog


def structured_catalog_path(cache, root, layout, folders, recursive):
    identity = json.dumps(dict(root=str(root), layout=layout, folders=folders, recursive=recursive), sort_keys=True)
    return Path(cache).resolve() / 'catalogs' / (hashlib.sha256(identity.encode()).hexdigest()[:24] + '.json')


def inventory_character(catalog_path, character, cache, notify=lambda *args: None, oodle=''):
    """Read one character's animation archives in a structured source and match its clips."""
    catalog_path = Path(catalog_path)
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    if catalog.get('layout') not in STRUCTURED:
        raise ValueError('Only game and custom layouts load characters separately. Scan the folder instead.')
    entry = next((c for c in catalog['characters'] if c['id'] == character or c['character'] == str(character).lower()), None)
    if not entry:
        raise ValueError(f'{character} has no animation archives in this source.')
    configure_oodle(oodle)
    cache = Path(cache).resolve()
    archives = [Path(a) for a in entry['archives']]
    members, errors = [], []
    for index, path in enumerate(archives):
        notify('inventory', f"Reading {entry['name']} · {path.name} ({index+1}/{len(archives)})", 8 + int(80*index/max(1, len(archives))))
        try:
            members += archive_members(path, cache)
        except Exception as exc:
            errors.append(f'{path.name}: {exc}')
    if not any(m['kind'] == 'skeleton' for m in members):
        # Archives without a skeleton can store their clips under another character's
        # folder; that character's base archive then supplies the skeleton.
        named = {character_id(m['member']) for m in members if m['kind'] == 'animation'} - {'', entry['character']}
        for other in sorted(named):
            base = next((Path(a) for c in catalog['characters'] if c['id'] == other for a in c['archives']
                         if Path(a).name.lower() in (other + '.anibnd', other + '.anibnd.dcx')), None)
            if not base:
                continue
            notify('inventory', f'Reading the skeleton in {base.name}', 90)
            try:
                members += [m for m in archive_members(base, cache) if m['kind'] in ('skeleton', 'compendium')]
                archives.append(base)
            except Exception as exc:
                errors.append(f'{base.name}: {exc}')
    requested = catalog.get('game', '')
    detected = {m['sourceHavok'].get('game') for m in members if m['sourceHavok'].get('game')}
    character_game = requested or (next(iter(detected)) if len(detected) == 1 else '')
    if len(detected) > 1:
        errors.append(f"{entry['name']}'s archives identify several games ({', '.join(GAMES[g] for g in sorted(detected))}). Keep one game per source.")
    for m in members:
        m.update(character=entry['character'], scope=catalog['folder'], characterKey=entry['id'],
                 game=m['sourceHavok'].get('game', '') or character_game)
    clips = match_clips(members)
    if requested:
        for clip in clips:
            if clip['game'] and clip['game'] != requested:
                clip['issues'].append(f"This archive is from {GAMES[clip['game']]}, but the source is set to {GAMES[requested]}. Set the source game to Auto detect or {GAMES[clip['game']]}.")
                clip['ready'] = False
    catalog['clips'] = [c for c in catalog['clips'] if c['characterKey'] != entry['id']] + \
        sorted(clips, key=lambda c: (c['name'], c['archive']))
    entry.update(inventoried=True, count=len(clips), ready=sum(c['ready'] for c in clips), errors=errors,
                 game=character_game or next((c['game'] for c in clips if c['game']), ''))
    catalog['archiveSignatures'].update({str(p): signature(p) for p in archives if p.is_file()})
    catalog['games'] = sorted({c['game'] for c in catalog['clips'] if c['game']} | ({requested} if requested else set()))
    write_json(catalog_path, catalog)
    return catalog


def refresh_clip(catalog_path, catalog, clip_id, cache, notify=lambda *args: None, oodle=''):
    """Reload a structured source's character when the clip's archives changed since they were read."""
    clip = next((c for c in catalog['clips'] if c['id'] == clip_id), None)
    if not clip or catalog.get('layout') not in STRUCTURED:
        return catalog, clip_id
    current = all(Path(a).is_file() and catalog['archiveSignatures'].get(a) == signature(Path(a)) for a in clip.get('inputArchives', []))
    if current and all(Path(p).is_file() for p in (clip['path'], clip['skeleton'], clip['compendium'], clip['skeletonCompendium']) if p):
        return catalog, clip_id
    notify('inventory', f"{Path(clip['archive']).name} changed since it was read; reading it again", 6)
    catalog = inventory_character(catalog_path, clip['characterKey'], cache, notify, oodle)
    again = [c for c in catalog['clips'] if c['archive'] == clip['archive'] and c['member'] == clip['member']]
    if len(again) != 1:
        raise ValueError(f"{clip['name']} is no longer in {Path(clip['archive']).name}. Choose the animation again.")
    return catalog, again[0]['id']


def load_catalog(path, folder, check_sources=False):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    if catalog.get('schema') not in (2, CATALOG_SCHEMA):
        raise ValueError('This scan was created by an older bridge version. Click Scan folder to rebuild it with game-aware matching.')
    catalog.setdefault('layout', 'folder')
    if Path(catalog['folder']).resolve() != Path(folder).resolve():
        raise ValueError('This scan belongs to another folder. Scan the selected folder again.')
    if check_sources and catalog['layout'] == 'folder':
        for source in catalog['sources']:
            p = Path(source['path'])
            if not p.is_file() or signature(p) != source['signature']:
                raise ValueError(f'Assets changed since the last scan: {p.name}. Scan the folder again.')
    return catalog


def ui_catalog(catalog):
    """What the UI needs: no signatures, type IDs or Havok headers."""
    keep = ('id', 'name', 'archive', 'member', 'character', 'characterKey', 'game', 'scope', 'ready', 'issues',
            'compendium', 'skeletonCompendium')
    result = {k: v for k, v in catalog.items() if k not in ('sources', 'archiveSignatures', 'clips')}
    result['clips'] = [{k: c.get(k) for k in keep} for c in catalog['clips']]
    return result


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
    structured = catalog.get('layout') in STRUCTURED
    wolf = clip['character'] == 'c0000' and source_game == 'sekiro'
    player = clip['character'] == 'c0000'
    if not wolf and preset in PRESETS: preset = 'auto'
    preset = ('wolf' if wolf else 'player' if player else 'npc') if preset == 'auto' else preset
    if structured:
        # One game per structured source: models are found by ID rather than by shared folder.
        available = catalog['parts'] if player else catalog['models']
    else:
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
    if structured:
        references = [r['path'] for r in catalog['referenceModels']]
        libraries = list(catalog['materialLibraries'])
    else:
        references = [r['path'] for r in catalog['referenceModels'] if r['game']==source_game and r['scope']==clip['scope']]
        libraries = [m for m in catalog['materialLibraries'] if m['game']==source_game and m['scope']==clip['scope']]
    reference=references[0] if len(references)==1 else ''
    if source_game=='er': libraries=[m for m in libraries if m.get('kind')=='matbin' or '.matbinbnd' in m['path'].lower()]
    libraries.sort(key=lambda m:(m.get('loose',False), not Path(m['path']).name.lower().startswith(('allmaterial.', 'allmaterialbnd.')), m['path']))
    return dict(animation=clip['path'], skeleton=clip['skeleton'], compendium=clip['compendium'],
                skeletonCompendium=clip['skeletonCompendium'], materialBinder=libraries[0]['path'] if libraries else '',
                textureDirectory='' if structured else clip['scope'], characterSource='' if structured else clip['scope'],
                textureFolders=catalog.get('textureFolders', []) if structured else [],
                textureRecursive=bool(catalog.get('recursive')) if structured else False,
                layout=catalog.get('layout', 'folder'), preset=preset, game=source_game,
                referenceModel=reference,
                parts=parts, missing=missing, character=clip['character'], clipName=clip['name'])
