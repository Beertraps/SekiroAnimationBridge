# Game packages: engines that anyone can add

The bridge reads FromSoftware games itself. Every other engine comes as a **game package**: a folder with a `package.json`, a small Python module that implements a fixed, versioned API, and the tools that module runs. The RE Engine support for Devil May Cry 5 becomes the first package and is built only on that API, which proves the API is enough.

This continues [MULTI_GAME_IMPORT_PLAN.md](MULTI_GAME_IMPORT_PLAN.md). That plan made the bridge, the UI and Blender engine-neutral; this one lets people outside the project add engines, and lets users download only the engines they need.

## Goals

- A modder adds an engine without changing the bridge: write a package, test it with one command, publish a ZIP.
- A user installs a package from its ZIP on the **Setup** page and removes it there. The bridge release holds FromSoftware support only.
- Packages share one .NET runtime, so a package with a .NET tool adds its own code, not another 68 MB runtime.
- A package can tell the retarget add-on how its bone names map to body parts.

## Not in this version

- FromSoftware stays inside the bridge. Its code predates the registry, is the bridge's reason to exist and exports; it is not a package.
- No package catalog, no automatic downloads and no updates from the internet. Users get packages from their authors.
- No sandbox. A package is code that runs with the user's rights (see *Security*).
- One kind of source option: a file, such as RE Engine's file list. Other kinds come when a package needs them.
- Export stays a FromSoftware feature. A package declares `export: false`; the bridge refuses export of its games with the retarget hint.

## A package

```
re_engine/
  package.json        identity, games, source options, tools, bone names
  __init__.py         the adapter: the API v1 functions
  characters.py       any other modules of the package
  tools/              built or prebuilt tools, such as re-decoder/ReEngineDecoder.exe
  decoder/            sources and build script of the tools (optional)
  tests/              the package's own tests (optional)
  README.md, LICENSE
```

The folder is a Python package. The bridge imports it under a private name (`bridge_packages.<id>`), so relative imports (`from . import characters`) work and two packages never collide. A package imports only `games.api` from the bridge; everything else in the bridge may change between versions.

### package.json

| Field | Meaning |
| --- | --- |
| `id` | Lower case letters, digits and `_`; also the engine ID in documents (`re_engine`). |
| `name`, `version`, `description` | Shown on the Setup page. `version` is the package's own. |
| `apiVersion` | The API the package implements. The bridge loads packages of the API versions it supports (1) and lists others as incompatible. |
| `authors`, `license`, `homepage` | Shown before installing, so the user sees where the code comes from. |
| `games` | Game profiles, as `GameProfile` data: `id`, `name`, `short`, `executables`, `capabilities`, `basis`, `unitScale`, `formats`, `hint`, `verified`, `documentation`. |
| `sourceOptions` | Options a source of this engine can need. Version 1 knows `fileList`: a file the user chooses in the source dialog. |
| `tools` | Programs the package runs: `id`, `name`, `path` (relative to the package), `version` (arguments that print a version line), `expect` (the line's start), `runtime` (`dotnet-9` or none), `build` (a script that builds the tool from the package's sources) and `help`. |
| `bones` | Bone names for the retarget add-on: `names` (exact name → a name the matcher reads, such as `"Becken": "Pelvis"`) and `patterns` (regular expression → replacement). |

`schemas/package.schema.json` checks it.

## API version 1

Every function is a module-level function of the package. Each gets plain dictionaries and paths, and a `Context` as its last argument. The bridge stores catalogs, caches previews, checks every result against its schema and turns errors into messages; the package only reads its game.

| Function | Returns |
| --- | --- |
| `detect(path, options, ctx)` | A detection when the folder belongs to one of the package's games, else `None`: `game`, `root`, `evidence`, `note`, `counts` (`animations`, `characters`, `materials`) and `needs` (source options still missing). Other keys are kept and handed back to `scan`. |
| `scan(detection, options, ctx, previous)` | A catalog: the source's characters, with the clips of characters already read. `previous` is the last catalog of the same source or `None`, so read characters can be kept. |
| `inventory(catalog, character, ctx)` | The catalog with that character's clips. |
| `refresh(catalog, clip_id, ctx)` | Optional. `(catalog, clip_id)` after the clip's files changed. |
| `validate(catalog, folder, check_sources, ctx)` | Optional. Raise `ValueError` when a stored catalog is stale. |
| `selection(catalog, clip_id, preset, ctx)` | What the UI shows of a clip and the import uses: `animation`, `game`, `character`, `clipName`, `parts` (model parts with `selected`), `model`. |
| `preview(selection, ctx)` | A motion JSON version 2 of the clip. The bridge samples it into the skeleton preview and caches it. |
| `preview_key(selection, ctx)` | Optional. A string that changes when the preview would; the default hashes the selection and the package's tools. |
| `prepare(request, catalog, temp, ctx)` | `motion` (path of a motion JSON version 2), `characters` (paths of version 5 manifests), `report` (`clip`, `frames`, `tracks`, `warnings`, `parts`, `textures`), and optionally `catalog` (when it read more clips) and `request` (keys to set on the request, such as `game` and `animation`). |

