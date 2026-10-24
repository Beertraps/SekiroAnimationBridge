# 0.7.1 — custom layouts: the first folder wins

- **Custom layouts**: when several folders of one kind hold a file of the same name, the first folder listed wins, the way a mod folder overrides the game's files. This now holds for every kind. Animation archives used to be listed twice under the same name, a game texture could replace the mod's when its image was larger, two c0000 rig attachment models left neither chosen, and a tie between material libraries went to the alphabetically first path. A name with or without `.dcx` counts as the same file, and the dialog's counts leave out hidden files. Scan an existing custom source again (**Scan this source again**) to apply it.
- 3 new unit tests on owned synthetic folders cover it; see VERIFICATION.md.

# 0.7.0 — sources, redesigned workspace, control rig

- **Sources** replace the single assets folder. **Detect** recognises a game folder in the game's own structure (`chr`, `parts`, `mtd` or `material`, also through `Game` or `DATA`, or from a chosen `chr` folder) and names the game by its executable, by Elden Ring's material library or from one archive. Any other folder is a collected folder, matched by the folders its files share as before. A folder of several games lists them.
- **Custom layouts** name the folders for animations, character models, parts, textures and the material library: relative to the source or absolute, several per kind, optionally with subfolders. The dialog marks folders that do not exist and counts the files in the others.
- A game folder is listed by file name, and a character's archives are read when you choose it: the Sekiro player's 44 archives with 1,434 animations took about a second. Characters read once stay listed while their archives are unchanged, and an import reads a changed archive again. The model, parts, textures and material library are found by character ID across the source's folders; only texture packages named by the model and its materials are read.
- Save several sources and switch between them in the top bar. Each remembers its layout, game, scenes folder and scan, and your character, animation, parts, output file and material overrides. A single assets folder saved by an earlier version becomes the first source. Sources are kept in `ui-sources.json`, which older versions do not rewrite.
- **Redesigned UI**: a compact rail with Import, Export, Sources and Setup. The import page has three panes: characters; an animation list that stays fast with thousands of clips, with search, an archive filter and keyboard navigation; and the scene with its checks, parts, materials and matched files. The Sources page shows every source with its layout and counts. Light and dark themes follow Windows or can be chosen in Setup, and the layout adapts down to phone width.
- CLI: `-SourceLayout auto|folder|game|custom`, `-SourceLayoutFile` for a custom layout in JSON, and `-AssetCharacter` to choose a character in a game or custom source.
- 21 new unit tests on owned synthetic folders cover detection, indexing, carry-over, selection and the settings migration; see VERIFICATION.md.
- Retarget Assistant 0.3.0 adds a **Control rig** panel to the Retarget tab. **Add control rig** gives an imported rig animator controls in the same armature: an FK control on every game bone that points along its limb, IK arms and legs with pole targets and an IK/FK slider per limb, a root control, and coloured shapes in bone collections (Torso, FK limbs, IK limbs, Fingers & toes; Extras and the game bones start hidden). The active action is baked onto the controls in FK and IK alike, so the pose does not change; the original action is kept.
- The game bones follow the controls through constraints and keep their rest pose, so meshes and weapons stay bound and export writes what the controls do. **Switch to IK** and **Switch to FK** match a limb's other controls to its pose over the scene range, or at the current frame, before switching. **Remove control rig** bakes the edited motion onto the game bones as a new action, or restores the original action.
- Export with a control rig: the export page, CLI and the add-on's **Export HKX** sample the game bones as before. **Read actions** lists only actions that animate the controls, and exporting another action of that armature stops with a message instead of writing a clip that the controls override. A keyed control of an untracked bone counts for **Original tracks + keyed bones**. The retarget bake refuses a target that has a control rig.
- Arms and legs get IK wherever the matcher recognises them; other skeletons get FK controls. Bones that the clip scales unevenly, such as Sekiro's pectoral helpers, keep their own axes so their scale carries over exactly. Not in this version: foot roll, finger IK, face controls and IK stretch.
- Install `SekiroRetargetAssistant-0.3.0.zip` over 0.2.0. New Blender test `blender_control_rig.py`; see VERIFICATION.md.

