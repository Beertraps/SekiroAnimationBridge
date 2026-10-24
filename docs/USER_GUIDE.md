# User guide

Import an animation into Blender with its skinned character model, edit normally, and export a raw HKX. Use the local UI or the CLI; no Blender add-on is required. Sekiro, DS1/PTDE, Dark Souls Remastered, Dark Souls III and Elden Ring are supported.

See [OTHER_GAMES.md](OTHER_GAMES.md) for the files each game needs, the source-game controls and current evidence. HKX writing and read-back are checked for all five games; no game playback is claimed for the other games. New scenes remember their source game; older scenes need an explicit source-game choice on export.

## Install and start

1. Download `SekiroAnimationBridge-<version>-win-x64.zip` from the repository's Releases page and extract it to a folder you can write to.
2. Double-click **Start Animation Bridge.cmd**. On the first start, a console window prepares the conversion Python: the included uv downloads Python 3.13, Soulstruct, Soulstruct Havok and NumPy into `%LOCALAPPDATA%\SekiroAnimationBridge`. This needs an internet connection and takes a few minutes. Later starts skip it, unless an update pins different libraries.
3. The UI opens in a local app window using Edge, or your default browser. It serves its own files on this computer; there are no external web assets or web service dependencies.
4. If Blender is not found automatically, select your `blender.exe` in **Settings & setup**.

The release ZIP includes the HKX decoder, so no Python, .NET or Git installation is needed. **Settings & setup** checks every tool. To repeat or repair the Python setup, run `tools\setup_writer.cmd`.

To update, extract the new version and start it. Settings and the conversion Python carry over, the new version uses its own decoder, and the retarget add-on finds the version you started last. To remove the bridge, delete its folder and `%LOCALAPPDATA%\SekiroAnimationBridge`; uv keeps its download cache in `%LOCALAPPDATA%\uv\cache`.

From a source checkout, run `tools\setup_writer.cmd` and `tools\SekiroMotionDecoder\build_decoder.cmd` once instead. The README's "Build from source" section lists what they need.

The `.cmd` launchers use a process execution-policy bypass. No persistent PowerShell policy change is needed. Organization policy can still restrict unsigned scripts.

Blender 4.5.14 is verified locally with Wolf and Owl/c5060. The code uses action slots on newer Blender versions, but Blender 5.2 still needs a run on that version.

## Import a folder of DCX files

1. Put the character’s needed archives in a folder outside the game installation. Subfolders are supported; no manual unpacking is required.
2. In **Import animation → Choose your inputs**, select **Folder of DCX files · automatic** and browse to the folder. Browsing starts a scan; use **Scan folder** after changing its contents.
3. Choose a character and animation. Search by clip or archive name. The scan fills the animation, skeleton, compendium, models, material library and texture folder below. Different clips with the same name retain their archive labels.
4. Choose a Wolf outfit or adjust the model selection if needed. For animation only, turn off **Include model**. Choose your scene output and click **Create Blender scene**.

The scan reads ANIBND members, identifies skeletons by character and archive, and matches external compendiums by Havok’s internal type IDs. Separate animation and skeleton compendiums are supported. Missing or ambiguous skeletons are shown beside the clip. “Matched inputs” does not mean every clip type has been decoded: additive animations and float tracks remain unsupported.

Original files stay in place. Only animation/skeleton/compendium members are extracted, into `work/asset-cache`. Binder member paths cannot write outside that cache. Model and texture binders are read directly. A second scan reuses unchanged archive extractions. Scan runs in a separate process and can be cancelled from Activity. Changed source files require a rescan before import.

### Which files to put in the folder

