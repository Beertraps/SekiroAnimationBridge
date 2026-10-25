"""Fixes for animating with the control rig: keep a hand or foot on something, or spread a correction over frames.

A retarget often leaves cleanup that takes many steps in Blender: the second
hand of a two-handed grip ends off the hilt, a sheathing sword misses the
sheath, a foot slides, an arm stands wide for a stretch of frames. Each fix
keys the controls over a range of frames and eases in and out over blend
frames on each side, so the frames around the range change smoothly and the
frames beyond it keep their keys.

Two operations do the work:

- follow(): a limb's IK control keeps where it is relative to a target, as on
  the frames where it was posed. The target is a bone, or the world in which
  the game moves the character, which root motion carries. Between posed
  frames the relation is interpolated in the target's space, and over the
  blend frames the control eases between the animation and that relation, so
  a sword that slides into its sheath slides along it. With held, the hand
  moves so that the bone it holds, rather than the hand, keeps the relation.
- adjust(): the change from the animation to the posed controls spreads over
  the frames. An IK control or pole measures it from the bone above its limb,
  so the change turns with the body; any other control changes its own
  channels, as an additive layer would.

Neither adds constraints: the controls are keyed, so export and the control
rig's removal treat the result like any other keys.
"""
import bpy
from mathutils import Euler, Matrix, Quaternion
from . import control_rig, mapping, retarget

TASKS = [
    ('HAND', 'Hand on weapon', 'Keep a hand where you posed it on a weapon or another bone, '
     'such as the second hand of a two-handed grip on the hilt'),
    ('SHEATH', 'Weapon into sheath', 'Move a hand so that the weapon it holds keeps where you posed it on the sheath'),
    ('PLANT', 'Plant foot', 'Keep a foot where it stands on the posed frame, so it does not slide'),
    ('ADJUST', 'Adjust over frames', 'Spread the change you posed on one or more frames over a range of frames'),
]
HINTS = dict(
    HAND='Pose the hand on the grip, then click Apply fix. On the chosen frames it follows the weapon.',
    SHEATH='Pose the blade at the mouth of the sheath and click Use this pose, then pose it fully in on a later '
           'frame and click Apply fix. The blade slides along the sheath between them.',
    PLANT='Go to a frame where the foot stands right, then click Apply fix. On the chosen frames it stays there.',
    ADJUST='Pose the controls right on a frame, then click Apply fix. To pose several frames, click Use this pose '
           'before you go to the next.',
)
SELECTED = 'SELECTED'
KINDS = dict(HAND=('arm',), SHEATH=('arm',), PLANT=('leg',), ADJUST=('arm', 'leg'))
# Controls a fix can key; the sockets and IK chain bones only follow them.
KEYED = ('root', 'fk', 'ik', 'pole', 'swivel')
CHANNELS = ('location', 'rotation_quaternion', 'rotation_euler', 'rotation_axis_angle', 'scale')


def limbs(rig, task):
    """(index, limb) of the control rig's limbs that a task works on."""
    return [(index, limb) for index, limb in enumerate(control_rig.layout(rig)['limbs']) if limb['kind'] in KINDS[task]]


def held_weapon(rig, hand):
    """The weapon bone a hand holds, such as Sekiro's R_Weapon or an enemy's R_Katana; the nearest one first."""
    found = [bone for bone in rig.data.bones[hand].children_recursive
             if not control_rig.is_control(bone) and mapping.weapon_name(bone.name)]
    found.sort(key=lambda bone: (len(bone.parent_recursive), len(bone.name), bone.name))
    return found[0].name if found else ''


def sheaths(rig):
    """Bones that keep a weapon on the body, such as Wolf's Sheath; sheaths and scabbards before other storage."""
    hands = {limb['bones'][2] for limb in control_rig.layout(rig)['limbs'] if limb['kind'] == 'arm'}
    found = []
    for bone in rig.data.bones:
        if control_rig.is_control(bone) or hands & {parent.name for parent in bone.parent_recursive}:
            continue
        stems = set(mapping.words(bone.name))
        if stems & mapping.STORAGE:
            found.append((not stems & {'sheath', 'saya', 'scabbard'}, len(bone.name), bone.name))
    return [name for *_, name in sorted(found)]


