"""FromSoftware games: Havok animations in BND archives, FLVER models and TPF textures.

The FromSoftware code predates the registry and stays in the bridge's modules (asset_sources,
asset_discovery, character_assets, bridge_runtime). This adapter names those entry points, so every
engine offers the same ones (games.base.GameAdapter); the generic code calls them directly.
"""
from __future__ import annotations

from games.space import FROMSOFT

ENGINE = 'fromsoft'
SPACE = FROMSOFT


def detect(path, file_list='', options=None):
    from asset_discovery import detect_fromsoft
    return detect_fromsoft(path)


def discover(root, cache, notify, found, game='auto', file_list='', options=None):
    from asset_discovery import discover as run
    return run(root, cache, notify, '', game, found.get('layout', 'auto'))


def inventory_character(catalog_path, catalog, character, cache, notify=lambda *args: None):
    from asset_discovery import inventory_character as run
    return run(catalog_path, character, cache, notify)


def refresh_clip(catalog_path, catalog, clip_id, cache, notify=lambda *args: None):
    from asset_discovery import refresh_clip as run
    return run(catalog_path, catalog, clip_id, cache, notify)


def load_catalog(catalog, folder, check_sources=False):
    raise NotImplementedError('FromSoftware catalogs are read by asset_discovery.load_catalog.')


def selection(catalog, clip_id, preset='auto'):
    from asset_discovery import selection as run
    return run(catalog, clip_id, preset)


def preview(selection, cache, decoder='', oodle='', stored_only=False):
    from clip_preview import preview as run
    return run(selection, decoder, cache, oodle, stored_only)
