# Unreal Engine games

The bridge imports animations and characters of Unreal Engine 4 and 5 games into Blender with its **Unreal Engine package**. One package reads every UE4 and UE5 game: the engine's archive and asset formats are the same across games, and what differs (the engine version, an encryption key, a mappings file) is set per source in the source dialog.

The bridge does not write Unreal's formats, so an Unreal clip goes back into a game in one of two ways:

- **Edit it in Blender** as a reference, a render or a starting point.
- **Retarget it onto a Sekiro, Dark Souls or Elden Ring character** with the Retarget add-on, and export that character's scene as HKX for that game.

**Status: experimental.** The package has been checked with the files of Deep Rock Galactic (the Xbox app version, Unreal Engine 4.27): the scan, and imports of the dwarves and Glyphids with their models into Blender. With Star Wars Zero Company (Unreal Engine 5) the scan was checked as far as it goes without a mappings file, which it asks for. Imports from Unreal Engine 5 games, ACL-compressed clips, AES keys, mappings files and retargeting an Unreal clip are not checked with a real game yet. The package is not in the release ZIPs: it loads in a source checkout of the bridge, or from its own package ZIP.

What is imported:

- The animation sequences (`AnimSequence` assets) in the game's archives. Each skeleton that has animations is one character in the list, named after the skeleton: `SK_Hero_Skeleton` shows as **Hero**. Each animation sequence is one clip.
- The skeletal meshes made for that skeleton, with their skin weights (the four strongest bones of each vertex), their most detailed level of detail, their material slots and the base color and normal map textures (at most 2048 pixels on a side).
- The skeleton of the chosen mesh, so every bone the model needs is in the rig.

The game folder is only read. The decoder reads the PAK or IoStore archives in place; only the meshes and textures of an import are written, into the bridge's own cache.

## What you need

1. The game installed.
2. The Unreal package, in one of two ways:
   - **Its package ZIP**, `AnimationBridge-package-unreal-<version>.zip`, which holds the package with its decoder built. In the bridge, open **Settings & setup**, click **Install package…** under **Game packages**, choose the ZIP and confirm. **Unreal decoder: READY** then shows there, and you skip step 3.

     Install it into a bridge folder unpacked from the release ZIP alone. GitHub's *Source code* ZIP of a release has a `packages\unreal` folder without the decoder, and the bridge uses a package in its own folder instead of the installed one. If you unpacked that ZIP into the bridge folder, delete the bridge's `packages\unreal` folder first.
   - **A source checkout** of the bridge, set up as the README's *Build from source* describes. The Unreal package is in `packages\unreal`.
