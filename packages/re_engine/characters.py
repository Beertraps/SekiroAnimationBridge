"""Character models of RE Engine games for Blender: mesh arrays, mdf2 materials and tex textures.

Writes the bridge's character manifest version 5 (docs/INTERCHANGE.md): one .npz per mesh with
rest rotations as quaternions, PNG textures, and the RE Engine space, so Blender converts the
models the same way as the motion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from games.api import check_manifest, dds_to_png

from . import materialize

# mdf2 texture slots, in the order a material's base color is looked for.
ALBEDO_SLOTS = ('BaseMetalMap', 'BaseShiftMap', 'BaseAlphaMap', 'BaseDielectricMap', 'BaseColorMap', 'AlbedoMap', 'BaseMap')
NORMAL_SLOTS = ('NormalRoughnessMap', 'NormalMap')
# Alpha, translucency, occlusion and subsurface scattering in red, green, blue and alpha.
ATOS_SLOT = 'AlphaTranslucentOcclusionSSSMap'
NULL_TEXTURE = re.compile(r'(^|/)null[a-z_]*\.tex$', re.IGNORECASE)
DTYPES = {'f4': np.float32, 'i4': np.int32}


def read_mesh(stem):
    """The decoder's mesh JSON and its arrays."""
    stem = Path(stem)
    info = json.loads(stem.with_name(stem.name + '.json').read_text(encoding='utf-8-sig'))
    data = stem.with_name(stem.name + '.bin').read_bytes()
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
    np.savez_compressed(path, positions=arrays['positions'], normals=arrays['normals'], uvs=uvs[uv_names[0]],
                        bone_indices=arrays['bone_indices'], bone_weights=arrays['bone_weights'], faces=arrays['faces'],
                        face_materials=arrays['face_materials'], vertex_materials=arrays['vertex_materials'],
                        bone_names=np.asarray([b['name'] for b in bones], dtype='U'),
                        bone_parents=np.asarray([b['parent'] for b in bones], dtype=np.int32),
                        bone_translations=np.asarray([b['translation'] for b in bones], dtype=np.float32).reshape(-1, 3),
                        bone_quaternions=np.asarray([b['rotation'] for b in bones], dtype=np.float32).reshape(-1, 4),
                        bone_scales=np.asarray([b['scale'] for b in bones], dtype=np.float32).reshape(-1, 3),
                        material_names=np.asarray(info['materials'] or ['Material 0'], dtype='U'), **uvs)
    return dict(vertices=count, triangles=len(arrays['faces']), bones=len(bones), materials=len(info['materials']),
                uv_layers=len(uv_names))


def texture_paths(stored, profile):
    """Where an mdf2 texture path is in the archives: its full-resolution streaming copy first, then the normal one."""
    path = stored.replace('\\', '/').lower().lstrip('/')
    version = profile.formats['tex']
    return [f'natives/x64/streaming/{path}.{version}', f'natives/x64/{path}.{version}']


def slot_texture(material, slots):
    for slot in slots:
        entry = next((t for t in material['textures'] if t['slot'] == slot and t['path'] and not NULL_TEXTURE.search(t['path'])), None)
        if entry:
            return entry
    return None


def params(material):
    return {p['name']: p['value'] for p in material.get('params', [])}


def uses_alpha_map(material):
    """Hair, and materials that switch their alpha map on, cut out with the red channel of their ATOS texture."""
    values = params(material)
    switched = any(values.get(key, [0])[0] for key in ('UseAlphaMap', 'Use_AlphaMap'))
    return switched or 'hair' in material.get('shader', '').lower()


def hidden(material):
    """Transparent overlay layers such as eye wetness, which the preview cannot shade, are left invisible."""
    shader = material.get('shader', '').lower()
    return 'transparent' in shader and not slot_texture(material, ('BaseAlphaMap',))


def mdf2_path(mesh_path, profile):
    return re.sub(r'\.mesh\.\d+$', f'.mdf2.{profile.formats["mdf2"]}', mesh_path)


