# Devil May Cry 5

The bridge imports Devil May Cry 5 animations and characters into Blender. It does not write DMC5's animation format, so a DMC5 clip goes back into a game in one of two ways:

- **Edit it in Blender** as a reference, a render or a starting point.
- **Retarget it onto a Sekiro, Dark Souls or Elden Ring character** with the Retarget add-on, and export that character's scene as HKX for that game.

What is imported:

- The animations of every player and enemy with a folder under `natives/x64/animation/player` or `enemy`, such as Dante (`pl0100`), Nero (`pl0000`) and the enemies (`em…`). Each motion inside a `.motlist` file is one clip in the list.
- The character's body, head and hair meshes with their skin weights, materials and textures. Other meshes of the same character, such as costumes, can be chosen under the model parts.
- The skeleton of the body mesh, so every bone the model needs is in the rig.

The game folder is only read. The files the bridge needs are copied out of the game's PAK archives into the bridge's own cache.

## What you need

1. Devil May Cry 5 installed, for example through Steam.
2. The bridge and its **RE Engine package**, which reads Devil May Cry 5:
   1. On the bridge's release page, download `AnimationBridge-package-re_engine-<version>.zip` too, next to the bridge ZIP.
   2. In the bridge, open **Settings & setup**. Under **Game packages**, click **Install package…** and choose that ZIP.
   3. The window shows the package: *RE Engine*, its games and its author. Click **Install**.
   4. The Setup page now lists **RE Engine** under **Game packages** and shows **RE Engine decoder: READY**.

   In a source checkout the package is already in `packages\re_engine`. Build its decoder once with `packages\re_engine\decoder\build_decoder.cmd`.
3. The **file list** `DMC5_STM_Release.list`. The PAK archives store a number for each file instead of its name; the file list gives the names back. It is a community file and the bridge does not include it. To get it:
   1. Open [REE.PAK.Tool on GitHub](https://github.com/Ekey/REE.PAK.Tool) in your browser.
   2. Open the folder **Projects**, then the file **DMC5_STM_Release.list**.
   3. Click the **Download raw file** button (the arrow pointing down, at the top right of the file view).
   4. Save it somewhere you keep, for example `Documents\Animation Bridge\DMC5_STM_Release.list`. Do not put it into the game folder.
4. Blender 4.5, and for retargeting the **Sekiro Retarget Assistant** add-on (see the README's *Install*).

## Add the game as a source

1. Open the bridge and go to the **Sources** page.
2. Click **Add source** and choose the game folder, normally `C:\Program Files (x86)\Steam\steamapps\common\Devil May Cry 5`. To find it in Steam: right-click the game, **Manage › Browse local files**.
3. The dialog says it found **a game folder (Devil May Cry 5)** and shows a **File list** field below. Click **Browse** next to it and choose `DMC5_STM_Release.list`.
4. The dialog now counts the animation files, models and materials it found. Click **Save and scan**. The scan takes a few seconds the first time and lists about 47 characters.

A folder with an extracted `natives` folder works too, for example one unpacked with REE.PAK.Tool. Choose the folder that holds `natives`. It needs no file list.

## Import an animation

1. On the **Import animation** page, choose the character, for example **Dante** (`PL0100`). The first time, the bridge reads the character's motlist files, which takes about 5 seconds for Dante's 968 clips.
2. Choose an animation, for example `pl0100_Idle_Normal`. The skeleton preview plays it.
3. Under the model parts, the body, the first head and the first hair are chosen. Leave them, or tick other parts.
4. Click **Create Blender scene**. Dante's idle takes about 15 seconds, the first time about 35, because the textures are extracted and converted.
5. Open the `.blend` in Blender. The rig plays the clip at 60 fps on the timeline. Press **Space** with the mouse over the 3D view to play it.

The activity log may say that some animated bones are not in the skeleton. For Dante these are 14 coat and shoulder helper bones that his clips animate but his body mesh does not have. The rest of the clip is complete; those bones are left out.

## Retarget a DMC5 animation onto a Sekiro character

This puts both characters in one scene; the add-on then moves the DMC5 motion onto the Sekiro character, which you export as an HKX for Sekiro.

1. On the **Import animation** page, choose the DMC5 source, the character and the animation, for example Dante's `pl0100_Idle_Normal`.
2. In the **Retarget donor** block, click **Use this animation as the donor**.
3. Switch the source menu at the top to your Sekiro source and choose the receiving character and one of its animations, for example Wolf (`C0000`) and `a000_000000`. Its animation gives the target its frame rate and settings; the bake replaces the motion.
4. Click **Create Blender scene** and open the `.blend` in Blender.
5. In the 3D view, press **N** to open the sidebar and click the **Retarget** tab. **Source** is already *Donor pl0100* and **Target** is *c0000*.
6. In **2. Match bones**, click **Match bones automatically**. The list pairs the body, arms, legs and fingers by name: Dante's `Hip` with Wolf's `Pelvis`, `L_Shin` with `L_Calf`, `L_IndexF1` with `L_Finger1`, and so on. Rows without a source bone, such as Wolf's cloth and weapon helper bones, keep their own motion.
7. In **3. Bake motion onto target**, click **Bake motion onto target**. Play the timeline: Wolf now moves like Dante.
8. In **4. Export HKX**, click **Export HKX**, or save the scene and export it on the bridge's **Export animation** page.

Dante's idle on Wolf keeps every arm and leg pointing as Dante's within 0.01°; the spine differs by up to 3.5° because Wolf's spine has other proportions. The export writes a Sekiro HKX of 259 frames at 60 fps. In-game playback of such a clip is not checked yet.

Exporting the DMC5 scene itself stops with a message that the bridge cannot write DMC5's format: retarget it first, as above.

## Notes

- **Mirrored clips.** Some DMC5 motions are played mirrored by the game. The bridge imports them as stored; the activity log says so for each such clip.
- **Materials** are a preview: base color, normal map and the cut-out of hair and eyelashes. Transparent eye layers are hidden.
- **Bridge versions before the RE Engine package** scanned DMC5 sources in another format. Scan the source again once: the refresh button beside the source menu does it.
- **Updates.** When the game updates, scan the source again with the refresh button beside the source menu; the bridge also asks for this when an import finds changed archives.
- **Space and units.** DMC5 stores positions in metres with Y up. The bridge turns the scene so that Z is up and the character faces Blender's front view, as for every other game; see [INTERCHANGE.md](../INTERCHANGE.md).
- File versions: motlist 85, mot 65, mesh 1808282334, mdf2 10, tex 11.
