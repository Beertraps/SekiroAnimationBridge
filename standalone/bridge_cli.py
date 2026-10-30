"""The bridge's command line for scripts and agents: every command prints one JSON document.

standalone\\bridge_cli.cmd <command> [options], or the conversion Python with standalone/bridge_cli.py.

stdout holds only the result. Progress, the tools' output and notices go to stderr, as the UI's activity log shows
them. The exit code is 0 when the command ran and 1 otherwise; then the result is {"ok": false, "error": "..."}.

  env                        the tools the bridge uses, whether they are ready, and the sources saved in the UI
  games                      the games of the registry and the installed game packages
  detect FOLDER              what a folder is as a source: its layout, game and file counts
  scan FOLDER                index a source into a catalog and list its characters
  clips CATALOG              the clips of a catalog; --character reads that character's archives first
  select CATALOG CLIP        what an import of the clip uses: its files, model parts and material library
  masks MODEL                the numbered mesh groups of a model binder or FLVER
  import CATALOG CLIP        create a Blender scene; --donor-clip adds a retarget donor beside it
  inspect SCENE              the scene's rig, actions and frame ranges
  verify SCENE               numbers to check an import by, with pass or fail checks; --render draws it
  export SCENE               write the edited animation as HKX
  run REQUEST                any request as the UI and sekiro_animation_cli.ps1 send it to bridge_runtime.py

Blender, the decoder and the Oodle DLL default to those saved in the UI; --blender, --decoder and --oodle choose
others. The bridge refuses to write into a game folder, and verify never saves the scene.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from bridge_runtime import EVENT_PREFIX, HERE, HOME

CACHE = HOME / 'work/asset-cache'


class Failure(Exception):
    """A command that cannot finish; its message becomes the result's error."""


def tools(args):
    """The tools as the UI saved them, with the command line's choices first, and the saved settings."""
    from bridge_ui import defaults
    saved = defaults()
    return dict(blender=args.blender or saved['blender'], decoder=args.decoder or saved['decoder'],
                oodle=args.oodle or saved.get('oodle', ''), writer=sys.executable), saved


def path(value):
    return str(Path(value).expanduser().resolve()) if value else ''


