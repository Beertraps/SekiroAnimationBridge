"""Mirror an animation left to right, so that a right-handed slash becomes a left-handed one.

The mirror runs across the armature's X axis: in a bridge rig, the game's X
axis, which runs from the character's right to its left. Each bone with a
counterpart on the other side takes its counterpart's motion, reflected:
L_Hand that of R_Hand. A bone on the middle line reflects its own motion.
Root motion reflects too: sideways travel and turns change sign.

Gear takes its own motion, reflected, so that it changes sides with the
motion: the katana that the right hand swings goes into the left hand with
the swing, whether the game hangs it on R_Weapon or the character's mesh
holds it, and a scabbard modeled on the left hip goes to the right hip. Gear
is a weapon, sheath or shield bone, together with the bones without a
counterpart between it and the body, such as a cord around a hilt. The bones
below it mirror across the piece's own mirror plane, so that a piece that
rests symmetric, as the cord does, keeps its shape as it bends: each takes
the motion of the bone at its mirrored place in the piece, or reflects its
own on the plane, and one with no bone there keeps its motion relative to
the bone above it. Gear keeps its side where its mesh bends together with the
body, as Wolf's scabbard is part of his clothes, and where it is stored on
the body without a mesh of its own, as the hip and back cases where the game
hangs sheathed weapons.

A bone without a counterpart that a bone with one carries, such as the cloth
of a sleeve, keeps its own motion relative to that bone and goes along with
it; so does gear that keeps its side and has no counterpart. Other bones
without a counterpart reflect their own motion where they are: exactly on the
middle line, and on their own side for one off it, such as a sash on one hip.

FromSoftware's left and right bones rest as mirror images, but each left bone
is turned 180 degrees about its own Y or Z axis from the reflected right bone,
which is why Blender's Paste Flipped Pose turns them wrong. The mirror reads
each pair's rest frames instead. With W the reflection seen from the bone's
own rest frame and its counterpart's, W = rest(counterpart)⁻¹ · X flip ·
rest(bone) without the rests' places, a bone's pose relative to its rest
becomes W⁻¹ · its counterpart's pose · W. Where a pair rests at mirrored
places, as almost all do, that is exactly the reflected pose, and mirroring
twice gives the original back; where it does not, each bone keeps its rest
place and only its motion reflects. Gear goes where the reflection of the
armature puts it, turned by a reflection W in its own rest frame: that of
armature X, as FromSoftware rests weapons facing the middle plane, unless
its mesh maps onto itself much better under the flip of one of its own axes,
as a scabbard resting tilted with the hip does. A symmetric piece thus looks
exactly like its mirror image, and comes back when mirrored twice.

Bones pair by name. Bones whose names give no side, such as cloth bones on
either hip, pair by mirrored rest place when exactly one bone rests there,
within a thousandth of the leg length as in a rig mirrored by its maker, and
their parents pair too. HKX tracks belong to bones, so they keep their names
and carry their bones' new motion. A custom property that the clip keys on a
bone moves to the bone's counterpart unchanged.
"""
import math
import re
import statistics
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.kdtree import KDTree
from . import control_rig, mapping, retarget

# Armature X runs from the character's right to its left; the mirror negates it.
FLIP = Matrix.Diagonal((-1.0, 1.0, 1.0))
SUFFIX = ' Mirrored'
ROOT_SUFFIX = ' RootMotion'  # The bridge's export pairs an action with the root motion action named like this.
# Root motion channels that change sign: sideways travel, and turns about the up and forward axes.
ROOT_SIGNS = {('location', 0), ('delta_location', 0), ('rotation_euler', 1), ('rotation_euler', 2),
              ('delta_rotation_euler', 1), ('delta_rotation_euler', 2), ('rotation_quaternion', 2),
              ('rotation_quaternion', 3), ('delta_rotation_quaternion', 2), ('delta_rotation_quaternion', 3),
              ('rotation_axis_angle', 2), ('rotation_axis_angle', 3)}
