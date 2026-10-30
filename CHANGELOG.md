# Unreleased

- **A missing package tool is named when the folder is chosen.** A game package whose decoder is not built, such as the `packages\unreal` folder of GitHub's *Source code* ZIP unpacked into a release, failed only at the scan, with *Unreal decoder is missing*. The source dialog now says so as soon as the game folder is chosen, and shows the detection as a warning. In the bridge folder the message says to run the package's build script; for an installed package it says to install its package ZIP again.
- The Unreal decoder's build copies the licenses of the .NET runtime it carries, and of ACL and RTM when it builds the native library, next to the decoder, so its package ZIP can be handed on. The [Unreal guide](docs/games/unreal.md) says how to build that ZIP and install it into a release.

## Command line for scripts and agents

- New **`standalone\bridge_cli.cmd`**: the steps of the UI as commands that each print one JSON document, for scripts and AI agents. `env`, `games`, `detect`, `scan`, `clips`, `select`, `masks`, `import`, `inspect`, `verify`, `export`, and `run` for any request the UI sends. The log goes to stderr; a failure exits with 1 and `{"ok": false, "error": ...}`. It lists one character's clips (`clips --character`), which the PowerShell CLI cannot, and takes clips by ID or by name. `detect` and `scan` take a game package's source options, such as the Unreal package's engine version or AES key, with `--option ID=VALUE`. See the [user guide](docs/USER_GUIDE.md#json-command-line-for-scripts-and-agents).
- New **`verify`**: measures a scene in Blender without saving it and says what is wrong: the size at rest (unit scale), the up axis, which side the left bones are on, whether each mesh follows its bones, vertices on model bones outside the animation's skeleton, and missing images or base colors. An advisory check names the frame where skinning stretches a mesh's edges most; `passed` leaves it out, since cloth stretches as far as a wrong bind. `--render` draws the characters from the front and the side. New module `blender_verify.py`; `bridge_runtime.py` and `blender_bridge.py` take the new `verify` mode.
- New `CLAUDE.md`: setup, commands, tests and rules for agents working in the repository.
- `build_decoder.cmd` clones SoulsAssetPipeline with Git's long paths on. Without them, Git for Windows stopped at generated Havok class files under `%LOCALAPPDATA%`.
- The writer Python runs from the path it is given rather than its resolved one. Inside a packaged app, such as the Claude desktop app, `%LOCALAPPDATA%` resolves to a longer folder, and Soulstruct's longest module names passed Windows' 260 characters, so export failed with `ModuleNotFoundError`.

# 0.14.2 — game packages, Devil May Cry 5 import, full-body bake, faster skeleton preview, cache cleanup

Install `SekiroRetargetAssistant-0.10.0.zip` over 0.9.0 for the retarget changes. 0.14.0 and 0.14.1 were tagged but not released, because the release checks of their ZIPs failed.

## Import from other games: Devil May Cry 5

- **Devil May Cry 5 imports.** Add the game folder as a source and choose its file list, `DMC5_STM_Release.list` from REE.PAK.Tool. The bridge reads the PAK archives without changing them, lists the players and enemies, previews their clips and builds a Blender scene with the rig, the body, head and hair, their materials and textures. A folder with an extracted `natives` folder works without a list. [docs/games/dmc5.md](docs/games/dmc5.md) walks through it.
- DMC5 is import-only: edit a clip in Blender, or use it as the **Retarget donor** for a Sekiro, Dark Souls or Elden Ring character and export that. Exporting a DMC5 scene says so instead of failing in the writer.
- New RE Engine decoder (on REE-Lib) in the RE Engine game package, shown under **Settings & setup**. Build it in a source checkout with `packages\re_engine\decoder\build_decoder.cmd`.
- A game registry (`standalone/games`) names every game with its engine, capabilities and axis convention. The game lists in the UI, the CLI and the add-on come from it, so a new game of a known engine is one entry. Resident Evil 2 (DX11) is registered as untested.
- Motion JSON version 2 and character manifest version 5 say which axes and unit their game uses; Blender converts them once. FromSoftware files and scenes give the same results as before. See [docs/INTERCHANGE.md](docs/INTERCHANGE.md).
- Retarget add-on: RE Engine bone names (`Hip`, `L_Shin`, `L_IndexF1`) match by name, fingers included. A bake no longer stops when a target finger has no source bone.

## Game packages

- Engines other than FromSoftware's come as **game packages**: a folder with `package.json`, a Python module on a fixed, versioned API and the tools it runs. Users download only the engines they need. Devil May Cry 5 and Resident Evil 2 are in the RE Engine package, a separate ZIP beside each release.
- **Settings & setup › Game packages** lists the packages, shows what a package ZIP holds (games, tools, authors, license, homepage) and installs it into `%LOCALAPPDATA%\SekiroAnimationBridge\packages` after a warning that a package runs its own code. **Remove** deletes an installed package. Each package tool has its own card, and a package that cannot load says why.
- Anyone can write a package: [docs/PACKAGES.md](docs/PACKAGES.md) describes the API, with an example package as the template. `tools\check_package.cmd` runs a package as the bridge does, from `package.json` to a Blender scene, and names the step that fails. `tools/package_game_package.py` builds the ZIP.
- The bridge checks what a package returns against the new catalog schema and the motion and manifest schemas. `standalone/schemas/package.schema.json` checks `package.json`.
- A package can give the retarget add-on its games' bone names. Imported rigs record their game, so the add-on reads the names of that game only.
- The decoders share one .NET 9 runtime. Release ZIPs carry it in `dotnet-runtime/`, and the decoders no longer include their own; a source checkout prepares it with `tools\prepare_dotnet_runtime.cmd`. **Settings & setup** shows it as **.NET runtime**.
- DMC5 sources scanned before need one new scan.
- The skeleton preview hands a package the whole selection it made for the clip, as the import does, so a package that needs more than the clip's file (DOOM Eternal needs its game folder) can preview. `tools\check_package.cmd` asks for the preview the way the page does.
- **Source options.** A package can declare fields for its sources, such as a key, a version choice or a file, and the source dialog shows the ones a source needs. The values are kept with the source on this computer, each set of values has its own scan, and the CLI takes them with `-SourceOptionsFile`. `tools\check_package.cmd` takes them with `--option id=value`.

