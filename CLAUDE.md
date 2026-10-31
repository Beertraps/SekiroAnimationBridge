# Sekiro Animation Bridge: notes for agents

The bridge imports FromSoftware HKX animations with their skinned characters into Blender and exports the edited
clip as HKX again. Other engines (Devil May Cry 5, DOOM Eternal, Unreal Engine 4 and 5) come as import-only game
packages. Windows only.

The pipeline: a **source** folder → a **catalog** of its characters and clips → the decoder writes a **motion JSON**
and the model code a **character manifest** with `.npz` meshes ([docs/INTERCHANGE.md](docs/INTERCHANGE.md), the
contract) → Blender builds the scene → export samples it back and writes HKX.

## Setup

- Conversion Python: `%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe`, made by
  `tools\setup_writer.cmd` (needs uv, or Python 3.13 with the `py` launcher). Everything below runs with it.
- HKX decoder: `tools\prepare_dotnet_runtime.cmd`, then `tools\SekiroMotionDecoder\build_decoder.cmd` (.NET 9 SDK). It
  also builds `SekiroCharacterWriter.exe`, which the character export needs.
  The RE Engine decoder is only for DMC5: `packages\re_engine\decoder\build_decoder.cmd`. The Unreal decoder is only
  for Unreal Engine games: `packages\unreal\decoder\build_decoder.cmd` (.NET 10 SDK; CMake and the C++ build tools for
  ACL clips, [docs/games/unreal.md](docs/games/unreal.md)).
- Blender 4.5. The bridge finds standard installations; `bridge_cli env` says which one it uses and what is missing.
- Optional, for `export --register-slot`: `tools\setup_hkb_duplicator.cmd` downloads the SDT HKB Duplicator (commit
  560426d, no license: never copy its code into the repo) to `%LOCALAPPDATA%\SekiroAnimationBridge\tools`;
  `setup_writer.cmd` installs its lxml. `SEKIRO_HKB_DUPLICATOR` and `SEKIRO_CHARACTER_WRITER` point at other copies.
- Inside a packaged app, such as the Claude desktop app, Windows keeps new folders under `%LOCALAPPDATA%` in the app's
  own copy (`%LOCALAPPDATA%\Packages\<app>\LocalCache\Local`). Setup run there is invisible to the bridge started from
  Explorer, and the reverse; run it once in each place that uses the bridge. There, `setup_writer.cmd` stops at the
  junction uv makes for Python 3.13, whose target only the app sees. Create the environment from the full-version
  folder, then run `setup_writer.cmd` again to install the requirements:
  `tools\uv\uv.exe venv --python %LOCALAPPDATA%\SekiroAnimationBridge\python\cpython-3.13.<n>-windows-x86_64-none\python.exe %LOCALAPPDATA%\SekiroAnimationBridge\writer-env`.

## Drive the bridge with `standalone\bridge_cli.cmd`

Every command prints one JSON document on stdout; the log goes to stderr. Exit code 1 means
`{"ok": false, "error": "..."}`. `bridge_cli <command> --help` lists the options.

```bat
standalone\bridge_cli.cmd env
standalone\bridge_cli.cmd scan "D:\Games\Sekiro"
standalone\bridge_cli.cmd clips <catalog> --character c5060 --match a000_003
standalone\bridge_cli.cmd select <catalog> <clip ID>
standalone\bridge_cli.cmd import <catalog> <clip ID> --output work\scenes\c5060.blend
standalone\bridge_cli.cmd verify work\scenes\c5060.blend --render work\scenes\c5060.png
standalone\bridge_cli.cmd export work\scenes\c5060.blend --output work\scenes\c5060_edited.hkx
standalone\bridge_cli.cmd export work\scenes\wolf.blend --output work\scenes\a000_000000.hkx --write-parts work\mods\umbrella
standalone\bridge_cli.cmd part-verify work\mods\umbrella
standalone\bridge_cli.cmd export work\scenes\c1010.blend --output work\scenes\a100_003008.hkx --binder work\mods\c1010\chr\c1010.anibnd.dcx --binder-member a100_003008.hkx --register-slot
standalone\bridge_cli.cmd character-parts "D:\Games\Sekiro" --map m11_00_00_00
standalone\bridge_cli.cmd character-export work\scenes\dante.blend --game-folder "D:\Games\Sekiro" --id c1800 --output work\mods\dante --map m11_00_00_00 --part c1010_0000
standalone\bridge_cli.cmd character-model work\scenes\c1010_gun.blend --template c1010 --game-folder "D:\Games\Sekiro" --output work\mods\c1010_gun
standalone\bridge_cli.cmd character-model work\scenes\c1010_gun.blend --template c1010 --game-folder "D:\Games\Sekiro" --output work\mods\c1010_wbones --weapon-bones
standalone\bridge_cli.cmd character-verify work\mods\dante --id c1800
```