def run_job(request):
    """Run one request through bridge_runtime.py, as the UI does. Its log goes to stderr; returns the 'done' event."""
    with tempfile.TemporaryDirectory(prefix='SekiroBridgeCLI-') as temp:
        file = Path(temp) / 'request.json'
        file.write_text(json.dumps(request), encoding='utf-8')
        last, notices = {}, []
        with subprocess.Popen([sys.executable, '-E', '-X', 'utf8', str(HERE / 'bridge_runtime.py'), '--request', str(file)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
            for line in process.stdout:
                line = line.rstrip()
                if line.startswith(EVENT_PREFIX):
                    last = json.loads(line[len(EVENT_PREFIX):])
                    line = f"[{last.get('stage', '')} {last.get('progress', 0)}%] {last.get('message', '')}"
                elif line.startswith('NOTICE: '):
                    notices.append(line[len('NOTICE: '):])
                print(line, file=sys.stderr, flush=True)
            code = process.wait()
    if code or last.get('stage') != 'done':
        raise Failure(last.get('message') if last.get('stage') == 'error' else
                      f'The conversion stopped with exit code {code}; its log is on stderr.')
    return dict(output=last.get('output', ''), report=last.get('report') or {}, notices=list(dict.fromkeys(notices)))


def catalog_at(value):
    """A scanned catalog by its path in the bridge's cache: (path, catalog)."""
    file = Path(value).expanduser().resolve()
    if file.parent != (CACHE / 'catalogs').resolve() or not file.is_file():
        raise Failure(f'No catalog of the bridge at {file}. Scan the source first: bridge_cli scan <folder>.')
    from asset_discovery import load_catalog
    stored = json.loads(file.read_text(encoding='utf-8'))
    return file, load_catalog(file, stored['folder'])


def characters(catalog):
    return [dict(id=c['id'], character=c.get('character', c['id']), name=c.get('name', c['id']), game=c.get('game') or catalog.get('game', ''),
                 inventoried=bool(c.get('inventoried')), clips=c.get('count'), ready=c.get('ready'),
                 archives=c.get('archiveCount', len(c.get('archives', []))), errors=c.get('errors', []))
            for c in catalog.get('characters', [])]


def character(catalog, wanted):
    """One character of a catalog, by its ID or by its character ID such as c5060."""
    rows = catalog.get('characters', [])
    found = [c for c in rows if c['id'] == wanted] or [c for c in rows if str(c.get('character', '')).lower() == wanted.lower()]
    if not found:
        listed = ', '.join(c['id'] for c in rows[:40]) + (' …' if len(rows) > 40 else '')
        raise Failure(f'No character {wanted} in this catalog. Its characters: {listed or "none"}.')
    if len(found) > 1:
        raise Failure(f'Several characters are {wanted}, from different folders or games: '
                      f'{", ".join(c["id"] for c in found)}. Choose one by its ID.')
    return found[0]


def read_character(file, catalog, wanted, settings):
    """The catalog with the character's clips, reading its archives first where the source lists them separately."""
    if not wanted:
        return catalog, None
    entry = character(catalog, wanted)
    if not entry.get('inventoried'):
        run_job(dict(settings, mode='inventory', assetFolder=catalog['folder'], assetCatalog=str(file), assetCharacter=entry['id']))
        file, catalog = catalog_at(file)
        entry = character(catalog, entry['id'])
    return catalog, entry


def own_clips(catalog, entry):
    return [c for c in catalog['clips'] if entry is None or c.get('characterKey') == entry['id']]


def clip_catalog(value, clip, wanted, settings):
    """(path, catalog, character, clip ID) of a clip given by its ID, or by its name with the character's clips."""
    file, catalog = catalog_at(value)
    catalog, entry = read_character(file, catalog, wanted, settings)
    clips = own_clips(catalog, entry)
    found = [c for c in clips if c['id'] == clip] or [c for c in clips if c['name'].lower() == clip.lower()]
    if not found:
        hint = '' if entry or catalog.get('layout', 'folder') == 'folder' else \
            ' A game folder lists a character\'s clips once it is read: pass --character.'
        raise Failure(f'No clip {clip} in this catalog.{hint} bridge_cli clips lists the clips.')
    if len(found) > 1:
        raise Failure(f'{len(found)} clips are named {clip}: {", ".join(c["id"] for c in found[:10])}. '
                      'Choose one by its ID, or pass --character.')
    return file, catalog, entry, found[0]['id']


def json_option(value, label):
    """A JSON value given inline or as the path of a JSON file."""
    if not value:
        return {}
    text = Path(value).read_text(encoding='utf-8-sig') if Path(value).is_file() else value
    try:
        return json.loads(text)
    except ValueError as exc:
        raise Failure(f'{label} is neither JSON nor a JSON file: {exc}') from None


def masks(values):
    """--mask MODEL=1,2 per model: the numbered mesh groups to keep; the model's unnumbered meshes always stay."""
    chosen = {}
    for value in values or []:
        model, separator, groups = value.rpartition('=')
        if not separator or not model:
            raise Failure(f'Give a mesh group choice as MODEL=1,2: {value}')
        chosen[path(model)] = [group.strip() for group in groups.split(',') if group.strip()]
    return chosen


def source_options(values):
    """--option ID=VALUE per source option that a game package declares, such as engineVersion=GAME_UE4_27.

    A value that names an existing file, such as a mappings file, is passed as its full path."""
    chosen = {}
    for value in values or []:
        key, separator, given = value.partition('=')
        if not separator or not key.strip():
            raise Failure(f'Give a source option as ID=VALUE, such as engineVersion=GAME_UE4_27: {value}')
        chosen[key.strip()] = path(given) if given and Path(given).expanduser().is_file() else given
    return chosen


def command_env(args, settings, saved):
    import bridge_ui
    bridge_ui.CONFIG.update(saved, **settings)
    checks = bridge_ui.environment()
    sources = [dict(id=s.get('id', ''), name=s.get('name', ''), path=s.get('path', ''), layout=s.get('layout', ''),
                    game=s.get('game', ''), catalog=s.get('catalog', '')) for s in saved.get('sources', [])]
    return dict(ready=all(c['ready'] for c in checks if not c.get('optional')), checks=checks, tools=settings,
                cache=str(CACHE), settings=str(bridge_ui.SETTINGS), sources=sources)


def command_games(args, settings, saved):
    from games import public
    return public()


def command_detect(args, settings, saved):
    from asset_discovery import detect_source
    return detect_source(args.folder, settings['oodle'], args.file_list, source_options(args.option))


def command_scan(args, settings, saved):
    folders = json_option(args.folders, '--folders')
    layout = 'custom' if folders and args.layout in ('auto', 'folder') else args.layout
    done = run_job(dict(settings, mode='discover', assetFolder=path(args.folder), game=args.game, sourceLayout=layout,
                        sourceFolders=folders, sourceRecursive=not args.no_recursive, sourceFileList=path(args.file_list),
                        sourceOptions=source_options(args.option)))
    file, catalog = catalog_at(done['output'])
    return dict(catalog=str(file), folder=catalog['folder'], layout=catalog.get('layout', 'folder'), game=catalog.get('game', ''),
                games=catalog.get('games', []), clips=len(catalog['clips']), characters=characters(catalog),
                warnings=catalog.get('warnings', []), notices=done['notices'])


def command_clips(args, settings, saved):
    file, catalog = catalog_at(args.catalog)
    catalog, entry = read_character(file, catalog, args.character, settings)
    clips = own_clips(catalog, entry)
    if args.match:
        clips = [c for c in clips if args.match.lower() in c['name'].lower() or args.match.lower() in c['id'].lower()]
    if args.ready:
        clips = [c for c in clips if c.get('ready')]
    keep = ('id', 'name', 'character', 'characterKey', 'game', 'ready', 'issues', 'archive', 'member')
    return dict(catalog=str(file), character=entry['id'] if entry else '', total=len(clips),
                clips=[{k: c.get(k) for k in keep} for c in clips[:args.limit]],
                characters=characters(catalog) if entry is None else [])


def command_select(args, settings, saved):
    file, catalog, entry, clip = clip_catalog(args.catalog, args.clip, args.character, settings)
    from asset_discovery import selection
    return dict(catalog=str(file), clip=clip, selection=selection(dict(catalog, clips=own_clips(catalog, entry)), clip, args.preset))


def command_masks(args, settings, saved):
    from character_assets import model_masks
    from dcx_codec import configure_oodle
    configure_oodle(settings['oodle'])
    return dict(model=path(args.model), groups=model_masks(args.model))


def clip_request(file, catalog, entry, clip, preset, models, rig_only, file_list):
    """The input options of a clip from a catalog, as the UI sends them."""
    return dict(inputMethod='folder', game='auto', assetFolder=catalog['folder'], assetCatalog=str(file), assetClip=clip,
                assetCharacter=entry['id'] if entry else '', sourceLayout=catalog.get('layout', 'folder'),
                sourceFileList=path(file_list), preset=preset, models=[path(m) for m in models or []], includeCharacter=not rig_only)


def command_import(args, settings, saved):
    request = dict(settings, mode='import', **clip_request(*clip_catalog(args.catalog, args.clip, args.character, settings),
                                                         args.preset, args.models, args.rig_only, args.file_list),
                   modelMasks=masks(args.mask), partAnimations=not args.no_part_animations,
                   weaponAttachments=json_option(args.weapon_attachments, '--weapon-attachments'),
                   outputBlend=path(args.output), force=args.force)
    if args.game != 'auto':
        request['game'] = args.game
    if args.donor_clip:
        found = clip_catalog(args.donor_catalog or args.catalog, args.donor_clip, args.donor_character, settings)
        request['donor'] = clip_request(*found, args.donor_preset, args.donor_models, args.donor_rig_only, args.donor_file_list)
    elif any((args.donor_catalog, args.donor_character, args.donor_models, args.donor_rig_only)):
        raise Failure('The --donor options describe a retarget donor: name its clip with --donor-clip.')
    done = run_job(request)
    return dict(scene=done['output'], report=done['report'], notices=done['notices'])


def command_inspect(args, settings, saved):
    done = run_job(dict(settings, mode='inspect', inputBlend=path(args.scene)))
    return dict(blend=done['output'], scene=done['report'].get('scene'), notices=done['notices'])


def command_verify(args, settings, saved):
    done = run_job(dict(settings, mode='verify', inputBlend=path(args.scene), render=path(args.render), frames=args.frames,
                        force=args.force))
    return {'blend': done['output'], **done['report'], 'notices': done['notices']}


def command_export(args, settings, saved):
    request = dict(settings, mode='export', inputBlend=path(args.scene), outputHKX=path(args.output), game=args.game,
                   exportGame=args.game, format=args.format, exportAction=args.action or '', frameRange=args.frame_range,
                   trackSet=args.tracks, rootMotion=args.root_motion, rootBone=args.root_bone or '', rootVertical=args.root_vertical,
                   rootYaw=args.root_yaw, quantization=args.quantization, tolerance=args.tolerance, verify=not args.no_verify,
                   exportParts=args.parts, addToBinder=bool(args.binder), binder=path(args.binder), binderMember=args.binder_member or '',
                   force=args.force)
    for key, value in (('frameStart', args.frame_start), ('frameEnd', args.frame_end), ('frameRate', args.frame_rate)):
        if value is not None:
            request[key] = value
    done = run_job(request)
    return dict(hkx=done['output'], report=done['report'], notices=done['notices'])


def command_run(args, settings, saved):
    request = json_option(args.request, 'The request')
    if not isinstance(request, dict) or not request.get('mode'):
        raise Failure('A request is a JSON object with a mode: import, export, inspect, verify, discover or inventory.')
    for key, value in settings.items():
        if not request.get(key):
            request[key] = value
    return run_job(request)


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--blender', default='', help='blender.exe; the one saved in the UI by default')
    common.add_argument('--decoder', default='', help='SekiroMotionDecoder.exe; the one saved in the UI by default')
    common.add_argument('--oodle', default='', help="the game's oo2core_6_win64.dll, for KRAK archives")
    main = argparse.ArgumentParser(prog='bridge_cli', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = main.add_subparsers(dest='command', required=True, metavar='command')

    def command(name, help):
        return commands.add_parser(name, parents=[common], help=help, description=help)

    command('env', 'the tools the bridge uses, whether they are ready, and the sources saved in the UI')
    command('games', 'the games of the registry and the installed game packages')
    detect = command('detect', 'what a folder is as a source: its layout, game and file counts')
    detect.add_argument('folder')
    detect.add_argument('--file-list', default='', help="the game's file list, for packed games that need one")
    option_help = ("a source option that the game's package declares, such as engineVersion=GAME_UE4_27 or aesKey=0x...; "
                   'repeat for more. detect lists them in optionFields')
    detect.add_argument('--option', action='append', default=[], metavar='ID=VALUE', help=option_help)
    scan = command('scan', 'index a source into a catalog and list its characters')
    scan.add_argument('folder')
    scan.add_argument('--layout', choices=('auto', 'folder', 'game', 'custom'), default='auto',
                      help="auto detects a game's own folders or a collected folder")
    scan.add_argument('--game', default='auto', help='a game ID of the registry (bridge_cli games); auto detects it')
    scan.add_argument('--folders', default='', help='a custom layout as JSON or a JSON file: {"animations": ["anims"], ...}')
    scan.add_argument('--no-recursive', action='store_true', help="a custom layout's folders without their subfolders")
    scan.add_argument('--file-list', default='')
    scan.add_argument('--option', action='append', default=[], metavar='ID=VALUE', help=option_help)
    clips = command('clips', "the clips of a catalog; --character reads that character's archives first")
    clips.add_argument('catalog', help='the catalog path that scan printed')
    clips.add_argument('--character', default='', help='a character ID from scan, such as c5060')
    clips.add_argument('--match', default='', help='only clips whose name or ID contains this text')
    clips.add_argument('--ready', action='store_true', help='only clips that can be imported')
    clips.add_argument('--limit', type=int, default=200, help='at most this many clips (default 200); total counts all')
    select = command('select', 'what an import of the clip uses: its files, model parts and material library')
    select.add_argument('catalog')
    select.add_argument('clip', help='a clip ID, or a clip name with --character')
    select.add_argument('--character', default='')
    select.add_argument('--preset', choices=('auto', 'npc', 'player', 'wolf', 'tutorial', 'mortal'), default='auto')
    model = command('masks', 'the numbered mesh groups of a model binder or FLVER')
    model.add_argument('model', help='a .chrbnd.dcx, .partsbnd.dcx or .flver file')
    scene = command('import', 'create a Blender scene from a clip of a catalog')
    scene.add_argument('catalog')
    scene.add_argument('clip')
    scene.add_argument('--output', required=True, help='the .blend to write')
    scene.add_argument('--character', default='')
    scene.add_argument('--game', default='auto')
    scene.add_argument('--preset', choices=('auto', 'npc', 'player', 'wolf', 'tutorial', 'mortal'), default='auto')
    scene.add_argument('--models', nargs='+', default=[], help="model files instead of the selection's chosen parts")
    scene.add_argument('--mask', action='append', default=[], help='MODEL=1,2: keep these numbered mesh groups of a model')
    scene.add_argument('--rig-only', action='store_true', help='the rig without models')
    scene.add_argument('--no-part-animations', action='store_true', help="leave Sekiro's weapon part clips out")
    scene.add_argument('--weapon-attachments', default='', help='weapon placements as JSON or a JSON file, as the CLI takes them')
    scene.add_argument('--file-list', default='')
    scene.add_argument('--donor-clip', default='', help='a second clip for the retarget add-on, placed beside the target')
    scene.add_argument('--donor-catalog', default='', help="the donor's catalog; the target's by default")
    scene.add_argument('--donor-character', default='')
    scene.add_argument('--donor-preset', choices=('auto', 'npc', 'player', 'wolf', 'tutorial', 'mortal'), default='auto')
    scene.add_argument('--donor-models', nargs='+', default=[])
    scene.add_argument('--donor-rig-only', action='store_true')
    scene.add_argument('--donor-file-list', default='')
    scene.add_argument('--force', action='store_true', help='replace an existing output')
    inspect = command('inspect', "the scene's rig, actions and frame ranges")
    inspect.add_argument('scene')
    verify = command('verify', 'numbers to check an import by, with pass or fail checks; the scene is not saved')
    verify.add_argument('scene')
    verify.add_argument('--render', default='', help='also draw it into this PNG from the front, and beside it from the side')
    verify.add_argument('--frames', type=int, default=3, help='frames of the scene range to measure (default 3)')
    verify.add_argument('--force', action='store_true', help='replace existing pictures')
    export = command('export', 'write the edited animation as HKX')
    export.add_argument('scene')
    export.add_argument('--output', required=True, help='the .hkx to write; a .motion.json sidecar goes beside it')
    export.add_argument('--game', default='auto', help="the scene's own game by default")
    export.add_argument('--format', choices=('interleaved', 'spline'), default='interleaved')
    export.add_argument('--action', default='', help='the action to export; the active one by default')
    export.add_argument('--frame-range', choices=('scene', 'action', 'clip', 'custom'), default='scene')
    export.add_argument('--frame-start', type=float)
    export.add_argument('--frame-end', type=float)
    export.add_argument('--frame-rate', type=float)
    export.add_argument('--tracks', choices=('original', 'keyed', 'all'), default='original')
    export.add_argument('--root-motion', choices=('auto', 'object', 'bone', 'none'), default='auto')
    export.add_argument('--root-bone', default='')
    export.add_argument('--root-vertical', action='store_true')
    export.add_argument('--root-yaw', action='store_true')
    export.add_argument('--quantization', choices=('threecomp40', 'threecomp48', 'uncompressed'), default='threecomp40')
    export.add_argument('--tolerance', type=float, default=0.001)
    export.add_argument('--no-verify', action='store_true', help='skip reading the HKX back')
    export.add_argument('--parts', action='store_true', help="also write the weapon parts' clips")
    export.add_argument('--binder', default='', help='also add the HKX to this .anibnd.dcx; a copy beside the HKX for a game file')
    export.add_argument('--binder-member', default='', help="the member name in the binder; the clip's own by default")
    export.add_argument('--force', action='store_true')
    run = command('run', 'any request as the UI and sekiro_animation_cli.ps1 send it to bridge_runtime.py')
    run.add_argument('request', help='the request as JSON or a JSON file')
    return main


COMMANDS = dict(env=command_env, games=command_games, detect=command_detect, scan=command_scan, clips=command_clips,
                select=command_select, masks=command_masks, inspect=command_inspect, verify=command_verify,
                export=command_export, run=command_run, **{'import': command_import})


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        # The decoders are .NET programs; they run on the bridge's shared runtime when there is one.
        from dotnet_runtime import configure
        configure()
        settings, saved = tools(args)
        result, code = {'ok': True, **COMMANDS[args.command](args, settings, saved)}, 0
    except (Failure, ValueError) as exc:
        result, code = dict(ok=False, error=str(exc)), 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        result, code = dict(ok=False, error=f'{type(exc).__name__}: {exc}'), 1
    print(json.dumps(result, indent=1, default=str), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
