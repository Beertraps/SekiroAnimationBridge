"""Fixes of the control rig on an owned synthetic bridge rig. Run with Blender --background --factory-startup --python this_file.py.

A FromSoftware-style skeleton with turned rest frames, a weapon bone in each
hand, a mesh on the right one and a sheath at the hip is imported through the
bridge with a clip in which the body turns and travels with root motion. With
the control rig added and every limb in IK:

- Hand on weapon keeps the left IK control where it was posed relative to
  R_Weapon on every frame of its range, eases in and out over the blend frames
  and leaves the frames beyond them unchanged.
- Plant foot keeps the left foot still in the game's world, where root motion
  carries the character.
- Weapon into sheath slides R_Weapon from one posed relation to the sheath to
  another, also while the weapon is shrunk to 0.1% as clips hide weapons.
- Adjust over frames spreads two posed changes of the left hand, measured from
  the clavicle, and a selected FK control's change in its own channels.
- An adjustment that finds no change keeps the pose on the screen and says what
  to do: key the weapon control, which has no location or rotation keys, so a
  pose of it holds on every frame, or include a posed control that the limb
  does not read. Keyed once, Selected controls spreads the weapon's change.
- The reports name out-of-reach frames and frames that are not in IK, and the
  fixes refuse a target that moves with the limb, a posed frame outside the
  range and a pose that matches the animation.
- The Fixes panel draws every task with properties, operators and icons that
  exist; export carries the fixes, and removing the control rig keeps them.
"""
import json
import math
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import bl_to_game_trs, export_motion, import_motion
import sekiro_retarget
from sekiro_retarget import control_rig, fixes, retarget

COUNT, RATE = 60, 30
LIMBS = (('L', 'upperarm', 'forearm', 'hand'), ('R', 'upperarm', 'forearm', 'hand'),
         ('L', 'thigh', 'calf', 'foot'), ('R', 'thigh', 'calf', 'foot'))


def turned_rest(bones, seed):
    """Rest matrices at the given heads with randomly turned frames, as game skeletons store them."""
    rng = random.Random(seed)
    rest = {}
    for name, parent, head, label in bones:
        axis = Vector([rng.uniform(-1, 1) for _ in range(3)]).normalized()
        rest[name] = Matrix.LocRotScale(Vector(head), Quaternion(axis, rng.uniform(-math.pi, math.pi)), None)
    return rest


def pose(bones, rest, turns, travel=None):
    """Armature-space matrices with each bone turned in world space by turns[name] after its parent."""
    deltas, result = {}, {}
    for name, parent, head, label in bones:
        deltas[name] = (deltas[parent] if parent else Quaternion()) @ turns.get(name, Quaternion())
        if parent:
            position = result[parent] @ (rest[parent].inverted() @ rest[name]).translation
        else:
            position = rest[name].translation.copy()
        if travel and name in travel:
            position += travel[name]
        result[name] = Matrix.LocRotScale(position, deltas[name] @ rest[name].to_quaternion(), None)
    return result


def motion(bones, rest, poses, tracked):
    """Bridge motion JSON for a skeleton with these rest matrices and armature-space poses, with root motion that
    travels and turns."""
    index = {bone[0]: i for i, bone in enumerate(bones)}

    def local(matrices, name, parent):
        return matrices[parent].inverted() @ matrices[name] if parent else matrices[name]
    skeleton = [dict(index=i, name=name, parent=index[parent] if parent else -1,
                     **bl_to_game_trs(*local(rest, name, parent).decompose()))
                for i, (name, parent, head, label) in enumerate(bones)]
    tracks = [index[name] for name in tracked]
    frames = [[bl_to_game_trs(*local(p, bones[i][0], bones[i][1]).decompose()) for i in tracks] for p in poses]
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip='a000_003000.hkx', skeletonName='Owned', game='sekiro',
                skeleton=dict(name='Owned', boneCount=len(skeleton), bones=skeleton), frameCount=len(poses), frameRate=RATE,
                duration=(len(poses) - 1) / RATE, trackCount=len(tracks), trackBoneIndices=tracks,
                trackNames=[bones[i][0] for i in tracks], frames=frames,
                rootMotion=[[.02 * f, 0, .03 * f, .01 * f] for f in range(len(poses))], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


