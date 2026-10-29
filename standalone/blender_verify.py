"""Measure a bridge scene in Blender, so that a script or an agent can check an import without looking at it.

blender_bridge.py verify runs it. Each rig of the bridge (the target, and a retarget donor) gets its size, its up
axis and the side its left bones are on; each of its meshes, whether it moves with the bones it is weighted to and
how far the skinning stretches its edges; each material, whether its images exist. checks[] turns these numbers into
pass or fail with the reason; an advisory check only points at a frame worth a look, and passed leaves it out. The
scene is never saved.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

# A plausible character, in metres. A unit scale error makes one 100 times too large or too small.
SIZE = (0.2, 30.0)
# Skinning stretches edges at the joints. On FromSoftware characters, cloth and armour plates stretch 3 to 8 times in
# big motions, as far as a wrong bind pose or bone rotation stretches a body layer, so this check is advisory.
STRETCH = 3.0
# Edges shorter than this share of the character's height change length too unevenly to measure.
SHORTEST = 0.005
# A mesh that follows its bones moves at least this far, in metres, where those bones do.
MOVES = 0.001


def bone_side(name):
    """'L' or 'R' for a bone named for one side of the body (L_Thigh, Thigh.L, l_arm_upper, mixamorig:LeftArm), else ''."""
    lowered = name.lower()
    for side, word in (('L', 'left'), ('R', 'right')):
        letter = side.lower()
        if re.search(rf'(?:^|[^a-z]){word}', lowered) or re.match(rf'{letter}[_.\s]', lowered) or re.search(rf'[_.\s]{letter}$', lowered):
            return side
    return ''


def world_points(obj, depsgraph, deformed=True):
    """The mesh's vertices in the world: as Blender shows them, or as stored before the armature deforms them."""
    owner = obj.evaluated_get(depsgraph) if deformed else obj
    mesh = owner.to_mesh() if deformed else obj.data
    try:
        points = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', points)
    finally:
        if deformed:
            owner.to_mesh_clear()
    matrix = np.asarray(owner.matrix_world, dtype=np.float64)
    return points.reshape(-1, 3).astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]


def edge_pairs(mesh):
    pairs = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get('vertices', pairs)
    return pairs.reshape(-1, 2)


def stretch(stored, posed, pairs, shortest=1e-6):
    """How many times longer the posed edges are than the stored ones, of those at least shortest long: 99th percentile
    and largest ratio. Only longer counts: the game hides parts by scaling their bones to zero."""
    if not len(pairs):
        return 1.0, 1.0
    before = np.linalg.norm(stored[pairs[:, 0]] - stored[pairs[:, 1]], axis=1)
    after = np.linalg.norm(posed[pairs[:, 0]] - posed[pairs[:, 1]], axis=1)
    keep = before >= max(shortest, 1e-6)
    if not np.any(keep):
        return 1.0, 1.0
    ratio = after[keep] / before[keep]
    return float(np.percentile(ratio, 99)), float(ratio.max())


def summary(checks):
    """'8 of 9 checks pass; 2 advisory to look at', for the log."""
    hard = [c for c in checks if not c['advisory']]
    notes = sum(1 for c in checks if c['advisory'] and not c['ok'])
    return f"{sum(c['ok'] for c in hard)} of {len(hard)} checks pass" + (f'; {notes} advisory to look at' if notes else '')


def detached_bones(rig):
    """Model-only bones with no bone of the animation above them: what they carry never moves with a clip."""
    return {bone.name for bone in rig.data.bones if all(b.get('sekiro_model_only') for b in (bone, *bone.parent_recursive))}


def skin_armature(obj):
    return next((m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object), None)


def bone_heads(armature, names, depsgraph):
    """World positions of the armature's posed bone heads, by name."""
    evaluated = armature.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world
    return {name: np.asarray(matrix @ evaluated.pose.bones[name].head, dtype=np.float64) for name in names if name in evaluated.pose.bones}


