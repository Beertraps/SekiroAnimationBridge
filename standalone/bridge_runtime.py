"""Shared CLI / UI conversion runner. Dependencies stay outside Blender."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = HERE.parent
APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
EVENT_PREFIX = 'BRIDGE_EVENT '


def event(stage, message, progress, **extra):
    print(EVENT_PREFIX + json.dumps(dict(stage=stage, message=message, progress=progress, **extra)), flush=True)


def default_decoder():
    """The decoder shipped in a release ZIP, otherwise the one build_decoder.cmd builds."""
    bundled = HOME / 'decoder/SekiroMotionDecoder.exe'
    return bundled if bundled.is_file() else APP / 'decoder/SekiroMotionDecoder.exe'


def existing(value, label):
    if not value or not Path(value).is_file():
        raise ValueError(f'{label} was not found. Browse to the file and try again.\n{value or "No path selected"}')
    return str(Path(value).resolve())


def output_file(value, suffix, force=False):
    if not value or Path(value).suffix.lower() != suffix:
        raise ValueError(f'Choose an output filename ending in {suffix}.')
    p = Path(value).resolve()
    from dcx_codec import protect_output
    protect_output(p)
    if p.exists() and not force:
        raise ValueError(f'Output already exists. Choose a new name or enable Replace existing output.\n{p}')
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run(args):
    process = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for line in process.stdout:
        print(line.rstrip(), flush=True)
    code = process.wait()
    if code:
        raise RuntimeError(f'{Path(str(args[0])).name} stopped with exit code {code}. The activity log above contains the details.')


def choice(request, key, allowed, label):
    value = request.get(key) or allowed[0]
    if value not in allowed:
        raise ValueError(f'{label} must be one of: {", ".join(allowed)}.')
    return value


def number(request, key, label):
    value = request.get(key)
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a number.') from None


def sampling_arguments(request):
    """blender_bridge.py export options from a UI / CLI request."""
    args = ['--frame-range', choice(request, 'frameRange', ('scene', 'action', 'clip', 'custom'), 'Frame range')]
    if args[1] == 'custom':
        start, end = number(request, 'frameStart', 'Start frame'), number(request, 'frameEnd', 'End frame')
        if start is None or end is None or end <= start:
            raise ValueError('Enter a custom frame range whose end frame is after its start frame.')
        args += ['--frame-start', f'{start:g}', '--frame-end', f'{end:g}']
    rate = number(request, 'frameRate', 'Frame rate')
    if rate:
        if not 1 <= rate <= 240:
            raise ValueError('Choose an output frame rate between 1 and 240 fps, or leave it empty for the source rate.')
        args += ['--frame-rate', f'{rate:g}']
    if str(request.get('exportAction') or '').strip():
        args += ['--action', request['exportAction'].strip()]
    args += ['--tracks', choice(request, 'trackSet', ('original', 'keyed', 'all'), 'Track set'),
             '--root-motion', choice(request, 'rootMotion', ('auto', 'object', 'bone', 'none'), 'Root motion')]
    if args[-1] == 'bone':
        if str(request.get('rootBone') or '').strip():
            args += ['--root-bone', request['rootBone'].strip()]
        args += ['--root-axes', 'xyz' if request.get('rootVertical') else 'xy']
        if request.get('rootYaw'):
            args.append('--root-yaw')
    return args


def writer_arguments(request, fmt, stats):
    from hkx_compression import QUANTIZATION, DEFAULT_QUANTIZATION, DEFAULT_TOLERANCE
    args = ['--format', fmt, '--game', request.get('exportGame', 'auto'), '--stats-json', stats]
    if fmt == 'spline':
        tolerance = number(request, 'tolerance', 'Spline tolerance') or DEFAULT_TOLERANCE
        if not 1e-6 <= tolerance <= 0.1:
            raise ValueError('Spline tolerance must be between 0.000001 and 0.1.')
        args += ['--quantization', choice(request, 'quantization', (DEFAULT_QUANTIZATION, *QUANTIZATION), 'Rotation quantization'),
                 '--tolerance', f'{tolerance:g}']
    if request.get('verify', True):
        args.append('--verify')
    return args


def discover_source(request, notify=event):
    from asset_discovery import discover
    return discover(request.get('assetFolder', ''), HOME/'work/asset-cache', notify, request.get('oodle', ''), request.get('game', 'auto'),
                    request.get('sourceLayout') or 'folder', request.get('sourceFolders'), request.get('sourceRecursive', True))


def catalog_file(request):
    path = Path(request.get('assetCatalog') or '').resolve()
    if path.parent != (HOME/'work/asset-cache/catalogs').resolve() or not path.is_file():
        raise ValueError('Scan the source first.')
    return path


def character_clips(catalog, character):
    """Clip names repeat across characters; a chosen character narrows a name to its own clips."""
    if not character:
        return catalog
    return dict(catalog, clips=[c for c in catalog['clips'] if character in (c['characterKey'], c['character'])])


def part_clips(models, manifest, animation, game, decoder, work, tae_binder=None, character='', notify=event):
    """Match each animated weapon part to the clip it plays with this animation, and decode it into the manifest."""
    from part_animations import plan, prepare, character_tae
    rows = plan(models, Path(animation).name, character_tae(tae_binder), character)
    if not rows:
        return [], []
    notify('character', 'Decoding weapon part animations', 46)

    def decode(clip, compendium, skeleton, output):
        # A part's skeleton shares the clips' compendium.
        run([decoder, clip, compendium, skeleton, output, *([compendium] if compendium != '-' else [])])
    report, notices = prepare(manifest, rows, decode, work, game)
    for notice in notices:
        print('NOTICE: ' + notice, flush=True)
    return report, notices


def weapon_places(models, manifest, animation, game, tae_binder=None, character=''):
    """Record where the character's TAE moves or hides each weapon model during the animation (event 715)."""
    from part_animations import plan, locate, character_tae, character_locations
    events = character_locations(tae_binder)
    if game != 'sekiro' or not events:
        return [], []
    report, notices = locate(manifest, plan(models, Path(animation).name, character_tae(tae_binder), character),
                             Path(animation).name, events, game)
    for notice in notices:
        print('NOTICE: ' + notice, flush=True)
    return report, notices


