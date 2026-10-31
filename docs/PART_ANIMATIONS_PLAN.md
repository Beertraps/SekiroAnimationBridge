# New part animations, from Sekiro and other games

Plan of 2026-10-30. Part 4.1 was built on 2026-10-31 (see its section); the rest is not built yet. Facts marked *checked* were read from Steam Sekiro (unpacked with UXM, read only) and the bridge's code on that date.

## Summary

Today the bridge can edit a part clip that a Sekiro weapon already has and write it as HKX. It cannot add a clip, it cannot put the clip into the game's files, and it cannot take a weapon's motion from another game. This plan adds four things, in this order:

1. **New part clips for Sekiro weapons that have a part skeleton.** Any weapon rig can be keyed for any animation ID, also one where the weapon holds its rest pose, and the export writes the part binder into a mod folder.
2. **An animation binder for weapons that have none**, such as the prosthetic arm `wp_a_0700`. This depends on an in-game test.
3. **Animated bones for NPC weapons**, which are bones of the character's own skeleton, not parts.
4. **Weapon motion from other games**: imported onto the weapon's bones, then into a new Sekiro character, onto a Sekiro weapon, or later as a whole new Sekiro weapon.

## 1. What Sekiro does (checked)

- A weapon is a part binder: `parts\wp_a_0760.partsbnd.dcx` holds `WP_A_0760.tpf`, the models `WP_A_0760.flver` and `WP_A_0760_1.flver`, and one animation binder per animated model, `WP_A_0760.anibnd` and `WP_A_0760_1.anibnd`.
- An animation binder holds the part's skeleton, a compendium, often a TAE, and the clips. The clips of model `_1` end in `_1`: `skeleton_1.hkx`, `a076_405010_1.hkx`.
- 78 weapon part binders: 52 hold 73 animation binders, 26 hold none (among them `wp_a_0700`, `wp_a_0301`, `wp_a_0320`). Every animation binder has the rest clip `a999_000000`.
- A part clip plays while the character plays the TAE ID of the same number (`part_animations.py`, checked on every animated prosthetic tool). No TAE event starts it. The part's own TAE can give an ID another clip: the umbrella's `a076_405033` plays `a076_421020_1`.
- Whether a part clip needs a TAE entry in the part is open. 7 animation binders have no TAE, but all of them are in `_l` or `_m` files, and the ones with clips besides the rest clip are `_m` files: `WP_A_0201.anibnd` (`a003_029001`, `a003_029006`), `WP_A_0300_5.anibnd` (`a023_385090_5`) and `WP_A_9500.anibnd` in `wp_a_9500_m` (9 clips). 31 animation binders hold clips that their TAE does not list, often only `a999_000000`.
- Some weapons come in more files: `wp_a_0300.partsbnd.dcx` and `wp_a_0300_l.partsbnd.dcx` both hold `WP_A_0300.anibnd`, with smaller models in the `_l` file. `_m` files, such as `wp_a_9500_m`, hold other copies, probably for cutscenes.
- NPC weapons are not parts. `c1010`'s spear hangs on its skeleton bone `Spear`, and its motion is in the body clips.
- Vanilla body clips bind every bone in order: Wolf's `a000_003017` has 112 tracks for 112 bones.

## 2. What the bridge does today (checked)

- **Import** (`part_animations.plan()` and `prepare()`): each chosen weapon gets the clip that pairs with the body clip, keyed on its weapon rig in an action `<MODEL> | <clip>`. The clip, decoded, is stored in the rig (`sekiro_part_source_text_data`). A weapon that holds its rest pose gets no clip and no stored data.
- **Export** (`blender_parts.export_parts()`, `bridge_runtime.part_outputs()`): only rigs with stored data are written. Each keeps its clip's member name, skeleton and track list. The HKX goes beside the body clip; the user puts it into the part binder with WitchyBND.
- **Add to an animation binder** writes a body clip into a character's animation binder that the user chooses, with a `.bak` copy. It does not open part binders.
- **New Sekiro characters** fold a weapon rig's bones into the new skeleton, and their motion into the one body clip. **Write model only** gives bones outside the skeleton no track.
- **Game packages** must set `part_animations` to false. Devil May Cry 5 weapons with their own animation, Cavaliere (`WP01_009`) and King Cerberus (`WP01_007`), stay in their rest pose. The package scans only `animation/player` and `animation/enemy`: 471 motlists.

