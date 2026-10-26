# User guide

Import an animation into Blender with its skinned character model, edit normally, and export a raw HKX. Use the local UI or the CLI; no Blender add-on is required. Sekiro, DS1/PTDE, Dark Souls Remastered, Dark Souls III and Elden Ring are supported.

See [OTHER_GAMES.md](OTHER_GAMES.md) for the files each game needs, the source-game controls and current evidence. HKX writing and read-back are checked for all five games; no game playback is claimed for the other games. New scenes remember their source game; older scenes need an explicit source-game choice on export.

## Install and start

1. Download `SekiroAnimationBridge-<version>-win-x64.zip` from the repository's Releases page and extract it to a folder you can write to.
2. Double-click **Start Animation Bridge.cmd**. On the first start, a console window prepares the conversion Python: the included uv downloads Python 3.13, Soulstruct, Soulstruct Havok and NumPy into `%LOCALAPPDATA%\SekiroAnimationBridge`. This needs an internet connection and takes a few minutes. Later starts skip it, unless an update pins different libraries.
3. The UI opens in a local app window using Edge, or your default browser. It serves its own files on this computer; there are no external web assets or web service dependencies.
4. If Blender is not found automatically, select your `blender.exe` in **Settings & setup**.

The release ZIP includes the HKX decoder, so no Python, .NET or Git installation is needed. **Settings & setup** checks every tool. To repeat or repair the Python setup, run `tools\setup_writer.cmd`.

The optional *Spline* export format runs Soulstruct Havok's 32-bit `CompressAnim.exe`, which needs the [Microsoft Visual C++ 2010 Redistributable (x86)](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist#visual-studio-2010-vc-100-sp1-no-longer-supported). Many games install it already; the **Spline compression** check in **Settings & setup** shows whether it is present. Interleaved export, the default, does not need it.

To update, extract the new version and start it. Settings and the conversion Python carry over, the new version uses its own decoder, and the retarget add-on finds the version you started last. To remove the bridge, delete its folder and `%LOCALAPPDATA%\SekiroAnimationBridge`; uv keeps its download cache in `%LOCALAPPDATA%\uv\cache`.

From a source checkout, run `tools\setup_writer.cmd` and `tools\SekiroMotionDecoder\build_decoder.cmd` once instead. The README's "Build from source" section lists what they need.

The `.cmd` launchers use a process execution-policy bypass. No persistent PowerShell policy change is needed. Organization policy can still restrict unsigned scripts.

Blender 4.5.14 is verified locally with Wolf and Owl/c5060. The code uses action slots on newer Blender versions, but Blender 5.2 still needs a run on that version.

## Sources

A source is a folder the bridge reads game files from: a game folder in the game's own structure, a collected folder of archives, or a custom layout. Add one on the **Sources** page or from the source menu at the top of the Import page. The same menu switches between saved sources.

1. Click **Add source** and choose the folder. The dialog shows what it found:
   - **Game folder**: an unpacked game, or a mod folder with the game's structure: `chr` with the animation and character archives, `parts`, and `mtd` (Elden Ring: `material`). Choosing `chr` itself, or a folder whose `Game` (Dark Souls III, Elden Ring) or `DATA` (Prepare to Die) subfolder holds them, uses that game folder. The game is named by its executable, by Elden Ring's `material/allmaterial.matbinbnd.dcx`, or by reading one archive.
   - **Collected folder**: any other folder of archives. Archives that share a folder belong together, and subfolders are read, as in earlier versions.
   - A folder that holds several game folders lists them; choose one.
2. Keep the layout on **Detect**, or choose **Game folder**, **Collected** or **Custom**. Choose the game when it is not recognised.
3. **Scenes folder** is where new `.blend` files go: `Documents\Animation Bridge\<name>` for a game folder, a `Blender` folder inside a collected folder.
4. Click **Save and scan**.

A game folder is listed by file names, because a whole game holds hundreds of animation archives. A character's archives are read when you choose that character, which takes a few seconds at most. Characters read once stay listed while their archives are unchanged, and an import reads a changed archive again. The model, parts, textures and material library are found by character ID across the source's folders, for example `chr/c5060.chrbnd.dcx` for Owl and Wolf's parts in `parts`.

Each source remembers its character, animation, model choice, output file and the overrides under **Textures & materials**; switching sources brings them back. On the Sources page, **Edit** changes a source's folder, layout, game or scenes folder; **Remove source** in that dialog removes it from the list and leaves its files alone. The refresh button beside the source menu scans the active source again, for example after you added archives.

Sources are only read. Animation, skeleton and compendium members are extracted into the bridge's `work/asset-cache`; models and textures are read in place. Outputs inside a game installation are refused.

### Custom layouts

For folders that follow neither structure, such as a mod's archives next to an unpacked game, choose **Custom** and name the folders for each kind of file: animations (ANIBND), character models (CHRBND, FLVER), parts (PARTSBND), textures (TEXBND, TPF) and the material library (MTDBND, MATBINBND). Entries are relative to the source folder or absolute, and a kind can have several folders. When several folders of one kind hold a file of the same name, the first folder listed wins, the way a mod folder overrides the game's files: put the mod's folders first. A name with or without `.dcx` counts as the same file. **Start from the game structure** fills in `chr`, `parts` and `mtd`. Folders that do not exist are marked and skipped; the dialog counts the files it finds in the others. **Include subfolders** also reads below each folder. Files are matched by the character ID at the start of their names, so `c0000_c5060.anibnd.dcx` belongs to c0000.