def part_outputs(blender, blend, motion, output, force, temp):
    """Sample every animated weapon part over the character's exported frames.

    Returns (index entry, final HKX path) pairs. A part clip keeps its member name,
    such as a076_405010_1.hkx, beside the character's HKX; two models that share a
    clip name each get a folder named after the model.
    """
    sampled = json.loads(Path(motion).read_text(encoding='utf-8')).get('export', {})
    folder = temp / 'parts'
    event('blender', 'Sampling the weapon part animations in Blender', 50)
    run([blender, '--background', blend, '--python', HERE / 'blender_parts.py', '--', 'export', '--output-dir', folder,
         '--frame-start', f"{sampled['frameStart']:g}", '--frame-end', f"{sampled['frameEnd']:g}"])
    if not (folder / 'parts.json').is_file():
        raise RuntimeError('Blender did not sample the part animations. See the activity log.')
    index = json.loads((folder / 'parts.json').read_text(encoding='utf-8'))
    if not index:
        print('NOTICE: This scene has no animated weapon parts, so only the character HKX is written.', flush=True)
    names = [entry['clip'].lower() for entry in index]
    pairs = []
    for entry in index:
        if entry['missingBones']:
            print(f"NOTICE: {entry['name']}'s rig lacks {', '.join(entry['missingBones'][:6])}; those tracks keep the reference pose.", flush=True)
        target = output.parent / entry['clip'] if names.count(entry['clip'].lower()) == 1 else output.parent / entry['name'] / entry['clip']
        if target.resolve() == output.resolve():
            raise ValueError(f"The HKX output has the name of {entry['name']}'s part clip. Choose another name for the character's HKX.")
        pairs.append((entry, output_file(str(target), '.hkx', force)))
    return pairs


