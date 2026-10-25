"""Build the modular character inside Blender using only its bundled Python and NumPy."""
from __future__ import annotations
import json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector, Euler, Quaternion

LABELS = {'fc': 'Head', 'am': 'Arms', 'bd': 'Torso', 'lg': 'Legs', 'wp': 'Weapon', 'hd': 'Headwear'}


def load_image(spec, color=True):
    image = bpy.data.images.load(spec['path'], check_existing=True)
    space = 'Linear Rec.709' if color and spec.get('linear') else ('sRGB' if color else 'Non-Color')
    try:
        image.colorspace_settings.name = space
    except TypeError:
        image.colorspace_settings.name = 'Linear' if space.startswith('Linear') else space
    image.pack()
    return image


def texture_node(material, spec, uv_names, color=True):
    nodes, links = material.node_tree.nodes, material.node_tree.links
    uv = nodes.new('ShaderNodeUVMap')
    # MTD UV indices refer to the corresponding FLVER stream; keep every stream available.
    field = f"uv_{spec.get('uv', 0)}"
    uv.uv_map = field if field in uv_names else uv_names[0]
    uv.location = (-700, 100 if color else -260)
    mapping = nodes.new('ShaderNodeVectorMath'); mapping.operation = 'MULTIPLY'
    sx, sy = spec.get('scale', [1, 1])
    mapping.inputs[1].default_value = (sx, sy, 1)
    mapping.location = (-520, uv.location.y)
    links.new(uv.outputs['UV'], mapping.inputs[0])
    tex = nodes.new('ShaderNodeTexImage'); tex.image = load_image(spec, color)
    tex.label = spec.get('stem', '')
    tex.location = (-310, uv.location.y)
    links.new(mapping.outputs[0], tex.inputs['Vector'])
    return tex


def make_material(spec, uv_names, cache):
    key = json.dumps(spec, sort_keys=True)
    if key in cache:
        return cache[key]
    mat = bpy.data.materials.new('FromSoftware / ' + spec['name'])
    mat.use_nodes = True
    mat.diffuse_color = (0.42, 0.33, 0.23, 1)
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.location = (290, 80)
    shader.inputs['Roughness'].default_value = 0.82
    if 'Specular IOR Level' in shader.inputs:
        shader.inputs['Specular IOR Level'].default_value = .22
    shader.inputs['Base Color'].default_value = (*spec.get('color', [.42, .33, .23])[:3], 1)
    if spec.get('albedo'):
        tex = texture_node(mat, spec['albedo'], uv_names)
        color_output = tex.outputs['Color']
        if spec.get('tint'):
            tint = texture_node(mat, spec['tint'], uv_names)
            tint.location.y -= 240
            mix = mat.node_tree.nodes.new('ShaderNodeMixRGB'); mix.blend_type = 'MULTIPLY'
            mix.inputs[0].default_value = 1
            mat.node_tree.links.new(color_output, mix.inputs[1])
            mat.node_tree.links.new(tint.outputs['Color'], mix.inputs[2])
            color_output = mix.outputs[0]
        mat.node_tree.links.new(color_output, shader.inputs['Base Color'])
        if spec.get('alpha'):
            mat.node_tree.links.new(tex.outputs['Alpha'], shader.inputs['Alpha'])
            if hasattr(mat, 'surface_render_method'):
                mat.surface_render_method = 'DITHERED'
            elif hasattr(mat, 'blend_method'):
                mat.blend_method = 'HASHED'
    if spec.get('emissive'):
        tex = texture_node(mat, spec['emissive'], uv_names)
        emission = shader.inputs.get('Emission Color') or shader.inputs.get('Emission')
        if emission is not None:
            mat.node_tree.links.new(tex.outputs['Color'], emission)
        if 'Emission Strength' in shader.inputs:
            shader.inputs['Emission Strength'].default_value = 1.0
    # DirectX normals use an inverted green channel. Reconstruct Z for two-channel BC5 maps.
    if spec.get('normal'):
        tex = texture_node(mat, spec['normal'], uv_names, color=False)
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        separate = nodes.new('ShaderNodeSeparateXYZ'); links.new(tex.outputs['Color'], separate.inputs[0])
        def math(op, a, b=None):
            node = nodes.new('ShaderNodeMath'); node.operation = op
            if isinstance(a, (float, int)): node.inputs[0].default_value = a
            else: links.new(a, node.inputs[0])
            if b is not None:
                if isinstance(b, (float, int)): node.inputs[1].default_value = b
                else: links.new(b, node.inputs[1])
            return node.outputs[0]
        x = math('SUBTRACT', math('MULTIPLY', separate.outputs['X'], 2), 1)
        y = math('SUBTRACT', math('MULTIPLY', separate.outputs['Y'], 2), 1)
        z = math('SQRT', math('MAXIMUM', math('SUBTRACT', 1, math('ADD', math('MULTIPLY', x, x), math('MULTIPLY', y, y))), 0))
        combine = nodes.new('ShaderNodeCombineXYZ')
        links.new(separate.outputs['X'], combine.inputs['X'])
        links.new(math('SUBTRACT', 1, separate.outputs['Y']), combine.inputs['Y'])
        links.new(math('ADD', math('MULTIPLY', z, .5), .5), combine.inputs['Z'])
        normal = nodes.new('ShaderNodeNormalMap'); normal.inputs['Strength'].default_value = .65
        normal.uv_map = f"uv_{spec['normal'].get('uv', 0)}"
        links.new(combine.outputs[0], normal.inputs['Color']); links.new(normal.outputs[0], shader.inputs['Normal'])
    mat['sekiro_material_definition'] = spec.get('mtd', '')
    mat['sekiro_sampler_sources'] = json.dumps(spec.get('samplers', []))
    cache[key] = mat
    return mat