3. In a source checkout, the package's decoder, built once. It needs the [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0) (not only the runtime) and [Git](https://git-scm.com/):
   1. Open a command prompt in the bridge folder.
   2. Run `packages\unreal\decoder\build_decoder.cmd`.
   3. The script downloads [CUE4Parse](https://github.com/FabianFG/CUE4Parse) at a fixed commit into `%LOCALAPPDATA%\SekiroAnimationBridge\CUE4Parse`, builds `packages\unreal\tools\unreal-decoder\UnrealDecoder.exe` and tests it. It ends with *Unreal decoder ready*.
   4. In the bridge, **Settings & setup** shows **Unreal decoder: READY** under **Game packages**.

   The decoder carries its own .NET 10 runtime, so it runs without .NET installed. The bridge's other decoders keep using its shared .NET 9 runtime. The runtime comes from the SDK: if the script stops because the runtime *has a known vulnerability*, update the .NET 10 SDK and run the script again.

   Many Unreal Engine 5 games compress their animations with ACL. CUE4Parse decodes ACL with a native library, which the script builds only when [CMake](https://cmake.org/download/) and the Visual Studio C++ build tools are installed; it then also downloads the ACL sources. Without them the script warns that ACL clips will not decode, and every other clip still works. To add ACL later:
   1. Install both from a command prompt:

      ```
      winget install --id Kitware.CMake -e
      winget install --id Microsoft.VisualStudio.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
      ```

      Windows asks for permission for each installer; click **Yes**. If no window appears, click the flashing shield icon in the taskbar. The second installer shows its own progress window and takes several minutes.
   2. Open a new command prompt, so that it finds CMake, and run `packages\unreal\decoder\build_decoder.cmd` again. It now prints *Native ACL decoding: available*.

   The script copies the licenses of what the decoder folder carries next to it: CUE4Parse's `LICENSE` and `NOTICE`, the .NET runtime's `LICENSE.TXT` and `THIRD-PARTY-NOTICES.TXT`, and, with the native library, the licenses of ACL and RTM. To give the package to someone without a source checkout, build its package ZIP from the bridge folder:

   ```
   python tools\package_game_package.py packages\unreal --output dist\AnimationBridge-package-unreal-0.1.0.zip --tool decoder=packages\unreal\tools\unreal-decoder
   ```
4. Depending on the game, one or more of these. The source dialog asks for the ones your game needs.
   - **The AES key**, when the game's archives are encrypted. It is `0x` followed by 64 hexadecimal digits. The bridge does not include keys: use the one published for your game version, for example by the game's modding community.
   - **A mappings file** (`.usmap`), when the game's packages store their properties without names, which many Unreal Engine 5 games do. It is made while the game runs, by a dumper such as [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS). The bridge does not include mappings files.
   - **The Oodle library**, only when the archives use Oodle compression and the built-in decompressor cannot read them. Choose the game's own `oo2core_*_win64.dll`, if the game folder has one. The bridge never downloads it.
5. Blender 4.5, and for retargeting the **Sekiro Retarget Assistant** add-on (see the README's *Install*).

## Add the game as a source

1. Open the bridge and go to the **Sources** page.
2. Click **Add source** and choose the game folder, for example `C:\Program Files (x86)\Steam\steamapps\common\<game>`. To find it in Steam: right-click the game, **Manage › Browse local files**. The game's project folder (the one with `Content\Paks`), its `Paks` folder or its `Binaries\Win64` folder work too. Xbox app installs keep the project one folder deeper, in `C:\XboxGames\<game>\Content\<project>`; choosing `C:\XboxGames\<game>` works.
3. The dialog says it found **a game folder (Unreal Engine game)**, or the game's own name for the games the package knows. It names the engine version and where that came from: the game's executable, the package's entry for the game, or a guess from the archive format.
4. Below are the fields this game needs:
   - **Engine version**: leave it at **Auto**. When the dialog says the version is a guess, or the scan or a clip fails with a message about the engine version, choose the game's version here.
   - **Mappings file**: click **Browse** and choose the game's `.usmap`, if it needs one. The dialog says so for IoStore games, which are the ones that usually need it.
   - **AES key**, only for encrypted games: paste the key.
   - **Oodle library**, only for archives that use Oodle: leave it empty unless the scan fails to decompress them.
5. Click **Save and scan**. The scan reads the game's asset registry and lists one character per skeleton that has animations. The first scan of a large game can take a while. Later scans reuse it until the game's archives change.

## Import an animation

1. On the **Import animation** page, choose the character (a skeleton). Its clips are listed at once.
2. Choose an animation. The skeleton preview plays it.
3. Under the model parts, the skeletal mesh named like the skeleton is chosen, for example `SK_Hero` for `SK_Hero_Skeleton`. Other meshes made for the same skeleton, such as heads, hair or outfits, can be ticked too.
4. Click **Create Blender scene**.
5. Open the `.blend` in Blender. Press **Space** with the mouse over the 3D view to play the clip.

The activity log may say that some animated bones are not in the mesh. These are often helper bones such as `ik_foot_l`, which the game's animations move but the mesh does not use. The rest of the clip is complete; those bones are left out.

## Retarget an Unreal animation onto a Sekiro character

This puts both characters in one scene; the add-on then moves the Unreal motion onto the Sekiro character, which you export as an HKX for Sekiro.

1. On the **Import animation** page, choose the Unreal source, the character and the animation.
2. In the **Retarget donor** block, click **Use this animation as the donor**.
3. Switch the source menu at the top to your Sekiro source and choose the receiving character and one of its animations, for example Wolf (`C0000`) and `a000_000000`. Its animation gives the target its frame rate and settings; the bake replaces the motion.
4. Click **Create Blender scene** and open the `.blend` in Blender.
5. In the 3D view, press **N** to open the sidebar and click the **Retarget** tab. **Source** is the donor and **Target** is `c0000`.
6. In **2. Match bones**, click **Match bones automatically**. The add-on knows the bone names of Epic's mannequin, which many games keep: `pelvis`, `spine_01`, `thigh_l`, `calf_l`, `upperarm_l`, `lowerarm_l`, `hand_l`, `index_01_l` and so on. For a skeleton with other names, pair the remaining bones by hand in the list.
7. In **3. Bake motion onto target**, click **Bake motion onto target**. Play the timeline to check it.
8. In **4. Export HKX**, click **Export HKX**, or save the scene and export it on the bridge's **Export animation** page.

## Messages and what to do

To change a source's fields, click **Edit** on its card on the **Sources** page, change them and click **Save and scan**.

- **Unreal decoder is not built yet**: the bridge folder has the package's sources but no decoder, as a folder unpacked from GitHub's *Source code* ZIP has. The source dialog says so as soon as you choose the game folder. Build the decoder (step 3 of *What you need*), or delete the bridge's `packages\unreal` folder and install the package ZIP.
- **Unreal decoder is missing … Install the package again from its package ZIP**: the installed package lost its decoder, for example to a virus scanner. Install the ZIP again.
- **This game stores properties without names**: it needs a mappings file. Edit the source and choose its `.usmap` under **Mappings file**.
- **… package headers could not be read, so their assets name no skeleton**: the scan found the animations but could not read which skeleton each one uses. The last line says what to do: choose the game's mappings file, or another engine version. When the engine version was a guess, try the next newer version first.
- **… uses ACL compression, and this decoder was built without CUE4Parse's native ACL library**: install CMake and the Visual Studio C++ build tools and run `packages\unreal\decoder\build_decoder.cmd` again.
- **A message about the engine version**, or packages that cannot be read: edit the source and choose the game's version under **Engine version**. The wrong version reads the files wrongly or not at all.
- **Archives stay closed without their AES key**: the key is missing or wrong. Check that it is the key for your game version.
- **The game was updated since the last scan**: scan the source again with the refresh button beside the source menu.

## Notes

- **Additive clips** store only the difference to a base pose. The bridge imports them added to that pose, as full poses; the activity log says so.
- **Root motion.** Clips the game moves the character with keep that movement on their root bone. The bridge does not extract it as separate root motion.
- **Play rate.** When the game plays a clip faster or slower than stored, the log says so; the clip keeps its stored timing.
- **Materials** are a preview: base color, normal map and the cut-out of masked materials. Emissive and mask textures are not used. The bridge does not run a game's material graphs; it takes textures and colors by their parameter names. A material that mixes its color in the graph, for example two tints through a pattern as many Deep Rock Galactic props do, shows the pattern texture or one flat color.
- **Keys and files stay on your computer.** The AES key and the paths you choose are stored with the source in the bridge's settings and in its cache. The bridge sends them nowhere.
- **Space and units.** Unreal stores positions in centimetres with Z up, in a left-handed system. The bridge converts it once, so the character stands on Blender's floor and faces its front view, as for every other game; see [INTERCHANGE.md](../INTERCHANGE.md).
- **Games the package knows.** Deep Rock Galactic is named and set to Unreal Engine 4.27, because its Xbox app executable cannot be read for the version. Every other game shows as *Unreal Engine game* and works the same way.
