# 0.14.2 — import from other games: Unreal Engine

## Before the release

- The 201 unit tests in `standalone/tests`, the 9 RE Engine and 12 Unreal Engine package tests, and `node --check` on `app.js` and `preview.js` pass. Blender 4.5.14 with `--factory-startup` and `--python-exit-code 7` passes all twenty-two scripts and the three weapon scripts with `-- BODY`, among them `blender_panels.py` with the full-body bake's labels without *experimental*.
- The run of tag v0.14.0 (40971258230) stopped at *Test the release ZIP on a fresh profile*, before publishing, so v0.14.0 stays a tag without a release. The ZIP left out `.json` files, so installing the RE Engine package found no `standalone/schemas/package.schema.json`, and the example package that the unit tests use had no `package.json`. `tools/package_release.py` now ships `.json` files, and `test_package_release.py` checks that the schemas and the test fixtures are in the ZIP; it fails without the fix. A ZIP built locally the same way, with the decoder and the shared runtime, installs the RE Engine package into a fresh profile, its decoder is ready on the ZIP's runtime (9.0.22), and the 201 unit tests pass from the unpacked folder.
- The run of tag v0.14.1 (40972545864) got past the package install and stopped in the unit tests from the unpacked ZIP: the runner's temporary folder is `C:\Users\RUNNER~1\…`, the bridge resolves the catalog path to `C:\Users\runneradmin\…`, and `test_scan_inventory_selection_preview_and_prepare` compared the two. A run on main without a tag (40973182240) then found the same in the RE Engine package's scan test, and with the scratchpad's 8.3 short path as `TEMP` the Unreal package's detection and scan tests failed the same way locally. The tests now resolve their temporary folders. With the short `TEMP` and with the normal one, the 201 unit tests and the 9 RE Engine and 12 Unreal Engine package tests pass. Run 40973838655 on main then passed every step; without a tag it does not publish. The release is 0.14.2 from that tree, and v0.14.1 stays a tag without a release.

## Deep Rock Galactic, on the game's own files

Xbox app install (`C:\XboxGames\Deep Rock Galactic`), read only: one PAK archive (version 11, Zlib), Unreal Engine 4.27, not encrypted, no mappings file. The Unreal decoder 0.1.0, built from CUE4Parse `460fc477` and published self-contained with .NET 10.0.403, passes its self-test (17 checks). The first build had no CMake, so it had no native ACL library. CMake 4.4.4 and the Visual Studio 2026 Build Tools (18.11, C++ workload) were then installed with winget, and the script built CUE4Parse's native library from ACL v2.1.0 as CUE4Parse pins it: the self-test reports *Native ACL decoding: available*, and the dwarf's check below passes again with that build.

- `tools\check_package.cmd packages\unreal --source "C:\XboxGames\Deep Rock Galactic" --models --blender`: every step passed for both characters below. Detection names Deep Rock Galactic with Unreal Engine 4.27 from the package's entry, since the Xbox app executable cannot be read for the version. The first scan took about a second from `FSD/AssetRegistry.bin` and lists 227 characters, with 1792 animations, 1428 skeletal meshes and 360 skeletons in 109,806 files.
- The dwarf (`3P_Dwarf_Rig_Skeleton`, 523 clips) with `3P_ANIM_HeavyFront_RunForward_A`: 83 bones, 49 frames at 60 fps. In the scene the model is 1.19 m tall with its feet on the floor, its hands lie towards −Y (Blender's front) and its left eye is on +X. The skin shows the material's peach tint.
- The Glyphid (`SK_Spider_Skeleton`, 109 clips) with `ANIM_Spider_WalkForward_A`: 53 bones, 21 frames at 30 fps. The head lies towards −Y, the left legs on +X (+0.35 m on average, the right ones −0.47 m) and the feet on the floor; the body has its material's tint.
- Workbench renders from the front and the side show both characters upright, facing the front view, in the clip's pose.
- 19 more skeletal meshes, the models of every twelfth character in the list, export without errors with 8 textures.
- Defects found this way and fixed: Python 3.13 refused to search the executable through `mmap`, so it is now read in pieces; the crash reporter in `Engine/Programs/CrashReportClient` was taken for a game; the decoder missed textures that CUE4Parse files under fallback names, took the engine's placeholders (`DefaultDiffuse`) for textures, gave tint-only materials no color and kept the project name in texture paths (`FSD/Content/…` instead of `/Game/…`); the dwarf's skin showed a camouflage pattern (`T_Base_Tiger01`) that its base material holds in a parameter called just `Texture`, and now shows its tint.
- Library versions: NuGet's audit names Microsoft.Bcl.Memory 9.0.0 (GHSA-73j8-2gch-69rq) and SixLabors.ImageSharp 3.1.12 (six advisories) among CUE4Parse's pins. With Microsoft.Bcl.Memory 9.0.22 referenced by the decoder, the published `UnrealDecoder.deps.json` lists Microsoft.Bcl.Memory 9.0.22, SixLabors.ImageSharp 3.1.12, SkiaSharp 2.88.9 and the .NET runtime 10.0.14. The build script refuses runtimes before 10.0.4; its comparison was checked with 10.0.14, 10.0.4, 10.0.3 and a 10.0.0 preview. ImageSharp 3.2.0 stopped the build with *No Six Labors license found*. CUE4Parse encodes textures with SkiaSharp and uses ImageSharp only for landscape heightmaps, which the decoder does not export. After the change the self-test passes (17 checks, native ACL available), the dwarf's check passes again through Blender (83 bones, 49 frames at 60 fps), and the 19 sample meshes export again with 8 textures, all valid PNG files.
- `packages/unreal/tests` (12 tests), `packages/re_engine/tests` (9) and the 200 unit tests in `standalone/tests` pass.

## Star Wars Zero Company, on the game's own files

Steam install, read only: four IoStore containers (TOC version 8) with their three PAK files (version 11), none encrypted, Oodle compression, no Oodle library or mappings file in the game folder. The executable holds no engine branch name, so the source dialog guesses Unreal Engine 5.5 from the TOC version.

- A scan takes about 15 s. The asset registry lists 309 skeletons, 25,115 animations and 2876 skeletal meshes, but names no skeleton for the animations, so the decoder reads them from the package headers.
- `dump` of one animation shows why that fails: as 5.4 or 5.5 its header does not parse (*Read size is bigger than remaining archive length*); as 5.6 or 5.7 it parses, and CUE4Parse refuses the package because its properties have no names and no mappings file was chosen. The game needs a mappings file, which this computer does not have, so no clip was decoded.
- Defects found this way and fixed: the scan listed no characters and said *No animation sequences found*, because the skeleton lookup dropped CUE4Parse's reason. It now fails with that reason and what to do: with the guessed 5.5, choose another engine version; as 5.6, choose the mappings file. `global.utoc`, which CUE4Parse reads as shared data and never mounts, was reported as an archive without its AES key.

Not checked: Unreal Engine 5 imports; IoStore archives, AES keys, mappings files and an Oodle library with a real game (made-up files only); ACL-compressed clips, since no game here with them can be read without a mappings file; the Steam version of Deep Rock Galactic; retargeting an Unreal clip onto a Sekiro character; Blender renders other than Workbench. Many Deep Rock Galactic props mix two tints through a pattern texture in the material graph; the scene shows the pattern instead.

# 0.14.2 — import from other games: Devil May Cry 5

## Game packages

- `test_adapters.py` (23 tests), with the example package from `standalone/tests/fixtures/packages`: built-in and package games have unique IDs and only FromSoftware games export; `games.json` lists packages and bone names; every engine serves the bridge's entry points; broken JSON, a newer API version and a game ID that is taken are listed with their reason while the rest loads; the bridge folder wins over an installed copy; a module without the API functions is refused when used; scan, inventory, selection, preview and prepare through the package API, with results checked against the schemas; a stored scan of another folder is refused; a missing tool names its build script, and `ctx.run` returns a tool's output and reports its last error line; ZIP install, replace and remove, and ZIPs with `..` paths or two `package.json` are refused; the UI server lists, inspects, installs (only after confirmation) and removes packages; the checker passes every step for the example package and stops at the module of a package without the API.
- `packages/re_engine/tests` (9 tests): the RE Engine package through the package API with a stand-in decoder, as the RE tests in `test_adapters.py` did before.
- `test_dotnet_runtime.py` (7) and `test_package_game_package.py` (7): finding and configuring the shared runtime, and building package ZIPs.
- The RE Engine decoder built framework-dependent runs on the runtime prepared by `tools\prepare_dotnet_runtime.cmd` (.NET 9.0.22); `COREHOST_TRACE` shows `hostfxr.dll` and `coreclr.dll` loaded from it. A release ZIP built with `--dotnet-runtime` is 48.8 MB and its unpacked decoder runs on its own `dotnet-runtime`.
- **Real DMC5 files from the package ZIP.** `tools/package_game_package.py` built `AnimationBridge-package-re_engine-0.1.0.zip` (22 files, 1.5 MB), and `install_zip` put it into an empty packages folder. `tools\check_package.cmd` on that folder, with the Steam install, `DMC5_STM_Release.list`, `--character pl0100 --clip pl0100_Idle_Normal --models --blender`: every step passed. Detection counts 471 motlists, 288 meshes and 1040 mdf2 files; the scan lists 47 characters; Dante has 968 clips, 855 ready; the preview has 89 bones and 259 frames at 60 fps; the Blender scene has 3 parts, 32 textures, 127,260 vertices and 173,258 triangles, with the same 14 coat and shoulder helper bones noted. The scan used the cache of earlier runs.

- **Setup page**, on a copy of the bridge with a throwaway profile, in the desktop app's browser: the card lists the example package as *BRIDGE FOLDER*; the install dialog for the RE Engine ZIP shows package, games, tool, authors, license, homepage, 22 files and 4 MB with the warning; **Install** adds *RE Engine 0.1.0* with **Remove**, the card *RE Engine decoder: READY* (on the system .NET 9.0.22) and Devil May Cry 5 to the source dialog's games; **Remove** asks again, deletes the folder and takes all three away. The Windows file dialog was not used: the page received the ZIP path directly.
- 196 unit tests, the 9 package tests and `node --check` on `app.js` and `preview.js` pass; Blender 4.5.14 with `--factory-startup` passes all 22 scripts.

Not checked for packages: the release workflow's runtime and package steps, which run only on GitHub; a retarget onto Wolf after the move (the Blender side did not change and its tests pass).

## Registry, adapters and source spaces

## Registry, adapters and source spaces

- `test_interchange.py` (13 tests): the motion, manifest and preview schemas accept the bridge's own documents of versions 1, 2, 4 and 5 and reject broken ones; `Space` maps vectors, quaternions, scales and matrices both ways, and the FromSoftware space gives the 0.13 Y/Z swap exactly.
- `test_adapters.py` (15 tests), with a stand-in decoder and a made-up natives tree: the registry's IDs, engines and capabilities; `games.foreign()` sends RE Engine catalogs, selections and motions to the RE adapter and keeps FromSoftware documents; detection of a natives folder by file versions (chosen as the folder, `natives` or `natives/x64`) and of a game folder by `DevilMayCry5.exe` with its PAKs in patch order; scan, inventory, selection (body, first head, first hair) and decode through `asset_discovery`; loose files replace packed ones; DMC5 material slots, Null textures, hidden eye layers and channel-packed alpha; requests with unknown games, export of import-only games and sampled RE Engine clips are refused.
- `test_retarget_mapping.py`: the new RE Engine naming fixture (`humanoids.re_engine`: `Hip`, `Waist`/`Stomach`/`Chest`, `L_Shin`, `L_IndexF1`, a palm bone, `_SS`/`_SR`/`_offset` helpers) pairs every core bone and finger with every other convention, and its body is found by name.
- `blender_source_spaces.py`, new: on 200 random samples, `game_to_bl_trs` and `bl_to_game_trs` give the 0.13 results exactly. An RE Engine clip, and one with `unitScale` 0.01, import with bone rests and poses equal to `C · M · C⁻¹` within 1e-4, root motion in the source's space, and export with the same frames, root motion and basis. A version 5 manifest builds its mesh in the RE space without reversed winding, its model-only bone from quaternions, no bind adapter for a matching bind pose, `Devil May Cry 5 / …` materials, an opacity texture channel, a fixed opacity and channel-packed alpha.
- All 171 unit tests pass in the writer environment, and Blender 4.5.14 with `--factory-startup` passes all 22 scripts.

## Devil May Cry 5, on the game's own files

Steam install, read only, with `DMC5_STM_Release.list` and the RE Engine decoder 0.1.0 built from REE-Lib `383be0b`:

- Detection takes 0.2 s and counts 471 motlists, 288 meshes and 1040 mdf2 files listed in the PAKs. The scan lists 47 characters, among them Nero, Dante, V, Vergil, Lady and Trish. Reading Dante's 29 motlists gives 968 clips, 855 of them with bone animation, in 4.8 s. The preview of `pl0100_Idle_Normal` has 89 bones and 259 frames at 60 fps.
- Import of `pl0100_Idle_Normal` with body, head and hair: 127,260 vertices, 173,258 triangles and 32 textures; 36 s the first time, 14.5 s once the files are in the cache. The rig has 458 bones: the body's 339 and 119 that head and hair add. No part needed a bind adapter. The decoder notes 14 coat and shoulder helper bones that the clip animates and the body mesh lacks.
- In the scene: 1.93 m tall with the hair, the `Head` bone at 1.74 m; the `L_` bones lie at +0.215 m X on average and the `R_` bones at −0.198 m, so the character is not mirrored; toes point to −Y, Blender's front; the body's face normals point outward. An EEVEE render shows the red coat, skin, gloves, boots and white hair. Before `packedAlpha`, every non-metal surface rendered black, because the ALBM alpha (metalness) acted as opacity of the color.
- Retarget: Wolf (`c0000`, `a000_000000`) from the Sekiro install with Dante's idle as the donor imports in 21.7 s. **Match bones automatically** pairs 56 of Wolf's 114 rows, body and fingers (32 before the RE finger names were read). The bake keeps upper arm, forearm, thigh and shin directions equal to Dante's on every 16th frame (0.00°), and the spine-to-neck line within 3.5°. The add-on's export gives Sekiro motion JSON (version 1, no basis) with 259 frames at 60 fps and 114 tracks; the bridge wrote it as interleaved HKX and read it back with at most 2.4e-6° rotation error.
- Exporting the DMC5 scene itself stops after sampling with the message that the bridge cannot write DMC5's format and should retarget first.
- Two defects found this way and fixed: the add-on's bake stopped on an unmapped finger (`None in source.data.bones`), and a DMC5 donor had no `animation` path for the same-clip check.

Not checked: game playback of the retargeted HKX; DMC5's normal-map green direction (DirectX assumed; the render looks right but was not compared with the game); mirrored clips; enemy models; an extracted natives folder with real files (synthetic only); Resident Evil 2; the release workflow's new decoder step, which runs only on GitHub; the UI beyond `node --check` and the API checks listed in the commit.

# 0.13.0 — export into the animation binder, join animations, Wolf's katana, alternate model meshes, and c1070 skin

## Export into the animation binder, Join animations, Animate tab

- `test_binder_members.py`, new, on BND4 binders built with Soulstruct: parsing and writing keeps every member, name and ID, puts data on 16-byte boundaries and is idempotent; the path hash table finds every member; a member of the same name is replaced and the others are unchanged; a new name gets its ID (`a050_300000.hkx` is 1050300000), its clip's folder and its place in ID order, or the most common clip folder; names that are not `aXXX_YYYYYY.hkx` and binders whose clips do not follow the ID scheme are refused; `.bak` is made once; the export request refuses other suffixes, bad names and binders in the game folder, and the member defaults to the clip's name. All 135 unit tests pass in the writer environment.
- Rewriting each of the 34 Sekiro `.anibnd.dcx` of the game folder, decompressed, gave identical bytes (read only).
- CLI export on a scene imported from the game folder: with `-Binder` naming a new path beside the HKX and `-BinderMember a050_999000.hkx`, the binder was made from the game's `c0000_a05x.anibnd.dcx` with 181 members instead of 180, the new one equal to the HKX, the others byte for byte. A second export with the clip's own name replaced `a050_002000.hkx` and made one `.bak`. Every member's data starts on a 16-byte boundary. The game's archive was not written.
- `blender_join.py`, new, on owned synthetic bridge clips of five bones (20 frames and 15 frames at 30 fps, and 29 frames at 60 fps): **Load clip from .blend** brings in the second clip and its root motion, paired by name where Blender numbered both, without objects or metadata; with a 0.1 s blend the joined clip matches the first clip on frames 1-17 and the second on 21-32 within 1e-4 and eases between them on 18-20; the root goes on from frame 18 without a jump; the export has 32 frames with root motion; blend 0 starts the second clip on frame 21; the 60 fps clip spans 14 scene frames and warns; the refusals work.
- `blender_panels.py` checks both tabs, that a child panel is in its parent's tab, the Log at the bottom of each, and the new states *Join chosen* and *Joined, export to a binder*. Blender 4.5.14 with `--factory-startup` passes panels, join, mirror, control_rig, fixes, export_options, retarget, two_characters, synthetic_check and part_animations.
- Before the 0.13.0 release: the 135 unit tests and `node --check` on `app.js` and `preview.js` pass. Blender 4.5.14 with `--factory-startup` and `--python-exit-code 7` passes all twenty-one scripts and the three weapon scripts with `-- BODY`.
- Not checked: game playback of a joined clip or a binder written this way, a new member with a TAE entry, and the panels in Blender's UI beyond the drawn outline.


- Collapsible mesh group panel: checked that the native disclosure starts closed, remains open while changing choices, and closes when selecting another model.
- `blender_mesh_groups.py`: owned geometry imported as one legacy mesh and four NPC group objects, both directly on the character rig and through one shared bind adapter. The split retains every vertex (including a loose weighted vertex), face, weight, material index, UV layer and custom normal. Evaluated skin, weapon/finger/torso geometry, mirror skin relationships, both retarget bake methods and generated controls match the combined mesh. Hiding one object leaves the other groups visible and animation export unchanged. Existing two-character import, weapon-location and part-animation Blender checks also pass.
- Real Resurrection `c1070` Juzo import: 45,518 vertices split into **Shared meshes** (5,606), **#09 juzo rope** (6,847), and **#10 juzo hakama top** (33,065), driven by the same bind adapter. Compared with the previous combined scene, deformed vertices differ by 0 at frames 1, 85 and 170; all 170 exported animation frames and root motion match exactly. Group `09` hides independently without changing export. The add-on's **Append source .blend** command loads all three objects and the adapter, with target export unchanged. Local scene and reports: `work/mesh_groups_verification`.
- Follow-up on cross-ID NPC models: a vanilla `c5400` `a000_003000` animation imported with `c5410.chrbnd.dcx`, retaining the `c5400` animation skeleton. The resulting Blender scene has 91 frames, 199 mapped tracks, a 49,693-vertex `c5410` model, 17 textures and no notices. The source picker lists 128 NPC model IDs, defaults to `c5400`, and includes `c5410`. This checks the bridge import, not how that pairing looks in game.
- Owned fixture checks: the default Wolf scan and source selection include `wp_a_0300` when present and do not report it missing when absent; mesh mask filtering keeps material indices aligned with the chosen geometry; the Sekiro stencil skin sampler chooses slot 7 over tiling detail slots 1 and 2 and ignores a damage normal in an emissive-named slot.
- On the user's Resurrection source, read only: `c1070.chrbnd.dcx` contains Juzo groups `09` and `10`, Shige group `11` and armor groups `20`–`24`, plus separate prop groups. A full import of `a000_003017` with Juzo groups `09` and `10` made a 170-frame Blender scene with 45,518 vertices, 50,598 triangles, 14 materials, 19 packed texture images and no notices. Its body material links packed `c1070_skin_a` at UV 0 and scale 1; no Shige materials remain. A Cycles render shows the dark body texture, while the prior render with `c1070_skin_damage_n` in emission was pale white. The scene and render are in `work/texture_review`; in-game appearance is not checked.
- Preparing Shige groups `11` and `20`–`24` from the same source and shared texture folders made 75,177 vertices, 82,519 triangles, 30 materials and 22 images with no notices. This confirms that the same FLVER can produce a distinct second appearance from the same animation.

## Body figures and Biped-style feet, jumps and props

- `blender_biped_options.py`, new, on owned synthetic rigs. The source has base proportions and stands with its knees bent 5 cm. Its left foot rolls 25° onto its ball and back with the toes flat and 2 mm of jitter. Its right foot slides 20 cm outward. It jumps 30 cm with both feet off the ground for twelve frames and throws a prop 60 cm from its right hand. The target has legs 0.85 as long, thighs at 0.6 of the leg, a two-bone spine, arms 0.9 and 1.25, its toes 8 cm further forward, and a prop of its own.
  - Figures: **Create figure** puts the Pelvis, Thighs, Calves, Feet and Hands on their joints within 1e-6 and links each to its bone; the Heel lies behind the ankle and the Toe's tip ahead of the ball. A part linked to a missing bone is refused with its name and nothing is saved. With the Head raised 25 cm, the saved figure measures the height 25 cm more and the leg the same. It is kept on the rig and in one file named by the skeleton signature, found through the folder for a second rig of the same skeleton but not for the source, kept after **Close figure**, and deleted with its file by **Delete saved figure**. The report gives `figures == [False, True]`. While a figure is open its rig is in Rest Position and **Bake** refuses with the rig's name; saving or closing it, also after opening it twice, gives the rig back its earlier pose position, also where that was Rest Position.
  - *Planted, sliding, free*: the target's left ball (toe head) stands still within 0.000 mm through the roll, against 5.7 mm with *Slow feet stand*. The slide's fast middle is found as sliding (frames 17 to 20), and the right ankle stays within 0.001 mm of its height before the slide. No frame's ankle step exceeds the default contacts' by more than 1 cm.
  - Jumps: with **Scale jumps by height**, the target's hips rise above the line from lift-off to touchdown as the source's times travel times the ratio of the heights, 1.224, within 1e-4 on every frame in the air: 31.1 cm where leg length alone gives 25.4 cm. Without the option, they rise by travel alone within 1e-4.
  - Moving props: with both bake methods, *By height* and *By limb size* put the target's prop from its hand as far as the source's, scaled by the heights (1.043) or the right arms (1.065), within 0.01 mm on the throw's frames; *Keep target place* keeps its rest offset within 0.01 mm and reports no props.
- The test changed the design in three places before it passed:
  - Planted points first stood where the source's points were, scaled. The target's foot is 22.6 cm from ankle to ball against the source's 14 cm, scaled to 12 cm, so standing still moved the target's foot up to 8.6 cm from the scaled footprint. Now a planted point of the target's own foot stays where the foot's goal carries it on average over its stretch, at the source point's height.
  - A foot-rigid toe tip went 3.5 cm into the ground as the foot rolled on its ball and planted itself against the ball, which drifted 10.8 mm. A point now counts as planted only while it is on the ground, and the toe tip rides on the toe bone where both feet have one.
  - The rest stance tilts the target's longer foot 10°, so its four points cannot all touch the ground. Planted frames took the mean of their heights and sliding frames the lowest source point, 13 mm apart. Both now stand as high as the target's lowest point needs.
- With every option off, `blender_full_body.py` gives the same numbers as before. Blender 4.5.14 with `--factory-startup` and `--python-exit-code 7` passes all twenty scripts and the three weapon scripts with `-- BODY`. The 124 unit tests pass in the bridge's writer environment.
- Not checked: real motion capture or game clips with the new options, a skinned target's figure fitted from its meshes, and the panel in the Blender UI beyond its operators.

# Unreleased — the fist holds the weapon's matching part — 2026-10-26

- `blender_weapon_grips.py`, with both bake methods:
  - The plain box blades of the existing checks now lie on the source's grip line in the palm, scaled, within 0.0005 mm and 0.0000°, held where the source's fist holds in proportion to the two blades' lengths. The curved blade turned 130° lies in the palm as the source's within 0.0000° for the flat side and 0.02° for blade and curve (0.21° before).
  - New: a sword with a guard, a spear with a head and an axe with a head on one side of its handle, each with its bone 1.2 cm off the handle and at another place along it than the source's, and other proportions. With the source's grip, the gripped part lies on the source's line in the palm within 0.002 mm and 0.0000°, and the fist holds within 0.6 cm of the place in proportion between the features: pommel and guard, butt and head, butt and axe head. The spear's bone lies nearer the butt on the source and nearer the head on the target; it comes out head to head.
  - New: a target weapon without a long axis (a cube) keeps the bone's place, within 0.0003 mm of where the source's bone sits, scaled, with the former status text.
- Isshin's c5400_a000_003024 on Wolf, from the user's scene in the background without saving, with the scene's options (source's grip, the raw defaults):
  - Before: Wolf's hilt line 1.49 cm from Isshin's in the palm, scaled to Wolf's hand; the fist 8.9 cm from Wolf's guard.
  - After: 0.17 to 0.25 cm and 0.82 to 0.86°, depending on how the probe fits a whole hilt's line (vertex average or slice middles); the fist 6.5 to 6.6 cm from Wolf's guard, against Isshin's 11.1 cm from his on a hilt 1.5 times longer. Close-up renders of the fist on frame 51 show the hilt through the fist where it lay over the fingers before.
