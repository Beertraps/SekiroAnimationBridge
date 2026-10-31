"""DOOM Eternal characters for Blender: md6 models, their skin, material2 decls and images.

Writes the bridge's character manifest version 5 (docs/INTERCHANGE.md): one .npz per model with rest
rotations as quaternions, PNG textures, and the id Tech space, so Blender converts the models the same
way as the motion.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from games.api import check_manifest, dds_to_png

from . import md6, models

# The joint whose subtree is the head: id Tech skeletons and the HumanIK skeletons of cinematics.
HEAD_JOINTS = ('head_part01_md', 'head')
HEAD_NOTICE = 'None of the chosen parts has a head. Tick a body marked "with head".'
_HEADS = {}


def model_name(path):
    return path.rsplit('/', 1)[-1].rsplit('.', 1)[0]


def prepare_character(game, entries, paths, output, profile, ctx, joints=None, defs=None):
    """Read the chosen models with level-of-detail 0 geometry, their materials and textures, into a manifest.

    A path is a model, or model#look for one look of a model with several. defs holds the md6def of each model
    (looks and gore meshes, from definitions()); gore pieces and the meshes of other looks are left out.
    joints maps the path of each weapon to the tag it hangs on: a joint of the character and an offset from it.
    A weapon's bones are named after it (maraudergun_origin), so that a weapon and the character never share a bone.
    """
    joints, defs = joints or {}, defs or {}
    out = Path(output)
    textures_out = out / 'textures'
    textures_out.mkdir(parents=True, exist_ok=True)
    warnings, read = [], []
    images = defaultdict(list)
    for kind, name in entries:
        if kind == 'image':
            images[name.split('$', 1)[0]].append(name)

    def read_decl(key):
        found = entries.get(('rs_streamfile', key))
        return game.read(found).decode('utf-8', 'replace') if found else None

    for index, path in enumerate(paths):
        source, _, look = path.partition('#')
        entry = entries.get(('baseModel', source))
        name = model_name(source) + (f'_{look}' if look else '')
        if entry is None:
            warnings.append(f'{name}: the model is not in the archives.')
            continue
        model = models.read_model(game.read(entry))
        skeleton_entry = entries.get(('skeleton', model.skeleton))
        if skeleton_entry is None:
            warnings.append(f'{name}: its skeleton {model.skeleton} is not in the archives.')
            continue
        skeleton, _, _ = md6.without_bind_scale(md6.read_skeleton(game.read(skeleton_entry)))
        _, size, _, _ = model.disk[0]
        data = game.stream(models.geometry_key(entry, 0), size) if size else b''
        if not data:
            warnings.append(f'{name}: its geometry is not in the .streamdb files.')
            continue
        meshes = [arrays if keep else None
                  for arrays, keep in zip(models.read_geometry(model, data, 0), chosen_meshes(model, defs.get(source), look))]
        if path in joints:
            skeleton, meshes = on_tag(skeleton, meshes, joints[path], name)
        materials = {m.material: models.read_material(read_decl, m.material)
                     for m, arrays in zip(model.meshes, meshes) if arrays is not None}
        read.append((index, path, name, model, skeleton, meshes, materials))

    # A weapon hangs on a joint of the character's skeleton; without it, the weapon is left out.
    body = {n for _, path, _, _, skeleton, *_ in read if path not in joints for n in skeleton.names}
    for entry in list(read):
        path, name = entry[1], entry[2]
        if path in joints and body and joints[path]['bone'] not in body:
            warnings.append(f"{name}: the character has no joint {joints[path]['bone']}; the weapon is left out.")
            read.remove(entry)
    if body and not any(holds_head(head_joints(skeleton), meshes) is not False
                        for _, path, _, _, skeleton, meshes, _ in read if path not in joints):
        warnings.append(HEAD_NOTICE)

    # Every texture the materials use, converted in one pass.
    wanted, kinds = {}, defaultdict(set)
    for *_, materials in read:
        for material in materials.values():
            for names, kind in ((models.ALBEDO, 'albedo'), (models.NORMAL, 'normal'), (models.EMISSIVE, 'bloommask')):
                texture = models.slot(material, names)
                if texture:
                    wanted[texture] = models.image_name(images, texture, kind)
                    kinds[kind].add(texture)
    ctx.notify('character', f'Converting {len(wanted)} textures', 36)
    # Some decls name a glow image the game does not ship (soldier_shield_gun_e); without it nothing glows, as in the game.
    converted = convert_textures(game, entries, wanted, textures_out, warnings, optional=kinds['bloommask'],
                                 normals=kinds['normal'])

    manifest = dict(version=5, game=profile.id, models=[], warnings=warnings, material_library='', boneRotation='quaternion',
                    **profile.space().to_json())
    for index, path, name, model, skeleton, meshes, materials in read:
        data_path = out / f'{index:02d}_{name}.npz'
        names = list(dict.fromkeys(m.material for m, arrays in zip(model.meshes, meshes) if arrays is not None))
        if not names:
            warnings.append(f'{name}: none of its meshes is in the chosen look.')
            continue
        labels = short_names(names)
        stats = write_arrays(data_path, model, skeleton, meshes, names, labels)
        specs = [dict(material_spec(materials[n], converted, profile), name=label) for n, label in zip(names, labels)]
        joint = joints.get(path)
        manifest['models'].append(dict(name=name, source=path, data=str(data_path.resolve()), materials=specs, stats=stats,
                                       attachment=dict(kind='joint', bone=joint['bone']) if joint else None,
                                       role='Weapon' if joint else 'Body'))
        print(f"Prepared {name}: {stats['vertices']:,} vertices, {stats['triangles']:,} triangles, {stats['bones']} bones",
              flush=True)
    if not manifest['models']:
        raise ValueError('None of the chosen models could be read. Choose other parts.')
    manifest['texture_count'] = len(converted)
    manifest['warnings'] = list(dict.fromkeys(warnings))
    check_manifest(manifest, f'The {profile.name} character manifest')
    path = out / 'character.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"Character ready: {len(manifest['models'])} models, {len(converted)} texture images, "
          f"{len(manifest['warnings'])} notices", flush=True)
    for warning in manifest['warnings']:
        print(f'NOTICE: {warning}', flush=True)
    return path


def chosen_meshes(model, definition, look=''):
    """Which meshes of a model to read: those of the look (its first one by default), else all but the gore pieces.

    The Marauder's Base look leaves out 30 gore meshes; the soldier's Shield look adds the shield."""
    groups = [models.mesh_group(mesh.name) for mesh in model.meshes]
    looks = dict(definition.get('looks') or []) if definition else {}
    names = set(looks.get(look) or next(iter(looks.values()), None) or [])
    if names & set(groups):
        return [group in names for group in groups]
    gore = set(definition.get('gore') or []) if definition else set()
    return [group not in gore for group in groups]


def on_tag(skeleton, meshes, tag, name):
    """A weapon placed at its tag: the tag's offset from its joint moves the weapon's root bones and vertices,
    and every bone is named after the weapon. Blender then hangs it on the joint itself."""
    rotation = np.asarray(tag['rotation'], np.float64)
    rotation /= max(np.linalg.norm(rotation), 1e-12)
    matrix, offset = rotation_matrix(rotation), np.asarray(tag['translation'], np.float64)
    roots = np.asarray(skeleton.parents) < 0
    translations = skeleton.translations.astype(np.float64).copy()
    rotations = skeleton.rotations.astype(np.float64).copy()
    translations[roots] = translations[roots] @ matrix.T + offset
    rotations[roots] = [multiply(rotation, q) for q in rotations[roots]]
    placed = md6.Skeleton([f'{name}_{bone}' for bone in skeleton.names], skeleton.parents, rotations,
                          skeleton.scales, translations)
    moved = []
    for arrays in meshes:
        if arrays is not None:
            arrays = dict(arrays, positions=arrays['positions'] @ matrix.T + offset)
            if 'normals' in arrays:
                arrays['normals'] = arrays['normals'] @ matrix.T
        moved.append(arrays)
    return placed, moved


def rotation_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def multiply(a, b):
    """The quaternion a * b, both as x, y, z, w: b turned first, then a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def head_joints(skeleton):
    """The head joint and every joint below it; empty for a skeleton without a head joint."""
    names = [n.lower() for n in skeleton.names]
    head = next((names.index(n) for n in HEAD_JOINTS if n in names), None)
    if head is None:
        return set()
    below = set()
    for i in range(len(names)):
        k, seen = i, 0
        while k >= 0 and seen <= len(names):
            if k == head:
                below.add(i)
                break
            k, seen = skeleton.parents[k], seen + 1
    return below