def defaults(rig, task, index=None):
    """The limb (its index as text, or SELECTED), target and held bone that a task starts with on this rig.

    Hand on weapon starts with an arm whose other hand holds a weapon that shows a
    mesh, the left arm first, following that weapon. Weapon into sheath starts
    with an arm whose own hand holds such a weapon, the right arm first, and the
    first sheath. Plant foot and Adjust over frames start with their first limb.
    """
    choices = limbs(rig, task)
    if not choices:
        return dict(limb=SELECTED if task == 'ADJUST' else '', target='', held='')
    arms = {limb['side']: limb for limb in control_rig.layout(rig)['limbs'] if limb['kind'] == 'arm'}
    weapons = {side: held_weapon(rig, limb['bones'][2]) for side, limb in arms.items()}
    shown = {side: bool(name and retarget.carried_meshes(rig, name)) for side, name in weapons.items()}
    other = dict(L='R', R='L')
    if index is None:
        if task == 'HAND':
            def rank(choice):
                side = other.get(choice[1]['side'])
                return not shown.get(side), not weapons.get(side), choice[1]['side'] != 'L'
        elif task == 'SHEATH':
            def rank(choice):
                side = choice[1]['side']
                return not shown.get(side), not weapons.get(side), side != 'R'
        else:
            def rank(choice):
                return 0
        index = min(choices, key=rank)[0]
    limb = control_rig.layout(rig)['limbs'][index]
    target = held = ''
    if task == 'HAND':
        target = weapons.get(other.get(limb['side']), '')
    elif task == 'SHEATH':
        held = weapons.get(limb['side'], '')
        target = next(iter(sheaths(rig)), '')
    return dict(limb=str(index), target=target, held=held)


def movers(rig, task, limb, held='', selected=()):
    """The bones whose pose a task reads on posed frames: the limb's IK control, with the held weapon for a
    sheath and the pole and swivel ring for an adjustment, or the selected controls."""
    if limb is None:
        bones = rig.data.bones
        return [name for name in selected if name in bones and bones[name].get('sekiro_control') in KEYED]
    if task == 'ADJUST':
        return [limb['control'], limb['pole']] + ([limb['swivel']] if limb.get('swivel') else [])
    return [limb['control']] + ([held] if task == 'SHEATH' and held else [])


def capture(context, rig, names):
    """The pose of the named bones on the current frame, as {bone: (armature-space matrix, matrix_basis)}.

    Read it before anything changes the frame: a pose that is not keyed is lost there.
    """
    return {name: (rig.pose.bones[name].matrix.copy(), rig.pose.bones[name].matrix_basis.copy()) for name in names}


def _posed_here(rig, names, frame):
    """The named controls that are posed away from their keys on frame, the current one, as a pose that is not
    keyed stays until the frame changes."""
    data = rig.animation_data
    action = data.action if data else None
    if action is None:
        return []
    bag = control_rig._curves(rig, action)
    posed = []
    for name in names:
        bone = rig.pose.bones[name]
        if bone.bone.get('sekiro_control') not in KEYED:
            continue
        for channel in ('location', _rotation_field(bone), 'scale'):
            keyed, present = _channel(rig, bag, name, channel, [frame])[frame], tuple(getattr(bone, channel))
            if channel == 'rotation_quaternion':
                angle = Quaternion(keyed).normalized().rotation_difference(Quaternion(present).normalized()).angle
                moved = min(angle, 2 * 3.141592653589793 - angle) > 1e-5
            else:
                moved = max(abs(a - b) for a, b in zip(keyed, present)) > 1e-6
            if moved:
                posed.append(name)
                break
    return posed