For example, Owl's animation archive from a mod folder, with his model, textures and material library from the game:

| Kind | Folders |
| --- | --- |
| Animations | `D:\Mods\Owl` |
| Character models | `D:\Games\Sekiro\chr` |
| Textures | `D:\Games\Sekiro\chr`, `D:\Mods\Owl` |
| Material library | `D:\Games\Sekiro\mtd` |

### Import from a source

1. On **Import animation**, keep **Source library** and choose the source in the top bar.
2. Choose a character, then an animation. Filter by clip or archive name, or choose one archive beside the search. The arrow keys move through both lists, and `/` jumps to the animation search.
3. The scene panel checks the animation, skeleton, compendium, model and materials, and **Matched files** lists the inputs. Choose a Wolf outfit or adjust the parts if needed. For animation only, turn off **Model**.
4. Check **Save scene as** and click **Create Blender scene**.

Reading a character inventories its ANIBND members, identifies skeletons by character and archive, and matches external compendiums by Havok’s internal type IDs. Separate animation and skeleton compendiums are supported. A missing or ambiguous skeleton is shown with the clip. A matched clip is not necessarily decodable: additive animations and float tracks remain unsupported.

Binder member paths cannot write outside the cache, and a second scan reuses unchanged archive extractions. Scans run in a separate process and can be cancelled from the activity bar. A collected folder needs a new scan after its files change.

### Import by weapon part

For a Sekiro source, **Part animations** beside **Source library** starts from a weapon instead of a character. It lists the clips of an animated weapon part and the player animations that each clip plays in, so that you can import a weapon's clip with an animation that plays it. See [Animated weapon parts](#animated-weapon-parts) for what these clips are.

