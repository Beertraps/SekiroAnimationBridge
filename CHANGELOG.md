# 0.9.0 — retarget weapon hands, arm distance and foot targets, two characters from one import, weapon part animations and clip preview

Install `SekiroRetargetAssistant-0.5.0.zip` over 0.4.0 for the retarget changes.

## Retarget: weapons in the other hand, weapons that rest away from the hand, and hidden weapons

- **Weapon from the other hand**: where the source holds a weapon in one hand only and the target in the other hand only, **Match bones automatically** gives the target's weapon the source's at 80%, listed for review. Godfrey holds his axe in his left hand and Isshin his katana in his right, so `R_Katana` takes `L_Axe`. Weapon bones that rest away from the hand, such as Isshin's spear, are not matched this way; choose one by hand to use it instead.
- **Placed weapons**: the bake places a mapped weapon bone in the hand that holds the source weapon when it takes a weapon from the other hand, or when it rests away from its hand, as Isshin's spear `L_Yari` rests 1.7 m from his hand until a clip brings it in. It keeps the source weapon's offset from that hand, scaled like body travel, with its grip held in the hand along the weapon's line. It turns like the source weapon and shows and hides with it, also where the target's own clip hides the bone, and the bones below it, such as a scabbard, follow. Where the source shrinks its weapon to 0, the placed bone shrinks to 0.1%, so the bones below it keep their place. Before, such a weapon stayed in its own hand or far from the hand. A weapon bone that rests at its own hand and takes a weapon from the matching hand keeps its own grip as before. The status names each placed bone.
- Choosing a source bone that another row uses moves it: the other row is cleared and reads *Source moved to* the new row's bone, so giving the axe to Isshin's spear takes it from his katana.
- **Hide weapons**: weapon, scabbard, storage and shield rows in the bone list have an eye toggle, **Hide**. The bake shrinks a hidden bone to 0.1% on every frame where it would otherwise be, as FromSoftware clips hide weapons, and the bones below it shrink with it. With the axe on Isshin's spear, hiding his katana leaves only the spear. Bone maps save the toggle; **Match bones automatically** clears it.
- **Export of bones scaled to 0**: a bone keyed to scale 0 keeps its keyed rotation, and tracked bones below it keep their own channels. Before, its rotation was exported as none, and the bones below it came from the inverse of a matrix scaled to nothing: on a copy of an Isshin scene with his katana keyed to 0, the scabbard's track lay up to 48 m away at scale 0, which can show where the clip shows the katana again or the game blends into another clip. Keys of 0.1%, as FromSoftware uses, were already exported correctly.
- **Keep hands out of the body** counts a placed weapon with the hand that holds it.
- Baking again starts from the target as it was before any bake, now also for bones that only an earlier bake animated and for a target without an action of its own. Before, those kept the earlier bake's pose with *Keep target animation*.
- New Blender test `blender_weapon_hands.py`, new checks in `blender_export_options.py` for a bone keyed to scale 0, and two new matcher unit tests; see VERIFICATION.md.

## Retarget: arms close to the body

- **Keep arms close to the body**, a new bake option that is on by default: a source whose body is wide for its arms holds them out to clear it, and the bake used to copy those angles, so a slimmer target held its arms out. Now, where the source's forearm, hand or fingers come within a quarter of an arm of its own torso, the target's arm turns in at the shoulder until it stands as close to the target's torso, scaled by the ratio of arm lengths, but no closer than 2% of the arm. The elbow's bend, the hand's rotation and what the hand holds stay as they were. Between a quarter and half an arm, less and less of the difference is taken out, and arms held farther from the body keep their reach. Turns ease in and out over 0.2 s, and where both hands come together, as on one hilt, both arms keep the plain bake, so the grip holds. It needs the character meshes of both rigs; a source without a body mesh is not compared, and the status says so.
- On a copy of the review scene with Owl's clip on Wolf, the plain bake left Wolf's arms up to 13.8 cm (left) and 10.6 cm (right) farther from his torso than Owl's, at Wolf's size. With the option, the arms turned in by up to 26° and 20°, and from frame 17 on, away from the frames where the hands meet, each arm stood within 1.5 cm of Owl's gap, 0.5 cm on average. No forearm, hand or finger went into the torso.
- New Blender test `blender_arm_gap.py`; see VERIFICATION.md.

## Foot targets follow the feet

- Every FromSoftware rig checked, from Sekiro and Dark Souls III, hangs a second, straight chain from `Master` on each side: `L_Foot_Target2` at hip height, `L_Foot_Target1` at knee height and `L_Foot_Target` at the ankle. In every game clip checked, the chain stands on its foot like an upright column: the last bone copies the foot, within 9 mm and 0.34°, while `L_Foot_Target2` stays upright directly above the foot, within 7 mm and 1.8°, and `L_Foot_Target1` keeps its rest offset below it. Modders who retarget through 3ds Max and Rokoko noticed these vertical bones and report feet that flip for a frame when the game blends between clips. A target that no longer sits on its foot is the likely cause, since the game reads these bones; this is not yet checked in game.
- **Retarget bake**: each chain now stands on its foot on every frame, as in the game's clips: it keeps its rest pose and moves as one, without turning, so that `*_Foot_Target` sits on the foot, which it also turns with. That holds whatever the source's own targets do and whether or not they are mapped. Before, a source without the chain left the targets with the target's old clip or its rest pose. A FromSoftware source turned them like its own targets but left them at their rest offset from `Master`: on Owl's clip on Wolf, up to 1.13 m from the foot. The status lists the targets.
- **Export**: the bridge's export, which the add-on also uses, writes each chain standing on the exported foot in the same way, also after root motion is taken from a bone. An edit that moves the feet in Blender now moves the targets with them. The export summary and the log list the targets.
- New Blender test `blender_foot_targets.py` and a new matcher unit test; see VERIFICATION.md.