def humanoid():
    bones = humanoids.fromsoftware(45, 'elden') + [('Sheath', 'Pelvis', (-.16, -.12, .98), None)]
    rest = turned_rest(bones, 11)
    name = {label: bone for bone, parent, head, label in bones if label}
    hinge = {}
    for side, upper, lower, end in LIMBS:
        s, e, w = (rest[name[f'{side}.{role}']].translation for role in (upper, lower, end))
        hinge[f'{side}.{lower}'] = (e - s).cross(w - e).normalized()
    poses = []
    for f in range(COUNT):
        w = 2 * math.pi * f / (COUNT - 1)
        turns = {
            'hips': Quaternion((0, 0, 1), .5 * math.sin(w)), 'spine.first': Quaternion((1, 0, 0), .2 * math.sin(w)),
            'spine.mid': Quaternion((0, 1, 0), .1 * math.sin(2 * w)), 'head': Quaternion((0, 0, 1), .3 * math.sin(w)),
            'L.upperarm': Quaternion(Vector((.3, 1, .2)).normalized(), -.4 * math.sin(w)),
            'L.forearm': Quaternion(hinge['L.forearm'], .4 + .5 * math.sin(w) ** 2),
            'L.hand': Quaternion(Vector((1, .5, .3)).normalized(), .4 * math.sin(w)),
            'R.upperarm': Quaternion((1, 0, 0), .4 * math.sin(w)),
            'R.forearm': Quaternion(hinge['R.forearm'], .5 + .4 * math.sin(w) ** 2),
            'R.hand': Quaternion((0, 1, 0), -.3 * math.sin(w)),
            'L.thigh': Quaternion((1, 0, 0), .5 * math.sin(w)), 'L.calf': Quaternion(hinge['L.calf'], .2 + .8 * math.sin(w) ** 2),
            'L.foot': Quaternion((1, 0, 0), .2 * math.sin(w)),
            'R.thigh': Quaternion((1, 0, 0), -.5 * math.sin(w)), 'R.calf': Quaternion(hinge['R.calf'], .2 + .8 * math.cos(w / 2) ** 2)}
        turns = {name[label]: turn for label, turn in turns.items()}
        poses.append(pose(bones, rest, turns, {'RootPos': Vector((.05 * math.sin(w), -.1 * math.sin(w), .02 * math.sin(2 * w)))}))
    tracked = [bone for bone, parent, head, label in bones
               if label or bone in ('Master', 'RootPos', 'RootRotY', 'RootRotXZ', 'L_Weapon', 'R_Weapon', 'Sheath')]
    return bones, motion(bones, rest, poses, tracked)


def evaluate(rig, names, frames=range(1, COUNT + 1)):
    scene = bpy.context.scene
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = dict({name: rig.pose.bones[name].matrix.copy() for name in names}, rig=rig.matrix_world.copy())
    return result


def rigid(matrix):
    return Matrix.LocRotScale(matrix.translation, matrix.to_3x3().normalized().to_quaternion(), None)


def difference(a, b):
    """(distance, angle in degrees) between two matrices; atan2 of the half-angle sine stays exact for small angles."""
    turn = rigid(a).to_quaternion().rotation_difference(rigid(b).to_quaternion())
    return (a.translation - b.translation).length, math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0])))


def worst(pairs):
    distance = angle = 0.0
    for a, b in pairs:
        d, g = difference(a, b)
        distance, angle = max(distance, d), max(angle, g)
    return distance, angle


def mix(a, b, t):
    (la, ra, sa), (lb, rb, sb) = a.decompose(), b.decompose()
    if ra.dot(rb) < 0:
        rb.negate()
    return Matrix.LocRotScale(la.lerp(lb, t), ra.slerp(rb, t), None)


def weight(frame, start, end, blend):
    if start <= frame <= end:
        return 1.0
    distance = start - frame if frame < start else frame - end
    if distance > blend:
        return 0.0
    t = 1 - distance / (blend + 1)
    return t * t * (3 - 2 * t)


