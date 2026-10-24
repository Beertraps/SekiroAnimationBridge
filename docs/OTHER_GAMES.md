# Other FromSoftware games

The bridge handles Sekiro, Dark Souls: Prepare to Die, Dark Souls Remastered, Dark Souls III and Elden Ring PC files. The original project folder, commands and shortcut names are retained.

**Status (0.6.0):** HKX writing and read-back pass for all five games, and Blender scenes of Elden Ring and Remastered characters were retargeted and exported in both formats (VERIFICATION.md). No game playback has been run for the other games. This is a prototype to try with copies of assets.

## Use the UI

1. Close and reopen the bridge after updating. Existing Blender scenes can stay open.
2. Add a source: an unpacked game folder (Dark Souls III and Elden Ring keep their data in `Game`, Prepare to Die in `DATA`; choosing the folder above is enough) or a collected folder of archives. The game is detected; choose it in the source when it is not. Old saved catalogs need a new scan once.
3. Pick the character and one animation. In a collected folder, games sharing `c0000` have separate entries. The model, textures and material library fill automatically.
4. Player characters use **Player outfit / modular parts**. A lone piece per body region is selected automatically; competing outfits remain available for selection. Weapons are optional and initially unselected.
5. Check the textures and material library under **Textures & materials**, or turn off **Model** for rig-only work. Create a new `.blend` and edit normally.

## Files required

| Asset | Older MTD games / Sekiro | Elden Ring |
| --- | --- | --- |
| Animation rig | Base `cXXXX.anibnd.dcx` with `skeleton.hkx`, plus chosen animation archives | Same pattern; include split ANIBNDs and their compendiums |
| Player body | Outfit parts from `parts/*.partsbnd.dcx` | Outfit parts from `parts/*.partsbnd.dcx` |
| NPC body | `chr/cXXXX.chrbnd.dcx` | `chr/cXXXX.chrbnd.dcx` |
| Textures | Embedded TPFs, matching TEXBNDs, shared TPFs or extracted images | Same containers; MATBIN supplies the texture names |
| Material definitions | Usually `mtd/allmaterialbnd.mtdbnd.dcx`; explicit FLVER paths can work without it | **`material/allmaterial.matbinbnd.dcx`** |

`c0000.chrbnd.dcx` is a skeleton/socket reference without a visible player body in the supplied games. It cannot replace armor/body PARTSBND files. Texture package IDs can differ from model IDs.

Elden Ring retains an old MTD library, but its active assignments use MATBIN. The importer matches `.matxml`, `.mtd` and `.matbin` references by definition stem, includes samplers present only in the definition, and honors explicit FLVER texture overrides. Missing files are reported with the referenced texture names. It does not guess a different character's images or reconstruct unavailable textures.

An extracted folder of loose `.matbin` or `.mtd` definitions is accepted too. Put it inside the corresponding game’s assets folder and rescan. Only definitions actually used by the selected model are parsed. DS1’s `MtdPatch.mtdbnd.dcx` overrides its base `Mtd.mtdbnd.dcx` when both are beside each other.

Elden Ring’s `allmaterial_dlc01.matbinbnd.dcx` and `allmaterial_dlc02.matbinbnd.dcx`, when present next to the selected base `allmaterial.matbinbnd.dcx`, are included automatically. The `.devpatch.dcx` files are not material libraries.

Materials approximate base color, DirectX normals, alpha and emission. Layered/detail shader mixing, in-game lighting, cloth and equipment visibility are not reproduced fully. Weapons in DS1, DS3 and Elden Ring: **Auto** follows the WepAbsorpPosParam default row for any weapon. The main model goes to the right hand (dummy 20) and a scabbard to the opposite hip (dummy 30; in DS1 the `L_Wepon_Case` bone). Two-handed, sheathed states and per-model custom dummy lists such as `dummy:20,30` are also available. Extra models count as a scabbard when their bones name one (sheath, saya, scabbard, case) or for the known `WP_A_0201` scabbard; otherwise they are a paired weapon or an accessory. Replace older `dummy:20` overrides with **Auto**: a single dummy applies to every model and puts the scabbard in the hand.

## Native animation export

New scenes embed `game` and `sourceHavok` metadata. Blender export retains that metadata. The writer chooses the corresponding native version: HK2010 packfile (DS1/PTDE), HK2015 tagfile (Remastered), HK2014 packfile (DS3), HK2016.2 tagfile (Sekiro), or HK2018 tagfile (ER). Spline compression converts through a private HK2010 scratch file and returns to the source game's version. Since 0.6.0, `havok_compat.py` works around Soulstruct Havok 1.5.0 so that Dark Souls III packfiles get their section padding and member layout, and Elden Ring tagfiles their property bags and type names. Both formats write and read back for all five games; neither is new in-game evidence.

