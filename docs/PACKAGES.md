# Writing a game package

The bridge reads FromSoftware games itself. Every other engine comes as a **game package**: a folder with a `package.json`, a Python module that implements the package API, and the tools that module runs. The RE Engine package for Devil May Cry 5 (`packages/re_engine`) is built only on this API, as are the experimental DOOM Eternal package (`packages/doom_eternal`), which reads its game in Python and runs no tools, and the experimental Unreal Engine package (`packages/unreal`), which reads every UE4 and UE5 game with one decoder and asks for each game's engine version, key and mappings file through source options. So is the example package used in the tests (`standalone/tests/fixtures/packages/example`), which is the template for a new one.

A package reads its game's files and writes the bridge's interchange files ([INTERCHANGE.md](INTERCHANGE.md)): a motion JSON for each clip and, when it can, a character manifest with models and textures. Everything after that (the skeleton preview, the Blender scene, the retarget add-on) is the bridge's work and needs no change for a new engine.

Packages import only. A package's games cannot be exported; users retarget their clips onto a FromSoftware character with the retarget add-on and export that.

## Start from the example

1. Work in a source checkout of the bridge (see the README's *Build from source*).
2. Copy `standalone/tests/fixtures/packages/example` to `packages/<your id>`, for example `packages/my_engine`.
3. In `package.json`, change `id` to the folder name, and `name`, `version`, `authors`, `homepage` and the game entries to yours.
4. Replace the functions in `__init__.py` with ones that read your game. Keep their names and arguments.
5. Check it on a folder of your game:

   ```
   tools\check_package.cmd packages\my_engine --source "D:\Games\My Game"
   ```

6. Start the bridge. **Settings & setup › Game packages** lists the package, and the source dialog detects your game.

The bridge loads packages from `packages/` in its own folder and from `%LOCALAPPDATA%\SekiroAnimationBridge\packages`, where **Install package…** puts them. When both hold the same ID, the bridge folder wins, so your working copy is used while you develop.

## Layout

```
my_engine/
  package.json        identity, games, source options, tools, bone names
  __init__.py         the API functions
  other.py            any other modules: import them with "from . import other"
  tools/              built tools, such as my-decoder/MyDecoder.exe (not in Git)
  decoder/            the tools' sources and build script (optional)
  tests/              the package's own tests (optional)
```

The bridge imports the folder as the Python package `bridge_packages.<id>`, so relative imports work and two packages never collide. Import only `games.api` from the bridge: other modules of the bridge may change in any version.

## package.json

`standalone/schemas/package.schema.json` checks it.

| Field | Meaning |
| --- | --- |
| `id` | Lower case letters, digits and `_`, starting with a letter: `re_engine`. It is also the engine name in documents. `fromsoft`, `games`, `packages` and `bridge` are taken. |
| `name`, `version`, `description` | Shown on the Setup page. `version` is your package's version. |
| `apiVersion` | `1`. A bridge lists packages of API versions it does not know as incompatible and does not load them. |
| `authors`, `license`, `homepage` | Shown before a user installs the package, so they see where it comes from. |
| `games` | One entry per game, see below. Game IDs must be unique among all games the bridge knows. |
| `sourceOptions` | Fields the source dialog can show for a source of your games, see *Source options*. `"fileList"` is the **File list** field, for a file such as RE Engine's file list. |
| `tools` | Programs the package runs, see *Tools*. |
| `bones` | Bone names for the retarget add-on, see *Bone names*. |

A game entry:

| Field | Meaning |
| --- | --- |
| `id`, `name`, `short` | `dmc5`, `Devil May Cry 5`, `DMC5`. |
| `executables` | File names that mark a game folder. |
| `capabilities` | `import_animation`, `import_character`, `textures`, `root_motion`, `packed_archives` as true or false. `export`, `add_to_binder`, `weapons` and `part_animations` must be false. |
| `basis`, `unitScale` | The game's axis convention and unit, as in [INTERCHANGE.md](INTERCHANGE.md#source-space). |
| `formats` | Free notes on file versions, shown nowhere but useful to readers. |
| `hint` | One line for the source dialog's help: what a folder of this game holds. |
| `verified` | `false` until someone checked the game with real files; the UI marks it *untested*. |
| `documentation` | A path such as `docs/games/dmc5.md`. |

### Source options

A source can need more than its folder: a key, an engine version, a file that is not in the game. Declare each as an object; the Unreal Engine package declares these:

```json
"sourceOptions": [
  {"id": "engineVersion", "name": "Engine version", "kind": "choice", "default": "auto",
   "choices": [{"value": "auto", "label": "Auto"}, {"value": "GAME_UE4_27", "label": "Unreal Engine 4.27"}]},
  {"id": "aesKey", "name": "AES key", "kind": "secret", "placeholder": "0x followed by 64 hexadecimal digits",
   "help": "The key the game's archives are encrypted with."},
  {"id": "mappings", "name": "Mappings file", "kind": "file", "filter": "Mappings (*.usmap)|*.usmap|All files (*.*)|*.*"}
]
```

| Field | Meaning |
| --- | --- |
| `id` | A name such as `aesKey`, unique in the package. `fileList` is taken. |
| `name` | The field's label. |
| `kind` | `text`; `secret`, a text field that hides what is typed; `file`, a path with a **Browse** button; or `choice`, a list of `choices`, each a `value` and its `label`. |
| `default` | The value when the user sets none. A choice's default must be one of its values; without one it is the first. |
| `help`, `placeholder` | The help behind the field's **?** button, and the grey text of an empty field. |
| `filter` | For `file`: the file types the **Browse** window offers, as `Name (*.ext)\|*.ext` pairs. |

How the values reach your package:

- `detect` and `scan` get every declared option in `options`: what the user entered, trimmed, or the default. A choice that is not in the list falls back to the default.
- A detection lists in `options` the fields its source shows, and in `needs` the ones that must be filled before a scan, such as the key of an encrypted game. Show a field only where the source can use it.
- Each set of values has its own catalog. Choosing another engine version scans again instead of opening the scan made with the old one.
- The import request carries the values as `sourceOptions`. The command-line interface reads them from a JSON file, `-SourceOptionsFile options.json` with `{"engineVersion": "GAME_UE4_27"}`, and a donor from another source from `-DonorSourceOptionsFile`.

The bridge keeps the values with the source in its settings on this computer and hands them only to your package. Keep secrets out of the documents you write, such as motion JSONs and reports, which users share.

## API version 1

Every function is a module-level function. Each gets plain dictionaries and paths and a `Context` as its last argument, `ctx`. Raise `ValueError` with a message for the user when something is wrong with the source; the bridge shows the message. The bridge stores the catalogs, caches the previews and checks each result against its schema, so a mistake in a package shows as a clear error instead of a broken scene.

| Function | Returns |
| --- | --- |
| `detect(path, options, ctx)` | `None` when the folder is not a source of your games. Otherwise a detection: `game`, `root` (the folder to scan, which may be a parent or child of `path`), `evidence` (what identified the game), `note` (a line for the source dialog), `counts` (`animations`, `characters`, `materials`), `options` (the source options the dialog shows for this source, such as `["fileList"]` or `["engineVersion", "aesKey"]`) and `needs` (those that must be filled before a scan). Other keys are kept and handed to `scan`. The argument `options` holds the user's values: `fileList` and each declared option. |
| `scan(detection, options, ctx, previous)` | A catalog of the source's characters. Clips of a character can wait until it is chosen. `previous` is the last catalog of the same source, or `None`, so characters already read can be kept. |
| `inventory(catalog, character, ctx)` | The catalog with the clips of one character, and that character's `inventoried` set to true. |
| `selection(catalog, clip_id, preset, ctx)` | What the import uses of one clip: `animation` (a path), `game`, `character`, `clipName`, and `parts`, the model parts the UI lists, each with `id`, `path`, `role` and `selected`. |
| `preview(selection, ctx)` | A motion JSON version 2 of the clip, as a dictionary. The bridge turns it into the skeleton preview and caches the result. |
| `prepare(request, catalog, temp, ctx)` | A dictionary: `motion` (path of a motion JSON version 2 written into `temp`), `characters` (a list with at most one path of a character manifest version 5), `report` (`clip`, `frames`, `tracks`, `warnings`, `parts`, `textures`), and optionally `catalog` (when it read more of the source) and `request` (keys the bridge sets on the import request, such as `game`). `request` holds `assetClip`, `assetCharacter`, `includeCharacter` and the source's `assetFolder`, `sourceFileList` and `sourceOptions`. |
| `refresh(catalog, clip_id, ctx)` | Optional. `(catalog, clip_id)` after the files of a clip changed, such as a mod archive. |
| `validate(catalog, folder, check_sources, ctx)` | Optional. Raise `ValueError` when a stored catalog no longer fits the source, for example after a game update. |
| `preview_key(selection, ctx)` | Optional. A string that changes whenever the preview would. By default the bridge uses the selection and the size and date of the clip file and of the package's tools. |

### Catalogs

`standalone/schemas/catalog.schema.json` checks them.

- The catalog: `schema` (your own number; change it when the catalog's shape changes), `game`, `folder` (the source folder), `characters`, `clips`.
- A character: `id`, `name`, `archives` (the files its clips come from), `inventoried`. Optional: `count`, `ready`, `model`, `bytes`, `errors` (problems to show in the log).
- A clip: `id` (unique in the catalog, such as `pl0100/pl0100_base#0`), `name`, `character`, `characterKey` (the ID of its character), `game`, `ready` (whether it can be imported) and `issues` (why not). Optional: `archive`, `member`, `path`.

Keep other keys you need: the bridge stores the catalog as you return it and adds `engine` and `package`.

### Context

| `ctx.` | Meaning |
| --- | --- |
| `cache` | A folder of your package in the bridge's cache. Keep extracted files there. |
| `notify(stage, message, percent)` | A progress line. `stage` is `inventory`, `decode` or `character`. |
| `profiles`, `profile(game)` | Your games, as the bridge reads them from `package.json`, with `space()` for the axis convention. |
| `tool(id)` | The path of one of your tools; a clear error when it is missing. |
| `run(id, *args, timeout=900)` | Runs a tool and returns what it printed. A tool that fails raises `ValueError` with its last line on stderr, or on stdout. |

### What games.api offers

`Space` (axis conventions), `check_motion` and `check_manifest` (check a document before you return it), `with_source` (adds the `source` block and space to a motion JSON), `write_json` (writes without leaving half a file), `read_json`, `signature` (size and date of a file, to notice changes) and `dds_to_png` (converts DDS textures with the bridge's texconv).

## Tools

A package that needs a program declares it in `package.json`:

```json
"tools": [{
  "id": "decoder", "name": "RE Engine decoder",
  "path": "tools/re-decoder/ReEngineDecoder.exe",
  "version": ["--version"], "expect": "ReEngineDecoder 0.1",
  "runtime": "dotnet-9", "build": "decoder/build_decoder.cmd",
  "help": "Reads PAK archives, motions, meshes and textures."
}]
```

- The Setup page shows a card for each tool. It runs the tool with the `version` arguments and is ready when the output starts with `expect`.
- `runtime: "dotnet-9"`: the tool is a framework-dependent .NET 9 program. The bridge points `DOTNET_ROOT` at its shared runtime, so the package does not carry its own (about 68 MB). Publish it with `dotnet publish -r win-x64 --self-contained false`.
- A tool on another .NET version leaves `runtime` out and carries its own runtime: publish it with `--self-contained true`. The Unreal Engine package does this, because CUE4Parse needs .NET 10.
- `build` names a script in the package that builds the tool into `tools/`. Keep `tools/` out of Git; `.gitignore` already ignores `packages/*/tools/`.

## Bone names

The retarget add-on pairs bones by name and knows the usual names (`Pelvis`, `L_Thigh`, `L_UpperArm`, finger numbers) and RE Engine's. For other names, give it the names it knows:

```json
"bones": {
  "names": {"Becken": "Pelvis", "Kopf": "Head"},
  "patterns": [{"match": "([LR])_Oberschenkel", "as": "\\1_Thigh"}]
}
```

`names` maps exact bone names; `patterns` are Python regular expressions that must match the whole name, with `as` as the replacement. Rigs record their game when they are imported, so the add-on uses these names only for rigs of your games. The bone keeps its own name in Blender.

## Testing

- **Unit tests.** Replace your tool with a function that answers its commands with made-up data, and run the API through the bridge as `packages/re_engine/tests/test_re_engine.py` does: it points `games.packages.ROOTS` at the folder that holds the package and patches `games.api.Context.run`. Run it with `python -m unittest discover -s packages/re_engine/tests`.
- **The checker** runs your package as the bridge does, step by step, and says which step fails and why:

  ```
  tools\check_package.cmd packages\my_engine --source <game folder> [--file-list <file>] [--option <id>=<value> ...] [--character <id>] [--clip <id or name>] [--models] [--blender <blender.exe> --output <scene.blend>]
  ```

  Without `--source` it checks `package.json`, the module and the tools. With a source it detects and scans it, reads one character, chooses one clip, builds its preview and prepares the import; `--models` includes the character's models, and `--blender` finishes with a Blender scene. `--option` sets a source option, such as `--option engineVersion=GAME_UE4_27`; repeat it for each option. Open the scene and check it as [VERIFICATION.md](VERIFICATION.md) describes: height, left side on +X, facing Blender's front, textures.
- Set `verified` to true for a game once that check passes with the game's own files.

## Publishing

Build a ZIP with the package and its built tools:

```
python tools/package_game_package.py packages\my_engine --output dist\AnimationBridge-package-my_engine-1.0.0.zip --tool decoder=<folder the build wrote>
```

The ZIP has one top folder named after the ID. It leaves out caches, `bin`, `obj` and the package's `tools/` folder, and puts each `--tool` folder where `package.json` expects the tool. Users install it with **Install package…** on the Setup page; installing a newer version replaces the older one.

Licenses: the package's own license is yours. Name the licenses of the libraries your tools include in your README, and do not include game files.

## Security

A package runs Python code and programs with the user's rights. It can read and change every file the user can. The bridge cannot make that safe, so it makes it visible: it loads packages only from the two package folders, downloads nothing, checks ZIPs for paths that leave the package folder, and shows the package's name, authors, homepage and license with a warning before it installs one. Tell your users where to get your package, and publish its source.
