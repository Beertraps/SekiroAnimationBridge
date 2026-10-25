"""Weapon part animations in Blender: key a part's rig with its clip, and sample it back for export.

Each weapon keeps its own rig under a socket on the character (blender_character.weapon_rig).
A part clip animates that rig with the part's HKX skeleton. The skeleton can parent
a bone differently from the FLVER, so the pose is placed through the skeleton's world
matrices and each bone keeps the game's pose under either hierarchy. FLVER bones
outside the skeleton follow their parents.

Run inside Blender to export:
    blender --background scene.blend --python blender_parts.py -- export --output-dir DIR --frame-start 1 --frame-end 61
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import textwrap
import zlib
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_bridge import bl_to_game_trs, export_rig, sample_times, script_arguments, set_time, trs_matrix, write_action  # noqa: E402

TEXT_PREFIX = "SEKIRO_BRIDGE_ZLIB_V1\n"


def part_motion(model):
    """The decoded clip of a character manifest model, or None. Its temporary path leaves the model's report."""
    animation = model.get("animation")
    if not animation or "motion" not in animation:
        return None
    return json.loads(Path(animation.pop("motion")).read_text(encoding="utf-8-sig"))


def skeleton_bones(motion, names):
    """Indices of the FLVER bones that the part's skeleton names, so the weapon rig builds every one."""
    known = {name: index for index, name in enumerate(names)}
    return {known[bone["name"]] for bone in motion["skeleton"]["bones"] if bone["name"] in known}


def skeleton_worlds(bones, local):
    worlds = []
    for index, bone in enumerate(bones):
        parent = int(bone["parent"])
        worlds.append(worlds[parent] @ local[index] if parent >= 0 else local[index].copy())
    return worlds


def animate_part(rig, motion, model=""):
    """Key a weapon rig with its part clip, on the scene frames at the clip's own times.

    A part clip can run at another frame rate than the character clip (30 against
    60 fps), and both last equally long, so its keys fall on the scene frames of the
    same seconds.
    """
    bones = motion["skeleton"]["bones"]
    names = [bone["name"] for bone in bones]
    parents = [int(bone["parent"]) for bone in bones]
    tracks = [int(index) for index in motion["trackBoneIndices"]]
    rest = [trs_matrix(bone) for bone in bones]
    scene = bpy.context.scene
    scene_rate = scene.render.fps / scene.render.fps_base
    rate = float(motion["frameRate"])
    frames = [1.0 + index * scene_rate / rate for index in range(int(motion["frameCount"]))]
    index_of = {name: index for index, name in enumerate(names)}
    tracked = [index for index in tracks if names[index] in rig.pose.bones]

    def moved(index):
        parent = rig.pose.bones[names[index]].parent
        return (parent.name if parent else None) != (names[parents[index]] if parents[index] >= 0 else None)
    # A bone without a track keeps its reference pose under its skeleton parent, which can be another bone in the FLVER.
    tracked += [index for index in range(len(bones)) if index not in tracks and names[index] in rig.pose.bones and moved(index)]
    for index in tracked:
        rig.pose.bones[names[index]].rotation_mode = "QUATERNION"

    channels, previous = {}, {}
    for frame in motion["frames"]:
        local = list(rest)
        for track, index in enumerate(tracks):
            local[index] = trs_matrix(frame[track])
        world = skeleton_worlds(bones, local)
        flver_world = {}

        def world_of(pose_bone):
            """This frame's armature-space matrix of a rig bone; one outside the skeleton keeps its rest offset."""
            if pose_bone.name in index_of:
                return world[index_of[pose_bone.name]]
            if pose_bone.name not in flver_world:
                parent = pose_bone.parent
                flver_world[pose_bone.name] = (world_of(parent) @ parent.bone.matrix_local.inverted() @ pose_bone.bone.matrix_local
                                               if parent else pose_bone.bone.matrix_local.copy())
            return flver_world[pose_bone.name]

        for index in tracked:
            pose_bone = rig.pose.bones[names[index]]
            parent = pose_bone.parent
            if parent is None:
                basis = pose_bone.bone.matrix_local.inverted() @ world[index]
            elif parents[index] >= 0 and names[parents[index]] == parent.name:
                # The same parent in both hierarchies: the track is the bone's own offset, even under a parent scaled to nothing.
                basis = (parent.bone.matrix_local.inverted() @ pose_bone.bone.matrix_local).inverted() @ local[index]
            else:
                basis = pose_bone.bone.convert_local_to_pose(world[index], pose_bone.bone.matrix_local,
                                                             parent_matrix=world_of(parent),
                                                             parent_matrix_local=parent.bone.matrix_local, invert=True)
            location, rotation, scale = basis.decompose()
            if index in previous and rotation.dot(previous[index]) < 0:
                rotation.negate()
            previous[index] = rotation.copy()
            prefix = pose_bone.path_from_id()
            for field, values in (("location", location), ("rotation_quaternion", rotation), ("scale", scale)):
                channels.setdefault(prefix + "." + field, []).append(tuple(values))

    clip = Path(motion["clip"]).stem
    name = (model or rig.name.split(" | ")[0]).upper()
    action = write_action(rig, "{} | {}".format(name, clip), channels, frames)
    text = bpy.data.texts.new("Sekiro Part Source - {} - {}.json".format(name, clip))
    encoded = base64.b64encode(zlib.compress(json.dumps(motion, separators=(",", ":")).encode("utf-8"))).decode("ascii")
    text.from_string(TEXT_PREFIX + "\n".join(textwrap.wrap(encoded, 120)))
    rig["sekiro_part_source_text_data"] = text
    rig["sekiro_part_clip"] = motion["clip"]
    rig["sekiro_part_model"] = name
    rig["sekiro_part_frame_count"] = int(motion["frameCount"])
    rig["sekiro_part_frame_rate"] = rate
    print("{}: plays {} ({} frames at {:g} fps, keyed on scene frames 1-{:g})".format(
        name, motion["clip"], len(frames), rate, frames[-1]), flush=True)
    return action