def holds_head(below, meshes, share=.05):
    """Whether a model holds the head: at least share of its vertices follow the head joint or one below it.
    None when the skeleton has no head joint, or the model no skin."""
    found = [m for m in meshes if m is not None and 'joints' in m and 'weights' in m]
    if not below or not found:
        return None
    joints = np.concatenate([m['joints'] for m in found])
    weights = np.concatenate([m['weights'] for m in found])
    on_head = np.where(np.isin(joints, list(below)), weights, 0).sum(axis=1)
    return float(np.mean(on_head > .5)) >= share


def head_notes(game, entries, path, definition):
    """{look: 'with head' or 'without head'} for a model, '' for its only look; read at its least detailed level
    of detail and kept for the bridge run. Empty when the skeleton has no head joint."""
    key = (str(game.root).lower(), path)
    if key in _HEADS:
        return _HEADS[key]
    notes = {}
    try:
        entry = entries[('baseModel', path)]
        model = models.read_model(game.read(entry))
        below = head_joints(md6.read_skeleton(game.read(entries[('skeleton', model.skeleton)])))
        lod = max((lod for lod in range(models.LODS) if model.disk[lod][1]), default=None)
        if below and lod is not None:
            meshes = models.read_geometry(model, game.stream(models.geometry_key(entry, lod), model.disk[lod][1]), lod)
            looks = [look for look, _ in (definition or {}).get('looks', [])]
            for look in looks if len(looks) > 1 else ['']:
                kept = [m for m, keep in zip(meshes, chosen_meshes(model, definition, look)) if keep]
                held = holds_head(below, kept)
                if held is not None:
                    notes[look] = 'with head' if held else 'without head'
    except (KeyError, IndexError, ValueError, OSError):
        notes = {}
    _HEADS[key] = notes
    return notes