def ensure_model_bones(rig, preview, needed):
    names = [str(n) for n in preview['bone_names']]
    missing = {i for i in needed if names[i] not in rig.data.bones}
    if not missing:
        return
    if 'bone_parents' not in preview:
        raise ValueError('FLVER bone data is incomplete; regenerate the character preview.')
    parents = preview['bone_parents']
    wanted = set(missing)
    for i in list(missing):
        parent = int(parents[i])
        while parent >= 0 and names[parent] not in rig.data.bones and parent not in wanted:
            wanted.add(parent); parent = int(parents[parent])
    conversion = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    world = {}
    visiting = set()
    def rest(i):
        if i in world: return world[i]
        if i in visiting: raise ValueError('FLVER bone hierarchy contains a cycle.')
        visiting.add(i)
        local = Matrix.LocRotScale(Vector(preview['bone_translations'][i]), Euler(preview['bone_rotations'][i], 'XZY').to_quaternion(), Vector(preview['bone_scales'][i]))
        parent = int(parents[i]); value = rest(parent) @ local if parent >= 0 else local
        world[i] = value; visiting.remove(i)
        return value
    bpy.context.view_layer.objects.active = rig; rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def add(i):
        if names[i] in rig.data.edit_bones: return rig.data.edit_bones[names[i]]
        parent = int(parents[i]); parent_bone = add(parent) if parent >= 0 else None
        bone = rig.data.edit_bones.new(names[i]); bone.length = .04
        bone.matrix = conversion @ rest(i) @ conversion
        bone.parent = parent_bone; bone['sekiro_model_only'] = True
        return bone
    for i in sorted(wanted): add(i)
    bpy.ops.object.mode_set(mode='OBJECT')
    print(f'Added {len(wanted)} model-only bones. Original HKX tracks remain unchanged.', flush=True)


def skin_rig_for_part(rig, preview, used, collection, name):
    """Some cutscene parts have a different authored bind pose; retain their inverse bind matrices."""
    names = [str(n) for n in preview['bone_names']]
    parents = preview['bone_parents']
    conversion = Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
    world = {}
    def rest(i):
        if i in world: return world[i]
        parent = int(parents[i])
        local = Matrix.LocRotScale(Vector(preview['bone_translations'][i]),
            Euler(preview['bone_rotations'][i], 'XZY').to_quaternion(), Vector(preview['bone_scales'][i]))
        world[i] = rest(parent) @ local if parent >= 0 else local
        return world[i]
    bind = {i:conversion @ rest(i) @ conversion for i in used}
    if not any(max(abs(bind[i][r][c]-rig.data.bones[names[i]].matrix_local[r][c]) for r in range(4) for c in range(4)) > .01 for i in used):
        return rig
    adapter = bpy.data.objects.new(name + ' | Bind adapter', bpy.data.armatures.new(name + ' bind'))
    collection.objects.link(adapter); adapter.parent = rig
    bpy.context.view_layer.objects.active = adapter; adapter.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def add(i):
        if names[i] in adapter.data.edit_bones: return adapter.data.edit_bones[names[i]]
        parent = int(parents[i]); parent_bone = add(parent) if parent >= 0 else None
        bone = adapter.data.edit_bones.new(names[i]); bone.length = .04
        matrix = conversion @ rest(i) @ conversion
        location, rotation, _ = matrix.decompose()
        bone.matrix = Matrix.LocRotScale(location, rotation, Vector((1,1,1)))
        bone.parent = parent_bone
        return bone
    for i in sorted(used): add(i)
    bpy.ops.object.mode_set(mode='OBJECT')
    for bone in adapter.pose.bones:
        if bone.name in rig.pose.bones:
            constraint=bone.constraints.new('COPY_TRANSFORMS'); constraint.target=rig
            constraint.subtarget=bone.name; constraint.target_space='POSE'; constraint.owner_space='POSE'
    adapter['sekiro_internal_bind_adapter'] = True
    adapter.hide_set(True); adapter.hide_select = True; adapter.hide_render = True
    bpy.context.view_layer.objects.active = rig
    print(f'{name}: preserved its cutscene bind pose with a driven skin adapter', flush=True)
    return adapter