| Purpose | Wolf / c0000 | Example NPC: Owl / c5060 |
| --- | --- | --- |
| Skeleton | `c0000.anibnd.dcx` | `c5060.anibnd.dcx` |
| Animations | A split archive such as `c0000_a000_lo.anibnd.dcx` | Also inside `c5060.anibnd.dcx` |
| Visible model | `fc_m_0200.partsbnd.dcx`, `am_m_9000.partsbnd.dcx`, `bd_m_9000.partsbnd.dcx`, `lg_m_9000.partsbnd.dcx` | `c5060.chrbnd.dcx` |
| Textures | Embedded part textures, plus `common_body.tpf.dcx` | `c5069.texbnd.dcx`, plus `common_body.tpf.dcx` |
| Material library | `allmaterialbnd.mtdbnd.dcx` | `allmaterialbnd.mtdbnd.dcx` |

A folder may contain several characters. The character selector filters animations and chooses the corresponding NPC model. Wolf retains its outfit and individual part controls. Texture IDs need not equal the character ID: matching uses actual material texture names across the supplied packages, without an Owl-specific rule. Keep the folder limited to the packages you need; supplying the whole game means a much larger scan and texture search. Materials and textures are optional for a rig-only import.

For already extracted inputs, choose **Individual files · manual**. Previous settings are preserved when upgrading from 0.3.1.

### DCX support and Oodle

The standalone `dcx_codec.py` and `sekiro_dcx.cmd` ship with the bridge, using the same pinned Soulstruct environment as the writer. The installed Sekiro Modding Agents plugin is not needed. Its bridge’s DCX/DFLT/KRAK handling was inspected; this implementation uses the existing Python codec and also accepts the older DFLT reserved-header variant.

KRAK-compressed DCX requires `oo2core_6_win64.dll` from the user’s own game installation. Steam libraries and Soulstruct’s existing locations are searched automatically. If needed, choose the DLL in **Settings & setup → DCX archive support**, or pass `--oodle` / `-OodleDll` on the CLI. It is used in place and is not distributed with the bridge. DFLT uses Python’s built-in zlib.

Optional DCX command, from a terminal in the tool folder:

```bat
standalone\sekiro_dcx.cmd decompress "D:\Assets\c5060.anibnd.dcx" "D:\Work\c5060.anibnd"
standalone\sekiro_dcx.cmd compress "D:\Work\c5060.anibnd" "D:\Work\c5060.anibnd.dcx" --like "D:\Assets\c5060.anibnd.dcx"
```

The codec handles the outer DCX wrapper only. It does not modify binder contents. Animation export continues to write raw HKX; replace/repack the member separately with WitchyBND. DCX wrapper compression is separate from spline/interleaved animation compression.

Folder CLI import can scan directly and select a unique animation filename:

```bat
standalone\sekiro_animation_cli.cmd import -AssetFolder "D:\Assets\Owl" -AssetClip "a000_003041.hkx" -BlenderExe "C:\Blender\blender.exe" -OutputBlend "D:\Work\Owl.blend"
```

Use `-RigOnly` to omit the model. `discover -AssetFolder "D:\Assets\Owl"` emits a catalog path; pass `-AssetCatalog` and a unique clip ID from that JSON when several archives contain the same clip filename. Existing manual import/export CLI arguments still work. A decoder built before 0.5 needs rebuilding for native PC packfiles and separate skeleton compendiums; release ZIPs include a current one.

## Import an NPC or custom character

1. Select the character's animation, `skeleton.hkx` and matching compendium from its ANIBND. NPC skeletons can reference the compendium as well as the animation; the updated decoder handles both.
2. Select **Auto detect** or **NPC / custom character**. Choose the extracted character folder, or use **Choose files** for `.flver(.dcx)` or `.chrbnd(.dcx)` files. A single model is enough. If a folder has multiple NPC variants, select the one matching your skeleton.
3. Supply the material library and a small folder containing the character's texture packages under **Textures & materials**. TEXBND, TPF and extracted image files are accepted. Texture IDs may differ from the model ID.
4. Choose an output scene and click **Create Blender scene**. The NPC view lists selected models without Wolf's four-part checklist.

