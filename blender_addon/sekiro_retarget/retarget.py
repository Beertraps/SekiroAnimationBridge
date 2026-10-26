"""Bake retargeted FK motion onto a target rig, keeping its skeleton, proportions and HKX tracks.

Each mapped target bone takes its source bone's world-space rotation change
from the source rest pose. With matched rest stances, that change starts from
a target pose whose limbs point like the source's rest pose, so an A-pose
target follows a T-pose source without lowered arms. Bone lengths stay the
target's own. Body travel goes to the bone above both the pelvis and the
spine (Root, RootPos or Master in FromSoftware rigs), so legs and upper body
move together, scaled by leg length. Root motion comes from the source's root
object, from the body's travel, from the target's original clip, or is left out.

A weapon that the target and source bones both carry as an elongated mesh is
turned in its bone so that the two blades stay parallel, whatever the bones'
own axes are. A weapon bone that takes a source weapon from the other hand,
or that rests away from its hand until a clip brings it in, is placed in the
hand that holds the source weapon: its line keeps the source weapon's offset
from that hand, its grip stays in the hand, and it turns, shows and hides
like the source weapon. A weapon that the map hides shrinks to 0.1% on every
frame, as FromSoftware clips hide weapons.
Each weapon in a hand then takes a grip: by default the source's, where the
source's weapon sits in its palm, scaled to the hand; or the target's own,
read from the target's own clip with that hand's fingers, the wrist turned so
that the blade points as far toward the source's as the blade follow says.
With the second hand, where the source holds its weapon with both hands, the
other hand goes onto the target's weapon at the matching place once the hands
are clear of the body.
With body clearance, a hand that would go into the target's
torso, with the weapon it holds, is moved out through its arm, easing in and
out over neighbouring frames, because a thinner source can hold its hands
closer to its body than the target can. Clipping that the source has in its
own body stays: only what goes deeper, at the target's size, is moved out.
A source with a wider body holds its arms out to clear it: where its arm
stands close to its body, the target's arm turns in at the shoulder until it
stands as close to the target's torso, at the target's size.
FromSoftware's foot target chains stand upright on the feet, as in the game's
clips: each keeps its rest pose, moved as one so that its target sits on the
foot, and the target turns with the foot.
"""
import base64
import contextlib
import json
import math
import re
import statistics
import textwrap
import zlib
import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from . import mapping as matching
from . import fullbody

BONE_CURVE = re.compile(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]')
# The scale of a hidden weapon. Isshin's clips shrink his spear and scabbard to 0.1%; unlike 0, this leaves the
# bones below a hidden weapon a parent they can be placed against.
HIDDEN = 1e-3


def source_text(rig):
    pointer = rig.get('sekiro_bridge_source_text_data')
    return pointer if isinstance(pointer, bpy.types.Text) else bpy.data.texts.get(rig.get('sekiro_bridge_source_text', ''))


def root_object(rig):
    pointer = rig.get('sekiro_root_motion_data')
    return pointer if isinstance(pointer, bpy.types.Object) else bpy.data.objects.get(rig.get('sekiro_root_motion_object', ''))


def decode(text):
    payload = text.as_string()
    if payload.startswith('SEKIRO_BRIDGE_ZLIB_V1\n'):
        payload = zlib.decompress(base64.b64decode(payload.split('\n', 1)[1])).decode('utf-8')
    return json.loads(payload)


def read_motion(rig):
    text = source_text(rig)
    return decode(text) if text else None


def write_motion(rig, document):
    text = bpy.data.texts.new('Sekiro Source - Retarget - ' + rig.name + '.json')
    encoded = base64.b64encode(zlib.compress(json.dumps(document, separators=(',', ':')).encode('utf-8'))).decode('ascii')
    text.from_string('SEKIRO_BRIDGE_ZLIB_V1\n' + '\n'.join(textwrap.wrap(encoded, 120)))
    text['sekiro_retarget'] = True
    rig['sekiro_bridge_source_text'] = text.name
    rig['sekiro_bridge_source_text_data'] = text
    return text


def bake_base(rig, key, current):
    """What a bake starts from: current data that no bake made, else what the earlier bake started from.

    Baking again with other options or a corrected bone map then gives the
    same result as a first bake instead of building on the previous result.
    None when the earlier bake started from nothing.
    """
    if current is not None and not current.get('sekiro_retarget'):
        rig[key] = current
        return current
    recorded = rig.get(key)
    return recorded if isinstance(recorded, bpy.types.ID) else None


def assign_action(obj, action):
    """Assign an action, with its slot for this object in Blender 4.4+."""
    obj.animation_data_create()
    data = obj.animation_data
    data.action = action
    if action is not None and hasattr(data, 'action_slot') and data.action_slot is None:
        slots = list(getattr(data, 'action_suitable_slots', None) or ())
        own = [slot for slot in slots if slot.identifier == 'OB' + obj.name]
        if own or slots:
            data.action_slot = (own or slots)[0]


def set_export_target(scene, rig):
    if not rig or rig.type != 'ARMATURE' or not rig.get('sekiro_animation_bridge'):
        raise ValueError('Choose a target imported by Sekiro Animation Bridge.')
    text = source_text(rig)
    if not text:
        raise ValueError('Target HKX metadata is missing. Open the target bridge scene first, or append it with this add-on.')
    scene['sekiro_bridge_active_rig'] = rig.name
    scene['sekiro_bridge_export_rig'] = rig
    scene['sekiro_bridge_source_text'] = text.name


def write_action(rig, name, channels):
    action = bpy.data.actions.new(name)
    if hasattr(action, 'slots'):
        slot = action.slots.new('OBJECT', rig.name)
        curves = action.layers.new('Retarget').strips.new(type='KEYFRAME').channelbag(slot, ensure=True).fcurves
    else:
        curves = action.fcurves
    for path, samples in channels.items():
        for axis in range(len(samples[0])):
            curve = curves.new(path, index=axis)
            curve.keyframe_points.add(len(samples))
            curve.keyframe_points.foreach_set('co', [v for i, sample in enumerate(samples) for v in (i + 1.0, float(sample[axis]))])
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
            curve.update()
    action['sekiro_retarget'] = True
    rig.animation_data_create()
    old = rig.animation_data.action
    if old and not old.get('sekiro_retarget'):
        old.use_fake_user = True  # The original clip stays; earlier bakes may be purged.
    rig.animation_data.action = action
    if hasattr(action, 'slots'):
        rig.animation_data.action_slot = slot
    return action


def action_curves(action):
    """The F-curves of an action, in legacy and Blender 4.4+ layered actions."""
    if action is None:
        return []
    layers = getattr(action, 'layers', None)
    return [curve for layer in layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves] \
        if layers else list(getattr(action, 'fcurves', ()))


def action_bones(action):
    """Names of the bones an action animates, in legacy and Blender 4.4+ layered actions."""
    matches = (BONE_CURVE.match(curve.data_path) for curve in action_curves(action))
    return {re.sub(r'\\(.)', r'\1', match.group(1)) for match in matches if match}


def hidden_bones(rig):
    """Bones that the rig's action shrinks below 1% on every key, as FromSoftware clips hide unused weapons.

    Isshin's clips scale his gun to zero and his spear to 0.001.
    """
    largest = {}
    for curve in action_curves(rig.animation_data.action if rig.animation_data else None):
        match = BONE_CURVE.match(curve.data_path)
        if match and curve.data_path.endswith('.scale') and len(curve.keyframe_points):
            values = [0.0] * (2 * len(curve.keyframe_points))
            curve.keyframe_points.foreach_get('co', values)
            name = re.sub(r'\\(.)', r'\1', match.group(1))
            largest[name] = max(largest.get(name, 0.0), max(abs(value) for value in values[1::2]))
    return {name for name, value in largest.items() if value < .01}


def bone_infos(rig, tracked_only=True):
    bones = [b for b in rig.data.bones if 'sekiro_control' not in b]  # Not the control rig's bones.
    if tracked_only and any('hkx_track_index' in b for b in rig.pose.bones):
        bones = [b for b in bones if 'hkx_track_index' in rig.pose.bones[b.name]]
    return bones


def rig_bones(rig, bones=None):
    """Bones for the matcher, with rest heads turned like the object so that +Z is up.

    A bone whose parent is left out hangs from its nearest included ancestor,
    so the hierarchy stays connected when only HKX tracks or Rigify's deform
    bones are matched. The control rig's bones are left out.
    """
    bones = [bone for bone in (rig.data.bones if bones is None else bones) if 'sekiro_control' not in bone]
    bones = [bone for bone in bones if bone.name.startswith('DEF-')] or bones
    names = {bone.name for bone in bones}
    turn = rig.matrix_world.to_3x3()
    result = []
    for bone in bones:
        parent = bone.parent
        while parent and parent.name not in names:
            parent = parent.parent
        result.append(matching.Bone(bone.name, parent.name if parent else '', tuple(turn @ bone.head_local)))
    return result


def uniform_scale(rig):
    return rig.matrix_world.to_scale()[0]


def leg_length(rig, hips, feet):
    ground = sum((rig.data.bones[name].head_local for name in feet), Vector()) / len(feet)
    return (rig.data.bones[hips].head_local - ground).length * uniform_scale(rig)


def estimate_scale(source, target, bone_map, body):
    """Target / source size in world units, from leg length or, failing that, mapped bone spans."""
    hips = body.get(('', 'hips'))
    feet = [body[(side, 'foot')] for side in 'LR' if body.get((side, 'foot')) in bone_map]
    if hips in bone_map and feet:
        target_length = leg_length(target, hips, feet)
        source_length = leg_length(source, bone_map[hips], [bone_map[name] for name in feet])
        if min(target_length, source_length) > 1e-4:
            return max(.05, min(20.0, target_length / source_length))
    ratios = []
    for target_name, source_name in bone_map.items():
        bone = target.data.bones[target_name]
        parent = bone.parent
        while parent and parent.name not in bone_map:
            parent = parent.parent
        if not parent:
            continue
        target_span = (bone.head_local - parent.head_local).length * uniform_scale(target)
        source_span = (source.data.bones[source_name].head_local -
                       source.data.bones[bone_map[parent.name]].head_local).length * uniform_scale(source)
        if source_span > 1e-3 and target_span > 1e-3:
            ratios.append(target_span / source_span)
    return max(.05, min(20.0, statistics.median(ratios))) if ratios else 1.0


def common_ancestor(bones, a, b):
    above = [a] + [parent.name for parent in bones[a].parent_recursive]
    for name in [b] + [parent.name for parent in bones[b].parent_recursive]:
        if name in above:
            return name
    return ''


def body_carrier(rig, body):
    """(hips, carrier): the carrier is the lowest bone above both the hips and the spine."""
    hips = body.get(('', 'hips'))
    if not hips:
        return None, None
    upper = (body['spine'] or body['neck'] or [body.get(('', 'head'))])[0]
    carrier = common_ancestor(rig.data.bones, hips, upper) if upper else hips
    return hips, carrier or hips


def stance_alignment(source, target, bone_map, links, rotation):
    """Per mapped target bone, the rotation that points its limb like the source rest pose.

    Rotations are in target armature space; rotation maps source armature
    directions into it. A bone without its own link (hand, foot, head) keeps its
    nearest mapped ancestor's alignment, so a hand stays in line with its forearm.
    """
    own = {bone: child for bone, child in links if bone in bone_map and child in bone_map}
    result = {}
    for bone in sorted(target.data.bones, key=lambda b: len(b.parent_recursive)):
        if bone.name not in bone_map:
            continue
        parent = bone.parent
        while parent and parent.name not in bone_map:
            parent = parent.parent
        alignment = result[parent.name].copy() if parent else Quaternion()
        child = own.get(bone.name)
        if child:
            target_direction = alignment @ (target.data.bones[child].head_local - bone.head_local)
            source_direction = rotation @ (source.data.bones[bone_map[child]].head_local -
                                           source.data.bones[bone_map[bone.name]].head_local)
            if target_direction.length > 1e-6 and source_direction.length > 1e-6:
                alignment = target_direction.rotation_difference(source_direction) @ alignment
        result[bone.name] = alignment
    return result


def root_transforms(matrices, yaw):
    """Ground travel (and, optionally, heading) of one bone as root transforms starting at the origin.

    Matches the bridge exporter's extraction: Blender Z is up, and the bone
    keeps its first-frame offset from the root.
    """
    start = matrices[0].translation.copy()
    start_rotation = matrices[0].to_quaternion()
    result, previous = [], 0.0
    for matrix in matrices:
        angle = 0.0
        if yaw:
            delta = matrix.to_quaternion() @ start_rotation.inverted()
            twist = 2.0 * math.atan2(delta.z, delta.w)
            angle = previous + (twist - previous + math.pi) % (2.0 * math.pi) - math.pi
            previous = angle
        rotation = Matrix.Rotation(angle, 4, 'Z')
        offset = matrix.translation - rotation.to_3x3() @ start
        offset.z = 0.0
        result.append((Matrix.Translation(offset) @ rotation, offset, angle))
    return result


def same_pose(matrix, other):
    """Equal within single-precision noise (0.01 mm, 0.001 degrees)."""
    location, rotation, scale = matrix.decompose()
    other_location, other_rotation, other_scale = other.decompose()
    turn = rotation.rotation_difference(other_rotation)
    return (location - other_location).length < 1e-5 and Vector(turn[1:]).length < 1e-5 and (scale - other_scale).length < 1e-5