def _still(rig, name):
    """Whether name is a control without location or rotation keys. The animation holds such a control still, so
    a pose of it changes every frame at once and a fix cannot tell it from the animation."""
    bone = rig.pose.bones.get(name)
    data = rig.animation_data
    if bone is None or bone.bone.get('sekiro_control') not in KEYED or not (data and data.action):
        return False
    paths = {bone.path_from_id('location'), bone.path_from_id(_rotation_field(bone))}
    return not any(curve.data_path in paths and len(curve.keyframe_points)
                   for curve in control_rig._curves(rig, data.action).fcurves)


def _rotation_field(bone):
    mode = bone.rotation_mode
    return 'rotation_quaternion' if mode == 'QUATERNION' else 'rotation_axis_angle' if mode == 'AXIS_ANGLE' else 'rotation_euler'


def _listed(names):
    """Names as text: 'A', 'A and B', 'A, B and C'."""
    names = list(names)
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _rigid(matrix, turn=None):
    """matrix without its scale. A bone shrunk to nothing, as clips hide weapons, takes turn, or no turn."""
    basis = matrix.to_3x3()
    if min(basis.col[axis].length for axis in range(3)) < 1e-9:
        rotation = turn.copy() if turn is not None else Quaternion()
    else:
        rotation = basis.normalized().to_quaternion()
    return Matrix.LocRotScale(matrix.translation, rotation, None)


def _mix(a, b, t):
    """The matrix a part t of the way from a to b: positions and scales interpolated, turns the shorter way."""
    if t <= 0:
        return a.copy()
    if t >= 1:
        return b.copy()
    (la, ra, sa), (lb, rb, sb) = a.decompose(), b.decompose()
    if ra.dot(rb) < 0:
        rb.negate()
    return Matrix.LocRotScale(la.lerp(lb, t), ra.slerp(rb, t), sa.lerp(sb, t))


def _between(keys, frame):
    """The matrix at frame from {frame: matrix}: the first one before the first frame, the last after the last,
    interpolated in between."""
    frames = sorted(keys)
    if frame <= frames[0]:
        return keys[frames[0]]
    for a, b in zip(frames, frames[1:]):
        if frame <= b:
            return _mix(keys[a], keys[b], (frame - a) / (b - a))
    return keys[frames[-1]]


def _weight(frame, start, end, blend):
    """1 on frames start to end, easing smoothly to 0 over blend frames on each side."""
    if start <= frame <= end:
        return 1.0
    distance = start - frame if frame < start else frame - end
    if distance > blend:
        return 0.0
    t = 1 - distance / (blend + 1)
    return t * t * (3 - 2 * t)


def _difference(a, b):
    """(distance, degrees) between the positions and turns of two matrices."""
    turn = a.to_quaternion().rotation_difference(b.to_quaternion())
    angle = turn.angle
    return (a.translation - b.translation).length, min(angle, 2 * 3.141592653589793 - angle) * 57.29577951308232


def _sample(context, rig, names, frames, root=None, switch=None):
    """Per frame: the armature-space matrices of the named bones, the world matrices of the rig and of its
    root-motion object, and the IK slider of the switch control."""
    scene, current = context.scene, context.scene.frame_current
    manager = context.window_manager
    manager.progress_begin(0, len(frames))
    samples = {}
    try:
        for index, frame in enumerate(frames):
            scene.frame_set(frame)
            samples[frame] = dict(bones={name: rig.pose.bones[name].matrix.copy() for name in names},
                                  rig=rig.matrix_world.copy(), root=root.matrix_world.copy() if root else None,
                                  switch=float(rig.pose.bones[switch].get(control_rig.SWITCH, 0.0)) if switch else 1.0)
            manager.progress_update(index)
    finally:
        manager.progress_end()
        scene.frame_set(current)
    return samples


def _curves(rig):
    """Where the rig's action keeps the controls' F-curves; an action is made for a rig without one."""
    data = rig.animation_data
    if data and any(not track.mute for track in data.nla_tracks):
        raise ValueError('Mute the NLA tracks of this armature first, so its action alone gives the motion to fix.')
    action = data.action if data else None
    if action is None:
        base = rig.get('sekiro_control_rig_action')
        action = control_rig._new_action(rig, rig.name + ' Controls', base if isinstance(base, bpy.types.Action) else None)
        action['sekiro_control_rig'] = True
    return control_rig._curves(rig, action)