## Experimental: DOOM Eternal package

- `packages/doom_eternal` imports DOOM Eternal's characters: the Doom Slayer, the demons and the cinematics, with their animations, skin weights and textures. It reads the game's `.resources` archives in place with the game's own Oodle library, in Python ported from [Valen](https://github.com/jandk/valen) (MIT), and needs no other program.
- Characters show readable names and gore variants in words; clip names leave out the folders they share.
- Release ZIPs do not include it, and it is not attached to releases. A source checkout loads it as it is; `tools/package_game_package.py packages/doom_eternal` builds a ZIP to install into a release.

## Experimental: Unreal Engine package

- `packages/unreal` reads Unreal Engine 4 and 5 games, one package for all of them. It lists one character per skeleton with animations, previews the animation sequences and imports them with the skeleton's skeletal meshes, materials and textures. Its decoder runs on [CUE4Parse](https://github.com/FabianFG/CUE4Parse) (Apache-2.0) and reads the PAK and IoStore archives in place; `packages\unreal\decoder\build_decoder.cmd` builds it from a pinned commit. [docs/games/unreal.md](docs/games/unreal.md) walks through it.
- CUE4Parse needs .NET 10, so the decoder carries its own .NET 10 runtime instead of the bridge's shared .NET 9 one. Building it needs the .NET 10 SDK.
- The decoder takes Microsoft.Bcl.Memory 9.0.22 instead of the 9.0.0 that CUE4Parse names, which has a known vulnerability (GHSA-73j8-2gch-69rq). Its build stops when the SDK would give it a .NET runtime older than 10.0.4, which has the same one. SixLabors.ImageSharp stays at CUE4Parse's 3.1.12 despite its advisories: the fixed 3.2.0 builds only with a Six Labors license key, and the decoder does not run the affected TIFF, ICC profile and histogram code.
- The source dialog reads the engine version from the game's executable, or guesses it from the archive format and says so. It asks for the AES key of encrypted archives and offers fields for a mappings file (`.usmap`) and the game's own Oodle library. The bridge includes no keys, mappings or Oodle libraries and downloads none.
- Deep Rock Galactic has an entry with its engine version, and its import is checked with the Xbox app version's files: the scan, the dwarves and the Glyphids with their models in Blender. Unreal Engine 5 games, IoStore archives, keys and mappings files are not checked with a real game yet.
- When the scan finds animations but cannot read their package headers to learn their skeletons, it says why instead of listing no characters: the game needs its mappings file, or another engine version. The game guide shows how to install CMake and the C++ build tools for ACL clips.
- Release ZIPs do not include it.

## Retarget add-on

- The full-body bake is no longer experimental. **Bake method** offers *Full body* beside *Bone by bone*, which stays the default, and the bake status and report say *Full body*.

## Import page

- Drag the border beside the character list or the scene panel to resize it, or the border between the two lists when they are stacked in a narrower window. A double-click resets a border, and the arrow keys move a focused one. The sizes are kept in the browser and shrink to fit a smaller window.

## Skeleton preview and cache

- The skeleton preview computes joint positions with NumPy for all frames at once, 3–5 times faster than before with identical results. The UI loads NumPy when it starts, so the first preview no longer waits for it.
- A clip previewed before shows at once from the cache, without the 300 ms wait for the selection to settle.
- The decoder writes compact JSON. A long clip's motion file shrinks to under 40 % of its size (Wolf's 1800-frame `a000_252000`: about 80 MB to about 30 MB), so it is written and read faster. Rebuild the decoder with `tools\SekiroMotionDecoder\build_decoder.cmd` to get this in a source checkout.
- New **Cache** card in Setup: the size of the unpacked animations, scans and previews, and **Remove unused files now**. On every start the bridge removes the scans that no source uses, the archive folders that only they list, and previews over 256 MB, least recently shown first. Files changed in the last 10 minutes and anything a running job may need are left alone. New module `cache_cleanup.py` and unit test `test_cache_cleanup.py`.
- Decoder 0.6.0 has a preview mode (`--preview <samples>`): it decodes only the frames the preview shows and writes the joint positions itself, instead of the whole motion for Python to read back. Wolf's 1800-frame `a000_252000` previews in 0.6 s instead of 1.7 s; NPC clips take 0.2–0.4 s. The positions match the Python computation to the rounding step (0.1 mm). With an older decoder the bridge computes the preview as before. Rebuild the decoder with `tools\SekiroMotionDecoder\build_decoder.cmd` to get this in a source checkout.
- Previews are stored gzipped (`.json.gz`, about 40 % of the JSON) and sent to the page as stored, without being read and written again. Previews of the older format are removed by the next cleanup.
- Once a clip shows, the bridge prepares the previews of the two clips on each side of it in the background, so moving through the list shows each clip at once (about 30 ms, with the file matching). A clip asked for while it is being prepared waits for that result instead of being decoded twice. Nothing is prepared while a conversion runs or while the preview block is collapsed.
- **Preview caching** on the Cache card: **Standard** works as above. **Aggressive** prepares every clip of the list, two at a time, nearest to the selection first, and keeps up to 2 GB of previews. Wolf's 1247 animations take about two minutes and 80 MB. New unit test `test_clip_preview_cache.py`.
- Preview fix: a clip track that no skeleton bone takes is left out; it moved the skeleton's last bone before.

