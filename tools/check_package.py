"""Check a game package with the bridge, from its package.json to a scene in Blender.

python tools/check_package.py <package folder> [--source <game folder>] [--file-list <list>] [--option <id>=<value> ...]
                              [--character <id>] [--clip <id>] [--models] [--blender <blender.exe> --output <scene.blend>]

Without --source it checks package.json, the module and the tools. With a source it also detects and scans it,
reads one character's clips, decodes one clip for the preview and imports it as the bridge does; --models also
prepares the character's models. With --blender the import ends in a Blender scene. The scan goes into the bridge's
cache, where the UI finds it too.

Every step prints PASS or FAIL with the reason. The exit code is 1 when a step failed.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone'))


class Steps:
    def __init__(self, verbose):
        self.verbose, self.failed = verbose, 0

    def run(self, name, function, *args):
        """Run one step; it returns (result, detail). A failed step prints why and returns None."""
        start = time.time()
        try:
            result, detail = function(*args)
        except Exception as exc:
            self.failed += 1
            print(f'FAIL  {name}: {exc}', flush=True)
            if self.verbose:
                traceback.print_exc()
            return None
        print(f'PASS  {name} ({time.time() - start:.1f} s)' + (f': {detail}' if detail else ''), flush=True)
        return result


def notify(stage, message, progress=None, **extra):
    print(f'      {message}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('package', type=Path, help='the package folder, with package.json')
    parser.add_argument('--source', type=Path, help='a game folder or unpacked files of one of its games')
    parser.add_argument('--file-list', default='', help="the game's file list, for games that need one")
    parser.add_argument('--option', action='append', default=[], metavar='ID=VALUE',
                        help="a source option the package declares, such as engineVersion=GAME_UE4_27; repeat for more")
    parser.add_argument('--character', default='', help='the character to read; the first one by default')
    parser.add_argument('--clip', default='', help='the clip ID or name to import; the first ready clip by default')
    parser.add_argument('--models', action='store_true', help="also prepare the character's models")
    parser.add_argument('--blender', type=Path, help='blender.exe, to import the clip into a scene')
    parser.add_argument('--output', type=Path, help='the .blend file that --blender writes')
    parser.add_argument('--verbose', action='store_true', help='print the traceback of a failed step')
    args = parser.parse_args()
    if args.blender and not args.output:
        parser.error('--blender needs --output, the scene to write.')
    if any('=' not in o for o in args.option):
        parser.error('--option takes ID=VALUE, such as engineVersion=GAME_UE4_27.')
    options = dict(o.split('=', 1) for o in args.option)
    folder = args.package.resolve()
    steps = Steps(args.verbose)

    import games
    from dotnet_runtime import configure
    from games import packages
    configure()
    # Only the checked folder's packages load, so an installed copy cannot stand in for it.
    packages.ROOTS = [folder.parent]
    games.reload()

    def load():
        package = next((p for p in games.PACKAGES if p.folder.resolve() == folder), None)
        if package is None:
            raise ValueError(f'No package.json in {folder}.')
        if package.error:
            raise ValueError(package.error)
        if package.duplicate:
            raise ValueError(f'Another folder has the package ID {package.id!r}: {package.duplicate}')
        return package, f'{package.name} {package.version}, games ' + ', '.join(p.id for p in package.profiles)

    package = steps.run('package.json', load)
    if package is None:
        return 1

    def module():
        from games import api
        loaded = package.module()
        optional = [name for name in api.OPTIONAL if callable(getattr(loaded, name, None))]
        return loaded, 'optional functions: ' + (', '.join(optional) or 'none')

    if steps.run('module', module) is None:
        return 1
    for tool in package.tools:
        def check(tool=tool):
            ready, detail = package.tool_status(tool)
            if not ready:
                raise ValueError(detail)
            return None, detail
        steps.run(f'tool {tool["id"]}', check)
    if not args.source:
        return 1 if steps.failed else 0

    engine = games.adapter(package.id)
    cache = packages.CACHE

    def detect():
        found = engine.detect(args.source, args.file_list, options)
        if not found:
            raise ValueError(f'{package.name} does not recognise {args.source}.')
        if found['needsFileList'] and not args.file_list:
            raise ValueError((found.get('note') or 'This source needs a file list.') + ' Pass it with --file-list.')
        unknown = set(options) - {o['id'] for o in package.source_options}
        if unknown:
            raise ValueError(f'{package.name} declares no source option {", ".join(sorted(unknown))}.')
        missing = [o['id'] for o in found['optionFields'] if o['id'] in found['needs'] and not options.get(o['id'])]
        if missing:
            raise ValueError((found.get('note') or 'This source needs more options.') +
                             f' Pass {", ".join(missing)} with --option.')
        return found, f"{found['game']}, {found.get('evidence', '')}, counts {json.dumps(found.get('counts', {}))}"

    found = steps.run('detect', detect)
    if found is None:
        return 1
    def scan():
        result = engine.discover(args.source, cache, notify, found, 'auto', args.file_list, options)
        return result, f"{len(result[1]['characters'])} characters"

    scanned = steps.run('scan', scan)
    if scanned is None:
        return 1
    catalog_path, catalog = scanned
    character = args.character or (catalog['characters'][0]['id'] if catalog['characters'] else '')

    def inventory():
        result = engine.inventory_character(catalog_path, catalog, character, cache, notify)
        entry = next(c for c in result['characters'] if c['id'] == character)
        return result, f"{character}: {entry.get('count', 0)} clips, {entry.get('ready', 0)} ready"

    catalog = steps.run('inventory', inventory)
    if catalog is None:
        return 1
    clips = [c for c in catalog['clips'] if c['characterKey'] == character]
    clip = next((c['id'] for c in clips if args.clip in (c['id'], c['name'])), args.clip) if args.clip else \
        next((c['id'] for c in clips if c['ready']), '')

    def choose():
        if not clip:
            raise ValueError(f'{character} has no ready clip. Choose one with --clip.')
        chosen = engine.selection(engine.load_catalog(catalog, args.source, True), clip)
        return chosen, f"{clip} of {chosen['character']}"

    chosen = steps.run('selection', choose)
    if chosen is None:
        return 1

    def preview():
        from clip_preview import preview_selection
        from games.interchange import check_preview
        # The selection as the page sends it for the preview.
        sent = json.loads(json.dumps(preview_selection(chosen, chosen), default=str))
        document = check_preview(json.loads(gzip.decompress(engine.preview(sent, cache / 'previews'))))
        return None, f"{len(document['bones'])} bones, {document['frameCount']} frames at {document['frameRate']:g} fps"

    steps.run('preview', preview)
    request = dict(assetClip=clip, assetCharacter=character, game='auto', includeCharacter=args.models,
                   assetFolder=str(args.source), sourceFileList=args.file_list, sourceOptions=options)
    if args.blender:
        import bridge_runtime

        def scene():
            request.update(mode='import', inputMethod='folder', sourceLayout='game', assetCatalog=str(catalog_path),
                           blender=str(args.blender), outputBlend=str(args.output.resolve()), force=True)
            return None, str(bridge_runtime.convert(request))

        steps.run('Blender import', scene)
    else:
        def prepare():
            with tempfile.TemporaryDirectory(prefix='SekiroBridge-check-') as temp:
                motion, character_args, report = engine.prepare(dict(request), catalog_path, catalog, temp, notify)
                warnings = report.get('warnings') or []
                return None, (f"{report.get('frames', '?')} frames, {report.get('tracks', '?')} tracks, "
                              f"{len(character_args) // 2} character manifest(s), {len(warnings)} warning(s)")

        steps.run('prepare', prepare)
    return 1 if steps.failed else 0


if __name__ == '__main__':
    sys.exit(main())