def _channel(rig, bag, name, field, frames):
    """Per frame, the values the action gives a control's channel; its present value where the channel has no keys."""
    bone = rig.pose.bones[name]
    path = bone.path_from_id(field)
    present = tuple(getattr(bone, field))
    curves = [bag.fcurves.find(path, index=axis) for axis in range(len(present))]
    return {frame: tuple(present[axis] if curve is None or not len(curve.keyframe_points) else curve.evaluate(frame)
                         for axis, curve in enumerate(curves)) for frame in frames}


def _key(rig, bag, name, bases, guards):
    """Key a control's location and rotation from its matrix_basis per frame, and its present values on the
    guard frames.

    The guard frames lie just outside the changed ones, so the frames beyond them
    keep their motion also where the control has fewer keys. Quaternions keep the
    sign of the keys they replace, so the control does not spin where the new keys
    meet the old ones.
    """
    bone = rig.pose.bones[name]
    mode = bone.rotation_mode
    if mode == 'AXIS_ANGLE':
        raise ValueError(f'{name} uses axis-angle rotation. Set its rotation mode to Quaternion first.')
    field = 'rotation_quaternion' if mode == 'QUATERNION' else 'rotation_euler'
    frames = sorted(set(bases) | set(guards))
    old_location = _channel(rig, bag, name, 'location', frames)
    old_rotation = _channel(rig, bag, name, field, frames)
    locations, rotations = [], []
    for frame in frames:
        if frame not in bases:
            locations.append(old_location[frame])
            rotations.append(old_rotation[frame])
            continue
        location, rotation, scale = bases[frame].decompose()
        locations.append(tuple(location))
        if mode == 'QUATERNION':
            if rotation.dot(Quaternion(old_rotation[frame])) < 0:
                rotation.negate()
            rotations.append(tuple(rotation))
        else:
            rotations.append(tuple(rotation.to_euler(mode, Euler(old_rotation[frame], mode))))
    group = bag.groups.get(name) or bag.groups.new(name)
    control_rig._write(bag, bone.path_from_id('location'), group, frames, locations)
    control_rig._write(bag, bone.path_from_id(field), group, frames, rotations)


def _basis(rig, name, matrix, parent_matrix):
    """matrix_basis that gives a bone the armature-space matrix under its parent's armature-space matrix."""
    bone = rig.data.bones[name]
    if bone.parent is None:
        return bone.convert_local_to_pose(matrix, bone.matrix_local, invert=True)
    return bone.convert_local_to_pose(matrix, bone.matrix_local, parent_matrix=parent_matrix,
                                      parent_matrix_local=bone.parent.matrix_local, invert=True)


def _window(scene, start, end, blend):
    return list(range(max(scene.frame_start, start - blend), min(scene.frame_end, end + blend) + 1))


def _guards(scene, frames):
    return [frame for frame in (frames[0] - 1, frames[-1] + 1) if scene.frame_start <= frame <= scene.frame_end]


def _check_posed(posed, start, end):
    outside = sorted(frame for frame in posed if not start <= frame <= end)
    if outside:
        raise ValueError(f'Frame {retarget.spans(outside)} is posed but lies outside frames {start}–{end}. '
                         'Widen the frames, or clear the posed frames.')


def _slider(rig, limb, frames):
    """Per frame, the limb's IK slider: from its keys where the action has any, else its value."""
    bone = rig.pose.bones[limb['control']]
    action = rig.animation_data.action if rig.animation_data else None
    curve = control_rig._curves(rig, action).fcurves.find(bone.path_from_id(f'["{control_rig.SWITCH}"]')) if action else None
    if curve is None or not len(curve.keyframe_points):
        return {frame: float(bone.get(control_rig.SWITCH, 0.0)) for frame in frames}
    return {frame: curve.evaluate(frame) for frame in frames}