## 3. Decisions for the user

| # | Question | Recommendation |
| --- | --- | --- |
| D1 | Which part comes first? | Part 4.1, then the in-game test M1 before parts 4.2 to 4.4. |
| D2 | Where do written part binders go? | A mod folder with a me3 profile, as the character export does (`parts\wp_a_0760.partsbnd.dcx`). The other choice edits a binder the user picks, as **Add to an animation binder** does. |
| D3 | Does a new part clip get a TAE entry in the part? | Test both in M2: the clip alone, then with an entry. Writing an entry needs a `tae` command in `SekiroCharacterWriter` (SoulsFormats `TAE`). |
| D4 | From another game, which result matters most? | A new Sekiro character works once the import keys the weapon (4.4a). A whole new Sekiro weapon (4.4c) is the bigger goal and needs its own plan. |

## 4. Design

### 4.1 New part clips for weapons with a part skeleton

**Built on 2026-10-31**, with these changes to the design below. D2 is decided: a mod folder.

- A weapon at rest keys its rest clip's first frame on frame 1, since the rest pose is not always the bind pose: `WP_A_0760`'s rest clip scales its root to 0.8. Its rig keeps the weighted bones and their parents, so that new characters made from such scenes keep their bone count.
- The export writes a rest rig only when a sample leaves the rest clip by more than 1e-4. A new clip runs at 30 fps, since rest clips run at 3, 30 or 0.33 fps. Its tracks are the rest clip's, which list every skeleton bone; tracks of bones that the rig lacks hold the rest clip's pose.
- Request options `writeParts`, `partsFolder` and `partId`; `bridge_cli export --write-parts FOLDER --part-id ID` and `bridge_cli part-verify FOLDER`. Code: `part_export.py`, `binder_members.put_member()` with `PART_CLIP`, `blender_parts.keyed_rest()`.
- A clip whose name is the character HKX's own goes into a folder named after its model.

- **Import.** Every chosen weapon whose model has an animation binder gets its part skeleton and the decoded rest clip `a999_000000` stored in its rig, also when it holds its rest pose. The rig records its part binder, its animation binder and the model's suffix (`_1`). The rest clip is not keyed, as now.
- **Export.** Every weapon rig with stored data is written when its action keys a bone, or when it came with a clip. The clip is named after the TAE ID it plays with and the model's suffix: `a000_003000_1.hkx` for the umbrella's model `_1` with Wolf's `a000_003000`. The ID is the body clip's by default; the UI and `bridge_cli export --part-id` can set another.
- **Tracks.** A clip that existed keeps its track list. A new clip gets one track for each bone of the part skeleton that the rig has, as the rest clip lists them.
- **Write.** New request option `writeParts` with an output folder. The export reads each weapon's part binder from the game folder, adds or replaces the clip in its animation binder, and writes the part binder into `<mod>\parts\`, together with its `_l` copy when the game has one. `_m` files stay as they are. A me3 profile goes beside the folder. Nothing is written into the game folder (`dcx_codec.protect_output`). Binder code: `character_export.read_binder()` and `write_binder()`, with the animation binder opened as a member.
- **Check.** New `part-verify`: each written part binder reads back, each clip decodes on its part skeleton, member names match the model's suffix, and both copies hold the same clips.
- **Notices.** A new ID that the character's TAE does not have plays only after a body clip of that ID is added with its TAE entry, as **Add to an animation binder** already says.

### 4.2 An animation binder for a weapon that has none

- 26 part binders have no animation binder. The export builds `WP_A_0700.anibnd`: a skeleton from the FLVER's bones, written over another weapon's `skeleton.hkx` with `havok_tagfile.write_skeleton()` as the character export writes skeletons; that weapon's compendium; a rest clip `a999_000000`; and the new clips.
- Nobody knows yet whether the game loads an animation binder that a weapon did not have. Build 4.2 only after M3 passes on a binder made by hand.