# 0.6.1 — ready-to-run release ZIP

- Release ZIPs include the prebuilt HKX decoder and uv. Extract the ZIP and double-click **Start Animation Bridge.cmd**: the first start downloads Python 3.13 and the pinned libraries into `%LOCALAPPDATA%\SekiroAnimationBridge`. No Python, .NET SDK or Git installation is needed; Blender 4.5 stays a separate install.
- The launcher repeats that setup when an update pins different libraries. `tools\setup_writer.cmd` uses the included or an installed uv, and still accepts Python 3.13 with pip.
- The bridge prefers the decoder in its own folder over the one `build_decoder.cmd` builds, and replaces a decoder path saved by another unpacked version. A custom decoder choice stays. The CLI uses the same default.
- Spline export needs the Microsoft Visual C++ 2010 Redistributable (x86): Soulstruct Havok's `CompressAnim.exe` is a 32-bit program linked against `MSVCR100.dll`. **Settings & setup** shows an optional Spline compression check, and a missing runtime now gives a clear message instead of error 0xC0000135. Interleaved export does not need it.
- A GitHub Actions workflow builds each tagged version: the decoder from the pinned SoulsAssetPipeline commit, uv with a pinned checksum, then a first start of the packaged bridge and the unit tests on a fresh profile, then the release with both ZIPs.
- The project is licensed GPL-3.0-or-later. The README is now an overview; its previous content is `docs/USER_GUIDE.md`, next to `OTHER_GAMES.md`, `VERIFICATION.md` and `PROJECT_CONTEXT.md`.

# 0.6.0 — export options, all-game writing, retargeting

