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
    """The code an engine supplies. Every method gets plain paths and dictionaries and returns them.

    detect(path) -> dict | None
        Describe a folder the way asset_sources.detect does, with 'engine' and 'game' set, or None
        when the folder is not this engine's.
    discover(source, cache, notify, game, layout, folders, recursive, options) -> (catalog_path, catalog)
        List a source's characters. A catalog carries 'engine'.
    inventory_character(catalog_path, character, cache, notify) -> catalog
        Read one character's clips.
    refresh_clip(catalog_path, catalog, clip_id, cache, notify) -> (catalog, clip_id)
    selection(catalog, clip_id, preset) -> dict
        The inputs of one clip: what the UI shows and the import uses.
    preview(selection, cache) -> bytes
        Gzipped preview JSON.
    prepare(request, temp, event) -> (motion_path, character_args, report)
        Decode a clip to motion JSON version 2 and its character to a manifest.
    """
