"""Create or sample a Sekiro animation armature using Blender's built-in Python."""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import textwrap
import zlib
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


def game_to_bl_trs(sample):
    x, y, z, w = sample["rotation"]
    rotation = Quaternion((float(w), -float(x), -float(z), -float(y)))
    rotation.normalize()
    translation = Vector((float(sample["translation"][0]), float(sample["translation"][2]), float(sample["translation"][1])))
    scale = Vector((float(sample["scale"][0]), float(sample["scale"][2]), float(sample["scale"][1])))
    return translation, rotation, scale


def bl_to_game_trs(translation, rotation, scale):
    rotation = rotation.normalized()
    return {
        "translation": [float(translation.x), float(translation.z), float(translation.y)],
        "rotation": [float(-rotation.x), float(-rotation.z), float(-rotation.y), float(rotation.w)],
        "scale": [float(scale.x), float(scale.z), float(scale.y)],
    }


def trs_matrix(sample):
    translation, rotation, scale = game_to_bl_trs(sample)
    return Matrix.LocRotScale(translation, rotation, scale)


def make_active(context, obj):
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def write_action(obj, name, channels, frames=None):
    """Build sampled curves in bulk, including Blender 4.4+ action slots.

    Samples are keyed on frames 1, 2, 3, ... unless frames gives each sample's scene frame.
    """
    action = bpy.data.actions.new(name)
    if hasattr(action, "slots"):
        slot = action.slots.new("OBJECT", obj.name)
        bag = action.layers.new("Animation").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
        curves = bag.fcurves
    else:
        curves = action.fcurves
    for path, samples in channels.items():
        if not samples:
            continue
        for axis in range(len(samples[0])):
            curve = curves.new(path, index=axis)
            curve.keyframe_points.add(len(samples))
            coordinates = [value for i, sample in enumerate(samples)
                           for value in (float(frames[i] if frames else i + 1), float(sample[axis]))]
            curve.keyframe_points.foreach_set("co", coordinates)
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
            curve.update()
    obj.animation_data_create()
    obj.animation_data.action = action
    if hasattr(action, "slots"):
        obj.animation_data.action_slot = slot
    return action