For an older scene, select its original game under **Export → Source game**, or re-import the original animation with 0.5.0. A new scene cannot be exported as a different game's skeleton by changing a dropdown. Retarget onto a scene imported from the destination game instead. The exporter still handles skeletal transform tracks only; additive clips, float tracks, TAE and unrelated HKX metadata are outside its scope.

The decoder needs rebuilding once for native packfile reading. Local dependencies have been updated on the development machine; fresh recipients run the included setup/build commands. Binder packing remains an external WitchyBND step.

CLI examples:

```bat
standalone\sekiro_animation_cli.cmd import -Game er -AssetFolder "D:\Assets\ER" -AssetClip "a000_004000.hkx" -BlenderExe "C:\Blender\blender.exe" -OutputBlend "D:\Work\ER-player.blend"
standalone\sekiro_animation_cli.cmd import -AssetFolder "D:\Games\ELDEN RING" -SourceLayout game -AssetCharacter c0000 -AssetClip "a000_004000.hkx" -BlenderExe "C:\Blender\blender.exe" -OutputBlend "D:\Work\ER-player.blend"
standalone\sekiro_animation_cli.cmd export -Game ds3 -InputBlend "D:\Work\legacy-DS3.blend" -BlenderExe "C:\Blender\blender.exe" -OutputHKX "D:\Work\edited.hkx"
```

For new scenes, omit `-Game` on export to use their embedded source game. In a mixed folder, use the unique clip ID emitted by `discover` if the filename occurs more than once.

## Supplied local examples

Read-only inventory: `work/other_games/input-inventory.json`.

- `Desktop/Test/Other Fromsoft Games/DS1` contains Remastered HK2015 animations, `c5370`'s model and skeleton-only `c0000`. The user added 9490 outfit PARTSBNDs, common TPFs and Mtd/MtdPatch libraries. Matching c5370-specific texture names still need the corresponding assets if absent from those packages.
- `DS3` contains HK2014 PC packfiles, `c5280`'s model and a TEXBND with 44 textures. The user added 5400 outfit PARTSBNDs and its allmaterialbnd MTD library.
- `ER` contains HK2018 animations, four full-detail 1690 outfit packages (plus low-detail copies), a weapon, and `c2190`'s model. The user added c2190 high/low TEXBNDs and the base/DLC MATBIN libraries. Those material definitions now resolve. Some referenced shared AAT textures are still absent.

The prepared folder scan found 15,952 clips in 47 animation archives, with six separate game/character entries. Actual material-reference inventory is in `work/other_games/material-inventory.json`: supplied base-color images cover 16/16 DS1 player slots, 21/21 DS3 player slots, 15/15 DS3 c5280 slots, 19/21 ER player slots and 14/26 ER c2190 slots. Some other c2190 materials are effect shaders without an albedo sampler. DS1 c5370 has no matching base-color textures (0/22 slots). These counts are file-reference coverage, not Blender appearance or animation/playback checks.

Remaining missing ER outfit base-color names include `AAT100_Metal_02_a`, `AAT500_Belt_01_a`, `AAT100_LeatherAlbedo_01_a`, and `AAT500_Hair_01_a`. NPC fur/hair also references shared AAT textures. Include the packages containing those exact names for a more complete material preview; neutral areas remain when assets are absent.

Keep one coherent source set per game folder. Sharing the parent folder is supported by game/character grouping; multiple conflicting copies of the same assets within a game should be separated or selected manually.

## Weapon attachment details

The HKX skeleton's name is not a character ID: DS1's c0000 player skeleton can be named `Master`. The importer now validates the actual animated bone names. It no longer rejects the player's weapon because of that string. A missing required bone still gives a matching-reference error.

DS1 uses the animation weapon bone directly, with the old-game right/left weapon orientation. DS3 uses authored FLVER dummy frames. Those conventions were read from the supplied reference models and [DSAnimStudio's weapon-transform implementation](https://github.com/Meowmaritus/DSAnimStudio/blob/master/DSAnimStudioNETCore/NewChrAsm.cs). Auto is a static preview choice from the default absorption row; it does not infer equipment/TAE states, paired-weapon events or per-weapon absorption rows.

The CLI attachment map also accepts per-member keys, e.g. `"wp_a_0201:1": "dummy:31"`. A per-member entry overrides the package-level entry. This is useful for an unknown package containing several independently attached models. Weapon-local rigs remain separate from the HKX/export skeleton.