def materials(obj):
    rows = []
    for material in obj.data.materials:
        if material is None:
            continue
        images, textured = [], False
        if material.use_nodes and material.node_tree:
            for node in material.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    path = bpy.path.abspath(node.image.filepath) if node.image.filepath else ''
                    images.append(dict(name=node.image.name, path=path,
                                       found=bool(node.image.packed_file) or bool(path and Path(path).is_file())))
            shader = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            textured = bool(shader and shader.inputs['Base Color'].is_linked)
        rows.append(dict(name=material.name, images=images, baseColor=textured))
    return rows


def sample_frames(scene, count):
    start, end = int(scene.frame_start), int(scene.frame_end)
    if end <= start or count < 2:
        return [start]
    return sorted({round(start + (end - start) * i / (count - 1)) for i in range(count)})


def bounds(points):
    low, high = points.min(axis=0), points.max(axis=0)
    return low, high, high - low


def rig_points(rig):
    """The rig's bone heads and tails in the world, for a rig without meshes."""
    return np.asarray([rig.matrix_world @ point for bone in rig.data.bones for point in (bone.head_local, bone.tail_local)])


def moved_by(start, heads):
    return max((float(np.linalg.norm(heads[name] - start[name])) for name in heads if name in start), default=0.0)


def rounded(values, digits=4):
    return [round(float(v), digits) for v in values]