def import_motion(motion):
    skeleton = motion["skeleton"]
    bones = skeleton["bones"]
    frame_count = int(motion["frameCount"])
    if not bones or len(bones) != int(skeleton["boneCount"]):
        raise ValueError("Skeleton bone table is missing or inconsistent.")
    if motion["skeletonName"] != skeleton["name"]:
        raise ValueError("Animation and skeleton names do not match.")
    if len(motion["frames"]) != frame_count:
        raise ValueError("Motion frame count does not match its frame data.")

    rest_local = [trs_matrix(bone) for bone in bones]
    rest_world = []
    for index, bone in enumerate(bones):
        parent_index = int(bone["parent"])
        if parent_index >= index:
            raise ValueError("Skeleton bones are not in parent-before-child order.")
        rest_world.append(rest_world[parent_index] @ rest_local[index] if parent_index >= 0 else rest_local[index].copy())

    clip_name = Path(motion["clip"]).stem
    scene = bpy.context.scene
    collection = bpy.data.collections.new("Sekiro - " + clip_name)
    scene.collection.children.link(collection)
    armature_data = bpy.data.armatures.new(skeleton["name"])
    rig = bpy.data.objects.new(skeleton["name"], armature_data)
    collection.objects.link(rig)
    rig.show_in_front = True
    armature_data.display_type = "STICK"
    make_active(bpy.context, rig)
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = []
    for bone, rest_matrix in zip(bones, rest_world):
        edit_bone = armature_data.edit_bones.new(bone["name"])
        # A new edit bone has zero length. Set a length before assigning its matrix,
        # otherwise Blender cannot retain the intended rest orientation.
        edit_bone.length = 0.08
        location, rotation, unused_scale = rest_matrix.decompose()
        edit_bone.matrix = Matrix.LocRotScale(location, rotation, Vector((1.0, 1.0, 1.0)))
        edit_bone.use_connect = False
        parent_index = int(bone["parent"])
        if parent_index >= 0:
            edit_bone.parent = edit_bones[parent_index]
        edit_bones.append(edit_bone)

    bpy.ops.object.mode_set(mode="POSE")
    print("Skeleton ready: {} bones".format(len(bones)), flush=True)
    for bone in bones:
        pose_bone = rig.pose.bones[bone["name"]]
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone["hkx_bone_index"] = int(bone["index"])

    track_to_bone = [int(index) for index in motion["trackBoneIndices"]]
    track_names = motion["trackNames"]
    if len(track_to_bone) != int(motion["trackCount"]) or len(track_names) != len(track_to_bone):
        raise ValueError("Animation track map is missing or inconsistent.")
    if len(set(track_to_bone)) != len(track_to_bone):
        raise ValueError("This prototype does not support duplicate bone tracks.")
    if any(index < 0 or index >= len(bones) for index in track_to_bone):
        raise ValueError("Animation refers to a bone outside the supplied skeleton.")
    for track_index, bone_index in enumerate(track_to_bone):
        pose_bone = rig.pose.bones[bones[bone_index]["name"]]
        pose_bone["hkx_track_index"] = track_index
        pose_bone["hkx_track_name"] = track_names[track_index]

    source_text = bpy.data.texts.new("Sekiro Source - " + clip_name + ".json")
    encoded = base64.b64encode(zlib.compress(json.dumps(motion, separators=(",", ":")).encode("utf-8"))).decode("ascii")
    source_text.from_string("SEKIRO_BRIDGE_ZLIB_V1\n" + "\n".join(textwrap.wrap(encoded, 120)))
    print("Source animation metadata embedded", flush=True)
    rig["sekiro_animation_bridge"] = 1
    rig["sekiro_bridge_source_text"] = source_text.name
    rig["sekiro_bridge_source_text_data"] = source_text
    rig["sekiro_clip"] = motion["clip"]
    rig["sekiro_skeleton"] = skeleton["name"]
    rig["sekiro_frame_count"] = frame_count
    rig["sekiro_frame_rate"] = float(motion["frameRate"])

    rig.animation_data_create()
    frame_rate = max(float(motion["frameRate"]), 1.0)
    scene.render.fps = max(1, round(frame_rate))
    scene.render.fps_base = scene.render.fps / frame_rate
    scene.frame_start = 1
    scene.frame_end = frame_count
    scene["sekiro_bridge_active_rig"] = rig.name
    scene["sekiro_bridge_export_rig"] = rig
    scene["sekiro_bridge_source_text"] = source_text.name

    root_motion = motion.get("rootMotion")
    root_object = None
    if root_motion is not None:
        if len(root_motion) != frame_count:
            raise ValueError("Root-motion sample count does not match frame count.")
        root_object = bpy.data.objects.new("HKX_RootMotion", None)
        collection.objects.link(root_object)
        root_object.empty_display_type = "ARROWS"
        root_object.empty_display_size = 0.15
        root_object.rotation_mode = "XYZ"
        root_object["sekiro_root_motion"] = True
        root_object["hkx_role"] = "hkaDefaultAnimatedReferenceFrame"
        root_object["hkx_up"] = json.dumps(motion.get("rootUp"))
        root_object["hkx_forward"] = json.dumps(motion.get("rootForward"))
        root_object.animation_data_create()
        rig["sekiro_root_motion_object"] = root_object.name
        rig["sekiro_root_motion_data"] = root_object

    bone_to_track = {bone_index: track_index for track_index, bone_index in enumerate(track_to_bone)}
    channels = {}
    previous_rotations = {}
    for frame_index, frame in enumerate(motion["frames"]):
        if len(frame) != len(track_to_bone):
            raise ValueError("Frame {} has the wrong number of tracks.".format(frame_index))
        local_matrices = [matrix.copy() for matrix in rest_local]
        for track_index, bone_index in enumerate(track_to_bone):
            local_matrices[bone_index] = trs_matrix(frame[track_index])
        world_matrices = []
        for index, bone in enumerate(bones):
            parent_index = int(bone["parent"])
            world_matrices.append(
                world_matrices[parent_index] @ local_matrices[index]
                if parent_index >= 0 else local_matrices[index].copy()
            )

        for index, bone in enumerate(bones):
            if index not in bone_to_track and frame_index > 0:
                continue
            pose_bone = rig.pose.bones[bone["name"]]
            parent_index = int(bone["parent"])
            if parent_index >= 0:
                basis = pose_bone.bone.convert_local_to_pose(
                    world_matrices[index],
                    pose_bone.bone.matrix_local,
                    parent_matrix=world_matrices[parent_index],
                    parent_matrix_local=pose_bone.parent.bone.matrix_local,
                    invert=True,
                )
            else:
                basis = pose_bone.bone.convert_local_to_pose(
                    world_matrices[index], pose_bone.bone.matrix_local, invert=True
                )
            if frame_index == 0:
                pose_bone.matrix_basis = basis
            if index in bone_to_track:
                location, rotation, scale = basis.decompose()
                previous = previous_rotations.get(index)
                if previous is not None and rotation.dot(previous) < 0:
                    rotation.negate()
                previous_rotations[index] = rotation.copy()
                prefix = pose_bone.path_from_id()
                for field, values in (("location", location), ("rotation_quaternion", rotation), ("scale", scale)):
                    channels.setdefault(prefix + "." + field, []).append(tuple(values))

    print("Animation sampled: {} frames; creating curves".format(frame_count), flush=True)
    write_action(rig, clip_name + "_Sekiro", channels)
    if root_object:
        write_action(root_object, clip_name + "_RootMotion", {
            "location": [(float(s[0]), float(s[2]), float(s[1])) for s in root_motion],
            "rotation_euler": [(0.0, 0.0, -float(s[3])) for s in root_motion],
        })

    bpy.ops.object.mode_set(mode="OBJECT")
    make_active(bpy.context, rig)
    scene.frame_set(1)
    print("Editable animation ready", flush=True)
    return rig


DONOR_KINDS = ("objects", "collections", "actions", "texts", "armatures")
SCENE_RIG_KEYS = ("sekiro_bridge_active_rig", "sekiro_bridge_export_rig", "sekiro_bridge_source_text")


def donor_name(name, kind):
    """Name of a donor's data block: 'Donor ' before objects, actions and armatures, 'Donor' in collections and texts."""
    if kind == "collections":
        return re.sub(r"^Sekiro\b", "Donor", name) if name.startswith("Sekiro") else "Donor " + name
    if kind == "texts":
        if name.startswith("Sekiro Source - "):
            return "Sekiro Source - Donor - " + name[len("Sekiro Source - "):]
        stem, dot, suffix = name.rpartition(".")
        return "{} - Donor.{}".format(stem, suffix) if dot else name + " - Donor"
    return "Donor " + name


def character_span(rig):
    """Lowest and highest X of a bridge rig's meshes in the evaluated scene, or of its bones when it has none."""
    deps = bpy.context.evaluated_depsgraph_get()
    points = [obj.matrix_world @ Vector(corner) for obj in rig.children_recursive if obj.get("sekiro_flver_preview")
              for corner in obj.evaluated_get(deps).bound_box]
    if not points:
        points = [rig.matrix_world @ point for bone in rig.pose.bones for point in (bone.head, bone.tail)]
    return min(point.x for point in points), max(point.x for point in points)


