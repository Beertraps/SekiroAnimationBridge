"""Write a character export manifest from a Blender scene, for a new game character (docs/INTERCHANGE.md).

The manifest holds the rig's bones with their rest transforms, every mesh skinned to the rig, the materials with
their textures by role, the images, and the active action sampled at every frame. Everything is in Blender's space:
meters, Z up, world coordinates. The game writer (character_export.py) converts it to the game's space.
Runs inside Blender with its bundled Python and NumPy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import bmesh
import bpy
import numpy as np

FORMAT = 'sekiro-animation-bridge-character-export'
VERSION = 1
ROLES = ('albedo', 'opacity', 'normal', 'metalness', 'roughness', 'emissive')


def rows(matrix):
    """A 4x4 matrix as 16 numbers, row by row, in Blender's column-vector order."""
    return [float(value) for row in matrix for value in row]


def safe(name):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', name).strip('_') or 'image'


def skinned_meshes(rig):
    """Visible mesh objects that an Armature modifier binds to the rig."""
    found = []
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        if any(m.type == 'ARMATURE' and m.object == rig for m in obj.modifiers):
            found.append(obj)
    return found


def upstream(socket, seen=None):
    """(node, output socket name, channel) of the image texture that feeds socket, through any nodes on the way.

    channel is 'RGB' for an image's color, 'A' for its alpha, or R, G, B after a Separate Color node.
    """
    seen = seen or set()
    for link in socket.links if socket.is_linked else ():
        node, out = link.from_node, link.from_socket
        if node in seen:
            continue
        seen.add(node)
        if node.type == 'TEX_IMAGE' and node.image is not None:
            return node, out.name, 'A' if out.name == 'Alpha' else 'RGB'
        if node.type in ('SEPRGB', 'SEPARATE_COLOR', 'SEPXYZ', 'SEPARATE_XYZ'):
            channel = {'Red': 'R', 'Green': 'G', 'Blue': 'B', 'R': 'R', 'G': 'G', 'B': 'B', 'X': 'R', 'Y': 'G', 'Z': 'B'}.get(out.name, 'R')
            found = upstream(node.inputs[0], seen)
            if found:
                return found[0], found[1], channel if found[2] == 'RGB' else found[2]
        for item in node.inputs:
            found = upstream(item, seen)
            if found:
                return found
    return None


def traced_roles(material):
    """Texture roles read from the node tree, for materials made by hand or by another importer."""
    tree = material.node_tree if material.use_nodes else None
    shader = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if tree else None
    if shader is None:
        return {}
    roles = {}
    for role, name in (('albedo', 'Base Color'), ('opacity', 'Alpha'), ('metalness', 'Metallic'),
                       ('roughness', 'Roughness'), ('emissive', 'Emission Color')):
        socket = shader.inputs.get(name)
        found = upstream(socket) if socket is not None else None
        if found:
            roles[role] = dict(image=found[0].image.name, channel=found[2])
    normal = shader.inputs.get('Normal')
    if normal is not None and normal.is_linked and normal.links[0].from_node.type == 'NORMAL_MAP':
        mapped = normal.links[0].from_node.inputs['Color']
        found = upstream(mapped)
        if found:
            # The importer rebuilds DirectX normals with a 1 - Y step before its Combine XYZ node.
            combine = mapped.links[0].from_node if mapped.is_linked else None
            y = combine.inputs.get('Y') if combine is not None and combine.type in ('COMBXYZ', 'COMBINE_XYZ') else None
            directx = y is not None and y.is_linked and y.links[0].from_node.type == 'MATH'
            roles['normal'] = dict(image=found[0].image.name, channel='RGB', convention='directx' if directx else 'opengl')
    return roles


def fixed_inputs(material):
    """The shader's alpha and base color (linear RGBA) where no texture drives them, else None for each."""
    tree = material.node_tree if material and material.use_nodes else None
    shader = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if tree else None
    if shader is None:
        return None, None
    alpha, color = shader.inputs.get('Alpha'), shader.inputs.get('Base Color')
    return (None if alpha is None or alpha.is_linked else round(float(alpha.default_value), 4),
            None if color is None or color.is_linked else [round(float(v), 4) for v in color.default_value])


def material_roles(material):
    """The importer's record of a material's roles when it has one, otherwise the node tree's."""
    stored = material.get('bridge_texture_roles') if material else None
    if stored:
        return json.loads(stored)
    return traced_roles(material) if material else {}


