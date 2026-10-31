# DOOM Eternal

The bridge imports DOOM Eternal animations and characters into Blender. It does not write DOOM Eternal's animation format, so a DOOM clip goes back into a game in one of three ways:

- **Edit it in Blender** as a reference, a render or a starting point.
- **Retarget it onto a Sekiro, Dark Souls or Elden Ring character** with the Retarget add-on, and export that character's scene as HKX for that game.
- **Write the DOOM character into Sekiro as a new character** with its own model, textures, skeleton and one clip, such as the Marauder as `c1804`. See [Into Sekiro](#into-sekiro). Not yet tested in the game.

What is imported:

- The animations of every character: the Doom Slayer, the demons, the humans and the cinematics. A character is a skeleton, and its clips are all animations that play on that skeleton, wherever the game stores them. The shield soldier's clips play on the blaster soldier's skeleton, so they are listed there.
- The character's models with their skin weights, materials and textures: base color, normal map and glow.
- The looks of a model, such as the blaster soldier's *Base*, *Shield* and *Chaingunner*, each as a part to tick.
- The character's weapons, such as the Marauder's shotgun, each on a joint you choose.

The game folder is only read. The package reads the `.resources` and `.streamdb` files in place, with the game's own `oo2core_8_win64.dll`, and needs no other program.

## What you need

1. DOOM Eternal installed, for example through Steam.
2. The bridge with its **DOOM Eternal package**. A source checkout loads it from `packages\doom_eternal`; it is pure Python and needs no build step. Releases do not include it. To use it with a release, build its ZIP in a source checkout:

   ```bat
   python tools\package_game_package.py packages\doom_eternal --output dist\AnimationBridge-package-doom_eternal.zip
   ```

   Then, in the bridge, open **Settings & setup**, click **Install package…** under **Game packages** and choose that ZIP.
3. Blender 4.5, and for retargeting the **Sekiro Retarget Assistant** add-on (see the README's *Install*).

## Add the game as a source

1. Open the bridge and go to the **Sources** page.
2. Click **Add source** and choose the game folder, normally `C:\Program Files (x86)\Steam\steamapps\common\DOOMEternal`. To find it in Steam: right-click the game, **Manage › Browse local files**.
3. The dialog says it found **a game folder (DOOM Eternal)** and counts 16,888 animations and 196 character skeletons. Click **Save and scan**.
4. The first scan reads which skeleton each animation plays on. It lists 158 characters that have clips.

## Import an animation

1. On the **Import animation** page, choose the character, for example **Marauder**. It has 352 clips; 316 of them can be imported. The other 36 are additive: the game adds them on top of another clip, so they have no pose of their own.
2. Choose an animation, for example `combat/quickdraw`, where the Marauder draws his shotgun and fires. The skeleton preview plays it.
3. Under the model parts, `marauder` is ticked. Tick other parts if you want them. See [Model parts](#model-parts).
4. Click **Create Blender scene**.
5. Open the `.blend` in Blender. The rig plays the clip at 30 fps on the timeline. Press **Space** with the mouse over the 3D view to play it.

## Model parts

Each row names the part, its role and a note:

- **Body · with head**: the model is the whole character, as the Marauder, the demons and the third-person Doom Slayer are.
- **Body · without head**: the model has no head, such as `marine` of the first-person Doom Slayer.
- **A look**, such as `soldier_blaster · Base`, `· Shield` and `· Chaingunner`: the meshes the game shows together for one version of the character. The first look is ticked. Tick one look of a model, not two.
- **A skin**, such as `marauder_set2 · set2`: another model of the same character, from the game's customization folders.
- **Weapon**: a model of its own that the character holds or wears, listed after the bodies, such as `maraudergun`. The note says *shown from the start* or *hidden until the game shows it*. Tick it, and choose in the menu beside it where it hangs. The menu lists the places the game itself hangs it, each as the place's name and the joint, such as **Left hand · weapon_part01_lf** and **Holster hip left · gunholster_part01_lf**. The first one is chosen.

Characters with weapons:

| Character | Weapons |
| --- | --- |
| Marauder | `maraudergun` |
| Doomslayer (cinematics) | `shotgun_3p`, `double_barrel_3p`, `chainsaw_3p`, `rocketlauncher_3p`, `chaingun`, `unmaykr_3p`, all in the right hand |
| Doom Marine 3P | 13, such as `heavy_cannon_3p`, `bfg_3p` and `crucible_3p` |
| Gladiator | `gladiator_shield`, `gladiator_flailhead` |
| Demonic Troops | `reaper_3p` |
| Soldier Blaster | `grenade` |

The Marauder with his shotgun in his hand: tick `maraudergun` and keep **Left hand · weapon_part01_lf**. In `combat/quickdraw` the gun rests at his hip on the first frame, because the game moves the hand's weapon joint to the holster, and comes to his hand as he draws.

In Blender, a weapon's bones hang below its joint and are named after it, such as `maraudergun_origin`: the weapon moves with the hand. It is part of the scene like the body, so a new Sekiro character made from the scene holds it too.

Left out without a notice:

- **Gore pieces**: the chunks and severed limbs the game shows when a demon is torn apart. The Marauder's model holds 45 meshes; his look keeps 17 of them.
- **Glow cards**: flat squares the game adds as light around an energy blade, such as `marauder_axe_blade_effect`. They are hidden in Blender and left out of a Sekiro export.

When none of the ticked parts has a head, the activity log says so.

## Into Sekiro

1. Import the character with its parts, as above.
2. On the **Character** page, or with `bridge_cli character-export`, write the scene as a new character. For example:

   ```bat
   standalone\bridge_cli.cmd character-export work\scenes\marauder.blend --game-folder "C:\Program Files (x86)\Steam\steamapps\common\Sekiro" --id c1804 --output work\mods\doom_marauder
   ```

3. The export pairs the character's bones with the template's by name, with the bone names of the package. This needs a body like a human's, such as the Marauder's. A spider such as the Arachnotron stops with *These template bones have no partner in the scene: L_Thigh, L_Calf, L_Foot, R_Thigh, R_Calf, R_Foot.*

Textures: each material gets an `_a` from its base color and an `_n` from its normal map, with green turned the way Sekiro reads it. DOOM Eternal keeps a specular color and a smoothness where Sekiro keeps metalness and roughness, so no `_m` is written; see [Notes](#notes).

## Notes

- **Materials** are a preview: base color, normal map, glow, and the cut-out of hair and other alpha-tested surfaces. The specular color (`_s`) and smoothness (`_g`) images are left out. They are not metalness and roughness: the Marauder's skin reflects as brightly as metal would (median 0.51 in `marauder_head_s`, 0.47 in `marauder_body_s`), so no rule can tell metal from skin in them.
- **Normal maps** are of two kinds. Of the 981 normal maps of the character models, 935 point green up the image, as OpenGL does, such as `marauder_body_n`, `imp_torso_n` and `doomslayer_helmet_local`. 33 point it down, as DirectX does, such as `cacodemon_e_local`, `imp_wounds_local` and `doomslayer_hair_n`. The game files mark both kinds alike, so the package measures each image when it converts it, and the Blender material and the Sekiro export read it the right way. Where the measure cannot tell (9 maps), and for the one map in another format (`samur_maykr_ball_n`, BC7), the package uses OpenGL.
- **Energy surfaces** such as the Marauder's axe blade and the Khan Maykr's wings have no base color image. They show as flat gray, and Blender's `verify` reports them under *base colors*.
- **Units.** Some clips store their positions in game units (0.01905 m); the bridge converts them to metres and says so in the activity log.
- **Updates.** When the game updates, scan the source again with the refresh button beside the source menu; the bridge also asks for this when an import finds changed archives.
- **Space.** DOOM Eternal stores positions in metres with Z up and the character facing +X. The bridge turns the scene so that the character faces Blender's front view, as for every other game; see [INTERCHANGE.md](../INTERCHANGE.md).
- File formats: `.resources` version 12, `md6skl` skeletons, `md6anim` clips, `md6mesh` models, `material2` and `md6def` decls, BIM images. The formats are ported from [Valen](https://github.com/jandk/valen) by Jan De Kock.