def weapon_rig(rig, preview, used, collection, name, attachment):
    """Keep each weapon's local skeleton separate and drive its object via a socket."""
    bone_name = attachment['bone']
    if bone_name and bone_name not in rig.pose.bones:
        raise ValueError(f'{name}: socket {attachment["dummy"]} requires {bone_name}, which is missing from this animation rig.')
    anchor=attachment.get('anchorBone',bone_name) if attachment.get('kind')=='bone' else str(attachment['dummy'])
    socket = bpy.data.objects.new(name.upper()+' | Socket '+anchor, None)
    collection.objects.link(socket); socket.parent=rig; socket.empty_display_size=.035
    constraint=socket.constraints.new('COPY_TRANSFORMS'); constraint.target=rig
    constraint.subtarget=bone_name; constraint.target_space='WORLD'; constraint.owner_space='WORLD'
    socket['sekiro_weapon_socket']=attachment['dummy']; socket['sekiro_socket_bone']=bone_name
    local_rig=bpy.data.objects.new(name.upper()+' | Weapon rig',bpy.data.armatures.new(name+' local bones'))
    collection.objects.link(local_rig);local_rig.parent=socket
    local_rig.matrix_basis=Matrix(attachment['matrix'])
    local_rig['sekiro_weapon_rig']=True;local_rig['sekiro_weapon_attachment']=json.dumps(attachment)
    names=[str(n) for n in preview['bone_names']];parents=preview['bone_parents']
    conversion=Matrix(((1,0,0,0),(0,0,1,0),(0,1,0,0),(0,0,0,1)))
    worlds={};visiting=set()
    def rest(i):
        if i in worlds:return worlds[i]
        if i in visiting:raise ValueError('Weapon bone hierarchy contains a cycle.')
        visiting.add(i);parent=int(parents[i])
        local=Matrix.LocRotScale(Vector(preview['bone_translations'][i]),
            Euler(preview['bone_rotations'][i],'XZY').to_quaternion(),Vector(preview['bone_scales'][i]))
        worlds[i]=rest(parent)@local if parent>=0 else local
        visiting.remove(i);return worlds[i]
    for obj in bpy.context.selected_objects:obj.select_set(False)
    local_rig.select_set(True);bpy.context.view_layer.objects.active=local_rig
    bpy.ops.object.mode_set(mode='EDIT')
    def add(i):
        if names[i] in local_rig.data.edit_bones:return local_rig.data.edit_bones[names[i]]
        parent=int(parents[i]);parent_bone=add(parent) if parent>=0 else None
        bone=local_rig.data.edit_bones.new(names[i]);bone.length=.04
        location,rotation,_=(conversion@rest(i)@conversion).decompose()
        bone.matrix=Matrix.LocRotScale(location,rotation,Vector((1,1,1)));bone.parent=parent_bone
        return bone
    for i in sorted(used):add(i)
    bpy.ops.object.mode_set(mode='OBJECT')
    local_rig.hide_set(True);local_rig.hide_render=True;socket.hide_set(True)
    if attachment.get('locations'): follow_locations(rig, socket, local_rig, collection, name, attachment)
    bpy.context.view_layer.objects.active=rig;rig.select_set(True)
    print(f'{name}: attached independent weapon rig to {bone_name or "character root"}, {attachment.get("kind","dummy")} anchor {anchor}',flush=True)
    return local_rig


def location_frames(changes):
    """Scene frames of event 715's changes: the clip's first frame is scene frame 1, at the scene's frame rate."""
    scene = bpy.context.scene
    rate = scene.render.fps / scene.render.fps_base
    return [(1 + float(time) * rate, int(dummy)) for time, dummy in changes]


def constant_keys(owner):
    action = owner.animation_data.action
    # Blender 4.4+ keeps the curves of a layered action in channel bags.
    layered = getattr(action, 'layers', None)
    curves = [curve for layer in layered for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves] \
        if layered else action.fcurves
    for curve in curves:
        for point in curve.keyframe_points:
            point.interpolation = 'CONSTANT'