def _trs(matrix):
    translation, rotation, scale = matrix.decompose()
    return dict(translation=[translation.x, translation.z, translation.y],
        rotation=[-rotation.x, -rotation.z, -rotation.y, rotation.w], scale=[scale.x, scale.z, scale.y])


def deformers(rig):
    """(mesh, armature) for each mesh that a rig deforms, directly or through a bridge bind adapter."""
    result = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for modifier in obj.modifiers:
            armature = modifier.object if modifier.type == 'ARMATURE' else None
            if armature and (armature == rig or (armature.parent == rig and armature.get('sekiro_internal_bind_adapter'))):
                result.append((obj, armature))
                break
    return result


def carried_meshes(rig, bone):
    """Meshes that follow a bone rigidly: on a bridge weapon socket, or parented to the bone."""
    holders = [obj for obj in bpy.data.objects
               if (obj.parent == rig and obj.parent_type == 'BONE' and obj.parent_bone == bone) or
               any(c.type == 'COPY_TRANSFORMS' and c.target == rig and c.subtarget == bone and not c.mute and c.influence > .999
                   for c in obj.constraints)]
    return list(dict.fromkeys(mesh for holder in holders for mesh in [holder, *holder.children_recursive] if mesh.type == 'MESH'))


def strongest_groups(obj, names):
    """Per vertex, the index of the vertex group among the given bone names that weighs most on it, or -1."""
    allowed = {group.index for group in obj.vertex_groups if group.name in names}
    result = np.full(len(obj.data.vertices), -1, dtype=np.int64)
    for vertex in obj.data.vertices:
        best, weight = -1, 0.0
        for item in vertex.groups:
            if item.weight > weight and item.group in allowed:
                best, weight = item.group, item.weight
        result[vertex.index] = best
    return result


def evaluated_points(obj, graph, indices=None):
    """World positions of an object's evaluated mesh vertices, or of some of them."""
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    try:
        coordinates = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get('co', coordinates)
        coordinates = coordinates.reshape(-1, 3)
        if indices is not None:
            if len(coordinates) != len(obj.data.vertices):
                return np.empty((0, 3))  # A modifier changed the vertices; their groups no longer apply.
            coordinates = coordinates[indices]
        matrix = np.array(evaluated.matrix_world)
        return coordinates @ matrix[:3, :3].T + matrix[:3, 3]
    finally:
        evaluated.to_mesh_clear()


def weapon_points(rig, bone, graph):
    """The vertices of the weapon a bone carries, in the bone's own space.

    The weapon is the meshes that follow the bone, else the vertices that the bone deforms most, such as an
    enemy's katana inside its character mesh.
    """
    chunks = [evaluated_points(obj, graph) for obj in carried_meshes(rig, bone)]
    if not chunks:
        names = set(rig.data.bones.keys())
        for obj, armature in deformers(rig):
            group = obj.vertex_groups.get(bone)
            if group is not None:
                indices = np.flatnonzero(strongest_groups(obj, names) == group.index)
                if len(indices):
                    chunks.append(evaluated_points(obj, graph, indices))
    points = np.concatenate(chunks) if chunks else np.empty((0, 3))
    if not len(points):
        return points
    inverse = np.array((rig.matrix_world @ rig.pose.bones[bone].matrix).inverted())
    return points @ inverse[:3, :3].T + inverse[:3, 3]


def weapon_axis(rig, bone, graph, local=None):
    """The long axis of the weapon a bone carries (see weapon_points), in the bone's own space, pointing from the bone
    to its far end. None without such a mesh or when it is not clearly elongated. local: its vertices, when known.
    """
    local = weapon_points(rig, bone, graph) if local is None else local
    if len(local) < 4:
        return None
    centred = local - local.mean(0)
    values, vectors = np.linalg.eigh(centred.T @ centred)
    if values[2] < 9 * max(values[1], 1e-12):
        return None  # Less than three times longer than wide: no clear blade or shaft direction.
    axis = Vector(vectors[:, 2])
    tip = Vector(local[np.argmax((local ** 2).sum(1))])
    return axis if axis.dot(tip) >= 0 else -axis


def blade_flat(local, axis):
    """The normal of the flat side of a weapon's front part, from its vertices local in the bone's space, square to
    axis; the sign is arbitrary. None where the front is not clearly flatter one way, as a round shaft is."""
    along = local @ np.array(axis)
    front = local[along > .4 * along.max()]
    if len(front) < 4:
        return None
    centred = front - front.mean(0)
    values, vectors = np.linalg.eigh(centred.T @ centred)
    if values[1] < 4 * max(values[0], 1e-12):
        return None  # Less than twice as wide as thick.
    flat = Vector(vectors[:, 0])
    flat -= axis * flat.dot(axis)
    return flat.normalized() if flat.length > 1e-6 else None


def overlap(points, others, turn, scale):
    """How far, on average, points turned by turn and scaled lie from the nearest of others."""
    tree = KDTree(len(others))
    for index, point in enumerate(others):
        tree.insert(point, index)
    tree.balance()
    moved = (points @ np.array(turn.to_matrix()).T) * scale
    return sum(tree.find(tuple(point))[2] for point in moved) / len(moved)


