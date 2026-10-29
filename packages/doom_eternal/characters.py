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


def model_name(path):
    return path.rsplit('/', 1)[-1].rsplit('.', 1)[0]


def prepare_character(game, entries, paths, output, profile, ctx):
    """Read the chosen models with level-of-detail 0 geometry, their materials and textures, into a manifest."""
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
        entry = entries.get(('baseModel', path))
        name = model_name(path)
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
        meshes = models.read_geometry(model, data, 0)
        materials = {m.material: models.read_material(read_decl, m.material) for m in model.meshes}
        read.append((index, path, name, model, skeleton, meshes, materials))

    # Every texture the materials use, converted in one pass.
    wanted = {}
    for *_, materials in read:
        for material in materials.values():
            for names, kind in ((models.ALBEDO, 'albedo'), (models.NORMAL, 'normal')):
                texture = models.slot(material, names)
                if texture:
                    wanted[texture] = models.image_name(images, texture, kind)
    ctx.notify('character', f'Converting {len(wanted)} textures', 36)
    converted = convert_textures(game, entries, wanted, textures_out, warnings)

    manifest = dict(version=5, game=profile.id, models=[], warnings=warnings, material_library='', boneRotation='quaternion',
                    **profile.space().to_json())
    for index, path, name, model, skeleton, meshes, materials in read:
        data_path = out / f'{index:02d}_{name}.npz'
        names = list(dict.fromkeys(m.material for m, arrays in zip(model.meshes, meshes) if arrays is not None))
        labels = short_names(names)
        stats = write_arrays(data_path, model, skeleton, meshes, names, labels)
        specs = [dict(material_spec(materials[n], converted, profile), name=label) for n, label in zip(names, labels)]
        manifest['models'].append(dict(name=name, source=path, data=str(data_path.resolve()), materials=specs, stats=stats,
                                       attachment=None, role='Body'))
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
    return path


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


def convert_textures(game, entries, wanted, output, warnings):
    """PNG images of the wanted textures: {texture path: dict(path, stem)}."""
    staging = output / 'dds'
    staging.mkdir(parents=True, exist_ok=True)
    stems, written, missing = {}, [], []
    for texture, image_key in wanted.items():
        entry = entries.get(('image', image_key)) if image_key else None
        if entry is None:
            missing.append(texture)
            continue
        try:
            image = models.read_image(game.read(entry), game.stream, entry.hash)
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
        else:
            warnings.append(f'{Path(texture).name} could not be converted.')
    for path in written:
        path.unlink(missing_ok=True)
    return images


def material_spec(material, images, profile):
    """A manifest material: base color and normal map from the decl's parms."""
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
        spec['normal'] = dict(images[normal], linear=True, uv=0, scale=[1, 1], convention='opengl', channels='xyz',
                              packedAlpha=False)
    if material.overlay:
        spec['opacityValue'] = 0.0
    return spec