1. On **Import animation**, choose **Part animations**. **Weapon parts** lists the source's weapon parts that have clips, with their names from the game and how many clips they have.
2. Choose a part. **Part clips** lists its clips, such as `a076_412000_1` for the umbrella's model `WP_A_0760_1`, with the number of animations that play each one. A part with several animated models, such as Divine Abduction, lists the clips under each model's name. A clip that no player animation plays shows *not played*.
3. Choose a clip. **Plays in** lists the player animations that play it, each with its archive and the reason: *same ID*, an ID that the part's own TAE gives the clip, or an ID that Wolf's TAE gives the same body clip, such as *TAE of C0000: a076_412000 plays a070_412000*. These are the pairings of [Part clips on import](#part-clips-on-import), read the other way round, so the import keys the clip that you chose.
4. Choose an animation. It is selected for import together with the weapon part, and **Animate weapon parts** is turned on. The scene panel and the **Preview** block show the animation as in **Source library**. Check **Save scene as** and click **Create Blender scene**.

A game folder reads Wolf's animation archives the first time that you choose a part. In a collected folder, a part pairs with Wolf's animations in the same folder, as the parts of an import from **Source library** do. The rest pose, `a999_000000`, plays in every animation without a clip of its own and is not listed. The arrow keys, Home and End move through each list, and `/` jumps to the part clip search. The view remembers the part and the clip for each source.

### Clip preview

The **Preview** block at the top of the scene panel plays the chosen animation as a skeleton before you import it: bones as lines and joints as dots over a floor grid, upright as in Blender. It shows a clip from a source as soon as its files are matched, and individual files once the animation and the skeleton are chosen.

- Play and pause with the play button, or with Space or Enter on the canvas. Drag the slider, or press `,` and `.` on the canvas, to step through the frames. The line below the slider shows the frame and the time.
- Drag on the canvas or use the arrow keys to turn the view; double-click resets it.
- **Root motion** moves the skeleton along the clip's root motion and draws its path on the grid. It is off by default, so the skeleton plays in place.
- Bones far from the rest of the skeleton, such as Wolf's camera dummy 4 m away, are left out, so the body fills the view.

The preview decodes the clip with the HKX decoder from Setup and keeps the result in this tool's `work\asset-cache\previews`, so the same clip shows at once the next time; nothing is written beside your files. A very long clip shows only every second or later frame, in the preview only. It starts playing by itself unless Windows' animation effects are off, and pauses while the window is hidden. Collapse the block to stop decoding previews while you browse; the workspace remembers whether it is open.

The preview has no meshes and no weapons. The weapon part clips that will play with the animation are listed below it; see [Animated weapon parts](#animated-weapon-parts).

### Which files to put in a collected folder

| Purpose | Wolf / c0000 | Example NPC: Owl / c5060 |
| --- | --- | --- |
| Skeleton | `c0000.anibnd.dcx` | `c5060.anibnd.dcx` |
| Animations | A split archive such as `c0000_a000_lo.anibnd.dcx` | Also inside `c5060.anibnd.dcx` |
| Visible model | `fc_m_0200.partsbnd.dcx`, `am_m_9000.partsbnd.dcx`, `bd_m_9000.partsbnd.dcx`, `lg_m_9000.partsbnd.dcx` | `c5060.chrbnd.dcx` |
| Textures | Embedded part textures, plus `common_body.tpf.dcx` | `c5069.texbnd.dcx`, plus `common_body.tpf.dcx` |
| Material library | `allmaterialbnd.mtdbnd.dcx` | `allmaterialbnd.mtdbnd.dcx` |

A folder may contain several characters. The character selector filters animations and chooses the corresponding NPC model. Wolf retains its outfit and individual part controls. Texture IDs need not equal the character ID: matching uses actual material texture names across the supplied packages, without an Owl-specific rule. A collected folder is read completely, so keep it limited to the packages you need; for a whole game, add the game folder as a source instead. Materials and textures are optional for a rig-only import.

For already extracted inputs, choose **Individual files**. A single assets folder saved by an earlier version becomes the first source.

### DCX support and Oodle

The standalone `dcx_codec.py` and `sekiro_dcx.cmd` ship with the bridge, using the same pinned Soulstruct environment as the writer. The installed Sekiro Modding Agents plugin is not needed. Its bridge’s DCX/DFLT/KRAK handling was inspected; this implementation uses the existing Python codec and also accepts the older DFLT reserved-header variant.

KRAK-compressed DCX requires `oo2core_6_win64.dll`. The bridge first looks for Sekiro’s copy in your Steam libraries, then for the copy that comes with Soulstruct. If needed, choose the DLL in **Settings & setup → DCX archives**, or pass `--oodle` / `-OodleDll` on the CLI. It is used in place and is not distributed with the bridge. DFLT uses Python’s built-in zlib.

Optional DCX command, from a terminal in the tool folder:

```bat
standalone\sekiro_dcx.cmd decompress "D:\Assets\c5060.anibnd.dcx" "D:\Work\c5060.anibnd"
standalone\sekiro_dcx.cmd compress "D:\Work\c5060.anibnd" "D:\Work\c5060.anibnd.dcx" --like "D:\Assets\c5060.anibnd.dcx"
```

The codec handles the outer DCX wrapper only. It does not modify binder contents. Animation export continues to write raw HKX; replace/repack the member separately with WitchyBND. DCX wrapper compression is separate from spline/interleaved animation compression.

The CLI imports from a source directly and selects an animation by its file name:

```bat
standalone\sekiro_animation_cli.cmd import -AssetFolder "D:\Assets\Owl" -AssetClip "a000_003041.hkx" -BlenderExe "C:\Blender\blender.exe" -OutputBlend "D:\Work\Owl.blend"
standalone\sekiro_animation_cli.cmd import -AssetFolder "D:\Games\Sekiro" -SourceLayout auto -AssetCharacter c5060 -AssetClip "a000_003011.hkx" -BlenderExe "C:\Blender\blender.exe" -OutputBlend "D:\Work\Owl.blend"
```

`-SourceLayout` is `folder` (the default, a collected folder), `game`, `custom` or `auto`. A game or custom source holds many characters, so name one with `-AssetCharacter`. `-SourceLayoutFile "D:\Work\layout.json"` reads a custom layout, such as `{"animations": ["D:\\Mods\\Owl"], "characters": ["D:\\Games\\Sekiro\\chr"], "textures": ["D:\\Games\\Sekiro\\chr"], "materials": ["D:\\Games\\Sekiro\\mtd"]}`. Its entries are relative to `-AssetFolder` unless absolute, and subfolders are read.

Use `-RigOnly` to omit the model. For a collected folder, `discover -AssetFolder "D:\Assets\Owl"` emits a catalog path; pass `-AssetCatalog` and a unique clip ID from that JSON when several archives contain the same clip filename. Existing manual import/export CLI arguments still work. A decoder built before 0.5 needs rebuilding for native PC packfiles and separate skeleton compendiums; release ZIPs include a current one.

## Import an NPC or custom character

From extracted files, with **Individual files**:

1. Select the character's animation, `skeleton.hkx` and matching compendium from its ANIBND. NPC skeletons can reference the compendium as well as the animation; the updated decoder handles both.
2. Select **Auto detect** or **NPC / custom character**. Choose the extracted character folder, or use **Choose files** for `.flver(.dcx)` or `.chrbnd(.dcx)` files. A single model is enough. If a folder has multiple NPC variants, select the one matching your skeleton.
3. Supply the material library and a small folder containing the character's texture packages under **Textures & materials**. TEXBND, TPF and extracted image files are accepted. Texture IDs may differ from the model ID.
4. Choose an output scene and click **Create Blender scene**. The NPC view lists selected models without Wolf's four-part checklist.

For Owl/c5060, the visible mesh is in `chr/c5060.chrbnd.dcx`; textures come from `chr/c5069.texbnd.dcx` and `parts/common_body.tpf.dcx`. His material definitions are in `mtd/allmaterialbnd.mtdbnd.dcx`. Keep the selected texture folder limited to this character's packages.

Owl's `a000_003041.hkx` was imported with its model, edited in Blender, exported to both formats, decoded and re-imported. This checks the conversion pipeline; no new NPC in-game confirmation was performed.

## Import a complete Wolf

A source selects Wolf's standard parts automatically. From extracted files, with **Individual files**:

1. Select the animation HKX, the compendium from the same animation binder, and Wolf's animation skeleton HKX. Use WitchyBND to extract those inputs. A self-contained HKX exported by this tool can be imported with the compendium field empty.
2. Choose the unpacked Sekiro `parts` folder, the unpacked game folder, or a folder containing extracted model parts. The tool reads `.partsbnd(.dcx)` binders directly, including their FLVERs and TPFs. It also accepts loose `.flver(.dcx)` files through **Choose files**.
3. Select a Wolf outfit and click **Find models**. Change individual body parts as needed. Weapons or headwear can be selected under extra parts when present.
4. Select an output `.blend` file and click **Create Blender scene**.

Standard Wolf consists of:

| Part | Standard file ID | Preset alternatives |
| --- | --- | --- |
| Head | `fc_m_0200` | Select another head individually |
| Arms / prosthetic | `am_m_9000` | Tutorial: `am_m_9010` |
| Torso | `bd_m_9000` | Tutorial: `bd_m_9030`; Mortal Blade: `bd_m_9040` |
| Legs | `lg_m_9000` | Select another leg model individually |

The `c0000.flver` inside the character binder contains the base skeleton and has no visible mesh. Select the actual parts for a character preview.

The reader combines split vertex buffers, retains UV layers, normalizes skin weights and maps bones by name. Each part becomes a separate Blender mesh driven by the animation rig. Additional model bones are retained; cutscene parts with a substantially different bind pose use a hidden skin adapter driven by the editable rig.

## Textures

The tool resolves texture names per material. It reads the selected binders' TPFs and shared `common_body.tpf.dcx`, and looks for `mtd\allmaterialbnd.mtdbnd.dcx` beside the parts folder. A small custom `wolf.mtdbnd` library is also supported. Override the material library or supply an additional TPF/image folder under **Textures & materials**.

Alpha-tested fur and hair materials are recognized from their authored alpha thresholds, including NPC materials that use blend mode zero. Sekiro's layered fur and cloth shaders remain approximations in Blender.

Used base-color and normal maps are converted to PNG outside Blender, assigned through the MTD's UV selection, and packed into the `.blend`. Hair transparency and its tint layer are approximated. Materials with an authored solid color retain that color. Missing referenced images produce notices in Activity and a neutral fallback, rather than an unrelated texture assignment.

New scenes include three soft preview lights. Material Preview uses those lights and the scene world, so the character appears similarly in Rendered view. The lights are named `Sekiro Preview Key`, `Sekiro Preview Fill` and `Sekiro Preview Rim` and can be adjusted in Blender without changing animation export. For an older scene, the same lights can be copied from a newly created scene.

This is a character preview, not a reconstruction of every Sekiro shader. Layered effects, dynamic skin expressions and Havok cloth simulation are outside this version. Model and texture inputs affect the Blender preview; HKX export writes animation only.

## Wolf weapons

Wolf’s body parts share the character skeleton. Separate weapon models have their own local bones; their placement comes from the character model’s dummy attachment points. The importer keeps each weapon’s armature separate and follows the correct animated bone through the authored socket transform. Weapon bones are not added to the main HKX export rig.

1. Include **`c0000.chrbnd.dcx`** alongside the Wolf assets when importing weapons, or supply its extracted `c0000.flver` in **Textures & materials → Rig attachment model**. The ANIBND skeleton provides bone animation; this CHRBND supplies socket positions and orientations. A source finds it automatically.
2. Select weapon packages under **Weapons & extra parts**. `wp_a_0300.partsbnd.dcx` is the normal katana/Kusabimaru; `wp_a_0310.partsbnd.dcx` is the Mortal Blade. The tool does not choose an equipped loadout from an HKX filename.
3. Leave placement on **Auto · game socket**, or choose **Drawn · right hand**, **Drawn · left hand**, **Hip sheath**, **Back sheath**, or a **Custom dummy ID** for the preview. The separate scabbard stays on the body when its blade is held.

| Automatic placement | Attachment on Wolf |
| --- | --- |
| Katana blade (`0300`, katana variant `0301`) | Dummy 20 → `R_Weapon` |
| Katana scabbard | Dummy 147 → `Sheath` |
| Mortal Blade and its scabbard (`0310`) | Dummy 149 → `LargeSheath` (stowed) |
| Prosthetic families (`0700`–`0791`) | Their authored forearm/hand sockets (112–119, 123, 124) |

The socket profiles are based on vanilla equipment/attachment parameters and c0000’s FLVER dummy data. Unknown prop/cutscene weapon profiles require an explicit placement instead of being left floating at the origin. Modded attachment geometry can be supplied through **Rig attachment model**, and custom dummy IDs can override the vanilla slot choice.

Placement is a preview choice. Equipment state is not simulated, but with a source that holds Wolf's `c0000.anibnd.dcx` the import follows the draw, sheath and prosthetic moves of the chosen animation; see [Weapons that the animation moves](#weapons-that-the-animation-moves). The weapons’ own animation clips are covered in [Animated weapon parts](#animated-weapon-parts). Auxiliary meshes retain their authored local rest pose. Shader approximation limits also apply.

### Weapons that the animation moves

In the game, an animation can move a weapon to another socket or hide one of its models while it plays: Wolf's TAE event 715. When the Loaded Umbrella opens (`a076_405010`), the folded umbrella on the prosthetic forearm (`WP_A_0760`, dummy 118) is hidden and the opening umbrella (`WP_A_0760_1`) sits in the left hand (dummy 21). Kusabimaru goes into its sheath while a prosthetic tool is out, and the Mortal Blade moves from the back to the right hand when it is drawn. A prosthetic tool's second and third models have no socket of their own, so they are hidden until an animation shows them.

With **Auto · game socket**, the import does the same. It reads the events of the animation's ID in Wolf's TAE, or of the TAE ID that the weapon's part clip was paired through, such as `a076_412000` for `a070_412000`. The activity log names each weapon that moves, such as *Weapon place: WP_A_0760_1 follows event 715 of a076_405010: dummy 21 (L_Weapon) from 0.00 s*, and the import result counts them.

In the scene, such a weapon's rig hangs from a hidden `<MODEL> | Mount` under its socket. The mount copies the hidden `<MODEL> | Anchor <dummy>` of another socket while that socket's constraint influence is keyed to 1, so the weapon follows the hand even when you change the arm's animation. Hiding is keyed on the weapon mesh's *Disable in Viewports* and *Disable in Renders*. Both are keyed constant on the frames of the events, at the scene's frame rate.

This covers the sword (`wp_a_0300`), the Mortal Blade (`wp_a_0310`), the grappling hook (`wp_a_9500`) and the prosthetic tools (`wp_a_0700` to `wp_a_0799`). Other weapons, any weapon with a placement chosen by hand, individual files and other games keep their one socket. Events that hide a weapon (710) or a model mask (711, 713) are not read.

Existing `.blend` scenes keep their previous preview setup until re-imported or repaired; updating the scripts does not modify saved scenes.

CLI options: `-ReferenceModel "D:\Assets\c0000.chrbnd.dcx"` and optional `-WeaponAttachmentsFile "D:\Work\attachments.json"`. That JSON maps package IDs to placements, for example `{"wp_a_0310":"right","wp_a_0700":"auto"}`. Custom sockets use `"dummy:112"`. Weapons of the other games are covered in [OTHER_GAMES.md](OTHER_GAMES.md).

## Animated weapon parts

Some of Wolf's weapons animate their own bones. The Loaded Umbrella opens, the Loaded Axe and the Loaded Spear move, the Mist Raven, Sabimaru, Divine Abduction and the Finger Whistle have clips too, and the Mortal Blade, its sheath and Kusabimaru have a few. Such a weapon's part binder holds an animation binder named after the model it animates: `WP_A_0760_1.anibnd` in `parts\wp_a_0760.partsbnd.dcx` animates the umbrella model `WP_A_0760_1`. Its clips carry Wolf's TAE animation IDs, so `a076_405010_1.hkx` plays while Wolf plays `a076_405010`. The other limits in [Wolf weapons](#wolf-weapons) still apply.

### Part clips on import

With **Animate weapon parts** on, the import keys each selected weapon with the clip it plays with the chosen animation. The option is on by default and shows under **Save scene as** once a weapon is selected. The clip is chosen in this order:

1. The part's clip with the same ID. The part's own TAE can give an ID another clip: the umbrella's `a076_405033` plays `a076_421020_1`.
2. A clip whose ID plays the same body clip in the character's TAE. Wolf's TAE gives the prosthetic tools' `a07X_412000` the body clip `a070_412000`, so with `a070_412000` the umbrella plays `a076_412000_1` and the Loaded Axe `a073_412000_1`; a clip in the tool's own animation category comes first. A source finds the TAE in the character's `c0000.anibnd.dcx`. Individual files skip this step.
3. Otherwise the part holds its rest pose, `a999_000000`, which every animation without a clip of its own shares. It is not keyed.

To start from a part's clip instead and find the animations that play it, use [Import by weapon part](#import-by-weapon-part).

The **Preview** block lists the clip that each selected weapon plays and why; the activity log names them too, and the import result counts them. A part clip is keyed on the weapon's own rig, the hidden `<MODEL> | Weapon rig` armature under its socket, in an action named `<MODEL> | <clip>`, such as `WP_A_0760_1 | a076_405010_1`. The rig gains every bone of the part's skeleton. A part clip keeps its own frame rate on the scene's timeline: a 30 fps part clip in a 60 fps scene is keyed on every second frame. Edit it like any action.

A clip that moves bones the weapon's model lacks is not keyed, and the activity log says so. Which socket the animated model sits on, and when it shows, comes from the animation's TAE; see [Weapons that the animation moves](#weapons-that-the-animation-moves). Without it, the umbrella's opening model would sit on the forearm next to the folded one instead of in the hand. TAE events that hide a weapon or swap its model masks are not applied.

### Part clips on export

**Also export part animations** on the export page also writes the clip of each animated weapon part in the scene. Each is sampled from its weapon rig over the same frames as the character, at the part clip's own frame rate, written in the character HKX's format and settings, and read back like it. A file keeps its member name and goes beside the character's HKX, such as `a076_405010_1.hkx`; two weapons with a clip of the same name each get a folder named after the model. A weapon that holds its rest pose is not written.

Replace the file in the part's animation binder with WitchyBND, for example `WP_A_0760_1.anibnd` inside `parts\wp_a_0760.partsbnd.dcx`. The bridge does not repack binders, and part clips written this way are not yet tested in game.

## Edit and export

Edit the main animation rig in Blender and save the scene. On the UI's export page, choose the scene and click **Read actions** to list its actions and frame ranges; the file is not changed. Then choose:

- **Action**: the active action, or another action that keys the rig, to export another take. With the add-on's control rig on the armature, only actions that animate its controls are listed.
- **Frame range**: the scene range, the action's keys, the imported clip length, or custom frames. The evaluated pose is sampled by time, so constraints, drivers and NLA strips are baked.
- **Tracks, frame rate and root motion**: *Source clip tracks* keeps the imported track list and is the safest choice; *Source tracks + keyed bones* and *Every skeleton bone* add tracks. The frame rate defaults to the source clip's. Root motion comes from the `HKX_RootMotion` empty, from a bone's travel, or is left out. Bone extraction uses the bone above pelvis and spine by default (Root, RootPos or Master), optionally with vertical travel and turning.
- **Format**: *Interleaved* stores every frame uncompressed; the earlier Sekiro export path was confirmed in game by the user. *Spline* is smaller and lossy, with 40-bit, 48-bit or full-float rotations and a position tolerance. It needs the Visual C++ 2010 runtime (x86), see [Install and start](#install-and-start). In-game confirmation of spline output is still needed.
- **Read the HKX back**: decodes the written file and reports the largest rotation and translation difference from the sampled pose.

Export creates a raw `.hkx` and adjacent `.motion.json` sidecar. Use WitchyBND to replace the relevant member in your own binder. This tool does not repack animation binders, create a mod profile or launch the game.

Sekiro and Dark Souls III rigs have a foot target chain on each side: `L_Foot_Target2` and `L_Foot_Target1` hang straight down from `Master`, and `L_Foot_Target` sits on the foot. In the game's clips the chain stands on the foot like an upright column: the target copies its foot on every frame, and the two bones above it keep their reference pose, upright, and move with it; the game most likely reads the targets for foot IK. The export does the same, whatever Blender shows for these bones: each chain is written standing on the exported foot. Feet that you move in Blender take their targets with them. The export log lists the targets.

Original animation annotations and unrelated HKX metadata are not reproduced. Float tracks, additive animations and TAE gameplay events are outside this version; the decoder rejects float tracks and additive clips explicitly. TAE event times are in seconds: a different frame rate keeps them aligned, but a different clip length does not retime them. Existing scenes from the older prototype remain readable by the exporter.

## Optional Blender retargeting add-on

`SekiroRetargetAssistant-0.7.0.zip` is in the tool folder and on the Releases page. In Blender 4.5, open Edit > Preferences > Add-ons > dropdown menu > Install from Disk, choose this ZIP, and enable **Sekiro Retarget Assistant**. Remove an older version first, or restart Blender after installing over it. Press N in the 3D Viewport and open **Retarget**.

The add-on's panel leads through four steps: **1. Choose rigs**, **2. Match bones**, **3. Bake motion** and **4. Export HKX**. Open the receiving character's bridge scene and choose its armature as the target, use **Append source .blend** for the source, which also matches the bones, review the list and click **Bake motion onto target**. Then click **Export HKX** in step 4: it writes the HKX through this bridge, with the same options and checks as the export page. Alternatively, save the scene and export it here. A greyed-out button says under it what it needs first. The bake options and export settings wait in closed groups: the export settings' defaults suit most clips, and the bake starts raw, with the source's weapon grip and the corrections for hands, arms and a second hand on the weapon off.

Bone names do not have to match. The matcher combines normalized names and aliases with each rig's anatomy (hierarchy and rest positions) and left/right position. On owned synthetic rigs of 15 conventions, six of them with scrambled bone names, every core body bone matched in every pairing. On the supplied FromSoftware rigs with scrambled names, all core bones matched for most pairs; pairs with a Dark Souls 1 rig missed one or two spine bones, because its spine has fewer bones.

The bake keeps the target's skeleton, proportions and track layout. It poses the target limbs like the source's rest stance, moves the body with the source hips scaled by leg length, and carries the travel on the bone above hips and spine. Root motion comes from the source, from the body's travel, from the target clip, or is left out. A weapon bone in the hand, such as Wolf's `R_Weapon`, is matched to the weapon the source holds. By default the target takes the source's grip: the weapon lies in the target's palm as the source's lies in the source's palm, its edge facing the same way, with the source's fingers. **Weapon grip** > *Target's own grip* holds it as in the target's own clip instead, with that clip's fingers, and turns the wrist so that the blade points like the source's, for characters that hold their weapons differently. With **Second hand on the weapon**, where the source holds its weapon with both hands, the target's other hand goes onto the weapon too. A weapon that the source holds in the other hand, such as Godfrey's left-hand axe on Isshin's right-hand katana, and a weapon bone that rests away from the hand, such as Isshin's spear, are placed in the hand that holds the source weapon, and they turn, show and hide with it. The eye on a weapon's row in the bone list hides that weapon for the whole clip, as FromSoftware clips hide weapons, by scaling it to 0.1%. **Keep hands out of the body** moves a hand out through its arm where it or its weapon would go into a thicker target torso; clipping that the source animation already has stays. **Keep arms close to the body** does the opposite for a slimmer target: where the source holds an arm close to its own body, the target's arm turns in at the shoulder until it stands as close, at the target's size, instead of being held out. Both are off by default. The target's foot target chains stand upright on its feet, as in the game's clips. This is FK retargeting: foot contacts and other contacts can still need cleanup, and TAE events are not retimed. **Bake method** > *Full body (experimental)* bakes another way: it finds the body in both rigs without a bone list, spreads each chain, such as a spine with another number of bones, over the target's own bones, and keeps planted feet and hands that meet each other where the source's are, at the cost of the limbs' directions. On FromSoftware pairs it gives nearly the same result as the default *Bone by bone*; it is meant for rigs from other sources. See [the add-on README](../blender_addon/sekiro_retarget/README.md) for every option.

For animating by hand, the add-on's **Control rig** panel gives an imported rig animator controls: FK controls that point along the limbs, IK arms and legs with pole targets, swivel rings at the elbows and knees and an IK/FK slider per limb, and a root control. The clip is baked onto the controls without changing the pose; the game bones follow the controls, so export works as before. **Switch to IK** and **Switch to FK** change a limb without a jump, the **Fixes** panel does common cleanup over a range of frames, such as a hand held on a hilt or a foot that slides, and **Remove control rig** bakes the edited motion back onto the game bones or restores the original action. See [Control rig](../blender_addon/sekiro_retarget/README.md#control-rig).

To mirror a clip left to right, so that a right-handed slash becomes a left-handed one, click **Mirror animation** in the same panel. It adds a copy, "*clip* Mirrored", with its root motion "*clip* Mirrored RootMotion", and plays it; the original is kept. Each left bone does what its right bone did, the body leans and turns the other way, root motion travels and turns the other way, and the weapons and scabbards change sides with the swing; a sheath that is part of the clothes, as Wolf's is, and cases without a mesh of their own keep their side, and the status lists them. Export the copy from the add-on, or choose it under **Action** on the export page. See [Mirror animation](../blender_addon/sekiro_retarget/README.md#mirror-animation).

### Import the donor with the target

One import can bring both characters of a retarget into one scene, so the donor needs no scene of its own and no **Append source .blend**:

1. On the import page, choose the donor's animation, from any source or game, and click **Use this animation as the donor** in the **Retarget donor** block. The block keeps it pinned while you choose other animations.
2. Choose the animation of the receiving character, the target. The block shows the donor, and the suggested scene name becomes `<target>_<clip>_from_<donor>_<clip>.blend`.
3. Click **Create Blender scene**. The activity log marks the donor's steps with *Donor:*, and the result names the donor clip.

The scene holds both rigs, each with its own action, root-motion object and embedded HKX metadata. The target is set up exactly as after a single import: it keeps the scene's frame range, frame rate, export rig and selection, so the export page and the add-on's **Export HKX** treat it as before, and **Read actions** leaves out the donor's action. Everything of the donor is named *Donor*: for example the rig `Donor c5060`, `Donor HKX_RootMotion`, the actions `Donor a000_003041_Sekiro` and `Donor a000_003041_RootMotion`, and the metadata text `Sekiro Source - Donor - a000_003041.json`. Rigs of the same name, such as c0000 from Sekiro and Elden Ring, stay apart that way. The donor stands beside the target through its delta location, which leaves its keys as imported and does not change the bake. Its action starts at frame 1 with its own length and frame rate; the bake then sets the scene to the new clip. Weapon part clips are imported for the target only.

When the file opens in Blender, the add-on fills in **Source** with the donor and **Target** with the target, so you continue with **Match bones automatically**. The same animation cannot be both the donor and the target. **Remove** in the **Retarget donor** block goes back to importing one character.

## CLI

From the extracted tool folder:

```powershell
.\standalone\sekiro_animation_cli.cmd import -BlenderExe "D:\Blender\blender.exe" -Animation "D:\SekiroWork\a000_000100.hkx" -Compendium "D:\SekiroWork\a000_lo.compendium" -Skeleton "D:\SekiroWork\c0000_skeleton.hkx" -CharacterSource "D:\SekiroUnpacked\parts" -OutputBlend "D:\SekiroWork\wolf.blend"

.\standalone\sekiro_animation_cli.cmd export -BlenderExe "D:\Blender\blender.exe" -InputBlend "D:\SekiroWork\wolf.blend" -OutputHKX "D:\SekiroWork\a000_000100_edited.hkx" -HKXFormat interleaved
```

Use `-HKXFormat spline` for compressed output. `-WolfPreset tutorial` or `-WolfPreset mortal` changes the assembled outfit. Omit `-CharacterSource` to import only the rig. The CLI uses the conversion Python that the first start of the UI prepares, or that `tools\setup_writer.cmd` creates.

Export options, matching the export page:

| Option | Purpose |
| --- | --- |
| `-Action` | Export another action instead of the active one |
| `-FrameRange scene\|action\|clip\|custom`, `-FrameStart`, `-FrameEnd` | Frames to sample |
| `-FrameRate` | Output rate; the source clip's rate by default |
| `-Tracks original\|keyed\|all` | Track set |
| `-RootMotion auto\|object\|bone\|none`, `-RootBone`, `-RootVertical`, `-RootYaw` | Root motion source |
| `-Quantization threecomp40\|threecomp48\|uncompressed`, `-Tolerance` | Spline rotation precision and tolerance |
| `-NoVerify` | Skip the read-back check |
| `-Game` | Source game of a scene that does not record it |

`inspect -BlenderExe ... -InputBlend ...` lists a scene's actions, frame ranges, tracks and root-motion object without changing it.

Additional options:

| Option | Purpose |
| --- | --- |
| `-PreviewModels` / `-ModelFiles` | Explicit array of model files when calling the PowerShell `.ps1` entry directly |
| `-MaterialBinder` | MTD binder override |
| `-TextureDirectory` | Additional TPF / image directory |
| `-PreviewModel` | Backward-compatible single FLVER or model binder |
| `-PreviewTexture` | Backward-compatible image override; applies to all selected materials |
| `-DecoderExe`, `-WriterPython` | Alternate prepared tools; by default the decoder in the tool folder, else the one `build_decoder.cmd` builds |
| `-Force` | Replace existing output |

For example, from PowerShell:

```powershell
.\standalone\sekiro_animation_cli.ps1 import -BlenderExe "D:\Blender\blender.exe" -Animation "D:\SekiroWork\a000_000100.hkx" -Compendium "D:\SekiroWork\a000_lo.compendium" -Skeleton "D:\SekiroWork\c0000_skeleton.hkx" -PreviewModels @("D:\SekiroWork\head.flver", "D:\SekiroWork\body.flver") -TextureDirectory "D:\SekiroWork\textures" -MaterialBinder "D:\SekiroUnpacked\mtd\allmaterialbnd.mtdbnd.dcx" -OutputBlend "D:\SekiroWork\custom.blend"
```

### Retarget donor options

`import` takes a second clip as the retarget donor through `-Donor` versions of the input options, and builds the two-character scene described in [Import the donor with the target](#import-the-donor-with-the-target). Without a folder or files of its own, the donor reads the target's `-AssetFolder` with its layout, catalog and game.

| Option | Purpose |
| --- | --- |
| `-DonorAssetClip`, `-DonorAssetCharacter` | The donor clip, and its character in a game folder or custom layout |
| `-DonorAssetFolder`, `-DonorAssetCatalog`, `-DonorSourceLayout`, `-DonorSourceLayoutFile`, `-DonorGame` | Another source for the donor, with its own layout and game |
| `-DonorAnimation`, `-DonorSkeleton`, `-DonorCompendium`, `-DonorSkeletonCompendium` | The donor's extracted files instead of a source |
| `-DonorCharacterSource`, `-DonorModels`, `-DonorPreset`, `-DonorRigOnly` | The donor's model, or only its rig |
| `-DonorTextureDirectory`, `-DonorMaterialBinder`, `-DonorReferenceModel` | The donor's additional textures, material library and rig attachment model |

For example, Owl's clip from a collected folder onto Wolf from a game folder:

```powershell
.\standalone\sekiro_animation_cli.cmd import -BlenderExe "D:\Blender\blender.exe" -AssetFolder "D:\SekiroUnpacked" -SourceLayout game -AssetCharacter c0000 -AssetClip "a000_000100.hkx" -DonorAssetFolder "D:\Assets\Owl" -DonorAssetClip "a000_003041.hkx" -OutputBlend "D:\SekiroWork\c0000_a000_000100_from_c5060_a000_003041.blend"
```

### Weapon part options

[Animated weapon parts](#animated-weapon-parts) are keyed on import by default.

| Option | Purpose |
| --- | --- |
| `-NoPartAnimations` | `import`: leave every weapon in its rest pose instead of keying its part clip |
| `-ExportParts` | `export`: also write each animated weapon part's clip beside the HKX, under its member name |

For example, the umbrella's clip with Wolf's `a076_405010.hkx`:

```powershell
.\standalone\sekiro_animation_cli.ps1 export -BlenderExe "D:\Blender\blender.exe" -InputBlend "D:\SekiroWork\c0000_a076_405010.blend" -OutputHKX "D:\SekiroWork\export\a076_405010.hkx" -ExportParts
```

This writes `a076_405010.hkx` and `a076_405010_1.hkx` into `D:\SekiroWork\export`.

## Local files and support

UI settings are stored in `%LOCALAPPDATA%\SekiroAnimationBridge\ui-settings.json` and your sources in `ui-sources.json` beside it, so an older version of the bridge leaves them alone. Scans are in this tool's `work\asset-cache`. Activity logs go under this tool's `work\logs`. The UI has one conversion at a time and can cancel its process tree. Closing the workspace stops its local server; after closing the window, an idle server also exits automatically.

The bridge also records its folder in `%LOCALAPPDATA%\SekiroAnimationBridge\bridge-location.json`, so the retarget add-on can find it.

To run the checks, from the tool folder: `%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe -m unittest discover -s standalone/tests -p "test_*.py"` for the unit tests, and `blender --background --factory-startup --python standalone/tests/<script>.py` for `blender_retarget.py`, `blender_export_options.py`, `blender_synthetic_check.py`, `blender_control_rig.py`, `blender_fixes.py`, `blender_weapon_clearance.py`, `blender_weapon_hands.py`, `blender_weapon_grips.py`, `blender_two_characters.py`, `blender_arm_gap.py`, `blender_foot_targets.py`, `blender_mirror.py` and `blender_preview_lighting.py`. `blender_weapons.py`, `blender_part_animations.py` and `blender_weapon_locations.py` also need an output folder after `--`. All fixtures are owned synthetic rigs; no game files are needed.

See [VERIFICATION.md](VERIFICATION.md) for the checks performed on each version. The release ZIP contains no game assets or local settings; besides the source, it includes the prebuilt decoder and uv, listed in [CREDITS.md](../CREDITS.md).