def binder_request(request):
    """(the animation binder that export adds the HKX to, the member name or '' for the clip's own), checked before
    anything is written; None without addToBinder."""
    if not request.get('addToBinder'):
        return None
    binder = str(request.get('binder') or '').strip()
    if not binder:
        raise ValueError('Choose the animation binder to add the HKX to, such as c0000_a05x.anibnd.dcx.')
    path = Path(binder).resolve()
    if not path.name.lower().endswith(('.anibnd', '.anibnd.dcx')):
        raise ValueError(f'Choose an animation binder, a file ending in .anibnd.dcx, to add the HKX to.\n{path}')
    from dcx_codec import protect_output
    protect_output(path)
    from binder_members import CLIP
    name = str(request.get('binderMember') or '').strip()
    if name and not CLIP.fullmatch(name):
        raise ValueError(f'Name the HKX in the binder like the game\'s clips, aXXX_YYYYYY.hkx, such as a050_002000.hkx: {name}')
    return path, name


def binder_member(into, motion):
    """The member name and the archive to start a new binder from, for the sampled motion; checked before writing."""
    binder, name = into
    name = name or Path(str(motion.get('clip') or '')).name
    from binder_members import CLIP
    if not CLIP.fullmatch(name):
        raise ValueError(f'The clip\'s own name, {name or "unknown"}, is not one the game uses. Name the HKX in the binder, '
                         'such as a050_002000.hkx.')
    base = motion.get('archive') or ''
    if not binder.is_file() and not (base and Path(base).is_file()):
        raise ValueError('The binder does not exist yet, and the scene does not record the archive its clip came from '
                         f'to start it from. Choose an existing binder.\n{binder}')
    return name, base


def add_to_binder(into, name, base, motion, hkx, temp):
    """Add the written HKX to the binder, keeping a .bak of the binder the first time. Returns the report."""
    from binder_members import add_member, backup
    binder = into[0]
    event('write', f'Adding {name} to {binder.name}', 92)
    data, report = add_member(binder, name, hkx.read_bytes(), base or None, motion.get('member', ''))
    report['backup'] = backup(binder)
    staging = temp / 'binder.dcx'
    staging.write_bytes(data)
    binder.parent.mkdir(parents=True, exist_ok=True)
    atomic_copy(staging, binder)
    print(f"{'Replaced' if report['replaced'] else 'Added'} {report['member']} (ID {report['id']}) in {binder}"
          + (f", from {report['base']}" if report['base'] != str(binder) else '')
          + (f"; the binder before it is kept as {Path(report['backup']).name}" if report['backup'] else ''), flush=True)
    if not report['replaced']:
        print('NOTICE: A new animation ID needs a TAE entry of its own, and something that plays it, before the game uses it.',
              flush=True)
    return report


def donor_request(request):
    """Input options of the retarget donor, with the tools and weapon settings it shares with the target.

    A donor gets no weapon part clips, since the bake does not read them.
    """
    donor = request['donor']
    if not isinstance(donor, dict):
        raise ValueError('The retarget donor must be a set of input options, like the target clip.')
    shared = {key: request[key] for key in ('decoder', 'oodle', 'weaponAttachments') if key in request}
    return {**shared, **donor, 'partAnimations': False}