def save_image(image, folder, written):
    """Write an image to folder once, as its packed bytes or a copy of its file. Returns the path."""
    if image.name in written:
        return written[image.name]
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(image.filepath_raw or image.name).suffix.lower() or '.png'
    path = folder / (safe(Path(image.name).stem) + suffix)
    if image.packed_file is not None:
        path.write_bytes(bytes(image.packed_file.data))
    elif image.filepath and Path(bpy.path.abspath(image.filepath)).is_file():
        path.write_bytes(Path(bpy.path.abspath(image.filepath)).read_bytes())
    else:
        path = path.with_suffix('.png')
        image.save_render(str(path))
    written[image.name] = str(path)
    return str(path)


def mesh_arrays(obj, rig, bone_index):
    """Rest-pose arrays of one mesh object in world space: vertices, corners (loops) and triangles."""
    mesh = obj.data.copy()
    try:
        work = bmesh.new()
        work.from_mesh(mesh)
        bmesh.ops.triangulate(work, faces=work.faces[:])
        work.to_mesh(mesh)
        work.free()
        uv_names = [layer.name for layer in mesh.uv_layers]
        if uv_names:
            mesh.calc_tangents(uvmap=uv_names[0])
        world = np.array(obj.matrix_world, dtype=np.float64)
        normal_matrix = np.linalg.inv(world[:3, :3]).T

        count = len(mesh.vertices)
        positions = np.empty(count * 3, np.float32)
        mesh.vertices.foreach_get('co', positions)
        positions = positions.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]

        loops = len(mesh.loops)
        loop_vertex = np.empty(loops, np.int32)
        mesh.loops.foreach_get('vertex_index', loop_vertex)
        normals = np.empty(loops * 3, np.float32)
        if hasattr(mesh, 'corner_normals'):
            mesh.corner_normals.foreach_get('vector', normals)
        else:
            mesh.loops.foreach_get('normal', normals)
        normals = normals.reshape(-1, 3) @ normal_matrix.T
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8)
        tangents = np.zeros((loops, 4), np.float32)
        if uv_names:
            tangent = np.empty(loops * 3, np.float32)
            mesh.loops.foreach_get('tangent', tangent)
            sign = np.empty(loops, np.float32)
            mesh.loops.foreach_get('bitangent_sign', sign)
            tangent = tangent.reshape(-1, 3) @ world[:3, :3].T
            tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-8)
            tangents[:, :3], tangents[:, 3] = tangent, sign
        arrays = dict(positions=positions.astype(np.float32), loop_vertex=loop_vertex, normals=normals.astype(np.float32),
                      tangents=tangents)
        for index, name in enumerate(uv_names[:2]):
            uv = np.empty(loops * 2, np.float32)
            mesh.uv_layers[name].data.foreach_get('uv', uv)
            arrays[f'uv_{index}'] = uv.reshape(-1, 2)

        tris = len(mesh.polygons)
        # Every polygon is a triangle now, so its corners are three consecutive loops.
        starts = np.empty(tris, np.int32)
        mesh.polygons.foreach_get('loop_start', starts)
        corners = starts[:, None] + np.arange(3, dtype=np.int32)
        slots = np.empty(tris, np.int32)
        mesh.polygons.foreach_get('material_index', slots)
        arrays['triangles'], arrays['triangle_slots'] = corners, slots

        # The four largest weights of bones in the rig, summing to 1. Groups of other names are left out.
        groups = {group.index: bone_index.get(group.name, -1) for group in obj.vertex_groups}
        indices = np.zeros((count, 4), np.int32)
        weights = np.zeros((count, 4), np.float32)
        lost = 0
        for vertex in mesh.vertices:
            pairs = sorted(((g.weight, groups.get(g.group, -1)) for g in vertex.groups if g.weight > 0), reverse=True)
            lost += sum(1 for w, b in pairs if b < 0)
            pairs = [(w, b) for w, b in pairs if b >= 0][:4]
            total = sum(w for w, _ in pairs)
            for k, (w, b) in enumerate(pairs):
                indices[vertex.index, k], weights[vertex.index, k] = b, w / total
        arrays['bone_indices'], arrays['bone_weights'] = indices, weights
        unweighted = int(np.count_nonzero(weights.sum(axis=1) == 0))
        return arrays, dict(vertices=count, triangles=tris, uvSets=len(uv_names), unweightedVertices=unweighted,
                            weightsOutsideRig=lost)
    finally:
        bpy.data.meshes.remove(mesh)


