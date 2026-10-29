"""Join two animations of one armature into one clip: the first plays, then the second.

The second clip starts where the first one ends, so that the game plays both as one
animation instead of two clips one after the other. Over the blend, the last frames
of the first clip and the first frames of the second play at once: each bone turns
from the one pose to the other, eased in and out, as the game blends two clips. A
blend of 0 cuts from the last frame of the first clip to the first of the second.

Root motion continues: the second clip's travel and turns start from where the
first clip's root stands when the second clip begins, so the character goes on
from there instead of jumping back to where the first clip started. Over the
blend, the root goes from the one path to the other.

A clip from another bridge scene of the same skeleton comes in with Load clip from
.blend: its armature actions and root-motion actions, without objects. A clip
keyed at another frame rate than the scene's is played at its own speed.
"""
import math
import re
from pathlib import Path
import bpy
from mathutils import Euler, Matrix, Vector
from . import control_rig, mirror, retarget

ROOT_SUFFIX = ' RootMotion'  # The bridge's export pairs an action with the root motion action named like this.
JOINT = ' + '
RATE = 'sekiro_frame_rate'  # The frame rate a loaded clip was keyed at, where it differs from this scene's.


def key_range(action):
    """(first, last) frame of an action's keys, or None without keys."""
    ranges = [curve.range() for curve in retarget.action_curves(action) if len(curve.keyframe_points)]
    return (min(start for start, _ in ranges), max(end for _, end in ranges)) if ranges else None


def bone_of(path):
    match = retarget.BONE_CURVE.match(path)
    return (re.sub(r'\\(.)', r'\1', match.group(1)), path[match.end():]) if match else (None, path)


def shares(action, rig):
    """How many of the bones that an action keys the armature has, and how many it keys."""
    keyed = retarget.action_bones(action)
    return len(keyed & set(rig.data.bones.keys())), len(keyed)


def joinable(action, rig):
    """Whether an action animates this armature: most of the bones it keys are the armature's."""
    if action is None or rig is None or rig.type != 'ARMATURE':
        return False
    common, keyed = shares(action, rig)
    return keyed > 0 and common * 2 >= keyed


def named_root(action):
    """The root motion action that the bridge pairs with an action by its name, or None."""
    names = [action.name + ROOT_SUFFIX] + ([action.name[:-len('_Sekiro')] + '_RootMotion']
                                          if action.name.endswith('_Sekiro') else [])
    return next((bpy.data.actions[name] for name in names if name in bpy.data.actions), None)


def free_name(first, second):
    """'first + second', shortened and numbered if needed, so that neither it nor its root motion action's name is taken
    and both fit in a Blender name of 63 bytes."""
    room = 63 - len(('.000' + ROOT_SUFFIX).encode('utf-8'))
    # An imported clip's action is named after its clip, numbered where Blender had the name already.
    first, second = (re.sub(r'_Sekiro(\.\d{3})?$', '', name) for name in (first, second))
    base = first + JOINT + second
    while len(base.encode('utf-8')) > room:
        first, second = (first[:-1], second) if len(first) >= len(second) else (first, second[:-1])
        base = first + JOINT + second
    name, number = base, 0
    while name in bpy.data.actions or name + ROOT_SUFFIX in bpy.data.actions:
        number += 1
        name = f'{base}.{number:03d}'
    return name


def ease(value):
    """0 to 1 over 0 to 1, slow at both ends."""
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def mix(pose, other, weight):
    """A pose (location, quaternion, scale) between two, weight 0 giving the first."""
    rotation = other[1] if pose[1].dot(other[1]) >= 0 else -other[1]
    return pose[0].lerp(other[0], weight), pose[1].slerp(rotation, weight), pose[2].lerp(other[2], weight)


def root_matrix(curves, frame, rest):
    """The root object's matrix at frame from its location and rotation_euler F-curves; channels without keys as in rest."""
    values = {}
    for path, size in (('location', 3), ('rotation_euler', 3)):
        values[path] = [curves[(path, index)].evaluate(frame) if (path, index) in curves else rest[path][index]
                        for index in range(size)]
    return Matrix.LocRotScale(Vector(values['location']), Euler(values['rotation_euler'], 'XYZ'), None)