# 0.13.0 — export into the animation binder, join animations, Animate tab, body figures and Biped-style feet, Wolf's katana, alternate model meshes, skin preview

Install `SekiroRetargetAssistant-0.9.0.zip` over 0.8.0 for the retarget changes.

- Wolf outfit imports select Kusabimaru (`wp_a_0300`) when the part exists in the source. A missing weapon does not make the outfit incomplete.
- The scene setup lists numbered mesh groups within a character model, so one animation can be imported with a chosen appearance. The selection is saved per model file; unnumbered meshes are always included.
- **Visible model meshes** now starts collapsed and can be opened or closed with its heading. New NPC imports create separate Blender objects for the selected numbered groups and shared meshes, so each can be hidden in the Outliner while using the same character rig and bind adapter.
- NPC scene setup now offers every character model in the source, so an animation such as `c5400` can use another model ID such as `c5410`. The matching model remains the default when it exists.
- Sekiro stencil skin materials use the base skin albedo before their tiling detail maps and ignore a damage normal map stored in an emissive slot. This corrects Resurrection `c1070`'s body preview.
- The scene checklist says **No animation compendium** when that field is empty, instead of **Self-contained types**.

## Export into the animation binder

- New **Also add it to an animation binder** on the export page, **Add to animation binder** in the add-on's step 4, and `-Binder` / `-BinderMember` on the CLI. The export also puts the written HKX into an `.anibnd.dcx`, so WitchyBND is no longer needed for the main clip. The binder starts as the archive the clip came from, which import from a source now records in the scene. The name starts as the clip's own name, which replaces that clip; another `aXXX_YYYYYY.hkx` name adds a new clip with the member ID (1000000000 + category × 1000000 + number) and folder that the binder's clips follow, kept in ID order. A new clip needs a TAE entry before the game plays it, and the log says so.
- The game's own files stay protected: for a clip from the game folder, the binder is a copy of its archive beside the output HKX, made from the game's archive on the first export. The binder is kept as `.bak` before its first change.
- The binder is rewritten as FromSoftware lays out BND4 files, with its path hash table and data on 16-byte boundaries, and compressed with the same DCX type. The other members stay byte for byte. The result is read back before it is written. Weapon part clips still go beside the HKX only.

## Retarget add-on 0.9.0: Join animations, an Animate tab, and a Log

- New **Join animations**: one action that plays the armature's own animation and then another one, such as an attack and its recovery, so the game plays both as one clip. **Blend** sets how long one eases into the other (0.2 s by default; 0 cuts). The root motion of the second clip goes on from where the first leaves the character. A second clip keyed at another frame rate plays at its own speed. **Load clip from .blend** brings in the animations and root motion of another bridge scene of the same skeleton, without its objects. Both originals are kept. TAE events of the second clip are not carried over.
- The sidebar now has two tabs. **Retarget** keeps the four retarget steps. The new **Animate** tab holds **Animation** (the armature, its action, **Mirror animation** and **Join animations**), then **Control rig** and **Fixes**. **Mirror animation** moved there from the control rig panel.
- The result box under step 4 is now a **Log** panel at the bottom of each tab. It starts closed; its header says **Warnings** when the last result warned. Export progress shows under **Export HKX** while it runs.
- New Blender test `blender_join.py`; `blender_panels.py` checks both tabs and the new states. New unit test `test_binder_members.py`. The add-on package includes the new module `join.py`.

## Retarget: body figures and Biped-style feet, jumps and props

- New **Body figures** panel under **1. Choose rigs**, as 3ds Max's Biped fits a figure to each character. **Create figure** places a stick figure with Biped's parts (Pelvis, Spine, Neck, Head, and per side Clavicle, UpperArm, Forearm, Hand, Thigh, Calf, Foot, Toe and Heel) on the joints that the add-on finds, with the head's top, the heels and the toe tips from the meshes. The rig shows its rest pose while the figure is open. You move the ends in Edit Mode (only their places count, not how parts are rotated), choose another skeleton bone for a part where needed, and click **Save figure**, which closes the figure and shows the rig's pose again. Baking and exporting wait while a figure is open. It is kept on the rig and in a figure folder, one file per skeleton, so other scenes with the same skeleton find it. The full-body bake then takes the body's bones, leg length, hip joints, height, limbs and feet from the figure. The figure only measures the character: it is not animated or constrained, and export is unchanged. Without a saved figure the bake works as before.
- New **Feet, jumps and props (Biped)** options under **3. Bake motion onto target**, all off by default:
  - **Foot contacts** > *Planted, sliding, free (Biped)*: with the full-body bake, a foot is planted where its heel, ankle, ball or toe tip stays on the ground within **Plant tolerance** (0.15 of the source's foot length, Biped's default) for 0.1 s. That point of the target's own foot then stands still, so the foot rolls from heel to toe without sliding. A foot that moves along the ground slides on the target's ground, and is free in the air. The toe tip rides on the toe bone, so it stays down while the toes bend.
  - **Scale jumps by height**: where both feet are off the ground, the body rises in proportion to the target's height against the source's, rather than by leg length; the time in the air is kept, as Biped's gravity scales with the figure.
  - **Moving props** > *By height* or *By limb size*: bones outside the body whose source bones move away from their parents, such as a thrown weapon, move as far from the nearest mapped bone above them as the source's, scaled. Works with both bake methods.