def import_donor(motion, target, manifest=None):
    """Add a second character beside the target, for the retarget add-on to bake from.

    The target keeps the scene: its frame range, frame rate, export rig and
    embedded metadata stay as a single import leaves them. The donor's data is
    named "Donor ..." so that rigs of the same name, such as c0000 from two
    games, stay apart. It stands beside the target through delta transforms,
    which leave its keys and the add-on's armature-space bake unchanged.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from blender_character import import_character, setup_view
    scene = bpy.context.scene
    settings = scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end
    keys = {key: scene[key] for key in SCENE_RIG_KEYS if key in scene}
    before = {kind: set(getattr(bpy.data, kind)) for kind in DONOR_KINDS}
    rig = import_motion(motion)
    if manifest:
        import_character(manifest, rig)

    renamed = {kind: {} for kind in DONOR_KINDS}
    for kind in DONOR_KINDS:
        taken = {item.name for item in before[kind]}
        for item in [item for item in getattr(bpy.data, kind) if item not in before[kind]]:
            # Blender appends .001 when the target already has the name the importer asked for.
            match = re.fullmatch(r"(.+)\.\d{3,}", item.name)
            old, item.name = item.name, donor_name(match.group(1) if match and match.group(1) in taken else item.name, kind)
            renamed[kind][old] = item.name
    root = root_motion_object(rig)
    rig["sekiro_bridge_source_text"] = rig["sekiro_bridge_source_text_data"].name
    if root is not None:
        rig["sekiro_root_motion_object"] = root.name
    if "sekiro_preview_meshes" in rig:
        objects = renamed["objects"]
        rig["sekiro_preview_meshes"] = json.dumps([objects.get(name, name) for name in json.loads(rig["sekiro_preview_meshes"])])
    for obj in (rig, root):
        slot = getattr(obj.animation_data, "action_slot", None) if obj is not None and obj.animation_data else None
        if slot is not None and hasattr(slot, "name_display"):
            slot.name_display = obj.name

    scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end = settings
    for key in SCENE_RIG_KEYS:
        if key in keys:
            scene[key] = keys[key]
        elif key in scene:
            del scene[key]
    scene["sekiro_bridge_retarget_source"] = rig
    scene.frame_set(1)
    bpy.context.view_layer.update()
    low, high = character_span(target)
    donor_low, donor_high = character_span(rig)
    offset = high - donor_low + max(0.5, 0.25 * max(high - low, donor_high - donor_low))
    for obj in (rig, root):
        if obj is not None:
            obj.delta_location = (offset, 0.0, 0.0)
    bpy.context.view_layer.update()
    if any(obj.get("sekiro_flver_preview") for obj in scene.objects):
        setup_view(target)
    else:
        make_active(bpy.context, target)
        scene.frame_set(1)
    print("Added {} beside {}, {:.2f} m along X".format(rig.name, target.name, offset), flush=True)
    return rig


def import_preview_model(preview_data_path: Path, rig, texture_path: Path | None = None):
    """Create an optionally textured FLVER mesh and bind it to the imported animation armature."""
    import numpy as np

    with np.load(str(preview_data_path), allow_pickle=False) as preview:
        positions = np.asarray(preview["positions"], dtype=np.float32)
        bone_indices = np.asarray(preview["bone_indices"], dtype=np.int32)
        bone_weights = np.asarray(preview["bone_weights"], dtype=np.float32)
        uvs = np.asarray(preview["uvs"], dtype=np.float32)
        faces = np.asarray(preview["faces"], dtype=np.int32)
        face_materials = np.asarray(preview["face_materials"], dtype=np.int32)
        bone_names = [str(name) for name in preview["bone_names"].tolist()]
        material_names = [str(name) for name in preview["material_names"].tolist()]

    if positions.ndim != 2 or positions.shape[1] != 3 or len(positions) == 0:
        raise ValueError("FLVER preview has invalid vertex positions.")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("FLVER preview has no valid triangle faces.")
    if bone_indices.shape != bone_weights.shape or bone_indices.shape != (len(positions), 4):
        raise ValueError("FLVER preview skin data is missing or inconsistent.")
    if len(uvs) != len(positions):
        raise ValueError("FLVER preview UV data does not match its vertices.")

    rig_bone_names = {bone.name for bone in rig.data.bones}
    used_bone_indices = set()
    for influence in range(4):
        used_bone_indices.update(
            int(index)
            for index, weight in zip(bone_indices[:, influence], bone_weights[:, influence])
            if weight > 1e-6
        )
    invalid_indices = [index for index in used_bone_indices if index < 0 or index >= len(bone_names)]
    if invalid_indices:
        raise ValueError("FLVER preview refers to invalid skeleton bone indices: {}".format(sorted(invalid_indices)))
    missing_bones = sorted({bone_names[index] for index in used_bone_indices if bone_names[index] not in rig_bone_names})
    if missing_bones:
        raise ValueError(
            "The FLVER is not using the selected animation skeleton. These weighted FLVER bones are missing from "
            "the animation rig: {}".format(", ".join(missing_bones[:20]))
        )

    # Sekiro uses Y-up and a left-handed basis. The animation bridge maps positions to Blender by swapping Y/Z.
    blender_vertices = [(float(x), float(z), float(y)) for x, y, z in positions]
    # The Y/Z swap reflects the basis, so reverse each triangle's winding to preserve its front face.
    blender_faces = [(int(face[0]), int(face[2]), int(face[1])) for face in faces]

    mesh_data = bpy.data.meshes.new("Sekiro Preview Mesh")
    mesh_data.from_pydata(blender_vertices, [], blender_faces)
    mesh_data.update()
    mesh_obj = bpy.data.objects.new("Sekiro FLVER Preview", mesh_data)
    rig.users_collection[0].objects.link(mesh_obj)
    mesh_obj.parent = rig
    mesh_obj.matrix_parent_inverse = Matrix.Identity(4)

    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    for polygon in mesh_data.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh_data.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = (float(uvs[vertex_index, 0]), 1.0 - float(uvs[vertex_index, 1]))

    preview_image = None
    if texture_path is not None:
        texture_path = texture_path.resolve()
        if not texture_path.is_file():
            raise FileNotFoundError("Preview texture not found: {}".format(texture_path))
        try:
            preview_image = bpy.data.images.load(str(texture_path), check_existing=True)
            preview_image.pack()
        except Exception as exc:
            raise RuntimeError(
                "Blender could not read the selected preview texture. Use a PNG, TGA, JPEG, BMP, or TIFF image; "
                "convert DDS textures to one of those formats for Blender versions without native DDS support."
            ) from exc

    if not material_names:
        material_names = ["Sekiro Preview Material"]
    for index, name in enumerate(material_names):
        material = bpy.data.materials.new(name="Sekiro Preview - {}".format(name))
        material.diffuse_color = (0.55, 0.42, 0.32, 1.0)
        material.use_nodes = True
        if preview_image is not None:
            nodes = material.node_tree.nodes
            shader = nodes.get("Principled BSDF")
            image_node = nodes.new("ShaderNodeTexImage")
            image_node.image = preview_image
            image_node.label = "User-selected preview texture"
            material.node_tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
            if "Alpha" in image_node.outputs and "Alpha" in shader.inputs:
                material.node_tree.links.new(image_node.outputs["Alpha"], shader.inputs["Alpha"])
        mesh_data.materials.append(material)

    for polygon_index, polygon in enumerate(mesh_data.polygons):
        if polygon_index < len(face_materials):
            material_index = int(face_materials[polygon_index])
            polygon.material_index = max(0, min(material_index, len(mesh_data.materials) - 1))

    groups = {}
    for bone_index in sorted(used_bone_indices):
        bone_name = bone_names[bone_index]
        groups[bone_index] = mesh_obj.vertex_groups.new(name=bone_name)
    for bone_index, group in groups.items():
        vertex_indices = []
        weights = []
        for influence in range(4):
            matches = np.flatnonzero((bone_indices[:, influence] == bone_index) & (bone_weights[:, influence] > 1e-6))
            if matches.size:
                vertex_indices.extend(int(index) for index in matches)
                weights.extend(float(bone_weights[index, influence]) for index in matches)
        if vertex_indices:
            # Blender's vertex group API accepts one scalar per add. Group by equal weight to retain FLVER weights.
            by_weight = {}
            for vertex_index, weight in zip(vertex_indices, weights):
                by_weight.setdefault(round(weight, 7), []).append(vertex_index)
            for weight, indices in by_weight.items():
                group.add(indices, float(weight), "REPLACE")

    modifier = mesh_obj.modifiers.new(name="Sekiro Animation Rig", type="ARMATURE")
    modifier.object = rig
    modifier.use_vertex_groups = True
    mesh_obj["sekiro_flver_preview"] = True
    mesh_obj["sekiro_skinning"] = "FLVER bone weights mapped by bone name to the imported HKX armature"
    if preview_image is not None:
        mesh_obj["sekiro_preview_texture"] = str(texture_path)
    rig["sekiro_preview_mesh"] = mesh_obj.name
    print(
        "Attached FLVER preview to animation rig: {} vertices, {} triangles, {} weighted bones{}".format(
            len(positions), len(faces), len(groups), " with preview texture" if preview_image else ""
        )
    )


EXPORT_OPTIONS = dict(action="", frame_range="scene", frame_start=None, frame_end=None, frame_rate=None,
                      tracks="original", root_motion="auto", root_bone="", root_axes="xy", root_yaw=False)
BONE_CURVE = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]')


def export_rig(scene):
    rig_name = scene.get("sekiro_bridge_active_rig", "")
    recorded = scene.get("sekiro_bridge_export_rig")
    rig = recorded if isinstance(recorded, bpy.types.Object) and recorded.name in scene.objects else (bpy.data.objects.get(rig_name) if rig_name else None)
    if rig is None:
        rig = next((obj for obj in scene.objects if obj.type == "ARMATURE" and obj.get("sekiro_animation_bridge")), None)
    if rig is None or rig.type != "ARMATURE" or not rig.get("sekiro_animation_bridge"):
        raise RuntimeError("No armature created by this standalone importer is present in the blend file.")
    return rig


def embedded_motion(rig):
    recorded_text = rig.get("sekiro_bridge_source_text_data")
    text = recorded_text if isinstance(recorded_text, bpy.types.Text) else bpy.data.texts.get(rig.get("sekiro_bridge_source_text", ""))
    if text is None:
        raise RuntimeError("The embedded source motion is missing from this blend file.")
    payload = text.as_string()
    if payload.startswith("SEKIRO_BRIDGE_ZLIB_V1\n"):
        payload = zlib.decompress(base64.b64decode(payload.split("\n", 1)[1])).decode("utf-8")
    motion = json.loads(payload)
    if motion.get("format") != "sekiro-animation-bridge" or motion.get("formatVersion") != 1:
        raise RuntimeError("The embedded motion uses an unsupported bridge format.")
    return motion


def root_motion_object(rig):
    recorded = rig.get("sekiro_root_motion_data")
    return recorded if isinstance(recorded, bpy.types.Object) else bpy.data.objects.get(rig.get("sekiro_root_motion_object", ""))


def action_curves(action):
    """F-curves of a legacy action, or of every slot of a Blender 4.4+ layered action."""
    layers = getattr(action, "layers", None)
    if layers:
        return [curve for layer in layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves]
    return list(getattr(action, "fcurves", ()))


def control_bones(rig):
    """Bones that the retarget add-on's control rig added, with the game bones each one moves."""
    result = {}
    for bone in rig.data.bones:
        if "sekiro_control" in bone:
            try:
                result[bone.name] = [str(name) for name in json.loads(bone.get("sekiro_control_for", "[]"))]
            except (TypeError, ValueError):
                result[bone.name] = []
    return result