def verify_scene(output_json: Path, render: Path | None = None, samples: int = 3):
    scene = bpy.context.scene
    rigs = [obj for obj in scene.objects if obj.type == 'ARMATURE' and obj.get('sekiro_animation_bridge')]
    if not rigs:
        raise RuntimeError('This scene has no rig made by the bridge.')
    target, donor = scene.get('sekiro_bridge_export_rig'), scene.get('sekiro_bridge_retarget_source')
    meshes = {rig: [obj for obj in rig.children_recursive if obj.type == 'MESH' and obj.get('sekiro_flver_preview')] for rig in rigs}
    frames = sample_frames(scene, samples)
    current = scene.frame_current

    # The rest pose: size, up axis and sides, from the meshes where there are any.
    positions = {rig: rig.data.pose_position for rig in rigs}
    for rig in rigs:
        rig.data.pose_position = 'REST'
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rest = {}
    for rig in rigs:
        points = [p for p in (world_points(obj, depsgraph) for obj in meshes[rig]) if len(p)] or [rig_points(rig)]
        sides = {'L': [], 'R': []}
        for bone in rig.data.bones:
            side = bone_side(bone.name)
            if side and not bone.get('sekiro_model_only'):
                sides[side].append((rig.matrix_world @ bone.head_local).x)
        rest[rig] = (bounds(np.concatenate(points)), sides)
    for rig, position in positions.items():
        rig.data.pose_position = position

    # The clip: how far each rig's bones and each mesh move, and how far the skinning stretches the mesh.
    stored = {obj: world_points(obj, depsgraph, deformed=False) for rig in rigs for obj in meshes[rig]}
    pairs = {obj: edge_pairs(obj.data) for obj in stored}
    shortest = {obj: SHORTEST * float(rest[rig][0][2][2]) for rig in rigs for obj in meshes[rig]}
    weighted = {obj: [group.name for group in obj.vertex_groups] for obj in stored}
    rig_moved, moved, bones_moved = {rig: 0.0 for rig in rigs}, {obj: 0.0 for obj in stored}, {obj: 0.0 for obj in stored}
    # Per mesh: the largest 99th percentile, the largest ratio, and the frame of that percentile.
    stretched = {obj: (1.0, 1.0, frames[0]) for obj in stored}
    # The first sampled frame of each rig's bones, each mesh's vertices and each mesh's weighted bones.
    first_rig, first_mesh, first_weighted = {}, {}, {}
    for frame in frames:
        scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for rig in rigs:
            heads = bone_heads(rig, rig.data.bones.keys(), depsgraph)
            rig_moved[rig] = max(rig_moved[rig], moved_by(first_rig.setdefault(rig, heads), heads))
        for obj in stored:
            posed = world_points(obj, depsgraph)
            if len(posed) != len(stored[obj]):
                continue
            start = first_mesh.setdefault(obj, posed)
            moved[obj] = max(moved[obj], float(np.linalg.norm(posed - start, axis=1).max(initial=0)))
            armature = skin_armature(obj)
            if armature is not None:
                heads = bone_heads(armature, weighted[obj], depsgraph)
                bones_moved[obj] = max(bones_moved[obj], moved_by(first_weighted.setdefault(obj, heads), heads))
            p99, largest = stretch(stored[obj], posed, pairs[obj], shortest[obj])
            worst, most, at = stretched[obj]
            stretched[obj] = (p99, max(most, largest), frame) if p99 > worst else (worst, max(most, largest), at)
    scene.frame_set(current)

    checks, reports = [], []

    def check(name, ok, detail, advisory=False):
        checks.append(dict(name=name, ok=bool(ok), advisory=advisory, detail=detail))

    for rig in rigs:
        (low, high, extent), sides = rest[rig]
        role = 'donor' if rig == donor else 'target' if rig == target or len(rigs) == 1 else 'rig'
        label = f'{role} {rig.name}'
        height = float(extent[2])
        check(f'{label}: size', SIZE[0] <= height <= SIZE[1],
              f'{height:.2f} m tall at rest; a wrong unit scale makes it 100 times too large or too small')
        # A rest pose with spread arms or a held weapon can be wider than tall; a Y-up basis lays it along Y.
        upright = extent[2] >= 0.8 * extent[1] and extent[2] >= 0.4 * extent[0]
        check(f'{label}: upright', upright,
              'Z is its tallest axis' if extent[2] >= max(extent) else
              f'{extent[2]:.2f} m tall, {extent[1]:.2f} m deep and {extent[0]:.2f} m wide at rest' if upright else
              f'extent x {extent[0]:.2f}, y {extent[1]:.2f}, z {extent[2]:.2f} m: it should stand along Z, taller than deep')
        left, right = sides['L'], sides['R']
        if left and right:
            left_x, right_x = sum(left) / len(left), sum(right) / len(right)
            check(f'{label}: left side on +X', left_x > right_x,
                  f'left bones at x {left_x:.3f}, right bones at x {right_x:.3f}; with Z up, left on +X faces Blender\'s front (-Y)')
        detached = detached_bones(rig)
        mesh_reports = []
        for obj in meshes[rig]:
            armature = skin_armature(obj)
            bones = set(armature.data.bones.keys()) if armature else set()
            missing = sorted(name for name in weighted[obj] if name not in bones)
            # Each vertex follows its strongest bone most; one on a detached bone stays behind.
            unweighted, loose, carriers = 0, 0, set()
            for vertex in obj.data.vertices:
                strongest = max(((g.weight, g.group) for g in vertex.groups if g.weight > 1e-6), default=None)
                if strongest is None:
                    unweighted += 1
                elif weighted[obj][strongest[1]] in detached:
                    loose += 1
                    carriers.add(weighted[obj][strongest[1]])
            p99, largest, at = stretched[obj]
            rows = materials(obj)
            mesh_reports.append(dict(name=obj.name, model=obj.get('sekiro_model_id', ''), source=obj.get('sekiro_source_model', ''),
                                     vertices=len(obj.data.vertices), unweighted=unweighted, groups=len(weighted[obj]),
                                     groupsWithoutBones=missing, detachedVertices=loose, detachedBones=sorted(carriers),
                                     armature=armature.name if armature else '',
                                     moved=round(moved[obj], 4), bonesMoved=round(bones_moved[obj], 4),
                                     stretch99=round(p99, 3), stretchMax=round(largest, 3), stretchFrame=at, materials=rows))
            if armature is None:
                check(f'{obj.name}: skinned', False, 'it has no Armature modifier, so it does not follow the rig')
                continue
            if missing:
                check(f'{obj.name}: vertex groups', False,
                      f'{len(missing)} groups name no bone of {armature.name}: {", ".join(missing[:8])}')
            check(f'{obj.name}: bones in the animation', not loose,
                  'every vertex follows a bone of the animation, or a model bone below one' if not loose else
                  f'{loose} of {len(obj.data.vertices)} vertices follow model bones outside the animation\'s skeleton, '
                  f'which never move: {", ".join(sorted(carriers)[:8])}')
            if bones_moved[obj] >= MOVES:
                check(f'{obj.name}: follows its bones', moved[obj] >= MOVES,
                      f'its bones move up to {bones_moved[obj]:.3f} m over frames {frames[0]}-{frames[-1]} and the mesh up to {moved[obj]:.3f} m')
            check(f'{obj.name}: skin stretch', p99 <= STRETCH,
                  f'99% of edges stay within {p99:.2f} times their stored length, the most on frame {at}; the worst {largest:.2f} times'
                  + ('' if p99 <= STRETCH else f'. Cloth stretches this far in big motions, a body layer only with a wrong bind pose '
                                               f'or bone rotation: look at frame {at}'), advisory=True)
        images = [image for mesh in mesh_reports for row in mesh['materials'] for image in row['images']]
        named = {image['path'] or image['name'] for image in images}
        lost = sorted({image['path'] or image['name'] for image in images if not image['found']})
        plain = sorted({row['name'] for mesh in mesh_reports for row in mesh['materials'] if not row['baseColor']})
        if mesh_reports:
            check(f'{label}: image files', not lost,
                  'no images' if not named else f'all {len(named)} images exist' if not lost else f'{len(lost)} of {len(named)} images missing: {", ".join(lost[:8])}')
            check(f'{label}: base colors', not plain,
                  'every material has a base-color image' if not plain else
                  f'{len(plain)} materials have none, so they show a flat color: {", ".join(plain[:8])}')
        reports.append(dict(name=rig.name, role=role, game=rig.get('sekiro_game', ''), clip=rig.get('sekiro_clip', ''),
                            bones=len(rig.data.bones), modelOnlyBones=sum(1 for b in rig.data.bones if b.get('sekiro_model_only')),
                            height=round(height, 4), extent=rounded(extent), bounds=[rounded(low), rounded(high)],
                            sides=dict(left=len(left), right=len(right)), moved=round(rig_moved[rig], 4), meshes=mesh_reports))

    renders = render_views(render, [obj for rig in rigs for obj in meshes[rig]] or rigs) if render else []
    info = dict(format='sekiro-animation-bridge-verification', formatVersion=1, blender=bpy.app.version_string,
                frames=frames, passed=all(c['ok'] for c in checks if not c['advisory']), checks=checks, rigs=reports,
                renders=renders)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(info, indent=1), encoding='utf-8')
    print(f'Verified {len(rigs)} rig(s): {summary(checks)}', flush=True)
    for item in checks:
        if not item['ok']:
            print(f"NOTICE: {item['name']}{' (advisory)' if item['advisory'] else ''}: {item['detail']}", flush=True)
    return info


