"""The part view on owned synthetic data: a weapon part's clips with the player clips they play in, and its routes."""
import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_ui
import clip_preview
import part_animations as pa
from asset_discovery import CATALOG_SCHEMA
from test_part_animations import binder, tae

TOKEN = 'part-view-test'


def sekiro_folder(root):
    """A game folder with the umbrella's animated part, a resting katana, an outfit binder and the player's TAE."""
    (root / 'parts').mkdir(parents=True)
    (root / 'chr').mkdir()
    # The umbrella's own TAE gives a076_405033 the clip of a076_421020.
    animated = binder([('skeleton_1.hkx', b'SKEL'), ('WP_A_0760_1.tae', tae([(76405033, 'hkx', 76421020)])),
                       ('a076_405010_1.hkx', b'A'), ('a076_412000_1.hkx', b'B'), ('a076_421020_1.hkx', b'C'),
                       ('a999_000000_1.hkx', b'REST')])
    resting = binder([('skeleton.hkx', b'SKEL'), ('a999_000000.hkx', b'REST')])
    (root / 'parts/wp_a_0760.partsbnd').write_bytes(binder([('WP_A_0760_1.flver', b'not read'), ('WP_A_0760_1.anibnd', animated),
                                                            ('WP_A_0760.anibnd', resting)]))
    (root / 'parts/wp_a_0300.partsbnd').write_bytes(binder([('WP_A_0300.anibnd', resting)]))
    # Outfit binders are never opened for part clips.
    (root / 'parts/bd_m_9000.partsbnd').write_bytes(b'not a binder')
    base = root / 'chr/c0000.anibnd'
    # Wolf's a076_412000 plays the body clip a070_412000.
    base.write_bytes(binder([('a076.tae', tae([(412000, 'hkx', 70412000)])), ('a070.tae', tae([(412000, 'own', 0)]))]))
    return base


def catalog(root, base, layout='game', game='sekiro', inventoried=True):
    """A source catalog of that folder: a game folder by default, or a collected folder."""
    scope = str(root)
    key = f'{game}|{scope}|c0000' if layout == 'folder' else 'c0000'

    def clip(name, ready=True):
        return dict(id=name.split('.')[0] + '-id', name=name, archive=str(base), member=name, character='c0000', characterKey=key,
                    game=game, scope=scope, ready=ready, issues=[] if ready else ['missing input'], path='', skeleton='',
                    compendium='', skeletonCompendium='', inputArchives=[str(base)])
    parts = [dict(id=p.name.split('.')[0], name=p.name.split('.')[0].upper(), path=str(p), selected=False, game=game, scope=scope,
                  role='Weapon', container='Binder + textures') for p in sorted((root / 'parts').iterdir())]
    clips = [clip('a076_405010.hkx'), clip('a070_412000.hkx'), clip('a000_000100.hkx'), clip('a076_405033.hkx', ready=False)]
    return dict(schema=CATALOG_SCHEMA, layout=layout, folder=str(root), game='' if layout == 'folder' else game, games=[game],
                characters=[dict(id=key, character='c0000', game=game, archives=[str(base)], inventoried=inventoried)],
                parts=parts, clips=clips if inventoried else [], sources=[], warnings=[])


class ListingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'Sekiro'
        self.base = sekiro_folder(self.root)
        self.umbrella = str(self.root / 'parts/wp_a_0760.partsbnd')
        patcher = mock.patch.object(clip_preview, 'use_oodle', lambda path='': None)
        patcher.start()
        self.addCleanup(patcher.stop)
        pa._CACHE.clear()

    def test_lists_the_weapon_parts_with_animated_models(self):
        (self.root / 'parts/wp_a_0700.partsbnd').write_bytes(b'not a binder')
        # Soulstruct logs and prints the traceback of the binder that cannot be read.
        with contextlib.redirect_stderr(io.StringIO()), self.assertLogs('soulstruct', 'ERROR'):
            listing = clip_preview.animated_parts(catalog(self.root, self.base))
        self.assertEqual([(p['id'], p['clips'], [(m['model'], m['clips']) for m in p['models']]) for p in listing['parts']],
                         [('wp_a_0760', 3, [('wp_a_0760_1', 3)])])
        # The katana holds only its rest pose, an unreadable binder becomes a notice, and the outfit is not opened.
        self.assertEqual(listing['read'], 3)
        self.assertEqual(len(listing['notices']), 1)
        self.assertTrue(listing['notices'][0].startswith('wp_a_0700.partsbnd: '))

    def test_each_part_clip_lists_the_player_clips_it_plays_in(self):
        result = clip_preview.part_matches(catalog(self.root, self.base), self.umbrella)
        self.assertEqual((result['part'], result['characterKey'], result['inventoried'], result['playerClips'], result['tae']),
                         ('wp_a_0760', 'c0000', True, 4, True))
        model, = result['models']
        self.assertEqual((model['model'], model['binder'], model['rest']), ('wp_a_0760_1', 'WP_A_0760_1.anibnd', 'a999_000000_1.hkx'))
        self.assertEqual({c['id']: (c['member'], [(m['name'], m['archive'], m['reason'], m['ready']) for m in c['matches']])
                          for c in model['clips']},
                         {'a076_405010': ('a076_405010_1.hkx', [('a076_405010.hkx', 'c0000.anibnd', 'same ID', True)]),
                          'a076_412000': ('a076_412000_1.hkx', [('a070_412000.hkx', 'c0000.anibnd',
                                                                 'TAE of C0000: a076_412000 plays a070_412000', True)]),
                          'a076_421020': ('a076_421020_1.hkx', [('a076_405033.hkx', 'c0000.anibnd',
                                                                 'its TAE plays a076_421020 for a076_405033', False)])})

    def test_the_import_keys_each_listed_part_clip(self):
        data = catalog(self.root, self.base)
        tae_index = pa.character_tae(pa.character_binder(data, data['clips'][0]))
        pairs = 0
        for clip in clip_preview.part_matches(data, self.umbrella)['models'][0]['clips']:
            for match in clip['matches']:
                row, = [r for r in pa.plan([self.umbrella], match['name'], tae_index, 'c0000') if r['model'] == 'wp_a_0760_1']
                self.assertEqual((row['id'], row['reason']), (clip['id'], match['reason']))
                pairs += 1
        self.assertEqual(pairs, 3)

    def test_parts_outside_the_catalog_and_other_games_are_refused(self):
        data = catalog(self.root, self.base)
        for path in (str(self.root / 'parts/bd_m_9000.partsbnd'), str(self.root / 'parts/../parts/wp_a_0760.partsbnd'), ''):
            with self.assertRaises(ValueError):
                clip_preview.part_matches(data, path)
        ds3 = catalog(self.root, self.base, game='ds3')
        self.assertEqual(clip_preview.animated_parts(ds3), dict(parts=[], notices=[], read=0))
        with self.assertRaises(ValueError):
            clip_preview.part_matches(ds3, self.umbrella)

    def test_a_game_folder_reads_the_player_first(self):
        result = clip_preview.part_matches(catalog(self.root, self.base, inventoried=False), self.umbrella)
        self.assertEqual((result['characterKey'], result['inventoried'], result['playerClips'], result['tae']), ('c0000', False, 0, False))
        self.assertEqual([c['matches'] for c in result['models'][0]['clips']], [[], [], []])

    def test_a_collected_folder_pairs_the_player_clips_beside_the_part(self):
        data = catalog(self.root, self.base, layout='folder')
        elsewhere = str(self.root / 'other')
        data['clips'].append(dict(data['clips'][0], id='elsewhere-id', scope=elsewhere, characterKey=f'sekiro|{elsewhere}|c0000'))
        result = clip_preview.part_matches(data, self.umbrella)
        self.assertEqual((result['characterKey'], result['playerClips']), (f'sekiro|{self.root}|c0000', 4))
        self.assertEqual([m['clip'] for m in result['models'][0]['clips'][0]['matches']], ['a076_405010-id'])


class RouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'Sekiro'
        base = sekiro_folder(self.root)
        self.home = Path(temp.name) / 'home'
        self.catalog = self.home / 'work/asset-cache/catalogs/sekiro.json'
        self.catalog.parent.mkdir(parents=True)
        self.catalog.write_text(json.dumps(catalog(self.root, base)), encoding='utf-8')
        self.umbrella = str(self.root / 'parts/wp_a_0760.partsbnd')
        for target, name, value in ((bridge_ui, 'HOME', self.home), (bridge_ui, 'CONFIG', {}),
                                    (clip_preview, 'use_oodle', lambda path='': None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        pa._CACHE.clear()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), bridge_ui.Handler)
        self.server.token = TOKEN
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, route, data, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        self.addCleanup(connection.close)
        headers = {'Content-Type': 'application/json', 'X-Bridge-Token': TOKEN, **headers}
        connection.request('POST', route, json.dumps(data).encode(), {k: v for k, v in headers.items() if v is not None})
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def files(self):
        return sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for folder in (self.root, self.home) for p in folder.rglob('*'))

    def test_the_routes_list_parts_and_pairs_without_writing(self):
        before = self.files()
        request = dict(path=str(self.catalog), folder=str(self.root))
        status, listing = self.post('/api/part-list', request)
        self.assertEqual((status, [p['id'] for p in listing['parts']]), (200, ['wp_a_0760']))
        status, result = self.post('/api/part-matches', dict(request, part=listing['parts'][0]['path']))
        self.assertEqual(status, 200)
        self.assertEqual([(c['id'], [m['clip'] for m in c['matches']]) for c in result['models'][0]['clips']],
                         [('a076_405010', ['a076_405010-id']), ('a076_412000', ['a070_412000-id']), ('a076_421020', ['a076_405033-id'])])
        self.assertEqual(self.files(), before)

    def test_requests_need_the_token_host_and_origin_of_this_session(self):
        request = dict(path=str(self.catalog), folder=str(self.root))
        for headers in (dict(**{'X-Bridge-Token': None}), {'X-Bridge-Token': 'wrong'}, {'Host': 'localhost:1'},
                        {'Origin': 'http://evil.example'}):
            for route in ('/api/part-list', '/api/part-matches'):
                status, body = self.post(route, dict(request, part=self.umbrella), **headers)
                self.assertEqual((status, body), (403, {'error': 'Unauthorized workspace session'}), (route, headers))

    def test_only_listed_routes_answer(self):
        status, body = self.post('/api/part-files', dict(path=str(self.catalog), folder=str(self.root)))
        self.assertEqual((status, body), (404, {'error': 'Unknown route'}))

    def test_the_catalog_must_be_in_the_bridge_cache_and_the_part_in_the_catalog(self):
        outside = self.home / 'sekiro.json'
        outside.write_text(self.catalog.read_text(encoding='utf-8'), encoding='utf-8')
        for route in ('/api/part-list', '/api/part-matches'):
            status, body = self.post(route, dict(path=str(outside), folder=str(self.root), part=self.umbrella))
            self.assertEqual((status, body), (400, {'error': 'Invalid folder catalog.'}))
        status, body = self.post('/api/part-matches', dict(path=str(self.catalog), folder=str(self.root),
                                                           part=str(self.root / 'chr/c0000.anibnd')))
        self.assertEqual((status, body), (400, {'error': 'Choose a Sekiro weapon part from the scanned source.'}))
        status, body = self.post('/api/part-list', dict(path=str(self.catalog), folder=str(self.home)))
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
