# Sekiro Retarget Assistant 0.4.0

An optional Blender add-on that matches the bones of two rigs, bakes the motion of one onto the other, and writes the result as HKX through the Animation Bridge installed on the same computer. It also gives an imported rig a [control rig](#control-rig) for animating by hand. The bridge's own import and export need no add-on.

## Install

In Blender 4.5, open Edit > Preferences > Add-ons, use the dropdown menu > Install from Disk, choose `SekiroRetargetAssistant-0.4.0.zip`, and enable **Sekiro Retarget Assistant**. If an older version is installed, remove it first, or restart Blender after installing over it. The tools are in the 3D Viewport sidebar: press N and open **Retarget**.

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

Helper bones (twist, cloth and similar) are matched by name only, and only below matched parents. A weapon bone in a matched hand, such as Sekiro's `R_Weapon` dummy, takes the weapon bone in the source's matching hand, such as an enemy's `R_Katana`. Weapons that the source clip hides by shrinking them to almost nothing do not count, so Isshin's gun and spear stay out; of several that remain, the hand's own child wins. Bones that store a weapon on the body, such as `Katana_Saya_Storage`, are not weapons in the hand. A source bone is used at most once. Uncertain matches stay suggestions until you accept them. Percentages describe match strength, not measured probabilities.

On synthetic test rigs of 15 conventions (Mixamo, Unreal, 3ds Max Biped, VRoid, Character Creator, Rigify, Daz, two FromSoftware styles, and six rigs with scrambled bone names), every core body bone matched in every pairing.

## Bake options

- **Rest stance.** *Match source stance* first poses the target limbs to point like the source rest pose, so an A-pose target follows a T-pose source without lowered or raised arms. *Keep target stance* applies the rotations from the target's own rest pose.
- **Root motion.** *Automatic* copies the source root motion when the source has a root-motion object. Without one, body travel becomes root motion when the body moves farther than 30% of its leg length (the status says so), and otherwise none is written. The other choices force one source: *From source root*, *From body travel* (optionally turning with the body), *Keep target root* (same clip length only), or *None*.
- **Unmapped bones.** *Keep target animation* keeps the original clip's motion for cloth, face, weapon and other unmapped bones. *Rest pose* holds them at rest; for bridge rigs, rest is the HKX reference pose.
- **Clip timing.** *Use source length* gives the clip the source's duration. *Fit target length* resamples the source over the target clip's length.
- **Move body with source hips** and **Scale travel by leg length** control body travel; see below.
- **Keep hands out of the body** (on by default). Where a hand, or what it holds, would go into the target's torso, the hand is moved out through its arm; see below. It needs the target's character mesh in the scene.

## How the bake works

Each mapped bone takes its source bone's world-space rotation change from the source rest pose. The target keeps its own bone lengths and proportions.

Body travel goes to the bone above both the hips and the spine: Root in Dark Souls III and Sekiro enemies, RootPos in Sekiro, Dark Souls III and Elden Ring player rigs, and Master in Dark Souls (DS1) player rigs. Legs and upper body therefore move together. Unmapped bones between that bone and the hips or spine follow it rigidly; bones above it hold their rest pose. Travel is scaled by the ratio of hip heights above the feet, or by a manual scale.

The new action keys the mapped bones, the bones that carry the body and the target clip's tracks. It keys any other bone only if it moved by more than 0.01 mm or 0.001 degrees. A mapped bone without a track in the target clip gets a warning: export with **Original tracks + keyed bones** to include it.

### Weapons

When a mapped weapon bone and its source bone both carry a clearly elongated mesh, the target bone is turned in its own space so that its blade points like the source's. The target's weapon is the mesh on its bridge weapon socket; the source's may also be the vertices its weapon bone deforms most, as with an enemy's katana inside the character mesh. Wolf's `R_Weapon` and Isshin's `R_Katana` differ by 6°; bones authored along other axes can differ by 90°. The status lists each turn.

### Body clearance

The target keeps its own proportions, so a source with a thinner body or longer arms can hold its hands closer to its body than the target's mesh allows. With **Keep hands out of the body**, the bake finds, frame by frame, where the hand meshes, the fingers and what the hands carry come within half an arm of the wrist and inside the torso: the mesh that the hips and spine deform most, without arms, legs, head or cloth bones. It also measures how deep the source's own hands and weapons go into the source's torso, as the distance from their deepest point to the nearest surface, so clipping that the source animation already has, such as a hilt pressed into a sash, stays at the target's size. A source without a body mesh is not compared, and then all clipping is removed. Where the target's hand goes in deeper than the source's, the bake moves it out through a two-bone arm solve that keeps the elbow in its plane and the hand's rotation:

- The push takes out what goes deeper than the source's own hand, scaled by the ratio of arm lengths. Where the source's hand is clear of its body, it goes 2% of the arm's length further; where the source's hand touches its body, the target's ends touching too.
- Each stretch of frames in contact gets one direction, forward, back or sideways in the torso's frame, the one whose largest push is smallest.
- Pushes ease in and out over 0.2 s, so the frames around the contact move too, and every frame still gets at least its own push.
- Hands that come close together within a stretch, as on one hilt, move as one.
- A push longer than about a third of the arm is left out and reported, since that is not a matter of proportions. An arm that would have to be longer than it is stays straight, pointing toward the push.

The status lists the frames each hand moved, the largest push and how much of the source's own clipping a hand keeps. Arms, legs and heads can still pass into each other; the control rig helps with that cleanup.

## Export

**Export HKX** follows the same path as the bridge's export page. Blender samples the evaluated pose with the bridge's own exporter, so constraints, drivers and NLA tracks are baked. The bridge's conversion Python then writes the HKX with its Havok compatibility fixes and, with **Read back and compare**, decodes it again and reports the largest difference.

- **Game.** *Stored in scene* uses the game recorded at import (bridge 0.5 and later). Older scenes need the game chosen here.
- **Format.** *Interleaved* stores every frame exactly. *Spline* compresses like the game's own clips, within the position **Tolerance** and with the chosen rotation precision.
- **Tracks.** *Original clip tracks* keeps the track list of the clip the target was imported from; *Original tracks + keyed bones* adds bones keyed in the action; *Every skeleton bone* writes all of them.
- **Frames.** The scene range (set by the bake), the action's key range, or the clip's frame count.
- **Root motion.** *As baked* writes the target's root-motion object; *None* writes no root motion.

## Control rig

An imported rig has one short bone per game bone, each oriented however the game stores it, which is awkward to animate by hand. The **Control rig** panel, below the retarget panel, adds animator controls to it:

1. Select the armature, or let the panel use the scene's bridge rig, and click **Add control rig**. Mute the armature's NLA tracks first if it has any.
2. The armature switches to Pose Mode and its controls draw in front of the mesh:
   - **Torso**: a root control whose arrow points forward, rings for the hips, spine, neck and head, and rings for the bones above them (such as Master and RootPos).
   - **FK limbs**: a ring on each arm and leg bone, pointing along the limb.
   - **IK limbs**: a box on each hand, a square under each foot, and a diamond pole target behind each elbow and in front of each knee.
   - **Fingers & toes**: small rings.
   - **Extras** (twist, weapon, cloth, face and other helper bones) and **Game bones** start hidden. The toggles under **Show** show or hide each group.
3. The active action is baked onto the controls as a new action, "*clip* Controls", in FK and IK alike, so the pose does not change. The original action is kept.
4. Each arm and leg has an IK slider: 0 follows the FK controls, 1 the IK controls, and you can key it. **Switch to IK** and **Switch to FK** first match the limb's other controls to its current pose, then set the slider, so the limb does not jump. They match at every frame of the scene range, or only at the current frame when *Match every frame* is off in the operator's redo panel.
5. Animate, save and export as usual. **Remove control rig** asks whether to *Keep the edited motion*, which bakes what the controls do onto the game bones as "*clip* Edited", or to *Restore the original action*.

Every game bone copies a hidden socket bone that hangs from its FK control at the game bone's own rest, and an arm or leg blends in a second socket on a two-bone IK chain by its slider. The game bones keep their rest pose, so meshes, weapon sockets and both exporters keep working. On owned test rigs and on copies of Sekiro player and enemy scenes, adding the control rig moved no game bone by more than 0.0001°, and IK placed the elbows, knees, hands and feet within 0.1 mm of the clip.

The bridge's export page, its CLI and **Export HKX** sample the game bones, so they write what the controls do. With a control rig on the armature, **Read actions** lists only the actions that animate the controls, and exporting another action of that armature stops with a message. A keyed control of a bone without a track in the clip counts for *Original tracks + keyed bones*. To retarget onto the armature, remove the control rig first; you can add it again afterwards.

Arms and legs get IK where the matcher finds them; other skeletons get FK controls only. IK bends each elbow and knee around one hinge, so a twist that the clip puts into a forearm itself does not show while that arm is in IK; FK keeps it. Bones that the clip scales unevenly, such as muscle helpers, get controls along their own axes so the scale carries over; on arm and leg bones, that scale holds in FK only. This version has no foot roll, finger IK, face controls or IK stretch.

## Current scope

The retarget bake transfers humanoid FK animation. It aligns held weapons and keeps hands out of the torso, but it does not solve foot contacts, a hand reaching for something other than its own weapon, cloth or facial animation; the control rig's IK limbs help with that cleanup by hand. Different proportions can still need pose cleanup. Non-humanoid rigs need manual mapping and review.

Mapped target bones must have no active constraints, and target NLA tracks must be muted. The bake adds no live constraints or handlers; the control rig adds constraints and drivers to its armature, and **Remove control rig** takes them away again. Source timing can change the clip's duration; TAE events are not retimed. In-game playback of a retargeted clip has not been verified.
