# Sekiro Retarget Assistant 0.2.0

An optional Blender add-on that matches the bones of two rigs, bakes the motion of one onto the other, and writes the result as HKX through the Animation Bridge installed on the same computer. The bridge's own import and export need no add-on.

## Install

In Blender 4.5, open Edit > Preferences > Add-ons, use the dropdown menu > Install from Disk, choose `SekiroRetargetAssistant-0.2.0.zip`, and enable **Sekiro Retarget Assistant**. If version 0.1.0 is installed, remove it first, or restart Blender after installing over it. The tools are in the 3D Viewport sidebar: press N and open **Retarget**.

The add-on needs no external Python libraries, account or network connection. To export HKX from Blender it uses the Animation Bridge on this computer and finds it by itself: the bridge records its folder each time its UI or CLI runs, and the conversion Python comes from the bridge's settings. The add-on preferences show what was found and can override both paths. This version was exercised in Blender 4.5.14; other Blender versions have not been run.

## Workflow

1. Open the bridge `.blend` of the receiving character, the target.
2. In section 1, set **Target (receiving)** to its armature; the eyedropper uses the active armature. Click **Append source .blend** and choose the donor animation scene. The add-on brings in its rig, meshes, action, root-motion object and embedded HKX metadata. Two rigs already in the scene can be chosen directly instead.
3. In section 2, click **Match bones automatically** and review the list. **Show unmatched / uncertain only** hides confident rows. Assign a source bone through a row's search field, use a suggestion, or **Accept all suggestions**. **Mirror L → R** and **Mirror R → L** copy corrections to the other side. Disable rows you do not want. **Save map** and **Load map** reuse a reviewed list.
4. In section 3, choose the bake options (see below) and click **Bake motion onto target**. The bake creates a new action and keeps the original one. Bake again at any time with other options or a corrected map: each bake starts from the original clip, not from the previous result.
5. In section 4, choose an output `.hkx` and click **Export HKX**. Export runs in the background; the status box shows progress and the result, and Esc cancels. The bridge writes the HKX with a `.motion.json` sidecar beside it. Pack the HKX into the game's animation binder with a binder tool such as WitchyBND.

To export with the bridge UI or CLI instead, click **Use target in the bridge UI**, save the `.blend`, and export that scene as usual.

## Matching

Bone names do not have to match. The matcher uses three kinds of evidence:

- **Names.** Namespaces and prefixes (`mixamorig:`, `CC_Base_`, `Bip01`, `DEF-`, `J_Bip_`), separators and left/right conventions are normalized, and common aliases are recognized: upper arm/arm, forearm/lower arm, thigh/upper leg, calf/shin, pelvis/hips and root-position names.
- **Anatomy.** The hierarchy and rest positions of each rig identify the hips, spine, neck, head, arms, legs, hands, feet and fingers, also in rigs with meaningless names such as `Bone_017`. Chains of different length are matched end to end, so a three-bone spine maps onto a two-bone spine chest to chest.
- **Position.** Left and right come from the rest position when the names do not tell them.

Helper bones (twist, weapon, cloth and similar) are matched by name only, and only below matched parents. A source bone is used at most once. Uncertain matches stay suggestions until you accept them. Percentages describe match strength, not measured probabilities.

On synthetic test rigs of 15 conventions (Mixamo, Unreal, 3ds Max Biped, VRoid, Character Creator, Rigify, Daz, two FromSoftware styles, and six rigs with scrambled bone names), every core body bone matched in every pairing.

## Bake options

- **Rest stance.** *Match source stance* first poses the target limbs to point like the source rest pose, so an A-pose target follows a T-pose source without lowered or raised arms. *Keep target stance* applies the rotations from the target's own rest pose.
- **Root motion.** *Automatic* copies the source root motion when the source has a root-motion object. Without one, body travel becomes root motion when the body moves farther than 30% of its leg length (the status says so), and otherwise none is written. The other choices force one source: *From source root*, *From body travel* (optionally turning with the body), *Keep target root* (same clip length only), or *None*.
- **Unmapped bones.** *Keep target animation* keeps the original clip's motion for cloth, face, weapon and other unmapped bones. *Rest pose* holds them at rest; for bridge rigs, rest is the HKX reference pose.
- **Clip timing.** *Use source length* gives the clip the source's duration. *Fit target length* resamples the source over the target clip's length.
- **Move body with source hips** and **Scale travel by leg length** control body travel; see below.

## How the bake works

Each mapped bone takes its source bone's world-space rotation change from the source rest pose. The target keeps its own bone lengths and proportions.

Body travel goes to the bone above both the hips and the spine: Root in Dark Souls III and Sekiro enemies, RootPos in Sekiro, Dark Souls III and Elden Ring player rigs, and Master in Dark Souls (DS1) player rigs. Legs and upper body therefore move together. Unmapped bones between that bone and the hips or spine follow it rigidly; bones above it hold their rest pose. Travel is scaled by the ratio of hip heights above the feet, or by a manual scale.

The new action keys the mapped bones, the bones that carry the body and the target clip's tracks. It keys any other bone only if it moved by more than 0.01 mm or 0.001 degrees. A mapped bone without a track in the target clip gets a warning: export with **Original tracks + keyed bones** to include it.

## Export

**Export HKX** follows the same path as the bridge's export page. Blender samples the evaluated pose with the bridge's own exporter, so constraints, drivers and NLA tracks are baked. The bridge's conversion Python then writes the HKX with its Havok compatibility fixes and, with **Read back and compare**, decodes it again and reports the largest difference.

- **Game.** *Stored in scene* uses the game recorded at import (bridge 0.5 and later). Older scenes need the game chosen here.
- **Format.** *Interleaved* stores every frame exactly. *Spline* compresses like the game's own clips, within the position **Tolerance** and with the chosen rotation precision.
- **Tracks.** *Original clip tracks* keeps the track list of the clip the target was imported from; *Original tracks + keyed bones* adds bones keyed in the action; *Every skeleton bone* writes all of them.
- **Frames.** The scene range (set by the bake), the action's key range, or the clip's frame count.
- **Root motion.** *As baked* writes the target's root-motion object; *None* writes no root motion.

## Current scope

This add-on transfers humanoid FK animation. It does not solve foot contacts, hand-to-weapon alignment, IK poles, cloth or facial animation. Different proportions can still need pose cleanup. Non-humanoid rigs need manual mapping and review.

Mapped target bones must have no active constraints, and target NLA tracks must be muted. The add-on adds no live constraints or handlers. Source timing can change the clip's duration; TAE events are not retimed. In-game playback of a retargeted clip has not been verified.