- Isshin's c5400_a000_003024 on Owl (c5060_a000_000401_from_c5400_a000_003024.blend, rigs chosen and bones matched as the panel does, since the saved file had none; source's grip, the raw defaults), frame 89, with the add-on as committed and as changed:
  - Committed: the odachi is placed, not gripped; the fist 4.6 cm past the guard, on the blade; the hilt line 6.70 cm from Isshin's in the palm, scaled, and 6.72° off.
  - Changed: R_Katana takes the source's grip by the matching part, 1.9 cm along from its bone; the knuckles 1.85 cm along, 13.8 cm below the guard by the outline (Isshin's 11.3 cm); the hilt line within 2.65 cm and 1.75° of Isshin's, as the probe fits a line through the whole hilt, which bends 8.5° against the odachi's long axis. Before the widest-part anchor, the match put the fist 111.2 cm up the blade.
  - Wolf's scene, rebaked with both: unchanged, 0.17 cm and 0.82°.
- `blender_weapon_grips.py`, with both bake methods: a weapon resting 0.85 m from the hand takes the source's grip and sits in the hand as one resting there within 0.0007 mm and 0.03°, with the source's grip and where the own clip hides it.
- `blender_weapon_hands.py`, with both bake methods: the spear resting 1.5 m from the left hand takes the axe's grip in the left palm, scaled, within 0.001 mm and 0.0000° by the bones without an axe mesh, and lies on the axe's line within 0.001 mm and 0.0000° with one; in the world it lies within 1.66° of the axe, as the two palms turn a little otherwise (it was checked within 1° of the axe in the world before). The katana taking the axe from the other hand keeps its place.
- Fit the weapon to the fist, on a copy of the user's Isshin-on-Wolf scene, rebaked with its options; finger skin (vertices that each finger bone moves most, from the deformed body mesh) against R_Weapon's mesh with the guard left out, over 12 frames, as share of skin inside and nearest skin (negative inside):
  - Before (committed d83e2d7): thumb 11%, index 19%, middle 59%, ring 44%, little 21%; palm 0%.
  - Hand alignment, no fit: thumb 26% (-1.8 cm), index 3%, middle 46% (-2.1 cm), ring 29% (-1.3 cm), little 3%; palm 0%.
  - Fit (default): thumb 1.1% (-0.09 cm), index 0% (+3.2 cm), middle 1.6% (-0.06 cm), ring 0% (+0.8 cm), little 0% (+2.6 cm), palm 0% (+0.6 cm).
  - Cost weights compared on the same scene: without the gap term, nothing goes in but the index and little fingers stand 3.9 and 4.0 cm off and the middle 1.1 cm; a gap term without the palm pulled the hilt 4.5 cm off the palm; with the palm counted, a gap cost of 0.05 gave the numbers above, 0.1 and 0.3 pushed the thumb 0.4 and 0.7 cm in.
  - Finger bend on top: thumb 0.7%, middle 0% (+0.8 cm); index and little stay 3 cm off, beyond the quarter hand length within which fingers close.
  - The first approach, bending the fingers instead of moving the weapon, left thumb 0%, index 0%, middle 0.4%, ring 7%, little 3%; the user preferred keeping the fingers: "Ideally we do this without changing the fingers, I could find a sword position (no rotation) that made it look way better."
  - `blender_weapon_grips.py`, both methods: a skinned synthetic hand on a hilt too thick for its fist; the weapon moves 1.9 cm across the palm, by one move without turning (within 1e-6 and 1e-3°), the fingers keep their pose within 1e-4°, and the skin goes 4.8 -> 0.6 mm into the hilt.
