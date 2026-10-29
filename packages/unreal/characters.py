"""Character models of Unreal games for Blender: skeletal mesh arrays, material slots and PNG textures.

Writes the bridge's character manifest version 5 (docs/INTERCHANGE.md): one .npz per skeletal mesh with rest
rotations as quaternions, the textures the decoder wrote, and the Unreal space, so Blender converts the models
the same way as the motion.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from games.api import check_manifest

DTYPES = {'f4': np.float32, 'i4': np.int32}
# Blend modes whose base color alpha cuts the material out.
CUT_OUT = {'BLEND_Masked', 'BLEND_Translucent', 'BLEND_AlphaComposite', 'BLEND_AlphaHoldout'}


def read_mesh(path):
    """The decoder's mesh JSON and its arrays."""
    path = Path(path)
    info = json.loads(path.read_text(encoding='utf-8-sig'))
    data = (path.parent / info['bin']).read_bytes()
    arrays = {}
    for name, entry in info['arrays'].items():
        values = np.frombuffer(data, dtype=DTYPES[entry['dtype']], count=entry['length'] // 4, offset=entry['offset'])
        arrays[name] = values.reshape(entry['shape'])
    return info, arrays


def write_arrays(path, info, arrays):
    """The model arrays Blender reads (docs/INTERCHANGE.md), with quaternion rest rotations."""
    bones = info['bones']
    uv_names = sorted([k for k in arrays if k.startswith('uv_')], key=lambda k: int(k[3:])) or ['uv_0']
    count = len(arrays['positions'])
    uvs = {k: arrays.get(k, np.zeros((count, 2), np.float32)) for k in uv_names}
    names = [m['slot'] for m in info['materials']] or ['Material 0']
    np.savez_compressed(path, positions=arrays['positions'], normals=arrays['normals'], uvs=uvs[uv_names[0]],
                        bone_indices=arrays['bone_indices'], bone_weights=arrays['bone_weights'], faces=arrays['faces'],
                        face_materials=arrays['face_materials'], vertex_materials=arrays['vertex_materials'],
                        bone_names=np.asarray([b['name'] for b in bones], dtype='U'),
                        bone_parents=np.asarray([b['parent'] for b in bones], dtype=np.int32),
                        bone_translations=np.asarray([b['translation'] for b in bones], dtype=np.float32).reshape(-1, 3),
                        bone_quaternions=np.asarray([b['rotation'] for b in bones], dtype=np.float32).reshape(-1, 4),
                        bone_scales=np.asarray([b['scale'] for b in bones], dtype=np.float32).reshape(-1, 3),
                        material_names=np.asarray(names, dtype='U'), **uvs)
    return dict(vertices=count, triangles=len(arrays['faces']), bones=len(bones), materials=len(info['materials']),
                uv_layers=len(uv_names))


def image(texture):
    """A manifest image for a texture the decoder wrote."""
    file = Path(texture['file'])
    return dict(path=str(file.resolve()), stem=file.stem, linear=not texture.get('srgb', True), uv=0, scale=[1, 1])


def material_spec(material, profile):
    """A manifest material: base color and normal map from the slot's textures."""
    spec = dict(name=material['slot'], mtd=material.get('path', ''), family=profile.name, albedo=None, normal=None, emissive=None,
                samplers=[], alpha=False, color=[1, 1, 1])
    found = {kind: material.get(kind) for kind in ('albedo', 'normal', 'mask', 'emissive')}
    spec['samplers'] = [dict(semantic=kind, texture=texture['texture'], uv=0, scale=[1, 1], found=Path(texture['file']).is_file())
                        for kind, texture in found.items() if texture]
    color = material.get('color')
    if not material.get('path'):
        spec['color'] = [.6, .6, .6]
    elif isinstance(color, list) and len(color) >= 3 and not found['albedo']:
        spec['color'] = [float(v) for v in color[:3]]
    albedo, normal = found['albedo'], found['normal']
    if albedo and Path(albedo['file']).is_file():
        # Masked and translucent materials cut out by the base color's alpha; elsewhere alpha holds other data or nothing.
        spec['alpha'] = material.get('blendMode') in CUT_OUT
        spec['albedo'] = dict(image(albedo), linear=False, packedAlpha=not spec['alpha'])
    if normal and Path(normal['file']).is_file():
        # Unreal's normal maps are DirectX style and keep X and Y; Blender rebuilds Z.
        spec['normal'] = dict(image(normal), linear=True, convention='directx', channels='xy', packedAlpha=True)
    return spec


def prepare_character(selection, models, output, profile, ctx):
    """Export a character's skeletal meshes, materials and textures into a manifest for Blender."""
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    ctx.notify('character', f'Exporting {len(models)} skeletal mesh{"es" if len(models) != 1 else ""}', 36)
    printed = ctx.run('decoder', 'mesh', selection['source'], out, *models, timeout=1800)
    warnings = [line[4:].strip(' :') for line in printed.splitlines() if line.startswith('NOTE')]
    listing = json.loads((out / 'meshes.json').read_text(encoding='utf-8-sig'))
    manifest = dict(version=5, game=profile.id, models=[], warnings=warnings, material_library='', boneRotation='quaternion',
                    **profile.space().to_json())
    # Each model keeps the role the part list showed for it.
    roles = {part['path']: part['role'] for part in selection.get('parts') or []}
    for index, entry in enumerate(listing['meshes']):
        if entry.get('error') or not entry.get('json'):
            continue
        info, arrays = read_mesh(entry['json'])
        name = info['name']
        data_path = Path(entry['json']).with_suffix('.npz')
        stats = write_arrays(data_path, info, arrays)
        manifest['models'].append(dict(name=name, source=entry['path'], data=str(data_path.resolve()),
                                       materials=[material_spec(m, profile) for m in info['materials']], stats=stats,
                                       attachment=None, role=roles.get(entry['path']) or ('Body' if index == 0 else 'Model')))
        print(f"Prepared {name}: {stats['vertices']:,} vertices, {stats['triangles']:,} triangles, {stats['bones']} bones", flush=True)
    if not manifest['models']:
        raise ValueError('None of the chosen skeletal meshes could be read. Choose other parts.')
    manifest['texture_count'] = len(listing.get('textures') or {})
    manifest['warnings'] = list(dict.fromkeys(warnings))
    check_manifest(manifest, f'The {profile.name} character manifest')
    path = out / 'character.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"Character ready: {len(manifest['models'])} parts, {manifest['texture_count']} texture images, "
          f"{len(manifest['warnings'])} notices", flush=True)
    for warning in manifest['warnings']:
        print(f'NOTICE: {warning}', flush=True)
    return path
