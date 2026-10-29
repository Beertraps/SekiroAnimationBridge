"""Asset sources: where a game's files are, and how their folders are laid out.

A source is a collected folder (any files, matched by the directory they share),
a folder in the game's own structure (an unpacked game or a mod folder with chr,
parts and mtd), or a custom layout that names the folders for each kind of file.
Detection only lists folders; reading archives is left to asset_discovery.
"""
from __future__ import annotations
import re
from pathlib import Path
from games import games as registered

KINDS = ('animations', 'characters', 'parts', 'textures', 'materials')
LAYOUTS = ('auto', 'folder', 'game', 'custom')
SUFFIXES = {
    'animations': ('.anibnd', '.anibnd.dcx'),
    'characters': ('.chrbnd', '.chrbnd.dcx', '.flver', '.flver.dcx'),
    'parts': ('.partsbnd', '.partsbnd.dcx'),
    'textures': ('.texbnd', '.texbnd.dcx', '.tpf', '.tpf.dcx'),
    'materials': ('.mtdbnd', '.mtdbnd.dcx', '.matbinbnd', '.matbinbnd.dcx'),
}
# Executables next to the data folders, or one or two folders above a mod folder.
EXECUTABLES = {name: p.id for p in registered('fromsoft') for name in p.executables}
# DS3 and Elden Ring keep their data in Game; Prepare to Die (UDSFM) in DATA.
DATA_FOLDERS = ('', 'Game', 'DATA')
KIND_FOLDERS = ('chr', 'parts', 'mtd', 'material')
SKIPPED = {'backup', '.git', '__pycache__', 'blender'}
FOLDER_SCAN_LIMIT = 50000


def game_folders(game=''):
    """The game's own structure. Only Elden Ring keeps materials in material/."""
    materials = ['material'] if game == 'er' else ['mtd'] if game else ['mtd', 'material']
    return dict(animations=['chr'], characters=['chr'], parts=['parts'], textures=['chr', 'parts'], materials=materials)


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def matches(path, kind):
    name = path.name.lower()
    return name.endswith(SUFFIXES[kind]) and not name.endswith('.devpatch.dcx')


def has_animations(folder):
    chr_folder = Path(folder) / 'chr'
    return chr_folder.is_dir() and next(chr_folder.glob('*.anibnd*'), None) is not None


def find_game_root(path):
    """The folder holding chr: the chosen one, its Game / DATA subfolder, or the parent of a chosen chr."""
    p = Path(path).expanduser().resolve()
    candidates = []
    if p.name.lower() in KIND_FOLDERS:
        candidates.append((p.parent, f'Uses the folder that contains {p.name}.'))
    for sub in DATA_FOLDERS:
        candidates.append((p / sub if sub else p, f'Uses its {sub} folder, where the game keeps its data.' if sub else ''))
    for folder, note in candidates:
        if folder.is_dir() and has_animations(folder):
            return folder, note
    return None, ''


def executable_game(root):
    for folder in [root, *list(root.parents)[:2]]:
        try:
            for item in folder.iterdir():
                game = EXECUTABLES.get(item.name.lower())
                if game and item.is_file():
                    return game, item.name if folder == root else f'{item.name} in {folder.name}'
        except OSError:
            continue
    return '', ''


def material_game(root):
    if any((root / 'material').glob('allmaterial.matbinbnd*')):
        return 'er', 'material/allmaterial.matbinbnd'
    return '', ''


def resolve_folders(root, folders):
    """Absolute, existing folders per kind. Entries may be relative to the source or absolute."""
    result = {}
    for kind in KINDS:
        found = []
        for entry in (folders or {}).get(kind) or []:
            entry = str(entry).strip()
            if not entry:
                continue
            folder = Path(entry).expanduser()
            folder = (folder if folder.is_absolute() else Path(root) / folder).resolve()
            if folder.is_dir() and folder not in found:
                found.append(folder)
        result[kind] = found
    return result


def override_name(path):
    """The name by which a file in an earlier folder hides one in a later folder: any case, with or without DCX."""
    name = Path(path).name.lower()
    return name[:-4] if name.endswith('.dcx') else name