- Weapon in hand (manual alignment): on a copy of the user's Isshin-on-Wolf scene (c0000_a000_000000_from_c5400_a000_003024), adjusted on frame 40, R_Weapon turned 12° and lifted 2 cm, applied: on frame 40 the weapon sits in R_Hand as posed within 0.0000 cm / 0.0000°, and on all 106 frames as the change times the plain bake within the same; Reset gives the plain bake back within 0.0000 cm / 0.0000°. The status note gave 4.0 cm and 12.0° (the turn about the weapon's head moves it in the hand's space).
- Rest-relative grip: `blender_weapon_grips.py`, bone by bone and full body: R_Weapon stays at the own clip's grip point within 0.0006 mm and turns in the hand as the source's katana turns from the rest poses within 0.0001°; the fingers keep the source grip's within 0.05°. On a copy of the user's Isshin-on-Wolf scene (c0000_a000_000000_from_c5400_a000_003024), baked with the grip, against the user's Rokoko retarget of the clip (a000_000000.hkx, 34 frames, imported onto Wolf by the bridge): R_Weapon in R_Hand within 1.4° and 0.00 cm on all 34 frames; the Source's grip bake of the same scene sat 2.8 cm and 39.7° from it. Rokoko's world-rotation copy, recomputed from both rigs' rest poses and Isshin's clip, matches that HKX within 1.5° for R_Weapon, R_Hand and R_Finger1. Close-up renders on frames 1 and 17 show the Rokoko clip and the new grip alike.
- Rest-relative grip as the default, the hilt shift removed: `blender_weapon_grips.py`, bone by bone and full body: a new scene bakes with the rest-relative grip and finger bending off; on a target with finger skin and a hilt too thick for the fist, **Bend fingers onto the weapon** takes the finger skin from 2.4 to 1.6 mm deep with the source's grip and from 33.4 to 11.6 mm with the rest-relative grip, the weapon kept where the grip puts it within 1e-6; the thumb's tip lies across the hilt there, so it stays partly in. `blender_weapon_clearance.py` now bakes with the source's grip, as its two swords lie along different bone axes, which only the source's grip lines up. Blender 4.5.14 with `--factory-startup` passes every script, both bake methods where they apply; `blender_fixes.py` prints its expected Error lines.
- Rest-relative fingers: `blender_weapon_grips.py`, bone by bone and full body, with *Match source stance*: under the rest-relative grip every finger of both hands turns in its hand as the source's turns from its rest pose, within 0.05°. On Isshin's c5400_a000_003024 on Wolf against the full Rokoko clip, 106 frames, the fingers lie within 0.5° (left) and 1.2° (right) of Rokoko's at the median, 1.1° and 1.7° at the 90th percentile, where they were 5.3° and 6.0°; hands and arms are unchanged.
  - `blender_weapon_grips.py`, both methods: aligned on frame 7, every frame within 3.1e-07, also after a later bake, Reset within 5.4e-09. `blender_panels.py`: two new states, posing and aligned.
  - Grip checks on the same scene, right hand's knuckle middle from the hilt line, median over 106 frames: 5.1 cm with the committed add-on (d83e2d7), the user's saved bake and the working copy alike (Isshin's 5.0 cm, scaled); left hand on the two-handed frames 7.7 cm committed, 1.6 cm now.
- Hands together on a hilt (full body), rebaked from a copy of the user's Owl-on-Isshin scene (c5400_a000_003000_from_c5060_a000_003008) with its options; over the 27 frames where Owl's left knuckles sit on his hilt line, median distance of Isshin's left knuckles from Isshin's hilt line (Owl's from his, scaled to the hand: 3.1 cm):
  - Before: 8.7 cm (bone by bone 23.4 cm). With the step at full strength where the source holds with both hands: 7.1 cm. With the knuckles kept apart instead of the wrists as well: 6.2 cm. Second hand on the weapon: 2.2 cm.
  - Isshin's hilt line at the left hand's place, in the right palm, runs within 0.2 cm of Owl's there (scaled), so the hilt is not the cause; bone by bone, the left arm turns within 1° of Owl's on frames 22, 35 and 51.
  - The whole Blender suite passes, the three weapon tests with both bake methods.
- Hand alignment (*Match source stance* lines up each hand from wrist to knuckles and about that line), rebaked from the user's scenes with their options and from copies with rigs set and bones matched; palm and blade in the world against the source's, over 14 sampled frames:
  - Isshin's c5400_a000_003024 on Wolf: palm 9.8° before, 0.0° after; blade 4.9° before, 1.6° after; blade in the palm 1.60° both.
  - Isshin's clip on Owl: palm 9.7° before, 0.0° after; blade 4.8° after (Owl's hilt bends 8.5° against the odachi, Isshin's 3.5°; the bake lines up the hilts).
  - c7110's a000_003022 on Wolf (full-body bake): palm 9.2° before, 0.0° after; blade 8.0 to 10.7° before, 1.6° after.
  - Isshin on Wolf and on Owl in the palm: unchanged, hilt line 0.17 cm / 0.82° and 2.65 cm / 1.75°.
  - `blender_weapon_grips.py`, both methods: the target whose fingers sit 15° about the knuckle line from the source's now turns its palm as the source's within 0.05° and its blade within 0.5° in the world; with *Keep target stance* the blade still turns away with the palm (over 5°).
  - The whole Blender suite passes, the three weapon tests with both bake methods.
- After the Owl change: the whole Blender suite passes, with `blender_weapon_grips.py`, `blender_weapon_hands.py` and `blender_weapon_clearance.py` run with both bake methods and `blender_fixes.py` on its own. Of the unit tests, 82 pass and 18 could not import `soulstruct` in the shell's Python at the time; none of them covers the retarget add-on's weapon code.
- The whole Blender suite, the add-on's unit tests (121) and `blender_weapon_clearance.py` and `blender_weapon_hands.py` with both bake methods pass. `blender_fixes.py` passes on its own and is flagged only when run in the batch, as before.
- Not checked: Owl onto Isshin and other pairs; Owl's odachi in the game; how the aligned hands look in the game, and c1070's weapon, whose mesh weighted to R_Katana holds a sparse curved blade and a part below the pommel that reads as its widest; how the looser fist around a thinner hilt looks in the game.

# Unreleased — raw bake by default — 2026-10-26

- The 121 unit tests and `node --check` on `app.js` and `preview.js` pass. Blender 4.5.14 with `--factory-startup` and `--python-exit-code 7` passes all eighteen scripts and the three weapon scripts with `-- BODY`.
- The first run with the new defaults failed only `blender_weapon_grips.py`, with both methods, on `AssertionError: ('SOURCE', 1.0)`: it expected the target's own grip from the default. It now asserts a new scene's defaults (*Source's grip*, **Blade follows source** 100%, **Second hand on the weapon**, **Keep hands out of the body** and **Keep arms close to the body** off) and bakes once with them: no second hand, and `R_Hand` and `R_Weapon` posed as in the later bake with *Source's grip* chosen, within 5.1e-09 m (4.6e-09 m with the full body), turns counted as 1 mm per degree. With the own grip and the second hand set, its other numbers are as before the change with either method: own grip within 0.0004 mm and 0.0000°, left hand on the hilt on frames 15–46.
- The other seventeen scripts passed unchanged.
- A scene saved in background Blender with the previous add-on, with **Clip timing** and **Keep arms close to the body** set by hand, opened with the changed add-on: *Source's grip*, **Second hand on the weapon** and **Keep hands out of the body** off, **Keep arms close to the body** on, **Clip timing** kept. The scene was synthetic and saved outside the repository.
- Not checked: the panels in a live Blender window.

# Unreleased — full-body bake, experimental — 2026-10-26

- The 121 unit tests pass; 5 are new in `BodyTemplate` in `test_retarget_mapping.py`:
  - `characterize()` finds the hips, head, neck, both spine ends, both arms and legs and every finger segment on the 15 rig conventions, the 6 scrambled rigs and two new rigs of other proportions with and without names. Its list of parts found by shape is empty exactly for the named rigs.
  - In a rig without clavicles, with a twist bone in series in each upper arm and scrambled names, the upper arm stays an upper arm. The matcher alone takes it for a clavicle.
  - `body_pairs()` spreads a three-bone spine over two bones (the lower one spans Spine and Spine1, chest pairs with chest), puts a twist bone 40% down the upper arm at 0.40 between upper arm and forearm, leaves the source's clavicles unpaired, pairs Mixamo with the Elden-style rig one to one, and finds no body in a rig without legs.
- Blender 4.5.14 with `--factory-startup` passes all eighteen scripts, `blender_full_body.py` new. `blender_weapon_locations.py` needs an output folder after `--`, like `blender_weapons.py` and `blender_part_animations.py`. `blender_weapon_grips.py`, `blender_weapon_hands.py` and `blender_weapon_clearance.py` also pass with `-- BODY`, which bakes them with the full body: the own grip holds within 0.0004 mm and 0.0000°, the katana follows the axe within 0.002 mm (0.001 mm bone by bone), and the blades point within 0.000°. `node --check` passes on `app.js` and `preview.js`.
- `blender_full_body.py`, new. A Mixamo-style source under an FBX transform squats 18 cm with both feet planted, bends its spine 20°, brings its hands together in front of the chest (5 cm apart on frames 9–27) and steps 25 cm forward with its left foot, over 40 frames. Two owned targets take it, both with matched rest stances and no root motion: *twisted* has a two-bone spine, no clavicles, twist bones in series in arms and legs, legs 0.85 as long with long thighs, long forearms and a 40° A-pose; *tall* has a four-bone spine, legs 1.2 as long with short thighs, hip joints closer together and short forearms. Each is baked bone by bone from the matched list and with the full body. Feet and hands in cm, directions in degrees, each on its worst frame:

  | target | method | slide | worst frame | float | width | hands | spine | arms | legs | elbows | knees |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | twisted | bone by bone | 29.00 | 1.47 | 1.85 | 0.00 | 5.18 | 2.35 | 0.00 | 0.00 | 0.00 | 0.00 |
  | twisted | full body | 0.00 | 0.00 | 0.01 | 0.00 | 0.00 | 0.00 | 3.18 | 12.85 | 3.60 | 0.00 |
  | tall | bone by bone | 29.23 | 1.46 | 1.83 | 0.00 | 2.73 | 0.78 | 0.00 | 0.00 | 0.00 | 0.00 |
  | tall | full body | 0.00 | 0.00 | 0.01 | 0.00 | 0.00 | 0.00 | 1.94 | 8.85 | 1.94 | 0.03 |

  - slide: how far the target's feet move in all on the frames where the source's foot stands still; worst frame: the most on one frame; float: how far a planted foot rises or sinks from its rest height; width: on frames where both of the source's feet stand, how far the target's feet are apart sideways against the target's own hip-joint distance plus the source's spread beyond its own, scaled; hands: how far the wrists are from the source's contact scaled by arm length, where the source's are within 0.6 forearm; spine: the chord from the first spine bone to the neck against the source's; arms and legs: each limb bone's direction against the source's; elbows and knees: the plane each limb bends in, where the source's bends by 10° or more.
  - Before the hip width (commit e7bcc62, measured with the same test), the full body's feet stood 3.00 cm (*twisted*) and 12.00 cm (*tall*) off that width, the legs pointed up to 12.81° and 9.01° away, the knee planes 1.63° and 4.57°, and the pelvis dropped by up to 0.12 cm on *tall*. Now it does not drop on either target. The test asserts width under 0.05 cm, legs under 15° and knee planes under 1°.
  - The full body's 0.01 cm float is a constant offset, not motion: the synthetic feet sit 2 cm forward of the hips whatever the leg length, so the travel scale, measured from the hips to the feet, differs from the ratio of heights by 0.01%.
  - A copy of *twisted* with scrambled bone names and no bone list bakes the same pose as the named one, within 1e-5 m and 0.01°, and the status lists hips, spine, neck, head, arms, legs and fingers as found by shape.
  - Root motion: the same clip on a source whose root-motion object carries the hips' 12.5 cm travel forward and turns by 30° over the clip, while the rig keys the rest, so that root and rig together put every bone where the clip without root motion does. Baked onto *tall* with **Root motion** > *From source*, the target's body bones land, where the game puts them, within 0.004 mm and 0.001° of the bake without root motion, so standing and the hip width are measured where the game puts the feet.
  - `fullbody.held()` on a pelvis that turns 8° over a first stand, swings 80° one way and 160° back while the foot steps, and turns 8° over a second stand: the direction holds still at each stand's mean, stays within 4.0° of the pelvis's direction between, which is its offset at the ends of the stands, and steps by no more than the pelvis does plus 1°.
- `blender_panels.py` draws 14 states, two of them new: with *Full body (experimental)* and no bone list, **Bake motion onto target** is available and the experimental note shows; after the bake, the status reads "Baked 24 frames from the full body" with the weapon in Wolf's hand placed as before.
- Read-only trials in background Blender, with the scenes not saved; renders of both bakes next to the source were kept outside the repository. Feet are measured where the game puts them: each rig's pose, turned and scaled like the rig but not moved by it, then moved and turned by its root-motion object; both pairs take the source's root motion. A source foot counts as standing where it moves less than 2 mm from one frame to the next. Width: the target's feet apart sideways, along the level line through its hip joints, against its own hip-joint distance plus the source's spread beyond its own, scaled. The full body was baked with this branch and with commit e7bcc62, before the hip width; bone by bone gives the same numbers with both.

  | pair | method | slide | worst frame | source slide | width, both feet standing | width, every frame | legs | knees |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | Owl onto Wolf | bone by bone | 1.31 | 0.22 | 1.61 | – | 5.16 | 0.00 | 0.00 |
  | Owl onto Wolf | full body, before | 1.07 | 0.13 | 1.61 | – | 8.57 | 16.06 | 6.28 |
  | Owl onto Wolf | full body | 1.07 | 0.13 | 1.61 | – | 0.20 | 9.97 | 0.89 |
  | Isshin onto Wolf | bone by bone | 3.00 | 0.18 | 3.92 | 0.12 | 0.23 | 0.00 | 0.00 |
  | Isshin onto Wolf | full body, before | 3.00 | 0.15 | 3.92 | 4.21 | 4.21 | 6.44 | 2.22 |
  | Isshin onto Wolf | full body | 2.98 | 0.15 | 3.92 | 0.33 | 0.73 | 1.78 | 0.70 |

  - Owl onto Wolf, a000_003041, 52 frames, travel scale 0.668, no hand contact in the clip; the Owl's feet never both stand. The review scene was made by appending the Owl before 0.6.1, so the Owl rig names Wolf's root-motion object, which holds an earlier bake's root motion; the trial pointed the Owl at its own, `HKX_RootMotion.001`, in memory. The status: "The source's footprint is set to Wolf | target rig's own hip width: left foot 4.3 cm in, right foot 4.3 cm in." The pelvis no longer drops; before, it dropped by up to 2.0 cm on frames 2–12. Feet moved by up to 6.8 cm from the chain transfer (8.6 cm before). Spine and head match the bone-by-bone bake; the neck is within 4.1°. Before the spine and neck kept the target's own stance, Wolf's neck was turned by about 49° and his head 50°.
  - Isshin onto Wolf, c5400 a000_003024, 106 frames, a 199-bone source, travel scale 0.767. The status: "The source's footprint is set to c0000's own hip width: left foot 2.1 cm out, right foot 2.1 cm out." Feet moved by up to 1.7 cm from the chain transfer (2.2 cm before). Second hand puts the left hand on the katana on frames 25–78 in both bakes. Hands, on the two frames where the source's wrists are within 0.6 forearm: 2.56 cm bone by bone, 2.44 cm full body, with the free left hand moved by up to 7.4 cm on frames 20–85. Before the weapon hand was left in place, the full body's hands were 3.19 cm off.
  - A first version of the hip width turned the sideways move straight from one stand's direction to the next. On Isshin onto Wolf, where the pelvis swings from 17° to −76° and back to 76° between two stands, it put the feet up to 6.71 cm off the width on every frame, worse than before; turning with the pelvis between stands brought that to 0.73 cm.
- Weapon grips and parts with the full-body bake, read-only, on Isshin onto Wolf with a scratch script that bakes both methods with both **Weapon grip** settings and measures the blade's long axis and flat side, taken from the meshes at rest, against the source's. Degrees on the worst of 106 frames:

  | settings | method | grip | axis in the palm | flat in the palm | axis in the world | flat in the world |
  | --- | --- | --- | --- | --- | --- | --- |
  | defaults | bone by bone | own | 46.51 | 9.31 | 18.01 | 20.84 |
  | defaults | full body | own | 46.51 | 9.31 | 18.00 | 20.84 |
  | defaults | bone by bone | source's | 0.00 | 0.00 | 17.35 | 11.49 |
  | defaults | full body | source's | 0.00 | 0.00 | 17.34 | 11.49 |
  | arm distance and body clearance off | either | own | 46.51 | 9.31 | 0.00 | 0.08 |
  | arm distance and body clearance off | either | source's | 0.00 | 0.00 | 5.75 | 9.39 |

  - Full body against bone by bone, defaults: the katana in Wolf's hand within 0.0004 mm and 0.0002°, the fingers within 0.0012°, the parts on its sockets (WP_A_0300 on socket 20, WP_A_0300_1 on socket 147) within 3e-7 of their bones; the hands up to 3.4 cm and 6.1° apart with the own grip and 2.3 cm and 1.1° with the source's, because the bodies under them differ. With arm distance and body clearance off, the two bakes are the same within 0.0002 cm and 0.0001°.
  - Second hand puts the left hand on the grip on frames 25–78 in all four bakes, 0.04 to 0.09 cm off, never short.
  - The 18° in the world with the defaults comes from **Keep arms close to the body**, which turns the right arm, hand and katana with it, by up to 22° at the shoulder, in both methods. The 46.5° in the palm is the own grip by design. 5.75° and 9.39° with the source's grip are as recorded for 0.11.0: Wolf's palm differs from Isshin's.
  - Owl onto Wolf: Wolf's R_Weapon carries no weapon mesh in the review scene, so only the bones were compared. The weapon bone sits in the hand within 0.0005 mm and 0.0001° of the bone-by-bone bake with either grip.
- iTaSC, checked with scratch scripts in background Blender 4.5.14: pole targets steer the knee with iTaSC as with the standard solver, and no result depended on earlier frames in the modes tried. The full-body bake uses its own closed-form solver; PROJECT_CONTEXT.md says why.
- Merged into main as 060cb12, on top of the katana edge fix and the preview lights: the 121 unit tests, `node --check`, all eighteen Blender scripts and the three weapon scripts with `-- BODY` pass on the merged tree. Blender prints at most 1000 bytes of an operator report, then "... truncated" without a line break, so with the full body's longer reports `blender_weapon_clearance.py -- BODY` prints its three reports and its pass line as one line; with `--python-exit-code 7` it exits 0.
- Not checked: game playback of a full-body clip, a real source from outside FromSoftware games, such as a Mixamo FBX, on a game character, the panel in a live Blender window, and a real clip in which a planted foot carries a pelvis that turns by much while it stands.

# Unreleased — the mirrored katana strikes with its edge — 2026-10-25

- The 116 unit tests pass. Blender 4.5.14 with `--factory-startup` passes all seventeen scripts, `blender_preview_lighting.py` among them. `blender_fixes.py`, flagged by the batch script for its expected refusal messages, passes on its own.
- `blender_mirror.py`, new case: a curved katana mesh, its flat sides facing the bone's ±Y, on a bridge socket that copies `R_Weapon`, which rests with armature X halfway between edge and flat. `R_Weapon`'s reflection is the flip of its Y within 1e-6, and the mirrored katana lies on the mirror image of the original within 1.2e-6 m; with the reflection of armature X, it lay 90.0 cm off.
- Read-only trials in the background, scenes not saved, measured as the largest over sampled frames of the mean distance from each mirrored vertex to the reflected original:
  - Isshin's c5400_a000_003024 on Wolf, from the user's scene, baked with the source's grip: the katana within 0.06 cm, against 0.63 cm with the mirror of 0.11.0. The scabbard on the sheath keeps its side, by design.
  - Wolf's a000_710200 with the Mortal Blade, from the event 715 test scene: on the frames where event 715 hangs a weapon on dummy 20, the Mortal Blade lies within 0.1 cm of the mirror image. The katana, on the sheath's dummy 147 all through, and the Mortal Blade's sheath keep their side, by design.
- The mirrored Isshin clip exported with read-back: 106 frames, 114 tracks, the `R_Weapon` track among them, read back within 0.000°.
- Not checked: game playback of a mirrored clip.

# Unreleased — preview lights in new character scenes — 2026-10-25

- New `blender_preview_lighting.py`, on an owned rig and a one-triangle model: setup_view() adds exactly the three area lights `Sekiro Preview Key`, `Sekiro Preview Fill` and `Sekiro Preview Rim`, each with positive power, and every 3D view's Material Preview uses the scene's lights and world. With the model moved 3 m and the view set up again, there are still three lights, and the key light moved with the model within 1e-5 m.
- The full run above, with the lights in place, passes all seventeen Blender scripts and the 116 unit tests.
- Not checked: how the lights look on a real character in a live Blender window.

# 0.11.0 — weapons lie as the source's — 2026-10-25

- Tagged run 40232279805 from v0.11.0 (e25ac74) built the decoder, packaged, tested the release ZIP on a fresh profile and published the release with `SekiroAnimationBridge-0.11.0-win-x64.zip` (66,051,154 bytes), its `.sha256` and `SekiroRetargetAssistant-0.7.0.zip` (109,338 bytes).
- Tagged run 40429075665 from v0.12.0 (f2c9601) built the decoder, packaged, tested the release ZIP on a fresh profile and published the release with `SekiroAnimationBridge-0.12.0-win-x64.zip` (66,152,952 bytes), its `.sha256` and `SekiroRetargetAssistant-0.8.0.zip` (138,039 bytes).
- The 116 unit tests pass. Blender 4.5.14 with `--factory-startup` passes all sixteen scripts. `blender_fixes.py`, flagged by the batch script for its expected refusal messages, passes on its own.
- `blender_weapon_grips.py`, new case: a curved source katana and a target blade authored turned 130° about its axis, in a palm turned 15° from the source's, baked with the source's grip. In the palm the flat side lay as the source's within 0.0000°, the blade and the curve within 0.21° (the curves tilt the meshes' long axes slightly differently), and the place within 0.0004 mm; in the world the blade pointed 14.5° from the source's. The add-on of 0.10.0 failed the same case: blade 12.5°, flat side 47.2° and curve 46.0° off in the palm.
- `blender_weapon_clearance.py`: the sword's turn is 120°, laying flat side on flat side, instead of 90°; blades parallel within 0.000°.
- Isshin's c5400_a000_003024 on Wolf, from the user's scene in the background without saving, with the source's grip, measured on 14 frames in the palm frame from the wrist to the knuckles:
  - Before: Wolf's palm turned 9.83° from Isshin's; in the palm, the blade 5.75° off and its flat side 42.5° off.
  - After: in the palm, the blade within 0.00° and the flat side within 0.02°; the blade's curve bulges to the same side of the palm as Isshin's within 1.2°. In the world the blade points 5.75° from Isshin's. The weapon turn chose the roll 50° from the smallest turn, where the meshes lay 0.0122 apart on average against 0.0155.
  - With Wolf's own grip, nothing changed: the wrist turned by up to 43.7°, as before.

# Weapons follow TAE event 715 — 2026-10-25

- The 116 unit tests pass, and `app.js` and `preview.js` pass `node --check`. Blender 4.5.14 with `--factory-startup` passes all sixteen scripts, the new `blender_weapon_locations.py` among them.
- `blender_weapon_locations.py`: on an owned rig whose L_Weapon bone turns, two models switch between dummy 118 on L_Forearm, dummy 21 on L_Weapon and hidden at 0.05 and 0.15 s. On frames 1 to 13 at 60 fps, visibility matched every change and the rigs' world matrices were within 1.8e-7 of bone times dummy, before and after saving and opening the scene.
- Imports from the game files with Wolf's TAE and part animations on, checked in the activity log, the manifest and renders:
  - `a076_405010`: `WP_A_0760_1` on dummy 21 the whole clip, `WP_A_0760` hidden; the opening umbrella is in the left hand.
  - `a070_412000`, paired through `a076_412000`: model 1 shown only from 0.2 to 0.467 s.
  - `a073_400000`: the axe changes socket at 0.233 and 3.833 s.
  - `a000_710200`: the Mortal Blade goes from dummy 149 to 20 and back to 149; Kusabimaru stays on 147 until 5.6 s.
- The part export (`-ExportParts`) of the umbrella scene is unchanged: 136,740 bytes, read back within 0.0000°.

# Merged on main after 0.10.0 — 2026-10-25

- After merging the panel review, Mirror animation and the Part animations view, with the mirror test's stand-in layout fitted to the reworked panels: the 109 unit tests pass, `app.js` and `preview.js` pass `node --check`, and Blender 4.5.14 with `--factory-startup` passes all fifteen scripts, the new `blender_panels.py` and `blender_mirror.py` among them.
- A trial merge of all four idea branches, bone links included, passed the 109 unit tests, `node --check` and all sixteen Blender scripts once the three changes named in PROJECT_CONTEXT were made. The trial was not kept.

# Unreleased — retarget add-on panel review

- On branch addon-ui-review, Blender 4.5.14 with `--factory-startup` passes all fourteen scripts: the thirteen of 0.10.0 and the new `blender_panels.py`. The 96 unit tests pass, and `app.js` and `preview.js` pass `node --check`.
- Trial three-way merges, in a scratch folder, of this branch's add-on files, the add-on README among them, with the current files of the two sessions that also change the add-on, bone connections (with its commit f425a2f) and mirror animation: no conflicts, and both merged `__init__.py` compile.

## Panels in each state

- New `blender_panels.py`, on owned synthetic rigs imported with the bridge's importer: a souls-style donor, *Donor*, with the clip a000_003008, and an Elden Ring-style target, *Hero*, at 1.1 times the size with a blade mesh on its `R_Weapon`. It brings an empty scene through twelve states: nothing chosen, a rig imported, source and target chosen, bones matched, after a bake, every conditional option shown, the control rig on, Hand on weapon with one posed frame, Plant foot with the leg in FK, Adjust over frames with auto keying on, after Apply fix, and the control rig in Object Mode.
- Background Blender draws no interface, so each panel's draw() runs against a stand-in layout that checks every call against Blender's UILayout: the function and its arguments, icons, layout attributes, the data's properties and enum values, operators and the properties set on their buttons, and UI lists, whose filter and draw functions run for every row. The check fails on a draw error; on a label that its column or box gives too little room at the sidebar's default width of 280 px, measured in the interface font with margins taken from the screenshots (58 px, 16 more in a box, 28 more with an icon); and when a state lacks an expected row or shows one it should not: the greyed buttons with their reasons, the match count, the status box after step 4, the alerts of the fixes and the Pose Mode hint.
- Bone list: the name filter THIGH showed 2 of 58 rows, L_Thigh and R_Thigh; the review filter showed the 3 rows to review; the A–Z sort ordered all 58 rows by target bone.
- `blender_control_rig.py`: its stand-in layout draws separators and gives the panel a region width; the panel still shows two Elbow swivel and two Knee swivel rows. `blender_fixes.py` expects the new FK alert, *Left leg is not in IK on this frame.*, and *click Apply fix* in two refusals.

## Before and after

Rows of the stand-in outline at 280 px, for add-on 0.6.0 (from c1da6e5) and this branch, in the same states; `(…)` is a button, `[…]` a field, `|` a box, `!` an alert, `>` a closed sub-panel, whose rows are left out. `blender_panels.py` writes every state's outline to panels.txt in an output folder given after `--`.

Bones matched, retarget panel, 0.6.0 (48 rows; at Blender's default size, *Rest sta…*, *Root m…*, *Unmap…*, *Clip timi…*, *Weapon…* and *Read back and…* show cut):

```text
v Sekiro Retarget Assistant
    1. Source → receiving character
    Source (animated)
    [Donor]  (eyedropper)
    Target (receiving)
    [Hero]  (eyedropper)
    (Append source .blend)
    2. Match and review
    [x] HKX animation bones only
    (Match bones automatically)
    55 / 58 target bones assigned
    [ ] Show unmatched / uncertain only
    {list: 58 of 58 rows, 5 at a time}
    | Same normalized name
    (Mirror L → R)  (Mirror R → L)
    (Save map)  (Load map)
    3. Bake a new action
    Rest stance: [Match source stance v]
    Root motion: [Automatic v]
    [ ] Turn root with the body
    Unmapped bones: [Keep target animation v]
    Clip timing: [Use source length v]
    [x] Move body with source hips
    [x] Keep hands out of the body
    [x] Keep arms close to the body
    Weapon grip: [Target's own grip v]
    Blade follows source: [100% slider]
    [x] Second hand on the weapon
    [x] Scale travel by leg length
    (Bake motion onto target)
    4. Export HKX
    Output: []
    Game: [Stored in scene v]
    Format: [Interleaved v]
    Tracks: [Original clip tracks v]
    Frames: [Scene range v]
    Root motion: [As baked v]
    [x] Read back and compare  [ ] Replace existing
    (Export HKX) (greyed out)
    (Use target in the bridge UI)
    | 55 / 58 target bones matched. Review the
    | rest before baking.
```

This branch (37 rows; the six rows that the list draws are left out of both blocks):

```text
v Sekiro Retarget Assistant
    v 1. Choose rigs
        Target (receives the motion)
        [Hero]  (restrict_select_off)
        Source (gives the motion)
        [Donor]  (restrict_select_off)
        (Append source .blend)
    v 2. Match bones
        [x] Only bones the clip animates
        (Match bones again)
        55 of 58 bones matched, 3 to review.
        [ ] Show unmatched / uncertain only
        {list: 58 of 58 rows, 5 at a time}
        | Master: Same normalized name
        (Mirror L → R)  (Mirror R → L)
        (Save map)  (Load map)
    v 3. Bake motion
        (Bake motion onto target)
        > Pose and timing
        > Body travel
        > Arms and hands
        > Weapons
    v 4. Export HKX
        Output: []
        [ ] Replace existing
        (Export HKX) (greyed out)
        Choose the Output file first.
        (Use target in the bridge UI)
        > Export settings
        | 55 / 58 target bones matched. Review
        | the rest before baking.
```

Plant foot with the leg in FK, Fixes, 0.6.0 (the alert shows cut to *Left leg is not…*):

```text
    v Fixes
        [Plant foot v]
        Go to a frame where the foot stands
        right, then Apply. On the chosen frames
        it stays there.
        Limb: [Left leg v]
        ! Left leg is not in IK here.  (Switch to IK)
        Whole clip | *Frames*
        Start: [8]  (time)  End: [16]  (time)
        Blend: [0.2 s]  6 frames
        (Use this pose)
        (Apply fix)
```

This branch:

```text
    v Fixes
        [Plant foot v]
        Go to a frame where the foot stands right,
        then click Apply fix. On the chosen
        frames it stays there.
        Limb: [Left leg v]
        ! Left leg is not in IK on this frame.
        ! The fix moves its IK controls, so
        ! switch it to IK first.
        (Switch to IK)
        Whole clip | *Frames*
        Start: [8]  (time)  End: [16]  (time)
        Blend: [0.2 s]  6 frames
        (Use this pose)
        (Apply fix)
```

## Screenshots

- Each state drawn in a Blender 4.5.14 window at factory settings, 1300 × 1340 px, with event simulation, which ignores real input; the sidebar scrolled through and stitched into one image per state. The screenshots are kept outside the repository. At interface scale 1 the sidebar is 280 × 1,139 px. Heights of the whole sidebar, the retarget and control rig panels together:

| State | 0.6.0 | This branch | All sub-panels open |
|---|---|---|---|
| Nothing chosen, rig imported, source and target chosen | one screen | one screen | 1,203–1,611 |
| Bones matched | 1,409 | 1,236 | 1,941 |
| Baked | 1,633 | 1,396 | 2,101 |
| Every option shown | 1,683 | 1,371 | 2,171 |
| Control rig on | 2,313 | 2,160 | 2,865 |
| Hand on weapon, one frame posed | 2,376 | 2,155 | 2,860 |
| Plant foot with the leg in FK | 2,288 | 2,140 | 2,845 |
| Adjust over frames with auto keying on | 2,354 | 2,135 | 2,840 |
| After Apply fix | 2,379 | 2,170 | 2,875 |
| Control rig in Object Mode | not taken | 2,240 | 2,945 |

- After a bake, the first screen of 0.6.0 ends at the export's Frames menu, above the Export button; on this branch it reaches past the Export button into the bake's result.
- Measured between the gaps that separate the panels, in the control rig states the retarget panel with its status box is 1,246 px high on this branch against 1,541 px in 0.6.0, and the control rig panel 67 to 140 px higher: 896 against 829 with Hand on weapon, 881 against 741 with Plant foot. The IK slider line, the gaps between the limbs and the taller Apply fix add about 70 px; the FK alert, on three lines with Switch to IK under it instead of one cut line, about 70 more where it shows.
- With the display's scaling, the window first opened at interface scale 1.25 (sidebar 350 px). There the FK alert's second line was cut to *switch it…*: an icon takes 28 px of the row, not the 20 px first assumed. At scale 1 the Hand on weapon hint was cut to *click Ap…*: the Fixes sub-panel gives a label less room than a top-level panel, a line of 228 px was cut where one of 223 px fit, so the margin went from 52 to 58 px. With these margins in the add-on and in the check, no label is cut in any state at scale 1 or 1.25, also with every sub-panel open at scale 1.
- Blender marks the Output path red in the shots because the test scene is not saved, so `//` has no folder; that is Blender's own check of the path.

# Unreleased — mirror animation

- On branch `mirror-animation`, Blender 4.5.14 with `--factory-startup` passes all fourteen scripts: the thirteen of 0.10.0 and the new `blender_mirror.py`. The 96 unit tests pass, and `app.js` and `preview.js` pass `node --check`.
- New `blender_mirror.py`, on an owned FromSoftware-style skeleton of 85 bones whose rest frames are all turned at random, the shoulder helpers half a turn from mirror images and the right weapon bone 3 cm from the mirror image of the left one. Cloth bones on either hip have no side in their names, nor do pouches on either hip that rest 5 mm from each other's mirrored places; a sash hangs on the left hip, cloth on the left forearm. Gear: a spear resting 2.5 m to the left with a fin on either side, keyed into the left hand; a cord in the right hand whose end bone rests 13 m below and is keyed up to it; a scabbard on the left hip with a wedge-shaped mesh of its own; a sheath that bends with the left thigh; hip cases without a mesh. The 30-frame clip swings the left arm, turns and leans the body, scales the left shoulder helper unevenly, travels sideways and turns with root motion, and keys a custom property on the left hand.
  - Pairs by name, and by place for the cloth bones but not the pouches; the hands' rests are no mirror images, even up to flipped axes. The rules, notes and warnings came out as designed, and the original action and root motion kept their keys.
  - 71 of the 85 bones, all whose pairs rest at mirrored places outside gear and one-sided bones, were the exact reflection of their counterparts within 3.1e-6, the hip cases and the place-paired cloth among them. The right hand followed the left one's path within 5.0e-7 m, the head leaned the other way within 1e-4 m, and the right shoulder helper took the left one's uneven scale, up to 15%, within 6.7e-7.
  - Gear was placed at its reflection within 1.4e-6, the weapons and the spear changed hands with their grips kept within 7.2e-7 m, and the scabbard went to the right hip. Its mesh, symmetric under a flip of its own X or Z axis only, was chosen that way and mirrored point for point within 4.9e-7 m. Below gear, the cord's bones reflected on the cord's plane and the spear's fins swapped across the spear's within 6.9e-6.
  - The sheath and the sleeve cloth kept their own motion within 2.9e-7; the sheath and the sash stayed on the left, attached within 5.1e-7 m, the sash mirroring its own turn. Root motion changed sign sideways and in its turn within 0.0, and the custom property's keys moved to the right hand unchanged.
  - The export of the mirrored clip had the original's tracks, its root motion mirrored within 0.0, and read back as the mirrored clip within 2.9e-6. Exported by name with the original playing, it had the same frames and root motion.
  - The panel row and `bpy.ops.sekiro_retarget.mirror_animation()` mirrored the copy back to the original within 8.6e-6, the largest on the cord's end bone, keyed 14 m from its rest; the other bones within 1.5e-6. Mirroring the original again named the copy "Mirrored.001" with the same result. With a control rig, the operator was greyed out and the mirror refused. The mirror took 0.07 s.
- Read-only trials in Blender 4.5.14 in the background: the scenes were opened from the user's bridge folder and not saved, and the user's live scene was not opened. Each trial ran the operator, rendered five frames before and after, mirrored twice, exported through **Export HKX** with the mirrored clip playing, and exported by name with the original playing, written by the conversion Python with read back. Mesh distances compare the mirrored clip's vertices with the original's flipped across the middle plane at the rendered frames.
  - Isshin, c5400_a000_003024, 106 frames, 199 tracks: 0.79 s. 56 pairs; 108 bones swap, 81 reflect, 60 of them the cord's on its own plane, and 10 gear bones follow, the scabbard with the flip of its Y axis. 105 bones were exact reflections, the worst `R_Shoulder` at 2.0e-4, whose rest is 0.64 mm off its mirror image; gear within 2.4e-6, and the bones below gear within 4.9e-3, the largest on `Wire_60`, whose head rests millimetres off the cord's plane. Mesh, 104,481 vertices: body median 0.6 mm, 95% within 2.5 cm, largest 15 cm; katana 1 mm, cord 6.6 mm (23 cm before the cord mirrored across its own plane), scabbard 4.9 cm. The katana went from 0.105 m off the right hand to 0.105 m off the left, the scabbard from the left hip to the right. Twice: 7.6e-6. **Export HKX**: 106 frames, 199 tracks, 1,033,716 bytes, read back within 0.000° and 0.00 mm; by name: read back within 2.4e-6° and 0 m, the same frames, root motion the original's with the signs changed within 2.3e-7, the same tracks.
  - Wolf, c0000_a070_400000, 58 frames, 112 tracks: 0.42 s. 60 pairs; 116 swap, 23 reflect, 4 follow (both weapons and shields), 3 keep. 119 bones exact, the worst `R_Pectoral` at 5.9e-3: the pectoral helpers rest 1.35° off mirror images and the clip scales them by up to 25% along one axis, which loc/rot/scale keys cannot reflect without shear. Gear within 9.5e-7, kept bones within 3.0e-7. Each weapon and shield bone went from 0.088 m off its hand to 0.088 m off the other hand. Warning: the back and hip cases, `LargeSheath` and `Sheath` keep their side. Mesh, 121,165 vertices: median 4.8 mm, 95% within 2.4 cm, largest 7.3 cm, as Wolf's costume is not symmetric. Twice: 1.1e-6. **Export HKX**: 58 frames, 112 tracks, 327,700 bytes, read back within 0.000° and 0.00 mm; by name within 2.4e-6°, root motion within 3.0e-8.
  - c5100_a000_000000, 251 frames, 171 tracks, no root motion: 1.40 s. 85 pairs; 174 swap, 66 reflect, 2 follow (WeaponHead and WeaponBlade), 6 keep. In the held head, the eyes, the eyelids and two pairs of scratch bones swap, one of them by place across the game's own spelling `WaeponScratch1`; the jaw, two tongue bones and one tooth reflect on the head's plane; the cheek and five teeth without a bone at their mirrored places keep their motion; across the head's plane within 1.2e-5. 211 bones exact, the worst `R_Shoulder` at 2.9e-5; gear within 4.8e-6, kept bones within 9.2e-7. Mesh, 182,814 vertices: median 5.6 mm, 95% within 5.5 cm, largest 57 cm in the fur, which is not symmetric; the head within 28 cm, its mesh mapping onto itself within 2.6 cm on average. Warning: two teeth of the body's head, `OverTeeth1` and `OverTeeth3`, stay on their side and mirror their own motion. Before pairing by place took 0.1% of the leg length, the cheek paired with a tooth on both heads, and the cheek's vertices mirrored 0.47 m from the tooth's. Twice: 5.2e-6. **Export HKX**: 251 frames, 171 tracks, 2,078,164 bytes, read back within 0.000° and 0.00 mm; by name within 2.4e-6°.
  - The contact sheets (the original, the original flipped as an image, the mirrored clip) show the mirrored poses matching the flipped ones, the katana in Isshin's left hand and his scabbard on the right hip; the differences are the meshes that are not symmetric, such as Wolf's prosthetic arm, which stays on his left.
- Not checked: game playback of a mirrored clip; clicks in a live Blender window, as the operator ran through `bpy.ops` and the panel through a stand-in layout.

# Unreleased: part animations view — 2026-10-25

- On the branch `part-animation-menu`, the 109 unit tests pass (the 96 of 0.10.0 and 13 new ones), Blender 4.5.14 with `--factory-startup` passes all thirteen scripts, and `app.js` and `preview.js` pass `node --check`.

## Part animations view

- New `test_part_view.py`, on owned synthetic data: an umbrella part `wp_a_0760` with an animated model, whose own TAE gives a076_405033 the clip a076_421020_1, and a model with only its rest pose; a katana part with only its rest pose; an outfit binder that is not a binder; and Wolf's `c0000.anibnd`, whose TAE has a076_412000 play a070_412000.
  - Listing: only the umbrella is listed, with its animated model and 3 clips. A weapon part whose binder cannot be read gives one notice, 3 parts count as read, and the outfit is not opened.
  - Pairs: a076_405010_1 plays in a076_405010 (*same ID*), a076_412000_1 in a070_412000 (*TAE of C0000: a076_412000 plays a070_412000*) and a076_421020_1 in a076_405033 (*its TAE plays a076_421020 for a076_405033*), which is marked not ready; the rest pose a999_000000_1 is named and not listed. For each of the 3 pairs, plan() of that player clip keys the listed part clip with the same reason.
  - Refused: an outfit part, a path with `..` in it, an empty path, and every part of a Dark Souls III catalog, which lists no parts. A game folder whose player is not read yet reports it, with no player clips and no pairs. In a collected folder, a player clip of another scope is not paired.
  - Routes, on a real ThreadingHTTPServer with the home folder and the settings patched: both routes answer on owned data, and no file in the source or home folder changes. Without the token, with a wrong token, a wrong Host or a foreign Origin, both routes give 403 *Unauthorized workspace session*; an unknown route gives 404; a catalog outside the cache gives 400 *Invalid folder catalog.*, the character binder as the part gives 400 *Choose a Sekiro weapon part from the scanned source.*, and a wrong folder gives 400.
- `test_part_animations.py`: players_of() groups the IDs by the HKX that they play; pairings() gives the three kinds of pair; for every player clip, it agrees with choose_clip(), with and without the players index.
- On the user's game folder, read only, in a fresh process: 36 Sekiro weapon parts read, 23 listed, no notices. The first listing took 0.52 s, then 6.4 ms; each part's matches took 15–28 ms. 27 models with 389 clips: 381 play in one player clip each, 309 by the same ID and 72 through Wolf's TAE; 8 play in none: a078_425010_1 and a078_426010_1 of wp_a_0780 to wp_a_0782, and a079_423000_1 of wp_a_0790 and wp_a_0791.
- Trial of the UI, through a copy of the app with its own state file and app data folder on port 8791, on the user's game folder read only, in the built-in browser at 1400×860:
  - The tab shows for the Sekiro game folder, and the first /api/part-list took 576 ms. The parts show with their names. Choosing WP_A_0760 started reading Wolf's archives: 1,434 animations.
  - a076_412000_1 lists a070_412000 from `c0000_a07x.anibnd.dcx` with *TAE of C0000: a076_412000 plays a070_412000*, chosen at once. The scene panel showed a070_412000 with am_m_9000, bd_m_9000, fc_m_0200, lg_m_9000 and wp_a_0760 selected and Animate weapon parts on, and the Preview block listed WP_A_0760_1 playing a076_412000_1 for the same reason.
  - **Create Blender scene**, saved to a scratch folder, took 6 s: 41 frames, 6 model parts, 47 material images and 1 part clip. Its report keys WP_A_0760_1 with a076_412000_1.hkx, 41 frames at 30 fps, and holds WP_A_0760 at its rest pose.
  - The Dark Souls III source, not scanned, hides the tab and shows Source library; back on Sekiro, the part, the clip and the animation came back. Down and Enter in the part clips chose a076_412003_1 and its animation a070_412003, with the focus kept on the row. `/` focuses the part clip search; this was sent as a key event from the page, since the browser tool's key presses did not produce `/`.
  - At 760 px the panes stack at full width without horizontal scrolling. After a reload, the remembered part and clip scroll into view inside their lists while the page stays at the top.
  - The user's settings files and Animation Bridge folder did not change, and nothing in the game folder is newer than the trial. Screenshots stayed in the session scratchpad.

# Version 0.10.0 — 2026-10-25

- On the release tree, Blender 4.5.14 with `--factory-startup` passes all thirteen scripts: the eleven of 0.9.0, the new `blender_fixes.py` and the new `blender_weapon_grips.py`. The 96 unit tests pass, and `app.js` and `preview.js` pass `node --check`.
- Tagged run 40213498235 (v0.10.0, commit c1da6e5, windows-2025 runner, image windows-2025-vs2026) built the decoder and the release ZIP (302 files, 65,951,903 bytes). On a fresh profile the first start downloaded Python 3.13.16 and installed the 15 pinned packages; the UI reported the conversion libraries, the decoder and DCX ready and selected the packaged decoder. With the Visual C++ 2010 runtime installed, the 96 unit tests passed from the unpacked ZIP. The run published the release: `SekiroAnimationBridge-0.10.0-win-x64.zip` (65,951,903 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.6.0.zip` (93,040 bytes).

## Retarget: weapon grips and the second hand

- New `blender_weapon_grips.py`, on owned synthetic rigs. An Isshin-like source holds a katana in its right hand by a grip of its own, moved 2 cm in the fist and turned out of it, its fingers curled by 50°, 40° and 30°. On frames 20–41 its right hand comes in front of its belly and its left hand holds the hilt behind it: the left knuckles sit 9 cm behind the right ones along the blade and 1.5 cm off its axis, solved onto the hilt within 0.1 mm. The Wolf-like target is 1.1 times larger, its blade along the weapon bone's Z axis, and its own clip holds the weapon by another grip, moved 1.8 cm and turned by 15°, with fingers curled by 30°, 20° and 10°.
  - **Target's own grip** at 100%: on all 60 frames the weapon kept the own grip within 0.0004 mm and 0.0000°, with the wrist turned by up to 35°; the blade stayed parallel to the source's within 0.0000°, and the right fingers took the own clip's pose within 0.0000°.
  - At 0%, the own grip held as closely, the wrist matched a bake with the source's grip within 5.1e-9, and the blade pointed up to 35° away from the source's. At 50%, the wrist turned half as far within 8.2e-6: 18° against 35°.
  - **Source's grip**: the weapon sat where the source's sits in its palm, scaled by 1.1, within 0.0003 mm, its blade parallel within 0.0000°, and the fingers turned as the source's within 0.0000°.
  - **Second hand on the weapon**: the left hand held on during frames 15–46, which cover the source's two-handed frames, never short of its place and within 1 cm of it. Its knuckles sat behind the right hand's along the hilt and 1.1 × 1.5 cm off the axis within 0.00 mm; without the option they were up to 3.8 cm off it. More than 10 frames away from the two-handed frames, the left arm matched the bake without the option within 3.9e-7.
  - A target clip that does not animate the weapon took the source's grip, with the note. One that hides the weapon on every frame gave the grip with the warning and *the wrist turns as the source's does*.
  - A target whose weapon bone rests 0.85 m from its hand was placed in the hand. With the own grip it sat there within 0.0003 mm of the own grip, its blade parallel within 0.0000°, without the *is placed* note. With the source's grip it kept the place where the source holds its weapon, more than 5 mm from the own grip, and an own clip that hides it on every frame left it at that place within 1e-5, with the note instead of the warning.
- New unit test for `Rig.finger_roots`, which the grips read: the first bone of each finger, thumb first, on every convention of the matcher tests, both sides, with named and unnamed fingers.
- Baked in Blender 4.5.14 from the user's scenes in the background, without saving them; the user's live Owl-to-Wolf scene was not opened:
  - Isshin's c5400_a000_003024 on Wolf (`c0000_a000_000000_from_c5400_a000_003024.blend`), 106 frames: `R_Weapon` took Wolf's own grip from frame 1 of his clip, the wrist turned by up to 44°, and the left hand went onto the hilt where Isshin holds his katana with both hands. At 100% the hilt went up to 9.6 cm into Wolf's torso, so the hands were kept out by up to 12.3 cm; at 0%, 6.4 cm and 7.6 cm.
  - Isshin's clip on Owl (`c5060_a000_000401_from_c5400_a000_003024.blend`), 106 frames: Owl's `R_Katana` rests 1.05 m from his hand and is placed. His clip a000_000401 hides it on every frame, so it stayed where Isshin holds his katana, with the note. The left hand held the hilt on frames 25–78 within 4.7 mm. As with 0.9.0, the hands were kept out of the body by up to 31.2 cm and parts of frames 40–79 report a hand left inside the body.
  - Owl's c5060_a000_003008 on Wolf (`c0000_a000_000000_from_c5060_a000_003008_before_pin.blend`), 89 frames: Owl's katana does not rest at his hand, so Wolf's `R_Weapon` is placed; it took Wolf's own grip from frame 1, the wrist turned by up to 23°, and the left hand held the hilt on frames 20–55 within 1.2 mm.
  - Close-up renders of the right hand on frames 50 and 90 of Isshin's clip and 36 and 50 of Owl's, against the 0.9.0 add-on, show Wolf's hilt through the fist with the guard at its front, where 0.9.0 left it beside the fingers or along the forearm.

## Control rig: swivel rings

- `blender_control_rig.py` now also checks the swivel rings. The control count includes a third control per IK limb, besides the IK control and the pole. On frame 8, each ring sits at its elbow or knee with its arrow on the side the joint bends to; turned by 30°, it swung the joint by 30° within 0.22° while the hand or foot moved 2.2e-6 m and turned by less than 0.05°. The panel shows *Elbow swivel* twice and *Knee swivel* twice, and after **Add control rig** every ring's turn is keyed on all 24 frames. A ring keyed at 40° went back to 0 with **Switch to IK**, which kept the pose within 3.1e-5 m. **Adjust over frames** on the left arm, with the ring turned by 25° on frame 18, over frames 15–21 with 2 blend frames, keyed only the ring: the turn spread as expected within 5.2e-6°, the elbow moved by more than 2 cm, the hand stayed within 1.8e-6 m, and frames outside 13–23 kept their pose. **Remove control rig** left no drivers.
- `blender_fixes.py` now expects the left arm's swivel ring among the controls that Adjust over frames keys.
- Refused adjustment (`blender_fixes.py`): with the right arm chosen and FK-R_Weapon, which has no location or rotation keys, nudged by 5.4 mm and 4° on frame 1, Apply was refused, said to key the control and set Limb to Selected controls, and left the pose, which held on every frame. Keyed once and nudged again, Apply was refused, named FK-R_Weapon as posed and kept the pose on the screen, and Selected controls then gave every frame the change within 3.7e-07 m / 8.4e-06°.

## Control rig: fixes

- New `blender_fixes.py`, on an owned FromSoftware-style skeleton with turned rest frames, a weapon bone in each hand, a mesh on the right one and a `Sheath` bone at the hip. Its 60-frame clip at 30 fps turns the hips, spine, head and limbs and travels with root motion, so import makes `HKX_RootMotion`. The control rig is added and every limb is set to IK.
  - Defaults: Hand on weapon takes the left arm and `R_Weapon`, which holds the mesh; Weapon into sheath takes the right arm, `R_Weapon` and `Sheath`; Plant foot takes the left leg.
  - **Hand on weapon** through **Apply**, with the left IK hand posed 3 cm along the weapon on frame 15 and not keyed, on frames 12–18 with 0.2 s blend (6 frames). The pose survived the property changes before Apply. The IK control kept its relation to `R_Weapon` within 2.7e-7 m and 2.8e-5° on frames 12–18, and the game hand within 2.4e-6 m; the blend frames matched the eased relation within 1.9e-5; frames beyond the blend were unchanged (0.0 m). The report named frames 9–10 out of reach by up to 0.5 cm. A first try on frames 10–25 left the hand out of reach on frames 10 and 21–25, which the report also named, as this clip swings the right arm far.
  - **Plant foot** on frames 20–30 from frame 25: in the game's world, root object @ armature, the IK foot stayed within 1.6e-7 m, where it slid 0.339 m before. The status explained that the foot moves against root motion in Blender.
  - **Weapon into sheath** posed with **Use this pose** on frame 44 and, 6 cm farther in, on frame 50, then applied on frame 47, which is not posed. The weapon is keyed to 0.001 on frames 48–52. On frames 44–50 its relation to the sheath followed the interpolation of the two posed relations within 3.9e-5 m and 2.2e-5°: the arm's IK reaches its control within 4.2e-5 m here, and with the first goal, taken before IK, the error grew to 7.9e-5 m. The weapon stayed at 0.001 on frame 49. **Use this pose** kept the unkeyed pose on the screen within 1e-9.
  - **Adjust over frames** with the left arm, posed by 4 cm and 10° on frame 30 with **Use this pose**, and by 3.6 cm and 5° on frame 36, where **Apply** took the pose directly, over frames 28–38 with a 3-frame blend: the change from the clavicle followed the expected spread within 3.1e-7 m and 4.8e-5°. A selected FK head control turned by 15° on frame 12 turned by it on all 60 frames within 2.5e-7 m and 3.2e-5°; the selected game bone was ignored.
  - Panel: drawn for every task with a stand-in layout, it uses only properties, operators, operator properties and icons that exist; the posed frames, the auto keying warning and *Left leg is not in IK here.* appear when expected. **Use current frame** set the start and end; **Clear posed frames** cleared them.
  - Reports and refusals: a hand held on the other foot over the whole clip named out-of-reach frames. With the leg's slider keyed from 0 on frame 6 to 1 on frame 8, frames 5–7 were reported as not fully in IK. Refused with a message: a fix of frames 1–6, all in FK, and **Use this pose** on frame 5; a target that moves with the limb; a posed frame outside the frames; a pose that matches the animation, through **Apply** too, which set the status. No fix added a constraint.
  - Export and removal: the export after the fixes turned the left arm by up to 173° against the export before them. **Remove control rig** with *Keep the edited motion* kept every game bone within 1.0e-5 m and 4.4e-3°, and its export matched the export with the control rig within 1.1e-6 m and 9.9e-4°. The largest error is on `R_Toe0`, which no fix moves: removal gives the same 1.0e-5 m on this rig with the legs in IK and no fix.
- On a copy of the user's Owl-to-Wolf scene (`c0000_a000_000000_from_c5060_a000_003008.blend`, saved 12:22, in the session scratchpad; the original was not changed), 89 frames at 30 fps with `HKX_RootMotion` and the left arm in IK:
  - Defaults: Hand on weapon takes the left arm following `R_Weapon`; Weapon into sheath the right arm, `R_Weapon` and `Sheath`, before `LargeSheath` and the `Wepon_Case` bones.
  - **Hand on weapon** on frames 20–45, from the pose on frame 20, with 3 blend frames: the left IK hand's relation to `R_Weapon` spread over 0.506 m before and 0.000000 m after, in 0.2 s. The report named frames 33–47 out of reach by up to 17.8 cm. The frame-20 hand sits off the hilt in this save, so Owl's grip held there needs a longer reach.
  - Weapon into sheath on the right arm in FK was refused with *Click Switch to IK first*. After **Switch to IK** (0.2 s), it ran in 0.1 s; Plant foot on the left leg after Switch to IK and an Adjust of 2 cm also ran in 0.1 s each.
- Not checked: clicks and drags in a live Blender window; game playback of a fixed clip.

# Version 0.9.0 — 2026-10-25

- On the release tree, with the clip preview's playback fix, the foot targets and the Browse fix: the 95 unit tests pass, `app.js` and `preview.js` pass `node --check`, and Blender 4.5.14 with `--factory-startup` passes all eleven scripts, `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py`, `blender_control_rig.py`, `blender_weapons.py`, `blender_weapon_clearance.py`, `blender_weapon_hands.py`, `blender_part_animations.py`, `blender_two_characters.py`, `blender_arm_gap.py` and `blender_foot_targets.py`, with **Keep arms close to the body** on by default. The sections below give what each change added and how it was checked.
- Before tagging, a ZIP packaged as the workflow does, from a clean copy of the tracked files and without the decoder and uv (77 files), passed the 95 unit tests from its unpacked folder; its `SekiroRetargetAssistant-0.5.0.zip` holds the add-on at version 0.5.0, with `imported_pair.py`.
- Tagged run 40180065989 (v0.9.0, commit ec1be1f, windows-2025 runner) built the decoder and the release ZIP (288 files, 65,747,308 bytes). On a fresh profile the first start downloaded Python 3.13.16 and installed the 15 pinned packages; the UI reported the conversion libraries, the decoder and DCX ready and selected the packaged decoder. With the Visual C++ 2010 runtime installed, the 95 unit tests passed from the unpacked ZIP. The run published the release: `SekiroAnimationBridge-0.9.0-win-x64.zip` (65,747,308 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.5.0.zip` (68,330 bytes).

## Retarget: weapons in the other hand, weapons that rest away from the hand, and hidden weapons

- Unit tests: 2 new in `test_retarget_mapping.py`. On owned FromSoftware-style rigs, a source holds an axe in its left hand only, and the target has a katana at its right hand and a spear and a gun that rest 1.7 m and 1.2 m from its left hand. The katana takes the axe ("Weapon from the other hand", 80%), and the spear and the gun stay unassigned. With another katana at the target's left hand beside the spear and the gun, the axe does not change hands, and that katana, one of three left-hand weapons, stays unassigned for review; with that katana alone in the left hand, it takes the axe on its own side. Weapon, scabbard, storage and shield names such as `R_Katana_Saya`, `back_Yari_Storage`, `B_Wepon_Case`, `L_Shield` and `c4720_L_Axe` get the Hide toggle; hands, fingers, the spine and the pelvis do not.
- `blender_weapon_clearance.py` gives the same results as for 0.8.0 and now also checks that its sword, which rests at the hand, is not placed.
- `blender_export_options.py` now also keys the pelvis's scale on frames 4–6 of a copy of its clip, first to 0 and then to 0.001, and exports it. Both times every value is finite, the pelvis keeps its keyed translation and rotation at the keyed scale, and the spine below it keeps its own translation, rotation and scale within 1e-3. With the exporter as it was, the spine's track on frame 4 was (0, 0, 2) at scale 0 instead of (0, 0.3, 0), and the pelvis's rotation there was the identity.
- New `blender_weapon_hands.py`, on owned FromSoftware-style skeletons with 60 frames. The source holds an axe in its left hand and nothing in its right; its clip hides the axe on frames 1–2 by scaling it to 0, slides it back and forth along its line and tilts it, and swings the left arm, while the right hand goes into the belly. The target is 1.2 times larger, with a box torso, box hands, a katana with a scabbard bone below it at its right hand, and a spear and a gun that rest 1.5 m and 1.2 m from its left hand and that its own clip hides by scaling them to zero.
  - The matcher gave `R_Katana` the axe ("Weapon from the other hand", 80%) and left the spear, the gun and the scabbard unassigned. The bake placed `R_Katana` in `L_Hand` and said so. On every frame, the katana lay within 0.001 mm of the axe's offset from the hand at 1.2 times the size, with its grip in the hand along the axe's line; it turned like the axe within 0.05° and was hidden at 0.001 on frames 1–2, where the axe is at 0. The scabbard kept its own channels within 1e-3 on every frame.
  - With **Keep hands out of the body**, only the right hand moved, on frames 9–60 by up to 12.8 cm, and the katana in the left hand stayed where the plain bake put it within 1e-5.
  - Giving the axe to the spear cleared the katana's row ("Source moved to L_Yari"). The bake placed `L_Yari` in `L_Hand` within 0.001 mm and showed it like the axe, although the target clip hides it. `R_Katana` stayed at its rest grip in the right hand within 1e-4, and the gun stayed hidden. With the axe's mesh along its bone's Y axis, the spear turned by 90° and stayed parallel to the axe within 0.000° on frames 3–60, with its grip in the hand along the mesh's line.
  - Hiding the katana, now unmapped, and the placed spear with their Hide toggles: the bake reported both as hidden on every frame. On all 60 frames both had scale 0.001 within 1e-6, the katana at its rest grip in the right hand within 1e-4 and 0.06°, the spear where the axe puts it within 0.1 mm; the scabbard shrank with the katana and kept its own channels within 1e-3. A saved map held both toggles, **Match bones automatically** cleared them, and loading the map brought them back with the axe on the spear; baking again hid both.
  - Each new check failed on a scratch copy of the code with its fix removed: without the 0.1% floor, the placed katana had scale 0 on frame 1; without the exporter's fallback, the spine's track was off; without the keyed rotation, the pelvis's rotation was the identity.
- Godfrey onto Isshin, on copies; originals untouched. Godfrey's a000_003000 was imported with the bridge from the supplied c4720 anibnd, which has his rig but no mesh, into the session scratchpad, and baked onto a copy of Isshin's c5400 scene with the defaults. Of Isshin's weapon bones, only `R_Katana` rests at its hand: his clip hides `L_Yari`, `L_Gun` and `R_Gun`, and `R_Katana_Wire` rests away from the hand.
  - **Match bones automatically** gave `R_Katana` Godfrey's `L_Axe` ("Weapon from the other hand", 80%) and left Isshin's other weapon bones unassigned. The bake placed the katana in Isshin's left hand within 0.002 mm of the axe's offset from Godfrey's left hand at Isshin's size, with the grip held along the line, and turned it like the axe within 0.000°. The grip stayed within 0.136 m of the hand; Godfrey's own grip slides along the haft by up to 0.601 m at Isshin's size. **Keep hands out of the body** moved both hands, which hold the haft together, on frames 58–84 by up to 3.4 cm; Godfrey has no body mesh to compare with.
  - Giving the axe to the spear cleared the katana's row ("Source moved to L_Yari"). The spear, which rests 1.7 m from Isshin's hand and which his clip hides, was placed in his left hand within 0.001 mm and 0.000° and shown with the axe. Both hands moved out on frames 47–71 by up to 4.8 cm. The katana, now unmapped, kept Isshin's clip and stayed in his right hand.
  - On the 11 frames between 2 and 65 where Godfrey's right hand is within 0.15 of the haft's line at his size, it lies 0.142 from the line on average. Isshin's right hand lies 0.202 from it on average and up to 0.324 at Godfrey's size, about 18 cm at Isshin's: the bake does not pull the second hand onto the weapon.
  - Renders of frames 1, 21, 41 and 71, with Godfrey as a stick figure and a stick along his axe, show the katana and then the spear in Isshin's left hand along the axe, and Isshin's unmapped `R_Katana_Wire` where his clip puts it. The stick gave the axe a mesh, so the spear turned by 0.43° to stay parallel to it.
  - Hiding by keys: Isshin's a000_003024 hides `Katana_Storage`, `L_Yari` and `R_Katana_Saya` at 0.001 and `L_Gun`, `R_Gun`, `world_Yari` and three spear storage bones at 0.0001, all of them bones without children. After the bake with the axe on the spear, `R_Katana`'s scale was keyed by hand for the whole 116-frame clip and exported with all 199 tracks. Keyed to 0, the exporter as it was wrote the scabbard `R_Katana_Saya` up to 48.332 m from the katana at scale 0, and the katana's rotation as the identity. With the fix, the scabbard's track stayed within 0.276 m at its own scale of 0.001, within 0.6 mm of the export with the katana keyed to 0.001, and the katana kept its keyed rotation within 0.04° of that export on every frame. The writer turned that export into a spline (threecomp40, tolerance 0.001) and an interleaved Sekiro HKX. Decoded again, the katana's scale was 0 and the scabbard's 0.001 on every frame, all values were finite, and every track's scale was within 3e-6 of the export; the spline's largest rotation difference, 0.29° on `L_Finger32`, stayed below the writer's 0.5° notice.
- Not checked: game playback of a clip with a placed or hidden weapon; Godfrey's own clipping, since no mesh of his was available; other pairs on real scenes.

## Retarget: arms close to the body

- With the option on by default, the other Blender scripts give the same results as before: their rigs without meshes, or without arm meshes, are not compared and get no new note.
- New `blender_arm_gap.py`, on owned FromSoftware-style skeletons with 110 frames at 30 fps. The source has a torso box 0.48 m wide and 0.30 m deep, far wider than its shoulders, and box forearms and hands. The target has the same skeleton 1.1 times larger, with a torso box 0.29 m wide and 0.26 m deep. The source's clip holds its rest stance, swings its left arm overhead, brings both wrists together in front of its belly and returns to rest.
  - The plain bake left the target's arms at least 12.1 cm farther from its torso than the source's at its size, on every frame where the source's arm stood within a quarter arm of its body.
  - With the option, the gap of the forearm and hand boxes to the torso box matched the source's at the target's size within 0.10 mm on 85 arm frames at rest, and within 7.7 mm on 18 moving ones, where the averaging lags. The arms turned by up to 23.2° and the hands came in by up to 23.4 cm, at most 5.47 cm per frame. Elbow bends and wrist rotations stayed within 0.01°, and the shoulders within 1e-6.
  - The 13 frames of the left arm's swing away from the body and all 26 frames with the hands together kept the plain bake within 1e-5, and the report listed the frames kept for the grip.
  - On frames 30–33 of a mix of both bakes, where the right arm already stood at the source's gap and only the frames around asked to come in all the way, the turns carried over by the averaging stopped 11.8 mm from the torso, at 2% of the arm (11.7 mm).
  - With **Keep hands out of the body** as well, the gaps stayed within 0.1 mm and no hand vertex was inside the torso. Without the source's body mesh, nothing was compared, the note said so, and every bone matched the plain bake within 1e-6. With a target torso wider than the source's, no arm turned.
  - Each check failed on a scratch copy of the code with its part removed: without the pass, the report had no turned arm; with every turn 10% short, the resting gap was 12.9 mm off; without the 2% cap, the mixed frames ended 0.5 mm from the torso in armature units, where the cap is 10.6 mm; without the grip ease, the left forearm moved by 0.096 on frame 69 with the hands together.
  - The bake took 0.27 s without the option and 0.36 s with it.
- Owl's a000_003041 onto Wolf, on a copy of `work/retarget_review/Owl_to_Wolf.blend` in the session scratchpad; the original was not changed. 97 of 114 rows matched and the clip has 52 frames; Owl's arm is 0.90 m long and Wolf's 0.51 m. The gaps below were measured with the add-on's own limb points and torso, signed with its forward-and-back ray test, at Wolf's size.
  - The plain bake left Wolf's left arm up to 13.8 cm (6.6 cm on average) and his right arm up to 10.6 cm (4.7 cm) farther from his torso than Owl's.
  - With the option, the left arm turned on frames 1–2 and 5–52 by up to 26°, 22.6 cm at the hand, and the right arm on frames 1–2, 5–33 and 36–52 by up to 20°, 11.0 cm at the hand. Both stayed as they were on frames 3–4, with the hands together, and the right arm also on frames 34–35, where it already stood 0.8 cm from the torso.
  - From frame 17 on, each arm stood within 1.5 cm of Owl's gap, 0.5 cm on average, where the plain bake was 5.2 cm (left) and 4.0 cm (right) off on average. On frames 1–16, around the frames with the hands together, the eased turns left the left arm up to 11.9 cm farther than Owl's, and the averaging brought the right arm up to 3.1 cm closer than Owl's on frames 9–11. No forearm, hand or finger point was inside the torso on any frame, and wherever the plain bake stood at least 1 cm from the torso, the arms did too.
  - Front renders of frames 13 and 19 show Wolf's arms held out in the plain bake and along his robe with the option.
  - The first version, before the grip ease and the 2% cap, put 11 forearm points 1.6 cm into the torso on frame 1, brought the right arm to 0.1–0.5 cm on frames 32–37 and turned both arms on frames 3–4.
- Not checked: the Corrupted Monk onto Wolf, the case the user reported, since no Monk files were available locally; other pairs on real scenes; game playback of a clip baked with the option.

## Foot targets follow the feet

- Game clips, in scenes imported earlier with the bridge and opened without saving. Every rig had `L_Foot_Target2` and `R_Foot_Target2` under `Master` at hip height, `*_Foot_Target1` below them at knee height and `*_Foot_Target` at the ankle, resting where its foot rests (0.00° and 0.0 mm). In nine clips of eight rigs, `*_Foot_Target` stayed on its foot on every frame, within 0.34° and 9.3 mm. The clips were Sekiro's c0000 a000_000302 and a070_400000, c5000 a000_003028, c5100 a000_000000, c5400 a000_003024, c1060 a000_003001 from the Sekiro-Resurrection folder and Owl's a000_003041, and Dark Souls III's c0000 a000_000000 and c5280 a000_003013. In the same clips the chain moved as one upright column standing on the foot: `*_Foot_Target2` stayed within 6.9 mm, horizontally, of the foot and within 1.8° of its reference rotation (0.06° on most rigs), while it moved up to 1.9 m from its rest position, and `*_Foot_Target1` and `*_Foot_Target` kept their rest offsets below it within 9.2 mm and 3.1 mm.
- Unit test: 1 new in `test_retarget_mapping.py`. On the owned FromSoftware-style rigs in both layouts with the chains added, `foot_targets` pairs `L_Foot_Target` with `L_Foot` and `R_Foot_Target` with `R_Foot` and lists the two bones above each, from the top. The body still finds `Pelvis` and its own feet, also in the layout whose `Master` hangs at hip height. A Mixamo rig has no foot targets, and a target without a foot on its side is left alone.
- New `blender_foot_targets.py`, on owned rigs with 24 frames. The target is an Elden Ring-style bridge rig with both chains, imported from a still synthetic clip that tracks every bone.
  - From a Mixamo-style source, whose left foot travels 0.77 m and turns by up to 92°, the targets stayed on the feet within 3.5e-05° and 3.4e-04 mm on every frame. The chains above them stood as upright columns: their rest pose, moved as one without turning to where the target sits, within 1e-4, measured as 0.0 mm, while the columns moved up to 1.40 m. That held with the travel left in the clip and with it taken out as root motion, which moved the feet by 0.80 m. The report listed both targets, and the status said they follow the feet.
  - From a FromSoftware-style source whose targets stand still while its feet move, mapped by name to the target's, the result was the same.
  - The export of a bridge rig after an edit in Blender: the left leg swings and the body travels on `RootPos`, while the targets keep the imported clip and `L_Foot_Target2` stands turned by 0.3 rad, which left the left foot 0.45 m from its target. Read back as the game builds the pose, the exported targets sat on the feet within 1.1e-05° and 1.5e-04 mm, also with root motion taken from `RootPos`, which moved the exported feet by 0.70 m. The chains were written as upright columns standing on the feet, within 1.2e-04 mm, so `L_Foot_Target2` stood upright again, and the columns moved up to 1.19 m. The export summary listed both targets.
  - Each part failed with its fix switched off on a scratch copy of the test: without the bake's step, the targets were 92.4° and 1.40 m off the feet; without the export's, 63.5° and 0.94 m. With only the columns switched off, so that the targets still copied the feet while the chains above them kept the clip, the chains left their columns by 1.32 m in the bake and 1.17 m in the export.
- Owl's a000_003041 onto Wolf, on the copy of the review scene used for the arm distance, opened without saving. Before, the bake mapped all six target bones by name and turned the targets within 1.9° of the feet, but left them up to 1.13 m (left) and 0.53 m (right) from the feet. Unmapped and set to *Rest pose*, the targets stood at rest, just as far away. With the fix, in all three cases, the targets stayed on the feet within 0.015° and 0.1 mm on all 52 frames, and the chains stood upright on them: `*_Foot_Target2` at its reference rotation and within 0.1 mm, horizontally, of the foot, and `*_Foot_Target1` and the targets at their rest offsets within 0.1 mm, while `*_Foot_Target2` moved up to 1.13 m. The 0.015° comes from evaluating the keyed bake in Blender, not from the step: it was the same with the columns switched off, and Owl's own clip has 0.33°. Exported with the bridge's exporter and read back, the targets sat on the feet within 1e-4° and 0.1 mm, with the chains standing upright on them in the same way.
- Not checked: game playback, so neither whether the game's foot IK reads the targets nor whether the reported foot flips stop; Elden Ring and Dark Souls rigs, which may have no such chains; clips without tracks for the targets, which the export leaves to the game; whether the 1.8° by which Wolf's clips turn `R_Foot_Target2` from its reference rotation matters, since the bake and the export write the reference rotation.

## Two characters from one import

- Unit tests: 7 in the new `test_two_character_import.py`. The donor shares the target's decoder, Oodle DLL and weapon placement and keeps its own inputs, never decodes weapon part clips, must be a set of input options, and reports its progress between 40 and 60 with "Donor:" before each message, also during its folder scan. Its warnings join the target's, marked as the donor's. A pinned donor is saved with the UI settings, reaches the job and is cleared by Remove.
- New `blender_two_characters.py`, on owned synthetic rigs. The target is an Elden Ring-style humanoid with 24 frames at 30 fps. The donor is a Souls-style humanoid 1.4 times larger with 40 frames at 60 fps, tagged as an Elden Ring clip. Both rigs are called c0000, both clips a000_003000.hkx, and each has a box mesh on its pelvis.
  - After the donor import, the donor's objects, actions, armature, collections and texts carried "Donor", and the target's names were unchanged. Each rig kept its action, its root-motion object and its own embedded clip, and the donor's action slots took the new names. The scene kept the target's frames 1–24 at 30 fps, its export rig and its active selection. The donor stood 1.22 m beside the target along X, moved by the delta location of its rig and its root-motion object; its root keys were unchanged, and the two meshes did not overlap.
  - Exporting the target gave the same motion JSON as a single-character import of it, and inspect listed the same actions, so the donor's action is not offered for export. A donor without a character model imported as well.
  - With the add-on registered, opening the saved file filled Source with the donor and Target with the target and said so in the status. A pair the user had started to choose was left alone. Bakes from the saved file with the donor at its imported place, at 0 and at −3 m gave the same target channels within 1e-5. After the bake the scene ran from 1 to 40 at 60 fps, and the target's export had 40 frames.
- Owl's a000_003041 onto Wolf's a000_000100, from the collected Owl (c5060) and Wolf (c0000) folders in this tool's `work\dcx-folders`, through the CLI with a scratch LOCALAPPDATA and TEMP. Every output stayed in the session scratchpad.
  - The import built Wolf (81 frames, 114 tracks, 4 model parts, 146 bones) and Owl as `Donor c5060` (52 frames, 112 tracks, 1 model part, 120 bones), 3.34 m apart along X: Wolf spans −0.41 to 0.36 m and Owl 1.13 to 4.20 m. There were no warnings, and the report held Owl's clip under `donor`. The donor's scan, decoding and character events read "Donor: …" at 42–56%. The first run showed the donor's folder scan without "Donor:" and at 5–8%, after the target's character at 32%; the runtime now passes the donor's progress to the scan, and a unit test covers it.
  - Names: collections `Sekiro - a000_000100`, `Sekiro | Character`, `Donor - a000_003041` and `Donor | Character`; actions `a000_000100_Sekiro`, `a000_000100_RootMotion`, `Donor a000_003041_Sekiro` and `Donor a000_003041_RootMotion`; texts `Sekiro Source - a000_000100.json` and `Sekiro Source - Donor - a000_003041.json` beside the two character reports; root-motion objects `HKX_RootMotion` and `Donor HKX_RootMotion`, with slots `OBDonor c5060` and `OBDonor HKX_RootMotion` on the donor. The scene ran from 1 to 81 at 30 fps with Wolf active and as the export rig, and inspect listed only `a000_000100_Sekiro`.
  - A copy opened with the add-on registered had Source `Donor c5060` and Target `c0000` filled. **Match bones automatically** and **Bake** with the defaults mapped 97 bones and baked 52 frames at a scale of 0.668 without warnings, with the note "R_Weapon is placed in R_Hand, where the source holds R_Katana." The scene then ran from 1 to 52, and inspect listed the baked action and `a000_000100_Sekiro`.
  - The CLI export of the baked copy used Wolf's embedded clip and wrote a Sekiro interleaved HKX of 52 frames and 114 tracks (300,436 bytes). The read-back differed by at most 0.0000° and 0.000 mm, with root motion within 0.000 mm.
  - The user guide's example named the clips without `.hkx`, which the folder catalog does not match ("Choose an animation from the scanned folder."). It now names them with the extension.
- UI, in the in-app browser with a scratch LOCALAPPDATA and TEMP and both folders as sources with their existing scans. With Owl's a000_003041 selected, **Use this animation as the donor** showed the donor card (`a000_003041`, "C5060 · Sekiro · Owl"). After switching to the Wolf source and choosing a000_000100, the card stayed, the button read **Replace the donor with this animation**, and the suggested scene was `c0000_a000_000100_from_c5060_a000_003041.blend` in the source's scenes folder. **Create Blender scene** finished in 18 s with "81 frames · 4 model parts · 45 material images · donor a000_003041, 52 frames", and with the same report and placement as the CLI. The donor stayed pinned after a reload. **Remove** cleared it from the settings, and the suggested name went back to `c0000_a000_000100.blend`. Pinning Wolf's selected clip and starting the import showed "This animation is the retarget donor. Choose the animation of the character that receives it, or remove the donor." and started nothing.
- Not checked: a donor from another game on real files, since the Elden Ring donor is synthetic; a donor from extracted files (`-DonorAnimation`) or from a game folder on real files; the add-on filling the pair in an interactive Blender session, checked only with `open_mainfile` in background mode, which runs the same handler; Blender versions other than 4.5.14; game playback of the baked clip.

## Weapon part animations and clip preview

- Unit tests: 15 in the new `test_part_animations.py`, on owned synthetic data. TAE reading covers entries with their own HKX, another ID's HKX and a reference, with category offsets, and gives nothing for an unknown version or another file. Reference chains resolve and a cycle ends. Clip choice covers the same ID, an ID that plays the same body clip in a Wolf-style TAE with the part's own category first, a redirect in the part's own TAE, and the rest pose. Plan and prepare run on BND4 part binders built in memory with Soulstruct: a nested animation binder with skeleton, compendium, TAE, clip and rest clip, a second model with only a rest clip, and an outfit binder that is never opened. The decoded clip lands in the manifest, the rest row is reported and not keyed, and a clip with a track that the model lacks keeps the rest pose with a notice. The character binder and TAE are found from a synthetic catalog. The preview's joint positions follow rotation and scale, and a bone far from the body is left out.
- New `blender_part_animations.py`, on an owned weapon with six FLVER bones and a 30 fps part clip of 5 frames in a 60 fps scene. The clip's skeleton puts `W_Tip` under `W_Root`, where the FLVER has it under the FLVER-only `W_Mid`, and `W_Flap`, which has no track, under `W_Wing`, where the FLVER has it under `W_Root`. It also holds `W_Extra`, which the FLVER lacks, and grows `W_Wing` to 1.4 times its size.
  - The weapon rig got all six FLVER bones and not `W_Extra`. The action `WP_A_9990_1 | a076_405010_1` keyed `W_Root`, `W_Wing`, `W_Tip` and `W_Flap` on frames 1, 3, 5, 7 and 9. On each of them every bone matched the skeleton's pose within 5.4e-7, and the FLVER-only `W_Tassel` followed `W_Flap` at its rest offset.
  - A second character marked as the bridge's, `Owned donor`, imported with the same weapon and part clip, got its own animated weapon rig. Only the export rig's weapon was exported.
  - The export over frames 1–9 gave the clip's 5 samples at 30 fps within 4.8e-7, and over frames 1–5 its first 3. The weapon rig was hidden again afterwards. After saving and opening the .blend, the export matched within 4.8e-7 again.
- Real data, read only from the unpacked game through the Sekiro source's catalog, with a scratch LOCALAPPDATA and TEMP; every output stayed in the session scratchpad, and the real settings files kept their timestamps. CLI imports of Wolf with his four body parts, the Loaded Umbrella (`wp_a_0760`) and the Loaded Axe (`wp_a_0730`):
  - `a076_405010`: `WP_A_0760_1` played `a076_405010_1` (same ID; 34 frames at 30 fps, 76 tracks), and `WP_A_0760` and `WP_A_0730_1` held their rest pose.
  - `a070_412000`: `WP_A_0760_1` played `a076_412000_1` ("TAE of C0000: a076_412000 plays a070_412000"), and `WP_A_0730_1` played `a073_412000_1`, 41 frames at 30 fps each.
  - With `-NoPartAnimations`, no part clip was decoded or keyed.
  - CLI exports with `-ExportParts`, interleaved: `a076_405010.hkx` with `a076_405010_1.hkx` (136,740 bytes), and `a070_412000.hkx` with `a076_412000_1.hkx` and `a073_412000_1.hkx`. Each part read back within 0.0000° and 0.000 mm. Each written part clip, decoded with the part's own skeleton, had the game clip's frame count, rate and tracks (76 and 6), with rotations within 0.0000° once the game's quaternions are normalized, translations within 0.000 mm and scales within 0.00001. The game stores part clip quaternions up to 0.435% off unit length; compared without normalizing, they seemed up to 10.7° apart. After the part export was limited to the export rig's weapons, both exports gave byte-identical files again.
- UI, in the in-app browser with a scratch LOCALAPPDATA holding copies of the settings and sources:
  - The preview of Wolf's `a000_000302` first framed his camera dummy `z_dummy_camera`, 4.4 m from the body, which left him small in a corner of the canvas. The preview now leaves such bones out, and a new unit test covers it. Previews cached by the first version are not reused.
  - With `a076_405010` chosen and `WP_A_0760` added, the block listed "WP_A_0760_1 a076_405010_1 same ID" and "Rest pose: WP_A_0760", and **Animate weapon parts** showed under **Save scene as**.
  - In the narrow scene panel, the time label ran into the **Root motion** checkbox. The time now sits below the slider.
  - The export page showed **Also export part animations** with its note.
  - The user reported that, for some clips, the preview stood still after the animation was chosen until the block was closed and opened again, with the time near −0.2 s. Reproduced by running `ClipPreview.show()` at the end of a 200 ms task while frames were being drawn: the label read "Frame -5 of 34 · -0.19 s", the slider stayed at 0 and drawing threw `TypeError: Cannot read properties of undefined (reading '0')`, which ended playback. Chromium stamped the first frame before the `performance.now()` taken when play began, so the time ran back to a negative frame. Playback now starts its clock on the first frame and never runs time back. With a stubbed frame clock that stamps the first frame 200 ms early, the preview read 0.00 s, then 0.17, 0.33 and 0.50 s at 60 Hz, kept 0.50 s on a frame stamped earlier still, and threw nothing.
- Not checked: game playback of an exported part clip; edits to a part clip in Blender beyond the round trip; a part clip whose frame rate differs from the scene's on real files, since the tested part and body clips are all 30 fps; parts of other games; the preview in a packaged release.

## Browse: the bridge stays in front

- The user reported that the bridge window sometimes went behind other windows after a selection in a Browse window. The picker shows each dialog from its own PowerShell process, owned by an invisible, topmost proxy form that the bridge window owns. A probe of that form, created without being shown, read style `0x06010000` and extended style `0x00090008`: topmost and layered, but not `WS_POPUP` (checked). When an active window that is not a popup closes, Windows does not prefer its owner and can activate the next window in the Z order, which may belong to another application (inferred, as Wine and ReactOS model the window manager). The picker now calls `SetForegroundWindow` on the bridge window before it closes the proxy. Without the foreground, as after **Cancel Browse** in the page, the call changes nothing.
- `native_picker.cs` compiles with `Add-Type` as `native_picker.ps1` loads it. Apart from the windows it opens on request (Explorer, Blender), every process that the UI server starts hides its window, so nothing else takes the foreground after a selection.
- Not checked: a Browse in the running bridge with real clicks; the intermittent push was not reproduced here. Automated input does not give the picker the foreground that a user's click does, and a test dialog would have covered the user's desktop.

# Version 0.8.0 — 2026-10-24

- Unit tests: 70 pass, 1 of them new in `test_retarget_mapping.py`. On an owned FromSoftware-style rig with a katana, a gun, a katana parked on a wire bone, a spear and storage bones, `R_Weapon` takes the katana as the weapon in the matched hand, `L_Weapon` stays unassigned when the left hand's weapons are hidden, and no hidden or storage bone is taken. Without the list of hidden bones, `R_Weapon` stays unassigned. Python sources compile and `app.js` passes `node --check`.
- Blender 4.5.14 with `--factory-startup`: `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py`, `blender_control_rig.py` and `blender_weapons.py` pass as before.
- New `blender_weapon_clearance.py`, on an owned Elden Ring-style skeleton. The source's sword lies along its weapon bone's Y axis and the target's along its socket's X axis; the source also has a gun keyed at scale 0, and the target is 1.25 times larger with a box torso, box hands and a sword on the bridge weapon socket. The matcher left out the hidden gun and mapped `R_Weapon` to the katana. The bake turned `R_Weapon` by 90°, and the blades stayed parallel within 0.000° on every frame. A two-handed grip close to the body put the plain bake's hands and sword into the torso on frames 20–52. With **Keep hands out of the body**, no point of the hands or of the sword near them was inside on any frame; the source had no torso to compare with, and the status said so. The hands moved by up to 12.5 cm, at most 1.68 cm from one frame to the next, and alike within 0.1 mm while close together. 15 frames, among them 1–3 and 70–72, matched the plain bake within 1e-5. Then the source got hands and a torso whose front lies 5 cm behind the target's, and its hands and sword went 3.8 cm into it during the hold. The target kept 4.7 cm there, the source's depth at 1.25 times the size, within 1.3 mm on frames 30–42, where the plain bake had 11.0 cm. The depth in the report matched the measured one within 2 mm, and frames where only the target clipped were cleared.
- Copies of the supplied Isshin source and Wolf target scenes, originals untouched; Isshin's clip (106 frames) baked onto Wolf with the defaults. **Match bones automatically** mapped `R_Weapon` to `R_Katana` ("Weapon in the matched hand") and left `L_Weapon` unassigned, since the clip hides `L_Gun` and `L_Yari`. The bake turned `R_Weapon` by 5.8°.
  - A separate ray test against Wolf's torso mesh, outside the add-on, measured the sword within 30 cm of the right hand. Without clearance it went up to 5.0 cm into the torso on 38 frames (39–76). The add-on's own test, sampled every 6 frames, put the left hand up to 9.5 cm and its fingers up to 7.5 cm inside. With clearance measured against Wolf's body alone, as first built, the left hand moved on frames 26–95 and the right on 26–90, both by up to 10.6 cm, and no sword point stayed inside; renders of frames 40, 44 and 48 show both hands on the hilt in front of the sash.
  - Keeping the source's own clipping: Isshin's left hand goes up to 4.8 cm into his kimono on frames 38–70, as the distance of its deepest point to the nearest surface, and his right hand and katana up to 3.0 cm at frame 41 and up to 1.6 cm otherwise. With the defaults, both of Wolf's hands moved by up to 7.6 cm, and the status reported up to 0.7 cm kept on the left and 0.6 cm on the right. The separate ray test put the sword up to 1.0 cm inside on frames 64–70, where Isshin's hilt touches his sash, and nowhere else. Both hands are on one hilt and move together, so Wolf's left hand keeps less than Isshin's. Measuring the source by its way out along one direction instead gave Isshin's left hand up to 11.7 cm, the hand's extent behind the kimono front, and would have allowed Wolf's up to 7.9 cm.
  - Placing mapped bones at the source's bone positions instead, in patched scratch copies of the add-on without clearance: with all bones, the sword went 2.1 cm in on 1 frame, the left hand still up to 7.0 cm, and Wolf's torso was visibly stretched; with only the spine, neck, head, clavicles and upper arms, the sword went 6.1 cm in and the left hand 8.3 cm.
- Before tagging, a ZIP packaged as the workflow does, without the decoder and uv (65 files), passed the 70 unit tests from its unpacked folder; its `SekiroRetargetAssistant-0.4.0.zip` holds the add-on at version 0.4.0.
- Tagged run 40135633468 (v0.8.0, commit 3a6337c, windows-2025 runner) built the decoder and the release ZIP (276 files, 65,638,660 bytes). On a fresh profile the first start downloaded Python 3.13.16 and installed the 15 pinned packages; the UI reported the conversion libraries, the decoder and DCX ready and selected the packaged decoder. With the Visual C++ 2010 runtime installed, the 70 unit tests passed from the unpacked ZIP. The run published the release: `SekiroAnimationBridge-0.8.0-win-x64.zip` (65,638,660 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.4.0.zip` (57,921 bytes).
- Not checked: game playback of a clip baked with clearance; other source and target pairs on real scenes.

# Version 0.7.1 — 2026-10-24

- Unit tests: 69 pass, 3 of them new in `test_sources.py`, on owned synthetic folders. An earlier folder hides a file of the same name (any case, with or without `.dcx`) only when that file is actually read, copies within one folder stay, and the dialog's counts agree. A custom layout with a mod folder before the game folder takes the mod's animation archive, model, part, c0000 rig attachment model and material library. A tie between material libraries follows folder order. Each new test fails on 0.7.0's code.
- `prepare_character` with owned empty files and a stubbed FLVER reader listed 3 of 5 texture packages in a mod folder and a game folder: the mod's 2 packages hid the game's packages of the same names.
- Python sources compile and `app.js` passes `node --check`. Blender 4.5.14 with `--factory-startup`: `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py`, `blender_control_rig.py` and `blender_weapons.py` pass.
- Before tagging, a ZIP packaged from main as the workflow does, without the decoder and uv (64 files), passed the 69 unit tests from its unpacked folder.
- Tagged run 40122167539 (v0.7.1, commit cc89448, windows-2025 runner) built the decoder and the release ZIP (275 files, 65,605,248 bytes). On a fresh profile the first start downloaded Python 3.13.16 and installed the 15 pinned packages; the UI reported the conversion libraries, the decoder and DCX ready and selected the packaged decoder. With the Visual C++ 2010 runtime installed, the 69 unit tests passed from the unpacked ZIP. The run published the release: `SekiroAnimationBridge-0.7.1-win-x64.zip` (65,605,248 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.3.0.zip` (47,199 bytes).
- Not checked: a real mod folder over the unpacked game in the UI (no mod folder was available).

# Version 0.7.0 — 2026-10-24

- Unit tests: 66 pass, 21 of them new in `test_sources.py`. On owned synthetic folders (empty files with game names) they cover game folder detection by executable, by Elden Ring's material library, through a `Game` subfolder and from a chosen `chr` folder; collected folders; a folder of games; owners of split archives; backup folders; custom folders relative and absolute with the count limit; the index of a game folder (characters, models, references, parts, texture folders, skipped unnamed archives); carry-over of a read character until its archive changes; custom layouts; structured selection of an NPC model and the Wolf preset; the migration of a single assets folder; and sources that survive an older bridge rewriting `ui-settings.json`. After a restart, the scratch UI moved its sources into `ui-sources.json` and restored the active source and selection. Python sources compile, `app.js` passes `node --check` and the CLI script parses.
- Blender 4.5.14 with `--factory-startup`, after merging the control rig: `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py`, `blender_control_rig.py` and `blender_weapons.py` pass.
- UI, in the built-in browser against a scratch `LOCALAPPDATA`: the unpacked Sekiro install was detected as a game folder by `sekiro.exe`, also when its `chr` folder was chosen, and listed 86 characters in 137 archives. Reading C5060 listed 155 animations; C0000's 44 archives with 1,434 animations took about a second, and Wolf's preset selected 4 of 4 parts. A collected folder of supplied Owl and Wolf archives listed 2 characters and 339 animations. Switching sources restored each one's character, animation and output file. Light and dark themes and widths of 1024, 900 and 760 pixels were checked.
- Custom layout: Owl's animation archive from a collected folder, with model, textures and material library from the game folder. The dialog counted 1 animation archive, 129 models, 134 parts, 128 texture packages and 1 material library, and marked a folder that did not exist. Importing a000_003011 from it (output in the session scratchpad) took 5 seconds: 86 frames, 1 model part and 22 material images, with 3 of 128 texture packages read and no notices. In Blender, the scene has frames 1–86 at 30 fps, the 120-bone c5060 armature with action a000_003011_Sekiro, 1 mesh, 23 materials and 22 packed images.
- CLI, also with a scratch `LOCALAPPDATA`: `import -AssetFolder <Sekiro>\chr -SourceLayout auto -AssetCharacter c5060 -AssetClip a000_003011.hkx` used the game folder and wrote the scene: 86 frames, 112 tracks, 1 part with 82,183 vertices, 22 textures, no warnings. `discover` with `-SourceLayoutFile` for the custom layout above found 1 character in 1 archive.
- No file under the game's `chr`, `parts` or `mtd` folders changed during these runs. The real `ui-settings.json` was not used, and the real `bridge-location.json` still points to the main checkout.
- Sources, not checked: unpacked Dark Souls or Elden Ring game folders (none available; their layouts are covered by the synthetic tests), screen readers, and game playback.
- Control rig, checked on main before the merge: unit tests: 45 pass. Python sources compile and `app.js` passes `node --check`. Blender 4.5.14 with `--factory-startup`: `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py` and `blender_weapons.py` pass as before, so the exporter's and the retarget's control rig handling changed nothing for rigs without one.
- New `blender_control_rig.py`, on an owned Elden Ring-style skeleton with randomly turned rest frames (67 bones, 24 frames). Three limbs bend around their rest hinges and the right forearm also twists; a muscle helper is scaled unevenly, and a face bone lies almost along its parent's -Y axis. Adding the control rig (76 controls, 0.05 s) kept every game bone within 5.7e-6 m and 3.6e-4° at every frame in FK, and the export matched the export from before within 4.5e-6. In IK, elbows, knees, hands and feet stayed within 5.3e-5 m and 0.001°; limbs that bend around their hinges stayed within 0.006°, and the twisted forearm differed by 28.2°, as expected. After an FK edit, switching the left arm to IK kept its joints within 3.1e-5 m, and switching back within 6.2e-7 m. Removal restored the original action exactly, or kept the edited motion within 4.9e-6 m and 4.6e-4°. The test also covers the operators, keyed controls of untracked bones (added with the keyed track set, warned about otherwise), **Read actions**, the export refusal for an action that does not move the controls, the retarget refusal, and FK-only controls on a skeleton without arms or legs.
- Mutation checks: with the socket rest correction disabled, the FK check failed at 0.0058°; without the handling of unevenly scaled bones, at 0.82°.
- Copies of supplied Sekiro scenes, originals untouched: c0000 a000_000403 (146 bones, 57 frames, 155 controls, 0.3 s) and c5400 a000_003000 (199 bones, 91 frames, 208 controls, 0.5 s). Both rigs got IK on both arms and legs, and no game bone's rest matrix changed. In FK every game bone stayed within 0.0001°, and the exports matched those from before within 2.4e-6 and 5.1e-6. IK kept the joints within 0.09 mm and the hands and feet within 0.0002°, and removal restored the original pose within 1e-5°. This run found two cases that are now handled: Wolf's pectoral helpers are scaled unevenly by up to 16%, which a control turned along the limb cannot carry (the export differed by 0.028), and face bones that rest almost along their parent's -Y axis, where Blender snaps rest matrices, were 0.0128° off.
- In Blender's UI, on a scene copy opened for screenshots and not saved: the controls draw in front of the mesh; the Control rig panel shows its sliders, switch buttons, group toggles and remove button; and **Switch to IK** set the left arm's IK influence to 1 without moving the arm.
- Control rig, not checked: dragging an IK slider by hand (Blender tags the armature for a driver update when a custom property changes in the UI, and the switch operator tags it explicitly); game playback of clips exported from a control rig; Blender versions other than 4.5.14.
- Before tagging, a ZIP packaged from main as the workflow does, without the decoder and uv, passed the 66 unit tests from its unpacked folder with TEMP on an 8.3 short path.
- Tagged run 40117745046 (v0.7.0, commit 000daa4, windows-2025 runner) built the decoder and the release ZIP (275 files, 65,602,947 bytes). On a fresh profile the first start downloaded Python 3.13.16 and installed the 15 pinned packages; the UI reported the conversion libraries, the decoder and DCX ready and selected the packaged decoder. With the Visual C++ 2010 runtime installed, the 66 unit tests passed from the unpacked ZIP, with TEMP under the runner's 8.3 short name. The run published the release: `SekiroAnimationBridge-0.7.0-win-x64.zip` (65,602,947 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.3.0.zip` (47,199 bytes).

# Version 0.6.1 — 2026-10-24

- Unit tests: 45 pass. Python sources compile, `app.js` passes `node --check`, and the four PowerShell scripts parse without errors.
- Setup: `tools\setup_writer.ps1` with uv 0.12.23 created a writer environment in a scratch profile, offline from uv's cache: Python 3.13.16 and the 15 pinned packages, the same versions as the development environment. `soulstruct.flver`, `soulstruct.havok` and NumPy import. The run also passes with all output redirected, after a fix: Windows PowerShell had turned uv's progress messages on stderr into a fatal error.
- Release ZIP built locally from the installed decoder and uv: 271 files, 65,168,617 bytes, without CompressAnim, `work/` or game files. From the unpacked ZIP on the scratch profile, `Start Animation Bridge.cmd --no-browser` repeated setup because the pinned list had changed (15 packages checked), then started the UI. The UI reported the conversion libraries and the packaged decoder ready, selected that decoder, and shut down on request. The packaged decoder decoded a supplied Sekiro clip (a000_000100: 81 frames, 114 of 114 tracks mapped, root motion included).
- First release workflow run (40103620749): the decoder build, packaging and first start passed, but 8 unit tests failed. Seven spline tests stopped with `0xC0000135` (STATUS_DLL_NOT_FOUND): Soulstruct Havok's `CompressAnim.exe` is a 32-bit program that imports `MSVCR100.dll`, which a clean Windows does not have. The eighth compared a path with TEMP's 8.3 short name. The bridge now names the missing Visual C++ 2010 runtime, Settings shows it as an optional check, and the test compares resolved paths.
- Release workflow run 40104682098 (manual, commit a52fdd6, windows-2025 runner): built the decoder and the release ZIP (271 files, 65,176,461 bytes), unpacked it and started `Start Animation Bridge.cmd --no-browser` on a fresh profile. The first start downloaded Python 3.13.16 and installed the 15 pinned packages. The UI reported the conversion libraries, the decoder and DCX ready (with the Oodle DLL that comes with Soulstruct) and selected the bundled decoder; the Spline compression check reported the Visual C++ 2010 runtime missing. After the step installed Microsoft's `vcredist_x86.exe` (Authenticode signature valid, Microsoft Corporation), all 45 unit tests passed, including spline export for Sekiro, DS3 and Elden Ring.
- Tagged run 40105861748 (v0.6.1, commit e4289a0) passed the same first-start checks and unit tests and published the release: `SekiroAnimationBridge-0.6.1-win-x64.zip` (65,446,240 bytes, with its `.sha256`) and `SekiroRetargetAssistant-0.2.0.zip` (32,564 bytes).
- README screenshot: taken from a temporary install packaged from this tree, after a folder scan of supplied Owl archives (1 archive, 155 animations). Not a test of Blender import.

# Version 0.6.0 — 2026-10-24

- Unit tests: 44 pass with the conversion Python (`unittest discover -s standalone/tests`), including the new matching tests on owned synthetic humanoid rigs (`standalone/tests/humanoids.py`). Python sources compile; `app.js` passes `node --check`.
- Blender 4.5.14 with `--factory-startup`: `blender_retarget.py` (limb directions within 0.0000°, body travel, connectors, unmapped-bone modes, repeat bakes, all root-motion modes, bridge export from the carrier bone), `blender_export_options.py` (defaults, track sets, parent compensation, frame ranges, resampling, root extraction, takes, inspect), `blender_synthetic_check.py` and `blender_weapons.py` (two owned weapons, maximum socket error 5.3e-7) all pass. A negative control confirmed that the retarget test fails when untouched bones are compared with identity instead of their unanimated pose.
- Writer: an owned two-bone clip went through `build_animation.build` for Sekiro, DS1, Remastered, DS3 and Elden Ring, interleaved and spline, with and without root motion: 15 of 15 written and read back. Interleaved is exact; spline differs by at most 0.0266° and 1e-6 in position; root motion is identical. Earlier in this release, a real DS3 clip wrote back exactly (interleaved) and within 0.16° (spline), and written Sekiro, Remastered, DS3 and Elden Ring files decoded through the bridge's SoulsAssetPipeline decoder with exact interleaved data, about 0.16–0.19° spline difference and identical root motion.
- Matching, synthetic: 15 rig conventions (Mixamo, Unreal, 3ds Max Biped, VRoid, Character Creator, Rigify, Daz, two FromSoftware styles, and six of these with scrambled bone names) in every pairing: 10,710 of 10,710 core assignments correct.
- Matching, supplied rigs: skeletons read from the supplied scenes, matched with scrambled bone names. All 52 core bones matched for most pairs. Dark Souls 1 targets matched 38 of 39 (c0000) and 50 of 51 (c5370); c5370 as source matched 50 of 52. Each miss is a spine bone where the spines differ in length. The rig dumps stay outside the project; tests use owned fixtures only.
- Full pipeline on copies of the supplied scenes (originals untouched): DS3 c5280 a000_003002 onto ER c0000 a000_004000 matched 30 of 42 rows (RootPos from Root), baked 104 frames in 0.6 s with travel scale 0.574, root motion from the source, carrier RootPos and 42 keyed bones (the clip's tracks), limb directions within 0.000°. Export: interleaved 437,408 bytes, read back within 0.000° / 0.00 mm; spline 28,904 bytes, within 0.156° / 1.01 mm. Sekiro c0000 a000_000403 onto Remastered c5370 a00_3015 matched 59 of 296 rows (cloth and helpers stay unmapped), carrier Pelvis, travel scale 1.412, 296 tracks. Export: interleaved 835,372 bytes, exact; spline 65,068 bytes, within 0.240° / 2.00 mm.
- The add-on ZIP was installed into an isolated Blender profile in a scratch folder. It reported version 0.2.0, found the bridge through `bridge-location.json`, and repeated the ER bake and export with the same result. The user's installed 0.1.0 add-on was not changed.
- UI, in the built-in browser, against a scratch copy of the settings: export options, **Read actions** on a scene copy (root bone default RootPos), the missing-game notice, and the Settings cards. The real `ui-settings.json` was unchanged afterwards (same SHA-256).
- Not checked: game launch or in-game playback of any 0.6.0 output; Blender versions other than 4.5.14. This final run covered weapon placement through unit tests and the owned fixture only; check the Elden Ring sword and scabbard in your own scene after switching to **Auto**.

# Version 0.5.1 weapon correction

- User supplied a failed DS1 import log: decoder produced skeleton=Master, 21 frames / 61 tracks, and body parts were prepared, then the literal c0000 skeleton-name guard rejected the selected weapon. The guard was located and removed; validation now uses actual bone names supplied by bridge_runtime.
- Read original WP_A_0201 binders and c0000 references from DS1 and DS3. Each supplied package contains main sword member 0 and scabbard member 1. DS1's reference has R_Weapon/L_Weapon and the named R_Wepon_Case/L_Wepon_Case nodes; DS3's hand dummies 20/21 target R_Weapon/L_Weapon and case dummies 31/30 follow Pelvis. Full records: work/other_games/weapon-input-inventory.json.
- Read the actual animation skeletons as source metadata: DS1 has 61 bones, DS3 has 110. Both include the weapon and case bone names. work/other_games/player-skeleton-names.json records the names; no animation was sampled by that reader.
- Inspected DSAnimStudio NewChrAsm.cs for old-game direct weapon-bone attachment versus newer dummy attachment and old-game orientation flips: https://github.com/Meowmaritus/DSAnimStudio/blob/master/DSAnimStudioNETCore/NewChrAsm.cs . DS1's scabbard preview uses its supplied named case node; DS3's static hip preview uses the supplied dummy. These are preview choices, not checked absorption-param/TAE playback behavior.
- Parsed Python and JavaScript syntax. No new unit/regression tests, Blender import/render/round trip or game launch was requested/performed for this correction. The old failing guard is absent by source inspection, but new placement appearance still needs the user's retry. Existing Blender scenes were not modified.
- Saved 0.5.0 source/ZIP/settings under Documents/SekiroAnimationBridge-Archive/before-ds-weapons-20261023. No dependency install/download or decoder rebuild was needed.

# Version 0.5.0 extension — 2026-10-23

- Read the supplied Other Fromsoft Games/DS1, DS3 and ER archives with the existing Binder/FLVER/TPF dependencies. Read-only inventory is in work/other_games/input-inventory.json; source assets were not changed. DS1 examples are Remastered HK2015 tagfiles, DS3 uses HK2014 PC packfiles, ER uses HK2018 tagfiles. Their player c0000 FLVERs have zero visible meshes.
- The user subsequently added DS1 9490 parts, Mtd/MtdPatch and common TPFs; DS3 5400 parts and its MTD binder; ER c2190 high/low TEXBNDs, followed by base/DLC MATBIN libraries. Production discovery was refreshed: 15,952 clips / 47 archives / six distinct game-character entries and no scan warnings.
- Actual model/material/TPF reference inspection (work/other_games/material-inventory.json) finds available base-color images for 16/16 DS1 player slots, 21/21 DS3 player slots, 15/15 DS3 c5280 slots, 19/21 ER player slots, 14/26 ER c2190 slots and 0/22 DS1 c5370 slots. All selected ER definitions resolve with the MATBIN addition. Some c2190 effect shaders have no albedo sampler. Missing DS1 character textures and ER shared AAT textures are reported. These counts do not establish Blender appearance, deformation or playback.
- Parsed Python source syntax and checked app.js syntax. Compiled decoder 0.5.0 locally against the existing pinned dependency assemblies and installed its DLL after saving the previous one. No dependency download/install or fresh SDK/Git build was performed.
- No new unit/regression tests, Blender scene creation, round trip, UI rendering or game launch were requested or performed for 0.5.0. Native-version export routing and MATBIN materials are implemented but have no new end-to-end evidence. Earlier evidence below applies to prior Sekiro versions.
- Actual production folder discovery performed to prepare the UI, if recorded in work/other_games/folder-scan.log, is input matching only. It is not animation decode, mesh deformation, material appearance or playback evidence.

# Evidence — Sekiro Animation Bridge

## 0.4.1 Wolf weapon repair — 2026-10-23

- Reproduced the report in the user’s saved c0000_a000_000202.blend: the WP_A_0310 blade and scabbard had identical evaluated vertex coordinates at frames 1, 41 and 81. Their local bones had been added as unrelated roots of the main rig.
- Checked the vanilla index’s EquipParamWeapon model/absorption IDs, WepAbsorpPosParam 5000 and 7000–7900, and the actual c0000 FLVER dummy transforms. Inspected DSAnimStudio’s NewDummyPolyInfo/NewChrAsm/NewEquipSlot_Weapon sources for the reference/follow transform and Sekiro weapon basis/slot conventions. Sources: https://github.com/Meowmaritus/DSAnimStudio/tree/master/DSAnimStudioNETCore .
- All 21 Python regression checks passed. The new owned Blender fixture verified two independent weapons sharing the bone name Blade00, nontrivial character/object transforms, animated sockets and FLVER XZY rotation equivalence. Maximum sampled world-position error: 5.34e-7; no weapon bones entered its main rig.
- Re-imported a000_000202 (81 frames / 112 tracks) and a000_030000 (145 frames / 110 tracks) with full Wolf, katana/scabbard, Mortal Blade/scabbard and a prosthetic. All five pieces followed their sockets at sampled frames; attachment matrix differences stayed below 3.0e-7. Main skeleton stayed at 146 bones. Rendered front/back previews were inspected.
- Broader placement coverage: all 30 high-detail packages with an automatic profile produced 58 visible model pieces. All had finite sampled geometry and followed their sockets over frames 1/40/80/120/145 of the second clip. Maximum attachment error: 1.28e-6; minimum sampled vertex displacement: 0.1026 game units. This checks following, not each prosthetic’s deployed shape or event state. WP_A_0300_2 is a skeleton-only reference; WP_A_0751_2 had one missing base-color image notice in this broad preview.
- Exported the first fixed scene to interleaved and spline HKX. Binary readback retained c0000, all 112 track names/indices, 81 frames and 81 root-motion samples. The weapon import introduced no body translation changes relative to the saved baseline export.
- A separate repaired copy of the user’s saved scene retained every sampled body translation, rotation and scale exactly (maximum difference 0), with identical track map, frame count and root motion. Legacy unused preview bones were retained in that copy to avoid editing custom rig additions; they are not exported as animation tracks.
- Isolated loopback UI check: reference auto-detection, saved placement-map persistence/restoration, and all 36 weapon selectors rendered in installed Chrome headless. Edge’s headless CLI returned no artifacts, so no Edge-specific headless UI claim is made. Production UI/Blender sessions and production settings were not changed by these checks.
- No game launch or new gameplay confirmation. Draw/sheath event switching, weapon-local animations, mechanism deployment, visibility masks, unknown cutscene props and final game shader reproduction are not verified by the attachment checks.
- Evidence and repaired files: work/weapons_review. 0.4.0 source/ZIP/settings safety copy: Documents/SekiroAnimationBridge-Archive/before-wolf-weapons-20261023. Game-derived files remain excluded from releases.

## 0.4.0 folder import — 2026-10-23

- Current source and launchers were compiled for Python syntax; the UI JavaScript passed Node’s syntax check. Decoder 0.4 was compiled against the already installed dependencies and installed locally. The fresh SDK/Git dependency build was not repeated.
- Created real local usage examples under `work/dcx-folders/Owl` and `work/dcx-folders/Wolf` by copying original archives read only. No game data is included in the source release.
- Ran the new discovery command on those example folders: Owl’s ANIBND yielded 155 clips with its skeleton and matching compendium; Wolf’s base and a000_lo ANIBNDs yielded 184 clips with the base skeleton and correct animation compendiums. Every discovered clip in those two catalogs had its required input references resolved.
- The Owl catalog selected c5060 as the matching model and found the supplied allmaterialbnd library; c5069 TEXBND and common_body remain texture inputs resolved through material references. Wolf’s catalog found the four standard part binders. Texture conversion and Blender scene creation continue through the existing shared runtime.
- “Input references resolved” does not attest that all these clips decode: unsupported float tracks/additive clips remain rejected. No new formal regression suite, Blender round-trip run, codec compression run or game check was requested or performed for 0.4. Older evidence below applies to the earlier pipeline versions.
- The installed plugin’s bridge source was inspected for DCX/DFLT/KRAK and Oodle handling. The standalone implementation uses Soulstruct’s existing codec, with a bounded DFLT header fallback; the whole modding plugin is not a dependency.
- Rollback copy: `~/Documents/SekiroAnimationBridge-Archive/before-dcx-folder-20261023`, including original 0.3.1 source, ZIP/checksum, user settings and decoder DLL.

# Version 0.2 verification — 2026-10-23

These are local conversion and Blender checks. They are not a new Sekiro gameplay confirmation.

## 0.3.1 retargeting prototype demonstration

The optional add-on was registered in a temporary Blender 4.5.14 session to generate `work/retarget_review/Owl_to_Wolf.blend`. It appended Owl's source collection, metadata and root object into Wolf's scene, matched 96 of 114 target animation tracks, and baked a separate 52-frame target action. The map and bake report are in the same folder. Eighteen unmatched target tracks retain target animation; no guesses were forcibly assigned.

The saved combined scene exported through the bridge. Binary readback identified the receiving Wolf skeleton c0000, 52 frames, 114 tracks and 52 root-motion samples. Rendered frame 1 and frame 26 previews show the receiving mesh posed by the new action. No formal new retargeting regression suite or game check was run. FK transfer can require cleanup for contacts, rest-stance differences, weapons and differing proportions. The add-on was not persistently installed.

## 0.3 NPC checks — Owl/c5060

- Blender 4.5.14 LTS; decoder rebuilt locally with the NPC skeleton-compendium fix against the existing pinned dependencies.
- Original `a000_003041.hkx` imported through CLI and UI with its own skeleton and compendium: 52 frames, 112 tracks, 120 bones.
- One FLVER: 82,183 vertices, 101,747 triangles, three UV layers and 21 packed used texture images. Armature skinning and visible mesh motion were checked. No missing-material-image notices occurred. Textures were resolved from c5069 and common_body packages, including alpha-tested fur cutouts.
- A separate Blender test scene added a seven-degree local Spine1 rotation at frame 26. Interleaved readback retained 7.000005 degrees; spline retained about 6.97131 degrees. The production tool has no canned animation-edit action.
- Both output formats decoded and re-imported with the complete character. Track names, track-to-bone mapping, frame counts and root motion were retained. Unmodified interleaved round-trip maximum translation difference was 7.7e-7 game units. Edited spline readback differed from sampled transforms by at most 0.000996 game units and 0.2073 degrees.
- UI import and spline export succeeded. Saved explicit-model selection and NPC folder auto-detection were checked. No four-part requirement or Wolf-part notice appeared in NPC mode. Wolf outfit discovery still selected four body parts.
- UI layouts at 1440, 1000 and 520 px had no horizontal overflow or browser script errors. Twelve owned synthetic Python checks and the Blender synthetic regression check passed.
- Local integration reports, source/output checks and rendered previews are under `work/npc_review`. Game-derived files are excluded from the release ZIP. Other NPCs and NPC in-game playback have not been verified.

## Environment

- Windows; Blender 4.5.14 LTS.
- Pinned Soulstruct 2.6.0, Soulstruct Havok 1.5.0 and NumPy 2.5.3 in the prepared Python environment.
- Decoder 0.2.0 compiled against the existing pinned SoulsAssetPipeline dependencies. The normal fresh SDK/Git dependency build was not repeated on this machine, which has the runtime but no .NET SDK.
- Blender 5.2 was not available and is not claimed as verified.

## Character checks

| Check | Result |
| --- | --- |
| UI import of Wolf `a000_000100.hkx` | Passed: 81 frames, 114 tracks, four skinned model objects |
| Default full character | 121,165 vertices, 160,026 triangles, 45 used images packed into the scene |
| Tutorial preset | Four parts imported through the Windows CLI launcher |
| Mortal Blade preset | Four parts imported through the Windows CLI launcher |
| Original unpacked game parts folder | Read directly; correct material library and shared textures found automatically |
| Paths with spaces and Unicode | Import saved successfully under a path containing spaces and Ω |
| All 20 local Wolf part/variant binders | Geometry extracted and assembled together in Blender; 461,336 vertices, 626,563 triangles, 140 images, no missing-material notices |
| Skin evaluation across the clip | All 20 parts produced finite evaluated geometry, normalized weights and visible animation displacement |
| Alternate cutscene bind poses | Three driven bind adapters created for AM_M_9100, BD_M_9100 and LG_M_9100 |
| Extra model bones | One old-head bone and six headwear bones retained; the original HKX track map stays unchanged |

The coverage set was AM_M_9000/9010/9020/9100/9200; BD_M_9000/9030/9040/9100/9500/9530; FC_M_0100/0110/0200/0210; HD_M_9510/9520; LG_M_9000/9050/9100. Overlapping variants were loaded together only for the coverage check. Select one part per body region for a normal character.

BD_M_9530 has literal green/blue MTD colors with intentionally empty texture paths. Those materials retain their authored colors; unrelated images are not guessed from the TPF.

## Animation checks

Both output modes were written, decoded with the updated decoder, and imported back into Blender without a compendium. Frame count and track-to-bone mapping were retained.

| Readback measurement | Interleaved | Spline |
| --- | ---: | ---: |
| Frames / transform tracks | 81 / 114 | 81 / 114 |
| Maximum translation difference, game units | 0.000002 | 0.00098401 |
| Maximum rotation difference, degrees | 0.0000351 | 0.17036 |
| Maximum scale difference | 0.00000064 | 0.0009897 |
| Root motion sample difference | 0 | 0 |
| HKX bytes | 459,588 | 50,020 |

Spline compression is lossy. Its temporary Havok 2010 packfile header is corrected before invoking the bundled utility. Compression uses private temporary files and does not modify the installed dependency's source.

## UI and regression checks

- Layouts checked in a clean headless Edge profile at 1440, 1000 and 520 pixels: no horizontal overflow, usable path controls, working page navigation and help dialog, and no JavaScript exceptions.
- A UI import completed end to end; a UI spline export completed end to end.
- An attempted export over an existing HKX was refused; the original file's SHA256 stayed unchanged.
- Cancelling an actual import during character preparation stopped the job and left no final `.blend` output.
- Unauthenticated and foreign-origin API requests returned 403.
- The PowerShell scripts parsed, and OpenFileDialog, SaveFileDialog and FolderBrowserDialog instantiated successfully. Interactive selection in the native dialogs remains a manual UI check.
- Eight synthetic Python tests passed, using owned fixtures only.
- A synthetic Blender check passed for bone rest orientation, bulk sampled curves, compressed source metadata, extra model bones, a driven bind adapter and animation round trip.

Owned checks can be repeated with:

```powershell
& "$env:LOCALAPPDATA\SekiroAnimationBridge\writer-env\Scripts\python.exe" -E -X utf8 -m unittest discover -s .\standalone\tests -p "test_*.py" -v
& "D:\Blender\blender.exe" --background --factory-startup --python .\standalone\tests\blender_synthetic_check.py
```

## Remaining limits

The preview approximates materials and does not run Havok cloth physics. It exports animation, not edited mesh geometry. Fixed clip length, transform tracks and the selected rig are the supported workflow. Additive clips, float tracks, duration changes, TAE events and unrelated HKX metadata are outside this version.

Earlier interleaved output was confirmed in game by the user. Version 0.2 and its spline output still need the user's normal in-game test after WitchyBND repacking. The game was not launched for this release.

Selected local reports and screenshots are under `work/verification`; the ready-to-edit full character scene is `work/wolf_complete.blend`. Older development outputs are preserved in the dated cleanup folder under `~/Documents/SekiroAnimationBridge-Archive`. These game-derived artifacts are excluded from the source ZIP.