# 0.12.0 — the rest-relative weapon grip, the fist holds the weapon's matching part, raw bake by default, full-body bake (experimental), the mirrored katana strikes with its edge, preview lights

Install `SekiroRetargetAssistant-0.8.0.zip` over 0.7.0 for the retarget changes.

## Retarget: the rest-relative grip, and the fist holds the weapon's matching part

### Retarget: Source's grip

- With *Source's grip*, the target's weapon could sit beside the fingers instead of inside the fist, although its turn matched. The bake put the target's weapon bone where the source's weapon bone sits in the palm, and games place weapon bones at different spots on their models: Wolf's sits 22 cm from the end of his katana's hilt and 1.7 cm off its middle, Isshin's 35 cm from his and 1.0 cm off. On Isshin's c5400_a000_003024 on Wolf, Wolf's hilt ran 1.5 cm from where Isshin's runs in his fist, scaled to the hand, which put it into the fingers on one side.
- Now the bake finds the part of the source's weapon that the source's fist holds and the matching part of the target's weapon. It measures how wide each weapon is along its length and lines up the two outlines: the widest part with the widest part, such as guard with guard, head with head, butt with butt, and in proportion between them. The center line of the target's matching part goes where the source's lies in the source's palm, scaled to the hand. On the same clip Wolf's hilt now runs within 0.2 to 0.25 cm and 0.8 to 0.9° of Isshin's, and his fist sits 6.5 to 6.6 cm from the guard, where Isshin's sits 11.1 cm from his, in proportion to the two hilts' lengths.
- This works for swords, spears, axes and other weapons with a handle along their length. A weapon without a clear long axis, such as a shield, still sits by its bone. Where the target's handle is thinner than the source's, it sits in the middle of a slightly loose fist, as the fingers keep the source's curl.
- A weapon that rests away from the hand until a clip brings it in, as Owl's odachi rests a metre from his hand, took no grip with *Source's grip*: the bake put its bone at the source weapon bone's offset from the hand, turned with the source's weapon in the world. Now, where it hangs below the hand that holds it, it takes the source's grip like a weapon resting in the hand, also with *Target's own grip* where the own clip hides it on every frame. On Isshin's c5400_a000_003024 on Owl, Owl's fist held his odachi 4.6 cm past the guard, on the blade, its hilt 6.7 cm from where Isshin's runs in his fist, scaled to the hand, and 6.7° off. Now the fist holds the hilt 13.8 cm below the guard, where Isshin's holds his 11.3 cm below, and the hilt runs within 2.7 cm and 1.8° of Isshin's line, measured along the whole of Owl's hilt, which bends 8.5° against the blade. A weapon placed in the other hand, as Isshin's katana taking Godfrey's axe, keeps its place.
- The outlines are lined up at their widest parts first, where both have a clearly widest part. The widths count relative to the widest, and Owl's blade is nearly as wide as his hilt against his guard, so the first match paired Owl's blade with Isshin's hilt and put the fist 111 cm up the blade.
- With *Match source stance*, each hand now also rests like the source's: from the wrist to the knuckles and about that line. Before, only the arm bones were lined up and the hand kept its forearm's alignment, so a difference in how two models' hands rest bent against the forearm stayed on every frame: Wolf's palm turned 9.2° from c7110's and 9.8° from Isshin's on every frame, and with *Source's grip* the blade turned with it, 8 to 10.7° from c7110's in the world. Now the palms turn alike within 0.05°, and Wolf's blade points within 1.6° of c7110's and of Isshin's, the difference between how each hilt and blade point. Owl's odachi points 4.8° from Isshin's katana, as its hilt bends 8.5° against its blade and Isshin's 3.5°.
- New option **Bend fingers onto the weapon**, off by default, with *Rest-relative grip* or *Source's grip*: each finger joint bends until its skin just touches the weapon, and the weapon stays where the grip puts it. With Isshin's clip on Wolf, a quarter of Wolf's thumb and almost half of his middle finger went into his hilt, up to 2.1 cm deep. It changes the source's finger pose and reads the target's skin from its meshes.
- New **Weapon in hand** panel under **Bake motion onto target**: after a bake, choose a weapon, click **Adjust weapon**, turn or move it in the hand on one frame, and click **Apply to all frames**. The bake runs again with the weapon sitting in the hand that way on every frame. The alignment stays for later bakes until **Reset**, and the second hand takes the aligned weapon. For weapons that no grip matches well, such as blades curved differently.
- New **Weapon grip** choice *Rest-relative grip*, now the default; scenes where you chose a grip keep it. A line under the grip menu says what the chosen grip does. The weapon bone stays at the target's own grip point in the hand, from the target's own clip, or from its rest pose where the clip does not animate it, and turns there as the source's weapon turns in the source's hand away from its rest pose. Each finger of both hands turns so too, from the target's rest pose, also with **Match source stance**: on Isshin's c5400_a000_003024 on Wolf the fingers lie within 0.5° (left) and 1.2° (right) of a Rokoko retarget, against 5.3° and 6.0° when they took the stance. It reads no meshes: it trusts that both rest poses hold their weapons alike in the hand, as FromSoftware's do. Rokoko's retargeting turns weapon bones this way, and a Rokoko retarget of Isshin's c5400_a000_003024 on Wolf held the katana better than *Source's grip*, which put Wolf's R_Weapon 2.8 cm and about 40° from where that retarget has it. The new grip puts it within 0.00 cm and 1.4°, the HKX's rounding, on all 34 frames of that clip.
- The full-body bake keeps the hands together wherever the source holds its weapon with both hands, and then keeps the middles of the knuckles the source's distance apart rather than the wrists. Before, it kept the wrists together only where they came within 0.6 of a forearm, and Owl's are 0.6 to 0.9 apart on his long odachi hilt, so on Owl's clips Isshin's left hand stayed where his arm put it: his shoulders and hands are half the size of Owl's against arms 0.84 as long, and the same arm turns put the left knuckles 8.7 cm from Isshin's hilt, against Owl's 3.1 cm from his. Now 6.2 cm. Bone by bone, which copies the arm turns as they are, leaves 23 cm; *Second hand on the weapon* puts the hand on the hilt at 2.2 cm.
- The weapon turn of every bake now also lays the two weapons head to head and butt to butt where their outlines show which end is which. Before, a spear whose bone sits nearer its butt on one model and nearer its head on the other could come out back to front.
- The status names the matching part: *R_Weapon sits in R_Hand by the part that matches where the source's fist holds R_Katana, 0.6 cm along from R_Weapon's origin, scaled to the hand, ...*