- Added HKX export options to the export page and CLI: action/take, frame range (scene, action keys, imported clip length, custom), output frame rate, track set (original tracks, plus keyed bones, every bone), root motion (root empty, extracted from a bone's travel with optional vertical travel and turning, or none), spline rotation precision and tolerance, and read-back verification. **Read actions** (CLI `inspect`) lists the scene's actions, frame ranges, tracks and root-motion object without changing the file.
- Bone root-motion extraction defaults to the bone that carries the whole body, above both pelvis and spine (Root, RootPos or Master), so legs and upper body stay together over the root.
- Writing now works for every supported game. `havok_compat.py` works around Soulstruct Havok 1.5.0: Dark Souls III packfile section padding and member layout, Elden Ring property bags, string tags and `hkFlags` type names, and reading Sekiro tagfiles back. Synthetic clips write and read back for Sekiro, DS1, Remastered, DS3 and Elden Ring in both formats.
- Weapons in DS1, DS3 and Elden Ring: **Auto** now follows the WepAbsorpPosParam default row for any weapon. The main model goes to the right hand (dummy 20) and its scabbard to the opposite hip (dummy 30). Added Two-handed, sheathed right-/left-hand states and per-model custom dummy lists such as `dummy:20,30`. Extra models are classified as scabbard, paired weapon or accessory from their bones. Replace an old `dummy:20` workaround with **Auto**.
- Retarget Assistant 0.2.0: bone names no longer need to match (names, anatomy and rest positions); matched rest stances; body travel on the bone above hips and spine, scaled by leg length; root motion from the source, from body travel, from the target, or none; repeatable bakes from the original clip; **Export HKX** directly from Blender through the bridge. Install `SekiroRetargetAssistant-0.2.0.zip` over 0.1.0.
- The bridge records its folder in `%LOCALAPPDATA%\SekiroAnimationBridge\bridge-location.json` when the UI or a conversion starts, so the add-on can find it. A new runtime mode, `write`, converts already-sampled motion JSON.
- UI: Settings shows the retarget add-on and credits; the export page warns when a scene has no recorded game. Added `CREDITS.md`.
- New owned test fixtures and checks: `standalone/tests/humanoids.py`, mapping unit tests, `blender_retarget.py` and `blender_export_options.py`. 44 unit tests and 4 Blender scripts pass; see VERIFICATION.md. No game launch or in-game playback check for this release.

# 0.5.1 — DS1 / DS3 weapon attachments

- Removed the incorrect skeleton-name-equals-c0000 check. The runtime supplies actual HKX bone names to weapon preparation; a DS1 player named Master is valid.
- Added a static Auto profile for the supplied DS1/Remastered and DS3 WP_A_0201 blade/scabbard packages, with right/left-hand and corresponding hip sheath choices.
- DS1 follows named weapon/case bones with its own orientation basis. DS3 uses its authored hand/case dummies. Existing Sekiro defaults remain available.
- Replaced the generic text-only placement input with Auto / hand / sheath / custom-dummy controls. The attachment JSON accepts package:member overrides.
- Source reference inventory and syntax checks only for this fix; no new unit tests, Blender conversion/playback or game run. Decoder 0.5.0 remains sufficient.

# 0.5.0 — other FromSoftware games

- Added game/header detection for Sekiro, DS1/PTDE, Remastered, DS3 and Elden Ring. Folder matching is scoped by game, original folder and character; repeated c0000 IDs remain separate.
- Added generic player outfit selection, including HD/FC/HR pieces and unambiguous available armor regions. Only Sekiro uses Wolf presets. The assets-folder display now fills from the selected character's folder; Find models retains that catalog selection.
- Added MTD/MATBIN resolution by definition stem, MATBIN-only samplers, explicit FLVER overrides, texture tiling and emissive preview maps. DS1's MtdPatch overrides are loaded with Mtd. High-resolution TEXBND images take priority over low-resolution duplicates.
- Added native packfile decoding to the C# tool. New scenes retain their game/Havok metadata; export chooses the native class and optional spline conversion returns to that version. Legacy scenes require an explicit source game. Export still writes raw HKX without binder packing.
- Added source-game controls, MTD/MATBIN browsing, missing-file explanations and stale-field clearing. Non-Sekiro weapons require explicit dummy IDs; automatic Sekiro weapon profiles are not reused for them.
- New paths have source inspection/discovery and compilation evidence only. No new Blender round-trip, regression suite or gameplay run. Details: OTHER_GAMES.md and VERIFICATION.md.
- Saved 0.4.1 source/ZIP/settings and the prior decoder DLL in Documents/SekiroAnimationBridge-Archive/before-other-games-20261023. No game files, dependency installs or downloads added to the release.

# 0.4.1 — Wolf weapon attachments

- Fixed weapon meshes floating at the origin or remaining static. Each weapon gets a separate local rig driven through the c0000 FLVER dummy attachment transform.
- Kept weapon-only bones out of the main animation/export skeleton and prevented shared names such as Blade00 from joining unrelated weapon skeletons.
- Added automatic katana, scabbard, Mortal Blade and prosthetic attachment profiles, with per-package preview placement and custom dummy ID controls in the GUI.
- Added automatic/manual rig attachment reference selection (c0000.chrbnd.dcx or c0000.flver), and matching CLI reference/placement-map options. Older 0.4 catalogs remain usable.
- Verified 30 full-detail weapon packages / 58 visible pieces on animated Wolf in Blender 4.5.14. Verified both HKX output formats retain the character track map and root motion. Passed 21 Python checks and an owned Blender socket/duplicate-bone-name fixture.
- Created a repaired copy of the user’s saved a000_000202 scene; sampled transforms and root motion are identical before and after repair. Original scenes/settings were preserved.
- This is static equipment attachment preview: equipment/TAE state switching, prosthetic deployment and weapon-local animation clips remain outside the implementation.

# 0.4.0 — folder import from DCX archives

- Added a folder input mode with Browse, cancellable archive scanning, character selection and animation search. Individual-file mode remains available.
- Extracts animation inputs into a private cache and resolves skeletons and compendiums without WitchyBND. Compendium type IDs are matched explicitly; split Wolf animation/base-skeleton archives are supported.
- Finds matching NPC models, Wolf part selections, material binders and texture packages in the supplied folder. Uses material texture references for shared texture IDs.
- Added a shared DCX wrapper codec and optional compress/decompress CLI using the existing pinned Python dependencies. Steam Oodle detection and an optional DLL field are included; native game DLLs are not distributed.
- Decoder 0.4 accepts a separate skeleton compendium, preserving its earlier four-argument form. Rebuild when upgrading.
- Created local example folders: Owl (5 archives / 155 clips) and Wolf (8 archives / 184 clips). All discovered clips in these examples had matching input files; this does not attest decoding every clip or in-game playback.
- Preserved 0.3.1 source, release ZIP, settings and installed decoder DLL before changes. No new formal regression suite or gameplay check was run for this release.

# 0.3.1 — optional retargeting assistant

- Bundles a standalone Blender add-on ZIP for appending source scenes, automatic bone matching with review, reusable mapping files and baking onto a target rig.
- Uses rest-relative FK rotation, retained target proportions, optional body/root travel scaling and source/target timing choices. Original target actions are retained.
- Preserves appended bridge text/root references and records an explicit HKX export target. New bridge scenes store datablock references so Blender can remap them when appending.
- Generated an Owl-to-Wolf demo: 96 of 114 target animation bones assigned, 52 frames baked and exported as a Wolf animation. Unmatched bones retain their target motion. No IK/contact solver or in-game retargeting confirmation is included.

# 0.3.0 — NPC characters

- Added Auto detect and NPC / custom character selection, a model checklist and a selected-model count. NPCs have no Wolf outfit requirements.
- Fixed NPC skeleton decoding by supplying the matching compendium to the skeleton reader too. Rebuild the decoder when upgrading; the runner checks for the skeleton-compendium capability.
- CLI accepts `-CharacterPreset auto` or `-CharacterPreset npc`; `-WolfPreset` remains supported.
- Restores explicit model selections after refreshing the UI and uses neutral character/material names in Blender.
- Frames the Blender viewport around the imported character's size and position.
- Recognizes authored alpha-test thresholds for NPC fur and hair cutouts.
- Checked Owl/c5060 import, mesh skinning, texture assignment, a pose edit, both export formats and complete-character re-imports. Checked the UI at 1440, 1000 and 520 pixels and retained Wolf's outfit selection. No NPC game launch was performed.

# 0.2.0 — full character workspace

- Fixed Browse dialogs appearing behind the bridge; Assets uses the modern Explorer folder picker. Added one-picker-at-a-time handling, Cancel Browse and bounded waiting so controls recover after cancellation or a timeout.
- Blender discovery also checks permanent installations under `%LOCALAPPDATA%\Programs\Blender` before searching Downloads.
- Replaced the fixed Windows form with a responsive local UI, native path pickers, field help, saved settings, environment checks, part selection, progress, cancellation, logs and output actions.
- Reads multiple FLVERs or original parts binders. Resolves their TPFs, shared body textures and MTD sampler assignments automatically.
- Includes Standard Wolf, tutorial and Mortal Blade presets, individual part selection and optional extra models.
- Handles split vertex streams, all UV layers, zero-weight sentinel indices, additional model bones and alternate cutscene bind poses.
- Builds separate Blender objects on an editable animation rig and packs used texture images into the scene.
- Corrected bone rest orientation by assigning bone length before its matrix. Uses bulk action curves and compressed embedded source metadata for fast import.
- Added interleaved HKX input alongside spline input, and a decoder version check.
- Fixed spline output: the pinned library wrote a 2016 version label into its temporary 2010 packfile. Compression now uses a corrected header and isolated temporary files.
- Keeps existing single-model CLI arguments. Animation export remains independent of model editing and binder packing.
- Adds owned synthetic regression checks and a reproducible source-only release packager.
