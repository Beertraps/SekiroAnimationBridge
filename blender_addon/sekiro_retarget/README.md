# Sekiro Retarget Assistant 0.7.0

An optional Blender add-on that matches the bones of two rigs, bakes the motion of one onto the other, and writes the result as HKX through the Animation Bridge installed on the same computer. It also gives an imported rig a [control rig](#control-rig) for animating by hand, with [fixes](#fixes) for common cleanup, and can [mirror an animation](#mirror-animation) left to right. The bridge's own import and export need no add-on.

## Install

In Blender 4.5, open Edit > Preferences > Add-ons, use the dropdown menu > Install from Disk, choose `SekiroRetargetAssistant-0.7.0.zip`, and enable **Sekiro Retarget Assistant**. If an older version is installed, remove it first, or restart Blender after installing over it. The tools are in the 3D Viewport sidebar: press N and open **Retarget**.

The add-on needs no external Python libraries, account or network connection. To export HKX from Blender it uses the Animation Bridge on this computer and finds it by itself: the bridge records its folder each time its UI or CLI runs, and the conversion Python comes from the bridge's settings. The add-on preferences show what was found and can override both paths. This version was exercised in Blender 4.5.14; other Blender versions have not been run.

## Workflow

The **Sekiro Retarget Assistant** panel leads through four steps, each a sub-panel that you can close once it is done. A greyed-out button says under it what it needs first. The box under step 4 shows the result of the last match, bake or export.

1. Open the bridge `.blend` of the receiving character, the target.
2. In **1. Choose rigs**, set **Target (receives the motion)** to its armature: choose it in the field, or select it in the viewport or Outliner and click the arrow button beside the field. Click **Append source .blend** and choose the donor animation scene. The add-on brings in its rig, meshes, action, root-motion object and embedded HKX metadata, sets it as **Source (gives the motion)** and matches the bones. Two rigs already in the scene can be chosen directly instead.
3. In **2. Match bones**, click **Match bones automatically** if no list shows yet, and review the list. The line above it counts the matched bones and the bones to review: rows without a source bone, switched off, or matched below 94%. Those rows have a question mark instead of a check mark, and **Show unmatched / uncertain only** lists just them. The small triangle under the list opens a filter that finds target and source bones by name, and an A–Z sort. Assign a source bone through a row's search field, use a suggestion, or **Accept all suggestions**. **Mirror L → R** and **Mirror R → L** copy corrections to the other side. Switch off rows you do not want. The eye on a weapon row hides that weapon in the bake; see [Weapons](#weapons). **Save map** and **Load map** reuse a reviewed list. Once a list exists, the button reads **Match bones again**: it makes a new list, which replaces your changes.
4. In **3. Bake motion**, click **Bake motion onto target**. **Bake method** above it stays at *Bone by bone* for most clips; *Full body (experimental)* needs no bone list for the body, see [Full-body bake](#full-body-bake-experimental). The closed groups under the button hold the bake options (see below); their defaults suit most clips. The bake creates a new action and keeps the original one. Bake again at any time with other options or a corrected map: each bake starts from the original clip, not from the previous result.
5. In **4. Export HKX**, choose an **Output** `.hkx` and click **Export HKX**. **Export settings**, closed at first, hold the game, the format and the other options; see [Export](#export). Export runs in the background; the status box shows progress and the result, and Esc cancels. The bridge writes the HKX with a `.motion.json` sidecar beside it. Pack the HKX into the game's animation binder with a binder tool such as WitchyBND.

**Only bones the clip animates**, in step 2 and on by default, matches only the bones that a bridge rig's HKX clip animates, its tracks; the model's other bones, such as cloth and helper bones, follow their parents. Switch it off to match every bone of the model. It takes effect at the next match.

To export with the bridge UI or CLI instead, click **Use target in the bridge UI**, save the `.blend`, and export that scene as usual.

### Both characters from one import

The bridge can import the donor beside the target in one step, so steps 1 and 2 need no second scene. Pin the donor animation in the **Retarget donor** block of the bridge's import page, from any source or game, then choose the target's animation and create the scene. On the command line, the `-Donor` options do the same; see the bridge's user guide.

The scene holds both rigs, each with its own action, root-motion object and embedded HKX metadata. Everything of the donor is named *Donor*: its rig is, for example, `Donor c5060`, its root-motion object `Donor HKX_RootMotion` and its metadata text `Sekiro Source - Donor - a000_003041.json`. Rigs of the same name, such as c0000 from two games, stay apart this way. The donor stands beside the target; only its delta location moves it, so its keys stay as imported and the bake gives the same result wherever it stands. The target keeps the scene's frame range, frame rate and export rig, as after a single import, so it exports the same way.

When the file opens, the add-on fills in **Source** and **Target** from the import while both are empty, and the status says so. Continue in **2. Match bones** with **Match bones automatically**.

## Matching

Bone names do not have to match. The matcher uses three kinds of evidence:

- **Names.** Namespaces and prefixes (`mixamorig:`, `CC_Base_`, `Bip01`, `DEF-`, `J_Bip_`), separators and left/right conventions are normalized, and common aliases are recognized: upper arm/arm, forearm/lower arm, thigh/upper leg, calf/shin, pelvis/hips and root-position names.
- **Anatomy.** The hierarchy and rest positions of each rig identify the hips, spine, neck, head, arms, legs, hands, feet and fingers, also in rigs with meaningless names such as `Bone_017`. Chains of different length are matched end to end, so a three-bone spine maps onto a two-bone spine chest to chest.
- **Position.** Left and right come from the rest position when the names do not tell them.

Helper bones (twist, cloth and similar) are matched by name only, and only below matched parents. A weapon bone in a matched hand, such as Sekiro's `R_Weapon` dummy, takes the weapon bone in the source's matching hand, such as an enemy's `R_Katana`. Weapons that the source clip hides by shrinking them to almost nothing do not count, so Isshin's gun and spear stay out; of several that remain, the hand's own child wins. Where the source holds a weapon in one hand only and the target in the other hand only, the weapon changes hands: Godfrey holds his axe in his left hand and Isshin his katana in his right, so Isshin's `R_Katana` takes `L_Axe` at 80% and is listed for review. Weapon bones that rest away from the hand, such as Isshin's spear `L_Yari`, are not matched this way, but you can give one a source weapon by hand; see [Weapons](#weapons). Bones that store a weapon on the body, such as `Katana_Saya_Storage`, are not weapons in the hand. A source bone is used at most once: choosing one that another row uses clears that row, which then reads *Source moved to* the new row's bone. Uncertain matches stay suggestions until you accept them. Percentages describe match strength, not measured probabilities.

On synthetic test rigs of 15 conventions (Mixamo, Unreal, 3ds Max Biped, VRoid, Character Creator, Rigify, Daz, two FromSoftware styles, and six rigs with scrambled bone names), every core body bone matched in every pairing.

## Bake options

**Bake method**, above the button: *Bone by bone*, the default, gives each target bone the motion of the source bone that the bone list gives it. *Full body (experimental)* finds the body in both rigs without a bone list and keeps the feet and hands where the source's are; see [Full-body bake](#full-body-bake-experimental).

The options sit in four groups under **Bake motion onto target**, closed at first.

**Pose and timing**

- **Rest stance.** *Match source stance* first poses the target limbs to point like the source rest pose, so an A-pose target follows a T-pose source without lowered or raised arms. *Keep target stance* applies the rotations from the target's own rest pose.
- **Unmapped bones.** *Keep target animation* keeps the original clip's motion for cloth, face, weapon and other unmapped bones. *Rest pose* holds them at rest; for bridge rigs, rest is the HKX reference pose.
- **Clip timing.** *Use source length* gives the clip the source's duration. *Fit target length* resamples the source over the target clip's length.

**Body travel**

- **Move body with source hips** and **Scale travel by leg length**, or a manual **Travel scale** while that is off, control body travel; see [How the bake works](#how-the-bake-works).
- **Root motion.** *Automatic* copies the source root motion when the source has a root-motion object. Without one, body travel becomes root motion when the body moves farther than 30% of its leg length (the status says so), and otherwise none is written. The other choices force one source: *From source root*, *From body travel* (optionally turning with the body, **Turn root with the body**), *Keep target root* (same clip length only), or *None*.

**Arms and hands**

- **Keep hands out of the body** (on by default). Where a hand, or what it holds, would go into the target's torso, the hand is moved out through its arm; see [Body clearance](#body-clearance). It needs the target's character mesh in the scene.
- **Keep arms close to the body** (on by default). Where the source holds an arm close to its own body, the target's arm turns in at the shoulder until it stands as close to the target's torso, at the target's size, so that a target with a slimmer body does not hold its arms out; see [Arm distance](#arm-distance). It needs the character meshes of both rigs in the scene.

**Weapons**

- **Weapon grip.** *Target's own grip*, the default, puts each weapon in the target's hand as the target's own clip holds it, with that clip's fingers, and turns the wrist so that the blade points as the source's does, as far as **Blade follows source** says (100% by default). *Source's grip* puts the weapon where the source's weapon sits in the source's hand, scaled to the hand, with the source's fingers, for a weapon made to fit the source's grip. See [Weapon grips](#weapon-grips).
- **Second hand on the weapon** (on by default). Where the source holds its weapon with both hands, the target's other hand goes onto the target's weapon at the matching place; see [Second hand](#second-hand).

With a control rig on the target, **Bake motion onto target** is greyed out and says so: remove the control rig first; you can add it again afterwards.

## How the bake works

Each mapped bone takes its source bone's world-space rotation change from the source rest pose. The target keeps its own bone lengths and proportions.

Body travel goes to the bone above both the hips and the spine: Root in Dark Souls III and Sekiro enemies, RootPos in Sekiro, Dark Souls III and Elden Ring player rigs, and Master in Dark Souls (DS1) player rigs. Legs and upper body therefore move together. Unmapped bones between that bone and the hips or spine follow it rigidly; bones above it hold their rest pose. Travel is scaled by the ratio of hip heights above the feet, or by a manual scale.

The new action keys the mapped bones, the bones that carry the body and the target clip's tracks. It keys any other bone only if it moved by more than 0.01 mm or 0.001 degrees. A mapped bone without a track in the target clip gets a warning: export with **Original tracks + keyed bones** to include it.

### Weapons

When a mapped weapon bone and its source bone both carry a clearly elongated mesh, the target bone is turned in its own space so that its weapon lies like the source's: the long axes parallel and, where both blades have a flat side, the flat sides too, so that the edge faces where the source's does. Of the two ways to lay one flat side on the other, the bake takes the one where the two meshes, scaled to the same length, lie closer together, which keeps a curved blade's edge on the source's edge side. The target's weapon is the mesh on its bridge weapon socket; the source's may also be the vertices its weapon bone deforms most, as with an enemy's katana inside the character mesh. Wolf's `R_Weapon` and Isshin's `R_Katana` differ by 6° in their long axes and by about 50° about the blade, which 0.6.0 left as it was; bones authored along other axes can differ by 90° or more. The status lists each turn.

A target weapon bone that rests at its own hand and takes a source weapon that rests at the matching hand keeps its own grip and only turns. The bake places any other mapped weapon bone where the source holds its weapon: one that takes a weapon from the other hand, such as Isshin's `R_Katana` with Godfrey's `L_Axe`, or one that rests away from the hand until a clip brings it in, such as Isshin's spear `L_Yari`, which rests 1.7 m from his hand. A weapon rests at a hand when it lies within three quarters of the forearm's length of it. On every frame, the placed bone:

- goes to the hand that holds the source weapon: the target bone mapped to the nearest mapped bone above the source weapon. It keeps the source weapon's offset from that hand, scaled like body travel, but along the weapon's own line its grip stays in the hand, as a weapon in its own hand does. Godfrey's grip slides along his long axe, and without this, Isshin's katana would float up to 60 cm from his hand.
- turns like the source weapon, together with the blade turn above, and shows or hides with it: where the source clip shrinks its weapon to nothing, the placed bone shrinks to 0.1% and keeps its last rotation, and where the target's own clip hides the bone, as Isshin's clips hide his spear, it shows wherever the source weapon shows.
- carries the bones below it, such as a scabbard on the katana.

The weapon's line is the long axis of the source weapon's mesh; without a mesh, the bone's X axis, along which FromSoftware weapon meshes lie. The status names each placed bone and the hand it is placed in. Weapon bones that no row maps keep the target clip with *Keep target animation*: with the axe on Isshin's spear, his katana stays in his right hand and shows where his clip shows it. With **Second hand on the weapon**, the other hand of a two-handed grip goes onto the weapon; see [Second hand](#second-hand).

To hide a weapon for the whole clip, click the eye (**Hide**) on its row in the bone list. Weapon, scabbard, storage and shield rows have it, mapped or not. On every frame the bake shrinks the bone to 0.1% where it would otherwise be, as FromSoftware clips hide weapons, and the bones below it shrink with it: with the axe on Isshin's spear, hiding `R_Katana` leaves only the spear. Bone maps save the toggles, and **Match bones again** clears them with the rest of the list. The bake hides at 0.1% rather than 0 because a bone scaled to 0 has no inverse, so the bones below it could not be placed against it.

Keying a weapon's scale by hand hides it too, but a new bake makes a new action without those keys. Export handles a key of 0: the bone keeps its keyed rotation, and tracked bones below it keep their own channels, so they are in place when the weapon shows again or the game blends into another clip.

### Weapon grips

Two characters rarely hold even similar weapons the same way: the weapon bone sits at another place in the fist, turned another way, and the fingers close at other angles. Copying the source's rotations alone left Wolf's hilt beside his fingers with Isshin's clip, although both hold a katana. **Weapon grip** chooses whose grip each weapon in a hand keeps:

- *Target's own grip*, the default, reads how the target's own clip, the action it had before the bake, holds the weapon: the weapon bone's place and turn in the hand and the pose of that hand's fingers, on the first frame that shows the weapon. On every frame the weapon sits there and the fingers take that pose, easing over 0.1 s around frames that hide the weapon. The wrist then turns, without twisting about the blade, so that the blade points as the source's does. **Blade follows source** sets how far: at 100% the blade keeps the source's directions, at 0% the wrist turns as the source's does and the blade points where the own grip puts it. Where the two grips differ, the turn bends the wrist sideways: Isshin's clip turns Wolf's wrist by up to 44°, Owl's clip by up to 23°.
- *Source's grip* puts the weapon where the source's weapon sits in the source's palm, in a frame from the wrist toward the knuckles, scaled by the hands' sizes, and turned in that frame as the source's weapon is turned in the source's palm, and the fingers keep the source's pose. Where the bake turns the target's palm otherwise than the source's, as with Wolf's hand on Isshin's clip by about 10°, the weapon turns with the palm, so the hilt lies across the fingers as the source's does and the blade points up to that much away from the source's. Use it for a weapon whose grip belongs to the animation, such as an unusual weapon held in an unusual way, and give the target a weapon that fits that grip. It needs two or more fingers on both hands; otherwise the weapon keeps its place in the hand from the rest pose.

The wrist turn also moves what the hand holds, so a hilt can come closer to the body: in Isshin's clip on Wolf it goes up to 9.6 cm into Wolf's torso at 100%, against 6.4 cm at 0%, and **Keep hands out of the body** moves the hand out by up to 12.3 cm instead of 7.6 cm. A lower **Blade follows source** trades blade direction for less of that push.

Where the target's own clip does not animate the weapon bone, the weapon takes the source's grip, and the status says so. FromSoftware clips hide unused weapons by shrinking them but still key their place in the hand. Where the own clip hides the weapon on every frame, its grip comes from a hidden frame, which can be off, by 85 mm in one of Owl's clips, and the status warns. A weapon that the bake places in a hand (see above) takes the own grip when it hangs below that hand, as Owl's katana does, which rests a metre from his hand until his clips bring it in; where the own clip hides it on every frame, it stays where the source holds its weapon, and the status says that a target clip that shows it gives its own grip. A placed weapon taken from the other hand keeps its place with either grip.

### Second hand

Where the source holds its weapon with both hands, **Second hand on the weapon** puts the target's other hand on the target's weapon at the same place. It comes after the hands are kept out of the body, so the weapon has its last place:

- The source's other hand holds on where the middle of its knuckles comes within half a hand's length of the weapon's axis, from a third of a hand behind the pommel to as far beyond the tip. Up to a whole hand's length it holds on less and less, and the weight is smoothed over 0.05 s, so the hand eases on and off.
- The target's hand takes the same side of the axis, scaled by the hands' sizes, and the same distance from the main hand along it, scaled by the length of the grip behind the main hand (or of the weapon ahead of it), so both hands stay on a hilt of another length.
- The hand keeps its turn relative to the weapon from the bake, which is the source's, and the arm reaches the place through a two-bone solve that keeps the elbow in its plane.

Elsewhere the arm keeps the bake. The status lists the frames each hand holds on and warns where the arm does not reach. Owl's clip on Wolf puts the left hand on the hilt within 1.2 mm, Isshin's clip on Owl within 4.7 mm. The control rig's **Hand on weapon** fix can still move the hand along the hilt.

### Body clearance

The target keeps its own proportions, so a source with a thinner body or longer arms can hold its hands closer to its body than the target's mesh allows. With **Keep hands out of the body**, the bake finds, frame by frame, where the hand meshes, the fingers and what the hands carry come within half an arm of the wrist and inside the torso: the mesh that the hips and spine deform most, without arms, legs, head or cloth bones. It also measures how deep the source's own hands and weapons go into the source's torso, as the distance from their deepest point to the nearest surface, so clipping that the source animation already has, such as a hilt pressed into a sash, stays at the target's size. A source without a body mesh is not compared, and then all clipping is removed. Where the target's hand goes in deeper than the source's, the bake moves it out through a two-bone arm solve that keeps the elbow in its plane and the hand's rotation:

- The push takes out what goes deeper than the source's own hand, scaled by the ratio of arm lengths. Where the source's hand is clear of its body, it goes 2% of the arm's length further; where the source's hand touches its body, the target's ends touching too.
- Each stretch of frames in contact gets one direction, forward, back or sideways in the torso's frame, the one whose largest push is smallest.
- Pushes ease in and out over 0.2 s, so the frames around the contact move too, and every frame still gets at least its own push.
- Hands that come close together within a stretch, as on one hilt, move as one.
- A weapon that the bake places in a hand counts with that hand, also when its bone hangs from the other arm, so it moves out with the hand that holds it.
- A push longer than about a third of the arm is left out and reported, since that is not a matter of proportions. An arm that would have to be longer than it is stays straight, pointing toward the push.

The status lists the frames each hand moved, the largest push and how much of the source's own clipping a hand keeps. Arms, legs and heads can still pass into each other; the control rig helps with that cleanup.

### Arm distance

The opposite happens too: a source whose body is wide for its arms holds them out to clear it, and the target copies those angles. Owl's clip on Wolf in the review scene leaves Wolf's arms up to 14 cm farther from his body than Owl's stand from Owl's, at Wolf's size. With **Keep arms close to the body**, the bake measures, frame by frame, how close each source arm comes to the source's torso: the nearest approach of the vertices that its forearm, hand and fingers deform most, without what the hand holds, to the torso mesh found as for body clearance. Scaled by the ratio of arm lengths, that is how close the target's arm should come to its own torso. Where it stands farther:

- The whole arm turns in at the shoulder joint, with the elbow's bend, the hand's rotation and what the hand holds, until its forearm, hand or fingers come that close, but no closer than 2% of the arm's length, and by at most 45°.
- Up to a quarter of an arm from the body, the source's gap is matched. From there to half an arm, less and less of the difference is taken out, and an arm that the source holds farther than half an arm from its body is left alone, so reaches and swings keep their extent.
- Turns ease in and out over 0.2 s. Where the easing carries a turn onto a frame whose arm already stands close, it stops at 2% of the arm's length.
- Where both hands come within 0.4 arm lengths of each other, as on one hilt, both arms stay as they are, so the grip holds. Their turns ease out over the 0.2 s before and back in over the 0.2 s after.
- An arm whose torso lies along it, so that turning at the shoulder cannot bring it closer, stays as it is.

The arm distance comes before **Keep hands out of the body**, which can still move a hand out afterwards. A source without a body mesh is not compared, nor is an arm without a mesh in both rigs, and the status says so. The status lists the frames each arm turned, by how many degrees and how far the hand moved, and the frames it was kept for a grip. The option only brings arms in: on a target with a wider body than the source, an arm can still pass into the torso, and **Keep hands out of the body** moves only the hands.

### Foot targets

Sekiro and Dark Souls III rigs hang a straight chain from `Master` on each side: `L_Foot_Target2` at hip height, `L_Foot_Target1` at knee height and `L_Foot_Target` at the ankle, where the foot rests. In the game's clips the chain stands on the foot like an upright column: the target copies its foot on every frame, and the two bones above it keep their reference pose, upright, and move with it; the game most likely reads the targets for foot IK. A retarget that leaves a target off its foot can make the foot snap when the game blends into another clip. So the bake stands each chain on its foot on every frame, after everything else has placed the feet: the chain keeps its rest pose and moves as one, without turning, so that the target sits on the foot, which it also turns with. That happens whatever the source's own targets do, and whether or not their rows are mapped. The status lists the targets. Export does the same for any action, including edits made after the bake.

### Full-body bake (experimental)

**Bake method** > *Full body (experimental)* bakes the body without a bone list, the way Biped and full-body IK tools retarget: it reads both skeletons as one template body and moves the motion from template to template.

- **The body is found in both rigs.** The hips, spine, neck, head, clavicles, arms, legs, hands, feet and fingers are found by bone name where the name is clear and by the skeleton's shape otherwise, so rigs with names such as `Bone_017` work too. The status names the parts it found by shape.
- **Chains spread over their own bones.** Between joints that both rigs have, such as the chest, shoulder, elbow and wrist, each target bone takes the source's motion at the same share of the way along the chain. A two-bone spine takes a three-bone spine's bend, a twist bone 40% down a forearm takes 40% of the turn from forearm to hand, and a target without clavicles works. Each segment then lies along the source's chain over the same share. Target bones that have no counterpart, such as clavicles the source does not have, do what **Unmapped bones** says.
- **The feet stay on the source's footprint.** Each foot goes where the source's foot is, measured from the hips and scaled like body travel, so a foot that stands still in the source stands still in the target. Where a leg cannot reach that far, the pelvis lowers, by at most a quarter of the leg, and the status gives the frames. The legs reach by IK: knees keep pointing where the source's point, and the feet keep the source's rotation.
- **The hands meet where the source's meet.** Where the source's wrists come within about half a forearm of each other, the target's wrists come as close and in the same direction apart, scaled by arm length. A hand that holds a weapon stays, and the free hand moves; **Second hand on the weapon** then still puts it on the grip.
- **Everything else works as bone by bone.** Bones outside the body, such as weapons and helpers, take their source bones from the bone list, or from automatic matching when there is no list. Rest stance, body travel, root motion, weapon grips, Second hand, body clearance, arm distance and the foot targets work as described above. Without a bone list there are no eyes to hide weapons with.

The price of the contacts: the legs and arms point up to about 16° away from the source's, the source's stance width carries over to the target, and where the spine bone counts differ, a bend within one target spine bone is lost. On FromSoftware pairs such as Owl or Isshin onto Wolf, whose skeletons match bone for bone, both methods give nearly the same result, and *Bone by bone* stays the better choice. The full-body bake is meant for rigs of other bone counts and proportions; check its result before you export it.

## Export

**Export HKX** follows the same path as the bridge's export page. Blender samples the evaluated pose with the bridge's own exporter, so constraints, drivers and NLA tracks are baked. The bridge's conversion Python then writes the HKX with its Havok compatibility fixes and, with **Read back and compare**, decodes it again and reports the largest difference. **Output** and **Replace existing**, which writes over an existing `.hkx` and its sidecar, stay in step 4; the rest is under **Export settings**:

- **Game.** *Stored in scene* uses the game recorded at import (bridge 0.5 and later). Older scenes need the game chosen here.
- **Format.** *Interleaved* stores every frame exactly. *Spline* compresses like the game's own clips, within the position **Tolerance** and with the chosen rotation precision.
- **Tracks.** *Original clip tracks* keeps the track list of the clip the target was imported from; *Original tracks + keyed bones* adds bones keyed in the action; *Every skeleton bone* writes all of them.
- **Frames.** The scene range (set by the bake), the action's key range, or the clip's frame count.
- **Root motion.** *As baked* writes the target's root-motion object; *None* writes no root motion.

## Control rig

An imported rig has one short bone per game bone, each oriented however the game stores it, which is awkward to animate by hand. The **Control rig** panel, below the retarget panel, adds animator controls to it:

1. Select the armature, or let the panel use the scene's bridge rig, and click **Add control rig**. Mute the armature's NLA tracks first if it has any.
2. The armature switches to Pose Mode and its controls draw in front of the mesh. In a file opened again in Object Mode, the panel says that the controls are posed in Pose Mode, and its **Pose Mode** button switches.
   The controls come in groups:
   - **Torso**: a root control whose arrow points forward, rings for the hips, spine, neck and head, and rings for the bones above them (such as Master and RootPos).
   - **FK limbs**: a ring on each arm and leg bone, pointing along the limb.
   - **IK limbs**: a box on each hand, a square under each foot, a diamond pole target behind each elbow and in front of each knee, and a [swivel ring](#elbow-and-knee-swivel) at each elbow and knee.
   - **Fingers & toes**: small rings.
   - **Extras** (twist, weapon, cloth, face and other helper bones) and **Game bones** start hidden. The toggles under **Show** show or hide each group.
3. The active action is baked onto the controls as a new action, "*clip* Controls", in FK and IK alike, so the pose does not change. The original action is kept.
4. Each arm and leg has an IK slider: 0 follows the FK controls, 1 the IK controls, and you can key it. **Switch to IK** and **Switch to FK** first match the limb's other controls to its current pose, then set the slider, so the limb does not jump. They match at every frame of the scene range, or only at the current frame when *Match every frame* is off in the operator's redo panel.
5. Animate, save and export as usual. **Remove control rig** asks whether to *Keep the edited motion*, which bakes what the controls do onto the game bones as "*clip* Edited", or to *Restore the original action*.

Every game bone copies a hidden socket bone that hangs from its FK control at the game bone's own rest, and an arm or leg blends in a second socket on a two-bone IK chain by its slider. The game bones keep their rest pose, so meshes, weapon sockets and both exporters keep working. On owned test rigs and on copies of Sekiro player and enemy scenes, adding the control rig moved no game bone by more than 0.0001°, and IK placed the elbows, knees, hands and feet within 0.1 mm of the clip.

The bridge's export page, its CLI and **Export HKX** sample the game bones, so they write what the controls do. With a control rig on the armature, **Read actions** lists only the actions that animate the controls, and exporting another action of that armature stops with a message. A keyed control of a bone without a track in the clip counts for *Original tracks + keyed bones*. To retarget onto the armature, remove the control rig first; you can add it again afterwards.

Arms and legs get IK where the matcher finds them; other skeletons get FK controls only. IK bends each elbow and knee around one hinge, so a twist that the clip puts into a forearm itself does not show while that arm is in IK; FK keeps it. Bones that the clip scales unevenly, such as muscle helpers, get controls along their own axes so the scale carries over; on arm and leg bones, that scale holds in FK only. This version has no foot roll, finger IK, face controls or IK stretch.

### Elbow and knee swivel

Each IK arm and leg has a swivel ring at its elbow or knee, around the line from the shoulder or hip to the hand or foot control, with an arrow on the side the joint bends to. Turning the ring swings the elbow or knee around that line, on top of where the pole puts it, while the hand or foot stays where it is: for an arm that goes into the body after a grip is adjusted, without moving the pole frame by frame. The ring turns about that one axis only, and the panel shows it as **Elbow swivel** or **Knee swivel** under the limb's IK slider. It is keyed at 0 on every frame, like the other controls, so a turn on one frame changes that frame only. **Switch to IK** sets it back to 0, since the pole then puts the joint where it is. **Adjust over frames** spreads a swivel turn over a range of frames like any other change. On the test rig, a 30° turn swung each elbow and knee by 30° within 0.22° and moved the hand or foot by 0.002 mm.

### Fixes

The **Fixes** panel under the control rig panel does common cleanup that takes many steps in Blender itself. A fix keys the controls on the frames you choose and eases in before them and out after them over **Blend** (0.2 s by default); the frames beyond keep their keys. It adds no constraints, so export and **Remove control rig** treat its keys like any others, and Ctrl+Z undoes it.

1. Choose the fix:
   - **Hand on weapon** keeps a hand where you pose it relative to a bone, such as the second hand of a two-handed grip on the hilt. It starts with the arm whose other hand holds a weapon with a mesh, following that weapon.
   - **Weapon into sheath** moves the hand so that the weapon it holds keeps where you pose it on the sheath. Pose the blade at the mouth of the sheath and click **Use this pose**, then pose it fully in on a later frame and click **Apply fix**: between the two frames the blade slides along the sheath, also where the clip hides the weapon by shrinking it.
   - **Plant foot** keeps a foot where it stands on the current frame, so it does not slide. With root motion it stays still in the game's world, where root motion carries the character; in Blender, where the character stays in place, the foot moves against the root motion.
   - **Adjust over frames** spreads a change that you pose over a range of frames, such as an arm that stands too wide. An IK control or pole changes relative to the bone above its limb, so the change turns with the body, and a [swivel ring](#elbow-and-knee-swivel) by its own angle. With **Selected controls**, each selected control, such as an FK ring, changes its own channels, as an additive layer would.
2. Choose the limb and, for the hand fixes, the bone to follow and the weapon held. An empty field uses the default that the panel names under it.
3. Choose **Whole clip**, or **Frames** with a start and an end; the clock buttons take the current frame.
4. Pose the controls without keying them. Turn auto keying off for **Adjust over frames**, which compares your pose with the keys; the panel warns while it is on. To pose several frames, click **Use this pose** before you go to the next one, since Blender drops a pose that is not keyed when the frame changes; **Apply fix** takes the pose on the current frame too.
5. Click **Apply fix**. The status lists how far the hand or foot moved, and the frames where the limb could not reach (IK has no stretch) or was not fully in IK.

Between posed frames a fix interpolates the relation or the change; before the first posed frame and after the last, it holds. The fixes key a limb's IK controls, so they need the limb in IK on the chosen frames. When the limb is not in IK on the current frame, the panel says so and shows **Switch to IK**, and **Apply fix** refuses where it is in FK on all the chosen frames: switching afterwards would match the IK controls to the FK pose again and undo the fix. On an owned test rig, the fixed hand kept its grip within 0.01 mm, the planted foot and the sheathed blade kept their paths within 0.05 mm, and the export after **Remove control rig** matched the export with the control rig.

## Mirror animation

**Mirror animation**, under the armature's name in the **Control rig** panel, makes a left-right mirrored copy of the armature's action, so that a right-handed slash becomes a left-handed one. Select the armature, or let the panel use the scene's bridge rig, and click it. The copy, "*clip* Mirrored", plays at once with its root motion, "*clip* Mirrored RootMotion"; the original action and root motion are kept. Export the copy like any other action: **Export HKX** writes the active action, and the bridge's export page and CLI can choose it by name and pair its root motion by that name. Mirroring the copy gives the original back.

The mirror runs across the character's middle plane:

- A bone with a counterpart on the other side takes its counterpart's motion, reflected: `L_Hand` does what `R_Hand` did. Bones pair by name, and bones whose names give no side, such as cloth on either hip, where one rests at the other's mirrored place, as in a rig that its maker mirrored. FromSoftware's left and right bones rest half a turn from mirror images of each other, which is why Blender's *Paste Flipped Pose* turns them wrong; the mirror reads each pair's rest frames instead.
- A bone on the middle line, such as the spine, reflects its own motion, so the body leans and turns the other way. Root motion reflects too: sideways travel and turns change sign.
- Gear changes sides with the motion. The katana that the right hand swings goes into the left hand with the swing, whether the game hangs it on `R_Weapon` or the character's mesh holds it, and a scabbard on the left hip goes to the right hip. Gear is a weapon, sheath or shield bone, together with the bones without a counterpart between it and the body, such as a cord around a hilt. It goes where the reflection puts it, and the bones below it mirror across the piece's own middle plane, so that a symmetric piece keeps its shape, and a pair on it, such as the eyes of a head held as a weapon, swaps. A weapon that the bridge hangs on a bone, as Wolf's katana on `R_Weapon`, is reflected so that its model maps onto itself, so the mirrored katana strikes with its edge. The bone's exported motion carries this, so the game, which hangs the sword on that bone, shows it as Blender does.
- Gear keeps its side where its mesh bends together with the body, as Wolf's scabbard is part of his clothes, and where it is stored on the body without a mesh of its own, as the hip and back cases where the game hangs sheathed weapons. The status lists such gear.
- Another bone without a counterpart keeps its own motion and goes along where a bone with a counterpart carries it, as the cloth of a sleeve; elsewhere, as a sash on one hip, it stays on its side and reflects its own motion. The status lists the ones that move.
- HKX tracks belong to bones, so the copy has the same tracks, each with its bone's new motion. A custom property that the clip keys on a bone moves to the bone's counterpart.

With a control rig on the armature, the game bones follow the controls, so the button is greyed out: remove the control rig, keeping the edited motion, mirror, and add the control rig again. Mute the armature's NLA tracks first, if it has any. Constraints are not mirrored; the status names the bones they still act on.

On an owned test rig whose left and right bones rest at random turns, the mirrored clip was the exact reflection of the original, mirroring twice gave the original back, and the export read back as the mirrored clip. On clips of Isshin, Wolf and c5100, the mirror took under 1.4 s and the export read back within 0.000°. The mirror swaps motion, not meshes: an uneven costume, such as Wolf's prosthetic arm, stays on its side, and a pair whose rests are not mirror images keeps its rest places.

## Current scope

The retarget bake transfers humanoid FK animation. It aligns held weapons and holds them by a grip, puts the second hand on a two-handed weapon, keeps hands out of the torso and keeps arms as close to the body as the source's, but bone by bone it does not solve foot contacts, a hand reaching for anything else, cloth or facial animation. The experimental full-body bake keeps planted feet and hands that meet each other, at the cost of the limbs' directions; it does not handle toes, the ground or other contacts. The control rig's [fixes](#fixes) keep the second hand where you put it on the grip, a weapon in its sheath and the feet on the ground over the frames you choose, and its IK limbs and swivel rings help with the rest by hand. Different proportions can still need pose cleanup. Non-humanoid rigs need manual mapping and review.

Mapped target bones must have no active constraints, and target NLA tracks must be muted. The bake adds no live constraints or handlers; the control rig adds constraints and drivers to its armature, and **Remove control rig** takes them away again. The fixes add keys only. Source timing can change the clip's duration; TAE events are not retimed. In-game playback of a retargeted clip has not been verified.

**Mirror animation** mirrors the bones and the root motion only: TAE events, such as a hand an effect comes from, and weapon part clips stay as they are. A weapon that Wolf's TAE event 715 moves to another dummy, such as the katana into its sheath, keeps its side there, as do the sheath and the prosthetic tools. In the game, a blend from a mirrored clip into an unmirrored one moves the weapons across the body. In-game playback of a mirrored clip has not been verified.