def short_names(materials):
    """Material names Blender keeps whole: the decl's file name, with its folder only where two share it."""
    stems = [m.rsplit('/', 1)[-1] for m in materials]
    return [m.rsplit('/', 2)[-2] + '_' + s if stems.count(s) > 1 and '/' in m else s for m, s in zip(materials, stems)]


def write_arrays(path, model, skeleton, meshes, names, labels):
    """The model arrays Blender reads (docs/INTERCHANGE.md): every mesh of the model in one, by material."""
    parts = {key: [] for key in ('positions', 'normals', 'uvs', 'joints', 'weights', 'faces', 'face_materials', 'vertex_materials')}
    base = 0
    for mesh, arrays in zip(model.meshes, meshes):
        if arrays is None:
            continue
        count = len(arrays['positions'])
        material = names.index(mesh.material)
        weights = np.clip(arrays.get('weights', np.tile([1.0, 0, 0, 0], (count, 1))), 0.0, None)
        weights /= np.maximum(weights.sum(1, keepdims=True), 1e-8)
        parts['positions'].append(arrays['positions'])
        parts['normals'].append(arrays.get('normals', np.zeros((count, 3))))
        parts['uvs'].append(arrays.get('uvs', np.zeros((count, 2))))
        parts['joints'].append(np.clip(arrays.get('joints', np.zeros((count, 4), np.int64)), 0, len(skeleton) - 1))
        parts['weights'].append(weights)
        # id Tech winds front faces clockwise; Blender expects counter-clockwise, and the basis does not reflect.
        parts['faces'].append(arrays['faces'][:, [0, 2, 1]] + base)
        parts['face_materials'].append(np.full(len(arrays['faces']), material))
        parts['vertex_materials'].append(np.full(count, material))
        base += count
    joined = {key: np.concatenate(values) for key, values in parts.items()}
    np.savez_compressed(path, positions=joined['positions'].astype(np.float32), normals=joined['normals'].astype(np.float32),
                        uvs=joined['uvs'].astype(np.float32), uv_0=joined['uvs'].astype(np.float32),
                        bone_indices=joined['joints'].astype(np.int32), bone_weights=joined['weights'].astype(np.float32),
                        faces=joined['faces'].astype(np.int32), face_materials=joined['face_materials'].astype(np.int32),
                        vertex_materials=joined['vertex_materials'].astype(np.int32),
                        bone_names=np.asarray(skeleton.names, dtype='U'),
                        bone_parents=np.asarray(skeleton.parents, dtype=np.int32),
                        bone_translations=skeleton.translations.astype(np.float32),
                        bone_quaternions=skeleton.rotations.astype(np.float32),
                        bone_scales=skeleton.scales.astype(np.float32),
                        material_names=np.asarray(labels or ['Material 0'], dtype='U'))
    return dict(vertices=len(joined['positions']), triangles=len(joined['faces']), bones=len(skeleton),
                materials=len(names), uv_layers=1)