def keyed_bones(action, rig=None):
    """Bones an action animates. With the rig, a keyed control rig bone counts for the game bones it moves."""
    names = set()
    for curve in action_curves(action):
        match = BONE_CURVE.match(curve.data_path)
        if match:
            names.add(re.sub(r"\\(.)", r"\1", match.group(1)))
    if rig is not None:
        controls = control_bones(rig)
        names.update(name for control in names & set(controls) for name in controls[control])
    return names


def drives_controls(action, rig):
    """Whether an action animates the rig's control rig, the only kind of action that moves its game bones."""
    return bool(keyed_bones(action) & set(control_bones(rig)))


def assign_action(obj, action):
    """Assign an action (and its slot for this object in Blender 4.4+); return a function restoring the previous one."""
    obj.animation_data_create()
    data = obj.animation_data
    previous = data.action, getattr(data, "action_slot", None)
    data.action = action
    if action is not None and hasattr(data, "action_slot") and data.action_slot is None:
        slots = list(getattr(data, "action_suitable_slots", None) or ())
        own = [slot for slot in slots if slot.identifier == "OB" + obj.name]
        if own or slots:
            data.action_slot = (own or slots)[0]

    def restore():
        data.action = previous[0]
        if previous[0] is not None and previous[1] is not None and hasattr(data, "action_slot"):
            data.action_slot = previous[1]
    return restore