# Values this close count as the same, so that a bone that holds still on both sides gets no keys.
SAME = 1e-5
# Bones whose names give no side pair when one rests this close to the other's mirrored place, as a fraction of the leg
# length. A rig mirrored by its maker rests its pairs within 0.01%; c5100's cheek and a tooth, which are no pair, rest
# within 0.9%.
PLACE = .001
# A vertex bends with every bone that weighs at least this much on it.
BENDS = .01
# A gear mesh maps onto itself under a flip of one of its bone's axes better than under the default reflection when
# its vertices land at least this much closer, on average, to the mesh, and at most half as far.
SYMMETRY = .001
FIELDS = ('location', 'rotation', 'scale')


def rotation_path(bone):
    """The pose bone property that holds its rotation in its rotation mode."""
    return {'QUATERNION': 'rotation_quaternion', 'AXIS_ANGLE': 'rotation_axis_angle'}.get(bone.rotation_mode, 'rotation_euler')


def counterparts(rig):
    """({bone: the bone on the other side}, the matcher's model of the rig, its leg length) for the bones that have
    a counterpart: by name or, where names give no side, by mirrored rest place under a parent that pairs too.
    Distances are fractions of the leg length: 1% from the middle line, 0.1% from the mirrored place, and no
    other bone within 1% more."""
    bones = rig.data.bones
    model = mapping.Rig(retarget.rig_bones(rig))
    pairs = {}
    for name, info in model.bones.items():
        other = model.counterpart(name) if info.side else ''
        if other and model.counterpart(other) == name:
            pairs[name] = other
    # The matcher measures in the scene; rest places here are the armature's own.
    scale = (model.body['scale'] / (retarget.uniform_scale(rig) or 1.0) if model.body else
             max((bone.head_local.length for bone in bones), default=1.0) or 1.0)
    near = .01 * scale
    loose = [bone for bone in bones
             if bone.name in model.bones and not model.bones[bone.name].side and abs(bone.head_local.x) > near]

    def single(place, skip):
        found = sorted(((bone.head_local - place).length, bone.name) for bone in loose
                       if bone.name != skip and bone.name not in pairs)
        if found and found[0][0] < PLACE * scale and (len(found) == 1 or found[1][0] > found[0][0] + near):
            return found[0][1]
        return ''

    for bone in sorted(loose, key=lambda bone: len(bone.parent_recursive)):
        if bone.name in pairs:
            continue
        other = single(FLIP @ bone.head_local, bone.name)
        if not other or single(FLIP @ bones[other].head_local, other) != bone.name:
            continue
        parent, other_parent = (item.parent.name if item.parent else '' for item in (bone, bones[other]))
        if pairs.get(parent, parent) == other_parent:
            pairs[bone.name], pairs[other] = other, bone.name
    return pairs, model, scale


def middle(bone, scale):
    """Whether a bone rests on the middle line."""
    return abs(bone.head_local.x) <= .01 * scale


def held(name):
    """Whether a bone holds gear that goes into a hand: a weapon (R_Weapon, R_Katana) or a shield."""
    return mapping.weapon_name(name) or 'shield' in mapping.words(name)


def meshes(rig):
    """The mesh objects that the armature deforms."""
    return [obj for obj in bpy.data.objects if obj.type == 'MESH' and any(
        modifier.type == 'ARMATURE' and modifier.object == rig for modifier in obj.modifiers)]


def skins(rig):
    """({bone: the bones that bend a vertex together with it}, the bones that bend any vertex) over the meshes that
    the armature deforms."""
    names = set(rig.data.bones.keys())
    shared, skinned = {}, set()
    for obj in meshes(rig):
        groups = [group.name if group.name in names else '' for group in obj.vertex_groups]
        for vertex in obj.data.vertices:
            found = {groups[item.group] for item in vertex.groups if item.weight >= BENDS and item.group < len(groups)}
            found.discard('')
            skinned |= found
            if len(found) > 1:
                for name in found:
                    shared.setdefault(name, set()).update(found)
    return shared, skinned