def check_ik(rig, limb, frames):
    """Refuse a fix of a limb that is in FK on all of frames (start, end).

    Its IK controls do not move it there, and Switch to IK, which matches them
    to the FK pose on every frame, would undo the fix afterwards.
    """
    start, end = frames
    if all(value < .001 for value in _slider(rig, limb, range(start, end + 1)).values()):
        span = f'frame {start}' if start == end else f'frames {start}–{end}'
        raise ValueError(f"The {limb['label'].lower()} is in FK on {span}, so its IK controls do not move it. "
                         'Click Switch to IK first, then pose it and click Apply fix.')


def _reach(context, rig, limb, frames):
    """Frames where the limb's hand or foot stops short of its IK control, the largest gap, and frames where the
    limb is not fully in IK."""
    control, end = limb['control'], limb['bones'][2]
    bones = rig.data.bones
    offset = bones[control].matrix_local.inverted() @ bones[end].matrix_local
    tolerance = max(5e-4, .002 * limb['distance'])
    short, partial, gap = [], [], 0.0
    for frame, sample in _sample(context, rig, [control, end], frames, switch=control).items():
        matrices = sample['bones']
        distance = ((matrices[control] @ offset).translation - matrices[end].translation).length
        if sample['switch'] < .999:
            partial.append(frame)
        elif distance > tolerance:
            short.append(frame)
            gap = max(gap, distance)
    return short, gap, partial


def follow(context, rig, limb, frames, blend, posed, target=None, held=None):
    """Keep a limb's IK control on a target over frames, easing in and out over blend frames; returns a report.

    frames is (start, end). posed maps the posed frames to {bone: armature-space
    matrix} of the IK control and, with held, of the bone its hand holds. target
    is a bone, or None for the world the game moves the character in: where the
    rig has a root-motion object, the frame of that object, which export writes
    as the character's place in the game, else Blender's world. With held, the
    hand moves so that held keeps its relation to the target instead.
    """
    scene, bones = context.scene, rig.data.bones
    control, follower = limb['control'], held or limb['control']
    part = 'hand' if limb['kind'] == 'arm' else 'foot'
    moving = set(limb['bones']) | {bone.name for bone in bones[limb['bones'][0]].children_recursive}
    if target is not None:
        if target not in bones or control_rig.is_control(bones[target]):
            raise ValueError(f"Choose a bone of the character for the {part} to follow, such as R_Weapon; '{target}' is not one.")
        if target in moving:
            raise ValueError(f"{target} moves with the {limb['label'].lower()} itself, so its {part} cannot follow it.")
    if held is not None and (held not in bones or limb['bones'][2] not in {p.name for p in bones[held].parent_recursive}):
        raise ValueError(f"'{held}' is not a bone in the {limb['label'].lower()}'s hand. Choose the weapon that hand holds.")
    start, end = frames
    _check_posed(posed, start, end)
    bag = _curves(rig)
    window = _window(scene, start, end, blend)
    parent = bones[control].parent.name if bones[control].parent else None
    names = list(dict.fromkeys(name for name in (control, parent, target, held) if name))
    root = retarget.root_object(rig) if target is None else None
    samples = _sample(context, rig, names, window, root)

    turns = {}

    def rigid(name, matrix):
        result = _rigid(matrix, turns.get(name))
        turns[name] = result.to_quaternion()
        return result

    def space(frame):
        """The target's frame in armature space."""
        sample = samples[frame]
        if target is not None:
            return rigid(target, sample['bones'][target])
        if sample['root'] is not None:
            return sample['root'].inverted()  # Export writes the root object as the character's place in the game.
        return sample['rig'].inverted()

    keys = {frame: space(frame).inverted() @ rigid(follower, matrices[follower]) for frame, matrices in sorted(posed.items())}
    bases, moved, angle = {}, 0.0, 0.0
    for frame in window:
        weight = _weight(frame, start, end, blend)
        if weight <= 0:
            continue
        matrices = samples[frame]['bones']
        old, here = rigid(follower, matrices[follower]), space(frame)
        wanted = here @ _mix(here.inverted() @ old, _between(keys, frame), weight)
        new = wanted @ old.inverted() @ matrices[control]
        bases[frame] = _basis(rig, control, new, matrices[parent] if parent else None)
        distance, degrees = _difference(new, matrices[control])
        moved, angle = max(moved, distance), max(angle, degrees)
    changed = sorted(bases)
    _key(rig, bag, control, bases, _guards(scene, changed))
    scene.frame_set(scene.frame_current)
    short, gap, partial = _reach(context, rig, limb, changed)
    return dict(frames=changed, moved=moved, angle=angle, short=short, gap=gap, partial=partial, part=part,
                root=root is not None and any(samples[f]['root'] != samples[window[0]]['root'] for f in window))