def paired_root_action(action):
    """Root-motion action that the importer or the retarget add-on created beside an armature action.

    Actions of the retarget add-on's control rig pair with the action they were made from.
    """
    base = action.get("sekiro_control_rig_base")
    if isinstance(base, bpy.types.Action) and base != action:
        return paired_root_action(base)
    names = [action.name + " RootMotion"]
    if action.name.endswith("_Sekiro"):
        names.insert(0, action.name[:-len("_Sekiro")] + "_RootMotion")
    return next((bpy.data.actions[name] for name in names if name in bpy.data.actions), None)


def ancestry(bones, index):
    """The bone and its parents up to the skeleton root, as indices."""
    chain = [index]
    while int(bones[chain[-1]]["parent"]) >= 0:
        chain.append(int(bones[chain[-1]]["parent"]))
    return chain


def body_carrier(bones, *indices):
    """The lowest bone above the pelvis, the spine and any given bones, as an index, or None.

    That bone carries the whole body: Root in Dark Souls III and Sekiro enemies,
    RootPos in Elden Ring and the player rigs, Master in Dark Souls, where the
    pelvis and the spine hang from separate bones. Where the spine hangs below
    the pelvis, it is the pelvis itself.
    """
    keys = [re.sub(r"[^a-z]", "", bone["name"].lower()) for bone in bones]
    pelvis = next((i for i, key in enumerate(keys) if key in ("pelvis", "hips", "hip") or key.endswith("pelvis")), None)
    spines = [i for i, key in enumerate(keys) if key == "spine"]
    spine = min(spines, key=lambda i: len(ancestry(bones, i))) if spines else None
    found = [i for i in (pelvis, spine, *indices) if i is not None]
    if pelvis is None or spine is None:
        return None
    shared = set(ancestry(bones, found[0]))
    for index in found[1:]:
        shared &= set(ancestry(bones, index))
    return max(shared, key=lambda i: len(ancestry(bones, i))) if shared else None


def default_root_bone(bones):
    """The bone carrying the whole body's travel; else the pelvis or the skeleton root."""
    carrier = body_carrier(bones)
    if carrier is not None:
        return bones[carrier]["name"]
    for bone in bones:
        if re.sub(r"[^a-z]", "", bone["name"].lower()) in ("pelvis", "hips", "hip"):
            return bone["name"]
    return bones[0]["name"]


def foot_targets(bones):
    """FromSoftware's foot targets as indices: {target: (foot, [the bones above the target, from the top])}.

    Each side hangs a straight chain from Master: L_Foot_Target2 at hip height,
    L_Foot_Target1 at knee height and L_Foot_Target at the ankle, where L_Foot
    rests. In the game's clips the chain stands on the foot like a column: it
    keeps its rest pose and its upright rest rotation, moved as one so that
    L_Foot_Target sits on the foot, and L_Foot_Target turns with the foot. The
    game reads these bones, so a clip whose targets leave the feet can make a
    foot snap when it blends into another clip.
    """
    keys = [re.sub(r"[^a-z0-9]", "", bone["name"].lower()) for bone in bones]
    targets = {}
    for index, key in enumerate(keys):
        match = re.fullmatch(r"([lr])foottarget", key)
        if not match or match.group(1) + "foot" not in keys:
            continue
        chain, parent = [], int(bones[index]["parent"])
        while parent >= 0 and re.fullmatch(match.group(1) + r"foottarget\d+", keys[parent]):
            chain.insert(0, parent)
            parent = int(bones[parent]["parent"])
        targets[index] = (keys.index(match.group(1) + "foot"), chain)
    return targets


def sample_times(start, end, scene_rate, rate):
    """Scene frames for evenly spaced output samples covering start..end in seconds."""
    if end <= start:
        raise RuntimeError("The export frame range must contain at least two frames.")
    # Rates that differ only through float storage (29.999998 vs 30 / fps_base) keep whole frames.
    step = 1.0 if abs(scene_rate - rate) <= 1e-5 * rate else scene_rate / rate
    return [start + index * step for index in range(int(round((end - start) / step)) + 1)]


def set_time(scene, time):
    frame = round(time)
    if abs(time - frame) < 1e-4:
        scene.frame_set(int(frame))
    else:
        frame = math.floor(time)
        scene.frame_set(int(frame), subframe=time - frame)
    bpy.context.view_layer.update()


def own_rotation(pose_bone):
    """A pose bone's keyed rotation, which its matrices lose when it is scaled to nothing."""
    if pose_bone.rotation_mode == "QUATERNION":
        rotation = pose_bone.rotation_quaternion.copy()
    elif pose_bone.rotation_mode == "AXIS_ANGLE":
        angle, x, y, z = pose_bone.rotation_axis_angle
        rotation = Quaternion((x, y, z), angle)
    else:
        rotation = pose_bone.rotation_euler.to_quaternion()
    return rotation.normalized() if rotation.magnitude > 1e-8 else Quaternion()