def unchanged(before, after, names, frames):
    error = worst((before[f][n], after[f][n]) for f in frames for n in names)
    assert error[0] < 1e-6 and error[1] < 1e-4, ('frames beyond the fix changed', error)
    return error


def reachable(after, limb, rig, frames):
    """Frames where the game hand or foot sits on its IK control, as it should wherever the limb reaches."""
    bones = rig.data.bones
    offset = bones[limb['control']].matrix_local.inverted() @ bones[limb['bones'][2]].matrix_local
    return [f for f in frames if ((after[f][limb['control']] @ offset).translation - after[f][limb['bones'][2]].translation).length < 5e-4]


ICONS = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())


class Layout:
    """Stands in for a panel's layout: each property, operator and icon it is asked to draw must exist."""
    def __init__(self, drawn):
        self.drawn = drawn

    def __getattr__(self, name):
        if name in ('row', 'column', 'box', 'grid_flow'):
            return lambda *args, **kwargs: Layout(self.drawn)
        raise AttributeError(name)

    def label(self, text='', icon='NONE'):
        assert icon in ICONS, icon
        self.drawn.append(text)

    def prop(self, data, name, icon='NONE', **kwargs):
        assert icon in ICONS, icon
        assert name in data.bl_rna.properties or name[2:-2] in data.keys(), ('no property', name)

    def prop_search(self, data, name, search_data, search_name, icon='NONE', **kwargs):
        assert icon in ICONS, icon
        assert name in data.bl_rna.properties and search_name in search_data.bl_rna.properties, (name, search_name)

    def operator(self, idname, icon='NONE', **kwargs):
        assert icon in ICONS, icon
        group, name = idname.split('.')
        return Settings(getattr(getattr(bpy.ops, group), name).get_rna_type().properties.keys())


class Settings:
    """Stands in for the properties of an operator button: only its own properties can be set."""
    def __init__(self, names):
        object.__setattr__(self, 'names', names)

    def __setattr__(self, name, value):
        assert name in self.names, ('no operator property', name)


def draw_fixes(rig):
    """The labels of the Fixes panel, drawn with a stand-in layout."""
    context = SimpleNamespace(scene=bpy.context.scene, region=SimpleNamespace(width=300), object=rig)
    assert sekiro_retarget.SKR_PT_fixes.poll(context)
    drawn = []
    sekiro_retarget.SKR_PT_fixes.draw(SimpleNamespace(layout=Layout(drawn)), context)
    return ' '.join(drawn)


