"""The game registry, game packages and their API, with the example package and made-up files."""
import contextlib
import gzip
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import games
from games import api, packages
from games.space import FROMSOFT, RE_ENGINE
from test_interchange import owned_motion

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'packages'
TOOLS = Path(__file__).resolve().parents[2] / 'tools'
ENGINE_FUNCTIONS = ('detect', 'discover', 'inventory_character', 'refresh_clip', 'load_catalog', 'selection', 'preview', 'prepare')


class PackageCase(unittest.TestCase):
    """Runs with the example package as the only package, from a copy in a temporary bridge folder."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.bridge, self.user = self.temp / 'bridge-packages', self.temp / 'user-packages'
        shutil.copytree(FIXTURES / 'example', self.bridge / 'example')
        self.user.mkdir()
        self.cache = self.temp / 'cache'
        for name, value in (('ROOTS', [self.bridge, self.user]), ('CACHE', self.cache)):
            patcher = mock.patch.object(packages, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(games.reload)
        games.reload()
        self.notes = []

    def notify(self, stage, message, progress=None, **extra):
        self.notes.append(message)

    def source(self):
        """A made-up example game: two clips of one character."""
        root = self.temp / 'Example Game'
        (root / 'motions' / 'hero').mkdir(parents=True)
        (root / 'example.game').write_text('', encoding='utf-8')
        for name in ('idle', 'walk'):
            (root / 'motions' / 'hero' / f'{name}.json').write_text(json.dumps(dict(owned_motion(2), clip=name)), encoding='utf-8')
        return root

    def write_package(self, root, manifest, code=None):
        folder = root / manifest['id']
        folder.mkdir(parents=True)
        (folder / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
        (folder / '__init__.py').write_text(code if code is not None else (FIXTURES / 'example' / '__init__.py').read_text(encoding='utf-8'),
                                            encoding='utf-8')
        return folder

    def zip_of(self, folder, name, top=True, extra=()):
        """A package ZIP of folder, with the folder as its top entry or without it."""
        path = self.temp / name
        with zipfile.ZipFile(path, 'w') as archive:
            for file in sorted(folder.rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts:
                    archive.write(file, (f'{folder.name}/' if top else '') + file.relative_to(folder).as_posix())
            for entry, data in extra:
                archive.writestr(entry, data)
        return path

    def manifest(self, **changes):
        return dict(json.loads((FIXTURES / 'example' / 'package.json').read_text(encoding='utf-8')), **changes)


class Registry(PackageCase):
    def test_built_in_and_package_games_have_unique_ids(self):
        ids = [profile.id for profile in games.PROFILES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(games.games('fromsoft')[0].id, 'sekiro')
        for profile in games.PROFILES:
            self.assertIn(profile.engine, games.ENGINES, profile.id)
            self.assertTrue(profile.name and profile.short and profile.hint, profile.id)

    def test_only_fromsoft_games_export(self):
        for profile in games.PROFILES:
            self.assertEqual(profile.capabilities.export, profile.engine == 'fromsoft', profile.id)
        self.assertEqual(games.profile('example').space(), RE_ENGINE)
        self.assertEqual(games.profile('sekiro').space(), FROMSOFT)
        self.assertFalse(games.profile('example').capabilities.import_character)

    def test_public_registry_is_json_with_packages_and_bone_names(self):
        registry = json.loads(json.dumps(games.public()))
        self.assertEqual({g['id'] for g in registry['games']}, set(games.BY_ID))
        self.assertEqual(registry['engines'], ['fromsoft', 'example'])
        [package] = registry['packages']
        self.assertEqual((package['id'], package['version'], package['installed'], package['error']), ('example', '1.0.0', False, ''))
        example = next(g for g in registry['games'] if g['id'] == 'example')
        self.assertEqual((example['package'], example['bones']['names']['Becken']), ('example', 'Pelvis'))

    def test_every_engine_has_the_bridge_entry_points(self):
        for engine in games.ENGINES:
            if engine == games.DEFAULT_ENGINE:
                continue  # The FromSoftware code is called directly; games.fromsoft names only what it shares.
            adapter = games.adapter(engine)
            for name in ENGINE_FUNCTIONS:
                self.assertTrue(callable(getattr(adapter, name, None)), f'{engine}.{name}')

    def test_foreign_dispatch(self):
        self.assertIsNone(games.foreign(dict(engine='fromsoft')))
        self.assertIsNone(games.foreign(dict(game='sekiro')))
        self.assertIsNone(games.foreign({}))
        engine = games.adapter('example')
        self.assertIsInstance(engine, packages.PackageEngine)
        self.assertIs(games.foreign(dict(engine='example')), engine)
        self.assertIs(games.foreign(dict(game='example')), engine)
        self.assertIs(games.foreign(dict(source=dict(engine='example'))), engine)
        with self.assertRaisesRegex(ValueError, 'not installed'):
            games.foreign(dict(engine='re_engine_v9'))


class Loading(PackageCase):
    def reasons(self):
        return {(p.folder.parent.name, p.folder.name): (p.error, p.duplicate) for p in games.reload()}

    def test_broken_packages_are_listed_and_the_rest_works(self):
        broken = self.user / 'broken'
        broken.mkdir()
        (broken / 'package.json').write_text('{"id": "broken"', encoding='utf-8')
        self.write_package(self.user, self.manifest(id='future', apiVersion=2, games=[dict(self.manifest()['games'][0], id='future')]))
        self.write_package(self.user, self.manifest(id='clash', games=[dict(self.manifest()['games'][0], id='sekiro')]))
        reasons = self.reasons()
        self.assertIn('not valid JSON', reasons['user-packages', 'broken'][0])
        self.assertIn('needs package API version 2', reasons['user-packages', 'future'][0])
        self.assertIn('already registered', reasons['user-packages', 'clash'][0])
        self.assertEqual(reasons['bridge-packages', 'example'], ('', ''))
        self.assertIn('example', games.BY_ID)

    def test_the_bridge_folder_wins_over_an_installed_copy(self):
        self.write_package(self.user, self.manifest(version='0.9.0'))
        reasons = self.reasons()
        self.assertEqual(reasons['bridge-packages', 'example'], ('', ''))
        self.assertEqual(reasons['user-packages', 'example'], ('', str(self.bridge / 'example')))
        installed = next(p for p in games.PACKAGES if p.installed)
        self.assertEqual((installed.version, installed.duplicate), ('0.9.0', str(self.bridge / 'example')))
        self.assertEqual(games.adapter('example').package.version, '1.0.0')

    def test_a_package_without_the_api_functions_is_refused_when_used(self):
        self.write_package(self.user, self.manifest(id='empty', games=[dict(self.manifest()['games'][0], id='empty')]), code='')
        games.reload()
        with self.assertRaisesRegex(ValueError, 'lacks the package API functions detect, scan'):
            games.adapter('empty').module
        # Detection skips it and notes why, so other engines still detect their folders.
        self.assertIsNone(games.detect(self.temp))
        self.assertTrue(any('lacks' in note for note in games.adapter('empty').package.problems))

    def test_package_data_is_checked(self):
        for changes, message in ((dict(id='Bad-Id'), 'the id must be'), (dict(id='fromsoft'), 'the id must be'),
                                 (dict(tools=[dict(id='t', name='T', path='../t.exe')]), 'must stay inside the package'),
                                 (dict(bones=dict(patterns=[dict(match='(', **{'as': 'x'})])), 'not a valid regular expression'),
                                 (dict(games=[dict(self.manifest()['games'][0], capabilities=dict(export=True))]), 'is not valid')):
            with self.assertRaisesRegex(ValueError, message):
                packages.check_package_data(self.manifest(**changes))


class Engine(PackageCase):
    def test_scan_inventory_selection_preview_and_prepare(self):
        from asset_discovery import detect_source, discover, inventory_character, load_catalog, selection
        root = self.source()
        found = detect_source(str(root))
        self.assertEqual((found['engine'], found['game'], found['layout'], found['needsFileList']), ('example', 'example', 'game', False))
        self.assertEqual(found['counts'], dict(animations=2, characters=1, materials=0))

        path, catalog = discover(root, self.cache, self.notify, '', 'auto', 'game', None, True, '')
        self.assertEqual((catalog['engine'], catalog['package'], catalog['layout'], catalog['archiveCount']), ('example', 'example', 'game', 2))
        self.assertEqual(Path(path).parent, self.cache / 'catalogs')
        self.assertIn('Listing the characters', self.notes)

        catalog = inventory_character(path, 'hero', self.cache, self.notify)
        self.assertEqual([c['name'] for c in catalog['clips']], ['idle', 'walk'])
        self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8'))['clips'][0]['scope'], str(root))
        catalog = load_catalog(path, root, True)
        chosen = selection(catalog, 'hero/idle')
        self.assertEqual((chosen['engine'], chosen['game'], chosen['layout'], chosen['skeleton']), ('example', 'example', 'game', ''))

        from clip_preview import preview
        data = preview(chosen, '', self.temp / 'previews')
        document = json.loads(gzip.decompress(data))
        self.assertEqual((document['clip'], document['basis']), ('idle', [list(row) for row in RE_ENGINE.basis]))
        self.assertEqual(preview(chosen, '', self.temp / 'previews', stored_only=True), data)

        request = dict(assetClip='hero/walk', game='auto')
        motion, character_args, report = games.adapter('example').prepare(request, path, catalog, self.temp, self.notify)
        self.assertEqual((json.loads(motion.read_text(encoding='utf-8'))['source']['engine'], character_args), ('example', []))
        self.assertEqual((request['game'], report['game'], report['clip'], report['parts']), ('example', 'Example Game', 'walk', 0))

    def test_package_results_are_checked(self):
        engine = games.adapter('example')
        with mock.patch.object(engine.module, 'scan', return_value=dict(schema=1, game='example', folder='x', characters=[],
                                                                       clips=[dict(id='a', name='a', character='c', characterKey='c',
                                                                                   game='example', ready=True)])):
            with self.assertRaisesRegex(ValueError, 'Example engine: the scan is not valid: .*issues'):
                engine.discover(self.temp, self.cache, self.notify, dict(game='example', root=str(self.temp)))
        with mock.patch.object(engine.module, 'detect', return_value=dict(game='other', root=str(self.temp))):
            with self.assertRaisesRegex(ValueError, 'does not declare'):
                engine.detect(self.temp)

    def test_a_stored_scan_of_another_folder_is_refused(self):
        root = self.source()
        from asset_discovery import discover, load_catalog
        path, catalog = discover(root, self.cache, self.notify, '', 'auto', 'game', None, True, '')
        with self.assertRaisesRegex(ValueError, 'another folder'):
            load_catalog(path, self.temp / 'elsewhere', False)


class Tools(PackageCase):
    def setUp(self):
        super().setUp()
        tool = dict(id='decoder', name='Example decoder', path='tools/decoder.exe', version=['--version'], expect='Example 1',
                    build='decoder/build.cmd')
        folder = self.write_package(self.user, self.manifest(id='tooled', games=[dict(self.manifest()['games'][0], id='tooled')],
                                                             tools=[tool]))
        (folder / 'decoder').mkdir()
        (folder / 'decoder' / 'build.cmd').write_text('', encoding='utf-8')
        games.reload()
        self.package = games.adapter('tooled').package
        self.ctx = api.Context(self.package, self.temp / 'tool-cache')

    def test_a_missing_tool_names_its_build_script(self):
        with self.assertRaisesRegex(ValueError, r'Example decoder is missing: .*Build it with .*build\.cmd'):
            self.ctx.run('decoder', 'list')
        ready, detail = self.package.tool_status(self.package.tool('decoder'))
        self.assertFalse(ready)
        self.assertIn('build.cmd', detail)

    def test_run_returns_output_and_reports_the_last_error_line(self):
        (self.package.folder / 'tools').mkdir()
        (self.package.folder / 'tools' / 'decoder.exe').write_bytes(b'')
        done = mock.Mock(returncode=0, stdout='listed\n', stderr='')
        with mock.patch('subprocess.run', return_value=done) as run:
            self.assertEqual(self.ctx.run('decoder', 'list', Path('a b.txt')), 'listed\n')
        command, environment = run.call_args[0][0], run.call_args[1]['env']
        self.assertEqual(command[1:], ['list', 'a b.txt'])
        self.assertIsInstance(environment, dict)
        failed = mock.Mock(returncode=2, stdout='step 1\n', stderr='Unknown motlist version 99\n')
        with mock.patch('subprocess.run', return_value=failed):
            with self.assertRaisesRegex(ValueError, 'Example decoder list failed: Unknown motlist version 99'):
                self.ctx.run('decoder', 'list')
        with mock.patch('subprocess.run', return_value=mock.Mock(returncode=0, stdout='Example 1.2\n', stderr='')):
            self.assertEqual(self.package.tool_status(self.package.tool('decoder')), (True, 'Example 1.2'))


class Installing(PackageCase):
    def test_install_replace_and_remove(self):
        source = self.write_package(self.temp / 'build', self.manifest(id='other', version='2.0.0',
                                                                         games=[dict(self.manifest()['games'][0], id='other')]))
        package_zip = self.zip_of(source, 'other.zip')
        info = packages.inspect_zip(package_zip)
        self.assertEqual((info['id'], info['version'], info['replaces'], info['games']), ('other', '2.0.0', '', ['Example Game']))
        packages.install_zip(package_zip)
        games.reload()
        self.assertTrue(games.adapter('other').package.installed)
        self.assertIn('other', games.BY_ID)

        (source / 'package.json').write_text(json.dumps(self.manifest(id='other', version='2.1.0',
                                                                      games=[dict(self.manifest()['games'][0], id='other')])), encoding='utf-8')
        update = self.zip_of(source, 'other-2.1.zip', top=False)
        self.assertEqual(packages.inspect_zip(update)['replaces'], '2.0.0')
        packages.install_zip(update)
        self.assertEqual(sorted(p.name for p in self.user.iterdir()), ['other'])
        self.assertEqual(json.loads((self.user / 'other' / 'package.json').read_text(encoding='utf-8'))['version'], '2.1.0')

        with self.assertRaisesRegex(ValueError, 'No installed package'):
            packages.remove('example')
        packages.remove('other')
        games.reload()
        self.assertNotIn('other', games.BY_ID)
        self.assertFalse((self.user / 'other').exists())

    def test_unsafe_or_incomplete_zips_are_refused(self):
        source = self.write_package(self.temp / 'build', self.manifest(id='other', games=[dict(self.manifest()['games'][0], id='other')]))
        for name, extra, message in (('escape.zip', [('../evil.py', 'x')], 'unsafe path'),
                                     ('two.zip', [('second/package.json', '{}')], 'one package.json')):
            with self.assertRaisesRegex(ValueError, message):
                packages.inspect_zip(self.zip_of(source, name, extra=extra))
        with self.assertRaisesRegex(ValueError, 'Choose a game package ZIP'):
            packages.inspect_zip(source / 'package.json')
        self.assertEqual(list(self.user.iterdir()), [])

    def test_a_package_in_the_bridge_folder_is_named_when_it_hides_an_install(self):
        info = packages.inspect_zip(self.zip_of(FIXTURES / 'example', 'example.zip'))
        self.assertEqual(info['shadowedBy'], str(self.bridge / 'example'))


class GameChecks(PackageCase):
    def test_requests_name_registered_games(self):
        from bridge_runtime import check_games
        check_games(dict(mode='import', game='example'))
        check_games(dict(mode='export', exportGame='sekiro'))
        with self.assertRaisesRegex(ValueError, 'Unknown game'):
            check_games(dict(mode='import', game='dmc6'))
        with self.assertRaisesRegex(ValueError, 'Unknown donor game'):
            check_games(dict(mode='import', donor=dict(game='dmc6')))
        with self.assertRaisesRegex(ValueError, 'cannot write its animation format'):
            check_games(dict(mode='export', exportGame='example'))

    def test_sampled_clips_of_import_only_games_are_refused(self):
        from bridge_runtime import refuse_import_only
        refuse_import_only(dict(game='sekiro'))
        refuse_import_only(dict(game='er', formatVersion=1))
        for document in (dict(game='example'), dict(game='', source=dict(engine='example')), dict(game='sekiro', engine='example')):
            with self.assertRaisesRegex(ValueError, 'Retarget the animation'):
                refuse_import_only(document)

class Workspace(PackageCase):
    """The UI server's routes, on a free port with a fixed token."""

    def setUp(self):
        super().setUp()
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import bridge_ui
        self.started = []
        for name, value in (('SETTINGS', self.temp / 'ui-settings.json'), ('SOURCES', self.temp / 'ui-sources.json'),
                            ('CONFIG', {}), ('JOB', None), ('worker', lambda job, request: self.started.append(request)),
                            ('remember_location', lambda: None)):
            patcher = mock.patch.object(bridge_ui, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server = ThreadingHTTPServer(('127.0.0.1', 0), bridge_ui.Handler)
        server.token = 'token'
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
        self.addCleanup(self.connection.close)

    def call(self, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        self.connection.request('GET' if data is None else 'POST', path, body,
                                {'Content-Type': 'application/json', 'X-Bridge-Token': 'token'})
        response = self.connection.getresponse()
        return response.status, json.loads(response.read())

    def test_the_workspace_passes_the_file_list_to_its_jobs(self):
        request = dict(mode='discover', assetFolder=r'C:\Games\Devil May Cry 5', writer='python.exe', game='auto',
                       sourceFileList=r'C:\Lists\DMC5_STM_Release.list')
        self.assertEqual(self.call('/api/job', request)[0], 200)
        # A PAK source scans only with its file list, so the server must keep it in the job's request.
        self.assertEqual([r.get('sourceFileList') for r in self.started], [request['sourceFileList']])

    def test_packages_are_listed_inspected_installed_and_removed(self):
        status, state = self.call('/api/packages')
        self.assertEqual((status, state['folder']), (200, str(self.user)))
        self.assertEqual([(p['id'], p['installed']) for p in state['packages']], [('example', False)])
        source = self.write_package(self.temp / 'build', self.manifest(id='other', games=[dict(self.manifest()['games'][0], id='other')]))
        package_zip = str(self.zip_of(source, 'other.zip'))
        status, info = self.call('/api/packages/inspect', dict(zip=package_zip))
        self.assertEqual((status, info['id'], info['games']), (200, 'other', ['Example Game']))
        # Nothing is installed until the user confirms the warning.
        status, error = self.call('/api/packages/install', dict(zip=package_zip))
        self.assertEqual(status, 400)
        self.assertIn('Confirm the warning', error['error'])
        self.assertEqual(list(self.user.iterdir()), [])
        status, state = self.call('/api/packages/install', dict(zip=package_zip, confirm=True))
        self.assertEqual((status, [(p['id'], p['installed']) for p in state['packages']]), (200, [('example', False), ('other', True)]))
        self.assertIn('other', [g['id'] for g in self.call('/api/games')[1]['games']])
        status, error = self.call('/api/packages/remove', dict(id='example', confirm=True))
        self.assertEqual(status, 400)
        self.assertIn('No installed package', error['error'])
        status, state = self.call('/api/packages/remove', dict(id='other', confirm=True))
        self.assertEqual((status, [p['id'] for p in state['packages']]), (200, ['example']))
        self.assertNotIn('other', games.BY_ID)


class Checker(PackageCase):
    """tools/check_package.py, which package authors run on their package and a source of its game."""

    def check(self, *arguments):
        sys.path.insert(0, str(TOOLS))
        self.addCleanup(sys.path.remove, str(TOOLS))
        import check_package
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['check_package.py', *map(str, arguments)]), \
                mock.patch('dotnet_runtime.configure'), contextlib.redirect_stdout(output):
            code = check_package.main()
        steps = [line.split()[1] for line in output.getvalue().splitlines() if line.startswith('PASS ')]
        failed = [line for line in output.getvalue().splitlines() if line.startswith('FAIL ')]
        return code, steps, failed

    def test_every_step_passes_for_the_example_package(self):
        code, steps, failed = self.check(self.bridge / 'example', '--source', self.source(), '--clip', 'walk')
        self.assertEqual((code, failed), (0, []))
        self.assertEqual(steps, ['package.json', 'module', 'detect', 'scan', 'inventory', 'selection', 'preview', 'prepare'])
        self.assertTrue(any(self.cache.glob('catalogs/example-*.json')))

    def test_a_package_without_the_api_stops_at_its_module(self):
        folder = self.write_package(self.temp / 'work', self.manifest(), code='')
        code, steps, failed = self.check(folder)
        self.assertEqual((code, steps), (1, ['package.json']))
        self.assertIn('lacks the package API functions', failed[0])


OPTIONED = '''"""A package that shows the source options it gets."""
from pathlib import Path

CATALOG_SCHEMA = 1


def detect(path, options, ctx):
    root = Path(path)
    if not (root / 'optioned.game').is_file():
        return None
    shown = ['engineVersion', 'key'] + (['fileList'] if options['engineVersion'] == 'old' else [])
    return dict(game='optioned', root=str(root), options=shown, needs=[] if options['key'] else ['key'], seen=options)


def scan(detection, options, ctx, previous=None):
    return dict(schema=CATALOG_SCHEMA, game='optioned', folder=detection['root'], characters=[], clips=[], seen=options)


def inventory(catalog, character, ctx):
    return catalog


def selection(catalog, clip_id, preset, ctx):
    raise ValueError('no clips')


def preview(selection, ctx):
    raise ValueError('no clips')


def prepare(request, catalog, temp, ctx):
    raise ValueError('no clips')
'''


class SourceOptions(PackageCase):
    """Options a package declares for its sources, such as an engine version or a key, from the dialog to the package."""

    OPTIONS = [dict(id='engineVersion', name='Engine version', kind='choice', default='auto',
                    choices=[dict(value='auto', label='Auto'), dict(value='old', label='Old')]),
               dict(id='key', name='Key', kind='secret', placeholder='0x…', help='The archive key.'), 'fileList']

    def setUp(self):
        super().setUp()
        game = dict(self.manifest()['games'][0], id='optioned', name='Optioned Game', short='OP', executables=[])
        self.write_package(self.user, self.manifest(id='optioned', name='Optioned engine', games=[game],
                                                    sourceOptions=self.OPTIONS), code=OPTIONED)
        games.reload()
        self.engine = games.adapter('optioned')
        self.root = self.temp / 'Optioned Game'
        self.root.mkdir()
        (self.root / 'optioned.game').write_text('', encoding='utf-8')

    def test_option_definitions_are_checked(self):
        text = dict(name='Name', kind='text')
        for options, message in (([dict(text, id='Key')], 'source option ids'), ([dict(text, id='key'), dict(text, id='key')], 'source option ids'),
                                 ([dict(text, id='fileList')], 'source option ids'),
                                 ([dict(id='mode', name='Mode', kind='choice', default='b', choices=[dict(value='a', label='A')])], 'unique choices'),
                                 ([dict(id='mode', name='Mode', kind='choice', choices=[])], 'unique choices')):
            with self.assertRaisesRegex(ValueError, message):
                packages.check_package_data(self.manifest(sourceOptions=options))
        with self.assertRaises(ValueError):
            packages.check_package_data(self.manifest(sourceOptions=[dict(text, id='size', kind='number')]))
        self.assertEqual(self.engine.package.error, '')

    def test_values_are_trimmed_and_unknown_choices_fall_back(self):
        self.assertEqual(self.engine.options(), dict(fileList='', engineVersion='auto', key=''))
        self.assertEqual(self.engine.options('list.txt', dict(engineVersion='bogus', key='  abc  ', other='x')),
                         dict(fileList='list.txt', engineVersion='auto', key='abc'))
        self.assertEqual(self.engine.options('', dict(engineVersion='old'))['engineVersion'], 'old')

    def test_detection_shows_the_fields_the_source_needs(self):
        found = games.detect(self.root)
        self.assertEqual((found['engine'], found['needs'], found['needsFileList']), ('optioned', ['key'], False))
        self.assertEqual([f['id'] for f in found['optionFields']], ['engineVersion', 'key'])
        key = found['optionFields'][1]
        self.assertEqual((key['kind'], key['placeholder'], key['help'], key['filter']), ('secret', '0x…', 'The archive key.', ''))
        self.assertEqual([c['value'] for c in found['optionFields'][0]['choices']], ['auto', 'old'])
        found = games.detect(self.root, 'list.txt', dict(key='k', engineVersion='old'))
        self.assertEqual((found['needs'], found['needsFileList'], found['seen']['fileList']), ([], True, 'list.txt'))

    def test_the_scan_gets_the_options_and_each_set_has_its_own_catalog(self):
        from asset_discovery import discover
        first, catalog = discover(self.root, self.cache, self.notify, '', 'auto', 'game', options=dict(key='one'))
        self.assertEqual(catalog['seen'], dict(fileList='', engineVersion='auto', key='one'))
        second, catalog = discover(self.root, self.cache, self.notify, '', 'auto', 'game', options=dict(key='two'))
        self.assertEqual(catalog['seen']['key'], 'two')
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