### 4.3 Animated bones for NPC weapons

- Editing the motion of an NPC's weapon bone works today: it is a body clip track, such as `c1010`'s `Spear`.
- A new moving bone, such as a gun's hammer added under `Spear`, needs a new skeleton bone. A new mode of **Write model only** appends such bones after the skeleton's last bone. Old clips keep their tracks, since they bind the first bones in order; the new bones hold their rest pose there. The per-bone behavior lists and the ragdoll's skeleton copy grow by the same bones, as `edit_behaviors()` and `edit_ragdoll()` already do for new characters.
- New body clips with tracks for the new bones go into the character's animation binder through **Add to an animation binder**.
- Risk: whether every vanilla clip binds bones in order. Check every clip of the target character before writing.

### 4.4 Weapon motion from other games

- **4.4a Import.** `games.api` lets a weapon part name a clip of its own. The import keys that weapon's bones, which hang below the joint in the character's armature, in the body action. Packages may then set `part_animations` to true. First research step: where Devil May Cry 5 keeps Cavaliere's and King Cerberus's motion, in a weapon motlist or as tracks in Dante's motlists. The Unreal and DOOM Eternal packages get the same check.
- **4.4b Into a new Sekiro character.** Works once 4.4a keys the bones: they join the skeleton and the body clip.
- **4.4c Onto a Sekiro weapon.** The Retarget Assistant bakes the other weapon's bones onto a Sekiro weapon rig by bone pairs chosen in the bone list. 4.1 then writes the clip. This fits only weapons of a similar build.
- **4.4d A new Sekiro weapon.** Write the other game's weapon as a Sekiro part binder with its own model, textures, skeleton and clips. It needs a FLVER and TPF writer for parts and a part skeleton writer, much as the character export has. It gets its own plan.

## 5. Checks

- Unit tests on owned synthetic binders: a part binder with a nested animation binder, a clip added and replaced, the `_l` copy, the name with the model's suffix, `part-verify`.
- `blender_part_animations.py` gains a weapon that holds its rest pose, keyed by hand and exported under a new ID, and a weapon with a clip exported as before, byte for byte.
- Real files: the umbrella's opening keyed for Wolf's idle `a000_000000`; Kusabimaru `wp_a_0300` and its `_l` copy; read back within the body clips' tolerance.
- FromSoftware results stay the same: imports, catalogs and body exports without `writeParts`.

### In-game milestones

| # | Test | Answers |
| --- | --- | --- |
| M1 | An edited existing part clip, `a076_405010_1`, written into the mod folder's `wp_a_0760.partsbnd.dcx` | Do written part binders load, and do edited part clips play? |
| M2 | A new clip for an ID the part had none for, such as the umbrella opening in Wolf's idle, first alone, then with a part TAE entry | Does a part clip play by ID alone, or does it need an entry? |
| M3 | An animation binder added by hand to `wp_a_0700.partsbnd.dcx` | Does the game load an animation binder a weapon did not have? |
| M4 | `c1010` with an appended moving bone and one new body clip | Do old clips keep working with more bones? |

## 6. Risks and open questions

- Part clips written by the bridge have never been tested in the game (M1).
- The game may pick part clips through something besides the ID; vanilla shows no TAE event for it (M2).
- `_l` files: assumed to be the far-away models; both copies are written so that neither plays the old clip. `_m` files are assumed to be for cutscenes and are not written.
- Another mod that changes the same part binder wins over this one or loses to it.
- 4.4c gives odd results between weapons of different builds; the Log should say which bones stayed unpaired.

## 7. Not in this plan

- Part clips for weapons of other FromSoftware games. Their parts pair by the same ID only (`TAE_VERSIONS`).
- Weapon TAE events (sounds, effects, hit boxes on dummy polys), and events 710, 711 and 713, which hide weapons or swap model masks.
- Physics on weapon bones, such as cloth or chains.