## Raw bake by default

### Retarget: bake options

- The bake options now start raw. **Weapon grip** is *Rest-relative grip* (see above). **Keep hands out of the body**, **Keep arms close to the body** and **Second hand on the weapon** are off. Turn them on under **Arms and hands** and **Weapons** where a target needs them; *Target's own grip* keeps **Blade follows source** at 100%.
- In scenes made with earlier versions, options you never changed take the new defaults too, since Blender stores an add-on option in the scene only once it is set. Options you changed keep their values.

## Full-body bake, experimental

### Retarget: Bake method

- **Bake method** in step 3 chooses how the target takes the source's motion. *Bone by bone*, the default, bakes as before. *Full body (experimental)* finds the body in both rigs by itself, by bone names where they are clear and by the skeleton's shape otherwise, so it needs no bone list for the hips, spine, neck, head, arms, legs, hands, feet and fingers. Bones outside the body, such as weapons, take their source bones from the bone list, or from automatic matching when there is no list.
- Chains of other bone counts take the source's motion spread over their own bones: a two-bone spine takes a three-bone spine's bend, twist bones along an arm or leg take their share of its turn, and a target without clavicles works.
- Feet stay where the source's feet stand, scaled by leg length, at the target's own hip width: each foot keeps the source's sideways distance from its hip joint, scaled, so a target with wider hips stands wider, as with the bone-by-bone bake. Where a foot stands, that sideways shift holds still, so it adds no sliding; while the foot steps, it turns with the pelvis. Whether a foot stands is judged where the game puts it, with the source's root motion. The pelvis lowers where a leg cannot reach. Where the source's hands come together, the target's hands come as close, scaled by arm length; a hand that holds a weapon stays, and the free hand moves. On test rigs of other proportions, planted feet slid 29 cm over the clip bone by bone and not at all with the full body, and the hands missed each other by up to 5.2 cm against 0.0 cm.
- The status says how far each foot was set out or in for the hip width. On Owl and Isshin onto Wolf, the feet now stand within 0.2 and 0.7 cm of Wolf's own hip width plus the source's spread, scaled, on every frame, against 8.6 and 4.2 cm when the source's stance width carried over, and the legs point closer to the source's: up to 10.0° and 1.8° away, against 16.1° and 6.4°.
- The price: to keep those contacts, the legs and arms point up to 13° away from the source's, and where spine bone counts differ, a bend within one target spine bone is lost. Weapon grips, Second hand, body clearance, arm distance, foot targets and root motion work as with the bone-by-bone bake: on Isshin onto Wolf, the katana sits in Wolf's hand within 0.001 mm and 0.001° of where the bone-by-bone bake puts it, with the same fingers and the parts on its sockets in place, and the three weapon tests pass with either method.
- On two FromSoftware pairs, Owl and Isshin onto Wolf, both methods give nearly the same result. Bone by bone stays the recommended method for those; try the full body for rigs from other sources.

## The mirrored katana strikes with its edge

### Retarget: Mirror animation

- A mirrored clip moved Wolf's katana into the left hand turned a quarter turn about its blade, so that it struck with the flat side. The mirror reflected the weapon bone across the character's middle plane as seen from the bone's rest, and `R_Weapon` rests with that plane halfway between the katana's edge and its flat. Now the mirror reads the meshes that the bridge's weapon sockets hang on a bone and reflects the bone so that its weapon maps onto itself: the edge stays the edge. On Isshin's clip on Wolf, the mirrored katana now lies within 0.06 cm of the mirror image of the original, against 0.63 cm before, the flat where the edge should be.
- The change is in the bone's motion, which the export writes into the `R_Weapon` track. The game hangs the sword on that bone's dummy, as the bridge's socket does, so the game shows the sword as Blender does.
- Only the weapon in the hand changes. Where Wolf's TAE event 715 moves a weapon to another dummy, such as the katana into its sheath, it keeps its side, as do the sheath, the prosthetic tools, TAE events and weapon part clips.

## Preview lights in new character scenes

- New character scenes get three soft area lights, `Sekiro Preview Key`, `Sekiro Preview Fill` and `Sekiro Preview Rim`, placed around the imported models and scaled with their height. Material Preview now uses the scene's lights and world instead of Blender's built-in studio light, so the character looks in Material Preview as in Rendered view.
- The lights are ordinary scene objects: move, recolor or delete them as you like. They do not change the animation export.
- Scenes made before this version keep their lighting. To get the lights, copy them from a newly created scene.

# 0.11.0 — weapon grips that match the source's, weapons that follow the animation's sockets, panel review, mirror animation, part animations view