def extract_root_motion(matrices, axes, yaw):
    """Root transforms carrying one bone's travel and, optionally, its heading.

    The bone keeps its first-frame offset from the root, so the root starts at
    the origin. Samples follow the importer's root empty: Blender location
    (x, y, z) is game (x, z, y), and game yaw is the negative Blender Z angle.
    """
    start = matrices[0].translation.copy()
    start_rotation = matrices[0].to_quaternion()
    transforms, samples, previous = [], [], 0.0
    for matrix in matrices:
        angle = 0.0
        if yaw:
            delta = matrix.to_quaternion() @ start_rotation.inverted()
            twist = 2.0 * math.atan2(delta.z, delta.w)
            # Continue from the previous heading so turns beyond 180 degrees stay continuous.
            angle = previous + (twist - previous + math.pi) % (2.0 * math.pi) - math.pi
            previous = angle
        rotation = Matrix.Rotation(angle, 4, "Z")
        offset = matrix.translation - rotation.to_3x3() @ start
        if axes == "xy":
            offset.z = 0.0
        transforms.append(Matrix.Translation(offset) @ rotation)
        samples.append([float(offset.x), float(offset.z), float(offset.y), float(-angle)])
    return transforms, samples


def export_motion(output_json: Path, **overrides):
    """Sample the bridge rig into motion JSON. Returns a summary of what was exported.

    The evaluated pose is sampled, so constraints, drivers and NLA tracks are
    baked. Each track is written relative to its parent as the game computes it:
    a bone without a track keeps its reference pose in game, and its children
    absorb any motion it has in Blender. FromSoftware's foot target chains
    stand upright on the exported feet, as in the game's clips, whatever
    Blender shows for them.
    """
    options = {**EXPORT_OPTIONS, **{key: value for key, value in overrides.items() if value is not None}}
    scene = bpy.context.scene
    rig = export_rig(scene)
    motion = embedded_motion(rig)
    bones = motion["skeleton"]["bones"]
    names = [bone["name"] for bone in bones]
    parents = [int(bone["parent"]) for bone in bones]
    source_tracks = [int(index) for index in motion["trackBoneIndices"]]
    if not source_tracks or len(source_tracks) != len(motion["trackNames"]):
        raise RuntimeError("The stored track map is invalid.")
    pose_bones = []
    for name in names:
        pose_bone = rig.pose.bones.get(name)
        if pose_bone is None:
            raise RuntimeError("The blend file is missing bone: " + name)
        pose_bones.append(pose_bone)

    current = rig.animation_data.action if rig.animation_data else None
    action = bpy.data.actions.get(options["action"]) if options["action"] else current
    if options["action"] and action is None:
        raise RuntimeError("The blend file has no action named '{}'. Read the scene again to list its actions.".format(options["action"]))
    if action is None:
        raise RuntimeError("The imported armature has no active action.")
    if rig.get("sekiro_control_rig") and not drives_controls(action, rig):
        raise RuntimeError("The armature has a control rig, so its game bones follow the controls and '{}' would not move "
                           "them. Export the control rig's action, or remove the control rig first.".format(action.name))

    root = root_motion_object(rig)
    root_mode = options["root_motion"]
    if root_mode == "auto":
        root_mode = "object" if root is not None else "none"
    if root_mode == "object" and root is None:
        raise RuntimeError("This scene has no HKX_RootMotion object. Extract root motion from a bone or export without it.")
    root_index = None
    if root_mode == "bone":
        root_name = options["root_bone"] or default_root_bone(bones)
        if root_name not in names:
            raise RuntimeError("The skeleton has no bone named '{}' to extract root motion from.".format(root_name))
        root_index = names.index(root_name)

    warnings = []
    if options["root_motion"] == "auto" and root is None and motion.get("rootMotion") is not None:
        warnings.append("The source clip has root motion, but its HKX_RootMotion object is missing. Exported without root motion.")
    tracked = set(source_tracks)
    keyed = keyed_bones(action, rig)
    untracked = [index for index, name in enumerate(names) if index not in tracked and name in keyed]
    if options["tracks"] == "all":
        added = [index for index in range(len(names)) if index not in tracked]
    elif options["tracks"] == "keyed":
        added = untracked
    else:
        added = []
        if untracked:
            listed = ", ".join(names[index] for index in untracked[:8]) + (", ..." if len(untracked) > 8 else "")
            warnings.append("Keyed bones without a track in the source clip ({}): {}. Their own motion is not exported, "
                            "though tracked child bones follow it. Choose the keyed track set to add them.".format(len(untracked), listed))
    track_bones = source_tracks + added
    track_names = [str(name) for name in motion["trackNames"]] + [names[index] for index in added]

    scene_rate = scene.render.fps / scene.render.fps_base
    rate = float(options["frame_rate"] or motion["frameRate"])
    if not 1.0 <= rate <= 240.0:
        raise RuntimeError("Choose an output frame rate between 1 and 240 fps.")
    if options["frame_range"] == "scene":
        start, end = scene.frame_start, scene.frame_end
    elif options["frame_range"] == "action":
        start, end = action.frame_range
    elif options["frame_range"] == "clip":
        start, end = 1, int(motion["frameCount"])
    else:
        if options["frame_start"] is None or options["frame_end"] is None:
            raise RuntimeError("A custom frame range needs a start and an end frame.")
        start, end = options["frame_start"], options["frame_end"]
    start, end = float(start), float(end)
    times = sample_times(start, end, scene_rate, rate)

    original_frame = scene.frame_current
    restore = []
    worlds, bases, rotations, root_samples = [], [], [], []
    try:
        if action != current:
            restore.append(assign_action(rig, action))
            paired = paired_root_action(action) if root is not None else None
            if paired is not None and paired != (root.animation_data.action if root.animation_data else None):
                restore.append(assign_action(root, paired))
            elif paired is None and root_mode == "object":
                warnings.append("No root-motion action matches '{}'. Root motion uses the root object's current action.".format(action.name))
        for time in times:
            set_time(scene, time)
            worlds.append([pose_bone.matrix.copy() for pose_bone in pose_bones])
            bases.append([pose_bone.matrix_basis.copy() for pose_bone in pose_bones])
            rotations.append([own_rotation(pose_bone) for pose_bone in pose_bones])
            if root_mode == "object":
                root_samples.append([float(root.location.x), float(root.location.z), float(root.location.y),
                                     -float(root.rotation_euler.z)])
    finally:
        for undo in reversed(restore):
            undo()
        scene.frame_set(original_frame)

    if root_mode == "bone":
        transforms, root_samples = extract_root_motion([world[root_index] for world in worlds],
                                                       options["root_axes"], bool(options["root_yaw"]))
        # The bone above both the extraction bone and the body gives up the travel with
        # its descendants, so legs and upper body stay together even when the travel
        # is read from the pelvis. Bones above it, such as Master, stay as animated and
        # move with the character in game, so blending with other clips never sees a
        # counter-moving skeleton root.
        carrier = body_carrier(bones, root_index)
        moved = {root_index if carrier is None else carrier}
        for index, parent in enumerate(parents):
            if parent in moved:
                moved.add(index)
        for world, transform in zip(worlds, transforms):
            inverse = transform.inverted()
            world[:] = [inverse @ matrix if index in moved else matrix for index, matrix in enumerate(world)]

    rest_local = [trs_matrix(bone) for bone in bones]
    # A bone's own rest offset from its parent, where Blender's parent is the skeleton's.
    own_rest = [pose_bone.parent.bone.matrix_local.inverted() @ pose_bone.bone.matrix_local
                if parent >= 0 and pose_bone.parent is not None and pose_bone.parent.name == names[parent] else None
                for pose_bone, parent in zip(pose_bones, parents)]
    exported = set(track_bones)
    # Foot target chains stand on the feet as exported, after root motion left them: each keeps its rest pose and moves
    # as one, without turning, so that its target sits on the foot, and the target turns with the foot. They and the
    # bones below them are placed once every other bone is, since the feet come later in the skeleton.
    targets = foot_targets(bones)
    placed = {index for target, (foot, chain) in targets.items() for index in (*chain, target)} & exported
    rest_world = []
    for index, parent in enumerate(parents):
        rest_world.append(rest_world[parent] @ rest_local[index] if parent >= 0 else rest_local[index])
    offsets = {target: rest_world[foot].inverted_safe() @ rest_world[target] for target, (foot, chain) in targets.items()}
    after = [index for index in range(len(names)) if placed & set(ancestry(bones, index))]
    frames, previous = [], {}
    for world, basis, own in zip(worlds, bases, rotations):
        game_world, local = [], {}
        for index, parent in enumerate(parents):
            if index in exported and parent >= 0 and own_rest[index] is not None and min(game_world[parent].to_scale()) < 1e-6:
                # A parent scaled to nothing, as games hide a weapon, has no inverse: the bone keeps its own channels,
                # so that it is in place when the parent shows again or the game blends into another clip.
                matrix = local[index] = own_rest[index] @ basis[index]
            elif index in exported:
                matrix = local[index] = game_world[parent].inverted_safe() @ world[index] if parent >= 0 else world[index]
            else:
                matrix = rest_local[index]
            game_world.append(game_world[parent] @ matrix if parent >= 0 else matrix)
        wanted = {}
        for target, (foot, chain) in targets.items():
            top = parents[(chain or [target])[0]]
            matrix, hanging = game_world[top] if top >= 0 else Matrix.Identity(4), {}
            for index in (*chain, target):
                matrix = hanging[index] = matrix @ rest_local[index]
            wanted[target] = game_world[foot] @ offsets[target]
            shift = Matrix.Translation(wanted[target].translation - hanging[target].translation)
            wanted.update({index: shift @ hanging[index] for index in chain})
        for index in after:
            parent = parents[index]
            above = game_world[parent].inverted_safe() if parent >= 0 else Matrix.Identity(4)
            if index in placed:
                matrix = local[index] = above @ wanted[index]
            elif index in exported:
                matrix = local[index] = above @ world[index]
            else:
                matrix = rest_local[index]
            game_world[index] = game_world[parent] @ matrix if parent >= 0 else matrix
        frame = []
        for index in track_bones:
            location, rotation, scale = local[index].decompose()
            if own_rest[index] is not None and min(abs(value) for value in scale) < 1e-6:
                # A matrix scaled to nothing has lost its rotation: the bone keeps the one it is keyed with.
                rotation = own_rest[index].to_quaternion() @ own[index]
            sample = bl_to_game_trs(location, rotation, scale)
            # Keep each track's quaternions in one hemisphere for the spline compressor.
            if index in previous and sum(a * b for a, b in zip(sample["rotation"], previous[index])) < 0:
                sample["rotation"] = [-value for value in sample["rotation"]]
            previous[index] = sample["rotation"]
            frame.append(sample)
        frames.append(frame)

    count = len(frames)
    edited = dict(motion)
    edited.update(frameCount=count, frameRate=rate, duration=(count - 1) / rate, trackCount=len(track_bones),
                  trackBoneIndices=track_bones, trackNames=track_names, frames=frames)
    if root_mode == "none":
        edited.update(rootMotion=None, rootUp=None, rootForward=None)
    else:
        edited.update(rootMotion=root_samples, rootUp=motion.get("rootUp") or [0.0, 1.0, 0.0, 0.0],
                      rootForward=motion.get("rootForward") or [0.0, 0.0, 1.0, 0.0])
    summary = dict(action=action.name, frameStart=start, frameEnd=end, sceneRate=scene_rate, frames=count,
                   frameRate=rate, tracks=len(track_bones), trackSet=options["tracks"],
                   addedTracks=[names[index] for index in added], rootMotion=root_mode,
                   rootBone=names[root_index] if root_index is not None else "",
                   footTargets={names[target]: names[foot] for target, (foot, chain) in sorted(targets.items()) if target in exported},
                   warnings=warnings)
    edited["export"] = dict(summary, blender=bpy.app.version_string)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(edited, separators=(",", ":")), encoding="utf-8")
    print("Exported motion JSON: {}".format(output_json))
    print("Sampled '{}' frames {:g}-{:g}: {} frames at {:g} fps, {} tracks{}, root motion: {}{}".format(
        action.name, start, end, count, rate, len(track_bones),
        " ({} added)".format(len(added)) if added else "", root_mode,
        " from " + summary["rootBone"] if root_index is not None else ""), flush=True)
    if summary["footTargets"]:
        print("Foot targets follow the feet: " + ", ".join(summary["footTargets"]), flush=True)
    for warning in warnings:
        print("WARNING: " + warning, flush=True)
    return summary