def _body(rig, name):
    """The game bone above the limb whose IK control or pole is name, or None for any other control."""
    for limb in control_rig.layout(rig)['limbs']:
        if name in (limb['control'], limb['pole']):
            parent = rig.data.bones[limb['bones'][0]].parent
            return parent.name if parent else None
    return None


class NoChange(ValueError):
    """adjust() found the controls as the animation has them on every posed frame."""


def adjust(context, rig, controls, frames, blend, posed):
    """Spread the change between the animation and the posed controls over frames, easing in and out over blend
    frames; returns a report.

    controls maps each control to the bone it measures its change from: for an IK
    control or pole the bone above its limb, so the change turns with the body;
    None for a control that changes its own channels, as an additive layer would.
    posed maps the posed frames to {control: (armature-space matrix, matrix_basis)}.
    Between posed frames the change is interpolated; before the first and after
    the last it holds.
    """
    scene, bones = context.scene, rig.data.bones
    start, end = frames
    _check_posed(posed, start, end)
    bag = _curves(rig)
    window = _window(scene, start, end, blend)
    parents = {name: bones[name].parent.name if bones[name].parent else None for name in controls}
    names = sorted(set(controls) | {n for n in controls.values() if n} | {n for n in parents.values() if n})
    samples = _sample(context, rig, names, window)

    def relation(name, frame, matrices):
        """The control relative to the bone it measures from, or its matrix_basis."""
        space = controls[name]
        if space:
            return _rigid(matrices[space]).inverted() @ matrices[name]
        parent = parents[name]
        return _basis(rig, name, matrices[name], matrices[parent] if parent else None)

    changes = {}
    for name in controls:
        deltas = {}
        for frame, pose in posed.items():
            if name not in pose:
                continue
            matrices = samples[frame]['bones']
            old = relation(name, frame, matrices).decompose()
            new = (relation(name, frame, {**matrices, name: pose[name][0]}) if controls[name] else pose[name][1]).decompose()
            deltas[frame] = Matrix.LocRotScale(new[0] - old[0], old[1].inverted() @ new[1], None)
        if any(d.translation.length > 1e-6 or d.to_quaternion().angle > 1e-5 for d in deltas.values()):
            changes[name] = deltas
    if not changes:
        raise NoChange(f"{_listed(controls)} {'matches' if len(controls) == 1 else 'match'} the animation on "
                       f"frame{'s' if len(posed) > 1 else ''} {retarget.spans(sorted(posed))}, so there is no change to spread.")
    moved = angle = 0.0
    changed = set()
    for name, deltas in changes.items():
        bases = {}
        for frame in window:
            weight = _weight(frame, start, end, blend)
            if weight <= 0:
                continue
            delta = _mix(Matrix(), _between(deltas, frame), weight)
            matrices = samples[frame]['bones']
            location, rotation, scale = relation(name, frame, matrices).decompose()
            changed_relation = Matrix.LocRotScale(location + delta.translation, rotation @ delta.to_quaternion(), scale)
            if controls[name]:
                new = _rigid(matrices[controls[name]]) @ changed_relation
                parent = parents[name]
                bases[frame] = _basis(rig, name, new, matrices[parent] if parent else None)
            else:
                bases[frame] = changed_relation
            moved = max(moved, delta.translation.length)
            angle = max(angle, _difference(Matrix(), delta)[1])
        frames_changed = sorted(bases)
        _key(rig, bag, name, bases, _guards(scene, frames_changed))
        changed |= set(frames_changed)
    scene.frame_set(scene.frame_current)
    changed = sorted(changed)
    short, partial, gap = [], [], 0.0
    for limb in control_rig.layout(rig)['limbs']:
        if changes.keys() & {limb['control'], limb['pole'], limb.get('swivel')}:
            limb_short, limb_gap, limb_partial = _reach(context, rig, limb, changed)
            short, partial, gap = sorted(set(short) | set(limb_short)), sorted(set(partial) | set(limb_partial)), max(gap, limb_gap)
    return dict(frames=changed, moved=moved, angle=angle, short=short, gap=gap, partial=partial, controls=sorted(changes))