Install `SekiroRetargetAssistant-0.7.0.zip` over 0.6.0 for the retarget changes, the reworked panels and Mirror animation.

## Retarget: weapons lie as the source's

The source's grip could leave the weapon visibly turned in the fist, so that it needed a rotation by hand after the bake. Two causes, both measured on Isshin's c5400_a000_003024 on Wolf:

- The bake laid the target's weapon on the source's only by the long axes, by the smallest turn, so the blade's roll about its axis came from how the two weapon bones and models were authored. Wolf's Kusabimaru lay about 50° about the blade from where Isshin's katana lies. Now, where both blades have a flat side, the flat sides are laid on each other too, so the edge faces where the source's does. Of the two ways to lay one on the other, the bake takes the one where the meshes, scaled to the same length, lie closer together, which keeps a curved blade's edge on the source's edge side. A weapon without a flat side, such as a round shaft, keeps the smallest turn. This holds for every bake, whatever the grip, and the turn that the status lists for a weapon bone includes the roll.
- *Source's grip* put the weapon at the source's place in the palm but kept the bake's world turn, so the blade pointed as the source's in the world while the bake turned Wolf's palm about 10° otherwise than Isshin's: in his palm, the blade lay 5.75° off and the edge 42° off. Now the weapon turns in the palm as the source's turns in the source's palm. In Wolf's palm the blade and the edge lie as Isshin's within 0.02°, and the blade points up to 5.75° from Isshin's in the world.
- The second hand's place on the weapon, which turns from the source's weapon into the target's as the bake turns the bone, gets the same roll.

## Weapons follow the animation's sockets

Part clips played on the wrong socket: the bridge kept every weapon model on the one dummy of WepAbsorpPosParam, while the game moves models between dummies and hides them with Wolf's TAE event 715. The opening Loaded Umbrella (`WP_A_0760_1`) sat on the forearm next to the folded one instead of in the left hand.

- With **Auto · game socket** and a source that holds `c0000.anibnd.dcx`, the import reads event 715 of the animation, or of the TAE ID that a weapon's part clip was paired through, for the sword, the Mortal Blade, the grappling hook and the prosthetic tools. A weapon that the event moves follows the other socket's bone while the event lasts, and a model that the event hides, or that has no socket of its own, is hidden on those frames. Changes are keyed constant at the scene's frame rate.
- In the scene, the weapon's rig hangs from a hidden `<MODEL> | Mount` under its socket, which copies one hidden `<MODEL> | Anchor <dummy>` per other socket by keyed constraint influence. The rig stays below the character, so the part export finds it as before.
- The activity log names each weapon that moves, such as *Weapon place: WP_A_0760_1 follows event 715 of a076_405010: dummy 21 (L_Weapon) from 0.00 s*, and the import result counts *N weapons placed by the TAE*. A dummy that the model's FLVER lacks gives a notice, and the weapon stays on its own dummy.
- Not covered: weapons with a placement chosen by hand, individual files without Wolf's TAE, other games, and events 710, 711 and 713.

## Retarget add-on panel review

The Retarget Assistant's panels were reviewed in each of their states and reworked for animators new to Blender: the steps come in order, each says what it needs, and nothing is cut at the sidebar's default width. What the operators do, their names in scripts and the saved settings stay as in add-on 0.6.0, so scenes from 0.6.0 open with the same settings and scripts that call the operators keep working.

### Retarget panel

- The four steps are sub-panels that can be closed once done: **1. Choose rigs**, **2. Match bones**, **3. Bake motion** and **4. Export HKX**. The bake options sit under the Bake button in four groups that start closed, *Pose and timing*, *Body travel*, *Arms and hands* and *Weapons*, and the export's game, format, tracks, frames, root motion and read-back check in *Export settings*, where the export's message about a scene without a recorded game now points. After a bake, the first screen of the sidebar at Blender's default size now reaches past the Export button to the bake's result; in 0.6.0 it ended in the export options, above the Export button.
- **Target (receives the motion)** comes first, then **Source (gives the motion)** with **Append source .blend** right under it, in the order the workflow takes. The button beside each field shows an arrow instead of a second eyedropper next to Blender's own and has a tooltip: it takes the armature selected in the viewport or Outliner. The step warns when both fields hold the same armature.
- A greyed-out button says why under it: **Match bones automatically** until both rigs are chosen, **Bake motion onto target** until the bones are matched or while the target has a control rig, where the bake stopped with an error before, and **Export HKX** until an output file is chosen.
- Once a list exists, the match button reads **Match bones again**, and its tooltip says that a new match replaces the list, changes included. The line above the list counts the bones to review, such as *55 of 58 bones matched, 3 to review.*, and rows matched below 94%, which the review filter lists, show a question mark like unmatched rows instead of a check mark. The list's name filter, under the small triangle below it, now finds target and source bones, and its A–Z sort works; before, both did nothing. The box under the list names its bone. Both mirror buttons have the mirror icon; **Save map** and **Load map** have icons and tooltips and show once both rigs are chosen, since Load map matches by itself.
- *HKX animation bones only* reads **Only bones the clip animates**, with a tooltip that says what it does.
- Menu names stand above their menus and checkboxes have rows of their own, so names such as *Rest stance*, *Root motion* and *Read back and compare* are no longer cut. Messages wrap by the measured width of the interface font at the panel's width and interface scale, instead of a count of characters that cut the status box's lines.
- The status box sits under step 4, below the Export button. **Match bones**, **Save map** and **Load map** report in Blender's status bar, and Load map's status counts the loaded list. A running export's status ends with *Esc cancels.*
- **Blade follows source** shows whole percents.
- New tooltips for the Source and Target fields, *Show unmatched / uncertain only*, the bone list's checkbox and source field, Rest stance, Root motion, Unmapped bones, Clip timing, Travel scale, Format, Rotations, Tracks, the export's Root motion, Replace existing, the fix menu and its Frames, and for **Use selected armature** (formerly *Use active armature*), **Use suggestion**, **Save bone map**, **Load bone map** and **Clear posed frames**.