def prepare_character(catalog, models, output, profile, ctx):
    """Decode a character's meshes, materials and textures into a manifest for Blender."""
    out = Path(output)
    textures_out = out / 'textures'
    textures_out.mkdir(parents=True, exist_ok=True)
    warnings, decoded = [], []
    for index, (path, local) in enumerate(models):
        name = Path(path).name.split('.')[0]
        if not local:
            warnings.append(f'{name}: the model is not in the archives.')
            continue
        stem = out / f'{index:02d}_{name}'
        ctx.run('decoder', 'mesh', local, stem)
        info, arrays = read_mesh(stem)
        material_file = materialize(catalog, [mdf2_path(path, profile)], ctx).get(mdf2_path(path, profile))
        materials = {}
        if material_file:
            listing = out / f'{index:02d}_{name}.mdf2.json'
            ctx.run('decoder', 'mdf2', material_file, listing)
            materials = {m['name']: m for m in json.loads(listing.read_text(encoding='utf-8-sig'))['materials']}
        else:
            warnings.append(f'{name}: no material file ({Path(mdf2_path(path, profile)).name}); the model stays untextured.')
        decoded.append((index, path, name, stem, info, arrays, materials))

    # Every texture the materials use, extracted in one pass.
    wanted = {}
    for *_, materials in decoded:
        for material in materials.values():
            for entry in (slot_texture(material, ALBEDO_SLOTS), slot_texture(material, NORMAL_SLOTS),
                          slot_texture(material, (ATOS_SLOT,)) if uses_alpha_map(material) else None):
                if entry:
                    wanted[entry['path']] = texture_paths(entry['path'], profile)
    ctx.notify('character', f'Extracting {len(wanted)} textures', 36)
    found = materialize(catalog, [p for paths in wanted.values() for p in paths], ctx)
    sources = {stored: next((found[p] for p in paths if p in found), None) for stored, paths in wanted.items()}
    images = convert_textures({s: f for s, f in sources.items() if f}, textures_out, ctx)
    missing = sorted(Path(s).name for s, f in sources.items() if not f)
    if missing:
        warnings.append(f"Textures not in the archives: {', '.join(missing[:8])}{', …' if len(missing) > 8 else ''}.")

    manifest = dict(version=5, game=profile.id, models=[], warnings=warnings, material_library='', boneRotation='quaternion',
                    **profile.space().to_json())
    for index, path, name, stem, info, arrays, materials in decoded:
        data_path = out / f'{index:02d}_{name}.npz'
        stats = write_arrays(data_path, info, arrays)
        specs = [material_spec(materials.get(material_name), material_name, images, profile) for material_name in info['materials']]
        manifest['models'].append(dict(name=name, source=path, data=str(data_path.resolve()), materials=specs, stats=stats,
                                       attachment=None, role=role(path)))
        print(f"Prepared {name}: {stats['vertices']:,} vertices, {stats['triangles']:,} triangles, {stats['bones']} bones", flush=True)
    if not manifest['models']:
        raise ValueError('None of the chosen models could be read. Choose other parts.')
    manifest['texture_count'] = len(images)
    manifest['warnings'] = list(dict.fromkeys(warnings))
    check_manifest(manifest, f'The {profile.name} character manifest')
    path = out / 'character.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"Character ready: {len(manifest['models'])} parts, {len(images)} texture images, {len(manifest['warnings'])} notices", flush=True)
    for warning in manifest['warnings']:
        print(f'NOTICE: {warning}', flush=True)
    return path


def role(path):
    folder = path.split('/')[-2] if '/' in path else ''
    return 'Head' if '_head' in folder else 'Hair' if '_hair' in folder else 'Body' if folder.endswith('_body') else 'Character'


def convert_textures(sources, output, ctx):
    """PNG images of tex files: the decoder writes each as DDS, the bridge converts them to PNG."""
    if not sources:
        return {}
    staging = output / 'dds'
    staging.mkdir(parents=True, exist_ok=True)
    names, dds = {}, []
    for stored, local in sources.items():
        stem = re.sub(r'[^a-zA-Z0-9_.-]', '_', Path(stored).name.rsplit('.', 1)[0])
        while stem in names.values():
            stem += '_'
        names[stored] = stem
        target = staging / f'{stem}.dds'
        ctx.run('decoder', 'tex', local, target)
        dds.append(target)
    ctx.notify('character', f'Converting {len(dds)} textures', 40)
    problem = dds_to_png(dds, output)
    if problem:
        print(f'NOTICE: {problem}', flush=True)
    images = {}
    for stored, stem in names.items():
        png = next((p for p in (output / f'{stem}.PNG', output / f'{stem}.png') if p.is_file()), None)
        if png:
            images[stored] = dict(path=str(png.resolve()), stem=stem)
    return images


def material_spec(material, name, images, profile):
    """A manifest material: base color, normal map and cut-out from the mdf2 slots."""
    spec = dict(name=name, mtd='', family=profile.name, albedo=None, normal=None, emissive=None, samplers=[], alpha=False, color=[1, 1, 1])
    if not material:
        spec['color'] = [.6, .6, .6]
        return spec
    spec['mtd'] = material.get('shader', '')
    color = params(material).get('BaseColor')
    if isinstance(color, list) and len(color) >= 3:
        spec['color'] = [float(v) for v in color[:3]]
    spec['samplers'] = [dict(semantic=t['slot'], texture=t['path'], uv=0, scale=[1, 1], found=t['path'] in images)
                        for t in material['textures']]
    albedo = slot_texture(material, ALBEDO_SLOTS)
    if albedo and albedo['path'] in images:
        # ALBA keeps alpha in the base color; ALBM keeps metalness there.
        spec['alpha'] = albedo['slot'] == 'BaseAlphaMap'
        spec['albedo'] = dict(images[albedo['path']], linear=False, uv=0, scale=[1, 1], packedAlpha=not spec['alpha'])
    normal = slot_texture(material, NORMAL_SLOTS)
    if normal and normal['path'] in images:
        # NRMR keeps roughness in alpha.
        spec['normal'] = dict(images[normal['path']], linear=True, uv=0, scale=[1, 1], convention='directx', channels='xyz',
                              packedAlpha=True)
    atos = slot_texture(material, (ATOS_SLOT,)) if uses_alpha_map(material) else None
    if atos and atos['path'] in images and not spec['alpha']:
        spec['opacity'] = dict(images[atos['path']], linear=True, uv=0, scale=[1, 1], channel='R', packedAlpha=True)
    if hidden(material):
        spec['opacityValue'] = 0.0
    return spec
