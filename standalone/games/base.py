"""What the bridge knows about a game: a profile of plain data, and the adapter protocol its engine implements."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from games.space import FROMSOFT_BASIS, Space


@dataclass(frozen=True)
class Capabilities:
    """What the bridge can do with a game. The UI, the CLI and the add-on hide or refuse what a game lacks."""
    import_animation: bool = True
    import_character: bool = True
    textures: bool = True
    # Writes the game's own animation format, and can put the result into the game's archive.
    export: bool = False
    add_to_binder: bool = False
    root_motion: bool = False
    # Weapon sockets from a reference model, and weapon parts that animate with the body.
    weapons: bool = False
    part_animations: bool = False
    # Reads the game's packed archives directly instead of extracted files.
    packed_archives: bool = False


@dataclass(frozen=True)
class GameProfile:
    """A game's identity and formats. Code lives in its engine's adapter; this is data only."""
    id: str
    name: str
    short: str
    engine: str
    executables: tuple = ()
    capabilities: Capabilities = field(default_factory=Capabilities)
    basis: tuple = FROMSOFT_BASIS
    unit_scale: float = 1.0
    # File versions and format names, for detection and for the documentation.
    formats: dict = field(default_factory=dict)
    # One sentence for the UI's source-game help.
    hint: str = ''
    # False until an import was checked with the game's own files; the UI marks the game as untested.
    verified: bool = True
    documentation: str = ''
    # The game package that adds the game, and its bone names for the retarget add-on; empty for built-in games.
    package: str = ''
    bones: dict = field(default_factory=dict)

    def space(self):
        return Space(self.basis, self.unit_scale)

    def to_json(self):
        """The profile as the UI, the CLI and the add-on read it."""
        result = asdict(self)
        result['executables'] = list(self.executables)
        result['basis'] = [list(row) for row in self.basis]
        result['unitScale'] = result.pop('unit_scale')
        return result


class GameAdapter(Protocol):
    """The bridge's own entry points for an engine: games.fromsoft for the built-in games, and
    games.packages.PackageEngine, which serves them from a game package's API (games.api, docs/PACKAGES.md).

    detect(path, file_list='') -> dict | None
    discover(root, cache, notify, found, game='auto', file_list='') -> (catalog_path, catalog)
    inventory_character(catalog_path, catalog, character, cache, notify) -> catalog
    refresh_clip(catalog_path, catalog, clip_id, cache, notify) -> (catalog, clip_id)
    load_catalog(catalog, folder, check_sources=False) -> catalog
    selection(catalog, clip_id, preset='auto') -> dict
    preview(selection, cache, stored_only=False) -> bytes | None
        Gzipped preview JSON.
    prepare(request, catalog_path, catalog, temp, event) -> (motion_path, character_args, report)
    """