def load(path, rig):
    """Bring in the armature and root motion actions of another bridge scene that animate this armature.

    Returns the armature actions brought in. A root motion action keeps the name that pairs it with its armature
    action, also where Blender numbered the names of both because the scene had them already.
    """
    path = Path(path).resolve()
    if bpy.data.filepath and path == Path(bpy.data.filepath).resolve():
        raise ValueError('Choose another .blend than the one that is open.')
    with bpy.data.libraries.load(str(path), link=False) as (source, loaded):
        names = list(source.actions)
        texts = [name for name in source.texts if name.startswith('Sekiro Source - ')]
        loaded.actions = list(names)  # Blender replaces the names in this list with the data it loads.
        loaded.texts = list(texts)
    actions = dict(zip(names, loaded.actions))
    rates = {}
    for text in loaded.texts:
        if text is None:
            continue
        try:
            motion = retarget.decode(text)
            rates[Path(str(motion.get('clip', ''))).stem] = float(motion['frameRate'])
        except (ValueError, KeyError, TypeError):
            pass
        bpy.data.texts.remove(text)
    kept, roots = [], {}
    for name, action in actions.items():
        if action is None:
            continue
        if joinable(action, rig):
            kept.append((name, action))
        else:
            roots[name] = action
    used = set()
    for name, action in kept:
        stem = re.sub(r'_Sekiro$', '', name)
        if stem in rates:
            action[RATE] = rates[stem]
        pair = next((roots[other] for other in (name + ROOT_SUFFIX, stem + '_RootMotion') if other in roots), None)
        action.use_fake_user = True
        if pair is not None:
            pair.name = action.name + ROOT_SUFFIX
            pair.use_fake_user = True
            used.add(pair)
    for action in roots.values():
        if action not in used:
            bpy.data.actions.remove(action)
    if not kept:
        raise ValueError(f'{path.name} has no animation of {rig.name}\'s bones. Choose a scene of the same skeleton.')
    return [action for _, action in kept]


