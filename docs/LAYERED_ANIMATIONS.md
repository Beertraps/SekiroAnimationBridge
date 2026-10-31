# Layered animations in Sekiro

How the game plays a second animation on top of the one that runs: hit flinches, guard bounces, prosthetic use while
walking, faces. Read from the game files on 2026-10-31, unless marked *inferred*. Only the bone weight rules were tested
in the game (see Bone weights, tested in the game).

Files read: `chr/c0000.behbnd.dcx` (player), `chr/c5400.behbnd.dcx` (Sword Saint Isshin; NpcParam `54000000` names
him), its `Behaviors\c9997.hkx` (the behavior that many NPCs share), the animation binders `chr/c5400.anibnd.dcx`,
`chr/c0000.anibnd.dcx`, `c0000_a000_hi`, `_md`, `_lo`, `c0000_a00x`, `_a05x`, `_a07x`, `_a2xx`, and `c1010.anibnd.dcx`
for TAE, and `action/script/c0000*.hks`, `c9997.hks`, `c5400.hks`.

## Summary

- The layering is in the behavior (hkb). The HKS sets layer weights and sends the events that start a layer's clip.
- The behavior layers clips in three ways:
  1. **Additive clips**: real Havok additive clips (`blendHint` 1), added on top of the running pose. Used for flinches,
     guard bounces and prosthetic recoil.
  2. **Bone-masked layers**: normal clips that replace the pose on some bones only. Used for faces, speech, fingers
     and the player's upper body while walking.
  3. **Motion and pose apart**: one layer gives only the root motion, another gives only the pose.
- The additive and bone-masked layers have `worldFromModelWeight` 0 or `useMotion` false, so they never move the
  character. Root motion comes from the main animation, or from a motion-only layer (way 3).

## Additive clips in the binders