def donor_event(stage, message, progress, **extra):
    """Progress of the donor's preparation, which runs between the target's character and Blender."""
    event(stage, 'Donor: ' + message, min(60, 40 + progress // 2), **extra)


def add_donor_report(report, donor):
    """Describe the donor beside the target. Its warnings join the target's, marked as the donor's."""
    report['warnings'] = [*report['warnings'], *('Donor: ' + warning for warning in donor.pop('warnings'))]
    report['donor'] = donor
    return report


def convert(request):
    mode = request.get('mode', 'import')
    from dcx_codec import configure_oodle
    configure_oodle(request.get('oodle', ''))
    if mode == 'discover':
        output, catalog = discover_source(request)
        structured = catalog['layout'] != 'folder'
        from asset_sources import plural
        found = plural(len(catalog['characters']), 'character') if structured else plural(len(catalog['clips']), 'animation')
        event('done', f"Found {found} in {plural(catalog['archiveCount'], 'archive')}", 100,
              output=str(output), report=dict(catalog=str(output), folder=catalog['folder'], layout=catalog['layout'], game=catalog.get('game', ''),
              clips=len(catalog['clips']), characters=len(catalog['characters']), warnings=catalog['warnings']))
        return str(output)
    if mode == 'inventory':
        from asset_discovery import load_catalog, inventory_character
        from asset_sources import plural
        path = catalog_file(request)
        load_catalog(path, request.get('assetFolder', ''))
        catalog = inventory_character(path, request.get('assetCharacter', ''), HOME/'work/asset-cache', event, request.get('oodle', ''))
        entry = next(c for c in catalog['characters'] if request.get('assetCharacter') in (c['id'], c['character']))
        for problem in entry.get('errors', []):
            print('NOTICE: ' + problem, flush=True)
        event('done', f"Read {plural(entry['count'], 'animation')} of {entry['name']}", 100, output=str(path),
              report=dict(catalog=str(path), folder=catalog['folder'], character=entry['id'], clips=entry['count'],
                          ready=entry['ready'], warnings=entry.get('errors', [])))
        return str(path)
    if mode not in ('import', 'export', 'inspect', 'write'):
        raise ValueError('Choose import, export or inspect.')
    event('validate', 'Checking files and output', 4)
    # 'write' takes motion JSON that Blender already sampled (the retarget add-on's Export HKX).
    blender = existing(request.get('blender'), 'Blender executable') if mode != 'write' else None
    force = bool(request.get('force', False))
    with tempfile.TemporaryDirectory(prefix='SekiroBridge-') as scratch:
        temp = Path(scratch)
        if mode == 'inspect':
            blend = existing(request.get('inputBlend'), 'Edited Blender scene')
            info_path = temp / 'scene.json'
            event('blender', 'Reading actions and frame ranges', 30)
            run([blender, '--background', blend, '--python', HERE / 'blender_bridge.py', '--', 'inspect', '--output-json', info_path])
            info = json.loads(info_path.read_text(encoding='utf-8'))
            if info.get('archive'):
                # Export adds the clip to this archive, or to a copy of it where the game's own files are protected.
                from dcx_codec import protect_output
                try:
                    protect_output(info['archive'])
                    info['archiveWritable'] = True
                except ValueError:
                    info['archiveWritable'] = False
            for action in info['actions']:
                print(f"  {'*' if action['active'] else ' '} {action['name']}: frames {action['frameStart']:g}-{action['frameEnd']:g}, "
                      f"{action['keyedBones']} keyed bones" + (f", {len(action['untracked'])} outside the clip's tracks" if action['untracked'] else ''))
            count = len(info['actions'])
            event('done', f"Read {count} action{'' if count == 1 else 's'} from {Path(blend).name}", 100, output=blend, report=dict(scene=info))
            return blend

        def prepare(request, temp, event=event):
            """Decode one clip into temp and prepare its character. A retarget donor passes an event that names it."""
            refreshed = False
            tae_binder, tae_character, origin = None, '', {}
            if request.get('inputMethod') == 'folder':
                from asset_discovery import load_catalog, selection, inventory_character, refresh_clip
                cache, character, clip = HOME/'work/asset-cache', request.get('assetCharacter', ''), request.get('assetClip')
                if not request.get('assetCatalog'):
                    path, catalog = discover_source(request, event)
                    if catalog['layout'] != 'folder':
                        if not character:
                            raise ValueError(f"This source holds {len(catalog['characters'])} characters. Choose one, for example -AssetCharacter c0000.")
                        catalog = inventory_character(path, character, cache, event, request.get('oodle', ''))
                else:
                    path = catalog_file(request)
                    catalog = load_catalog(path, request.get('assetFolder', ''), check_sources=True)
                    if catalog['layout'] != 'folder':
                        # A mod's archive may change between imports; read it again instead of using stale members.
                        catalog, clip = refresh_clip(path, catalog, clip, cache, event, request.get('oodle', ''))
                if not any(c['id'] == clip for c in catalog['clips']):
                    catalog = character_clips(catalog, character)
                resolved = selection(catalog, clip, request.get('preset', 'auto'))
                refreshed = clip != request.get('assetClip')
                requested_game = request.get('game', 'auto')
                if requested_game not in ('', 'auto', resolved['game']):
                    raise ValueError('The selected clip belongs to a different game. Choose Auto detect or the matching source game.')
                request['game'] = resolved['game']
                # Resolve again at conversion time so stale manual paths can never
                # substitute a different character's skeleton in folder mode.
                for key in ('animation', 'skeleton', 'compendium', 'skeletonCompendium'):
                    request[key] = resolved[key]
                if not request.get('models'):
                    request['models'] = [p['path'] for p in resolved['parts'] if p['selected']]
                for key in ('textureDirectory', 'materialBinder', 'referenceModel'):
                    if not request.get(key): request[key] = resolved[key]
                request['textureFolders'], request['textureRecursive'] = resolved['textureFolders'], resolved['textureRecursive']
                # The character's TAE tells which part clip plays with a body clip that several animation IDs share.
                from part_animations import character_binder
                chosen = next(c for c in catalog['clips'] if c['id'] == clip or c['name'].lower() == str(clip).lower())
                tae_binder, tae_character = character_binder(catalog, chosen), chosen.get('character', '')
                # Export can add the edited clip to the archive it came from, beside the member it came from.
                origin = dict(archive=chosen.get('archive', ''), member=chosen.get('member', ''))
            animation = existing(request.get('animation'), 'Animation HKX')
            skeleton = existing(request.get('skeleton'), 'Skeleton HKX')
            compendium = existing(request['compendium'], 'Compendium') if request.get('compendium') else '-'
            from game_profiles import havok_info, resolve_game, GAMES
            from dcx_codec import unwrap
            animation_data = unwrap(Path(animation).read_bytes())[0]
            skeleton_data = unwrap(Path(skeleton).read_bytes())[0]
            source_info = havok_info(animation_data, animation)
            source_game = resolve_game(source_info, request.get('game', 'auto'))
            source_info['game'] = source_game
            skeleton_info = havok_info(skeleton_data, skeleton)
            if source_info['version'] != skeleton_info['version']:
                raise ValueError('Animation and skeleton use different Havok versions. Select files from the same game and character.')
            if source_info['container']=='packfile' and not source_info['littleEndian']:
                raise ValueError('This version supports PC little-endian HKX files.')
            decoded_animation, decoded_skeleton = temp/'source.hkx', temp/'skeleton.hkx'
            decoded_animation.write_bytes(animation_data); decoded_skeleton.write_bytes(skeleton_data)
            decoder = existing(request.get('decoder') or str(default_decoder()), 'Animation decoder')
            version = subprocess.run([decoder, '--version'], capture_output=True, text=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if version.returncode != 0 or 'skeleton-compendiums' not in version.stdout:
                raise ValueError('The installed animation decoder is from an older version. Run tools/SekiroMotionDecoder/build_decoder.cmd from this updated tool folder.')
            if source_info['container']=='packfile' and 'native-packfiles' not in version.stdout:
                raise ValueError('This game needs the 0.5 decoder with native packfile support. Run tools/SekiroMotionDecoder/build_decoder.cmd.')
            event('decode', 'Decoding animation and skeleton', 15)
            motion = temp / 'motion.json'
            skeleton_compendium = request.get('skeletonCompendium', '')
            decoder_args = [decoder, decoded_animation, compendium, decoded_skeleton, motion]
            if skeleton_compendium:
                if 'separate-compendiums' not in version.stdout:
                    raise ValueError('Folder import requires the 0.4 decoder. Rebuild with tools/SekiroMotionDecoder/build_decoder.cmd.')
                decoder_args.append(existing(skeleton_compendium, 'Skeleton compendium'))
            run(decoder_args)
            document = json.loads(motion.read_text(encoding='utf-8-sig'))
            document.update(game=source_game, sourceHavok=source_info, clip=Path(animation).name, **origin)
            motion.write_text(json.dumps(document), encoding='utf-8')
            report = dict(clip=Path(animation).name, frames=document['frameCount'], tracks=document['trackCount'],
                          game=GAMES[source_game], compression=document.get('compression', 'spline'), parts=0, textures=0, warnings=[],
                          catalogRefreshed=refreshed)
            character_args = []
            if request.get('includeCharacter', bool(request.get('characterSource') or request.get('models'))):
                from character_assets import scan_character, prepare_character
                sources = request.get('models', [])
                if not sources:
                    if not request.get('characterSource'):
                        raise ValueError('Choose a character folder or model files, or select Rig only.')
                    scan = scan_character(request['characterSource'], request.get('preset', 'auto'), source_game)
                    sources = [p['path'] for p in scan['parts'] if p['selected']]
                    if scan['missing']:
                        raise ValueError('The selected folder is missing these Wolf parts: ' + ', '.join(scan['missing']) + '. Select the files explicitly to import a partial character.')
                event('character', 'Preparing model parts, skin weights and textures', 32)
                manifest = prepare_character(sources, temp / 'character', request.get('textureDirectory', ''),
                    request.get('materialBinder', ''), request.get('previewTexture', ''),
                    request.get('referenceModel', ''), request.get('weaponAttachments', {}), document['skeletonName'], source_game,
                    [bone['name'] for bone in document['skeleton']['bones']],
                    request.get('textureFolders') or None, bool(request.get('textureRecursive')), request.get('modelMasks'))
                if request.get('partAnimations', True):
                    report['partClips'], report['partNotices'] = part_clips(sources, manifest, animation, source_game, decoder,
                                                                             temp / 'parts', tae_binder, tae_character, event)
                places, notices = weapon_places(sources, manifest, animation, source_game, tae_binder, tae_character)
                if places or notices:
                    report['weaponPlaces'] = places
                    report['partNotices'] = report.get('partNotices', []) + notices
                character = json.loads(manifest.read_text(encoding='utf-8'))
                report.update(parts=len(character['models']), textures=character['texture_count'], warnings=character['warnings'],
                              vertices=sum(m['stats']['vertices'] for m in character['models']),
                              triangles=sum(m['stats']['triangles'] for m in character['models']))
                character_args = ['--character-manifest', manifest]
            return motion, character_args, report

        if mode == 'import':
            output = output_file(request.get('outputBlend'), '.blend', force)
            donor_input = donor_request(request) if request.get('donor') else None
            motion, character_args, report = prepare(request, temp)
            if donor_input:
                # A second clip for the retarget add-on, from any source or game. Blender places it beside the target.
                (temp / 'donor').mkdir()
                try:
                    donor_motion, donor_character, donor = prepare(donor_input, temp / 'donor', donor_event)
                except (ValueError, RuntimeError) as exc:
                    raise (ValueError if isinstance(exc, ValueError) else RuntimeError)(f'Donor: {exc}') from exc
                if Path(donor_input['animation']).resolve() == Path(request['animation']).resolve():
                    raise ValueError('The donor is the same animation as the target. Choose a different clip as the donor.')
                character_args += ['--donor-motion-json', donor_motion]
                if donor_character:
                    character_args += ['--donor-character-manifest', donor_character[-1]]
                add_donor_report(report, donor)
            event('blender', 'Building the editable Blender scene', 62)
            staged_blend = temp / output.name
            run([blender, '--background', '--factory-startup', '--python', HERE / 'blender_bridge.py', '--',
                 'import', '--motion-json', motion, '--output-blend', staged_blend, *character_args])
            if not staged_blend.is_file():
                raise RuntimeError('Blender did not save the scene. See the activity log.')
            # Copy through a sibling temporary file before atomically replacing the final file.
            atomic_copy(staged_blend, output)
            event('done', 'Blender scene ready', 100, output=str(output), report=report)
            return str(output)
        writer = existing(request.get('writer') or sys.executable, 'Writer Python')
        if mode == 'write':
            sampled = existing(request.get('motionJson'), 'Sampled motion JSON')
        else:
            blend = existing(request.get('inputBlend'), 'Edited Blender scene')
        output = output_file(request.get('outputHKX'), '.hkx', force)
        into = binder_request(request)
        sidecar = output.with_suffix('.motion.json')
        if sidecar.exists() and not force:
            raise ValueError(f'Motion sidecar already exists. Choose another name or enable Replace existing output.\n{sidecar}')
        fmt = request.get('format', 'interleaved')
        if fmt not in ('interleaved', 'spline'):
            raise ValueError('Output format must be interleaved or spline.')
        motion = temp / 'edited.motion.json'
        staged_hkx = temp / 'edited.hkx'
        stats_path = temp / 'stats.json'
        writing = writer_arguments(request, fmt, stats_path)
        if mode == 'write':
            shutil.copyfile(sampled, motion)
        else:
            sampling = sampling_arguments(request)
            event('blender', 'Sampling the edited animation in Blender', 25)
            run([blender, '--background', blend, '--python', HERE / 'blender_bridge.py', '--', 'export', '--output-json', motion, *sampling])
        parts = part_outputs(blender, blend, motion, output, force, temp) if mode == 'export' and request.get('exportParts') else []
        doc = json.loads(motion.read_text(encoding='utf-8'))
        member, base = binder_member(into, doc) if into else ('', '')
        event('write', f'Writing {fmt} HKX' + (' and part clips' if parts else '') + (' and reading it back' if '--verify' in writing else ''), 70)
        run([writer, '-E', '-X', 'utf8', HERE / 'build_animation.py', motion, staged_hkx, *writing])
        for entry, target in parts:
            # Part clips use the character's format and settings at their own frame rate.
            run([writer, '-E', '-X', 'utf8', HERE / 'build_animation.py', entry['motion'], temp / 'parts' / (entry['model'] + '.hkx'),
                 *writer_arguments(request, fmt, temp / 'parts' / (entry['model'] + '.stats.json'))])
        atomic_copy(motion, sidecar)
        atomic_copy(staged_hkx, output)
        written = []
        for entry, target in parts:
            atomic_copy(temp / 'parts' / (entry['model'] + '.hkx'), target)
            part_stats = json.loads((temp / 'parts' / (entry['model'] + '.stats.json')).read_text(encoding='utf-8'))
            written.append(dict(model=entry['name'], clip=entry['clip'], output=str(target), frames=entry['frames'],
                                frameRate=entry['frameRate'], bytes=part_stats['bytes'], readback=part_stats.get('readback')))
            print(f"Part clip {entry['clip']} of {entry['name']}: {target}", flush=True)
        binder = add_to_binder(into, member, base, doc, staged_hkx, temp) if into else None
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        sampled = doc.get('export', {})
        event('done', f"HKX animation added to {into[0].name}" if binder else 'HKX animation ready for WitchyBND', 100, output=str(output),
              report=dict(frames=doc['frameCount'], tracks=doc['trackCount'], frameRate=doc['frameRate'], compression=fmt,
                          sidecar=str(sidecar), bytes=stats['bytes'], quantization=stats['quantization'],
                          tolerance=stats['tolerance'], readback=stats.get('readback'), action=sampled.get('action', ''),
                          rootMotion=sampled.get('rootMotion', ''), addedTracks=len(sampled.get('addedTracks', [])),
                          warnings=sampled.get('warnings', []), parts=written, binder=binder))
        return str(output)


def atomic_copy(source, target):
    # The temporary sibling makes replacing across drives safe as well.
    with tempfile.NamedTemporaryFile(prefix='.' + target.stem + '-', suffix=target.suffix, dir=target.parent, delete=False) as file:
        staging = Path(file.name)
    try:
        shutil.copyfile(source, staging)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def remember_location():
    """Record this installation so the Blender retarget add-on can find the exporter."""
    try:
        APP.mkdir(parents=True, exist_ok=True)
        (APP / 'bridge-location.json').write_text(json.dumps(dict(folder=str(HERE))), encoding='utf-8')
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True, help='JSON request shared by the UI and PowerShell CLI')
    args = parser.parse_args()
    remember_location()
    try:
        request = json.loads(args.request.read_text(encoding='utf-8-sig'))
        convert(request)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        event('error', str(exc), 0)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