For Owl/c5060, the visible mesh is in `chr/c5060.chrbnd.dcx`; textures come from `chr/c5069.texbnd.dcx` and `parts/common_body.tpf.dcx`. His material definitions are in `mtd/allmaterialbnd.mtdbnd.dcx`. Keep the selected texture folder limited to this character's packages.

Owl's `a000_003041.hkx` was imported with its model, edited in Blender, exported to both formats, decoded and re-imported. This checks the conversion pipeline; no new NPC in-game confirmation was performed.

## Import a complete Wolf

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

This is a character preview, not a reconstruction of every Sekiro shader. Layered effects, dynamic skin expressions and Havok cloth simulation are outside this version. Model and texture inputs affect the Blender preview; HKX export writes animation only.

## Wolf weapons

Wolf’s body parts share the character skeleton. Separate weapon models have their own local bones; their placement comes from the character model’s dummy attachment points. The importer keeps each weapon’s armature separate and follows the correct animated bone through the authored socket transform. Weapon bones are not added to the main HKX export rig.

1. Include **`c0000.chrbnd.dcx`** alongside the Wolf assets when importing weapons, or supply its extracted `c0000.flver` in **Textures & materials → Rig attachment model**. The ANIBND skeleton provides bone animation; this CHRBND supplies socket positions and orientations. Folder mode finds it automatically.
2. Select weapon packages under **Weapons & extra parts**. `wp_a_0300.partsbnd.dcx` is the normal katana/Kusabimaru; `wp_a_0310.partsbnd.dcx` is the Mortal Blade. The tool does not choose an equipped loadout from an HKX filename.
3. Leave placement on **Auto · game socket**, or choose **Drawn · right hand**, **Drawn · left hand**, **Hip sheath**, **Back sheath**, or a **Custom dummy ID** for the preview. The separate scabbard stays on the body when its blade is held.

| Automatic placement | Attachment on Wolf |
| --- | --- |
| Katana blade (`0300`, katana variant `0301`) | Dummy 20 → `R_Weapon` |
| Katana scabbard | Dummy 147 → `Sheath` |
| Mortal Blade and its scabbard (`0310`) | Dummy 149 → `LargeSheath` (stowed) |
| Prosthetic families (`0700`–`0791`) | Their authored forearm/hand sockets (112–119, 123, 124) |

The socket profiles are based on vanilla equipment/attachment parameters and c0000’s FLVER dummy data. Unknown prop/cutscene weapon profiles require an explicit placement instead of being left floating at the origin. Modded attachment geometry can be supplied through **Rig attachment model**, and custom dummy IDs can override the vanilla slot choice.

Placement is a preview choice. Equipment state, TAE-driven draw/sheath changes, deployment of prosthetic mechanisms, secondary model visibility and the weapons’ own animation clips are not simulated. Auxiliary meshes retain their authored local rest pose. Shader approximation limits also apply.

Existing `.blend` scenes keep their previous preview setup until re-imported or repaired; updating the scripts does not modify saved scenes.

CLI options: `-ReferenceModel "D:\Assets\c0000.chrbnd.dcx"` and optional `-WeaponAttachmentsFile "D:\Work\attachments.json"`. That JSON maps package IDs to placements, for example `{"wp_a_0310":"right","wp_a_0700":"auto"}`. Custom sockets use `"dummy:112"`. Weapons of the other games are covered in [OTHER_GAMES.md](OTHER_GAMES.md).

## Edit and export

Edit the main animation rig in Blender and save the scene. On the UI's export page, choose the scene and click **Read actions** to list its actions and frame ranges; the file is not changed. Then choose:

- **Action**: the active action, or another action that keys the rig, to export another take.
- **Frame range**: the scene range, the action's keys, the imported clip length, or custom frames. The evaluated pose is sampled by time, so constraints, drivers and NLA strips are baked.
- **Tracks, frame rate and root motion**: *Source clip tracks* keeps the imported track list and is the safest choice; *Source tracks + keyed bones* and *Every skeleton bone* add tracks. The frame rate defaults to the source clip's. Root motion comes from the `HKX_RootMotion` empty, from a bone's travel, or is left out. Bone extraction uses the bone above pelvis and spine by default (Root, RootPos or Master), optionally with vertical travel and turning.
- **Format**: *Interleaved* stores every frame uncompressed; the earlier Sekiro export path was confirmed in game by the user. *Spline* is smaller and lossy, with 40-bit, 48-bit or full-float rotations and a position tolerance. In-game confirmation of spline output is still needed.
- **Read the HKX back**: decodes the written file and reports the largest rotation and translation difference from the sampled pose.

Export creates a raw `.hkx` and adjacent `.motion.json` sidecar. Use WitchyBND to replace the relevant member in your own binder. This tool does not repack animation binders, create a mod profile or launch the game.

Original animation annotations and unrelated HKX metadata are not reproduced. Float tracks, additive animations and TAE gameplay events are outside this version; the decoder rejects float tracks and additive clips explicitly. TAE event times are in seconds: a different frame rate keeps them aligned, but a different clip length does not retime them. Existing scenes from the older prototype remain readable by the exporter.

## Optional Blender retargeting add-on

`SekiroRetargetAssistant-0.2.0.zip` is in the tool folder and on the Releases page. In Blender 4.5, open Edit > Preferences > Add-ons > dropdown menu > Install from Disk, choose this ZIP, and enable **Sekiro Retarget Assistant**. Remove version 0.1.0 first, or restart Blender after installing over it. Press N in the 3D Viewport and open **Retarget**.

Open the receiving character's bridge scene, use **Append source .blend**, run **Match bones automatically**, review the list and **Bake motion onto target**. Then click **Export HKX** in the add-on: it writes the HKX through this bridge, with the same options and checks as the export page. Alternatively, save the scene and export it here.

Bone names do not have to match. The matcher combines normalized names and aliases with each rig's anatomy (hierarchy and rest positions) and left/right position. On owned synthetic rigs of 15 conventions, six of them with scrambled bone names, every core body bone matched in every pairing. On the supplied FromSoftware rigs with scrambled names, all core bones matched for most pairs; pairs with a Dark Souls 1 rig missed one or two spine bones, because its spine has fewer bones.

The bake keeps the target's skeleton, proportions and track layout. It poses the target limbs like the source's rest stance, moves the body with the source hips scaled by leg length, and carries the travel on the bone above hips and spine. Root motion comes from the source, from the body's travel, from the target clip, or is left out. This is FK retargeting: foot contacts and weapon alignment can still need cleanup, and TAE events are not retimed. See [the add-on README](../blender_addon/sekiro_retarget/README.md) for every option.

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

## Local files and support

UI settings are stored in `%LOCALAPPDATA%\SekiroAnimationBridge\ui-settings.json`. Activity logs go under this tool's `work\logs`. The UI has one conversion at a time and can cancel its process tree. Closing the workspace stops its local server; after closing the window, an idle server also exits automatically.

The bridge also records its folder in `%LOCALAPPDATA%\SekiroAnimationBridge\bridge-location.json`, so the retarget add-on can find it.

To run the checks, from the tool folder: `%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe -m unittest discover -s standalone/tests -p "test_*.py"` for the unit tests, and `blender --background --factory-startup --python standalone/tests/<script>.py` for `blender_retarget.py`, `blender_export_options.py` and `blender_synthetic_check.py`. `blender_weapons.py` also needs an output folder after `--`. All fixtures are owned synthetic rigs; no game files are needed.

See [VERIFICATION.md](VERIFICATION.md) for the checks performed on each version. The release ZIP contains no game assets or local settings; besides the source, it includes the prebuilt decoder and uv, listed in [CREDITS.md](../CREDITS.md).