def layout_files(folders, kind, recursive=False, cache=None):
    """Files of one kind as (folder index, path), without duplicates.

    A file in an earlier folder hides files of the same name in later folders,
    the way a mod folder overrides the game's own files. Within one folder,
    every file is kept.
    """
    seen, hidden, result = set(), set(), []
    for index, folder in enumerate(folders):
        names = set()
        items = folder.rglob('*') if recursive else folder.iterdir()
        for path in sorted(items):
            if cache and (path == cache or cache in path.parents):
                continue
            if recursive and any(x.lower() in SKIPPED for x in path.relative_to(folder).parts[:-1]):
                continue
            if path.is_file() and matches(path, kind) and path not in seen and override_name(path) not in hidden:
                seen.add(path)
                names.add(override_name(path))
                result.append((index, path))
        hidden |= names
    return result


def kind_files(folders, kind, recursive=False, cache=None):
    """Files of one kind in the given folders; see layout_files."""
    return [path for _, path in layout_files(folders, kind, recursive, cache)]


def leading_id(path):
    """The character an archive belongs to: c0000_c5060.anibnd holds c0000's motions against c5060."""
    match = re.match(r'(c\d{4})(?=$|[_.-])', Path(str(path)).name.lower())
    return match[1] if match else ''


def count_folder(root, limit=FOLDER_SCAN_LIMIT):
    counts, total = {kind: 0 for kind in KINDS}, 0
    for path in root.rglob('*'):
        total += 1
        if total > limit:
            return counts, True
        if path.is_file():
            for kind in KINDS:
                if matches(path, kind):
                    counts[kind] += 1
                    break
    return counts, False


def count_custom(root, folders, recursive=False, limit=FOLDER_SCAN_LIMIT):
    """Files per kind in a custom layout, looking at no more than limit entries per folder.

    Files hidden by the same name in an earlier folder are not counted (see layout_files).
    """
    counts, limited = {kind: 0 for kind in KINDS}, False
    for kind, found in resolve_folders(root, folders).items():
        hidden = set()
        for folder in found:
            names = set()
            items = folder.rglob('*') if recursive else folder.iterdir()
            for total, path in enumerate(items, 1):
                if total > limit:
                    limited = True
                    break
                if recursive and any(x.lower() in SKIPPED for x in path.relative_to(folder).parts[:-1]):
                    continue
                if path.is_file() and matches(path, kind) and override_name(path) not in hidden:
                    names.add(override_name(path))
                    counts[kind] += 1
            hidden |= names
    return counts, limited


def nested_games(path, limit=12):
    """Game folders one level down, for a folder that holds several games."""
    found = []
    try:
        children = sorted(p for p in Path(path).iterdir() if p.is_dir())
    except OSError:
        return found
    for child in children:
        root, _ = find_game_root(child)
        if root and root != Path(path):
            game, _ = executable_game(root)
            found.append(dict(path=str(root), name=child.name, game=game or material_game(root)[0]))
            if len(found) >= limit:
                break
    return found


def detect(path, probe=None):
    """Describe a folder: game structure (with its game when identifiable) or a collected folder.

    probe(root) may read one small archive to identify the game; detection itself
    only lists folders.
    """
    chosen = Path(str(path or '')).expanduser()
    if not str(path or '').strip() or not chosen.is_dir():
        raise ValueError(f'Choose an existing folder.\n{chosen}')
    chosen = chosen.resolve()
    root, note = find_game_root(chosen)
    if root:
        game, evidence = executable_game(root)
        if not game:
            game, evidence = material_game(root)
        if not game and probe:
            try:
                game, evidence = probe(root)
            except Exception:
                game, evidence = '', ''
        folders = game_folders(game)
        resolved = resolve_folders(root, folders)
        counts = {kind: len(kind_files(resolved[kind], kind)) for kind in KINDS}
        name = root.name if root.name.lower() not in ('game', 'data') else root.parent.name
        return dict(path=str(chosen), root=str(root), layout='game', game=game, evidence=evidence, note=note,
                    folders={k: [f for f in v if (root / f).is_dir()] for k, v in folders.items()},
                    counts=counts, name=name, nested=[], limited=False)
    counts, limited = count_folder(chosen)
    nested = nested_games(chosen)
    return dict(path=str(chosen), root=str(chosen), layout='folder', game='', evidence='', note='',
                folders={}, counts=counts, name=chosen.name, nested=nested, limited=limited)
