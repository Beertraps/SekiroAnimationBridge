# Exporting new characters into Sekiro

**Status:** implemented for the first goal; not yet tested in the game. Planned on 2026-10-30 against bridge 0.14.2 and Retarget Assistant 0.11.0, and built the same day. Dante from Devil May Cry 5 (DMC5) is the worked example, not a special case: nothing in the code names Dante, DMC5 or `c1010`.

How to use it: [USER_GUIDE.md, New Sekiro character](USER_GUIDE.md#new-sekiro-character). The manifest Blender writes: [INTERCHANGE.md, Character export manifest](INTERCHANGE.md#character-export-manifest). What a game package adds: [PACKAGES.md, Materials](PACKAGES.md#materials). What was checked: [VERIFICATION.md](VERIFICATION.md).

## Summary

- The bridge has a second kind of export: a whole character. From a Blender scene it writes a new Sekiro character ID with its own model, textures, skeleton and clip, and can place it in a map. Sekiro then loads it as a character of its own.
- The first goal is small: Dante as `c1800` stands in place of one Ashina soldier in `m11_00_00_00` and plays his DMC5 idle. No fighting yet.
- The bridge does this alone, from the UI's **Character** page, `bridge_cli character-export` or a request file. It needs neither the sekiro-modding plugin nor an agent.
- The method is **template cloning**. A vanilla character (the template, by default `c1010`) gives the files that the bridge cannot make: behavior, HavokScript, TAE and the NPC parameters. The bridge writes the rest new and changes the values in the copied behavior files that name bones.
- The character keeps its own bones. The new skeleton starts with the template's eight frame bones; every bone number in the behavior is mapped to the new skeleton by bone name.
- Havok files are patched in place by `standalone/havok_tagfile.py`, which keeps every byte the new character does not change. Model, textures and map go through a small .NET tool, `tools/SekiroCharacterWriter`, on SoulsFormats.

## Decisions (user, 2026-10-30)

| Question | Decision |
| --- | --- |
| First in-game test | The character stands in the game and plays an idle. No fighting. |
| ID | A new character ID, not a replaced vanilla one. `c1800` is free: no `c18xx` or `c19xx` exists in `chr/`. |
| Skeleton | The character's own bones. The template's behavior is remapped to them. |
| Placement | The character replaces one or more of the template's enemies in a map, chosen by part name. |
| Tools | The bridge works without the plugin and without an agent. The plugin was a reference only. |
| Template | Free choice. `c1010` is the default. |
| Scope | Dante is a test case. The two parts that are not Sekiro-specific are general: texture roles in the game package API, and finding and remapping bone fields in any behavior file. |

## 1. The template: c1010

`c1010` is an armored soldier with a katana. It is the most placed soldier in the Ashina maps: 43 parts in `m11_00_00_00` alone. Its files (game folder unpacked with UXM):

| File | Members |
| --- | --- |
| `chr/c1010.chrbnd.dcx` | `c1010.flver` (400 bones, 81 meshes, 76 dummy polys); ragdoll `c1010.HKX`, `c1010.hkxpwv`, cloth `c1010_c.hkx` and `c1010_c.clm2` |
| `chr/c1010.texbnd.dcx` | one TPF with 20 textures |
| `chr/c1010.anibnd.dcx` | `skeleton.HKX` (127 bones, types in the compendium); TAE; compendium; 349 clips |
| `chr/c1010.behbnd.dcx` | the project `c1010.hkx`; `Characters\c1010.hkx` (11,912 bytes); `Behaviors\c1010.hkx`; `Behaviors\c9997.hkx` (624,496 bytes, shared by many NPCs) |
| `action/script/c1010.hks` | HavokScript |

Its 94 NpcParam rows (10100000 to 10109900) all have `useRagdoll` 0 and `normalChangeTexChrId` 1019. The first test replaces part `c1010_0000` in `m11_00_00_00` (EntityID 1100200, NpcParam 10100010, think param 10100003).

## 2. What the bridge writes

A mod folder with the game's relative paths, and a me3 profile beside it (`<folder>.me3`, `profileVersion = "v1"`, one package that points at the folder). The game folder is only read; `dcx_codec.protect_output` refuses any path inside it.

| File | Content | Source |
| --- | --- | --- |
| `chr/c1800.chrbnd.dcx` | `c1800.flver` | new, on the template FLVER's layout |
| | ragdoll `c1800.HKX`, `c1800.hkxpwv` | the template's, on the new bones (3.9) |
| `chr/c1800.texbnd.dcx` | `c1800.tpf` | new |
| `chr/c1800.anibnd.dcx` | `skeleton.HKX` | the template's, patched: new bones, parents and rest pose |
| | TAE, compendium | copied |
| | every clip slot (349) | the scene's action, as one spline-compressed clip |
| `chr/c1800.behbnd.dcx` | project, `Characters\c1800.hkx`, `Behaviors\c1800.hkx` | the template's, patched: file names and bone fields |
| | `Behaviors\c9997.hkx` | copied as bytes when nothing in it changes |
| `action/script/c1800.hks` | HavokScript | copied |
| `map/mapstudio/<map>.msb.dcx` | model `c1800` added; the chosen parts set to it | the template's map, edited with SoulsFormats |

Member paths and file names are renamed from `c1010` to `c1800`. The ragdoll and its `.hkxpwv` stay, because their bodies are what attacks hit (3.9); without them, blows go through the character. The cloth is left out: it moves the template's model. No param changes: the parts keep their NpcParam and think rows.

`bridge_cli character-clone` writes the template itself under the new ID, through the same code, as a first in-game test of the renames, the patched Havok files and the map edit.

## 3. Design

### 3.1 Havok tagfiles: `havok_tagfile.py`

Sekiro's behavior and skeleton files are Havok 2016 binary tagfiles (TAG0). The planned route, rewriting them with Havoc, failed: Havoc reads an array of pointers or strings with a stride of 4 bytes, but Sekiro's files use the type's byte size, 8. A Havoc rewrite corrupts them.

`havok_tagfile.py` reads the sections, the types (from the file's own TYPE section or from the compendium that TCRF names), the items (ITEM) and the pointer table (PTCH), and walks every object from the root. It changes values in place. A list that grows, such as a per-bone weight list for more bones, is written as new data at the end of DATA, and its item points there. Pointers inside new data are added to PTCH; PTCH entries inside data that nothing reads any more are dropped. Every byte the new character does not change keeps the template's value. `Tagfile.unpatched()` checks that every pointer, string and list slot is in PTCH and that PTCH lists nothing else, since the game's loader turns only listed slots into addresses.

The section, type and item layout follows Havoc's `HkBinaryTagfileReader` and `HkBinaryTypeReader` (MIT); no code is copied.

### 3.2 Bone fields in a behavior

`havok_tagfile.bone_fields` finds every value that names a bone or holds one entry per bone, by field name and type, in any behavior file:

| Kind | Found by | Example in `c1010` |
| --- | --- | --- |
| `index` | an integer field named like `boneIndex`, `hipIndex`, `kneeIndex`, `ankleIndex`, `shoulderIndex`, `elbowIndex`, `wristIndex`, `animationBoneIndex`; not `ragdoll...` | foot IK legs: hip, knee, ankle 4/1, 5/2, 6/3 (the foot target chains); IK chains: shoulder, elbow, wrist 24/40, 27/43, 31/47 (`L_Thigh`/`R_Thigh`, `L_Calf`/`R_Calf`, `L_Foot`/`R_Foot`); `animationBoneIndex` 6 and 3 |
| `indices` | an integer list named like `boneIndices` | |
| `weights` | a float list named like `...Weights` with one entry per bone | `boneWeights` of the character data, 127 entries |
| `mirror` | `hkbMirroredSkeletonInfo.bonePairMap` | |
| `lodCounts` | `numBonesPerLod` | |
| `property` | a character property or behavior variable of a whole-number type whose name ends in `Start`, `End`, `Bone` or `BoneIndex` | `RefTwistNeckStart` 88 (`Neck`), `RefTwistNeckEnd` 89 (`Head`), `RefTwistSpineStart` 7 (`Root`), `RefTwistSpineEnd` 59 (`Spine2`) |

`Behaviors\c9997.hkx` holds only 0 and 1 (in `TwistParam`, `keyframedBonesList` and a `boneIndex`), which the frame bones keep, so it is copied unchanged.

`edit_behavior` maps each number from the template's bone to the new skeleton's bone of the same name; a template bone without a partner takes its nearest partnered ancestor. A per-bone list gets one entry per new bone: a paired bone takes its template bone's value, another bone its parent's. Then the strings that name the template are renamed (same length, in place).

### 3.3 Skeleton

In `c1010`'s skeleton, bones 0 to 7 are `Master`, the six foot target bones (`L_Foot_Target2`, `L_Foot_Target1`, `L_Foot_Target`, and the same for R) and `Root`. The new skeleton keeps them with the same names and parents. The scene's bones follow from index 8, the top ones under `Root`. For Dante: 8 + 458 = 466 bones.

`Root` rests at the hips, turned as the template's. Each foot target chain rests on its leg (`L_Foot_Target2` on `L_Thigh`, `L_Foot_Target1` on `L_Calf`, `L_Foot_Target` on `L_Foot`), as `c1010`'s does. In every clip frame, each chain stands on its foot.

`write_skeleton` gives the template's `hkaSkeleton` new bone names (new string items), parents and rest pose, and renames the skeleton from `c1010` to `c1800`. It refuses a template skeleton with partitions or local frames.

### 3.4 Bone pairs

The Retarget Assistant's matcher (`blender_addon/sekiro_retarget/mapping.py`) pairs the template's body bones with the scene's by name, side and rest position, without Blender. When the scene's rig records its game, the bone names of that game's package (`bones` in `package.json`) are read too, as in the add-on. Paired bones take the template's names (`Pelvis`, `L_Thigh`, `Head`), in case the game finds bones by name; the others keep their own, with `_` added where a name is taken. The export stops when the pelvis, a thigh, a calf or a foot has no partner. `--pair TEMPLATE=SOURCE` names a partner; `TEMPLATE=` removes one.

### 3.5 Model

The writer starts from the template FLVER with SoulsFormats `FLVER2`. It keeps the header, the vertex buffer layout and the GX lists of a `c1010` material, and replaces bones, meshes, materials and dummy polys.

- Nodes: `Master`, `Root`, the scene's bones (weighted ones and their ancestors first), the template's dummy poly holders, one node per mesh.
- A vertex names its bones with one byte, so a model skins with 256 nodes at most. Until the weighted bones and their ancestors fit in 254, the lightest bone that holds no other needed bone gives its weights to its parent (`reduce_weighted_bones`). Dante: 150 face bones merged, 218 weighted nodes.
- Vertices: position, normal, tangent, four bone indices and weights, two UV sets, converted from Blender to the FromSoftware space.
- Bounding boxes for the model, each mesh and each bone. The full mesh is written into each face-set variant of the template.
- Dummy polys: the template's 76, moved to the new bones by name. A dummy on a template bone the model lacks follows the nearest ancestor it has.
- A material whose shader alpha is 0 and has no opacity image is left out, since the game would draw it opaque. Dante: `m_eyewet` and `m_eyeouter`.
- Weapons: a game package's weapon hangs on a joint of the rig (`attachment` `{"kind": "joint"}`), its bones below the joint and its mesh skinned to the rig. The export writes it like any other mesh, so it is part of the model and moves with its joint, as the weapons of Sekiro's own enemies do. Dante with Rebellion on `WeaponConst` and Ebony and Ivory in his hands: 20 meshes, 200,862 triangles, 3 weapons' 29,090 of them; 481 bones.

### 3.6 Materials and textures

Each material uses a generic MTD and names its textures in the FLVER: `C[AMSN]_Decal.mtd`, or `C[AMSN]_e_Decal.mtd` with an opacity image.

| Role | Sekiro texture | Format |
| --- | --- | --- |
| albedo, with opacity in alpha | `c1800_<material>_a` | BC7 sRGB (TPF format 102) |
| normal | `c1800_<material>_n` | BC7 (106); blue and alpha filled as `c1010`'s `_n` |
| metalness | `c1800_<material>_m` | BC4 (103) |

A material without an albedo image gets a 4×4 `_a` in its shader color. Images are read with `texconv -srgb` and compressed with `texconv`, which comes with Soulstruct in the conversion Python. The longest side is 2048 pixels by default (`--texture-size`).

The roles come from the Blender material: `bridge_texture_roles`, which the import stores from the character manifest's `packed`, `metalness` and `roughness` fields, else the node tree. DMC5's ALBM albedo holds metalness in alpha, and NRMR holds roughness in alpha; the RE Engine package says so with `packed`. Roughness is recorded but not written: Sekiro's characters have no texture for it.

### 3.7 Clip

The scene's action is sampled in Blender at every frame (`motion.npz`), converted to the FromSoftware space with the frame bones filled, and written by the existing animation writer as a spline-compressed clip into every clip slot of the template's anibnd. Every slot gets a clip, because the TAE lists them all and a missing clip can freeze or crash the character. Later versions map other clips to slots.

### 3.8 Map

SoulsFormats `MSBS` reads the template's map. The writer adds the model `c1800` and points the chosen parts at it. The map is read from the game folder and written only into the mod folder.

### 3.9 Ragdoll: the hit bodies

Attacks hit the bodies of the chrbnd's ragdoll, `c1010.HKX`: 19 `hknpCapsuleShape` bodies, one per bone of the ragdoll skeleton `Ragdoll_Ctrl_Pelvis`. The file also holds a copy of the animation skeleton (`Master`, 127 bones, equal to the anibnd's `skeleton.HKX`) and two skeleton mappers: one moves the ragdoll bones with the animation bones, the other the reverse. Each mapping's `aFromBTransform` is the inverse of bone A's rest times bone B's rest, and each body rests where its ragdoll bone rests.

The export (`edit_ragdoll`) puts the new skeleton in the copy and gives the mappers the new bone numbers. Each ragdoll bone moves to the new bone that its driver is paired with, and turns as the limb turns from the template's rest to the new one; the limb is the direction to the ragdoll child nearest the middle, such as `Spine` for the pelvis. Bones without ragdoll children, such as the hands and the head, turn as their parent. The mapper transforms and bodies follow from the new rests. The capsules keep the template's sizes. `edit_pwv` gives the `.hkxpwv` one 8-byte row per new bone, copied from the template bone the new bone takes its weights from. With `c1010`'s own skeleton, `edit_ragdoll` gives back all of `c1010.HKX`'s transforms and bodies within 1e-6, and `edit_pwv` the same bytes.

### 3.10 Where the code is

| Area | Files |
| --- | --- |
| Blender side | `standalone/blender_character_export.py`, run by `blender_bridge.py export-character`: the export manifest |
| Orchestration | `standalone/character_export.py`: bone pairs, skeleton, behavior edits, model nodes, textures, clip, binders, map, profile and `verify` |
| Havok files | `standalone/havok_tagfile.py` |
| .NET writer | `tools/SekiroCharacterWriter/`: `inspect` (FLVER, TPF, map parts), `flver`, `tpf`, `msb`. One JSON job in, one JSON report out. `build_decoder.cmd` publishes it next to the decoder, which shares its runtime and SoulsAssetPipeline. |
| Requests | `bridge_runtime.character()`: `character-export`, `character-clone`, `character-verify`, `character-parts` |
| CLI | `bridge_cli character-parts`, `character-export`, `character-clone`, `character-verify` |
| UI | the **Character** page (`ui/index.html`, `ui/app.js`); `bridge_ui.py` maps its fields to the request |
| Interchange | `standalone/schemas/character_export.schema.json`; the character manifest's image `packed` and material `metalness` and `roughness` |

## 4. Checks

`character-verify` reads a written mod folder back and runs 12 checks: the four binders are there; member paths name the new ID; the skeleton starts with `Master`; every per-bone list of the behavior has one entry per bone; every pointer, string and list slot is in its PTCH table; every bone number names a bone of the skeleton; no file name names the template; the ragdoll holds a copy of the skeleton, its mappers name bones in range, its PTCH table lists every slot and its `.hkxpwv` counts the skeleton's bones; every model bone is in the skeleton; every material's texture path resolves in the TPF; the clip count equals the template's; the map's chosen parts use the new ID. `character-export` and `character-clone` run it at the end.

Automated tests use owned synthetic data only: `standalone/tests/test_character_export.py` (tagfiles built in the test, bone merging, bone pairs with a package's names, triangle winding, ragdoll rests, `.hkxpwv` rows, the UI's request) and `blender_character_export.py` (the manifest of a synthetic scene).

## 5. Steps

| Step | Status |
| --- | --- |
| Facts: tagfile round trip, map edit, `c1010`'s FLVER, textures, weight list and script | done |
| Writer, clone (`c1800` as `c1010`) | done; `character-verify` passes 11 of 11 |
| **M0 in game (user):** the cloned soldier at `c1010_0000` looks and moves like every other `c1010` | open |
| Export manifest, bone pairs, skeleton, behavior edits, model, textures, clip | done |
| Import-back check: the written `c1800` imported into Blender passes `verify` | done |
| **M1 in game (user):** Dante stands where `c1010_0000` stood, plays his idle, has his textures, and the game neither crashes nor freezes | open |
| CLI, UI, docs | done |

## 6. Risks and open questions

| # | Risk | What happens if it hits | Plan |
| --- | --- | --- | --- |
| R1 | The game rejects a patched tagfile. | Crash or a frozen character. | Unlikely for the clone, whose behavior files differ from `c1010`'s only in the ID. M0 tests it; then M1 tests the grown lists. |
| R3 | `normalChangeTexChrId` 1019 makes the game load `c1019.texbnd.dcx` for `c1800`. | Wrong or missing textures. | M1 shows it. Fallback: a NpcParam copy with -1, or a template whose rows have -1, such as `c1100`. |
| R4 | The game finds bones by name. | Head turn or attachments wrong. | Paired bones take the template's names. |
| R5 | FLVER details are wrong: bounding boxes, face-set flags, vertex layout. | The character vanishes at some angles or its skin tears. | The template FLVER's layout, the import-back check, M1. |
| R6 | Foot IK expects something other than the foot target chains on the legs. | Feet slide or snap. | M1. |
| R8 | Another mod also changes the map. | One mod's map wins. | The report names the map file it writes. |
| R9 | The character's size differs from the template's hit capsule (`c1010`: height 1.7, radius 0.4). | Collision slightly off. | Fine for an idle. |
| R10 | 256 skinned bones at most. | Small bones lose their own motion. | Their weights go to their parents; the export lists them. |
| R11 | The ragdoll's capsules keep the template's sizes. | A much bigger or smaller character is hit where the template's limbs would be. | Fine for Dante (1.94 m against `c1010`'s 1.7 m). A ragdoll bone whose driver has no partner rests on the nearest paired parent; the export names it. |

The Blender preview of FromSoftware imports reads sRGB textures as linear, so the imported `c1800` looks darker in Blender than in the game. This is older than the character export and does not change what it writes.

## 7. Not in the first version

- Fighting: other clips in the TAE's attack slots, hit boxes on dummy polys, BehaviorParam and AtkParam rows.
- Ragdoll physics (the ragdoll's bodies are kept as hit bodies; `useRagdoll` stays 0), cloth, sounds and effects.
- New NpcParam and NpcThinkParam rows, new placements.
- Modifiers: the export reads each mesh's own data; apply a modifier in Blender first.
- Replacing the player character.