def weapon_match(target_local, target_axis, source_local, source_axis, near):
    """The turn from the target weapon bone's space to the source's that lays the target weapon on the source's: long
    axis on long axis and the flat side of the blade on the source's. Of the two ways to lay one flat side on the
    other, the one where the meshes, scaled to the same length, lie closer together, so that a curved blade's edge
    stays on the source's edge side; where both lie as close, as for a straight double-edged blade, the one nearer
    to near. None where either blade has no clear flat side."""
    target_flat, source_flat = blade_flat(target_local, target_axis), blade_flat(source_local, source_axis)
    if target_flat is None or source_flat is None:
        return None
    from_target = Matrix((target_axis, target_flat, target_axis.cross(target_flat))).transposed()
    choices = []
    for sign in (1, -1):
        flat = source_flat * sign
        onto = Matrix((source_axis, flat, source_axis.cross(flat))).transposed()
        choices.append((onto @ from_target.transposed()).to_quaternion())
    lengths = [np.ptp(local @ np.array(axis)) for local, axis in ((target_local, target_axis), (source_local, source_axis))]
    step = max(1, len(target_local) // 1500), max(1, len(source_local) // 3000)
    gaps = [overlap(target_local[::step[0]], source_local[::step[1]], turn, lengths[1] / max(lengths[0], 1e-9)) for turn in choices]
    if abs(gaps[0] - gaps[1]) > .1 * max(gaps):
        return choices[gaps.index(min(gaps))]
    return max(choices, key=lambda turn: abs(turn.dot(near)))


def weapon_turns(source, target, bone_map, stance, rotation, graph, holds=()):
    """Per mapped weapon bone, a turn in its own space that keeps its weapon lying as the source's.

    A mapped bone takes its source bone's rotation change from rest. Both weapon meshes are fixed to their
    bones, so turning the target bone by the difference of the two weapons at rest keeps them lying alike at
    every frame, also where a game authored the two weapon bones or models with different axes: the long axes
    parallel and, where both blades have a flat side, the flat sides too (see weapon_match), so that the edge
    faces where the source's does; otherwise only the long axes, by the smallest turn. A bone in holds takes the
    source bone's own rotation, so its turn is the difference of the two weapons in the bones' own spaces.
    """
    turns = {}
    for name, source_name in bone_map.items():
        if not (matching.weapon_name(name) or carried_meshes(target, name)):
            continue
        if not (matching.weapon_name(source_name) or carried_meshes(source, source_name)):
            continue
        target_local, source_local = weapon_points(target, name, graph), weapon_points(source, source_name, graph)
        target_axis, source_axis = weapon_axis(target, name, graph, target_local), weapon_axis(source, source_name, graph, source_local)
        if target_axis is None or source_axis is None:
            continue
        # From the source bone's space to the target bone's, as the bake turns the bone.
        into = Quaternion() if name in holds else (
            target.data.bones[name].matrix_local.to_quaternion().inverted() @ stance.get(name, Quaternion()).inverted() @
            rotation @ source.data.bones[source_name].matrix_local.to_quaternion())
        turn = target_axis.rotation_difference(into @ source_axis)
        laid = weapon_match(target_local, target_axis, source_local, source_axis, into.inverted() @ turn)
        turns[name] = turn if laid is None else into @ laid
    return turns


def weapon_holds(source, target, bone_map):
    """Mapped weapon bones that the bake places where the source holds its weapon: {target bone: (holder, anchor)}.

    The anchor is the nearest mapped bone above the source weapon, normally its hand, and the holder is the
    target bone mapped to it. A target weapon bone below the holder that rests at its hand, mapped to a source
    weapon that rests at the anchor, keeps its own grip and only turns like the source: the usual case. The bake
    places any other in the holder: one in the other hand, as when Isshin's R_Katana takes Godfrey's L_Axe, or
    one that rests away from the hand until a clip brings it in, as Isshin's spear L_Yari does.
    """
    inverse = {source_name: name for name, source_name in bone_map.items()}
    models = {rig: matching.Rig(rig_bones(rig)) for rig in (source, target)}
    holds = {}
    for name, source_name in bone_map.items():
        if not (matching.weapon_name(name) or matching.weapon_name(source_name)):
            continue
        anchor = next((bone.name for bone in source.data.bones[source_name].parent_recursive if bone.name in inverse), None)
        if anchor is None:
            continue
        holder = inverse[anchor]
        if (holder in {bone.name for bone in target.data.bones[name].parent_recursive} and
                models[target].rests_at(name, holder) and models[source].rests_at(source_name, anchor)):
            continue
        holds[name] = (holder, anchor)
    return holds


def weapon_shape(rig, bone, graph):
    """(axis, (back, front)): the long axis of the weapon a bone carries (see weapon_axis) and how far the weapon
    reaches along it behind the bone (negative, toward the pommel) and ahead of it; (None, None) for a weapon without
    a clear axis."""
    local = weapon_points(rig, bone, graph)
    axis = weapon_axis(rig, bone, graph, local)
    if axis is None:
        return None, None
    along = local @ np.array(axis)
    return axis, (float(along.min()), float(along.max()))


def hand_weapons(source, target, bone_map, holds, hidden, body):
    """Mapped weapons that a target hand holds where the source's matching hand holds the source weapon: (weapon,
    hand, placed), placed for a weapon that the bake places in that hand (see weapon_holds). Weapons that the map
    hides are left out."""
    hands = {body[(side, 'hand')] for side in 'LR' if (side, 'hand') in body}
    found = []
    for name, source_name in bone_map.items():
        if name in hidden:
            continue
        if name in holds:
            if holds[name][0] in hands:
                found.append((name, holds[name][0], True))
            continue
        if not (matching.weapon_name(name) or carried_meshes(target, name)) or \
                not (matching.weapon_name(source_name) or carried_meshes(source, source_name)):
            continue
        hand = next((parent.name for parent in target.data.bones[name].parent_recursive if parent.name in hands), None)
        if hand and bone_map.get(hand) in {parent.name for parent in source.data.bones[source_name].parent_recursive}:
            found.append((name, hand, False))
    return found


def knuckles(rig, hand, fingers):
    """The middle of a hand's finger roots, in the hand bone's own space at rest: where a hilt passes through the fist.
    fingers are the roots without the thumb."""
    bones = rig.data.bones
    return bones[hand].matrix_local.inverted() @ (sum((bones[name].head_local for name in fingers), Vector()) / len(fingers))


def palm(poses, hand, fingers):
    """A hand's palm in armature space at a pose: x from the wrist toward the knuckles, y from the little finger's root
    toward the index finger's, z their cross product, at the wrist. fingers are the finger roots without the thumb,
    index finger first; None with fewer than two."""
    if len(fingers) < 2:
        return None
    wrist = poses[hand].translation
    heads = [poses[name].translation for name in fingers]
    x = sum(heads, Vector()) / len(heads) - wrist
    across = heads[0] - heads[-1]
    if x.length < 1e-9:
        return None
    x.normalize()
    y = across - x * across.dot(x)
    if y.length < 1e-9:
        return None
    y.normalize()
    frame = Matrix((x, y, x.cross(y))).transposed().to_4x4()
    frame.translation = wrist
    return frame


def keyed_basis(bone, curves, frame, still):
    """(location, rotation, scale) of a pose bone at frame from an action's F-curves, {(data path, index): curve};
    channels without keys keep their values in still, the bone's matrix_basis without the action."""
    prefix = bone.path_from_id()
    location, rotation, scale = still.decompose()

    def read(field, values):
        values, keyed = list(values), False
        for index in range(len(values)):
            curve = curves.get((f'{prefix}.{field}', index))
            if curve is not None and len(curve.keyframe_points):
                values[index], keyed = curve.evaluate(frame), True
        return values, keyed

    quaternion, keyed = read('rotation_quaternion', rotation)
    if keyed:
        rotation = Quaternion(quaternion).normalized()
    else:
        mode = bone.rotation_mode if bone.rotation_mode not in ('QUATERNION', 'AXIS_ANGLE') else 'XYZ'
        euler, keyed = read('rotation_euler', rotation.to_euler(mode))
        if keyed:
            rotation = Euler(euler, mode).to_quaternion()
    return Vector(read('location', location)[0]), rotation, Vector(read('scale', scale)[0])


def clip_grip(rig, action, hand, weapon, fingers, still):
    """How a rig's own clip holds a weapon: (hand-to-weapon matrix without the weapon's scale, {finger bone:
    matrix_basis}, frame, shown) on the first frame of the action that shows the weapon, else on its first frame.

    fingers names the bones of the hand's fingers to read. A FromSoftware clip that hides a weapon still keys its
    turn in the hand, but its place there can be off: 85 mm in one of Owl's clips.
    """
    bones = rig.data.bones
    above = [parent.name for parent in bones[weapon].parent_recursive]
    chain = list(reversed([weapon] + above[:above.index(hand)]))  # From below the hand down to the weapon.
    curves = {(curve.data_path, curve.array_index): curve for curve in action_curves(action)}
    start, end = action.frame_range
    first = None
    for frame in range(int(math.floor(start)), int(math.ceil(end)) + 1):
        poses, shown = {hand: bones[hand].matrix_local}, True
        for name in chain:
            bone = bones[name]
            location, rotation, scale = keyed_basis(rig.pose.bones[name], curves, frame, still[name])
            shown = shown and min(scale) >= .5
            if name == weapon:
                scale = Vector((1, 1, 1))
            poses[name] = bone.convert_local_to_pose(Matrix.LocRotScale(location, rotation, scale), bone.matrix_local,
                                                     parent_matrix=poses[bone.parent.name],
                                                     parent_matrix_local=bone.parent.matrix_local)
        grip = (poses[hand].inverted() @ poses[weapon], {name: Matrix.LocRotScale(*keyed_basis(
            rig.pose.bones[name], curves, frame, still[name])) for name in fingers}, frame, shown)
        if shown:
            return grip
        first = first or grip
    return first


@contextlib.contextmanager
def rest_pose(*rigs):
    """The rigs shown in their rest pose meanwhile, so that a weapon that a clip hides by scaling keeps its shape."""
    saved = [(rig.data, rig.data.pose_position) for rig in rigs]
    try:
        for data, position in saved:
            data.pose_position = 'REST'
        bpy.context.view_layer.update()
        yield
    finally:
        for data, position in saved:
            data.pose_position = position
        bpy.context.view_layer.update()


def subtree(bones, name):
    return {name} | {child.name for child in bones[name].children_recursive}


def thin(points, cell):
    """One point per grid cell, so a dense mesh costs no more than a coarse one."""
    if not len(points):
        return points
    _, first = np.unique(np.floor(points[:, :3] / cell).astype(np.int64), axis=0, return_index=True)
    return points[np.sort(first)]


def body_geometry(rig, body, graph, holds=None):
    """The torso and hand geometry of a rig's meshes, for keep_clear; None without a torso to keep clear of.

    The torso is the mesh that the hips, the spine and the bones above them deform most, so cloth, limbs and
    the head are left out. A hand's points are the vertices that the hand, its fingers or a weapon bone in it
    deform most, and the meshes those bones carry; each point stays fixed to its bone. holds names the weapon
    bones that the bake places in another bone, with that bone: a weapon placed in a hand belongs to that hand.
    An arm's limb points are the vertices that its forearm, hand and fingers deform most, without the weapons
    in the hand: they show how far the arm stands from the body.
    """
    hips, spine, bones = body.get(('', 'hips')), body['spine'], rig.data.bones
    if not hips or not spine or not body.get('forward'):
        return None
    torso = {hips, *spine} | {parent.name for name in (hips, spine[0]) for parent in bones[name].parent_recursive}
    holds = holds or {}
    placed = set().union(*(subtree(bones, name) for name in holds))
    sides = {}
    for side in 'LR':
        chain = [body.get((side, role)) for role in ('upperarm', 'forearm', 'hand')]
        if all(chain) and chain[1] in subtree(bones, chain[0]) and chain[2] in subtree(bones, chain[1]):
            heads = [bones[name].head_local for name in chain]
            held = (subtree(bones, chain[2]) - placed).union(*(subtree(bones, name) for name, holder in holds.items() if holder == chain[2]))
            sides[side] = dict(chain=chain, arm=(heads[1] - heads[0]).length + (heads[2] - heads[1]).length,
                               held=held, points=[], limb=[])
    if not sides:
        return None
    holder = {name: side for side, item in sides.items() for name in item['held']}
    limb = {}
    for side, item in sides.items():
        lower = subtree(bones, item['chain'][1])
        weapons = set().union(*(subtree(bones, name) for name in lower if matching.weapon_part(name) or carried_meshes(rig, name)))
        limb.update((name, side) for name in lower - weapons - placed)
    cell = min(item['arm'] for item in sides.values()) / 50
    names, to_rig = set(bones.keys()), rig.matrix_world.inverted()
    chunks, faces, offset = [], [], 0
    for obj, armature in deformers(rig):
        mesh = obj.data
        if not len(mesh.vertices):
            continue
        coordinates = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get('co', coordinates)
        premat = np.array(armature.matrix_world.inverted() @ obj.matrix_world)
        rest = np.c_[coordinates.reshape(-1, 3) @ premat[:3, :3].T + premat[:3, 3], np.ones(len(mesh.vertices))]
        post = np.array(to_rig @ armature.matrix_world)
        # A bind adapter's bones follow the rig's bones of the same name from its own rest pose.
        known = names & set(armature.data.bones.keys())
        groups = {group.index: group.name for group in obj.vertex_groups if group.name in known}
        influences = [[(groups[item.group], item.weight) for item in vertex.groups if item.group in groups and item.weight > 0]
                      for vertex in mesh.vertices]
        strongest = [max(items, key=lambda item: item[1])[0] if items else '' for items in influences]
        selected = [i for i, name in enumerate(strongest) if name in torso]
        if selected:
            used = sorted({name for i in selected for name, weight in influences[i]})
            column = {name: k for k, name in enumerate(used)}
            index = np.zeros((len(selected), max(len(influences[i]) for i in selected)), dtype=np.int64)
            weight = np.zeros(index.shape)
            for row, i in enumerate(selected):
                total = sum(w for name, w in influences[i])
                for k, (name, w) in enumerate(influences[i]):
                    index[row, k], weight[row, k] = column[name], w / total
            chunks.append(dict(names=used, index=index, weight=weight, rest=rest[selected], post=post,
                               inverse_rest=np.array([np.array(armature.data.bones[name].matrix_local.inverted()) for name in used])))
            remap = {i: offset + row for row, i in enumerate(selected)}
            faces += [[remap[i] for i in polygon.vertices] for polygon in mesh.polygons
                      if all(i in remap for i in polygon.vertices)]
            offset += len(selected)
        for name in {name for name in strongest if name in holder}:
            indices = [i for i, other in enumerate(strongest) if other == name]
            local = thin(rest[indices] @ np.array(armature.data.bones[name].matrix_local.inverted()).T, cell)
            sides[holder[name]]['points'].append((name, local, post))
        for name in {name for name in strongest if name in limb}:
            indices = [i for i, other in enumerate(strongest) if other == name]
            # Coarser than the hand points: a gap is measured, not a contact.
            local = thin(rest[indices] @ np.array(armature.data.bones[name].matrix_local.inverted()).T, 2 * cell)
            sides[limb[name]]['limb'].append((name, local, post))
    if not faces:
        return None
    for name, side in holder.items():
        for obj in carried_meshes(rig, name):
            world = evaluated_points(obj, graph)
            inverse = np.array((rig.matrix_world @ rig.pose.bones[name].matrix).inverted())
            local = np.c_[world @ inverse[:3, :3].T + inverse[:3, 3], np.ones(len(world))]
            sides[side]['points'].append((name, thin(local, cell), np.identity(4)))
    return dict(chunks=chunks, faces=faces, sides=sides, torso=torso, placed=placed)


def skin(chunks, poses):
    """The torso's vertices in armature space at one pose: linear blend skinning, as the Armature modifier does."""
    result = []
    for chunk in chunks:
        matrices = np.array([np.array(poses[name]) for name in chunk['names']]) @ chunk['inverse_rest']
        moved = np.zeros((len(chunk['rest']), 3))
        for k in range(chunk['index'].shape[1]):
            moved += chunk['weight'][:, k, None] * np.einsum('nij,nj->ni', matrices[chunk['index'][:, k], :3], chunk['rest'])
        post = chunk['post']
        result.append(moved @ post[:3, :3].T + post[:3, 3])
    return np.concatenate(result)


def farthest(tree, point, direction, limit):
    """Distance along a direction to the last torso surface within limit, or None when there is none."""
    travelled, last, step = 0.0, None, limit * 1e-5
    for _ in range(32):
        hit = tree.ray_cast(point + direction * travelled, direction, limit - travelled)
        if hit[0] is None:
            break
        last = travelled + hit[3]
        travelled = last + step
        if travelled >= limit:
            break
    return last


def inside(tree, point, forward, limit):
    """A point is inside the torso when torso surface lies both ahead of and behind it."""
    return tree.ray_cast(point, forward, limit)[0] is not None and tree.ray_cast(point, -forward, limit)[0] is not None


def escape(tree, points, directions, limit):
    """Per direction, the shortest move along it that takes every point out of the torso, or None where none does.

    Each point leaves past the last torso surface in that direction, so clothing layers count as one body.
    Returns None when no point is inside.
    """
    forward, step = directions[0], limit * 1e-4
    caught = [point for point in points if inside(tree, point, forward, limit)]
    if not caught:
        return None
    result = []
    for direction in directions:
        distances = [farthest(tree, point, direction, limit) for point in caught]
        if None in distances:
            result.append(None)  # A side opening in the torso mesh; this way out is not certain.
            continue
        need = max(distances)
        for _ in range(3):
            # Past one surface a point can still be inside another part of the torso; move on in the same direction.
            moved = [point + direction * (need + step) for point in caught]
            more = [farthest(tree, point, direction, limit) for point in moved if inside(tree, point, forward, limit)]
            more = [distance for distance in more if distance is not None]
            if not more:
                break
            need += step + max(more)
        result.append(need)
    return result


def ease(values, reach):
    """Widen each frame's push to its neighbours, then average twice: smooth ramps that still reach every push."""
    count = len(values)
    widened = [max(values[max(0, i - reach):i + reach + 1]) for i in range(count)]
    half = reach // 2  # Two averages over half the widening keep every frame at or above its own push.
    for _ in range(2 if half else 0):
        widened = [sum(widened[max(0, i - half):i + half + 1]) / len(widened[max(0, i - half):i + half + 1]) for i in range(count)]
    return widened


def move_hand(poses, chain, held, upper_part, fore_part, shift, pole=None):
    """Move a hand by shift through two-bone IK: the elbow stays in its plane and the hand keeps its rotation.

    A goal beyond the arm's reach leaves the arm straight, pointing at it. With a pole, the elbow keeps the side
    it bends to from its own shoulder-to-wrist line, and bends toward the pole where the arm is straight.
    """
    upper, fore, hand = chain
    shoulder, elbow, wrist = poses[upper].translation, poses[fore].translation, poses[hand].translation
    a, b = (elbow - shoulder).length, (wrist - elbow).length
    goal = wrist + shift
    reach = goal - shoulder
    d = min(max(reach.length, abs(a - b) + 1e-6), a + b - 1e-6)
    u = reach.normalized()
    bend = (elbow - shoulder) - u * (elbow - shoulder).dot(u)
    if pole is not None:
        line = (wrist - shoulder).normalized()
        side = (elbow - shoulder) - line * (elbow - shoulder).dot(line)
        side = side if side.length >= 1e-3 * a else pole
        bend = side - u * side.dot(u)
    bend = bend.normalized() if bend.length > 1e-6 * a else u.orthogonal().normalized()
    cosine = max(-1.0, min(1.0, (a * a + d * d - b * b) / (2 * a * d)))
    new_elbow = shoulder + (u * cosine + bend * math.sqrt(1 - cosine * cosine)) * a
    new_wrist = shoulder + u * d
    turn_upper = (elbow - shoulder).rotation_difference(new_elbow - shoulder)
    turn_fore = (turn_upper @ (wrist - elbow)).rotation_difference(new_wrist - new_elbow) @ turn_upper
    moves = ((upper_part, Matrix.Translation(shoulder) @ turn_upper.to_matrix().to_4x4() @ Matrix.Translation(-shoulder)),
             (fore_part, Matrix.Translation(new_elbow) @ turn_fore.to_matrix().to_4x4() @ Matrix.Translation(-elbow)),
             (held, Matrix.Translation(new_wrist - wrist)))
    for names, move in moves:
        for name in names:
            poses[name] = move @ poses[name]


def merged(first, second):
    """Per direction, the push that clears both hands, or None where either cannot leave that way."""
    if first is None or second is None:
        return first or second
    return [None if a is None or b is None else max(a, b) for a, b in zip(first, second)]


def runs(flags):
    """(start, end) of each stretch of consecutive true flags, end excluded."""
    result, start = [], None
    for index, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            result.append((start, index))
            start = None
    return result


def torso_frames(rig, body, geometry, pose_frames):
    """Per frame: the torso's ways out, its surface as a BVH tree, a ray length beyond its size, and per hand the
    points within half an arm of the wrist and within the torso's bounds.

    The ways out are forward, back and both sideways in the torso's frame. A bone scaled below 1%, as
    FromSoftware clips hide unused weapons, carries no points. The tree is None when no hand has points there.
    """
    spine, bones = body['spine'][0], rig.data.bones
    rest_turn = bones[spine].matrix_local.to_quaternion().inverted()
    to_rig = rig.matrix_world.to_quaternion().inverted()
    forward_rest = (to_rig @ Vector(body['forward'])).normalized()
    across_rest = forward_rest.cross((to_rig @ Vector((0, 0, 1))).normalized()).normalized()
    for poses in pose_frames:
        turn = poses[spine].to_quaternion() @ rest_turn
        forward, across = turn @ forward_rest, turn @ across_rest
        torso = skin(geometry['chunks'], poses)
        low, high = torso.min(0), torso.max(0)
        near = {}
        for side, item in geometry['sides'].items():
            wrist = np.array(poses[item['chain'][2]].translation)
            points = [(np.array(poses[name]) @ local.T)[:3].T @ post[:3, :3].T + post[:3, 3]
                      for name, local, post in item['points'] if max(poses[name].to_scale()) >= .01]
            points = np.concatenate(points) if points else np.empty((0, 3))
            points = points[(((points - wrist) ** 2).sum(1) < (.5 * item['arm']) ** 2) & np.all((points > low) & (points < high), axis=1)]
            near[side] = [Vector(point) for point in points]
        tree = BVHTree.FromPolygons(torso.tolist(), geometry['faces']) if any(near.values()) else None
        yield (forward, -forward, across, -across), tree, float(np.linalg.norm(high - low)) * 1.5, near


def source_clipping(source, body, geometry, source_frames, target_geometry, bone_map):
    """Per target hand and frame, how deep the matching source hand and what it holds go into the source's own
    torso, scaled to the target by the ratio of arm lengths: the clipping that the source animation has.

    The depth is the deepest point's distance to the nearest torso surface. The way out along one direction
    can be far longer where clothing wraps around the hand: 12 cm for Isshin's left hand, whose deepest point
    lies 4 cm inside his kimono.
    """
    depths = {side: [] for side in geometry['sides']}
    for directions, tree, limit, near in torso_frames(source, body, geometry, source_frames):
        for side, points in near.items():
            depths[side].append(max((tree.find_nearest(point)[3] for point in points if inside(tree, point, directions[0], limit)),
                                    default=0.0))
    allowed = {}
    for side, item in target_geometry['sides'].items():
        match = next((other for other, source_item in geometry['sides'].items()
                      if source_item['chain'][2] == bone_map.get(item['chain'][2])), None)
        if match:
            allowed[side] = [depth * item['arm'] / geometry['sides'][match]['arm'] for depth in depths[match]]
    return allowed


def keep_clear(rig, body, geometry, pose_frames, rate, allowed=None):
    """Move each hand out of the torso where it, or what it holds, would go in; returns what moved per hand.

    allowed gives, per hand and frame, how deep the hand may stay: as deep as the source's own hand goes into
    the source's body, so clipping that the source animation already has stays. A hand whose shortest way out
    is no longer than that is left alone. Otherwise a push takes out the rest of the way, forward, back or
    sideways in the torso's frame, so no point stays deeper; where the source's hand is clear of its body,
    the push goes 2% of the arm's length further. Each stretch of frames in contact keeps one direction, the
    one whose largest push is smallest, so the hand does not switch sides. Each push is widened to its
    neighbours over 0.2 s and averaged, so it eases in and out and
    still covers every frame. Hands that come close together within a stretch, as on one hilt, are pushed
    as one for all of it. A push longer than 35% of the arm is left out and reported, since a hand that far
    inside is not a matter of proportions.
    """
    bones = rig.data.bones
    sides = geometry['sides']
    for item in sides.values():
        upper, fore, hand = item['chain']
        # A weapon placed in the other hand moves with that hand alone.
        item['fore_part'] = subtree(bones, fore) - subtree(bones, hand) - geometry['placed']
        item['upper_part'] = subtree(bones, upper) - subtree(bones, fore) - geometry['placed']
    count = len(pose_frames)
    allowed = {side: allowed[side] if allowed and side in allowed else [0.0] * count for side in sides}
    options = {side: [None] * count for side in sides}
    frames = []
    for t, (directions, tree, limit, near) in enumerate(torso_frames(rig, body, geometry, pose_frames)):
        frames.append(directions)
        for side, points in near.items():
            need = escape(tree, points, directions, limit) if points else None
            if need is None or min((value for value in need if value is not None), default=math.inf) <= allowed[side][t]:
                continue
            # A source hand that touches its body leaves the target's touching too; a clear one, clear by the margin.
            floor = allowed[side][t] or -.02 * sides[side]['arm']
            options[side][t] = [None if value is None else value - floor for value in need]
    reach = max(1, round(.2 * rate))
    spread = reach + 2 * (reach // 2)  # How far ease() carries a push beyond its own frame.
    together = [False] * count
    if len(sides) == 2:
        span = .4 * min(item['arm'] for item in sides.values())
        close = [(poses[sides['L']['chain'][2]].translation - poses[sides['R']['chain'][2]].translation).length < span
                 for poses in pose_frames]
        together = [any(close[max(0, t - spread):t + spread + 1]) for t in range(count)]
    stretches = []  # (sides pushed alike, first frame, choices per frame)
    for start, end in runs(any(options[side][t] is not None for side in sides) for t in range(count)):
        if len(sides) == 2 and any(together[start:end]):
            stretches.append((list(sides), start, [merged(options['L'][t], options['R'][t]) for t in range(start, end)]))
            continue
        for side in sides:
            for first, last in runs(options[side][t] is not None for t in range(start, end)):
                stretches.append(([side], start + first, options[side][start + first:start + last]))
    channels = {side: [[0.0] * count for _ in range(4)] for side in sides}
    for item in sides.values():
        item['unresolved'] = []
    for pushed, start, choices in stretches:
        arm = min(sides[side]['arm'] for side in pushed)
        whole = [index for index in range(4) if all(choice[index] is not None for choice in choices)]
        steady = min(whole, key=lambda index: max(choice[index] for choice in choices)) if whole else None
        for t, choice in enumerate(choices, start):
            valid = [(push, index) for index, push in enumerate(choice) if push is not None]
            push, index = (choice[steady], steady) if steady is not None else min(valid) if valid else (math.inf, 0)
            for side in pushed:
                if push > .35 * arm:
                    sides[side]['unresolved'].append(t + 1)
                else:
                    channels[side][index][t] = push
    shifts = {}
    for side in sides:
        eased = [ease(values, reach) if any(values) else values for values in channels[side]]
        shifts[side] = [sum((direction * channel[t] for direction, channel in zip(frames[t], eased)), Vector()) for t in range(count)]
    moves = {side: [] for side in sides}
    for side, item in sides.items():
        for t, poses in enumerate(pose_frames):
            if shifts[side][t].length > 1e-7:
                move_hand(poses, item['chain'], item['held'], item['upper_part'], item['fore_part'], shifts[side][t])
                moves[side].append((t + 1, shifts[side][t].length))
    # How deep each hand still goes where the source's own hand goes into its body too.
    kept = dict.fromkeys(sides, 0.0)
    shared = [t for t in range(count) if any(allowed[side][t] > 0 for side in sides)]
    for t, (directions, tree, limit, near) in zip(shared, torso_frames(rig, body, geometry, [pose_frames[t] for t in shared])):
        for side, points in near.items():
            if allowed[side][t] > 0:
                kept[side] = max([kept[side]] + [tree.find_nearest(point)[3] for point in points if inside(tree, point, directions[0], limit)])
    report, scale = [], uniform_scale(rig)
    for side, item in sides.items():
        moved = moves[side]
        if moved or item['unresolved'] or kept[side] * scale >= .001:
            report.append(dict(side=side, hand=item['chain'][2], frames=[t for t, length in moved],
                               largest=max((length for t, length in moved), default=0.0) * scale, kept=kept[side] * scale,
                               unresolved=item['unresolved']))
    return report


def limb_frames(rig, body, geometry, pose_frames):
    """Per frame: the spine's turn from rest, the torso's surface as a BVH tree, and per arm its limb points (forearm,
    hand and fingers, without what the hand holds) in armature space."""
    spine = body['spine'][0]
    rest_turn = rig.data.bones[spine].matrix_local.to_quaternion().inverted()
    for poses in pose_frames:
        tree = BVHTree.FromPolygons(skin(geometry['chunks'], poses).tolist(), geometry['faces'])
        arms = {}
        for side, item in geometry['sides'].items():
            points = [(np.array(poses[name]) @ local.T)[:3].T @ post[:3, :3].T + post[:3, 3] for name, local, post in item['limb']]
            arms[side] = np.concatenate(points) if points else np.empty((0, 3))
        yield poses[spine].to_quaternion() @ rest_turn, tree, arms


def nearest_gap(tree, points, limit):
    """(distance, point, torso surface point) where the points come nearest the torso, within limit; else None."""
    best = None
    for point in points:
        location, normal, index, distance = tree.find_nearest(Vector(point), limit)
        if location is not None and (best is None or distance < best[0]):
            best = (distance, Vector(point), location)
    return best


def source_gaps(source, body, geometry, source_frames, target_geometry, bone_map):
    """Per target arm and frame, how far the matching source arm stands from the source's own torso: the gap scaled
    to the target by the ratio of arm lengths, and the gap in the source's arm lengths. None where the source arm
    stands farther than half an arm from its body; an arm without limb points in either rig is left out."""
    gaps = {side: [] for side in geometry['sides']}
    for turn, tree, arms in limb_frames(source, body, geometry, source_frames):
        for side, points in arms.items():
            found = nearest_gap(tree, points, .5 * geometry['sides'][side]['arm']) if len(points) else None
            gaps[side].append(found[0] if found else None)
    wanted = {}
    for side, item in target_geometry['sides'].items():
        match = next((other for other, source_item in geometry['sides'].items()
                      if source_item['chain'][2] == bone_map.get(item['chain'][2])), None)
        if match and geometry['sides'][match]['limb'] and item['limb']:
            arm = geometry['sides'][match]['arm']
            wanted[side] = [None if gap is None else (gap * item['arm'] / arm, gap / arm) for gap in gaps[match]]
    return wanted


def keep_close(rig, body, geometry, pose_frames, rate, wanted):
    """Turn each arm in at the shoulder where it stands farther from the torso than the source's arm stands from the
    source's torso, at the target's size; returns what turned per arm.

    wanted gives, per arm and frame, the source's gap scaled to the target and in the source's arm lengths. Up to a
    quarter of an arm, the target's arm takes that gap, but no less than 2% of its length; from there to half an
    arm, less and less of the difference is taken out, and beyond, the arm is left alone, so swings away from the
    body keep their reach. A gap is the nearest approach of the arm's limb points to the torso surface. The whole
    arm turns about the shoulder joint toward that surface, with the elbow's bend, the hand and what it holds, by
    at most 45°. Turns are averaged twice over 0.1 s on either side, so they ease in and out, but no frame turns
    its arm nearer the torso than 2% of the arm's length. Where both hands come within 0.4 arm lengths of each
    other, as on one hilt, the arms stay as they are, so the grip holds; their turns ease out over the 0.2 s before
    and back in over the 0.2 s after. An arm whose torso lies along it, which turning at the shoulder cannot bring
    closer, stays too.
    """
    bones = rig.data.bones
    sides = {side: item for side, item in geometry['sides'].items() if side in wanted}
    count = len(pose_frames)
    for item in sides.values():
        # The arm turns with what its hand holds, also a weapon placed there, but not with one placed in the other hand.
        item['turned'] = (subtree(bones, item['chain'][0]) - geometry['placed']) | item['held']
    together = [False] * count
    if len(sides) == 2:
        span = .4 * min(item['arm'] for item in sides.values())
        together = [(poses[sides['L']['chain'][2]].translation - poses[sides['R']['chain'][2]].translation).length < span
                    for poses in pose_frames]
    vectors = {side: [Vector()] * count for side in sides}  # Each frame's turn as a rotation vector, in the spine's rest frame
    turns, gripped = [], {side: [] for side in sides}
    for t, (turn, tree, arms) in enumerate(limb_frames(rig, body, geometry, pose_frames)):
        turns.append(turn)
        for side, item in sides.items():
            goal, points = wanted[side][t], arms[side]
            if goal is None or not len(points):
                continue
            x = min(max((goal[1] - .25) / .25, 0.0), 1.0)
            weight = 1 - x * x * (3 - 2 * x)
            if weight <= 0:
                continue
            found = nearest_gap(tree, points, 2 * item['arm'])
            if found is None:
                continue
            gap, closest, surface = found
            want = weight * (gap - max(goal[0], .02 * item['arm']))
            shoulder = pose_frames[t][item['chain'][0]].translation
            lever, pull = closest - shoulder, surface - closest
            if want <= 1e-6 or lever.length < 1e-6 or pull.length < 1e-9:
                continue
            pull.normalize()
            sideways = (pull - lever.normalized() * lever.normalized().dot(pull)).length
            if sideways < .2:
                continue
            if together[t]:
                # Its turn still counts toward the frames around, which ease out of it before the grip.
                gripped[side].append(t + 1)
            axis = lever.cross(pull).normalized()
            angle = want / (lever.length * sideways)
            origin = np.array(shoulder)
            for _ in range(2):
                # Another point can come nearest as the arm turns; measure again and scale the turn.
                moved = nearest_gap(tree, (points - origin) @ np.array(Matrix.Rotation(angle, 3, axis)).T + origin, 2 * item['arm'])
                got = gap - moved[0] if moved else 0.0
                if got <= 1e-9:
                    break
                angle *= min(2.0, max(.5, want / got))
            angle = min(angle, math.radians(45))
            vectors[side][t] = turn.inverted() @ (axis * angle)
    half = max(1, round(.1 * rate))
    # Toward frames with both hands together, turns ease out over 0.2 s, so that none is left where the grip holds.
    marks = [t for t in range(count) if together[t]]
    holds = [min(1.0, min((abs(t - mark) for mark in marks), default=2 * half) / (2 * half)) for t in range(count)]
    targets = {}
    for side in sides:
        series = vectors[side]
        if any(vector.length for vector in series):
            for _ in range(2):
                series = [sum(series[max(0, i - half):i + half + 1], Vector()) / len(series[max(0, i - half):i + half + 1])
                          for i in range(count)]
        targets[side] = [turns[t] @ series[t] * (x * x * (3 - 2 * x)) for t, x in enumerate(holds)]
    # The averaging carries turns onto frames that need less; none takes an arm nearer its torso than 2% of its length.
    busy = [t for t in range(count) if any(targets[side][t].length >= 1e-6 for side in sides)]
    for t, (_, tree, arms) in zip(busy, limb_frames(rig, body, geometry, [pose_frames[t] for t in busy])):
        for side, item in sides.items():
            vector, points = targets[side][t], arms[side]
            if vector.length < 1e-6 or not len(points):
                continue
            axis, origin = vector.normalized(), np.array(pose_frames[t][item['chain'][0]].translation)

            def clear(angle):
                found = nearest_gap(tree, (points - origin) @ np.array(Matrix.Rotation(angle, 3, axis)).T + origin, 2 * item['arm'])
                return found is None or found[0] >= .02 * item['arm']

            if clear(vector.length):
                continue
            low, high = 0.0, vector.length
            for _ in range(8):
                middle = (low + high) / 2
                low, high = (middle, high) if clear(middle) else (low, middle)
            targets[side][t] = axis * low
    report, scale = [], uniform_scale(rig)
    for side, item in sides.items():
        upper, hand, moved = item['chain'][0], item['chain'][2], []
        for t, poses in enumerate(pose_frames):
            vector = targets[side][t]
            if vector.length < 1e-6:
                continue
            shoulder, wrist = poses[upper].translation.copy(), poses[hand].translation.copy()
            move = Matrix.Translation(shoulder) @ Matrix.Rotation(vector.length, 4, vector.normalized()) @ Matrix.Translation(-shoulder)
            for name in item['turned']:
                poses[name] = move @ poses[name]
            moved.append((t + 1, (poses[hand].translation - wrist).length, math.degrees(vector.length)))
        if moved or gripped[side]:
            report.append(dict(side=side, hand=item['chain'][2], frames=[t for t, length, angle in moved],
                               largest=max((length for t, length, angle in moved), default=0.0) * scale,
                               angle=max((angle for t, length, angle in moved), default=0.0), gripped=gripped[side]))
    return report


def fade(value, near, far):
    """1 up to near, 0 from far on, easing smoothly in between."""
    x = min(1.0, max(0.0, (value - near) / (far - near)))
    return 1 - x * x * (3 - 2 * x)


def smoothed(values, reach):
    """values averaged twice over reach frames on either side."""
    for _ in range(2 if reach else 0):
        values = [sum(values[max(0, i - reach):i + reach + 1]) / len(values[max(0, i - reach):i + reach + 1])
                  for i in range(len(values))]
    return values


def degrees(turn):
    """The angle of a rotation quaternion in degrees, exact also for small angles."""
    return math.degrees(2 * math.atan2(Vector(turn[1:]).length, abs(turn[0])))


def rigid(matrix):
    """A matrix without its scale."""
    return Matrix.LocRotScale(matrix.translation, matrix.to_quaternion(), None)


def mix(a, b, t):
    """The matrix a part t of the way from a to b: positions and scales interpolated, turns the shorter way."""
    (la, ra, sa), (lb, rb, sb) = a.decompose(), b.decompose()
    if ra.dot(rb) < 0:
        rb.negate()
    return Matrix.LocRotScale(la.lerp(lb, t), ra.slerp(rb, t), sa.lerp(sb, t))


def local_basis(bone, poses):
    """A bone's matrix_basis from its own and its parent's armature-space matrices in poses."""
    keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=bone.parent.matrix_local) if bone.parent else {}
    return bone.convert_local_to_pose(poses[bone.name], bone.matrix_local, invert=True, **keywords)


def posed(bone, basis, poses):
    """A bone's armature-space matrix from its matrix_basis and its parent's matrix in poses."""
    keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=bone.parent.matrix_local) if bone.parent else {}
    return bone.convert_local_to_pose(basis, bone.matrix_local, **keywords)