def embedded_part(rig):
    """The part clip that the importer stored with a weapon rig, or None."""
    text = rig.get("sekiro_part_source_text_data")
    if not isinstance(text, bpy.types.Text):
        return None
    payload = text.as_string()
    if payload.startswith(TEXT_PREFIX):
        payload = zlib.decompress(base64.b64decode(payload.split("\n", 1)[1])).decode("utf-8")
    motion = json.loads(payload)
    if motion.get("format") != "sekiro-animation-bridge" or motion.get("formatVersion") != 1:
        raise RuntimeError("{}: the stored part clip uses an unsupported bridge format.".format(rig.name))
    return motion


def part_rigs(scene):
    """The animated weapon rigs of the character that the export writes, which hang below its rig.

    A second character in the scene, such as a retarget donor appended by hand, keeps its weapons out.
    """
    rig = export_rig(scene)
    return [obj for obj in rig.children_recursive if obj.name in scene.objects and obj.type == "ARMATURE"
            and obj.get("sekiro_weapon_rig") and isinstance(obj.get("sekiro_part_source_text_data"), bpy.types.Text)]


def sample_part(scene, rig, motion, start, end):
    """Sample one weapon rig into part motion JSON over the scene frames start..end, at its clip's frame rate.

    As for the character, each track is written relative to its parent in the
    part's skeleton, and bones without a track keep their reference pose.
    """
    bones = motion["skeleton"]["bones"]
    names = [bone["name"] for bone in bones]
    parents = [int(bone["parent"]) for bone in bones]
    tracks = [int(index) for index in motion["trackBoneIndices"]]
    present = [index for index in range(len(bones)) if names[index] in rig.pose.bones]
    rate = float(motion["frameRate"])
    times = sample_times(start, end, scene.render.fps / scene.render.fps_base, rate)
    worlds, bases = [], []
    for time in times:
        set_time(scene, time)
        worlds.append({index: rig.pose.bones[names[index]].matrix.copy() for index in present})
        bases.append({index: rig.pose.bones[names[index]].matrix_basis.copy() for index in present})

    rest = [trs_matrix(bone) for bone in bones]
    own_rest = {}
    for index in present:
        pose_bone = rig.pose.bones[names[index]]
        if parents[index] >= 0 and pose_bone.parent is not None and pose_bone.parent.name == names[parents[index]]:
            own_rest[index] = pose_bone.parent.bone.matrix_local.inverted() @ pose_bone.bone.matrix_local
    exported = set(tracks)
    frames, previous = [], {}
    for world, basis in zip(worlds, bases):
        game_world, local = [], {}
        for index, parent in enumerate(parents):
            if index in exported and index in world:
                if parent >= 0 and index in own_rest and min(game_world[parent].to_scale()) < 1e-6:
                    # A parent scaled to nothing has no inverse: the bone keeps its own channels.
                    matrix = local[index] = own_rest[index] @ basis[index]
                else:
                    matrix = local[index] = game_world[parent].inverted_safe() @ world[index] if parent >= 0 else world[index]
            else:
                # A track whose bone the rig lacks keeps the reference pose.
                matrix = rest[index]
                if index in exported:
                    local[index] = matrix
            game_world.append(game_world[parent] @ matrix if parent >= 0 else matrix)
        frame = []
        for index in tracks:
            sample = bl_to_game_trs(*local[index].decompose())
            if index in previous and sum(a * b for a, b in zip(sample["rotation"], previous[index])) < 0:
                sample["rotation"] = [-value for value in sample["rotation"]]
            previous[index] = sample["rotation"]
            frame.append(sample)
        frames.append(frame)
    count = len(frames)
    edited = dict(motion)
    edited.update(frameCount=count, frameRate=rate, duration=(count - 1) / rate, frames=frames,
                  rootMotion=None, rootUp=None, rootForward=None)
    action = rig.animation_data.action if rig.animation_data else None
    edited["export"] = dict(part=rig.get("sekiro_part_model", ""), action=action.name if action else "", frameStart=start,
                            frameEnd=end, frames=count, frameRate=rate, blender=bpy.app.version_string,
                            missingBones=[names[index] for index in tracks if names[index] not in rig.pose.bones])
    return edited