### Control rig panel

- Before **Add control rig**, a short text says what it adds; the button has the Add icon.
- When the armature is not in Pose Mode, as after opening a file again, the panel says that the controls are posed in Pose Mode and offers a **Pose Mode** button; while another object is active, it says to select the armature.
- A line says what the IK sliders mean, *0 follows FK, 1 follows IK*, and a gap separates the limbs.
- The main button of each step, Match, Bake, Export, Add control rig and **Apply fix**, is taller.

### Fixes

- The alert for a limb in FK reads *Left leg is not in IK on this frame. The fix moves its IK controls, so switch it to IK first.*, on lines of its own with **Switch to IK** below; before, it shared a row with the button and was cut to *Left leg is not…*.
- The auto keying warning of **Adjust over frames** comes right under the hint, before you pose, instead of after **Use this pose**.
- For **Weapon into sheath**, the default that an empty field uses is named under that field.
- The hints, the status after **Use this pose** and the refusals say **Apply fix**, as the button reads, instead of *Apply*.

### Checks

- New Blender test `blender_panels.py`; see VERIFICATION.md.

## Mirror animation

### Retarget add-on: Mirror animation

- **Mirror animation**, a new button under the armature's name in the **Control rig** panel, adds a left-right mirrored copy of the armature's action, "*clip* Mirrored", with mirrored root motion in "*clip* Mirrored RootMotion", and plays it, so that a right-handed slash becomes a left-handed one. The original action and root motion are kept. Both exporters write the copy: **Export HKX** as the active action, and the bridge's export page and CLI by name, pairing its root motion by name. Mirroring the copy gives the original back.
- Each bone with a counterpart takes its counterpart's motion, reflected through both bones' rest frames, so FromSoftware's left and right bones, which rest half a turn from mirror images, mirror correctly where Blender's Paste Flipped Pose turns them wrong. Bones whose names give no side, such as cloth on either hip, pair where one rests at the other's mirrored place. Bones on the middle line reflect their own motion, and root motion's sideways travel and turns change sign.
- Gear changes sides with the motion. Weapon, sheath and shield bones, with the bones without a counterpart between them and the body, go where the reflection puts them, so the katana that the right hand swings goes into the left hand and a scabbard on the left hip goes to the right hip. The bones below them mirror across the piece's own plane, so Isshin's cord around his hilt keeps its shape, and a pair on a piece, such as the eyes of a head held as a weapon, swaps. Gear whose mesh bends with the body, as Wolf's scabbard does, and cases without a mesh keep their side, and the status lists them.
- Other bones without a counterpart keep their own motion where a bone with a counterpart carries them, as sleeve cloth, and otherwise stay on their side and reflect their own motion; the status lists the ones that move. A keyed custom property moves to the counterpart. Constraints are not mirrored, and the status names the bones they act on. With a control rig on the armature the button is greyed out, and the mirror says to remove the control rig first.
- **Mirror L → R** and **Mirror R → L** in the bone list are unchanged.
- New Blender test `blender_mirror.py`; see VERIFICATION.md. The add-on package includes the new module `mirror.py`.

## Part animations view

### Import: start from a weapon part

- **Part animations**, a new view on the import page beside **Source library** and **Individual files**, for Sekiro sources. It works the other way round from **Animate weapon parts**: choose an animated weapon part, such as the Loaded Umbrella `WP_A_0760`, to list its clips, then a clip, such as `a076_412000_1`, to list the player animations that it plays in, each with its archive and the reason. The reason is the same ID, an ID that the part's own TAE gives the clip, or an ID that Wolf's TAE gives the same body clip: *TAE of C0000: a076_412000 plays a070_412000*. Choosing an animation selects it and the part for import and turns on **Animate weapon parts**, so **Create Blender scene** keys the weapon with that clip.
- The view asks the import's own pairing about every player animation, so an animation that it lists is one whose import keys the clip. In the game folder, 23 of the 36 weapon parts animate, and 381 of their 389 clips play in one player animation each. The spears' `a078_425010_1` and `a078_426010_1` and the Finger Whistle's `a079_423000_1` play in none and are marked *not played*.
- Weapon parts show their names from the game, such as *Loaded Umbrella* for `WP_A_0760`, in the new view and in the import's model list for Sekiro. Before, only the Kusabimaru and the Mortal Blade had names.
- The view remembers the chosen part and clip for each source and scrolls them into view. The arrow keys, Home and End move through its lists, and `/` jumps to the part clip search.

### Tests

- New unit tests `test_part_view.py` for the listing, the pairing and the two new routes, and new pairing tests in `test_part_animations.py`. See VERIFICATION.md.

# 0.10.0 — retarget weapon grips and the second hand on the weapon, control rig swivel rings and fixes, app icon and desktop shortcut

Install `SekiroRetargetAssistant-0.6.0.zip` over 0.5.0 for the retarget and control rig changes.

## Retarget: weapon grips