def follow_locations(rig, socket, local_rig, collection, name, attachment):
    """Move a weapon rig between dummies as the character's TAE event 715 does (see part_animations.locate).

    A mount between the socket and the rig copies, with keyed influence, an anchor
    under another dummy's socket; the anchor carries that dummy's attachment
    relative to the socket's own, so the rig keeps its offset under the mount.
    """
    own = Matrix(attachment['matrix'])
    frames = location_frames(attachment['locations']['changes'])
    mount = bpy.data.objects.new(name.upper() + ' | Mount', None)
    collection.objects.link(mount); mount.parent = socket; mount.empty_display_size = .02
    local_rig.parent = mount
    for key, other in attachment['locations']['sockets'].items():
        if other['bone'] and other['bone'] not in rig.pose.bones:
            print(f'{name}: dummy {key} needs {other["bone"]}, which this rig lacks; the weapon stays off it', flush=True)
            continue
        holder = bpy.data.objects.new(f'{name.upper()} | Socket {key}', None)
        collection.objects.link(holder); holder.parent = rig; holder.empty_display_size = .035
        follow = holder.constraints.new('COPY_TRANSFORMS'); follow.target = rig
        follow.subtarget = other['bone']; follow.target_space = 'WORLD'; follow.owner_space = 'WORLD'
        holder['sekiro_weapon_socket'] = int(key); holder['sekiro_socket_bone'] = other['bone']
        anchor = bpy.data.objects.new(f'{name.upper()} | Anchor {key}', None)
        collection.objects.link(anchor); anchor.parent = holder
        anchor.matrix_basis = Matrix(other['matrix']) @ own.inverted()
        moved = mount.constraints.new('COPY_TRANSFORMS'); moved.name = 'Dummy ' + key; moved.target = anchor
        moved.target_space = 'WORLD'; moved.owner_space = 'WORLD'
        for frame, dummy in frames:
            moved.influence = float(dummy == int(key))
            moved.keyframe_insert('influence', frame=frame)
        holder.hide_set(True); anchor.hide_set(True)
    if mount.animation_data:
        constant_keys(mount)
    mount.hide_set(True)
    print(f'{name}: follows event 715 of {attachment["locations"]["entry"]} over dummies '
          f'{", ".join(str(dummy) for _, dummy in frames)}', flush=True)


def key_visibility(obj, attachment):
    """Hide a weapon mesh on the frames where event 715 gives its model no dummy (-1)."""
    frames = location_frames(attachment['locations']['changes'])
    if all(dummy >= 0 for _, dummy in frames):
        return
    for frame, dummy in frames:
        obj.hide_viewport = obj.hide_render = dummy < 0
        obj.keyframe_insert('hide_viewport', frame=frame)
        obj.keyframe_insert('hide_render', frame=frame)
    constant_keys(obj)
    obj.hide_viewport = obj.hide_render = frames[0][1] < 0


