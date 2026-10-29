# Sekiro Retarget Assistant 0.9.0

An optional Blender add-on that matches the bones of two rigs, bakes the motion of one onto the other, and writes the result as HKX through the Animation Bridge installed on the same computer. It also gives an imported rig a [control rig](#control-rig) for animating by hand, with [fixes](#fixes) for common cleanup, can [mirror an animation](#mirror-animation) left to right, and can [join two animations](#join-animations) into one clip. The bridge's own import and export need no add-on.

## Install

In Blender 4.5, open Edit > Preferences > Add-ons, use the dropdown menu > Install from Disk, choose `SekiroRetargetAssistant-0.9.0.zip`, and enable **Sekiro Retarget Assistant**. If an older version is installed, remove it first, or restart Blender after installing over it. The tools are in the 3D Viewport sidebar: press N. They sit in two tabs on the sidebar's edge:

- **Retarget** holds the four retarget steps below.
- **Animate** holds the tools that change an armature's own animation: **Animation**, with [Mirror animation](#mirror-animation) and [Join animations](#join-animations), then the [Control rig](#control-rig) and its [Fixes](#fixes).

At the bottom of each tab, a **Log** panel holds the result of the last action, such as a match, bake, export, mirror or join. It starts closed. Its header says **Warnings**, with a warning sign, when that result warned; click the header to read it. Blender's status bar shows the same message for a few seconds.

The add-on needs no external Python libraries, account or network connection. To export HKX from Blender it uses the Animation Bridge on this computer and finds it by itself: the bridge records its folder each time its UI or CLI runs, and the conversion Python comes from the bridge's settings. The add-on preferences show what was found and can override both paths. This version was exercised in Blender 4.5.14; other Blender versions have not been run.

## Workflow

The **Sekiro Retarget Assistant** panel leads through four steps, each a sub-panel that you can close once it is done. A greyed-out button says under it what it needs first. The **Log** under step 4 holds the result of the last match, bake or export.

1. Open the bridge `.blend` of the receiving character, the target.
2. In **1. Choose rigs**, set **Target (receives the motion)** to its armature: choose it in the field, or select it in the viewport or Outliner and click the arrow button beside the field. Click **Append source .blend** and choose the donor animation scene. The add-on brings in its rig, meshes, action, root-motion object and embedded HKX metadata, sets it as **Source (gives the motion)** and matches the bones. Two rigs already in the scene can be chosen directly instead.
3. In **2. Match bones**, click **Match bones automatically** if no list shows yet, and review the list. The line above it counts the matched bones and the bones to review: rows without a source bone, switched off, or matched below 94%. Those rows have a question mark instead of a check mark, and **Show unmatched / uncertain only** lists just them. The small triangle under the list opens a filter that finds target and source bones by name, and an A–Z sort. Assign a source bone through a row's search field, use a suggestion, or **Accept all suggestions**. **Mirror L → R** and **Mirror R → L** copy corrections to the other side. Switch off rows you do not want. The eye on a weapon row hides that weapon in the bake; see [Weapons](#weapons). **Save map** and **Load map** reuse a reviewed list. Once a list exists, the button reads **Match bones again**: it makes a new list, which replaces your changes.
4. In **3. Bake motion**, click **Bake motion onto target**. **Bake method** above it stays at *Bone by bone* for most clips; *Full body (experimental)* needs no bone list for the body, see [Full-body bake](#full-body-bake-experimental). The closed groups under the button hold the bake options (see below). By default the bake is raw: the weapon keeps the source's grip, and the corrections for hands, arms and a second hand on the weapon are off until you turn them on. The bake creates a new action and keeps the original one. Bake again at any time with other options or a corrected map: each bake starts from the original clip, not from the previous result.
5. In **4. Export HKX**, choose an **Output** `.hkx` and click **Export HKX**. **Export settings**, closed at first, hold the game, the format and the other options; see [Export](#export). Export runs in the background; its progress shows under the button, the result goes to the **Log**, and Esc cancels. The bridge writes the HKX with a `.motion.json` sidecar beside it. To put the HKX into the game's animation binder too, turn on **Add to animation binder**; see [Export](#export). Otherwise pack it with a binder tool such as WitchyBND.

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

The options sit in four groups under **Bake motion onto target**, closed at first. By default the bake is raw: **Weapon grip** is *Rest-relative grip*, and **Bend fingers onto the weapon**, **Keep hands out of the body**, **Keep arms close to the body** and **Second hand on the weapon**, which correct the result for another body or grip, are off. Turn them on where the target needs them.

**Pose and timing**

- **Rest stance.** *Match source stance* first poses the target limbs to point like the source rest pose, so an A-pose target follows a T-pose source without lowered or raised arms. Each hand also points from the wrist to its knuckles like the source's and lies about that line like it, since two models' hands can rest bent differently against the forearm: Wolf's rests bent 6° from his forearm, c7110's 14.6°, and the bake would keep that difference on every frame. *Keep target stance* applies the rotations from the target's own rest pose.
- **Unmapped bones.** *Keep target animation* keeps the original clip's motion for cloth, face, weapon and other unmapped bones. *Rest pose* holds them at rest; for bridge rigs, rest is the HKX reference pose.
- **Clip timing.** *Use source length* gives the clip the source's duration. *Fit target length* resamples the source over the target clip's length.

**Body travel**

- **Move body with source hips** and **Scale travel by leg length**, or a manual **Travel scale** while that is off, control body travel; see [How the bake works](#how-the-bake-works).
- **Root motion.** *Automatic* copies the source root motion when the source has a root-motion object. Without one, body travel becomes root motion when the body moves farther than 30% of its leg length (the status says so), and otherwise none is written. The other choices force one source: *From source root*, *From body travel* (optionally turning with the body, **Turn root with the body**), *Keep target root* (same clip length only), or *None*.

**Arms and hands**

- **Keep hands out of the body** (off by default). Where a hand, or what it holds, would go into the target's torso, the hand is moved out through its arm; see [Body clearance](#body-clearance). It needs the target's character mesh in the scene.
- **Keep arms close to the body** (off by default). Where the source holds an arm close to its own body, the target's arm turns in at the shoulder until it stands as close to the target's torso, at the target's size, so that a target with a slimmer body does not hold its arms out; see [Arm distance](#arm-distance). It needs the character meshes of both rigs in the scene.

**Weapons**

- **Weapon grip.** *Rest-relative grip*, the default, keeps the weapon at the target's own grip point and turns it there as the source's weapon turns away from its rest pose, with each finger of both hands turned in its hand as the source's finger turns from its rest pose, with **Match source stance** too. *Source's grip* puts the weapon where the source's weapon sits in the source's hand, scaled to the hand, with the source's fingers. *Target's own grip* puts each weapon in the target's hand as the target's own clip holds it, with that clip's fingers, and turns the wrist so that the blade points as the source's does, as far as **Blade follows source** says (100% by default), for characters that hold their weapons differently. A line under the menu says what the chosen grip does. See [Weapon grips](#weapon-grips).
- **Bend fingers onto the weapon** (off by default, with *Rest-relative grip* or *Source's grip*). Each finger joint bends until its skin just touches the weapon; see [Bend fingers onto the weapon](#bend-fingers-onto-the-weapon). This changes the source's finger pose.
- **Second hand on the weapon** (off by default). Where the source holds its weapon with both hands, the target's other hand goes onto the target's weapon at the matching place; see [Second hand](#second-hand).

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

- *Rest-relative grip*, the default, leaves the weapon bone at the target's own grip point in the hand, from the target's own clip, or from its rest pose where the clip does not animate it, and turns it there as the source's weapon turns in the source's hand away from the source's rest pose, carried over through both rest poses. Each finger of both hands turns so too: in its hand, from the target's rest pose, as the source's finger turns from the source's, also with **Match source stance**, which would otherwise swing the fingers toward the source's rest shape. On that clip the fingers then lie within 0.5° (left) and 1.2° (right) of Rokoko's, half the frames, where they were 5.3° and 6.0° off. It reads no meshes: it trusts that both rest poses hold their weapons alike in the hand, as FromSoftware's do. Rokoko's retargeting turns weapon bones this way. On Isshin's c5400_a000_003024 on Wolf it matches a Rokoko retarget of that clip within 1.4°, the HKX's rounding, and puts the hilt in Wolf's fist, where *Source's grip* puts the weapon 2.8 cm and about 40° away. A weapon placed in the other hand, or resting away from the hand, takes *Source's grip*.
- *Target's own grip* reads how the target's own clip, the action it had before the bake, holds the weapon: the weapon bone's place and turn in the hand and the pose of that hand's fingers, on the first frame that shows the weapon. On every frame the weapon sits there and the fingers take that pose, easing over 0.1 s around frames that hide the weapon. The wrist then turns, without twisting about the blade, so that the blade points as the source's does. **Blade follows source** sets how far: at 100% the blade keeps the source's directions, at 0% the wrist turns as the source's does and the blade points where the own grip puts it. Where the two grips differ, the turn bends the wrist sideways: Isshin's clip turns Wolf's wrist by up to 44°, Owl's clip by up to 23°.
- *Source's grip* puts the weapon where the source's weapon sits in the source's palm, in a frame from the wrist toward the knuckles, scaled by the hands' sizes, and turned in that frame as the source's weapon is turned in the source's palm, and the fingers keep the source's pose. The fist holds the weapon by its matching part, not by its bone, since games put weapon bones at different places on their weapons: Wolf's sits 22 cm from the end of his katana's hilt, Isshin's 35 cm from his. The bake measures how wide each weapon is along its length, lines up the two outlines (the widest part with the widest part, such as guard with guard, head with head, butt with butt, and in proportion between them), and finds the part of the target's weapon that matches the part the source's fist holds. That part's center line goes where the source's lies in the source's palm, scaled. This works for swords, spears, axes and other weapons with a handle along their length; a weapon without a clear long axis, such as a shield, still sits by its bone. Where the target's handle is thinner than the source's, it sits in the middle of a slightly loose fist, as the fingers keep the source's curl. With *Match source stance* the target's palm turns as the source's, so the blade also points as the source's does, up to the difference between where each weapon's hilt and blade point: 1.6° for Wolf's katana against Isshin's. With *Keep target stance* the palm can turn otherwise, by about 10° for Wolf's hand on Isshin's clip, and the weapon turns with the palm, so the hilt lies across the fingers as the source's does and the blade points up to that much away from the source's. Use it for a weapon whose grip belongs to the animation, such as an unusual weapon held in an unusual way, and give the target a weapon that fits that grip. It needs two or more fingers on both hands; otherwise the weapon keeps its place in the hand from the rest pose.

The wrist turn also moves what the hand holds, so a hilt can come closer to the body: in Isshin's clip on Wolf it goes up to 9.6 cm into Wolf's torso at 100%, against 6.4 cm at 0%, and **Keep hands out of the body** moves the hand out by up to 12.3 cm instead of 7.6 cm. A lower **Blade follows source** trades blade direction for less of that push.

Where the target's own clip does not animate the weapon bone, the weapon takes the source's grip, and the status says so. FromSoftware clips hide unused weapons by shrinking them but still key their place in the hand. Where the own clip hides the weapon on every frame, its grip comes from a hidden frame, which can be off, by 85 mm in one of Owl's clips, and the status warns. A weapon that the bake places in a hand (see above) takes a grip like a weapon resting there when it hangs below that hand, as Owl's odachi does, which rests a metre from his hand until his clips bring it in: the own grip, or the source's grip, by default or where the own clip hides it on every frame, and the status then says that a target clip that shows it gives its own grip. A placed weapon taken from the other hand keeps its place with either grip.

### Bend fingers onto the weapon

The source's fingers close around the source's weapon in the source's hand. On another hand and another hilt they can sink into it or stand off it: with Isshin's clip on Wolf, the source's grip put a quarter of Wolf's thumb skin and almost half of his middle finger's inside his hilt, 1.8 and 2.1 cm deep. **Bend fingers onto the weapon**, with *Rest-relative grip* or *Source's grip*, bends each finger joint, from the root out, until its skin just touches the weapon: up to 60° open where it goes in, up to 30° closed where it stands off by less than a quarter of a hand's length. The weapon stays where the grip puts it. A joint turns only about the axis it bends about, so a fingertip that lies across the hilt can stay partly in it.

It reads the skin from the meshes that the target deforms, the vertices that each finger bone moves most, and the weapon's surface from its mesh, leaving out its guard. A finger bone without skin counts as a tube a quarter of its length thick. The status says on which frames the fingers bent and by how much they opened and closed. Your own alignment under **Weapon in hand** comes after it.

### Weapon in hand

Where no grip fits two weapons well, align the weapon yourself. After a bake, open **Weapon in hand** under **Bake motion onto target**:

1. Choose the weapon, such as *R_Weapon in R_Hand*. The list shows the weapons that the last bake put in a hand.
2. Go to a frame where the weapon shows clearly, and click **Adjust weapon**. The target goes into Pose Mode with the weapon bone selected.
3. Turn (R) or move (G) the weapon until it sits in the hand as you want. Stay on that frame: changing the frame resets the pose.
4. Click **Apply to all frames**. The bake runs again, and the weapon sits in the hand that way on every frame, moved and turned as you did it, in the hand's own space. **Cancel** puts it back instead.

The alignment stays for later bakes, with any options, and adds up if you adjust again; the panel shows how far it moves and turns the weapon. **Reset** forgets it and bakes again. The weapon is aligned after the grip and before the second hand, so with **Second hand on the weapon** the other hand takes the aligned weapon. The status says how far each aligned weapon moved and turned.

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
- **The feet stay on the source's footprint, at the target's own hip width.** Each foot goes where the source's foot is, measured from the hips and scaled like body travel, so a foot that stands still in the source stands still in the target. Each foot also keeps the source's sideways distance from its own hip joint, scaled, so a target with wider hips stands that much wider, as with *Bone by bone*; the status says how far each foot was set out or in. While a foot stands, that sideways shift holds still, so it adds no sliding; while the foot steps, it turns with the pelvis. With root motion from the source, a foot counts as standing where the game puts it. Where a leg cannot reach that far, the pelvis lowers, by at most a quarter of the leg, and the status gives the frames. The legs reach by IK: knees keep pointing where the source's point, and the feet keep the source's rotation.
- **The hands meet where the source's meet.** Where the source's wrists come within about half a forearm of each other, the target's wrists come as close and in the same direction apart, scaled by arm length. Where the source holds its weapon with both hands, this holds however far apart the wrists are, and the middles of the knuckles keep the source's distance apart instead of the wrists, as the hilt passes through them: Owl's wrists on his long odachi hilt are 0.6 to 0.9 of a forearm apart, and Isshin's hand is half the size of Owl's against arms 0.84 as long. A hand that holds a weapon stays, and the free hand moves; with **Second hand on the weapon** on, it then still goes onto the grip.
- **Everything else works as bone by bone.** Bones outside the body, such as weapons and helpers, take their source bones from the bone list, or from automatic matching when there is no list. Rest stance, body travel, root motion, weapon grips, Second hand, body clearance, arm distance and the foot targets work as described above. Without a bone list there are no eyes to hide weapons with.

The price of the contacts: the legs and arms point up to about 13° away from the source's, and where the spine bone counts differ, a bend within one target spine bone is lost. Weapons sit in the hand as with *Bone by bone*. On FromSoftware pairs such as Owl or Isshin onto Wolf, whose skeletons match bone for bone, both methods give nearly the same result, and *Bone by bone* stays the better choice. The full-body bake is meant for rigs of other bone counts and proportions; check its result before you export it.

### Body figures

3ds Max's Biped retargets through a figure: a simple stand-in body that you fit to each character once. **1. Choose rigs** > **Body figures** does the same. A figure measures the character; it is not a control rig. It is never animated and never constrained, and the bake still moves the real bones.

1. Choose the source and the target in **1. Choose rigs**, then open **Body figures**.
2. Click **Create figure** under the rig. A stick figure appears in front of the rig and Blender switches to Edit Mode. The figure is fitted to the rest pose, so the rig switches to its **Rest Position** while the figure is open; baking and exporting wait until you save or close it. Its parts carry Biped's names (*Pelvis*, *Spine*, *Neck*, *Head*, and per side *Clavicle*, *UpperArm*, *Forearm*, *Hand*, *Thigh*, *Calf*, *Foot*, *Toe* and *Heel*), and each sits where the add-on finds that part of the body in the skeleton and meshes.
3. Check the ends that the skeleton alone cannot show. Click a part's end and press G to move it: the *Head*'s tip to the top of the head or helmet, each *Heel* to the back of the heel on the ground, each *Toe*'s tip to the tip of the foot, each *Thigh*'s start to the hip joint. Only where the parts start and end counts, not how they are rotated or rolled, so there is no need to rotate a part.
4. With a part selected, the panel shows the skeleton bone it stands for. Choose another bone there if the add-on picked the wrong one.
5. Click **Save figure**. The figure is kept on the rig and as a file in the figure folder (**Edit** > **Preferences** > **Add-ons** > Sekiro Retarget Assistant > **Figure folder**), one file per skeleton, so every other scene and clip with the same skeleton finds it. Saving closes the figure, and the rig shows its pose again. The close button removes the figure without saving, **Edit figure** opens the saved figure again, and **Delete saved figure** deletes it.

The full-body bake then takes from the saved figure which bones are the hips, spine, neck, head, arms and legs, and it measures the leg length, the hip joints, the height, the limbs and the feet on it. Without a saved figure it uses the automatic one, which **Create figure** would make, so the bake works as before. **Use saved figures** turns them off for a bake.

### Feet, jumps and props (Biped)

Under **3. Bake motion onto target** > **Feet, jumps and props (Biped)**, all off by default:

- **Foot contacts** > *Planted, sliding, free (Biped)* finds footsteps the way Biped does from motion capture, with the full-body bake. A foot is planted where its heel, ankle, ball or toe tip stays on the ground and within **Plant tolerance** (in lengths of the source's foot; Biped's default 0.15) for at least 0.1 s. That point of the target's own foot then stands still, so the foot can roll from heel to toe without sliding. A foot that moves along the ground slides, keeping the source's path and staying on the target's ground. It is free in the air. Where the target holds its foot at another angle than the source, the foot stands as high as its lowest point needs, so no part of it goes into the ground. The status lists each foot's planted and sliding steps and the points it stood on. *Slow feet stand*, the default, keeps the earlier behavior: a foot stands where it moves slower than a quarter leg length per second.
- **Scale jumps by height**: Biped scales gravity with the figure's height. Where both feet are off the ground, the body rises above the line from lift-off to touchdown as far as the target's height against the source's, instead of by leg length; the time in the air stays the same. The status gives each jump's frames and rise.
- **Moving props** places bones outside the body whose source bones move away from their parents, such as a thrown weapon. *By height* moves the bone from the nearest mapped bone above it as far as the source's, scaled by the two heights; *By limb size* scales by the limb that carries it (arm, leg, torso, or leg length for a bone above the hips). *Keep target place*, the default, keeps them on their parents as before. This works with both bake methods.

## Export

**Export HKX** follows the same path as the bridge's export page. Blender samples the evaluated pose with the bridge's own exporter, so constraints, drivers and NLA tracks are baked. The bridge's conversion Python then writes the HKX with its Havok compatibility fixes and, with **Read back and compare**, decodes it again and reports the largest difference. **Output** and **Replace existing**, which writes over an existing `.hkx` and its sidecar, stay in step 4; the rest is under **Export settings**:

- **Game.** *Stored in scene* uses the game recorded at import (bridge 0.5 and later). Older scenes need the game chosen here.
- **Format.** *Interleaved* stores every frame exactly. *Spline* compresses like the game's own clips, within the position **Tolerance** and with the chosen rotation precision.
- **Tracks.** *Original clip tracks* keeps the track list of the clip the target was imported from; *Original tracks + keyed bones* adds bones keyed in the action; *Every skeleton bone* writes all of them.
- **Frames.** The scene range (set by the bake), the action's key range, or the clip's frame count.
- **Root motion.** *As baked* writes the target's root-motion object; *None* writes no root motion.

### Add to animation binder

**Add to animation binder**, in step 4 under **Replace existing**, also puts the written HKX into an animation binder (`.anibnd.dcx`), so no binder tool is needed:

- **Binder** starts as the archive the clip came from, as the bridge recorded it at import (bridge 0.13 and later; choose it for older scenes). The game's own files are protected: when that archive is in the game folder, **Binder** names a copy of it beside the **Output** HKX instead. The first export makes that copy from the game's archive; later exports change the copy. Put the copy into your mod's `chr` folder.
- **Name in binder** starts empty, which uses the clip's own name (the panel shows it under the field, such as *Uses a050_002000.hkx*). That replaces the original clip. Another name of the form `aXXX_YYYYYY.hkx` adds a new clip with the ID that the binder's clips follow; the game plays it only once a TAE entry of that animation ID points at it, and the **Log** says so.
- Before its first change the binder is kept as `.bak` beside it. The other members stay byte for byte as they were.

## Control rig

An imported rig has one short bone per game bone, each oriented however the game stores it, which is awkward to animate by hand. The **Control rig** panel, in the **Animate** tab, adds animator controls to it:

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

**Mirror animation**, under the armature's name in the **Animate** tab's **Animation** panel, makes a left-right mirrored copy of the armature's action, so that a right-handed slash becomes a left-handed one. Select the armature, or let the panel use the scene's bridge rig, and click it. The copy, "*clip* Mirrored", plays at once with its root motion, "*clip* Mirrored RootMotion"; the original action and root motion are kept. Export the copy like any other action: **Export HKX** writes the active action, and the bridge's export page and CLI can choose it by name and pair its root motion by that name. Mirroring the copy gives the original back.

The mirror runs across the character's middle plane:

- A bone with a counterpart on the other side takes its counterpart's motion, reflected: `L_Hand` does what `R_Hand` did. Bones pair by name, and bones whose names give no side, such as cloth on either hip, where one rests at the other's mirrored place, as in a rig that its maker mirrored. FromSoftware's left and right bones rest half a turn from mirror images of each other, which is why Blender's *Paste Flipped Pose* turns them wrong; the mirror reads each pair's rest frames instead.
- A bone on the middle line, such as the spine, reflects its own motion, so the body leans and turns the other way. Root motion reflects too: sideways travel and turns change sign.
- Gear changes sides with the motion. The katana that the right hand swings goes into the left hand with the swing, whether the game hangs it on `R_Weapon` or the character's mesh holds it, and a scabbard on the left hip goes to the right hip. Gear is a weapon, sheath or shield bone, together with the bones without a counterpart between it and the body, such as a cord around a hilt. It goes where the reflection puts it, and the bones below it mirror across the piece's own middle plane, so that a symmetric piece keeps its shape, and a pair on it, such as the eyes of a head held as a weapon, swaps. A weapon that the bridge hangs on a bone, as Wolf's katana on `R_Weapon`, is reflected so that its model maps onto itself, so the mirrored katana strikes with its edge. The bone's exported motion carries this, so the game, which hangs the sword on that bone, shows it as Blender does.
- Gear keeps its side where its mesh bends together with the body, as Wolf's scabbard is part of his clothes, and where it is stored on the body without a mesh of its own, as the hip and back cases where the game hangs sheathed weapons. The status lists such gear.
- Another bone without a counterpart keeps its own motion and goes along where a bone with a counterpart carries it, as the cloth of a sleeve; elsewhere, as a sash on one hip, it stays on its side and reflects its own motion. The status lists the ones that move.
- HKX tracks belong to bones, so the copy has the same tracks, each with its bone's new motion. A custom property that the clip keys on a bone moves to the bone's counterpart.

With a control rig on the armature, the game bones follow the controls, so the button is greyed out: remove the control rig, keeping the edited motion, mirror, and add the control rig again. Mute the armature's NLA tracks first, if it has any. Constraints are not mirrored; the status names the bones they still act on.

On an owned test rig whose left and right bones rest at random turns, the mirrored clip was the exact reflection of the original, mirroring twice gave the original back, and the export read back as the mirrored clip. On clips of Isshin, Wolf and c5100, the mirror took under 1.4 s and the export read back within 0.000°. The mirror swaps motion, not meshes: an uneven costume, such as Wolf's prosthetic arm, stays on its side, and a pair whose rests are not mirror images keeps its rest places.

## Join animations

**Join animations**, in the **Animate** tab under **Animation**, makes one clip that plays the armature's own animation and then another one, such as an attack followed by its recovery, so the game plays both as one animation. The root motion goes on from where the first clip leaves the character, so the second clip does not jump back to the start.

1. Open the bridge `.blend` with the first animation. Open the **Animate** tab; the **Animation** panel names the armature and its action. Select the armature if the panel shows another one.
2. Under **Join animations** > **Then**, choose the second animation. To take it from another bridge scene of the same skeleton, click the folder button beside the field and choose that scene's `.blend`. **Load clip from .blend** brings in its animations and root motion, without its objects, and sets **Then** to its animation.
3. Set **Blend**: how long, in seconds, the end of the first animation and the start of the second play at once, the pose easing from one to the other. 0.2 s is the default; 0 cuts from one to the other on the frame after the first ends.
4. Click **Join animations**. The new action, "*first* + *second*", plays at once with its root motion, "*first* + *second* RootMotion", and the scene's frame range becomes its range. Both originals are kept.
5. Export it like any other action, for example with **Export HKX** in the **Retarget** tab.

The blend shortens the clip: with 0.2 s at 30 fps, the second clip starts 6 frames before the first ends. A second clip keyed at another frame rate plays at its own speed, and the **Log** says so. Bones that only the second clip keys are joined too; the **Log** names any that are no track of the original clip, so export them with **Tracks** > *Original tracks + keyed bones*. With a control rig on the armature, the button is greyed out: remove the control rig, keeping the edited motion, join, and add the control rig again. Mute the armature's NLA tracks first, if it has any.

On owned test clips, frames outside the blend matched each clip's pose exactly, the blend eased from one to the other, and the root moved on without a jump.

## Current scope

The retarget bake transfers humanoid FK animation. It aligns held weapons and holds them by a grip, puts the second hand on a two-handed weapon, keeps hands out of the torso and keeps arms as close to the body as the source's, but bone by bone it does not solve foot contacts, a hand reaching for anything else, cloth or facial animation. The experimental full-body bake keeps planted feet and hands that meet each other, at the cost of the limbs' directions; it does not handle toes, the ground or other contacts. The control rig's [fixes](#fixes) keep the second hand where you put it on the grip, a weapon in its sheath and the feet on the ground over the frames you choose, and its IK limbs and swivel rings help with the rest by hand. Different proportions can still need pose cleanup. Non-humanoid rigs need manual mapping and review.

Mapped target bones must have no active constraints, and target NLA tracks must be muted. The bake adds no live constraints or handlers; the control rig adds constraints and drivers to its armature, and **Remove control rig** takes them away again. The fixes add keys only. Source timing can change the clip's duration; TAE events are not retimed. In-game playback of a retargeted clip has not been verified.

**Mirror animation** mirrors the bones and the root motion only: TAE events, such as a hand an effect comes from, and weapon part clips stay as they are. A weapon that Wolf's TAE event 715 moves to another dummy, such as the katana into its sheath, keeps its side there, as do the sheath and the prosthetic tools. In the game, a blend from a mirrored clip into an unmirrored one moves the weapons across the body. In-game playback of a mirrored clip has not been verified.

**Join animations** joins the bones and the root motion only. The joined clip keeps the TAE events of the animation ID it is exported as, which were made for the first clip alone: the events of the second clip, such as its attack hits and sounds, need TAE entries added at their new times. In-game playback of a joined clip, and of a clip that **Add to animation binder** added under a new name, has not been verified.