def exported_difference(a, b, names=None):
    """(distance, degrees): the largest difference between two exported clips in the named tracks, or in all."""
    clips = [json.loads(Path(path).read_text(encoding='utf-8')) for path in (a, b)]
    distance = angle = 0.0
    for name in names or clips[0]['trackNames']:
        tracks = [[frame[clip['trackNames'].index(name)] for frame in clip['frames']] for clip in clips]
        for x, y in zip(*tracks):
            distance = max(distance, (Vector(x['translation']) - Vector(y['translation'])).length)
            turn = Quaternion(x['rotation'][3:] + x['rotation'][:3]).rotation_difference(Quaternion(y['rotation'][3:] + y['rotation'][:3]))
            angle = max(angle, math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0]))))
    return distance, angle


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sekiro_retarget.register()
    scene = bpy.context.scene
    bones, clip = humanoid()
    rig = import_motion(clip)
    # A weapon mesh on the right weapon bone, as the bridge attaches weapons, so the defaults find the shown weapon.
    blade = bpy.data.objects.new('Blade', bpy.data.meshes.new('Blade'))
    blade.data.from_pydata([(0, 0, 0), (.8, 0, 0), (.8, .02, 0)], [], [(0, 1, 2)])
    scene.collection.objects.link(blade)
    blade.parent, blade.parent_type, blade.parent_bone = rig, 'BONE', 'R_Weapon'
    root = retarget.root_object(rig)
    assert root is not None and root.animation_data and root.animation_data.action, 'the clip should have root motion'

    control_rig.add(bpy.context, rig)
    data = control_rig.layout(rig)
    limbs = {limb['label']: limb for limb in data['limbs']}
    for limb in data['limbs']:
        rig.pose.bones[limb['control']][control_rig.SWITCH] = 1.0
    rig.update_tag()
    work = Path(tempfile.mkdtemp(prefix='FixesTest-'))
    export_motion(work / 'clip.motion.json')
    left_arm, right_arm, left_leg = limbs['Left arm'], limbs['Right arm'], limbs['Left leg']
    hand, foot, right = left_arm['control'], left_leg['control'], right_arm['control']
    body = rig.data.bones[left_arm['bones'][0]].parent.name  # The bone an adjustment of the left arm measures from.
    names = sorted({hand, foot, right, left_arm['pole'], body, 'R_Weapon', 'Sheath', 'L_Hand', 'R_Hand', 'L_Foot', 'Head'})
    fix = scene.sekiro_fix

    # Defaults: the second hand follows the shown weapon in the other hand; the sheath takes the hand holding it.
    fix.task = 'PLANT'
    assert fix.limb == str(data['limbs'].index(left_leg)), fix.limb
    fix.task = 'SHEATH'
    assert (fix.limb, fix.held, fix.target) == (str(data['limbs'].index(right_arm)), 'R_Weapon', 'Sheath'), (fix.limb, fix.held, fix.target)
    fix.task = 'HAND'
    assert (fix.limb, fix.target, fix.span) == (str(data['limbs'].index(left_arm)), 'R_Weapon', 'CLIP'), (fix.limb, fix.target, fix.span)
    for task, *_ in fixes.TASKS:
        fix.task = task
        drawn = draw_fixes(rig)
        assert 'not in IK' not in drawn and 'Posed frames' not in drawn, drawn
    fix.task = 'HAND'

    # Hand on weapon, through the operator: pose the left hand 3 cm along the weapon on frame 15 without keying it.
    before = evaluate(rig, names)
    scene.frame_set(15)
    weapon = rigid(rig.pose.bones['R_Weapon'].matrix)
    control = rig.pose.bones[hand]
    control.matrix = weapon @ Matrix.Translation((.03, 0, 0)) @ weapon.inverted() @ control.matrix
    bpy.context.view_layer.update()
    posed = control.matrix.copy()
    grip = weapon.inverted() @ posed
    fix.span, fix.frame_start, fix.frame_end, fix.blend = 'RANGE', 12, 18, .2
    assert bpy.ops.sekiro_retarget.fix_apply() == {'FINISHED'}, fix.status
    assert 'Left arm follows R_Weapon on frames 12–18' in fix.status and not fix.poses, fix.status
    after = evaluate(rig, names)
    held = worst((rigid(after[f]['R_Weapon']).inverted() @ after[f][hand], grip) for f in range(12, 19))
    assert held[0] < 1e-5 and held[1] < 1e-3, ('the hand should keep its grip on the weapon', held)
    eased = 0.0
    for f in range(6, 12):
        w = weight(f, 12, 18, 6)
        here = rigid(before[f]['R_Weapon'])
        expected = here @ mix(here.inverted() @ before[f][hand], grip, w)
        eased = max(eased, *difference(after[f][hand], expected))
        assert 0 < w < 1
    assert eased < 1e-4, ('the blend frames should ease between the clip and the grip', eased)
    hand_unchanged = unchanged(before, after, [hand, 'L_Hand', 'R_Hand', foot], [f for f in range(1, COUNT + 1) if not 6 <= f <= 24])
    reached = reachable(after, left_arm, rig, range(12, 19))
    assert len(reached) == 7, ('the left hand should reach the grip on every frame', sorted(set(range(12, 19)) - set(reached)))
    hand_error = worst((rigid(after[f]['R_Weapon']).inverted() @ after[f]['L_Hand'],
                        rigid(after[15]['R_Weapon']).inverted() @ after[15]['L_Hand']) for f in reached)
    assert hand_error[0] < 1e-4 and hand_error[1] < .01, ('the game hand should follow the weapon', hand_error)

    # Plant foot with root motion: the foot stays still where root motion carries the character.
    before = after
    fix.task = 'PLANT'
    fix.frame_start, fix.frame_end, fix.blend = 20, 30, 0
    scene.frame_set(25)
    assert bpy.ops.sekiro_retarget.fix_apply() == {'FINISHED'}, fix.status
    assert 'stays still in the game' in fix.status, fix.status
    after = evaluate(rig, names)

    def game(frame, matrix):
        """Where the game shows an armature-space matrix: export writes the root object as the character's place."""
        bpy.context.scene.frame_set(frame)
        return root.matrix_world @ matrix
    planted = worst((game(f, after[f][foot]), game(25, after[25][foot])) for f in range(20, 31))
    assert planted[0] < 1e-5 and planted[1] < 1e-3, ('the planted foot should stay still in the game', planted)
    travel = max((game(f, before[f][foot]).translation - game(25, before[25][foot]).translation).length for f in range(20, 31))
    assert travel > .05, ('the foot should have slid before the fix', travel)
    unchanged(before, after, [foot, hand], [f for f in range(1, COUNT + 1) if not 19 <= f <= 31])

    # Weapon into sheath, posed on two frames through Use this pose, while the weapon shrinks to 0.1% on frames 48-52.
    weapon_control = rig.pose.bones[data['fk']['R_Weapon']]
    for f in range(46, 55):
        weapon_control.scale = (.001,) * 3 if 48 <= f <= 52 else (1, 1, 1)
        weapon_control.keyframe_insert('scale', frame=f)
    before = evaluate(rig, names)
    fix.task = 'SHEATH'
    fix.frame_start, fix.frame_end, fix.blend = 44, 50, 0
    scene.frame_set(44)
    assert bpy.ops.sekiro_retarget.fix_pose() == {'FINISHED'}
    assert 'Posed frames: 44' in draw_fixes(rig)
    sheath = rigid(rig.pose.bones['Sheath'].matrix)
    first = sheath.inverted() @ rigid(rig.pose.bones['R_Weapon'].matrix)
    scene.frame_set(50)
    sheath, weapon = rigid(rig.pose.bones['Sheath'].matrix), rigid(rig.pose.bones['R_Weapon'].matrix)
    control = rig.pose.bones[right]
    control.matrix = sheath @ first @ Matrix.Translation((-.06, 0, 0)) @ weapon.inverted() @ control.matrix
    bpy.context.view_layer.update()
    kept = control.matrix.copy()
    # The relation as the pose shows it, where the arm's IK reaches its control within a few hundredths of a millimetre.
    last = rigid(rig.pose.bones['Sheath'].matrix).inverted() @ rigid(rig.pose.bones['R_Weapon'].matrix)
    assert bpy.ops.sekiro_retarget.fix_pose() == {'FINISHED'}
    assert difference(control.matrix, kept)[0] < 1e-9, 'Use this pose should keep the pose on the screen'
    assert sorted({p.frame for p in fix.poses}) == [44, 50] and {p.bone for p in fix.poses} == {right, 'R_Weapon'}
    scene.frame_set(47)  # Apply on a frame that is not posed uses the posed frames alone.
    assert bpy.ops.sekiro_retarget.fix_apply() == {'FINISHED'}, fix.status
    assert 'Right arm keeps R_Weapon on Sheath on frames 44–50' in fix.status, fix.status
    after = evaluate(rig, names)
    slid = []
    for f in reachable(after, right_arm, rig, range(44, 51)):
        relation = rigid(after[f]['Sheath']).inverted() @ rigid(after[f]['R_Weapon'])
        slid.append((relation, mix(first, last, (f - 44) / 6)))
    assert len(slid) == 7, ('the right hand should reach the sheath on every frame', len(slid))
    sliding = worst(slid)
    assert sliding[0] < 1e-4 and sliding[1] < .01, ('the weapon should slide along the sheath', sliding)
    assert after[49]['R_Weapon'].to_scale().length < .01, 'the weapon should stay hidden on frame 49'
    unchanged(before, after, [right, 'R_Weapon'], [f for f in range(1, COUNT + 1) if not 43 <= f <= 51])

    # Adjust over frames: two posed changes of the left hand, measured from the clavicle, spread over frames 28-38.
    before = evaluate(rig, names)
    fix.task = 'ADJUST'
    fix.limb = str(data['limbs'].index(left_arm))
    fix.frame_start, fix.frame_end, fix.blend = 28, 38, .1
    changes = {30: Matrix.LocRotScale(Vector((.04, 0, 0)), Quaternion((0, 0, 1), math.radians(10)), None),
               36: Matrix.LocRotScale(Vector((0, .03, .02)), Quaternion((1, 0, 0), math.radians(5)), None)}
    for f, change in changes.items():
        scene.frame_set(f)
        clavicle = rigid(rig.pose.bones[body].matrix)
        location, rotation, scale = (clavicle.inverted() @ rig.pose.bones[hand].matrix).decompose()
        rig.pose.bones[hand].matrix = clavicle @ Matrix.LocRotScale(location + change.translation, rotation @ change.to_quaternion(), scale)
        bpy.context.view_layer.update()
        if f == 30:  # Apply takes the pose on frame 36 itself, where the hand is posed away from its keys.
            assert bpy.ops.sekiro_retarget.fix_pose() == {'FINISHED'}
    assert bpy.ops.sekiro_retarget.fix_apply() == {'FINISHED'}, fix.status
    assert 'Spread the posed change of IK-L_Hand over frames 28–38' in fix.status, fix.status
    after = evaluate(rig, names)
    spread = []
    for f in range(25, 42):
        w = weight(f, 28, 38, 3)
        expected = changes[30] if f <= 30 else changes[36] if f >= 36 else mix(changes[30], changes[36], (f - 30) / 6)
        expected = mix(Matrix(), expected, w)
        old = (rigid(before[f][body]).inverted() @ before[f][hand]).decompose()
        new = (rigid(after[f][body]).inverted() @ after[f][hand]).decompose()
        spread.append((Matrix.LocRotScale(new[0] - old[0], old[1].inverted() @ new[1], None), expected))
    adjusted = worst(spread)
    assert adjusted[0] < 1e-5 and adjusted[1] < 1e-3, ('the change should spread from the clavicle', adjusted)
    unchanged(before, after, [hand, left_arm['pole']], [f for f in range(1, COUNT + 1) if not 24 <= f <= 42])

    # Adjust a selected FK control in its own channels over the whole clip.
    head_control = data['fk']['Head']
    before = evaluate(rig, names + [head_control])
    head = rig.pose.bones[head_control]
    scene.frame_set(12)
    turn = Quaternion((0, 0, 1), math.radians(15))
    head.rotation_quaternion = head.rotation_quaternion @ turn
    bpy.context.view_layer.update()
    report = fixes.run(bpy.context, rig, 'ADJUST', None, (1, COUNT), 0, selected=[head_control, 'Head'])
    assert report['controls'] == [head_control], report['controls']
    after = evaluate(rig, names + [head_control])
    # The control turns in its own frame on every frame, so its armature matrix gains the turn on the right.
    head_error = worst((after[f][head_control], before[f][head_control] @ turn.to_matrix().to_4x4()) for f in range(1, COUNT + 1))
    assert head_error[0] < 1e-5 and head_error[1] < 1e-3, ('the head control should turn by its posed change', head_error)

    # The weapon sits still in the hand, so its control has no location or rotation keys and a pose of it holds on
    # every frame. Adjusting the right arm with it posed is refused with how to change only some frames. Keyed once,
    # the arm's refusal names it as posed and keeps the pose on the screen, and Selected controls spreads its change.
    weapon_name = weapon_control.name
    assert fixes._still(rig, weapon_name), 'the weapon control should have no location or rotation keys'
    fix.limb, fix.span = str(data['limbs'].index(right_arm)), 'CLIP'
    for bone in rig.data.bones:
        bone.select = False
    rig.data.bones.active = rig.data.bones[weapon_name]
    scene.frame_set(1)
    location, rotation = weapon_control.location.copy(), weapon_control.rotation_quaternion.copy()
    moved = Matrix.LocRotScale(location + Vector((.004, -.002, .003)), rotation @ Quaternion((0, 1, 0), math.radians(4)), None)

    def shown():
        return Matrix.LocRotScale(weapon_control.location, weapon_control.rotation_quaternion, None)

    def nudge():
        weapon_control.location, weapon_control.rotation_quaternion = moved.decompose()[:2]
        bpy.context.view_layer.update()
        return shown()

    def refused(words):
        try:
            bpy.ops.sekiro_retarget.fix_apply()
            raise AssertionError('Apply should refuse: ' + words)
        except RuntimeError as exc:
            assert words in str(exc) and words in fix.status, (exc, fix.status)

    posed = nudge()
    refused(f'{weapon_name} has no location or rotation keys, so moving or turning it changes every frame at once. To change '
            f'only some frames, undo the change (Ctrl+Z), select {weapon_name} and press I in the viewport to key it, then pose it '
            'again, set Limb to Selected controls and Apply.')
    scene.frame_set(20)
    assert max(difference(shown(), posed)) < 1e-7, 'the pose of a control without keys should hold on every frame'
    scene.frame_set(1)
    weapon_control.location, weapon_control.rotation_quaternion = location, rotation  # Undo, key once, pose again.
    weapon_control.keyframe_insert('location', frame=1)
    weapon_control.keyframe_insert('rotation_quaternion', frame=1)
    posed = nudge()
    refused(f'{weapon_name} is posed, but the right arm reads only these controls: set Limb to Selected controls, select it and Apply.')
    assert max(difference(shown(), posed)) < 1e-7, 'a refused Apply should keep the pose on the screen'
    report = fixes.run(bpy.context, rig, 'ADJUST', None, (1, COUNT), 0, selected=[weapon_name])
    assert report['controls'] == [weapon_name], report['controls']
    taken = []
    for f in range(1, COUNT + 1):
        scene.frame_set(f)
        taken.append((shown(), moved))
    weapon_error = worst(taken)
    assert weapon_error[0] < 1e-6 and weapon_error[1] < 1e-3, ('the weapon control should take its posed change', weapon_error)
    fix.span = 'RANGE'

    # Start and End take the current frame; clearing forgets the posed frames; a refused fix says why.
    fix.task = 'ADJUST'
    fix.limb = str(data['limbs'].index(left_arm))
    scene.frame_set(33)
    assert bpy.ops.sekiro_retarget.fix_frame(end=True) == {'FINISHED'} and fix.frame_end == 33
    assert bpy.ops.sekiro_retarget.fix_frame() == {'FINISHED'} and fix.frame_start == 33
    assert bpy.ops.sekiro_retarget.fix_pose() == {'FINISHED'} and {p.bone for p in fix.poses} == {hand, left_arm['pole'], left_arm['swivel']}
    assert bpy.ops.sekiro_retarget.fix_clear() == {'FINISHED'} and not fix.poses
    scene.tool_settings.use_keyframe_insert_auto = True
    assert 'Auto keying is on.' in draw_fixes(rig)
    scene.tool_settings.use_keyframe_insert_auto = False
    try:
        bpy.ops.sekiro_retarget.fix_apply()
        raise AssertionError('Apply should refuse a pose that matches the animation')
    except RuntimeError as exc:
        assert 'match the animation on frame 33' in str(exc) and 'turn auto keying off' in fix.status, (exc, fix.status)

    # Reports and refusals.
    scene.frame_set(5)
    far = fixes.run(bpy.context, rig, 'HAND', data['limbs'].index(left_arm), (1, COUNT), 0, target='R_Foot')
    assert far['short'] and 'Out of reach on frame' in far['message'], far['message']
    # The left leg eases from FK to IK over frames 6-8: the fix shows only in part where the leg is not fully in IK,
    # and a fix of frames that are all in FK is refused, as Switch to IK would undo it.
    leg = rig.pose.bones[foot]
    for frame, value in ((6, 0.0), (8, 1.0)):
        leg[control_rig.SWITCH] = value
        leg.keyframe_insert(f'["{control_rig.SWITCH}"]', frame=frame)
    partial = fixes.run(bpy.context, rig, 'PLANT', data['limbs'].index(left_leg), (5, 9), 0)
    assert partial['partial'] == [5, 6, 7] and 'not fully in IK' in partial['message'], partial['message']
    fix.task = 'PLANT'
    try:
        bpy.ops.sekiro_retarget.fix_pose()
        raise AssertionError('Use this pose should refuse a limb in FK')
    except RuntimeError as exc:
        assert 'in FK on frame 5' in str(exc), exc
    for call, words in ((lambda: fixes.run(bpy.context, rig, 'PLANT', data['limbs'].index(left_leg), (1, 6), 0),
                         'Click Switch to IK first'),
                        (lambda: fixes.run(bpy.context, rig, 'HAND', data['limbs'].index(left_arm), (1, COUNT), 0, target='L_Weapon'),
                         'moves with the left arm'),
                        (lambda: fixes.run(bpy.context, rig, 'HAND', data['limbs'].index(left_arm), (20, 30), 0, target='R_Weapon'),
                         'outside frames 20–30'),
                        (lambda: fixes.run(bpy.context, rig, 'ADJUST', data['limbs'].index(left_arm), (1, COUNT), 0),
                         'match the animation')):
        try:
            call()
            raise AssertionError('the fix should refuse: ' + words)
        except ValueError as exc:
            assert words in str(exc), exc
    assert not [c for b in rig.pose.bones for c in b.constraints if c.type == 'CHILD_OF'], 'the fixes add no constraints'
    assert 'Left leg is not in IK here.' in draw_fixes(rig)

    # Export carries the fixes, and removing the control rig keeps them on the game bones.
    export_motion(work / 'fixed.motion.json')
    exported = exported_difference(work / 'clip.motion.json', work / 'fixed.motion.json', left_arm['bones'])[1]
    assert exported > 5, ('the export should carry the fixed left arm', exported)
    game_bones = [bone.name for bone in rig.data.bones if not control_rig.is_control(bone)]
    edited = evaluate(rig, game_bones)
    control_rig.remove(bpy.context, rig, keep_edits=True)
    assert not control_rig.present(rig)
    kept = worst((edited[f][n], m) for f, matrices in evaluate(rig, game_bones).items() for n, m in matrices.items() if n != 'rig')
    # With the legs in IK, removal bakes this rig's toes within 0.01 mm also without any fix.
    assert kept[0] < 2e-5 and kept[1] < .01, ('removal changed the fixed motion', kept)
    export_motion(work / 'removed.motion.json')
    removed = exported_difference(work / 'fixed.motion.json', work / 'removed.motion.json')
    assert removed[0] < 2e-5 and removed[1] < .005, ('the export after removal should match the one with the control rig', removed)

    print(f'Hand on weapon: grip kept within {held[0]:.1e} m / {held[1]:.1e} deg on frames 12-18, game hand {hand_error[0]:.1e} m, '
          f'blend {eased:.1e}, beyond {hand_unchanged[0]:.1e} m')
    print(f'Plant foot: {planted[0]:.1e} m in the game world, where it slid {travel:.3f} m before')
    print(f'Weapon into sheath: slid within {sliding[0]:.1e} m / {sliding[1]:.1e} deg, hidden on frames 48-52')
    print(f'Adjust: limb change within {adjusted[0]:.1e} m / {adjusted[1]:.1e} deg, FK change within {head_error[0]:.1e} m / {head_error[1]:.1e} deg')
    print(f'Refused adjust: kept the pose and named the unkeyed weapon control, then the posed one; keyed once, '
          f'it took its change within {weapon_error[0]:.1e} m / {weapon_error[1]:.1e} deg')
    print(f'Export: the left arm turned up to {exported:.0f} deg; removal kept the fixes within {kept[0]:.1e} m / {kept[1]:.1e} deg, '
          f'export within {removed[0]:.1e} m / {removed[1]:.1e} deg')
    print('Fixes check passed')


main()