def import_character(manifest_path, rig):
    document = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    collection = bpy.data.collections.new('Sekiro | Character')
    rig.users_collection[0].children.link(collection)
    cache, objects = {}, []
    for model in document['models']:
        with np.load(model['data'], allow_pickle=False) as preview:
            pos, faces = preview['positions'], preview['faces']
            indices, weights = preview['bone_indices'], preview['bone_weights']
            names = [str(n) for n in preview['bone_names']]
            used = set(int(i) for i in indices[weights > 1e-6])
            if model.get('attachment'):
                # An animated part's rig carries every bone of its HKX skeleton, not only the weighted ones.
                from blender_parts import part_motion, skeleton_bones, animate_part
                motion = part_motion(model)
                bones = used | skeleton_bones(motion, names) if motion else used
                skin_rig=weapon_rig(rig,preview,bones,collection,model['name'],model['attachment'])
                if motion: animate_part(skin_rig, motion, model['name'])
            else:
                ensure_model_bones(rig, preview, used)
                skin_rig = skin_rig_for_part(rig, preview, used, collection, model['name'])
            mesh = bpy.data.meshes.new(model['name'])
            mesh.from_pydata(pos[:, [0, 2, 1]].tolist(), [], faces[:, [0, 2, 1]].tolist()); mesh.update()
            role = LABELS.get(model['name'].split('_')[0], 'Character')
            obj = bpy.data.objects.new(f"{model['name'].upper()} | {role}", mesh)
            collection.objects.link(obj); obj.parent = skin_rig if model.get('attachment') else rig
            uv_names = sorted([key for key in preview.files if key.startswith('uv_')], key=lambda k:int(k[3:]))
            if not uv_names: uv_names = ['uv_0']
            loop_vertices = np.asarray([loop.vertex_index for loop in mesh.loops], dtype=np.int32)
            for key in uv_names:
                uv = (preview[key] if key in preview else preview['uvs'])[loop_vertices].copy()
                uv[:, 1] = 1 - uv[:, 1]
                layer = mesh.uv_layers.new(name=key); layer.data.foreach_set('uv', uv.ravel())
            if 'normals' in preview and np.any(preview['normals']):
                normals = preview['normals'][:, [0, 2, 1]].copy()
                length = np.linalg.norm(normals, axis=1, keepdims=True)
                normals = normals / np.maximum(length, 1e-8)
                mesh.normals_split_custom_set_from_vertices(normals.tolist())
            for spec in model['materials']:
                mesh.materials.append(make_material(spec, uv_names, cache))
            mesh.polygons.foreach_set('material_index', preview['face_materials'])
            for polygon in mesh.polygons: polygon.use_smooth = True
            for bone_index in sorted(used):
                # Combine duplicate influences before writing each weight once.
                values = np.sum(np.where(indices == bone_index, weights, 0), axis=1)
                group = obj.vertex_groups.new(name=names[bone_index])
                for vertex_index in np.flatnonzero(values > 1e-6):
                    group.add([int(vertex_index)], float(values[vertex_index]), 'REPLACE')
            modifier = obj.modifiers.new('Sekiro Animation Rig', 'ARMATURE'); modifier.object = skin_rig
            obj['sekiro_flver_preview'] = True; obj['sekiro_source_model'] = model['source']
            obj['sekiro_model_id'] = model['name']; objects.append(obj)
            if model.get('attachment'):
                obj['sekiro_weapon_preview']=True;obj['sekiro_weapon_attachment']=json.dumps(model['attachment'])
                if model['attachment'].get('locations'): key_visibility(obj, model['attachment'])
            print(f"Attached {obj.name}: {len(pos):,} vertices / {len(faces):,} faces", flush=True)
    text = bpy.data.texts.new('Sekiro Character Report.json')
    # Keep diagnostics, not paths to temporary geometry and PNG files which will be removed.
    report = {k:v for k,v in document.items() if k != 'models'}
    report['models'] = [{k:v for k,v in m.items() if k not in ('data', 'materials')} for m in document['models']]
    text.write(json.dumps(report, indent=2))
    rig['sekiro_preview_meshes'] = json.dumps([o.name for o in objects])
    rig.show_in_front = False
    setup_view(rig)
    return objects


def setup_view(rig):
    for obj in bpy.context.selected_objects: obj.select_set(False)
    rig.select_set(True); bpy.context.view_layer.objects.active = rig
    scene = bpy.context.scene
    scene.world = scene.world or bpy.data.worlds.new('Preview World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.15, .17, .20, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .6
    scene.frame_set(1); bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    points = [obj.matrix_world @ Vector(corner) for obj in scene.objects if obj.get('sekiro_flver_preview') and not obj.hide_viewport
              for corner in obj.evaluated_get(deps).bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3))) if points else Vector((0, 0, 0))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3))) if points else Vector((0, 0, 2))
    center = (low + high) * .5
    distance = max(1.5, (high - low).length * 1.35)
    setup_preview_lighting(scene, center, high.z - low.z)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = 'MATERIAL'
                space.shading.use_scene_world = True
                space.shading.use_scene_lights = True
                space.overlay.show_relationship_lines = False
                space.region_3d.view_location = center
                space.region_3d.view_distance = distance
                space.region_3d.view_rotation = Euler((1.35, 0, .4), 'XYZ').to_quaternion()
    scene.frame_set(1)


def setup_preview_lighting(scene, center, height):
    """Light the packed materials for both Material Preview and rendered view."""
    scale = max(1.25, height) / 1.8
    for name, offset, power, size in (
        ('Key', (2.5, -3.0, 4.0), 550, 3.0),
        ('Fill', (-2.0, -1.5, 2.0), 350, 2.5),
        ('Rim', (0.0, 2.5, 3.0), 650, 2.0),
    ):
        object_name = 'Sekiro Preview ' + name
        light = scene.objects.get(object_name)
        if light is None:
            data = bpy.data.lights.new(object_name, 'AREA')
            light = bpy.data.objects.new(object_name, data)
            scene.collection.objects.link(light)
        light.data.type = 'AREA'
        light.data.shape = 'DISK'
        light.data.size = size * scale
        light.data.energy = power * scale * scale
        light.location = center + Vector(offset) * scale
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