def grip_weapons(rig, grips, pose_frames, samples, follow, rate, placed, fingers):
    """Put each weapon in its hand by its grip; each grip records the largest turn of its wrist and move of its weapon.

    With the target's own grip (mode OWN, see clip_grip), the weapon sits in the hand as in the target's own clip,
    and the hand's fingers take their pose from that frame wherever the weapon shows, easing in and out over 0.1 s
    around frames that hide it. The wrist turns, without a twist about the blade, the part follow of the way toward
    the bake's blade direction, which is the source's: at 1 the blade points as the source's does, at 0 the wrist
    turns as the source's does. With the source's grip (mode SOURCE), the weapon sits in the palm as the source's
    weapon sits in the source's palm: its bone where the source's weapon bone sits, scaled by the size of the hands,
    and turned as the source's weapon is turned in that palm, with the turn from the source's weapon to this one
    (model, see weapon_turns), so that a palm that the bake turns otherwise than the source's still holds the hilt
    the same way; the fingers stay the source's. Where the source hides its weapon, the grip where it last showed it
    holds. Bones below a weapon move with it; weapons placed in a hand from elsewhere (placed) and the other hand
    stay. fingers names the target's finger bones; samples holds the source's bones per frame.
    """
    bones = rig.data.bones
    depth = {bone.name: len(bone.parent_recursive) for bone in bones}
    for item in grips:
        item.update(turn=0.0, moved=0.0)
        item['below'] = sorted(subtree(bones, item['weapon']) - {item['weapon']} - placed, key=depth.get)
        if item['mode'] != 'SOURCE':
            continue

        def spot(frame, hidden):
            """The source's weapon bone in the source's palm: its place, scaled to the target's hand, and its turn."""
            held, frame_palm = frame[item['source']], palm(frame, item['source_hand'], item['source_fingers'])
            if frame_palm is None or (min(held.to_scale()) < .5 and not hidden):
                return None
            return (frame_palm.inverted() @ held.translation) * item['ratio'], \
                frame_palm.to_quaternion().inverted() @ held.to_quaternion()
        spots = [spot(frame, False) for frame in samples]
        # A source that hides its weapon on every frame still keys where it holds it, as FromSoftware's clips do.
        item['hidden_source'] = all(value is None for value in spots)
        if item['hidden_source']:
            spots = [spot(frame, True) for frame in samples]
        last = next((value for value in spots if value is not None), None)
        for t, value in enumerate(spots):
            last = spots[t] = value if value is not None else last
        item['spots'] = spots
    by_hand = {}
    for item in grips:
        by_hand.setdefault(item['hand'], []).append(item)
    for hand, items in by_hand.items():
        owned = [item for item in items if item['mode'] == 'OWN']
        weapons = set().union(*(subtree(bones, item['weapon']) for item in items))
        moving = sorted(subtree(bones, hand) - {hand} - placed, key=depth.get)
        digits = [name for name in moving if name not in weapons and
                  any(other in fingers for other in [name] + [p.name for p in bones[name].parent_recursive[:depth[name] - depth[hand]]])]
        shows = [float(any(min(poses[item['weapon']].to_scale()) >= .5 for item in owned)) for poses in pose_frames]
        weights = ease(shows, max(1, round(.1 * rate))) if owned and any(shows) else [0.0] * len(pose_frames)
        for t, poses in enumerate(pose_frames):
            baked = {item['weapon']: poses[item['weapon']].translation.copy() for item in items}
            weight, primary = weights[t], None
            if weight > 1e-6:
                # The wrist turns with the weapon that shows, the first one where both do.
                primary = next((item for item in owned if min(poses[item['weapon']].to_scale()) >= .5), owned[0])
                bases = {name: local_basis(bones[name], poses) for name in digits}
                held, grip = poses[hand].to_quaternion(), primary['grip'].to_quaternion()
                wanted = poses[primary['weapon']].to_quaternion()
                if primary['axis'] is not None:
                    swing = (held @ grip @ primary['axis']).rotation_difference(wanted @ primary['axis'])
                else:
                    swing = wanted @ grip.inverted() @ held.inverted()  # No blade to point: the whole weapon turns like the bake's.
                turn = Quaternion().slerp(swing, follow * weight)
                wrist = poses[hand].translation.copy()
                move = Matrix.Translation(wrist) @ turn.to_matrix().to_4x4() @ Matrix.Translation(-wrist)
                for name in [hand] + moving:
                    poses[name] = move @ poses[name]
                for item in owned:
                    item['turn'] = max(item['turn'], degrees(turn))
            for item in items:
                old = poses[item['weapon']]
                if item['mode'] == 'OWN':
                    held_at = poses[hand] @ item['grip']
                    location, orientation = held_at.translation, held_at.to_quaternion()
                else:
                    frame_palm = palm(poses, hand, item['fingers'])
                    if frame_palm is None or item['spots'][t] is None:
                        continue
                    place, turn = item['spots'][t]
                    location, orientation = frame_palm @ place, frame_palm.to_quaternion() @ turn @ item['model']
                old_location, old_orientation, scale = old.decompose()
                delta = (Matrix.Translation(location) @ (orientation @ old_orientation.inverted()).to_matrix().to_4x4() @
                         Matrix.Translation(-old_location))
                for name in item['below']:
                    poses[name] = delta @ poses[name]
                poses[item['weapon']] = Matrix.LocRotScale(location, orientation, scale)
                item['moved'] = max(item['moved'], (location - baked[item['weapon']]).length)
            if primary is not None:
                for name in digits:
                    basis = bases[name]
                    if name in primary['own_fingers']:
                        basis = mix(basis, primary['own_fingers'][name], weight)
                    poses[name] = posed(bones[name], basis, poses)