- `scan` prints the catalog path the other commands take. In a game folder, clips are listed per character once it
  is read: pass `--character`.
- A game package can ask for source options, such as the Unreal package's engine version and AES key: `detect` lists
  them in `optionFields`, and `detect` and `scan` take them as `--option ID=VALUE`.
- `verify` answers "did the import work?" without opening Blender: `passed`, and `checks[]` with a reason for each.
  It checks the size (unit scale), the up axis, left bones on +X (facing Blender's front), whether each mesh follows its
  bones, vertices left on model bones outside the animation, and missing images. `skin stretch` is advisory and left
  out of `passed`: cloth stretches as far as a wrong bind does, so it names a frame to look at, not a fault.
  `--render` writes a front and a side picture; look at them when a check fails or a change touches the scene.
- `export --write-parts` also puts the weapon part clips into their part binders (`parts\wp_a_XXXX.partsbnd.dcx` and the
  `_l` copy) in a mod folder with a me3 profile, and reads them back like `part-verify`. A weapon at rest gets a new clip
  when its weapon rig is keyed. Plan, facts and limits: [docs/PART_ANIMATIONS_PLAN.md](docs/PART_ANIMATIONS_PLAN.md).
- `export --binder ... --register-slot` gives a clip new to the binder a TAE entry (copied from the source clip by
  `SekiroCharacterWriter tae`) and a clip generator in `cXXXX.behbnd.dcx` beside the binder (the Duplicator's
  variation), and reads both back. Only a new category of the source's number: `a000_003008` to `a100_003008`.
  `--slot-source` names the source; the scene's clip by default. In-game playback is not proven.
- An additive clip (`blendHint` 1, such as the flinch `a000_100002`) imports on the rest pose, or on a normal clip of
  the same character with `import --additive-base CLIP`, and exports as additive again. `export --additive
  rest|first-frame` writes a normal clip's scene as an additive clip. Needs decoder 0.7.0. Convention and the game's
  layers: [docs/LAYERED_ANIMATIONS.md](docs/LAYERED_ANIMATIONS.md). DOOM Eternal's additive md6 clips import the same
  way (space `separate`, base clip by name such as `combat/idle_01`); a package's base clip comes from its `preview`.
- `character-export` writes a scene as a new Sekiro character (template `c1010` by default) into a mod folder with a
  me3 profile beside it, and ends with the 12 checks of `character-verify`. `character-clone` writes the template itself
  under the new ID. `character-model --template c1010` writes a scene of a vanilla character as its model and textures
  only; its skeleton, clips and behavior stay the game's. Plan, facts and limits:
  [docs/CHARACTER_EXPORT_PLAN.md](docs/CHARACTER_EXPORT_PLAN.md). With `--weapon-bones` the scene's weapon bones join
  the skeleton after its last bone at rest scale 0.001; its clips stay, and an `export --binder` into that mod's anibnd
  gives a new clip their tracks ([docs/PART_ANIMATIONS_PLAN.md](docs/PART_ANIMATIONS_PLAN.md) 4.3).
- `run <request.json>` takes any request that the UI or `sekiro_animation_cli.ps1` sends to `bridge_runtime.py`.

## Tests

```bat
"%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe" -E -X utf8 -m unittest discover -s standalone/tests -p "test_*.py"
"%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe" -E -X utf8 -m unittest discover -s packages/<id>/tests
blender --background --factory-startup --python-exit-code 1 --python standalone/tests/<blender_script>.py
tools\check_package.cmd packages\<id> [--source <game folder>] [--option <id>=<value> ...]
```

- The Blender scripts are `standalone/tests/blender_*.py`; each prints a line saying it passed, or raises. Without
  `--python-exit-code 1`, Blender exits with 0 even when the script raises.
  `blender_weapons.py`, `blender_part_animations.py` and `blender_weapon_locations.py` take an output folder after `--`.
- Without the conversion Python, a plain Python 3.12 or later runs the tests that need neither NumPy nor Soulstruct;
  the other test modules fail on import, which says nothing about the code.
- Fixtures are synthetic and owned by the project (`tests/humanoids.py`, stand-in files in `tests/test_sources.py`).

## Rules

- **No game files in Git.** `.gitignore` lists their extensions. Game-derived work, caches, scenes and logs go in `work/`.
- **Never write into a game installation.** `dcx_codec.protect_output` refuses it; do not work around it.
- **FromSoftware results stay identical** when code is generalized for other games: the same numbers, scenes, catalogs and exports.
- A game package imports only `games.api` from the bridge ([docs/PACKAGES.md](docs/PACKAGES.md)). FromSoftware games are
  built in, not packages ([docs/GAME_PACKAGES_PLAN.md](docs/GAME_PACKAGES_PLAN.md)).
- Commit, push, tag or release only when the user asks. A release is `VERSION`, `CHANGELOG.md` and a `v*` tag; the
  workflow in `.github/workflows/release.yml` builds and publishes it.
- Record user-facing changes in the *Unreleased* section of `CHANGELOG.md`, and what was checked and how in
  `docs/VERIFICATION.md`. Docs use short, plain sentences and name exact files, clips and numbers.
- `docs/PROJECT_CONTEXT.md` is the decision log up to 0.13.0, newest first, and about 65,000 tokens: read its first
  section and search it, never the whole file. Later work is in the changelog, the verification log and the plans in `docs/`.

## Where things are

| Area | Files |
| --- | --- |
| Games, engines, capabilities, axes | `standalone/games/` (`__init__.py` registry, `base.py`, `space.py`, `packages.py`, `api.py`) |
| FromSoftware sources and catalogs | `standalone/asset_sources.py`, `standalone/asset_discovery.py` |
| Models, materials, textures | `standalone/character_assets.py`, `flver_geometry.py`, `material_assets.py`, `weapon_assets.py` |
| One request, start to end | `standalone/bridge_runtime.py` `convert()`: the UI and both command lines send it their requests |
| UI | `standalone/bridge_ui.py` (local server), `standalone/ui/` |
| Blender side | `standalone/blender_bridge.py`, `blender_character.py`, `blender_parts.py`, `blender_verify.py` |
| HKX writing | `standalone/build_animation.py`, `havok_compat.py`, `binder_members.py` |
| Weapon part clips | `standalone/part_animations.py` (pairing, import), `blender_parts.py`, `part_export.py` (part binders) |
| Additive clips | `standalone/games/additive.py` (compose and difference), `blender_bridge.py` import and export |
| New animation IDs | `standalone/animation_slots.py`, `havok_xml.py` (behavior tagfile to XML and back), `tools/SekiroCharacterWriter/Tae.cs` |
| New Sekiro characters | `standalone/character_export.py`, `havok_tagfile.py` (TAG0 patching), `blender_character_export.py`, `tools/SekiroCharacterWriter/` |
| Retarget add-on | `blender_addon/sekiro_retarget/` |
| Other engines | `packages/re_engine`, `packages/doom_eternal`, `packages/unreal`, template `standalone/tests/fixtures/packages/example` |