def _unread(rig, limb, names, frame, selected):
    """What to do when the controls an adjustment read match the animation on frame: include the controls that
    are posed instead, key the selected or active controls that the animation holds still, or pose without keying."""
    others = _posed_here(rig, [bone.name for bone in rig.pose.bones if bone.name not in names], frame)
    if others:
        posed, it = f"{_listed(others)} {'is' if len(others) == 1 else 'are'} posed", 'it' if len(others) == 1 else 'them'
        if limb is None:
            return f'{posed} but not selected: select {it} too, then click Apply fix.'
        return (f"{posed}, but the {limb['label'].lower()} reads only these controls: set Limb to Selected controls, "
                f'select {it} and click Apply fix.')
    active = rig.data.bones.active
    still = [name for name in dict.fromkeys([*selected, *([active.name] if active else [])]) if _still(rig, name)]
    if still:
        it = 'it' if len(still) == 1 else 'them'
        then = (', set Limb to Selected controls and click Apply fix' if limb is not None and set(still) - set(names)
                else ' and click Apply fix')
        return (f"{_listed(still)} {'has' if len(still) == 1 else 'have'} no location or rotation keys, so moving or "
                f'turning {it} changes every frame at once. To change only some frames, undo the change (Ctrl+Z), select '
                f'{_listed(still)} and press I in the viewport to key {it}, then pose {it} again{then}.')
    it = 'it' if len(names) == 1 else 'them'
    return f'Pose {it} without keying {it} (turn auto keying off), then click Apply fix.'