def second_hands(rig, pairs, pose_frames, samples, rate, rotation, baked):
    """Put the other hand on the weapon where the source holds its weapon with both hands; returns per hand the frames
    it moved on, how far its knuckles stayed from their place, and the frames where its arm does not reach.

    The source's other hand holds on where the middle of its knuckles comes within half a hand's length of the
    weapon's axis, from a third of a hand behind the pommel to as far ahead of the tip; from there to a hand's length
    it holds on less and less. The target's other hand takes the same place on the target's weapon: on the same
    side of the axis, scaled by the hands' sizes, and along it at the same distance from the main hand, scaled by the
    length of the grip behind the main hand (or of the weapon ahead of it), so both hands stay on a hilt of another
    length. The hand keeps its baked turn relative to the weapon, which is the source's; the arm reaches the place
    through move_hand. Weights are averaged twice over 0.05 s, so the hand eases on and off. samples holds the
    source's bones per frame, baked the turns of the weapons and the other hands before grip_weapons.
    """
    reach = max(1, round(.05 * rate))
    report = []
    for pair in pairs:
        weapon, hand, chain = pair['weapon'], pair['hand'], pair['chain']
        off, axis, source_axis = chain[2], pair['axis'], pair['source_axis']
        (back, front), (source_back, source_front) = pair['reach'], pair['source_reach']
        unit, source_unit = pair['unit'], pair['source_unit']
        weights, goals = [], []
        for t, (poses, frame) in enumerate(zip(pose_frames, samples)):
            held = frame[pair['source']]
            if min(held.to_scale()) < .5 or min(poses[weapon].to_scale()) < .5 or \
                    any(min(poses[name].to_scale()) >= .5 for name in pair['busy']):
                weights.append(0.0)
                goals.append(None)
                continue
            inverse = rigid(held).inverted()

            def along_weapon(names):
                return inverse @ (sum((frame[name].translation for name in names), Vector()) / len(names))
            point = along_weapon(pair['source_off_fingers'])
            along, main = point.dot(source_axis), along_weapon(pair['source_main_fingers']).dot(source_axis)
            radial = point - source_axis * along
            weights.append(fade(radial.length / source_unit, .5, 1) * fade((source_back - along) / source_unit, .3, 1) *
                           fade((along - source_front) / source_unit, .3, 1))
            grip = rigid(poses[weapon])
            main_place = (grip.inverted() @ (poses[hand] @ pair['main_knuckles'])).dot(axis)
            offset = along - main
            if offset < 0:
                lengths = source_back - main, back - main_place
                fits = lengths[0] < -.2 * source_unit and lengths[1] < -.2 * unit
            else:
                lengths = source_front - main, front - main_place
                fits = lengths[0] > .2 * source_unit and lengths[1] > .2 * unit
            stretch = lengths[1] / lengths[0] if fits else pair['ratio']
            # Source weapon space to target weapon space, as the bake turned one from the other.
            across = baked[t][weapon].inverted() @ rotation @ held.to_quaternion()
            place = grip @ (axis * (main_place + offset * stretch) + (across @ radial) * pair['ratio'])
            goals.append((place, poses[weapon].to_quaternion() @ baked[t][weapon].inverted() @ baked[t][off]))
        weights = smoothed(weights, reach)
        moved, gaps, short = [], [], []
        for t, poses in enumerate(pose_frames):
            weight = weights[t]
            if goals[t] is None or weight < 1e-3:
                continue
            place, turn = goals[t]
            wrist = place - turn @ pair['off_knuckles']
            move_hand(poses, chain, pair['held'], pair['upper_part'], pair['fore_part'], (wrist - poses[off].translation) * weight)
            now = poses[off].to_quaternion()
            if now.dot(turn) < 0:
                turn = -turn
            change = now.slerp(turn, weight) @ now.inverted()
            centre = poses[off].translation.copy()
            spin = Matrix.Translation(centre) @ change.to_matrix().to_4x4() @ Matrix.Translation(-centre)
            for name in pair['held']:
                poses[name] = spin @ poses[name]
            moved.append(t + 1)
            if weight > .99:
                gaps.append(((poses[off] @ pair['off_knuckles']) - place).length)
                if gaps[-1] > .1 * unit:
                    short.append(t + 1)
        scale = uniform_scale(rig)
        report.append(dict(side=pair['side'], hand=off, weapon=weapon, source=pair['source'], frames=moved,
                           gap=max(gaps, default=0.0) * scale, short=short))
    return report


