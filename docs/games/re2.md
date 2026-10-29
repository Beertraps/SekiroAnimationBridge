# Resident Evil 2 (DX11) — untested

Resident Evil 2 runs on the same RE Engine version as Devil May Cry 5, so the RE Engine package reads it with the same code and decoder. It has **not** been checked with the game's files. The game list shows it as *Resident Evil 2 (DX11) · untested*.

This profile is the example of adding a second game of a known engine: one entry under `games` in `packages/re_engine/package.json`, with no new code (see [PACKAGES.md](../PACKAGES.md)).

## What the profile assumes

| | Value | Source |
| --- | --- | --- |
| Version | The DX11 build, before the ray-tracing update. Steam offers it as a beta branch of the game. | RE2's later ray-tracing build uses newer file versions, which this profile does not read. |
| Executable | `re2.exe` | |
| Archives | `re_chunk_000.pak` and its patch PAKs | as DMC5 |
| File list | `RE2_STM_Release.list` from the **Projects** folder of [REE.PAK.Tool](https://github.com/Ekey/REE.PAK.Tool) | as DMC5 |
| motlist, mot | 85, 65 | REE-Lib's `MotlistVersion.RE2_DMC5` and `MotVersion.RE2_DMC5` |
| mesh, tex, mdf2 | 1808312334, 10, 10 | REE-Lib-Resources |
| Space | Y up, metres, the RE Engine basis | as DMC5 |

## What may need work

- **Folders.** The adapter looks for animations in `natives/x64/animation/player` and `enemy`, and for models in `natives/x64/character/player` and `enemy`, by IDs such as `pl0100` and `em0000`. If RE2 keeps its characters elsewhere, the scan finds no characters and says so. The paths are in `wanted()` and `group()` in `packages/re_engine/__init__.py`.
- **Materials.** The texture slot names come from DMC5 (`BaseMetalMap`, `NormalRoughnessMap`, `AlphaTranslucentOcclusionSSSMap`). RE2 materials with other slot names import untextured, with their base color.
- **Skeleton.** The import uses the body mesh `<id>/<id>.mesh` as the skeleton. A character whose base mesh is named otherwise imports without a model and its rig has only the clip's own bones.

## To try it

1. Switch RE2 to its DX11 build in Steam: right-click the game, **Properties › Betas**, and choose the DX11 / non-ray-tracing branch.
2. Install the RE Engine package as described in [dmc5.md](dmc5.md), step 2 of *What you need*. Download `RE2_STM_Release.list` as described for DMC5 in [dmc5.md](dmc5.md), step 3 of *What you need*.
3. Add the game folder as a source and choose the list, as for DMC5.
4. Import one player clip with its character, check the scene as [VERIFICATION.md](../VERIFICATION.md) does for DMC5 (height, left side on +X, facing Blender's front, textures), and set `"verified": true` for `re2` in `packages/re_engine/package.json` when it passes. `tools\check_package.cmd` runs the same steps as the bridge and says which one fails (see [PACKAGES.md](../PACKAGES.md#testing)).