def inspect_scene(output_json: Path):
    """Describe the bridge rig, its actions and frame ranges for the export options."""
    scene = bpy.context.scene
    rig = export_rig(scene)
    motion = embedded_motion(rig)
    bones = motion["skeleton"]["bones"]
    names = [bone["name"] for bone in bones]
    tracked = {names[int(index)] for index in motion["trackBoneIndices"]}
    current = rig.animation_data.action if rig.animation_data else None
    root = root_motion_object(rig)
    actions = []
    controlled = bool(rig.get("sekiro_control_rig"))
    # A second character, such as a retarget donor, plays its own action; it is not one to export from this rig.
    played = {obj.animation_data.action for obj in scene.objects if obj != rig and obj.type == "ARMATURE"
              and obj.animation_data and obj.animation_data.action}
    for action in bpy.data.actions:
        keyed = keyed_bones(action, rig) & set(names)
        if not keyed or (action in played and action != current) or (controlled and not drives_controls(action, rig)):
            continue
        start, end = action.frame_range
        paired = paired_root_action(action)
        actions.append(dict(name=action.name, frameStart=float(start), frameEnd=float(end), keyedBones=len(keyed),
                            untracked=sorted(keyed - tracked), active=action == current,
                            rootAction=paired.name if paired else ""))
    actions.sort(key=lambda item: (not item["active"], item["name"].lower()))
    root_action = root.animation_data.action if root is not None and root.animation_data else None
    info = dict(format="sekiro-animation-bridge-scene", formatVersion=1, blender=bpy.app.version_string,
                rig=rig.name, game=motion.get("game", ""), clip=motion.get("clip", ""),
                skeleton=motion.get("skeletonName", ""), frameCount=int(motion["frameCount"]),
                frameRate=float(motion["frameRate"]), trackCount=len(tracked), bones=names,
                defaultRootBone=default_root_bone(bones), activeAction=current.name if current else "",
                scene=dict(frameStart=scene.frame_start, frameEnd=scene.frame_end,
                           fps=scene.render.fps / scene.render.fps_base),
                actions=actions, rootObject=dict(name=root.name, action=root_action.name if root_action else "")
                if root is not None else None)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(info, indent=1), encoding="utf-8")
    print("Scene read: rig {}, {} armature actions".format(rig.name, len(actions)), flush=True)
    return info