def spans(frames):
    """Frame numbers as ranges, such as 3–7, 12."""
    parts, start = [], None
    for frame, following in zip(frames, list(frames[1:]) + [None]):
        start = frame if start is None else start
        if following != frame + 1:
            parts.append(f'{start}–{frame}' if frame > start else str(frame))
            start = None
    return ', '.join(parts)


def bake(scene, settings):
    source, target = settings.source, settings.target
    if not source or not target or source == target:
        raise ValueError('Choose two different armatures as Source and Target.')
    if target.get('sekiro_control_rig'):
        raise ValueError('The target has a control rig. Remove it under Control rig before baking; you can add it again afterwards.')
    if not source.animation_data or not source.animation_data.action:
        raise ValueError('The source rig has no active animation action.')
    if target.animation_data and any(not track.mute for track in target.animation_data.nla_tracks):
        raise ValueError('Mute target NLA tracks before baking so the new action can play without additional mixing.')
    rows = {row.target: row.source for row in settings.rows if row.enabled and row.source}
    whole = settings.method == 'BODY'
    if not rows and not whole:
        raise ValueError('Run Match bones, then select or assign at least one source bone.')
    if len(set(rows.values())) != len(rows):
        raise ValueError('A source bone is assigned more than once. Review the bone list first.')
    for t, s in rows.items():
        if t not in target.data.bones or s not in source.data.bones:
            raise ValueError('The bone list is stale. Run Match bones again.')
    # The full-body bake pairs the body itself and takes only the other bones from the list (see fullbody).
    body = fullbody.plan(source, target, rows, settings.tracked_only) if whole else None
    bone_map = body['bone_map'] if body else rows
    chains = body['chains'] if body else {}
    for rig in (source, target):
        scale = rig.matrix_world.to_scale()
        if min(scale) <= 0 or max(scale) - min(scale) > 1e-4:
            raise ValueError('Source and target armatures need positive uniform object scale.')
    # A bake's own copy of the target metadata serves where the original is gone.
    target_text = bake_base(target, 'sekiro_retarget_base_text', source_text(target)) or source_text(target)
    source_document, target_document = read_motion(source), decode(target_text) if target_text else None
    if target.get('sekiro_animation_bridge') and not target_document:
        raise ValueError('The target bridge metadata is missing.')
    target_action = target.animation_data.action if target.animation_data else None
    base_action = bake_base(target, 'sekiro_retarget_base_action', target_action)
    src_root, dst_root = root_object(source), root_object(target)
    root_action = dst_root.animation_data.action if dst_root and dst_root.animation_data else None
    base_root = bake_base(target, 'sekiro_retarget_base_root', root_action) if dst_root else None
    source_start = 1 if source_document else int(math.floor(source.animation_data.action.frame_range[0]))
    source_count = int(source_document['frameCount']) if source_document else int(math.ceil(source.animation_data.action.frame_range[1])) - source_start + 1
    count = int(target_document['frameCount']) if settings.timing == 'TARGET' and target_document else source_count
    if count < 1 or source_count < 1:
        raise ValueError('The animation has no frames.')
    rate = float(source.get('sekiro_frame_rate', scene.render.fps / scene.render.fps_base))
    if settings.timing == 'TARGET' and target_document:
        rate = float(target_document['frameRate'])

    warnings = []
    target_body = matching.anatomy(rig_bones(target))
    source_body = matching.anatomy(rig_bones(source))
    if body:
        target_body, source_body = fullbody.anatomy(target_body, body['target']), fullbody.anatomy(source_body, body['source'])
    hips, carrier = body_carrier(target, target_body)
    if hips not in bone_map:
        hips = carrier = None
        warnings.append('The target hips are not mapped, so body travel was not transferred.')
    source_hips = bone_map.get(hips)
    source_carrier = None
    if source_hips:
        source_upper = (source_body['spine'] or source_body['neck'] or [source_hips])[0]
        source_carrier = common_ancestor(source.data.bones, source_hips, source_upper) or source_hips
    bones = target.data.bones
    connectors = set()
    if carrier:
        # Unmapped bones between the carrier and the hips or spine (Dark Souls' Lower_Root and
        # Upper_Root, Elden Ring's RootRotY/RootRotXZ) follow the carrier rigidly. Bones above
        # it (Master) hold their rest pose, so the old clip cannot move the new body.
        for end in [hips] + ([target_body['spine'][0]] if target_body['spine'] else []):
            for parent in bones[end].parent_recursive:
                if parent.name == carrier:
                    break
                if parent.name not in bone_map:
                    connectors.add(parent.name)
        connectors.update(parent.name for parent in bones[carrier].parent_recursive if parent.name not in bone_map)
    targets = matching.foot_targets(rig_bones(target))
    columns = set(targets) | {link for foot, chain in targets.values() for link in chain}
    computed = set(bone_map) | connectors | ({carrier} if carrier else set()) | columns | set(chains)
    for name in computed:
        if any(not c.mute and c.influence > 0 for c in target.pose.bones[name].constraints):
            raise ValueError('Disable existing constraints on target bone ' + name + ' before baking.')

    target_rotation = target.matrix_world.to_quaternion()
    rotation = target_rotation.inverted() @ source.matrix_world.to_quaternion()
    rotation_inverse = rotation.inverted()
    factor = estimate_scale(source, target, bone_map, target_body) if settings.auto_scale else settings.travel_scale
    # Source armature units to target armature units for travel.
    travel = factor * uniform_scale(source) / uniform_scale(target)
    align = settings.rest_mode == 'ALIGN'
    if body:
        torso = set(body['target']['spine']) | set(body['target']['neck'])
        stance = fullbody.stance(source, target, bone_map, chains, rotation, torso) if align else {}
    else:
        stance = stance_alignment(source, target, bone_map, matching.limb_links(rig_bones(target)), rotation) if align else {}
    ordered = sorted(bones, key=lambda b: len(b.parent_recursive))
    source_rest = {b.name: b.matrix_local.copy() for b in source.data.bones}
    source_rest_rotation = {name: matrix.to_quaternion() for name, matrix in source_rest.items()}
    target_rest = {b.name: b.matrix_local.copy() for b in ordered}
    carried = {carrier} | {b.name for b in bones if carrier in {p.name for p in b.parent_recursive}} if carrier else set()
    holds = weapon_holds(source, target, bone_map)
    # A holder is placed before what it holds; the bones below a placed weapon follow it.
    placing = sorted(holds, key=lambda name: (len(bones[holds[name][0]].parent_recursive), len(bones[name].parent_recursive)))
    below = {name: [bone for bone in ordered if name in {parent.name for parent in bone.parent_recursive}] for name in holds}
    for name in placing:
        if holds[name][0] in carried:
            carried |= subtree(bones, name)  # It travels with the hand that holds it, wherever its own bone hangs.
    # Weapons that the map hides on every frame, outer ones first, and the bones that hide with them.
    hiding = sorted((row.target for row in settings.rows if row.hidden and row.target in bones),
                    key=lambda name: len(bones[name].parent_recursive))
    under = {name: [bone for bone in ordered if name in {parent.name for parent in bone.parent_recursive}] for name in hiding}
    facing = {}  # Each placed weapon's last rotation, kept while the source hides its weapon by scaling it to zero.
    placed = set().union(*(subtree(bones, name) for name in holds))
    in_hand = hand_weapons(source, target, bone_map, holds, set(hiding), target_body)
    models = {target: matching.Rig(rig_bones(target)), source: matching.Rig(rig_bones(source))}

    def fingers_of(rig, hand):
        """A hand's finger roots without the thumb, index finger first."""
        return [name for number, name in models[rig].finger_roots(hand) if number != 0]

    # Bridge imports leave unanimated bones at their HKX reference pose, a fraction of a
    # millimetre from the edit-bone rest. That pose, not identity, is where they rest.
    animated = action_bones(base_action) | action_bones(target_action)
    still = {b.name: Matrix.Identity(4) if b.name in animated else target.pose.bones[b.name].matrix_basis.copy() for b in ordered}
    source_root_samples, target_root_samples = [], []
    pose_frames = []
    original_frame = scene.frame_current
    # An earlier bake's action makes way for the clip that bake started from; on the target, also for no clip.
    replaced = [(obj, current) for obj, current, base in ((target, target_action, base_action), (dst_root, root_action, base_root))
                if obj and base != current and (base is not None or obj == target)]
    stale = set()
    for obj, current in replaced:
        assign_action(obj, base_action if obj == target else base_root)
        if obj == target:
            stale = action_bones(current) - action_bones(base_action)
    for name in stale:
        # Otherwise a bone that only the earlier bake animated keeps its pose from that bake.
        target.pose.bones[name].matrix_basis = still[name]
    try:
        scene.frame_set(1)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        with rest_pose(source, target):
            weapons = weapon_turns(source, target, bone_map, stance, rotation, graph, holds)
            # The long axis of each source weapon that the bake places; without a mesh, FromSoftware's bone X axis.
            lines = {name: weapon_axis(source, bone_map[name], graph) or Vector((1, 0, 0)) for name in holds}
            geometry = body_geometry(target, target_body, graph, {name: holder for name, (holder, anchor) in holds.items()}) \
                if settings.body_clearance or settings.arm_gap else None
            # The source's own torso, arms and hands show the clipping and the arm gaps that its animation already has.
            source_geometry = body_geometry(source, source_body, graph) if geometry else None
            # Each held weapon's long axis and how far it reaches along it, in both rigs.
            shapes = {(rig.name, bone): weapon_shape(rig, bone, graph) for name, hand, placed_in in in_hand
                      for rig, bone in ((target, name), (source, bone_map[name]))}
        grips, pairs, grip_notes = [], [], []
        for name, hand, placed_in in in_hand:
            source_name, source_hand = bone_map[name], bone_map[hand]
            # A weapon placed in the other hand keeps that place. One below its own hand can take the target's own
            # grip, as Owl's katana does, which rests a metre from his hand until his clips bring it in.
            if placed_in and (settings.weapon_grip != 'OWN' or hand not in {parent.name for parent in bones[name].parent_recursive}):
                continue
            item = dict(weapon=name, hand=hand, source=source_name, source_hand=source_hand, fingers=fingers_of(target, hand),
                        source_fingers=fingers_of(source, source_hand), axis=shapes[target.name, name][0])
            source_axis = shapes[source.name, source_name][0]
            if item['axis'] is None and source_axis is not None:
                # Without a mesh of its own, the blade lies where the bake turns the source's blade in the bone; a placed
                # weapon takes the source weapon's own turn.
                into = Quaternion() if placed_in else (target_rest[name].to_quaternion().inverted() @ stance.get(name, Quaternion()).inverted() @
                                                       rotation @ source_rest_rotation[source_name])
                item['axis'] = (weapons.get(name, Quaternion()).inverted() @ into) @ source_axis
            own = None
            if settings.weapon_grip == 'OWN':
                if base_action is not None and name in action_bones(base_action):
                    digits = [bone for bone in sorted(subtree(bones, hand) - subtree(bones, name) - placed)
                              if bone in models[target].fingers and bone in action_bones(base_action)]
                    own = clip_grip(target, base_action, hand, name, digits, still)
                if placed_in and (own is None or not own[3]):
                    # The bake already places it where the source holds its weapon; a hidden frame's place can be far off.
                    grip_notes.append(f"The target's own clip does not animate {name}, so it stays where the source holds "
                                      f"{source_name}." if own is None else
                                      f"The target's own clip hides {name} on every frame, so it stays where the source holds "
                                      f"{source_name}; a target clip that shows it gives its own grip.")
                    continue
                if own is None:
                    grip_notes.append(f"The target's own clip does not animate {name}, so it takes the source's grip.")
            if own is not None:
                item.update(mode='OWN', grip=own[0], own_fingers=own[1], frame=own[2], shown=own[3])
            elif len(item['fingers']) >= 2 and len(item['source_fingers']) >= 2:
                # From the target weapon bone's space to the source's: the source's turn that the bake gives this bone.
                model = (source_rest_rotation[source_name].inverted() @ rotation.inverted() @ stance.get(name, Quaternion()) @
                         target_rest[name].to_quaternion() @ weapons.get(name, Quaternion()))
                item.update(mode='SOURCE', model=model, ratio=knuckles(target, hand, item['fingers']).length /
                            knuckles(source, source_hand, item['source_fingers']).length)
            else:
                grip_notes.append(f'{name} keeps its place in {hand} from the rest pose: the hands have too few fingers to '
                                  'find a grip by.')
                continue
            grips.append(item)
        for name, hand, placed_in in in_hand if settings.second_hand else ():
            # The other hand, from shoulder to hand, joins on the frames where the source holds its weapon with both.
            other = 'R' if hand == target_body.get(('L', 'hand')) else 'L'
            chain = tuple(target_body.get((other, role)) for role in ('upperarm', 'forearm', 'hand'))
            source_name, source_hand = bone_map[name], bone_map[hand]
            source_off = bone_map.get(chain[2])
            (axis, reach), (source_axis, source_reach) = shapes[target.name, name], shapes[source.name, source_name]
            if not all(chain) or chain[1] not in subtree(bones, chain[0]) or chain[2] not in subtree(bones, chain[1]) or \
                    not source_off or None in (axis, reach, source_axis, source_reach):
                continue
            upper, fore, off = chain
            off_fingers, main_fingers = fingers_of(target, off), fingers_of(target, hand)
            source_off_fingers, source_main_fingers = fingers_of(source, source_off), fingers_of(source, source_hand)
            if not (off_fingers and main_fingers and source_off_fingers and source_main_fingers):
                continue
            off_knuckles = knuckles(target, off, off_fingers)
            source_unit = knuckles(source, source_off, source_off_fingers).length
            pairs.append(dict(side=other, weapon=name, hand=hand, chain=chain, source=source_name, axis=axis, reach=reach,
                              source_axis=source_axis, source_reach=source_reach, off_knuckles=off_knuckles,
                              main_knuckles=knuckles(target, hand, main_fingers), unit=off_knuckles.length,
                              source_unit=source_unit, ratio=off_knuckles.length / source_unit,
                              source_off_fingers=source_off_fingers, source_main_fingers=source_main_fingers,
                              busy=[weapon for weapon, holder, placed_there in in_hand if holder == off],
                              held=(subtree(bones, off) - placed).union(*(subtree(bones, weapon) for weapon, (holder, anchor)
                                                                           in holds.items() if holder == off)),
                              upper_part=subtree(bones, upper) - subtree(bones, fore) - placed,
                              fore_part=subtree(bones, fore) - subtree(bones, off) - placed))
        # The source bones that grips and second hands read, per frame.
        sampled = {bone for item in grips for bone in (item['source'], item['source_hand'], *item['source_fingers'])}
        sampled |= {bone for pair in pairs for bone in (pair['source'], *pair['source_off_fingers'], *pair['source_main_fingers'])}
        footprint = set()  # The source's hips, feet and hands, whose places the full-body bake keeps.
        if body:
            layout = body['target']
            ends = [layout['hips']] + [leg['foot'] for leg in layout['legs'].values()] + [arm['hand'] for arm in layout['arms'].values()]
            footprint = {body['direct'][name] for name in ends if name in body['direct']}
        grip_samples, source_frames, body_samples = [], [], []
        # Sample both rigs before assigning a new action; the original target clip
        # supplies animation for bones that deliberately remain unmapped.
        for i in range(count):
            source_frame = source_start + i * (source_count - 1) / max(1, count - 1)
            whole = int(math.floor(source_frame))
            scene.frame_set(whole, subframe=source_frame - whole)
            bpy.context.view_layer.update()
            source_poses = {bone.name: source.pose.bones[bone.name].matrix.copy() for bone in source.data.bones}
            if source_geometry:
                source_frames.append(source_poses)
            if sampled:
                grip_samples.append({bone: source_poses[bone] for bone in sampled})
            if footprint:
                body_samples.append({bone: source_poses[bone].translation.copy() for bone in footprint})
            if src_root:
                source_root_samples.append((src_root.location.copy(), src_root.rotation_euler.copy()))
            scene.frame_set(i + 1)
            bpy.context.view_layer.update()
            baseline = {b.name: target.pose.bones[b.name].matrix_basis.copy() for b in ordered}
            baseline_scales = {b.name: target.pose.bones[b.name].matrix.to_scale() for b in ordered}
            if dst_root:
                target_root_samples.append((dst_root.location.copy(), dst_root.rotation_euler.copy()))

            def turn(name):
                """Source bone's rotation change from rest, in target armature space."""
                delta = source_poses[name].to_quaternion() @ source_rest_rotation[name].inverted()
                return rotation @ delta @ rotation_inverse
            # The full-body bake's chain bones take the source chain's shape over their own bones.
            shaped = fullbody.turns(chains, source_poses, source_rest, target_rest, stance, rotation) if chains else {}

            def pose_of(bone):
                """A bone's armature-space pose, from its parent's pose in poses."""
                name = bone.name
                parent_pose = poses[bone.parent.name] if bone.parent else None
                keywords = dict(parent_matrix=parent_pose, parent_matrix_local=target_rest[bone.parent.name]) if bone.parent else {}
                if name in bone_map or name == carrier or name in shaped:
                    if name in shaped:
                        orientation = shaped[name]
                    elif name in bone_map:
                        orientation = (turn(bone_map[name]) @ stance.get(name, Quaternion()) @ target_rest[name].to_quaternion() @
                                       weapons.get(name, Quaternion()))
                    else:
                        # An unmapped carrier turns with the source bone above its hips and spine.
                        orientation = turn(source_carrier) @ target_rest[name].to_quaternion()
                    local_rest = target_rest[bone.parent.name].inverted_safe() @ target_rest[name] if bone.parent else target_rest[name]
                    head = parent_pose @ local_rest.translation if bone.parent else local_rest.translation.copy()
                    return Matrix.LocRotScale(head, orientation, baseline_scales[name])
                if name in connectors or settings.unmapped == 'REST':
                    return bone.convert_local_to_pose(still[name], target_rest[name], **keywords)
                return bone.convert_local_to_pose(baseline[name], target_rest[name], **keywords)

            poses = {}
            for bone in ordered:
                poses[bone.name] = pose_of(bone)
            if settings.body_translation and source_hips:
                # Move the carrier and everything below it so the hips follow the source hips.
                shift = source_poses[source_hips].translation - source_rest[source_hips].translation
                desired = target_rest[hips].translation + (rotation @ shift) * travel
                residual = desired - poses[hips].translation
                for name in carried:
                    poses[name].translation += residual
            for name in placing:
                # In the hand that holds the source weapon, turned and shown or hidden like it. The weapon's line
                # keeps its offset from that hand, scaled; along the line its grip stays in the hand, as a weapon in
                # its own hand does, while Godfrey's grip slides along his long axe.
                holder, anchor = holds[name]
                held = source_poses[bone_map[name]]
                scale = held.to_scale()
                if min(scale) >= .01:
                    facing[name] = rotation @ held.to_quaternion()
                turned = facing.get(name, rotation @ source_rest_rotation[bone_map[name]])
                line = turned @ lines[name]
                offset = rotation @ (held.translation - source_poses[anchor].translation) * travel
                # A source weapon hidden at 0 shrinks this one to HIDDEN, so that the bones below it keep a position.
                poses[name] = Matrix.LocRotScale(poses[holder].translation + offset - line * offset.dot(line),
                                                 turned @ weapons.get(name, Quaternion()), Vector([max(v, HIDDEN) for v in scale]))
                for bone in below[name]:
                    poses[bone.name] = pose_of(bone)
            for name in hiding:
                # Shrunk where it is, as FromSoftware clips hide a weapon. A bone below it follows it, and a mapped one,
                # which takes its own scale rather than its parent's, shrinks too.
                location, orientation, unused = poses[name].decompose()
                poses[name] = Matrix.LocRotScale(location, orientation, Vector((HIDDEN, HIDDEN, HIDDEN)))
                for bone in under[name]:
                    poses[bone.name] = pose_of(bone)
                    if bone.name in bone_map:
                        location, orientation, unused = poses[bone.name].decompose()
                        poses[bone.name] = Matrix.LocRotScale(location, orientation, Vector((HIDDEN, HIDDEN, HIDDEN)))
            pose_frames.append(poses)
        # The full-body bake keeps the feet on the source's footprint and the hands together where the source's are,
        # before the weapons go into their grips and the hands are kept clear of the body. Where the target takes the
        # source's root motion (see below), its feet stand where that motion puts them.
        ground = None
        if body and settings.root_motion in ('AUTO', 'SOURCE') and source_root_samples:
            to_rig = target.matrix_world.to_3x3().inverted()
            start_location, start_rotation = source_root_samples[0]
            ground = [(to_rig @ ((location - start_location) * factor), euler.z - start_rotation.z) for location, euler in source_root_samples]
        contacts = fullbody.keep_contacts(source, target, body, pose_frames, body_samples, travel, rate, rotation, carried, holds,
                                          placed, {hand for name, hand, placed_in in in_hand}, target_body.get('forward'),
                                          ground) if body else None
        # The second hands keep their baked turns relative to the weapons, which are the source's.
        baked = [{name: poses[name].to_quaternion() for pair in pairs for name in (pair['weapon'], pair['chain'][2])}
                 for poses in pose_frames]

        mode = settings.root_motion
        if mode == 'AUTO':
            mode = 'SOURCE' if source_root_samples else 'NONE'
            if mode == 'NONE' and carrier:
                start = pose_frames[0][carrier].translation
                distance = max((frame[carrier].translation - start).xy.length for frame in pose_frames)
                feet = [target_body[(side, 'foot')] for side in 'LR' if (side, 'foot') in target_body]
                legs = (target_rest[hips].translation - sum((target_rest[f].translation for f in feet), Vector()) / len(feet)).length \
                    if feet else target_rest[hips].translation.length
                if distance > .3 * legs:
                    mode = 'EXTRACT'
                    warnings.append(f'The source has no root motion; its {distance:.2f} travel became root motion.')
        if mode == 'SOURCE' and not source_root_samples:
            raise ValueError('The source has no root-motion object. Choose another root-motion option.')
        if mode == 'EXTRACT' and not carrier:
            raise ValueError('Extracting root motion needs mapped target hips.')

        if mode == 'TARGET':
            length = round(base_root.frame_range[1] - base_root.frame_range[0]) + 1 if base_root else 0
            if length != count:
                warnings.append("The target's original root motion was left out: " +
                                (f'it has {length} frames, the new clip {count}.' if base_root else 'the target has none.'))
                mode = 'NONE'
        root_values = None  # (world location, Z angle) per frame for the target's root object
        origin = target_root_samples[0] if target_root_samples else (Vector((0, 0, 0)), Vector((0, 0, 0)))
        if mode == 'EXTRACT':
            transforms = root_transforms([frame[carrier] for frame in pose_frames], settings.root_yaw)
            for frame, (transform, offset, angle) in zip(pose_frames, transforms):
                inverse = transform.inverted()
                for name in carried:
                    frame[name] = inverse @ frame[name]
            to_world = target.matrix_world.to_3x3()
            root_values = [(origin[0] + to_world @ offset, origin[1].z + angle) for transform, offset, angle in transforms]
        elif mode == 'SOURCE':
            # Root objects move in world space, where source and target face the same way.
            start_location, start_rotation = source_root_samples[0]
            root_values = [(origin[0] + (location - start_location) * factor, origin[1].z + euler.z - start_rotation.z)
                           for location, euler in source_root_samples]
        elif mode == 'TARGET':
            root_values = [(location.copy(), euler.z) for location, euler in target_root_samples]
        # Weapons into their grips before the hands are kept clear of the body, which moves them with what they hold.
        follow = settings.blade_follow / 100
        # A placed weapon that takes the target's own grip moves with its hand like any other.
        gripped = {item['weapon'] for item in grips}
        kept = set().union(*(subtree(bones, name) for name in holds if name not in gripped))
        grip_weapons(target, grips, pose_frames, grip_samples, follow, rate, kept, set(models[target].fingers))
        # Arms first, so that a hand they bring close to the body is still kept out of it.
        wanted = source_gaps(source, source_body, source_geometry, source_frames, geometry, bone_map) \
            if settings.arm_gap and source_geometry else {}
        closeness = keep_close(target, target_body, geometry, pose_frames, rate, wanted) if wanted else []
        clearing = settings.body_clearance and geometry
        allowed = source_clipping(source, source_body, source_geometry, source_frames, geometry, bone_map) \
            if clearing and source_geometry else None
        clearance = keep_clear(target, target_body, geometry, pose_frames, rate, allowed) if clearing else []
        # The other hand goes onto the weapon once the weapon's hand has its last place.
        seconds = second_hands(target, pairs, pose_frames, grip_samples, rate, rotation, baked)
        # Last, once the feet are final: FromSoftware's foot target chains stand on the feet, as on every frame of the
        # game's clips, whatever the source's own targets do. Each chain keeps its rest pose and moves as one, without
        # turning, so that its target sits on the foot, and the target turns with the foot.
        offsets = {name: target_rest[foot].inverted_safe() @ target_rest[name] for name, (foot, chain) in targets.items()}

        def at_rest(name, poses):
            bone = bones[name]
            keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=target_rest[bone.parent.name]) if bone.parent else {}
            return bone.convert_local_to_pose(still[name], target_rest[name], **keywords)
        for poses in pose_frames:
            for name, (foot, chain) in targets.items():
                for link in chain:
                    poses[link] = at_rest(link, poses)
                goal = poses[foot] @ offsets[name]
                shift = goal.translation - at_rest(name, poses).translation
                for link in chain:
                    poses[link].translation += shift
                poses[name] = goal

        channels, previous, keyed = {}, {}, set()
        tracked = {b.name for b in target.pose.bones if 'hkx_track_index' in b}
        bases = []
        for poses in pose_frames:
            frame = {}
            for bone in ordered:
                keywords = dict(parent_matrix=poses[bone.parent.name], parent_matrix_local=target_rest[bone.parent.name]) if bone.parent else {}
                frame[bone.name] = bone.convert_local_to_pose(poses[bone.name], target_rest[bone.name], invert=True, **keywords)
                if not same_pose(frame[bone.name], still[bone.name]):
                    keyed.add(bone.name)
            bases.append(frame)
        keyed |= tracked | computed
        for frame in bases:
            for bone in ordered:
                if bone.name not in keyed:
                    continue
                location, rotation_value, scale = frame[bone.name].decompose()
                if bone.name in previous and rotation_value.dot(previous[bone.name]) < 0:
                    rotation_value.negate()
                previous[bone.name] = rotation_value.copy()
                prefix = target.pose.bones[bone.name].path_from_id()
                for field, values in (('location', location), ('rotation_quaternion', rotation_value), ('scale', scale)):
                    channels.setdefault(prefix + '.' + field, []).append(tuple(values))
        action = write_action(target, 'Retarget ' + source.name + ' to ' + target.name, channels)
        for bone in target.pose.bones:
            bone.rotation_mode = 'QUATERNION'
            if bone.name not in keyed:
                bone.matrix_basis = still[bone.name]

        root_samples = None
        if root_values is not None or (mode == 'NONE' and dst_root):
            if dst_root is None:
                dst_root = bpy.data.objects.new('HKX_RootMotion', None)
                target.users_collection[0].objects.link(dst_root)
                dst_root.empty_display_type = 'ARROWS'
                dst_root['sekiro_root_motion'] = True
                target['sekiro_root_motion_object'] = dst_root.name
                target['sekiro_root_motion_data'] = dst_root
            if root_values is None:
                # Hold the root still so its old clip cannot play under the new motion.
                root_values = [(origin[0].copy(), origin[1].z)] * count
            dst_root.rotation_mode = 'XYZ'
            write_action(dst_root, action.name + ' RootMotion', {
                'location': [tuple(location) for location, angle in root_values],
                'rotation_euler': [(0.0, 0.0, angle) for location, angle in root_values]})
            if mode != 'NONE':
                root_samples = [[v.x, v.z, v.y, -angle] for v, angle in root_values]
        if target_document:
            document = dict(target_document)
            document.update(frameCount=count, frameRate=rate, duration=(count - 1) / rate)
            skeleton = document['skeleton']['bones']
            document['frames'] = []
            for poses in pose_frames:
                frame = []
                for index in document['trackBoneIndices']:
                    bone = skeleton[index]
                    parent = int(bone['parent'])
                    matrix = poses[skeleton[parent]['name']].inverted_safe() @ poses[bone['name']] if parent >= 0 else poses[bone['name']]
                    frame.append(_trs(matrix))
                document['frames'].append(frame)
            document['rootMotion'] = root_samples
            if root_samples is None:
                document.update(rootUp=None, rootForward=None)
            elif mode == 'SOURCE' and source_document and source_document.get('rootUp'):
                document.update(rootUp=source_document.get('rootUp'), rootForward=source_document.get('rootForward'))
            else:
                document.update(rootUp=target_document.get('rootUp') or [0.0, 1.0, 0.0, 0.0],
                                rootForward=target_document.get('rootForward') or [0.0, 0.0, 1.0, 0.0])
            write_motion(target, document)
            target['sekiro_frame_count'] = count
            target['sekiro_frame_rate'] = rate
            set_export_target(scene, target)
        scene.frame_start = 1
        scene.frame_end = count
        scene.render.fps = max(1, round(rate))
        scene.render.fps_base = scene.render.fps / rate
        untracked = sorted((set(bone_map) | set(hiding)) - tracked) if tracked else []
        if untracked:
            warnings.append(f'{len(untracked)} mapped or hidden bones have no HKX track in the target clip; '
                            'export with the "Original tracks + keyed bones" track set to include them.')
        owned = {item['weapon'] for item in grips if item['mode'] == 'OWN'}
        notes = [f"{name} turned {math.degrees(turn.angle):.0f}° so that its weapon points like the source's."
                 for name, turn in sorted(weapons.items()) if math.degrees(turn.angle) >= .5 and name not in owned]
        notes += [f'{name} is placed in {holder}, where the source holds {bone_map[name]}.'
                  for name, (holder, anchor) in sorted(holds.items()) if name not in owned]
        notes += [f'{name} is hidden on every frame.' for name in hiding]
        size = uniform_scale(target)
        for item in grips:
            name, hand = item['weapon'], item['hand']
            if item['mode'] == 'OWN':
                turned = (f"the wrist turns by up to {item['turn']:.0f}° so that the blade points " +
                          ("as the source's does" if follow >= 1 else f"{follow:.0%} of the way to the source's")) \
                    if item['turn'] >= .5 else "the wrist turns as the source's does"
                notes.append(f"{name} sits in {hand} as in the target's own clip on frame {item['frame']}, with its "
                             f'fingers; {turned}.')
                if not item['shown']:
                    warnings.append(f"The target's own clip hides {name} on every frame, so its place in {hand} comes from "
                                    'a hidden frame and can be off; check it, or bake with the source\'s grip.')
            else:
                notes.append(f"{name} sits in {hand} where the source's {item['source']} sits in its hand, scaled to the hand, "
                             f"up to {item['moved'] * size * 100:.1f} cm from where the rest pose puts it.")
                if item['hidden_source']:
                    notes.append(f"The source hides {item['source']} on every frame; its place in the hand comes from there.")
        notes += grip_notes
        for item in seconds:
            hand = 'Left' if item['side'] == 'L' else 'Right'
            if item['frames']:
                notes.append(f"{hand} hand goes onto {item['weapon']} on frames {spans(item['frames'])}, where the source "
                             f"holds {item['source']} with both hands.")
            if item['short']:
                warnings.append(f"{hand} hand stops up to {item['gap'] * 100:.1f} cm short of its place on {item['weapon']} "
                                f"on frames {spans(item['short'])}: the arm does not reach.")
        for item in clearance:
            hand = 'Left' if item['side'] == 'L' else 'Right'
            if item['frames']:
                notes.append(f"{hand} hand kept out of the body on frames {spans(item['frames'])}, by up to {item['largest'] * 100:.1f} cm.")
            if item['kept'] >= .001:
                notes.append(f"{hand} hand keeps up to {item['kept'] * 100:.1f} cm of clipping where the source's own hand goes into its body.")
            if item['unresolved']:
                warnings.append(f"{hand} hand left inside the body on frames {spans(item['unresolved'])}: "
                                'it goes in too deep to move out through the arm.')
        if any(item['frames'] for item in clearance) and not source_geometry:
            notes.append('The source has no body mesh to compare with, so clipping already in its animation was removed too.')
        for item in closeness:
            hand = 'Left' if item['side'] == 'L' else 'Right'
            if item['frames']:
                notes.append(f"{hand} arm turned in toward the body on frames {spans(item['frames'])}, by up to "
                             f"{item['angle']:.0f}°, {item['largest'] * 100:.1f} cm at the hand, to stand as close as the source's.")
            if item['gripped']:
                notes.append(f"{hand} arm kept as it is on frames {spans(item['gripped'])}, where both hands are together.")
        if settings.arm_gap and geometry and not wanted:
            reason = 'the source has no body mesh' if not source_geometry else 'no arm has a mesh in both rigs'
            notes.append(f'Arm distances to the body were not compared: {reason}.')
        if targets:
            notes.append(f"{' and '.join(sorted(targets))} follow the feet, with the bones above them standing upright "
                         "over the feet, as in the game's clips.")
        if body:
            shaped_bones, others = len(body['direct']) + len(chains), body['others']
            origin = 'the bone list' if body['listed'] else 'automatic matching'
            notes.insert(0, f"Full body (experimental): {shaped_bones} body bones follow the source's body chains; " +
                            (f'1 other bone takes its source bone from {origin}.' if others == 1 else
                             f'{others} other bones take their source bones from {origin}.'))
            for rig, layout in ((target, body['target']), (source, body['source'])):
                if layout['shape']:
                    notes.append(f"Found by the skeleton's shape, not by name, in {rig.name}: {', '.join(fullbody.parts(layout['shape']))}.")
            if body['unpaired']:
                notes.append(f"{', '.join(body['unpaired'])} {'has' if len(body['unpaired']) == 1 else 'have'} no counterpart in the "
                             "source and do" + ('es' if len(body['unpaired']) == 1 else '') + " what Unmapped bones says.")
            if contacts['dropped']:
                notes.append(f"Pelvis lowered by up to {contacts['drop'] * 100:.1f} cm on frames {spans(contacts['dropped'])}, so that "
                             "the legs reach the source's footprint.")
            widths = [item for item in contacts['feet'] if abs(item['outward']) >= .0005]
            if widths:
                notes.append(f"The source's footprint is set to {target.name}'s own hip width: " + ', '.join(
                    f"{'left' if item['side'] == 'L' else 'right'} foot {abs(item['outward']) * 100:.1f} cm "
                    f"{'out' if item['outward'] > 0 else 'in'}" for item in widths) + '.')
            for item in contacts['feet']:
                foot = 'Left' if item['side'] == 'L' else 'Right'
                if item['moved'] >= .0005:  # Where the chain transfer already puts the foot there, there is nothing to tell.
                    notes.append(f"{foot} foot kept on the source's footprint, scaled by leg length, up to {item['moved'] * 100:.1f} cm "
                                 "from where the chain transfer puts it.")
                if item['short']:
                    warnings.append(f"{foot} foot stops up to {item['gap'] * 100:.1f} cm short of the source's footprint on frames "
                                    f"{spans(item['short'])}: the leg does not reach.")
            for item in contacts['hands']:
                hand = 'Left' if item['side'] == 'L' else 'Right'
                notes.append(f"{hand} hand moved by up to {item['moved'] * 100:.1f} cm on frames {spans(item['frames'])}, where the "
                             "source's hands are together, to keep them as far apart as the source's.")
        result = dict(source=source.name, target=target.name, mapped=len(bone_map), frames=count, scale=factor,
                      action=action.name, root_motion=mode, rest_mode=settings.rest_mode, carrier=carrier or '',
                      keyed=len(keyed), untracked=untracked, warnings=warnings, notes=notes, clearance=clearance,
                      source_clipping=bool(clearing and source_geometry), closeness=closeness, arm_gaps=bool(wanted),
                      weapons={name: round(math.degrees(turn.angle), 1) for name, turn in weapons.items()},
                      placed={name: holder for name, (holder, anchor) in holds.items()}, hidden=hiding,
                      weapon_grip=settings.weapon_grip, blade_follow=follow,
                      grips={item['weapon']: dict(hand=item['hand'], mode=item['mode'], frame=item.get('frame'),
                                                  turn=round(item['turn'], 2), moved=round(item['moved'] * size, 5))
                             for item in grips},
                      second_hands=seconds,
                      foot_targets={name: targets[name][0] for name in sorted(targets)},
                      method='World-space FK from the source rest pose' + (' with matched rest stances' if align else '') +
                             '; target proportions retained' if not body else
                             'Full body: body chains transferred by share of their length' +
                             (' with matched rest stances' if align else '') + '; feet on the scaled source footprint',
                      bake_method='BODY' if body else 'BONES',
                      body=dict(target_shape=body['target']['shape'], source_shape=body['source']['shape'],
                                direct=len(body['direct']), chains=len(chains), others=body['others'], listed=body['listed'],
                                unpaired=body['unpaired'], **contacts) if body else None)
        scene['sekiro_retarget_report'] = json.dumps(result)
        return result
    except Exception:
        for obj, current in replaced:
            assign_action(obj, current)
        raise
    finally:
        scene.frame_set(min(max(original_frame, 1), count))
        bpy.context.view_layer.update()