def render_views(path: Path, objects):
    """Workbench pictures from the front and from the left, at the current frame, framed on the objects."""
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = np.concatenate([world_points(obj, depsgraph) if obj.type == 'MESH' else rig_points(obj) for obj in objects])
    low, high, extent = bounds(points)
    center = Vector((low + high) / 2)
    reach = float(max(extent)) * 2 + 1
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'TEXTURE'
    scene.render.resolution_x = scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    data = bpy.data.cameras.new('Bridge verify')
    data.type = 'ORTHO'
    data.clip_end = reach * 3
    camera = bpy.data.objects.new('Bridge verify', data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    written = []
    # The front camera looks along +Y at the character's face; the side camera along -X at its left side.
    for suffix, rotation, offset, width in (('', (math.pi / 2, 0, 0), Vector((0, -1, 0)), extent[0]),
                                            ('-side', (math.pi / 2, 0, math.pi / 2), Vector((1, 0, 0)), extent[1])):
        data.ortho_scale = float(max(width, extent[2])) * 1.15
        camera.location = center + offset * reach
        camera.rotation_euler = rotation
        target = path.with_name(path.stem + suffix + path.suffix)
        scene.render.filepath = str(target)
        bpy.ops.render.render(write_still=True)
        written.append(str(target))
    return written