All additive clips have `blendHint` 1 (`ADDITIVE_DEPRECATED`, parent space in SoulsAssetPipeline's names). None has 2.

- **Isshin** (`c5400.anibnd.dcx`): 9 of 276 clips. `a000_009200`, `a100_009200` (fire), `a000_009500`, `a100_009500`
  (flinch under super armor), `a000_009700`, `a100_009700`, `a100_009701` (guard bound), `a000_009999` (1 frame,
  0.033 s, the "no layer" clip), `a000_040000` (7.0 s loop). His full-body damage clip `a000_008020` is normal.
- **Player**: 15 clips. `a000_100000` to `a000_100003`, `a000_102000`, `a000_103000` (hit flinches), `a000_191100`
  (fire), `a000_219000`, `a000_299000` (0.167 s, the "no layer" clip), `a000_299020`, `a000_299300`, `a000_412090`,
  `a050_120000` (deflect), `a070_412010`, `a076_405200` (prosthetic).
- Additive clips hold as many tracks as normal clips: 199 for Isshin, 110 to 114 for the player. They are whole-body
  changes, not partial clips.

## NPCs: `c9997.hkx`

The NPC behavior mixes the main animation with additive layers in one blender, `Master_Blend` (`hkbBlenderGenerator`,
flags 0). It sits in the base layer of `LipSync_LG`, an `hkbLayerGenerator` whose second layer is lip sync.

| Child of `Master_Blend` | Weight variable | Clips |
| --- | --- | --- |
| `Master_Script` (`hkbScriptGenerator`) | none; weight 1, `worldFromModelWeight` 1 | 330 animations |
| `PartBlend01_SM` to `PartBlend16_SM` | `BlendPart01` to `BlendPart16` | `a000_009999` only |
| `SABlend_SM` | `BlendSA` | `a000_009500` to `a000_009503` (front, back, left, right), `a000_009999` |
| `AttackGuardBound_SM` | `AttackGuardBoundBlend` | `a000_009700`, `a100_009700`, `a000_009999` |
| `AttackJustGuardBound_SM` | `AttackJustGuardBoundBlend` | `a000_009600`, `a100_009600`, `a000_009999` |
| `AddBlend00` (`hkbManualSelectorGenerator`) | `AddBlend00`; index `IndexAddBlend00` | `a000_040000` |
| `Slope Blend` | `SlopeBlendWeight` | `a000_009999` |

Fire damage sits deeper, in `DamageBlend Blend`: `DamageFireBlend_SM` (`BlendDamageFire`, `a000_009200`) and
`DamageDirBlend_SM` (`BlendDamageDir`) over `DamageBase_SM`, which plays the normal damage clips such as `a000_008020`.

No child has bone weights. Every child except `Master_Script` has `worldFromModelWeight` 0.

**A flinch, step by step** (`c9997.hks`): one branch of the damage code picks the hit direction, sets
`BlendSA` to 0.5 and fires `W_SABlend_Add_Front`, `_Back`, `_Left` or `_Right`. It first checks
`IsExistAnime(ANIME_ID_ADD_BLEND_FRONT + offset)`, so a character without that clip gets the front one. The event moves
`SABlend_SM` from state 0 `SABlend_NoAdd` (`a000_009999`) to the flinch state. `Master_Script` keeps playing, so the
attack goes on with the flinch added at half weight.

**TAE `601 SetAdditiveAnim`**: Isshin's TAE has one, on `a000_400000` from 0 to 10.033 s; c1010's has five, such as
`a000_000000` and `a000_021000`. All have `AnimType` 0 and weight 1 to 1. The player's TAEs have none. No HKS sets
`AddBlend00` or `IndexAddBlend00`. *Inferred*: the engine sets them from event 601, `AnimType` choosing the index, so
601 plays `a000_040000` as an idle layer.

## Player: `c0000.hkx`

The player's top node is `Master LayerGenerator` (`hkbLayerGenerator`) under `Master_Script`. Its layers, in file
order (two add layers come before the main one):

| Layer | Weight variable | Bone weights in the file | Clips |
| --- | --- | --- | --- |
| `AddActionInput_SM` | `AddActionInputBlend` | 146 entries, all 0 | `a000_299000`, `a000_299020` and others |
| `AddDeflectGuard_SM` | `AddDeflectGuardBlend` | 146, all 0 | `a000_299000`, `a000_299060` |
| `Master Blend` (`useMotion` true) | none | none | the 2,254 main animations |
| `AddDamageFire_SM` | `AddDamageFireBlend` | 146, all 0.6 | `a000_191100`, `a000_299000` |
| `AddDamage_SM` | `AddDamageBlend` | 112, all 0.6 | 16 states, such as `AirDamageMinimumAdd` (`a000_102000`) |
| `AddAction_SM` | `AddActionBlend` | 113, all 0.1 | `a000_219000`, `a000_219100`, `a000_299000` |
| `AddSubWeaponChange_SM` | `AddSubWeaponChangeBlend` | 146, all 0 | `a000_412090` |
| `AddSubWeapon_SM` | `AddSubWeaponBlend` | 113, all 0.1 | `a070_412010` and others |
| `AddBlendFace_SM` | `AddBlendFace00` | 146; 1 on bones 81 to 112 (face) | normal clips `a000_790000` to `a000_790110` |
| `AddBlendFingerRight_SM` | none; on and off by events | 146; 1 on 16 bones from 120 (`R_Hand`) | `a000_299200` |
| `AddBlendSpeak_SM` | `AddBlendSpeakIndex` picks the clip | 146; 1 on bones 81 to 112 | normal clips `a000_790500` to `a000_790520` |
| `AddNonCombat_SM` | `AddNonCombatBlend` | 146, all 0 | `a000_299000`, `a000_299400`, `a000_299401` |

Only `Master Blend` has `useMotion` true.

**A flinch, step by step** (`c0000_transition.hks`): for a small hit in the air, the script sets `AddDamageBlend` to 1 and
calls `FireEventNoReset("W_AirDamageMinimumAdd")`. The event moves `AddDamage_SM` to state 10, which plays the additive
`a000_102000`. `NoReset` leaves the main state machine running.

**The prosthetic layer**: `next_add_behavior` with `BEH_ADD_R_SUB_WEAPON_EXPAND` sets `AddSubWeaponBlend` to 1.

**Upper body while walking**: states such as `StandMoveOverwrite` and `CrouchMoveOverwrite` hold an `hkbLayerGenerator`
with two layers:

- `StandMoveLower_SM`, `useMotion` true, no bone weights: 20 walk and run clips, such as `a000_000100`.
- `StandMoveUpper_SM`, `useMotion` false, bone weights of 39 entries, all 0: 83 clips in 24 states, none additive. Examples:
  `ItemGourdDrinkMove` (`a000_250000`), `SubWeaponExpandMove` (`a070_412001` and others),
  `GroundSubAttackLockOnMove` (`a079_400600`), `GroundSubAttackHoldMove` (`a072_400300`).

Bones 0 to 38 of the player skeleton are `Master`, the foot targets, `RootPos`, `Pelvis`, both legs and the leg weapon
cases. Bone 39 is `Sheath`, 42 is `Spine`. So the 39 entries cover exactly the lower body. The upper clips track the
legs too (112 tracks; they lack only `Sheath` and `LargeSheath`), so the mask is not in the clips.

**Motion and pose apart**: 19 move states, such as `StandMoveLoop`, `DeflectGuardMove` and
`GroundSpecialAttackHoldMove`, hold an `hkbLayerGenerator` with a `_MotionSelector` (`useMotion` true, 146 bone
weights, all 0) and an `_AnimeSelector` (`useMotion` false, no bone weights). Both select from the same clips, such as
`a000_000200` to `a000_000203`. *Inferred*: the character moves by one clip's root motion and shows another clip's
pose, such as the run direction against the facing direction.

## Bone weights, tested in the game

Tested by the user on 2026-10-31 with three mods. Each is the game's `chr/c0000.behbnd.dcx` with `Behaviors\c0000.hkx`
patched in place with `havok_tagfile`, as the character export patches behaviors. Only the bone weights of
`StandMoveUpper_SM` and `CrouchMoveUpper_SM` change. Readback: the patch table covers every slot, the two layers hold
the new weights, every other layer keeps its own, and `havok_xml` reads the whole file. All three loaded. Test: walk,
then drink from the Healing Gourd while walking.

| Mod | Change | Result in the game |
| --- | --- | --- |
| `bonetest_1_legs_one` | the 39 entries set to 1; 156 bytes differ | the legs slide: the drinking clip takes the legs too |
| `bonetest_2_all_zero` | both layers point at `AddActionInput_SM`'s array, 146 zeros; 4 bytes differ | no drinking motion |
| `bonetest_3_full_list` | the arrays grow to 39 entries 0, then 107 entries 1 | as in the game |

The rules that follow:

- A layer's bone weights are used per bone. 1 takes the layer's pose, 0 keeps the pose of the layers below.
- Bones past the end of a short array count as 1. So a 39-entry array of zeros masks exactly the lower body, as the
  Souls Modding wiki says for Dark Souls III.
- An array of zeros on every bone shows none of the layer's pose.

What they mean for the game's own layers (*inferred* from these rules):

- `AddDamage_SM` (112 entries of 0.6) adds a flinch at 0.6 on the body and at full weight from bone 112 on, which
  includes the sword arm. `AddDamageFire_SM` (146 entries of 0.6) adds at 0.6 everywhere.
- `AddAction_SM` and `AddSubWeapon_SM` (113 entries of 0.1) add at 0.1 on the body and at full weight on the right arm
  from `R_Clavicle` (bone 113).
- The motion selectors (146 zeros, `useMotion` true) give only root motion, as way 3 says.
- `AddActionInput_SM`, `AddDeflectGuard_SM`, `AddSubWeaponChange_SM` and `AddNonCombat_SM` (146 zeros) show no pose.
  Their CMSGs have `enableTae` true, so they may exist to run their clips' TAE events, unless the engine fills their
  weights at run time.

Test notes:

- Close the game and wait until me3 has let go of it before starting the next profile. On the first try,
  `bonetest_2_all_zero` looked like the game because the previous profile was still loaded.
- **The first test set crashed.** It rebuilt the whole behavior with `havok_xml.to_hkx`. Its control, with nothing
  changed, crashed the game on load. The binder and DCX headers and the other two members matched the game's; the
  rebuilt tagfile had a larger DATA section (2,586,936 to 2,591,272 bytes) and type hash table, `THSH` (468 to 500).
  In-place patches load: the Dante export's behavior and the three mods above. `export --register-slot` rebuilds
  behaviors with `to_hkx` too, so its output probably crashes as well.

## Open questions

- **How the blender adds an additive child.** `Master_Blend` has flags 0 and no bone weights, so the additive clips
  are told apart only by their `blendHint`. *Inferred* from Havok: the blender adds additive children on top of the
  normal ones instead of averaging them.
- **TAE 601.** The link from `AnimType` to `IndexAddBlend00` is inferred from names and from no HKS setting it.

## Other sources

- **Souls Modding wiki, [Havok Behavior Editing](https://soulsmodding.wikidot.com/topics:havok-behavior-editing)**,
  for Dark Souls III. Its HalfBlend section:
  - `HalfBlend_SM` holds `Lower_SM` and `Upper_SM`, blended by the `hkbBlenderGenerator` `HalfBlend_Blend`. The two
    children have weight 1 and complementary bone weights: the upper array lists 39 bones at 0, the lower lists 39 at
    1 and the rest at 0. The page concludes that bones an array leaves out get weight 1.
  - HKS starts both halves with `ExecEventHalfBlend`: it fires `W_<name>` for the lower half and `W_<name>_Upper` for
    the upper half, and sets `LowerDefaultState0N` and `UpperDefaultState0N` to the state IDs on the way down.
  - Directional blends bind `blendParameter` of a blender to a variable such as `RollingAngleReal`. The children's
    weights (-180 to 180) are the angles they stand for.
  - When clips are blended, a variable bound to each CMSG's `enableTae` keeps only one clip's TAE events running.
    Otherwise sounds and effects play twice.
- **Sekiro, checked against the wiki's `enableTae` rule.** The CMSGs that own the action have `enableScript` and
  `enableTae` true; the copies have both false. `StandMoveUpper_SM`: 29 of 29 true. `StandMoveLower_SM`: 16 true, 16
  false. `StandMoveLoop_MotionSelector`: 8 false; `StandMoveLoop_AnimeSelector`: 8 true. Every add layer, player and
  NPC: true. *Inferred*: a clip on a layer runs its own TAE, so a firing clip on an upper layer can carry the
  `BulletBehavior` event.
- **[HKS for Fun and Profit](https://docs.google.com/document/d/1YKhG1Yg0LykGeWRZ7QRWNdYfqHqQEF6TzWvvL0qHjn0)**, a
  Google document on HKS for Elden Ring, Sekiro and DS3.
  - The game compiles plain-text HKS itself, so decompiled and edited scripts load with a mod engine.
  - `c9997.hks` applies to enemies in general, a character's own script to that character, and in Elden Ring
    `modifier.hks` after `c9997.hks`. Sekiro has `action/script/modifier.hks` and `cxxxx.hks` too.
  - Elden Ring scales a jump's movement from HKS: `Act_Jump()` calls `act(SetMovementScaleMult, multiplier)`. That is
    a root motion scale set by script. Its act number in Sekiro is not known.

## What this means for a new layer on an NPC

- Isshin's own behavior (`Behaviors\c5400.hkx`, 18 objects) adds no layer; his layers are the shared ones in
  `c9997.hkx`. His binder holds its own copy of `c9997.hkx`, so editing it there changes no other character.
- A new layer is a new child of `Master_Blend` (additive clips) or a new `hkbLayerGenerator` (bone-masked clips, as the
  player's `StandMoveOverwrite`), a new weight variable, and a state machine whose states start on events. HKS sets the
  weight and fires the event, as `c9997.hks` does for `BlendSA`.
- A bone mask lists 0 for the bones that keep the main pose and stops where the layer should take over: bones past the
  end count as 1. The bone numbers follow the character's own skeleton; Isshin's bone order was not compared with the
  player's, so check it before reusing the player's 39-bone mask.
- A layer cannot move the character. Movement stays with the clip that `Master_Script` plays.
- The bridge imports and exports neither additive clips nor bone-masked layers yet. Its decoder rejects `blendHint` 1
  and 2 (`tools/SekiroMotionDecoder/Program.cs`).

## How it was read

- Behavior binders: unpacked with `binder_members.Binder` and `dcx_codec.unwrap`, converted with `havok_xml.to_xml`.
  Variable bindings followed from each node's `variableBindingSet` to `hkbBehaviorGraphStringData.variableNames`.
- Animation clips: `blendHint`, track counts and durations read with `havok_tagfile.Tagfile` and the binder's
  `.compendium`. Tracked bones compared with `havok_tagfile.track_bones` and `skeleton`.
- TAE: events of type 601 read with `part_animations.tae_entries`, parameters as `<iffi` at the event's parameter offset.
- HKS: the decompiled sources in the sekiro-modding plugin index, searched for `SetVariable` names and their callers.