def convert_textures(game, entries, wanted, output, warnings, optional=(), normals=()):
    """PNG images of the wanted textures: {texture path: dict(path, stem)}, and for normals the way their green
    points (convention). Missing optional ones go unmentioned."""
    staging = output / 'dds'
    staging.mkdir(parents=True, exist_ok=True)
    stems, written, missing, conventions = {}, [], [], {}
    for texture, image_key in wanted.items():
        entry = entries.get(('image', image_key)) if image_key else None
        if entry is None:
            if texture not in optional:
                missing.append(texture)
            continue
        try:
            image = models.to_rgba(models.read_image(game.read(entry), game.stream, entry.hash))
            if texture in normals:
                conventions[texture] = models.normal_convention(image)
            data = models.dds(image)
        except ValueError as error:
            warnings.append(f'{Path(texture).name}: {error}')
            continue
        stem = re.sub(r'[^a-zA-Z0-9_.-]', '_', Path(texture).stem)
        while stem in stems.values():
            stem += '_'
        stems[texture] = stem
        target = staging / f'{stem}.dds'
        target.write_bytes(data)
        written.append(target)
    if missing:
        names = sorted(Path(t).name for t in missing)
        warnings.append(f"Textures not in the archives: {', '.join(names[:8])}{', …' if len(names) > 8 else ''}.")
    problem = dds_to_png(written, output) if written else ''
    if problem:
        warnings.append(problem)
    images = {}
    for texture, stem in stems.items():
        png = next((p for p in (output / f'{stem}.PNG', output / f'{stem}.png') if p.is_file()), None)
        if png:
            images[texture] = dict(path=str(png.resolve()), stem=stem)
            if texture in conventions:
                images[texture]['convention'] = conventions[texture]
        else:
            warnings.append(f'{Path(texture).name} could not be converted.')
    for path in written:
        path.unlink(missing_ok=True)
    return images


def material_spec(material, images, profile):
    """A manifest material: base color, normal map and glow from the decl's parms.

    A normal map's convention is the one convert_textures measured, OpenGL style (green up) unless it found DirectX.
    The albedo's alpha is opacity only in alpha-tested materials. The bloom mask is the colour the surface glows in.
    The specular (_s) and smoothness (_g) images stay out: they are not metalness or roughness. Eye overlays and
    glow cards are hidden: opacity 0, which the character export also leaves out."""
    spec = dict(name=material.name, mtd=material.templates[0] if material.templates else '', family=profile.name,
                albedo=None, normal=None, emissive=None, samplers=[], alpha=False, color=[1, 1, 1])
    spec['samplers'] = [dict(semantic=parm, texture=path, uv=0, scale=[1, 1], found=path in images)
                        for parm, path in sorted(material.textures.items())]
    albedo = models.slot(material, models.ALBEDO)
    if albedo in images:
        spec['alpha'] = material.alpha
        spec['albedo'] = dict(images[albedo], linear=False, uv=0, scale=[1, 1], packedAlpha=not material.alpha)
    elif not material.textures:
        spec['color'] = [.6, .6, .6]
    normal = models.slot(material, models.NORMAL)
    if normal in images:
        spec['normal'] = dict(images[normal], linear=True, uv=0, scale=[1, 1], channels='xyz', packedAlpha=False)
        spec['normal'].setdefault('convention', 'opengl')
    emissive = models.slot(material, models.EMISSIVE)
    if emissive in images:
        spec['emissive'] = dict(images[emissive], linear=False, uv=0, scale=[1, 1])
    if material.overlay or material.card:
        spec['opacityValue'] = 0.0
    return spec