def script_arguments():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return sys.argv[1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    import_parser = modes.add_parser("import", help="Create an editable .blend from decoded motion JSON.")
    import_parser.add_argument("--motion-json", required=True, type=Path)
    import_parser.add_argument("--output-blend", required=True, type=Path)
    import_parser.add_argument("--model-preview-data", type=Path)
    import_parser.add_argument("--preview-texture", type=Path)
    import_parser.add_argument("--character-manifest", type=Path)
    import_parser.add_argument("--donor-motion-json", type=Path, help="second clip to place beside the first, for retargeting")
    import_parser.add_argument("--donor-character-manifest", type=Path)
    export_parser = modes.add_parser("export", help="Sample an edited .blend into bridge motion JSON.")
    export_parser.add_argument("--output-json", required=True, type=Path)
    export_parser.add_argument("--action", default="", help="armature action to sample (default: the active action)")
    export_parser.add_argument("--frame-range", choices=("scene", "action", "clip", "custom"), default="scene",
                               help="scene range, the action's keyframe range, the imported clip length, or custom")
    export_parser.add_argument("--frame-start", type=float)
    export_parser.add_argument("--frame-end", type=float)
    export_parser.add_argument("--frame-rate", type=float, help="output samples per second (default: the source clip's)")
    export_parser.add_argument("--tracks", choices=("original", "keyed", "all"), default="original",
                               help="source clip tracks, plus bones keyed in the action, or every skeleton bone")
    export_parser.add_argument("--root-motion", choices=("auto", "object", "bone", "none"), default="auto",
                               help="root empty (auto when present), extract from a bone, or none")
    export_parser.add_argument("--root-bone", default="", help="bone whose travel becomes root motion (default: the bone above pelvis and spine)")
    export_parser.add_argument("--root-axes", choices=("xy", "xyz"), default="xy",
                               help="extract ground travel only, or vertical travel as well")
    export_parser.add_argument("--root-yaw", action="store_true", help="also extract the bone's heading")
    inspect_parser = modes.add_parser("inspect", help="Describe the bridge rig, its actions and frame ranges as JSON.")
    inspect_parser.add_argument("--output-json", required=True, type=Path)
    args = parser.parse_args(script_arguments())

    if args.mode == "import":
        motion = json.loads(args.motion_json.read_text(encoding="utf-8-sig"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        rig = import_motion(motion)
        if args.character_manifest:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from blender_character import import_character
            import_character(args.character_manifest, rig)
        elif args.model_preview_data:
            import_preview_model(args.model_preview_data, rig, args.preview_texture)
        elif args.preview_texture:
            raise ValueError("A preview texture requires a FLVER model preview.")
        if args.donor_motion_json:
            donor = json.loads(args.donor_motion_json.read_text(encoding="utf-8-sig"))
            import_donor(donor, rig, args.donor_character_manifest)
        args.output_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.output_blend.resolve()))
        print("Created Blender scene: {}".format(args.output_blend.resolve()))
    elif args.mode == "export":
        export_motion(args.output_json.resolve(), action=args.action, frame_range=args.frame_range,
                      frame_start=args.frame_start, frame_end=args.frame_end, frame_rate=args.frame_rate,
                      tracks=args.tracks, root_motion=args.root_motion, root_bone=args.root_bone,
                      root_axes=args.root_axes, root_yaw=args.root_yaw)
    else:
        inspect_scene(args.output_json.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print("Sekiro standalone conversion failed: {}".format(exc), file=sys.stderr)
        raise
