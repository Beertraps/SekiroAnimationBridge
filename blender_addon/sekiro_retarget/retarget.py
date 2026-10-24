"""Bake retargeted FK motion onto a target rig, keeping its skeleton, proportions and HKX tracks.

Each mapped target bone takes its source bone's world-space rotation change
from the source rest pose. With matched rest stances, that change starts from
a target pose whose limbs point like the source's rest pose, so an A-pose
target follows a T-pose source without lowered arms. Bone lengths stay the
target's own. Body travel goes to the bone above both the pelvis and the
spine (Root, RootPos or Master in FromSoftware rigs), so legs and upper body
move together, scaled by leg length. Root motion comes from the source's root
object, from the body's travel, from the target's original clip, or is left out.
"""
import base64
import json
import math
import re
import statistics
import textwrap
import zlib
import bpy
from mathutils import Matrix, Quaternion, Vector
from . import mapping as matching

BONE_CURVE = re.compile(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]')


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
    """
    if current is not None and not current.get('sekiro_retarget'):
        rig[key] = current
        return current
    recorded = rig.get(key)
    return recorded if isinstance(recorded, bpy.types.ID) else current


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


def action_bones(action):
    """Names of the bones an action animates, in legacy and Blender 4.4+ layered actions."""
    if action is None:
        return set()
    layers = getattr(action, 'layers', None)
    curves = [curve for layer in layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves] \
        if layers else list(getattr(action, 'fcurves', ()))
    matches = (BONE_CURVE.match(curve.data_path) for curve in curves)
    return {re.sub(r'\\(.)', r'\1', match.group(1)) for match in matches if match}


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
    bone_map = {row.target: row.source for row in settings.rows if row.enabled and row.source}
    if not bone_map:
        raise ValueError('Run Match bones, then select or assign at least one source bone.')
    if len(set(bone_map.values())) != len(bone_map):
        raise ValueError('A source bone is assigned more than once. Review the bone list first.')
    for t, s in bone_map.items():
        if t not in target.data.bones or s not in source.data.bones:
            raise ValueError('The bone list is stale. Run Match bones again.')
    for rig in (source, target):
        scale = rig.matrix_world.to_scale()
        if min(scale) <= 0 or max(scale) - min(scale) > 1e-4:
            raise ValueError('Source and target armatures need positive uniform object scale.')
    target_text = bake_base(target, 'sekiro_retarget_base_text', source_text(target))
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
    computed = set(bone_map) | connectors | ({carrier} if carrier else set())
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
    stance = stance_alignment(source, target, bone_map, matching.limb_links(rig_bones(target)), rotation) if align else {}
    ordered = sorted(bones, key=lambda b: len(b.parent_recursive))
    source_rest = {b.name: b.matrix_local.copy() for b in source.data.bones}
    source_rest_rotation = {name: matrix.to_quaternion() for name, matrix in source_rest.items()}
    target_rest = {b.name: b.matrix_local.copy() for b in ordered}
    carried = {carrier} | {b.name for b in bones if carrier in {p.name for p in b.parent_recursive}} if carrier else set()
    # Bridge imports leave unanimated bones at their HKX reference pose, a fraction of a
    # millimetre from the edit-bone rest. That pose, not identity, is where they rest.
    animated = action_bones(base_action) | action_bones(target_action)
    still = {b.name: Matrix.Identity(4) if b.name in animated else target.pose.bones[b.name].matrix_basis.copy() for b in ordered}
    source_root_samples, target_root_samples = [], []
    pose_frames = []
    original_frame = scene.frame_current
    replaced = [(obj, current) for obj, current, base in ((target, target_action, base_action), (dst_root, root_action, base_root))
                if obj and base is not None and base != current]
    for obj, current in replaced:
        assign_action(obj, base_action if obj == target else base_root)
    try:
        # Sample both rigs before assigning a new action; the original target clip
        # supplies animation for bones that deliberately remain unmapped.
        for i in range(count):
            source_frame = source_start + i * (source_count - 1) / max(1, count - 1)
            whole = int(math.floor(source_frame))
            scene.frame_set(whole, subframe=source_frame - whole)
            bpy.context.view_layer.update()
            source_poses = {bone.name: source.pose.bones[bone.name].matrix.copy() for bone in source.data.bones}
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

            poses = {}
            for bone in ordered:
                name = bone.name
                parent_pose = poses[bone.parent.name] if bone.parent else None
                keywords = dict(parent_matrix=parent_pose, parent_matrix_local=target_rest[bone.parent.name]) if bone.parent else {}
                if name in bone_map or name == carrier:
                    if name in bone_map:
                        orientation = turn(bone_map[name]) @ stance.get(name, Quaternion()) @ target_rest[name].to_quaternion()
                    else:
                        # An unmapped carrier turns with the source bone above its hips and spine.
                        orientation = turn(source_carrier) @ target_rest[name].to_quaternion()
                    local_rest = target_rest[bone.parent.name].inverted_safe() @ target_rest[name] if bone.parent else target_rest[name]
                    head = parent_pose @ local_rest.translation if bone.parent else local_rest.translation.copy()
                    poses[name] = Matrix.LocRotScale(head, orientation, baseline_scales[name])
                elif name in connectors or settings.unmapped == 'REST':
                    poses[name] = bone.convert_local_to_pose(still[name], target_rest[name], **keywords)
                else:
                    poses[name] = bone.convert_local_to_pose(baseline[name], target_rest[name], **keywords)
            if settings.body_translation and source_hips:
                # Move the carrier and everything below it so the hips follow the source hips.
                shift = source_poses[source_hips].translation - source_rest[source_hips].translation
                desired = target_rest[hips].translation + (rotation @ shift) * travel
                residual = desired - poses[hips].translation
                for name in carried:
                    poses[name].translation += residual
            pose_frames.append(poses)

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
        untracked = sorted(set(bone_map) - tracked) if tracked else []
        if untracked:
            warnings.append(f'{len(untracked)} mapped bones have no HKX track in the target clip; '
                            'export with the "Original tracks + keyed bones" track set to include them.')
        result = dict(source=source.name, target=target.name, mapped=len(bone_map), frames=count, scale=factor,
                      action=action.name, root_motion=mode, rest_mode=settings.rest_mode, carrier=carrier or '',
                      keyed=len(keyed), untracked=untracked, warnings=warnings,
                      method='World-space FK from the source rest pose' + (' with matched rest stances' if align else '') +
                             '; target proportions retained')
        scene['sekiro_retarget_report'] = json.dumps(result)
        return result
    except Exception:
        for obj, current in replaced:
            assign_action(obj, current)
        raise
    finally:
        scene.frame_set(min(max(original_frame, 1), count))
        bpy.context.view_layer.update()