def join(context, rig, first, second, blend):
    """Add one action that plays first and then second on the armature, with root motion that goes on, and play it.

    blend: the seconds over which the two clips overlap and blend. The scene's frame range becomes the joined clip's.
    The original actions stay, with fake users. Returns a summary.
    """
    if rig is None or rig.type != 'ARMATURE':
        raise ValueError('Select the armature whose animations to join.')
    if control_rig.present(rig) or any(control_rig.is_control(bone) for bone in rig.data.bones):
        raise ValueError('The armature has a control rig, so its game bones follow the controls. Remove the control rig, '
                         'keeping the edited motion, then join; you can add the control rig again afterwards.')
    if rig.library or rig.data.library:
        raise ValueError('The armature is linked from another file. Make it local first.')
    if rig.mode == 'EDIT':
        raise ValueError('Leave Edit Mode first.')
    if first is None:
        raise ValueError('The armature has no action to start with.')
    if second is None:
        raise ValueError('Choose the animation that comes after it under Then.')
    if first == second:
        raise ValueError('Choose another animation than the armature\'s own to come after it.')
    data = rig.animation_data
    if data and any(not track.mute for track in data.nla_tracks):
        raise ValueError('Mute the NLA tracks of this armature first, so that its actions alone give the motion.')
    first_range, second_range = key_range(first), key_range(second)
    if first_range is None or second_range is None:
        raise ValueError(f'{(second if first_range else first).name} has no keys.')
    common, keyed = shares(second, rig)
    if not common:
        raise ValueError(f'{second.name} animates none of {rig.name}\'s bones.')

    scene = context.scene
    rate = scene.render.fps / scene.render.fps_base
    speed = float(second.get(RATE) or rate) / rate  # Frames of the second clip per scene frame.
    a0, a1 = first_range
    b0, b1 = second_range
    a0, a1 = int(math.floor(a0)), int(math.ceil(a1))
    length = (b1 - b0) / speed  # Scene frames from the second clip's first frame to its last.
    overlap = max(0, min(round(blend * rate), a1 - a0, int(length)))
    start = a1 + 1 - overlap  # The scene frame where the second clip begins.
    end = start + int(math.floor(length + 1e-6))
    frames = list(range(a0, end + 1))

    def into_second(frame):
        return b0 + (frame - start) * speed

    def weight(frame):
        """How far frame is into the second clip: 0 before it, 1 once the blend is over."""
        if frame < start:
            return 0.0
        if frame > a1:
            return 1.0
        return ease((frame - start + 1) / (overlap + 1))

    pose = rig.pose.bones
    names = [bone.name for bone in rig.data.bones]
    curves = [{(curve.data_path, curve.array_index): curve for curve in retarget.action_curves(action)}
              for action in (first, second)]
    found = [{name: mirror.channels(pose[name], items) for name in names} for items in curves]
    own = set()
    for name in names:
        own |= {pose[name].path_from_id(path) for path in ('location', mirror.rotation_path(pose[name]), 'scale')}

    name = free_name(first.name, second.name)
    joined, bag = mirror.new_action(rig, name)
    manager = context.window_manager
    manager.progress_begin(0, len(names))
    try:
        for step, bone_name in enumerate(names):
            fields = {field for field in mirror.FIELDS for items in found if any(items[bone_name][field])}
            if fields:
                poses = []
                for frame in frames:
                    w = weight(frame)
                    before = mirror.pose_at(pose[bone_name], found[0][bone_name], min(frame, a1)) if w < 1 else None
                    after = mirror.pose_at(pose[bone_name], found[1][bone_name], into_second(frame)) if w > 0 else None
                    poses.append(before if after is None else after if before is None else mix(before, after, w))
                mirror.write(bag, pose[bone_name], fields, frames, poses)
            manager.progress_update(step)
    finally:
        manager.progress_end()

    # Other channels, such as custom properties: each clip's values, blended linearly, the last or first value of a
    # clip that lacks the channel standing in for it.
    others = {}
    for index, items in enumerate(curves):
        for key, curve in items.items():
            bone, rest = bone_of(key[0])
            if key[0] in own or (bone in pose and rest.startswith('.rotation_')) or not len(curve.keyframe_points):
                continue
            others.setdefault(key, [None, None])[index] = curve
    for (path, array_index), (before, after) in others.items():
        values = []
        for frame in frames:
            w = weight(frame)
            a = before.evaluate(min(frame, a1)) if before else after.evaluate(b0)
            b = after.evaluate(into_second(frame)) if after else before.evaluate(a1)
            values.append(a + (b - a) * w)
        title = (before or after).group.name if (before or after).group else 'Other'
        mirror.key(bag, path, array_index, bag.groups.get(title) or bag.groups.new(title), frames, values)
    joined['sekiro_joined_from'] = f'{first.name}{JOINT}{second.name}'

    root, root_joined, warnings = retarget.root_object(rig), None, []
    first_root = named_root(first) or (root.animation_data.action if root and root.animation_data and
                                       data and data.action == first else None)
    second_root = named_root(second)
    if root is not None and (first_root or second_root):
        rest = dict(location=list(root.location), rotation_euler=list(root.rotation_euler))
        paths = [{(curve.data_path, curve.array_index): curve for curve in retarget.action_curves(action)} if action else {}
                 for action in (first_root, second_root)]
        anchor = root_matrix(paths[0], min(start, a1), rest) if first_root else Matrix.Identity(4)
        offset = anchor @ root_matrix(paths[1], b0, rest).inverted() if second_root else None
        held = root_matrix(paths[0], a1, rest) if first_root else None
        locations, rotations, previous = [], [], None
        for frame in frames:
            w = weight(frame)
            a = root_matrix(paths[0], min(frame, a1), rest) if first_root else Matrix.Identity(4)
            b = offset @ root_matrix(paths[1], into_second(frame), rest) if second_root else held
            location = a.translation.lerp(b.translation, w)
            turn = a.to_quaternion().slerp(b.to_quaternion(), w)
            previous = turn.to_euler('XYZ', previous) if previous is not None else turn.to_euler('XYZ')
            locations.append(tuple(location))
            rotations.append(tuple(previous))
        root_joined, root_bag = mirror.new_action(root, name + ROOT_SUFFIX)
        group = root_bag.groups.new('Object Transforms')
        for path, rows in (('location', locations), ('rotation_euler', rotations)):
            for index in range(3):
                mirror.key(root_bag, path, index, group, frames, [row[index] for row in rows])
        root_joined['sekiro_joined_from'] = joined['sekiro_joined_from']
        if not second_root:
            warnings.append(f'{second.name} has no root motion, so the root stands where {first.name} leaves it.')
        if not first_root:
            warnings.append(f'{first.name} has no root motion, so the root starts still.')
    elif root is not None:
        warnings.append('Neither clip has root motion.')

    for item in (first, second, first_root, second_root, joined, root_joined):
        if item is not None and not item.library:
            item.use_fake_user = True
    retarget.assign_action(rig, joined)
    if root_joined is not None:
        retarget.assign_action(root, root_joined)
    scene.frame_start, scene.frame_end = frames[0], frames[-1]
    scene.frame_set(min(max(scene.frame_current, frames[0]), frames[-1]))

    if common < keyed:
        warnings.append(f'{second.name} keys {keyed - common} bones that {rig.name} lacks; they are left out.')
    motion = retarget.read_motion(rig) or {}
    if motion.get('trackBoneIndices'):
        bones = motion['skeleton']['bones']
        tracked = {bones[int(index)]['name'] for index in motion['trackBoneIndices']}
        extra = sorted(retarget.action_bones(second) & set(names) - retarget.action_bones(first) - tracked)
        if extra:
            warnings.append(f'{second.name} keys bones that are no track of the clip ({mirror.listed(extra)}); export them '
                            'with Tracks: Original tracks + keyed bones.')
    if abs(speed - 1) > 1e-6:
        warnings.append(f'{second.name} was keyed at {second[RATE]:g} fps and plays at its own speed in this '
                        f'{rate:g} fps scene.')
    return dict(action=joined, first=first, second=second, root=root_joined, frames=len(frames), start=start,
                overlap=overlap, range=(frames[0], frames[-1]), warnings=warnings)


def summary(result):
    """One status line for a finished join."""
    text = (f"Joined {result['first'].name} and {result['second'].name} into {result['action'].name}: frames "
            f"{result['range'][0]}–{result['range'][1]}, the second clip from frame {result['start']}")
    text += f", blended over {result['overlap']} frames" if result['overlap'] else ', cut without a blend'
    text += f"; root motion in {result['root'].name}" if result['root'] else ''
    return text + '.' + ''.join(' ' + line for line in result['warnings'])
