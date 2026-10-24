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


def discover_source(request):
    from asset_discovery import discover
    return discover(request.get('assetFolder', ''), HOME/'work/asset-cache', event, request.get('oodle', ''), request.get('game', 'auto'),
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


def convert(request):
    mode = request.get('mode', 'import')
    from dcx_codec import configure_oodle
    configure_oodle(request.get('oodle', ''))
    if mode == 'discover':
        output, catalog = discover_source(request)
        structured = catalog['layout'] != 'folder'
        event('done', f"Found {len(catalog['characters'])} characters in {catalog['archiveCount']} archives" if structured else
              f"Found {len(catalog['clips'])} animations in {catalog['archiveCount']} archives", 100,
              output=str(output), report=dict(catalog=str(output), folder=catalog['folder'], layout=catalog['layout'], game=catalog.get('game', ''),
              clips=len(catalog['clips']), characters=len(catalog['characters']), warnings=catalog['warnings']))
        return str(output)
    if mode == 'inventory':
        from asset_discovery import load_catalog, inventory_character
        path = catalog_file(request)
        load_catalog(path, request.get('assetFolder', ''))
        catalog = inventory_character(path, request.get('assetCharacter', ''), HOME/'work/asset-cache', event, request.get('oodle', ''))
        entry = next(c for c in catalog['characters'] if request.get('assetCharacter') in (c['id'], c['character']))
        for problem in entry.get('errors', []):
            print('NOTICE: ' + problem, flush=True)
        event('done', f"Read {entry['count']} animations of {entry['name']}", 100, output=str(path),
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
            for action in info['actions']:
                print(f"  {'*' if action['active'] else ' '} {action['name']}: frames {action['frameStart']:g}-{action['frameEnd']:g}, "
                      f"{action['keyedBones']} keyed bones" + (f", {len(action['untracked'])} outside the clip's tracks" if action['untracked'] else ''))
            count = len(info['actions'])
            event('done', f"Read {count} action{'' if count == 1 else 's'} from {Path(blend).name}", 100, output=blend, report=dict(scene=info))
            return blend
        if mode == 'import':
            refreshed = False
            if request.get('inputMethod') == 'folder':
                from asset_discovery import load_catalog, selection, inventory_character, refresh_clip
                cache, character, clip = HOME/'work/asset-cache', request.get('assetCharacter', ''), request.get('assetClip')
                if not request.get('assetCatalog'):
                    path, catalog = discover_source(request)
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
            output = output_file(request.get('outputBlend'), '.blend', force)
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
            document.update(game=source_game, sourceHavok=source_info, clip=Path(animation).name)
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
                    request.get('textureFolders') or None, bool(request.get('textureRecursive')))
                character = json.loads(manifest.read_text(encoding='utf-8'))
                report.update(parts=len(character['models']), textures=character['texture_count'], warnings=character['warnings'],
                              vertices=sum(m['stats']['vertices'] for m in character['models']),
                              triangles=sum(m['stats']['triangles'] for m in character['models']))
                character_args = ['--character-manifest', manifest]
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
        event('write', f'Writing {fmt} HKX' + (' and reading it back' if '--verify' in writing else ''), 70)
        run([writer, '-E', '-X', 'utf8', HERE / 'build_animation.py', motion, staged_hkx, *writing])
        atomic_copy(motion, sidecar)
        atomic_copy(staged_hkx, output)
        doc = json.loads(motion.read_text(encoding='utf-8'))
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        sampled = doc.get('export', {})
        event('done', 'HKX animation ready for WitchyBND', 100, output=str(output),
              report=dict(frames=doc['frameCount'], tracks=doc['trackCount'], frameRate=doc['frameRate'], compression=fmt,
                          sidecar=str(sidecar), bytes=stats['bytes'], quantization=stats['quantization'],
                          tolerance=stats['tolerance'], readback=stats.get('readback'), action=sampled.get('action', ''),
                          rootMotion=sampled.get('rootMotion', ''), addedTracks=len(sampled.get('addedTracks', [])),
                          warnings=sampled.get('warnings', [])))
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