def run(context, rig, task, limb, frames, blend, posed=None, target='', held='', selected=()):
    """Apply a fix to the rig's control rig and return its report, with a message for the panel.

    limb is the index of a limb in the control rig's layout, or None to adjust
    the selected controls. frames is (start, end), blend the number of frames to
    ease over on each side. posed maps posed frames to {bone: (armature-space
    matrix, matrix_basis)}. The pose on the current frame joins them where a
    control is posed away from its keys there, and is used alone without them.
    target and held are bone names; empty takes the task's defaults.
    """
    if not control_rig.present(rig):
        raise ValueError('Add the control rig first.')
    data = control_rig.layout(rig)
    entry = data['limbs'][limb] if limb is not None else None
    if entry is None and task != 'ADJUST':
        raise ValueError('This rig has no ' + ('leg' if task == 'PLANT' else 'arm') + ' with IK controls for this fix.')
    if entry is not None and entry['kind'] not in KINDS[task]:
        raise ValueError(f"{dict((t[0], t[1]) for t in TASKS)[task]} works on {' and '.join(KINDS[task])}s, not the {entry['label'].lower()}.")
    if entry is not None:
        start_values = defaults(rig, task, limb)
        target, held = target or start_values['target'], held or start_values['held']
    if task in ('HAND', 'SHEATH') and not target:
        raise ValueError('Choose the bone for the hand to follow.' if task == 'HAND' else 'Choose the sheath bone.')
    if task == 'SHEATH' and not held:
        raise ValueError(f"Choose the weapon that the {entry['label'].lower()}'s hand holds.")
    start, end = sorted(frames)
    scene = context.scene
    if end < scene.frame_start or start > scene.frame_end:
        raise ValueError(f'Frames {start}–{end} lie outside the scene range {scene.frame_start}–{scene.frame_end}.')
    start, end = max(start, scene.frame_start), min(end, scene.frame_end)
    if entry is not None:
        check_ik(rig, entry, (start, end))
    names = movers(rig, task, entry, held, selected)
    if not names:
        raise ValueError('Select the controls to adjust in Pose Mode, or choose a limb.')
    current = scene.frame_current
    posed = dict(posed or {})
    if not posed or _posed_here(rig, names, current):
        posed[current] = capture(context, rig, names)
    lacking = sorted(frame for frame, pose in posed.items() if task != 'ADJUST' and any(name not in pose for name in names))
    if lacking:
        raise ValueError(f'Frame {retarget.spans(lacking)} was posed for another fix. Clear the posed frames and pose again.')
    # The fix samples other frames, which drops a pose that is not keyed, so a fix that fails puts the controls back.
    shown = {bone.name: {field: tuple(getattr(bone, field)) for field in CHANNELS}
             for bone in rig.pose.bones if bone.bone.get('sekiro_control') in KEYED}
    try:
        if task == 'ADJUST':
            if entry is None:
                names = sorted({name for pose in posed.values() for name in pose if name in rig.data.bones})
            report = adjust(context, rig, {name: _body(rig, name) for name in names}, (start, end), blend,
                            {frame: {name: pose[name] for name in names if name in pose} for frame, pose in posed.items()})
        else:
            report = follow(context, rig, entry, (start, end), blend, {frame: {name: pose[name][0] for name in names}
                                                                        for frame, pose in posed.items()},
                            target=None if task == 'PLANT' else target, held=held if task == 'SHEATH' else None)
    except Exception as exc:
        for name, channels in shown.items():
            for field, value in channels.items():
                setattr(rig.pose.bones[name], field, value)
        if isinstance(exc, NoChange):
            raise ValueError(f'{exc} {_unread(rig, entry, names, current, selected)}') from None
        raise
    report['message'] = describe(task, entry, target, held, (start, end), blend, report)
    report['warned'] = bool(report['short'] or report['partial'])
    return report


def describe(task, limb, target, held, frames, blend, report):
    """The panel's message for a fix's report."""
    start, end = frames
    span = f'frame {start}' if start == end else f'frames {start}–{end}'
    eased = f', easing in and out over {blend} frame{"s" if blend != 1 else ""}' if blend else ''
    if task == 'HAND':
        text = f"{limb['label']} follows {target} on {span}{eased}."
    elif task == 'SHEATH':
        text = f"{limb['label']} keeps {held} on {target} on {span}{eased}."
    elif task == 'PLANT':
        text = f"{limb['label']} stays in place on {span}{eased}."
    else:
        text = f"Spread the posed change of {', '.join(report['controls'])} over {span}{eased}."
    part = report.get('part', 'controls' if limb is None else 'hand' if limb['kind'] == 'arm' else 'foot')
    if report['moved'] > 5e-5 or report['angle'] > .05:
        text += f" The {part} moved by up to {100 * report['moved']:.1f} cm and {report['angle']:.0f}°."
    else:
        text += f' The {part} was already there.'
    if task == 'PLANT' and report.get('root'):
        text += (' It stays still in the game, where root motion carries the character; in Blender, where the '
                 'character stays in place, it moves against the root motion.')
    if report['short']:
        text += (f" Out of reach on frame {retarget.spans(report['short'])}, by up to {100 * report['gap']:.1f} cm: "
                 'the limb is straight there.')
    if report['partial']:
        label = limb['label'] if limb is not None else 'the limb'
        text += (f" Frame {retarget.spans(report['partial'])} is not fully in IK, so the fix shows there only in part. "
                 f"Set the {label} IK slider to 1 there.")
    return text