def gear(rig, pairs, scale):
    """The bones that carry gear to the other side, each with the bones below it. For each weapon, sheath or shield
    bone: the highest of it and the bones without a counterpart above it, up to the body, whose bones bend no vertex
    together with a bone outside them, and that holds a weapon or a shield or has a mesh of its own."""
    bones = rig.data.bones
    shared, skinned = skins(rig)
    roots = set()
    for bone in bones:
        if not mapping.weapon_part(bone.name):
            continue
        chain = [bone]
        while chain[-1].parent and chain[-1].parent.name not in pairs and not middle(chain[-1].parent, scale):
            chain.append(chain[-1].parent)
        for top in reversed(chain):
            inside = {top.name} | {child.name for child in top.children_recursive}
            if any(shared.get(name, set()) - inside for name in inside):
                continue  # Its mesh bends together with the body, which stays where it is.
            if any(held(name) for name in inside) or inside & skinned:
                roots.add(top.name)
                break
    return {name for name in roots if not any(parent.name in roots for parent in bones[name].parent_recursive)}


def piece(rig, root, turn, pairs, scale):
    """({bone below a gear piece's bone: the bone at its mirrored place, itself on the mirror plane, or None}, the
    mirror plane's reflection in the armature): the plane that the piece's W reflects across, through its head at
    rest. Bones pair by name where the names' pair rests there, else by place as counterparts() pairs them; a bone
    within 1% of the leg length from the plane is on it."""
    bones = rig.data.bones
    rest = bones[root].matrix_local.to_3x3().normalized()
    plane = rest @ turn @ rest.transposed()
    head = bones[root].head_local
    near = .01 * scale
    inside = sorted(bones[root].children_recursive, key=lambda bone: len(bone.parent_recursive))

    def image(bone):
        return head + plane @ (bone.head_local - head)

    names = {bone.name for bone in inside}
    found = {}
    for bone in inside:
        place = image(bone)
        named = pairs.get(bone.name)
        if named in names and (bones[named].head_local - place).length <= near:
            found[bone.name] = named
        elif (place - bone.head_local).length <= near:
            found[bone.name] = bone.name
        else:
            nearest = sorted(((other.head_local - place).length, other.name) for other in inside if other != bone)
            found[bone.name] = (nearest[0][1] if nearest and nearest[0][0] <= PLACE * scale and
                                (len(nearest) == 1 or nearest[1][0] > nearest[0][0] + near) else None)
    changed = True
    while changed:
        changed = False
        for bone in inside:
            other = found[bone.name]
            parent = bone.parent.name
            if other is not None and (found.get(other) != bone.name or
                                      found.get(parent, parent) != bones[other].parent.name):
                found[bone.name], changed = None, True  # No mirror image of it in the piece, or not under its parent's.
    return found, plane


def rules(rig, pairs, turns, scale):
    """{bone: (how it mirrors, the bone whose motion it takes, the reflection in the armature it takes it through)}.
    How: 'follow' for a bone that carries gear to the other side, 'swap' for a bone with a counterpart, 'reflect'
    for one that reflects its own motion where it is, 'keep' for one that keeps its own motion. Below a gear piece's
    bone, counterparts and the reflection are those of the piece's own mirror plane."""
    bones = rig.data.bones
    found = {}
    for root, turn in turns.items():
        found[root] = ('follow', root, None)
        within, plane = piece(rig, root, turn, pairs, scale)
        for name, other in within.items():
            found[name] = ('keep', name, None) if other is None else ('reflect' if other == name else 'swap', other, plane)
    for bone in sorted(bones, key=lambda bone: len(bone.parent_recursive)):
        if bone.name in found:
            continue
        parent = found[bone.parent.name][0] if bone.parent else None
        if bone.name in pairs:
            found[bone.name] = ('swap', pairs[bone.name], FLIP)
        elif mapping.weapon_part(bone.name) or parent in ('swap', 'keep'):
            found[bone.name] = ('keep', bone.name, None)
        else:
            found[bone.name] = ('reflect', bone.name, FLIP)
    return found