## Two characters from one import

- **Retarget donor**: one import can bring a second clip and its character into the scene for the retarget add-on, from any source or game, so a retarget no longer needs a second import and **Append source .blend**. On the import page, pin the donor's animation with **Use this animation as the donor** in the new **Retarget donor** block, then choose the target's animation. The suggested scene name becomes `<target>_<clip>_from_<donor>_<clip>.blend`. On the command line, `-DonorAssetClip`, `-DonorAnimation` and the other `-Donor` options do the same; without a folder of its own, the donor reads the target's source.
- The target is set up exactly as after a single import: its frame range, frame rate, export rig, embedded metadata and selection, so it exports the same way. The donor keeps its own action, root-motion object and embedded HKX metadata, all named *Donor* (`Donor c5060`, `Donor HKX_RootMotion`, `Sekiro Source - Donor - a000_003041.json`), so rigs of the same name, such as c0000 from two games, stay apart. It stands beside the target through its delta location, which leaves its keys as imported and does not change the bake. Weapon part clips are imported for the target only.
- **Read actions** and the CLI's `inspect` leave out actions that another armature plays, such as the donor's.
- Retarget add-on: when a file from such an import opens, **Source** and **Target** are filled in from it while both are empty, and the status says so. The add-on package includes the new module `imported_pair.py`.
- New Blender test `blender_two_characters.py` and new unit tests in `test_two_character_import.py`; see VERIFICATION.md.

## Weapon part animations and clip preview

- **Animated weapon parts**: the import keys the weapons that animate their own bones, such as the Loaded Umbrella, the Loaded Axe and the Loaded Spear, with the part clip that plays with the chosen animation. That is the part's clip of the same ID; else the clip of an ID that plays the same body clip in the character's TAE, so with Wolf's `a070_412000` the umbrella plays `a076_412000_1`; else the rest pose, which is not keyed. The part's own TAE can redirect an ID too. Each clip is keyed on the weapon's own rig at its own frame rate, in an action such as `WP_A_0760_1 | a076_405010_1`, and the rig gains every bone of the part's skeleton, also where the skeleton parents a bone differently from the model. Before, every weapon kept its rest pose.
- **Animate weapon parts** is on by default and shows on the import page once a weapon is selected; the CLI turns it off with `-NoPartAnimations`.
- **Part clip export**: **Also export part animations** on the export page, or `-ExportParts`, writes each animated part's clip beside the character's HKX under its member name, such as `a076_405010_1.hkx`. It is sampled over the same frames at the part clip's frame rate, in the character HKX's format, and read back. Replace it in the part's animation binder with WitchyBND; part clips are not yet tested in game.
- **Clip preview**: the scene panel of the import page plays the chosen animation as a skeleton before the import, with play and pause, a frame slider, orbiting by dragging or with the arrow keys, and optional root motion. Below it, the preview lists the part clip that each selected weapon plays and why. Decoded previews are kept in `work\asset-cache\previews`.
- New unit tests in `test_part_animations.py` and a new Blender test `blender_part_animations.py`; see VERIFICATION.md.

## Browse

- **The bridge stays in front after Browse**: after a choice in a Browse window, Windows could activate another application's window and put it over the bridge. The picker now hands the foreground back to the bridge window before its own windows close.

# 0.8.0 — retarget: weapons and body clearance

- **Weapon dummies**: **Match bones automatically** maps a weapon bone in a matched hand, such as Wolf's `R_Weapon`, to the weapon bone in the source's matching hand, such as Isshin's `R_Katana`. Weapons that the source clip hides by shrinking them to almost nothing, such as Isshin's gun and spear, do not count; of several that remain, the hand's own child wins. Bones that store a weapon on the body, such as `Katana_Saya_Storage`, are left out.
- **Weapon alignment**: when a mapped weapon bone and its source bone both carry a clearly elongated mesh, the bake turns the target bone so that its blade points like the source's. Wolf's `R_Weapon` and Isshin's `R_Katana` differ by 6°. The status lists each turn.
- **Keep hands out of the body**, a new bake option that is on by default: where a hand, its fingers or what it holds would go into the target's torso, the bake moves the hand out through its arm and keeps the hand's rotation. Clipping that the source animation already has stays: the source's own hands are measured against its own torso, and the target's hand moves out only by what goes deeper, at the target's size; where the source's hand is clear of its body, 2% of the arm's length further. A source without a body mesh is not compared. Each contact keeps one direction and eases in and out over 0.2 s, and two hands on one hilt move together. A push longer than about a third of the arm is left out and reported. This is for targets with a thicker body than the source, such as Isshin's clips on Wolf.
- Install `SekiroRetargetAssistant-0.4.0.zip` over 0.3.0. New Blender test `blender_weapon_clearance.py` and a new matcher unit test; see VERIFICATION.md.

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
