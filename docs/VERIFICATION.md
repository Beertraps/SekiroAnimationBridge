# Version 0.6.1 — 2026-10-24

- Unit tests: 44 pass. Python sources compile, `app.js` passes `node --check`, and the four PowerShell scripts parse without errors.
- Setup: `tools\setup_writer.ps1` with uv 0.12.23 created a writer environment in a scratch profile, offline from uv's cache: Python 3.13.16 and the 15 pinned packages, the same versions as the development environment. `soulstruct.flver`, `soulstruct.havok` and NumPy import. The run also passes with all output redirected, after a fix: Windows PowerShell had turned uv's progress messages on stderr into a fatal error.
- Release ZIP built locally from the installed decoder and uv: 271 files, 65,168,617 bytes, without CompressAnim, `work/` or game files. From the unpacked ZIP on the scratch profile, `Start Animation Bridge.cmd --no-browser` repeated setup because the pinned list had changed (15 packages checked), then started the UI. The UI reported the conversion libraries and the packaged decoder ready, selected that decoder, and shut down on request. The packaged decoder decoded a supplied Sekiro clip (a000_000100: 81 frames, 114 of 114 tracks mapped, root motion included).
- Not checked locally: a first start that downloads Python and the packages on a machine without uv's cache. The release workflow covers that on a fresh Windows profile.

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