def reflection(bone, other, plane=FLIP):
    """W, a reflection in the armature, across X unless given, seen from the bone's rest frame and its counterpart's,
    without the rests' places, as (W, the rotation -W, the axis each of the bone's scale axes comes from).

    The bone's pose relative to its rest becomes W⁻¹ · the counterpart's · W. W is orthogonal with determinant -1,
    so -W is a rotation u, and a rotation q becomes u⁻¹ · q · u. FromSoftware's pairs only flip axes, so scale
    stays on its axes.
    """
    turn = other.matrix_local.to_3x3().normalized().transposed() @ plane @ bone.matrix_local.to_3x3().normalized()
    spin = Matrix([[-value for value in row] for row in turn]).to_quaternion()
    return turn, spin, [max(range(3), key=lambda row: abs(turn[row][column])) for column in range(3)]


def reflect(reflected, location, rotation, scale):
    """A pose relative to rest, as (location, quaternion, scale), taken through a reflection: W⁻¹ · pose · W."""
    turn, spin, order = reflected
    return turn.transposed() @ location, spin.inverted() @ rotation @ spin, Vector([scale[row] for row in order])


def symmetry(rig, roots):
    """{bone that carries gear: the reflection W in its rest frame that it is placed with}. That of armature X seen
    from its rest frame, as FromSoftware rests weapons facing the middle plane; or, where the gear's mesh shows
    otherwise, as for a scabbard resting tilted with the hip, the flip of one of the bone's own axes that maps the
    mesh onto itself much better."""
    bones = rig.data.bones
    owner = {name: root for root in roots for name in [root] + [child.name for child in bones[root].children_recursive]}
    points = {root: [] for root in roots}
    for obj in meshes(rig):
        groups = [owner.get(group.name) for group in obj.vertex_groups]
        into = {root: bones[root].matrix_local.inverted() @ rig.matrix_world.inverted() @ obj.matrix_world for root in roots}
        for vertex in obj.data.vertices:
            weights = {}
            for item in vertex.groups:
                root = groups[item.group] if item.group < len(groups) else None
                if root:
                    weights[root] = weights.get(root, 0.0) + item.weight
            for root, weight in weights.items():
                if weight >= .5:
                    points[root].append(into[root] @ vertex.co)
    found = {}
    for root in roots:
        own = reflection(bones[root], bones[root])[0]
        found[root] = own
        if len(points[root]) < 8:
            continue
        tree = KDTree(len(points[root]))
        for index, point in enumerate(points[root]):
            tree.insert(point, index)
        tree.balance()
        sample = points[root][::max(1, len(points[root]) // 2000)]
        options = [own] + [Matrix.Diagonal([-1.0 if row == axis else 1.0 for row in range(3)]) for axis in range(3)]
        errors = [sum(tree.find(option @ point)[2] for point in sample) / len(sample) for option in options]
        best = min(range(len(options)), key=errors.__getitem__)
        if errors[best] < errors[0] / 2 and errors[0] - errors[best] > SYMMETRY:
            found[root] = options[best]
    return found


def placed(bone, matrix, parent_matrix, invert=False):
    """Where a pose relative to rest puts a bone in the armature under its parent's place, as Blender poses it
    without constraints; or with invert, the pose relative to rest that puts it at a place."""
    if bone.parent is None:
        return bone.convert_local_to_pose(matrix, bone.matrix_local, invert=invert)
    return bone.convert_local_to_pose(matrix, bone.matrix_local, parent_matrix=parent_matrix,
                                      parent_matrix_local=bone.parent.matrix_local, invert=invert)


def carry(bones, turns, count, original, mirrored):
    """Add the mirrored poses of the bones that carry gear, {bone: its W} in turns: at each frame, each goes where
    the reflection of the armature puts it, turned by its W, under its parent as mirrored."""
    roots = list(turns)
    above = sorted({parent.name for name in roots for parent in bones[name].parent_recursive},
                   key=lambda name: len(bones[name].parent_recursive))
    flip = FLIP.to_4x4()
    turns = {name: turn.to_4x4() for name, turn in turns.items()}
    for name in roots:
        mirrored[name] = []
    for index in range(count):
        before, after = {}, {}
        for name in above:
            parent = bones[name].parent
            before[name] = placed(bones[name], Matrix.LocRotScale(*original[name][index]), parent and before[parent.name])
            after[name] = placed(bones[name], Matrix.LocRotScale(*mirrored[name][index]), parent and after[parent.name])
        for name in roots:
            bone, parent = bones[name], bones[name].parent
            place = flip @ placed(bone, Matrix.LocRotScale(*original[name][index]), parent and before[parent.name]) @ turns[name]
            mirrored[name].append(placed(bone, place, parent and after[parent.name], invert=True).decompose())


def channels(bone, curves):
    """{'location' | 'rotation' | 'scale': [F-curve or None per component]} of a pose bone; rotation in its rotation mode."""
    prefix = bone.path_from_id()
    paths = dict(location=('location', 3), scale=('scale', 3), rotation=(
        rotation_path(bone), 4 if bone.rotation_mode in ('QUATERNION', 'AXIS_ANGLE') else 3))
    return {field: [curve if curve is not None and len(curve.keyframe_points) else None
                    for curve in (curves.get((f'{prefix}.{path}', index)) for index in range(size))]
            for field, (path, size) in paths.items()}


def pose_at(bone, found, frame=None):
    """A pose bone's (location, quaternion, scale) at frame from its channels' F-curves; channels without keys, or all
    channels without a frame, as they are now."""
    def values(field, current):
        return [curve.evaluate(frame) if curve is not None and frame is not None else value
                for curve, value in zip(found[field], current)]
    mode = bone.rotation_mode
    if mode == 'QUATERNION':
        rotation = Quaternion(values('rotation', bone.rotation_quaternion)).normalized()
    elif mode == 'AXIS_ANGLE':
        angle, *axis = values('rotation', bone.rotation_axis_angle)
        rotation = Quaternion(axis, angle) if Vector(axis).length > 1e-9 else Quaternion()
    else:
        rotation = Euler(values('rotation', bone.rotation_euler), mode).to_quaternion()
    return Vector(values('location', bone.location)), rotation, Vector(values('scale', bone.scale))


def differs(pose, other):
    return ((pose[0] - other[0]).length > SAME, pose[1].rotation_difference(other[1]).angle > SAME,
            (pose[2] - other[2]).length > SAME)


def new_action(obj, name):
    """An empty action for an object, with its slot in Blender 4.4+; returns (action, where its F-curves go)."""
    action = bpy.data.actions.new(name)
    if hasattr(action, 'slots'):
        slot = action.slots.new('OBJECT', obj.name)
        return action, action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    return action, action


def key(bag, path, index, group, frames, values):
    curve = bag.fcurves.new(path, index=index)
    curve.group = group
    curve.keyframe_points.add(len(frames))
    curve.keyframe_points.foreach_set('co', [v for frame, value in zip(frames, values) for v in (float(frame), float(value))])
    for point in curve.keyframe_points:
        point.interpolation = 'LINEAR'
    curve.update()


def write(bag, bone, fields, frames, poses):
    """Key the fields of a pose bone at frames from its (location, quaternion, scale) poses, rotation in its rotation mode."""
    group = bag.groups.get(bone.name) or bag.groups.new(bone.name)
    mode = bone.rotation_mode
    rotations, previous = [], None
    for _, rotation, _ in poses:
        if mode == 'QUATERNION':
            rotation = rotation.copy()
            if previous is not None and rotation.dot(previous) < 0:
                rotation.negate()
            previous = rotation
            rotations.append(tuple(rotation))
        elif mode == 'AXIS_ANGLE':
            axis, angle = rotation.to_axis_angle()
            rotations.append((angle, *axis))
        else:
            previous = rotation.to_euler(mode, previous) if previous is not None else rotation.to_euler(mode)
            rotations.append(tuple(previous))
    rows = dict(location=[tuple(pose[0]) for pose in poses], rotation=rotations, scale=[tuple(pose[2]) for pose in poses])
    for field in FIELDS:
        if field in fields:
            path = bone.path_from_id(rotation_path(bone) if field == 'rotation' else field)
            for index in range(len(rows[field][0])):
                key(bag, path, index, group, frames, [row[index] for row in rows[field]])


def copy_curve(bag, curve, path, sign=1.0):
    """A copy of an F-curve at path, with its keys, handles and interpolation, its values times sign."""
    copy = bag.fcurves.new(path, index=curve.array_index)
    if curve.group is not None:
        copy.group = bag.groups.get(curve.group.name) or bag.groups.new(curve.group.name)
    copy.extrapolation = curve.extrapolation
    copy.keyframe_points.add(len(curve.keyframe_points))
    for point, new in zip(curve.keyframe_points, copy.keyframe_points):
        new.interpolation, new.easing = point.interpolation, point.easing
        new.handle_left_type, new.handle_right_type = point.handle_left_type, point.handle_right_type
        new.amplitude, new.back, new.period = point.amplitude, point.back, point.period
        new.co = point.co.x, sign * point.co.y
        new.handle_left = point.handle_left.x, sign * point.handle_left.y
        new.handle_right = point.handle_right.x, sign * point.handle_right.y
    copy.update()
    return copy


def paired_root(rig, action):
    """The root motion action that goes with an action, as the bridge's export pairs them, else the root object's own."""
    base = action.get('sekiro_control_rig_base')
    if isinstance(base, bpy.types.Action) and base != action:
        return paired_root(rig, base)
    names = [action.name + ROOT_SUFFIX] + ([action.name[:-len('_Sekiro')] + '_RootMotion']
                                          if action.name.endswith('_Sekiro') else [])
    found = next((bpy.data.actions[name] for name in names if name in bpy.data.actions), None)
    root = retarget.root_object(rig)
    return found or (root.animation_data.action if root and root.animation_data else None)


def free_name(base):
    """base, numbered if needed, so that neither it nor its root motion action's name is taken; both fit in a
    Blender name of 63 bytes, so the export can pair them."""
    room = 63 - len((SUFFIX + '.000' + ROOT_SUFFIX).encode('utf-8'))
    while len(base.encode('utf-8')) > room:
        base = base[:-1]
    name, number = base + SUFFIX, 0
    while name in bpy.data.actions or name + ROOT_SUFFIX in bpy.data.actions:
        number += 1
        name = f'{base}{SUFFIX}.{number:03d}'
    return name


def listed(names, count=6):
    names = sorted(names)
    return ', '.join(names[:count]) + (f' and {len(names) - count} more' if len(names) > count else '')


def mirror(context, rig):
    """Add a left-right mirrored copy of an armature's action, with mirrored root motion, and play it.

    The original action and root motion stay as they are, with fake users, so neither is lost when the other plays.
    Returns a summary.
    """
    if rig is None or rig.type != 'ARMATURE':
        raise ValueError('Select the armature whose animation to mirror.')
    if control_rig.present(rig) or any(control_rig.is_control(bone) for bone in rig.data.bones):
        raise ValueError('The armature has a control rig, so its game bones follow the controls. Remove the control rig, '
                         'keeping the edited motion, then mirror; you can add the control rig again afterwards.')
    if rig.library or rig.data.library:
        raise ValueError('The armature is linked from another file. Make it local first.')
    if rig.mode == 'EDIT':
        raise ValueError('Leave Edit Mode first.')
    data = rig.animation_data
    action = data.action if data else None
    if action is None:
        raise ValueError('The armature has no action to mirror.')
    if any(not track.mute for track in data.nla_tracks):
        raise ValueError('Mute the NLA tracks of this armature first, so its action alone gives the motion to mirror.')
    bones, pose = rig.data.bones, rig.pose.bones
    pairs, model, scale = counterparts(rig)
    if not pairs:
        raise ValueError('No left and right bones were found, so there is nothing to swap.')
    if statistics.median((bones[name].head_local - FLIP @ bones[other].head_local).length
                         for name, other in pairs.items()) > .05 * scale:
        raise ValueError("The armature's left and right bones do not face each other across its X axis, so mirroring "
                         "across it would not swap them.")
    roots = gear(rig, pairs, scale)
    turns = symmetry(rig, roots)
    rule = rules(rig, pairs, turns, scale)
    kind = {name: item[0] for name, item in rule.items()}
    pieces = {child.name for root in roots for child in bones[root].children_recursive}

    curves = {(curve.data_path, curve.array_index): curve for curve in retarget.action_curves(action)}
    names = [bone.name for bone in bones]
    found = {name: channels(pose[name], curves) for name in names}
    keyed = {name: {field for field, items in found[name].items() if any(items)} for name in names}
    own = {pose[name].path_from_id(path) for name in names for path in ('location', rotation_path(pose[name]), 'scale')}
    kept, others, outside = [], [], []
    for (path, index), curve in curves.items():
        match = retarget.BONE_CURVE.match(path)
        name = re.sub(r'\\(.)', r'\1', match.group(1)) if match else ''
        if path in own and kind[name] == 'keep':
            kept.append(curve)  # The bone keeps its own motion.
        elif path in own or name in pose and path[match.end():].startswith('.rotation_'):
            continue  # A transform, or a rotation in a mode the bone does not use, which does not move it.
        elif name in pose:
            other = pose[rule[name][1] if kind[name] == 'swap' else name]
            prop = re.fullmatch(r'\["((?:[^"\\]|\\.)*)"\]', path[match.end():])
            prop = re.sub(r'\\(.)', r'\1', prop.group(1)) if prop else None
            if prop and prop in pose[name] and prop not in other:
                other[prop] = pose[name][prop]  # A custom property the counterpart lacks, so its keys have a home.
            others.append((curve, other.path_from_id() + path[match.end():]))
        else:
            outside.append(curve)
    ranges = [curve.range() for curve in curves.values() if len(curve.keyframe_points)]
    if not ranges:
        raise ValueError(f'{action.name} has no keys to mirror.')
    frames = list(range(int(math.floor(min(start for start, _ in ranges))), int(math.ceil(max(end for _, end in ranges))) + 1))

    # Poses relative to rest at each frame, (location, quaternion, scale): as the clip has them, and mirrored.
    original = {name: [pose_at(pose[name], found[name], frame) for frame in frames] for name in names}
    mirrored = {}
    for name in names:
        how, source, plane = rule[name]
        if how in ('swap', 'reflect'):
            reflected = reflection(bones[name], bones[source], plane)
            mirrored[name] = [reflect(reflected, *item) for item in original[source]]
        elif how == 'keep':
            mirrored[name] = original[name]
    carry(bones, turns, len(frames), original, mirrored)

    name = free_name(action.name)
    copy, bag = new_action(rig, name)
    manager = context.window_manager
    manager.progress_begin(0, len(names))
    try:
        for step, bone_name in enumerate(names):
            if kind[bone_name] != 'keep':
                # Fields either bone keys, and fields in which the bone stands otherwise than its mirrored pose.
                source = rule[bone_name][1]
                current, changed = pose_at(pose[bone_name], found[bone_name]), set()
                for item in mirrored[bone_name]:
                    changed |= {field for field, change in zip(FIELDS, differs(item, current)) if change}
                    if len(changed) == len(FIELDS):
                        break
                fields = keyed[bone_name] | keyed[source] | changed
                if fields:
                    write(bag, pose[bone_name], fields, frames, mirrored[bone_name])
            manager.progress_update(step)
    finally:
        manager.progress_end()
    for curve in kept:
        copy_curve(bag, curve, curve.data_path)
    for curve, path in others:
        copy_curve(bag, curve, path)
    for curve in outside:
        copy_curve(bag, curve, curve.data_path)
    copy.use_frame_range = action.use_frame_range
    if action.use_frame_range:
        copy.frame_start, copy.frame_end = action.frame_start, action.frame_end
    copy.use_cyclic = action.use_cyclic
    copy['sekiro_mirrored_from'] = action

    root, root_copy = retarget.root_object(rig), None
    source_root = paired_root(rig, action) if root else None
    if source_root is not None:
        root_copy, root_bag = new_action(root, name + ROOT_SUFFIX)
        for curve in retarget.action_curves(source_root):
            copy_curve(root_bag, curve, curve.data_path, -1.0 if (curve.data_path, curve.array_index) in ROOT_SIGNS else 1.0)
        root_copy.use_frame_range = source_root.use_frame_range
        if source_root.use_frame_range:
            root_copy.frame_start, root_copy.frame_end = source_root.frame_start, source_root.frame_end
        root_copy['sekiro_mirrored_from'] = source_root
    for item in (action, copy, source_root, root_copy):
        if item is not None and not item.library:
            item.use_fake_user = True
    retarget.assign_action(rig, copy)
    if root_copy is not None:
        retarget.assign_action(root, root_copy)
    context.scene.frame_set(context.scene.frame_current)

    notes, warnings = [], []
    if roots:
        notes.append('Gear changes sides with the motion: ' + listed(roots) + '.')
    stays = {name for name in set(names) - pieces if mapping.weapon_part(name) and kind[name] in ('swap', 'keep')}
    if stays:
        warnings.append('Gear that bends together with the body, or that is stored on it without a mesh of its own, '
                        'keeps its side: ' + listed(stays) + '.')
    animated = {name for name in names if keyed[name]}
    # Imports key every track, so the bones whose motion matters here are the ones that move.
    moving = {name for name in animated if any(any(differs(item, original[name][0])) for item in original[name][1:])}
    sided = {name for name in moving - stays - pieces if kind[name] == 'reflect' and not middle(bones[name], scale)}
    if sided:
        warnings.append('No bone on the other side, so these stay on their side and mirror their own motion: '
                        + listed(sided) + '.')
    carried = {name for name in moving - stays if kind[name] == 'keep'}
    if carried:
        warnings.append('No bone on the other side, so these keep their own motion and go along with the bone that '
                        'carries them: ' + listed(carried) + '.')
    moved = {name for name in names if kind[name] != 'keep' and (keyed[name] or keyed[rule[name][1]])}
    constrained = [bone for bone in animated | moved if any(not c.mute and c.influence > 0 for c in pose[bone].constraints)]
    if constrained:
        warnings.append('Constraints are not mirrored; they still act on ' + listed(constrained) + '.')
    if outside:
        warnings.append('Copied without mirroring, as they do not belong to a bone: '
                        + listed({curve.data_path for curve in outside}) + '.')
    if root is not None and source_root is None:
        warnings.append(f'{root.name} has no action, so the mirrored clip has no root motion.')
    return dict(action=copy, source=action, root=root_copy, rules=kind,
                pairs=sum(1 for name in set(names) - pieces if kind[name] == 'swap') // 2, frames=len(frames),
                notes=notes, warnings=warnings)


def summary(result):
    """One status line for a finished mirror."""
    text = (f"Mirrored {result['source'].name} into {result['action'].name}: {result['pairs']} left and right pairs "
            f"swapped over {result['frames']} frames")
    text += f"; root motion in {result['root'].name}" if result['root'] else ''
    return text + '.' + ''.join(' ' + line for line in result['notes'] + result['warnings'])