- **Weapon grip**, a new bake option. Before, a weapon in the hand kept the target's rest place in the hand and turned like the source's, so even similar weapons sat badly: with Isshin's clip, Wolf's hilt ended beside his fingers. *Target's own grip*, the default, puts the weapon in the hand as the target's own clip holds it, read from the first frame that shows it, and gives that hand the clip's finger pose, easing over 0.1 s around frames that hide the weapon. The wrist turns, without a twist about the blade, so that the blade points as the source's does. *Source's grip* puts the weapon where the source's weapon sits in the source's palm, scaled to the hand, with the source's blade direction and fingers, for a weapon made to fit the source's grip.
- **Blade follows source** (100% by default) sets how far the wrist turns for the own grip; at 0% it turns as the source's does. Isshin's clip turns Wolf's wrist by up to 44°, Owl's clip by up to 23°. The turn also moves what the hand holds: with Isshin's clip, Wolf's hilt goes up to 9.6 cm into his torso at 100% and 6.4 cm at 0%, so **Keep hands out of the body** moves the hand out by up to 12.3 cm instead of 7.6 cm.
- A target clip that does not animate the weapon takes the source's grip, and one that hides the weapon on every frame gives the grip from a hidden frame, with a warning. A weapon that the bake places in its own hand because it rests away from it, as Owl's katana rests a metre from his hand, takes the own grip too; where the own clip hides it on every frame, it stays where the source holds its weapon, and the status says so. A weapon placed from the other hand keeps its place.

## Retarget: second hand on the weapon

- **Second hand on the weapon**, a new bake option that is on by default: where the source holds its weapon with both hands, the target's other hand goes onto the target's weapon at the same place, on the same side of the axis and at the same distance from the main hand, scaled to the hands and to the length of the hilt, keeping its turn relative to the weapon from the source. The arm reaches the place through a two-bone solve once the hands are kept out of the body, and the hand eases on and off over 0.05 s. The status lists the frames and warns where an arm does not reach. Before, the other hand followed its own source arm and could end some way off the hilt; now Owl's clip on Wolf holds the hilt within 1.2 mm, Isshin's clip on Owl within 4.7 mm.

## Control rig: elbow and knee swivel

- Each IK arm and leg has a swivel ring at its elbow or knee. Turning it swings the joint around the line from the shoulder or hip to the hand or foot, on top of where the pole puts it, while the hand or foot stays: for an elbow that goes into the body after a grip is adjusted. The panel shows **Elbow swivel** and **Knee swivel** under each limb's IK slider. The rings are keyed at 0 on every frame, so a turn on one frame changes that frame only. **Switch to IK** sets the ring back to 0, and **Adjust over frames** spreads its turns. Control rigs added with earlier versions have no rings; remove and add the control rig again to get them.
- **Switch to IK** and **Switch to FK** key a control also on frames where its channel has no key, such as after keys were deleted. Before, they stopped with an error there.

## Control rig: fixes for common cleanup

- **Fixes**, a new box under the control rig panel, does cleanup that takes many steps in Blender itself, for animators new to it. Each fix keys the controls on the chosen frames, the whole clip or a start and end, and eases in and out over **Blend** (0.2 s by default), so the frames around them change smoothly and the frames beyond keep their keys. It adds no constraints, so export and **Remove control rig** treat its keys like any others, and Ctrl+Z undoes it.
- **Hand on weapon** keeps a hand where you pose it relative to a bone, such as the second hand of a two-handed grip on the hilt. It starts with the arm whose other hand holds a weapon with a mesh, following that weapon. Before, this took a Child Of constraint, a bake and an F-curve blend by hand.
- **Weapon into sheath** moves the hand so that the weapon it holds keeps where you pose it on the sheath: posed at the mouth on one frame and fully in on a later one, the blade slides along the sheath between them, also where the clip hides the weapon by shrinking it. It starts with the hand that holds a weapon and the first sheath bone, such as Wolf's `Sheath`.
- **Plant foot** keeps a foot where it stands on the current frame, so it does not slide. With root motion it stays still in the game's world, where export places the character by the root-motion object.
- **Adjust over frames** spreads a change that you pose on one or more frames over a range of frames: an IK control or pole changes relative to the bone above its limb, so the change turns with the body, a swivel ring by its own angle, and selected controls, such as FK rings, change their own channels, as an additive layer would. Between posed frames the change is interpolated.
- **Use this pose** keeps the pose of a frame for the fix, since Blender drops a pose that is not keyed when the frame changes; **Apply** also takes the pose on the current frame. The status lists how far the hand or foot moved, and the frames where the limb could not reach, as IK has no stretch, or was not fully in IK. A limb in FK on all the chosen frames is refused with **Switch to IK**, since switching after the fix would undo it.
- When **Adjust over frames** finds no change, it names the controls it compared and says what to do: to key a posed control that has no keys, which changes every frame at once, or to choose **Selected controls** for a posed control that the limb does not read. The pose stays on the screen.
- New Blender test `blender_fixes.py`; see VERIFICATION.md. The add-on package includes the new module `fixes.py`.

## App icon and desktop shortcut

- The app has its own icon, a bridge arc with a keyframe at its crown, shown in the navigation rail and as the browser tab's icon. Most interface symbols were redrawn in the same style, with rounded corners, and the donor button has a retarget symbol.
- **Create Desktop Shortcut.cmd** in the tool folder puts a *Sekiro Animation Bridge* shortcut with the icon on the desktop. It starts the app as **Start Animation Bridge.cmd** does, without a console window. Run it again after moving the folder.
- The release ZIP includes the icons. `tools/build_icons.js` regenerates the PNG and ICO files from the SVG artwork; it is optional and needs Node.

## Tests

- New Blender test `blender_weapon_grips.py` for the weapon grips and the second hand; `blender_control_rig.py` checks the swivel rings, and a new unit test the finger roots that the grips read. See VERIFICATION.md.

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