`ctx` offers `ctx.cache` (the package's own cache folder), `ctx.notify(stage, message, percent)`, `ctx.profile(game)`, `ctx.profiles`, `ctx.tool(id)` (the tool's path, or a clear error when it is missing) and `ctx.run(id, *args)` (runs a tool with the shared runtime and returns its output; a failure raises `ValueError` with the tool's last line).

`games.api` also offers what packages need to build documents: `Space`, `check_motion`, `check_manifest`, `with_source`, `write_json`, `read_json` and `signature`.

The schemas are the contract: motion JSON version 2 and character manifest version 5 ([INTERCHANGE.md](INTERCHANGE.md)), and the new `schemas/catalog.schema.json` for catalogs (`schema`, `game`, `folder`, `characters` with `id`, `name`, `archives`, `inventoried`; `clips` with `id`, `name`, `character`, `characterKey`, `game`, `ready`, `issues`). The bridge adds `engine` and `package` itself.

## Loading

- The bridge looks for packages in `packages/` of its own folder (a source checkout, where package authors work) and in `%LOCALAPPDATA%\SekiroAnimationBridge\packages` (where installed packages go). The first folder with an ID wins; the Setup page names the other as a duplicate.
- A package is read at start: its `package.json` is checked, its games join the registry, its module is imported only when a source of its engine is used. A package that fails to load is listed with the reason, and the rest of the bridge works.
- Installing or removing a package reloads the registry of the running workspace.
- `games.json`, which the bridge writes for the add-on, lists the package games with their bone names.

## Tools and the shared .NET runtime

- The Setup page shows one card per package tool, from its `package.json`, instead of the fixed RE Engine decoder card.
- Both decoders become framework-dependent .NET 9 programs. The release ZIP holds one `dotnet-runtime/` folder; a source checkout prepares it with `tools/prepare_dotnet_runtime.cmd`. The bridge sets `DOTNET_ROOT` to it for every program it starts, so a package's .NET tool runs without its own runtime. A self-contained build still runs, since it ignores `DOTNET_ROOT`.
- `tools/package_game_package.py` builds a package ZIP from a package folder and its built tools. The release workflow publishes the RE Engine package as a separate asset beside the bridge ZIP.

## Installing and removing

On **Setup › Game packages**:

1. **Install package…** opens a file dialog for the package ZIP.
2. The bridge reads the ZIP without running anything from it: one top folder or the root holds `package.json`; no absolute paths or `..`; a size limit. It shows the name, version, authors, homepage, license and games.
3. The user confirms after a warning that the package runs its own code on the computer. A newer or older version of an installed package replaces it after the same confirmation.
4. The ZIP is extracted into the packages folder; the registry reloads; the package's tools are checked.

**Remove** deletes an installed package's folder after confirmation. Packages in the bridge's own `packages/` folder are not removed from the UI.

## Security

A package runs Python code and programs with the user's rights. It can read and change any file the user can. The bridge cannot make that safe, so it makes it visible:

- Packages are only loaded from the two package folders; nothing is downloaded.
- Before installing, the bridge shows where the package comes from and warns in plain words.
- The Setup page lists every loaded package with its folder and homepage.
- Package ZIPs are checked for path tricks before extraction.

## Bone names in the retarget add-on

- The importer stores the clip's game on the rig (`sekiro_game`).
- `retarget.rig_bones` gives each bone an alias from that game's `bones`; the matcher reads the alias, while rows and the bake keep the real names.
- The generic rules stay as they are; aliases are for names they do not read, such as other languages or numbered schemes.

## Checking a package

`tools/check_package.cmd <package folder> --source <game folder> [--file-list <file>] [--character <id>] [--clip <id>] [--blender <blender.exe>]` runs the package the way the bridge does: `package.json`, tools, detect, scan, inventory, selection, preview and prepare on one clip, every result against its schema, and with `--blender` a Blender import of the motion and the character that must finish without errors. It prints one line per step and what to fix.

## RE Engine as the first package

- `packages/re_engine/` holds the adapter (from `standalone/games/re_engine`), the decoder sources (from `tools/ReEngineDecoder`), the DMC5 and RE2 profiles (from `standalone/games/__init__.py`), its tests (from `test_adapters.py`) and its documentation.
- It imports only `games.api`; decoder calls go through `ctx.run`; its cache moves to the package cache (existing DMC5 caches are extracted again once).
- The core tests use a small example package in `standalone/tests/fixtures/example_package`, which reads a made-up format and is the template in the author guide.

## Documentation

- `docs/PACKAGES.md`: the guide for package authors (layout, `package.json`, API, `ctx`, schemas, testing, publishing, security).
- `docs/games/dmc5.md`: installing the RE Engine package comes first.
- README, CHANGELOG, VERIFICATION and INTERCHANGE updated.

## Steps

1. This plan.
2. API v1, the loader and `PackageEngine` (which serves the bridge's existing entry points from API v1), the package and catalog schemas, the example package and its tests.
3. RE Engine moved into `packages/re_engine`, re-tested with its stand-in decoder.
4. Setup page: package list, tool cards, install and remove.
5. Shared .NET runtime, framework-dependent decoders, package ZIPs, release workflow.
6. Bone names from packages in the add-on.
7. `check_package`, author guide, real DMC5 check: install the RE Engine package from its ZIP into a clean packages folder, import Dante and retarget onto Wolf again.

## Risks

- API version 1 becomes a promise. Changes that break packages need version 2, with version 1 kept for a while.
- The release workflow's runtime and package steps run only on GitHub and are checked there first.
- A package's quality is its author's. The checker and the schemas catch broken output, not wrong motion.