def export_character(output_dir, rig, action_name='', frame_start=None, frame_end=None):
    """Write manifest.json, one .npz per mesh, motion.npz and the images into output_dir. Returns the manifest."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    bones = list(rig.data.bones)
    bone_index = {bone.name: index for index, bone in enumerate(bones)}
    world = rig.matrix_world
    # The rig's game, recorded at import, lets the bone matcher read the bone names of a game package.
    manifest = dict(format=FORMAT, version=VERSION, rig=rig.name, game=str(rig.get('sekiro_game', '')), space='blender',
                    unit='meter',
                    bones=[dict(name=b.name, parent=bone_index[b.parent.name] if b.parent else -1,
                                rest=rows(world @ b.matrix_local)) for b in bones],
                    meshes=[], materials=[], images={}, warnings=[])

    materials, written = {}, {}
    for obj in skinned_meshes(rig):
        arrays, stats = mesh_arrays(obj, rig, bone_index)
        slots = []
        for slot in obj.material_slots or [None]:
            material = slot.material if slot is not None else None
            key = material.name if material else ''
            if key not in materials:
                roles = material_roles(material)
                for role in roles.values():
                    image = bpy.data.images.get(role['image'])
                    if image is not None:
                        role['path'] = save_image(image, output_dir / 'images', written)
                materials[key] = len(manifest['materials'])
                alpha, color = fixed_inputs(material)
                manifest['materials'].append(dict(
                    name=key or 'default', roles={k: v for k, v in roles.items() if 'path' in v}, alpha=alpha, color=color,
                    doubleSided=bool(material and not material.use_backface_culling),
                    cutOut=bool(material and getattr(material, 'surface_render_method', '') == 'DITHERED')))
            slots.append(materials[key])
        arrays['triangle_materials'] = np.asarray(slots, np.int32)[np.clip(arrays.pop('triangle_slots'), 0, len(slots) - 1)]
        path = output_dir / (safe(obj.name) + '.npz')
        np.savez_compressed(path, **arrays)
        manifest['meshes'].append(dict(name=obj.name, data=str(path), **stats))
        if stats['weightsOutsideRig']:
            manifest['warnings'].append(f'{obj.name}: {stats["weightsOutsideRig"]} weights name groups that are not bones of '
                                        f'{rig.name}; they were left out.')
        if stats['unweightedVertices']:
            manifest['warnings'].append(f'{obj.name}: {stats["unweightedVertices"]} vertices have no weight on a bone of '
                                        f'{rig.name}; they stay on the first bone.')
    if not manifest['meshes']:
        raise RuntimeError(f'No visible mesh is bound to {rig.name} with an Armature modifier.')

    action = bpy.data.actions.get(action_name) if action_name else (rig.animation_data.action if rig.animation_data else None)
    if action_name and action is None:
        raise RuntimeError(f"The blend file has no action named '{action_name}'.")
    pose_bones = [rig.pose.bones[b.name] for b in bones]
    previous = rig.animation_data.action if rig.animation_data else None
    if action is not None:
        rig.animation_data_create().action = action
        first, last = action.frame_range
    else:
        first, last = scene.frame_current, scene.frame_current + 1
    first = int(round(frame_start if frame_start is not None else first))
    last = int(round(frame_end if frame_end is not None else last))
    if last <= first:
        last = first + 1
    original = scene.frame_current
    matrices = []
    try:
        for frame in range(first, last + 1):
            scene.frame_set(frame)
            matrices.append([np.array(rig.matrix_world @ pb.matrix, np.float32) for pb in pose_bones])
    finally:
        scene.frame_set(original)
        if rig.animation_data is not None:
            rig.animation_data.action = previous
    motion = output_dir / 'motion.npz'
    np.savez_compressed(motion, matrices=np.asarray(matrices, np.float32))
    manifest['motion'] = dict(action=action.name if action else '', frameStart=first, frameEnd=last,
                              frameRate=scene.render.fps / scene.render.fps_base, frames=last - first + 1, data=str(motion))
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(f"Character export manifest: {output_dir / 'manifest.json'} ({len(bones)} bones, {len(manifest['meshes'])} meshes, "
          f"{len(manifest['materials'])} materials, {len(written)} images, {last - first + 1} frames)", flush=True)
    for warning in manifest['warnings']:
        print('WARNING: ' + warning, flush=True)
    return manifest