def export_parts(output_dir: Path, start, end):
    """Write the motion JSON of every animated weapon rig and an index, parts.json, of what was written."""
    scene = bpy.context.scene
    rigs = part_rigs(scene)
    output_dir.mkdir(parents=True, exist_ok=True)
    hidden = [(rig, rig.hide_get()) for rig in rigs]
    original = scene.frame_current
    index = []
    try:
        # A hidden rig is still evaluated for its mesh; showing it keeps the sampled pose current regardless.
        for rig, _ in hidden:
            rig.hide_set(False)
        for rig in rigs:
            motion = embedded_part(rig)
            edited = sample_part(scene, rig, motion, float(start), float(end))
            name = str(rig.get("sekiro_part_model") or rig.name.split(" | ")[0])
            path = output_dir / "{}.motion.json".format(name.lower())
            path.write_text(json.dumps(edited, separators=(",", ":")), encoding="utf-8")
            index.append(dict(model=name.lower(), name=name, clip=Path(motion["clip"]).name, motion=str(path),
                              frames=edited["frameCount"], frameRate=edited["frameRate"], action=edited["export"]["action"],
                              missingBones=edited["export"]["missingBones"]))
            print("Sampled {}: {} frames of {} at {:g} fps".format(name, edited["frameCount"], motion["clip"], edited["frameRate"]),
                  flush=True)
    finally:
        for rig, state in hidden:
            rig.hide_set(state)
        scene.frame_set(original)
    (output_dir / "parts.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    if not index:
        print("This scene has no animated weapon parts.", flush=True)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    export_parser = modes.add_parser("export", help="Sample every animated weapon rig into part motion JSON.")
    export_parser.add_argument("--output-dir", required=True, type=Path)
    export_parser.add_argument("--frame-start", required=True, type=float, help="scene frame of the first sample")
    export_parser.add_argument("--frame-end", required=True, type=float, help="scene frame of the last sample")
    args = parser.parse_args(script_arguments())
    export_parts(args.output_dir.resolve(), args.frame_start, args.frame_end)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print("Sekiro part export failed: {}".format(exc), file=sys.stderr)
        raise
