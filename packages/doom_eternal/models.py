"""DOOM Eternal's character models: md6 models (resource type baseModel), their geometry in the .streamdb
files, material2 decls and images.

Ported from Valen (https://github.com/jandk/valen, MIT, by Jan De Kock): Md6Model, GeometryReader,
IdTechGeoReader, ImageReader and AbstractMaterialReader. Positions are in id Tech space and metres, like
the skeletons.
"""
from __future__ import annotations

import re
import struct

import numpy as np

from .md6 import Reader

LODS = 5
MASK64 = (1 << 64) - 1
# Vertex streams by mask: their size per vertex.
POSITION_SHORT, POSITION, NORMAL_TANGENT, COLOR = 0x20, 0x01, 0x14, 0x08
MATERIAL_UV_SHORT, MATERIAL_UV = 0x20000, 0x8000
STREAM_SIZES = {0x20: 8, 0x01: 12, 0x14: 8, 0x40: 4, 0x02: 8, 0x20000: 4, 0x8000: 8, 0x08000000: 8, 0x10000000: 8,
                0x20000000: 4, 0x40000000: 4, 0x08: 4, 0x010000: 8, 0x80: 12, 0x01000000: 0, 0x02000000: 4,
                0x04000000: 8}


class LodInfo:
    __slots__ = ('vertices', 'faces', 'offset', 'scale', 'uv_offset', 'uv_scale', 'mask')


class MeshInfo:
    __slots__ = ('name', 'material', 'joint_offset', 'lods')


class Model:
    """An md6 model: its skeleton, meshes and where each level of detail is in its geometry stream."""
    __slots__ = ('skeleton', 'joint_remap', 'meshes', 'layouts', 'disk')


def read_model(data):
    reader = Reader(data)
    model = Model()
    model.skeleton = reader.string()
    reader.take(24 + 1 + 4)  # bounds expansion, remap for skinning, padding
    model.joint_remap = np.frombuffer(reader.take(reader.short() & 0xFFFF), np.uint8).astype(np.int64)
    reader.take(24)  # default bounds
    if reader.int() != LODS:
        raise ValueError('This model does not have five levels of detail.')
    reader.take(LODS * 4 + 4 + 36)  # deviations, blend shape names, padding
    model.meshes = []
    for _ in range(reader.int()):
        mesh = MeshInfo()
        mesh.name, mesh.material = reader.string(), reader.string()
        reader.take(5)
        _, mesh.joint_offset, _, _ = struct.unpack('<4i', reader.take(16))
        mesh.lods = {}
        for lod in range(LODS):
            if struct.unpack('<i', reader.take(4))[0]:
                continue
            info = LodInfo()
            info.vertices, info.faces = struct.unpack('<2i', reader.take(8))
            reader.take(24)  # bounds
            info.offset = np.array(struct.unpack('<3f', reader.take(12)))
            info.scale = struct.unpack('<f', reader.take(4))[0]
            info.uv_offset = np.array(struct.unpack('<2f', reader.take(8)))
            info.uv_scale, info.mask = struct.unpack('<fI', reader.take(8))
            reader.take(8)
            mesh.lods[lod] = info
        reader.take(5)
        model.meshes.append(mesh)
    for _ in range(reader.int()):  # material infos: the same materials as the meshes name
        reader.string()
        reader.take(12)
    reader.string()  # geometry decals
    streams = reader.int()
    counts = struct.unpack(f'<{streams}i', reader.take(4 * streams))
    reader.take(4 * sum(counts))
    model.layouts = []
    for _ in range(reader.int()):
        combined, _, count = struct.unpack('<IiI', reader.take(12))
        masks = struct.unpack(f'<{count}I', reader.take(4 * count))
        offsets = struct.unpack(f'<{count}i', reader.take(4 * count))
        model.layouts.append((combined, masks, offsets, reader.int()))
    model.disk = [struct.unpack('<4i', reader.take(16)) for _ in range(LODS)]  # compression, size, packed size, offset
    return model


def geometry_key(entry, lod):
    """The stream ID of one level of detail of a model's geometry."""
    return (entry.hash << 4 | lod) & MASK64


def read_geometry(model, data, lod=0):
    """One dictionary of arrays per mesh of the model, None for a mesh without this level of detail."""
    combined, masks, offsets, index = model.layouts[lod]
    offsets = list(offsets)
    lookup = np.zeros(max(len(model.joint_remap), int(model.joint_remap.max(initial=0)) + 1), np.int64)
    lookup[model.joint_remap] = np.arange(len(model.joint_remap))
    meshes = []
    for mesh in model.meshes:
        info = mesh.lods.get(lod)
        if info is None or info.mask != combined:
            meshes.append(None)
            continue
        count = info.vertices
        arrays = {}
        for slot, mask in enumerate(masks):
            size = STREAM_SIZES.get(mask)
            if size is None:
                raise ValueError(f'{mesh.name} uses vertex data {mask:#x}, which this package does not read.')
            raw = np.frombuffer(data, np.uint8, count * size, offsets[slot]).reshape(count, size) if size else None
            offsets[slot] += count * size
            if mask == POSITION_SHORT:
                arrays['positions'] = raw[:, :6].copy().view('<u2') / 65535.0 * info.scale + info.offset
            elif mask == POSITION:
                arrays['positions'] = raw.copy().view('<f4').astype(np.float64) * info.scale + info.offset
            elif mask == NORMAL_TANGENT:
                normals = raw[:, 0:3] / 255.0 * 2.0 - 1.0
                arrays['normals'] = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8)
                # Skin weights hide in the spare bytes of the normal and the tangent.
                packed_normal, packed_tangent = raw[:, 3].astype(np.int64), raw[:, 7].astype(np.int64)
                second = (packed_tangent & 0x7F) / 254.0
                third = (packed_normal >> 4 & 0xF) / 45.0
                fourth = (packed_normal & 0xF) / 60.0
                arrays['weights'] = np.stack([1.0 - second - third - fourth, second, third, fourth], 1)
            elif mask == COLOR:
                arrays['joints'] = raw.astype(np.int64)
            elif mask == MATERIAL_UV_SHORT and 'uvs' not in arrays:
                arrays['uvs'] = raw.copy().view('<u2') / 65535.0 * info.uv_scale + info.uv_offset
            elif mask == MATERIAL_UV and 'uvs' not in arrays:
                arrays['uvs'] = raw.copy().view('<f4').astype(np.float64) * info.uv_scale + info.uv_offset
        faces = np.frombuffer(data, '<u2', info.faces * 3, index).reshape(-1, 3).astype(np.int64)
        index += info.faces * 6
        if 'positions' not in arrays:
            raise ValueError(f'{mesh.name} has no positions.')
        if 'joints' in arrays:
            slots = np.clip(arrays['joints'] + mesh.joint_offset, 0, len(lookup) - 1)
            arrays['joints'] = lookup[slots]
        arrays['faces'] = faces
        meshes.append(arrays)
    return meshes


# Materials

TEXTURE = re.compile(r'(\w+)\s*=\s*\{\s*filePath\s*=\s*"([^"]*)"', re.IGNORECASE)
INHERIT = re.compile(r'inherit\s*=\s*"([^"]+)"', re.IGNORECASE)
ALBEDO = ('albedo', 'decalalbedo', 'eyealbedomap', 'glassalbedomap', 'hairalbedomap')
NORMAL = ('normal', 'decalnormal', 'eyenormalmap', 'glassnormalmap', 'hairnormalmap')
EMISSIVE = ('bloommaskmap', 'eyeemissivemap')
DECLS = 'generated/decls/material2/'


class Material:
    """A material decl: its texture paths by parm, the templates it inherits from and whether it cuts out with alpha."""

    def __init__(self, name, textures, templates, text):
        self.name, self.textures, self.templates = name, textures, templates
        self.alpha = 'alphatest' in text or any('hair' in t for t in templates)
        self.overlay = any(word in name for word in ('eye_occ', 'eyes_occ', 'eyeocc', 'eyewet'))


def read_material(read_decl, name):
    """The material decl and the decls it inherits from; a missing decl gives a material without textures."""
    textures, templates, texts, current = {}, [], [], name
    for _ in range(8):
        text = read_decl(f'{DECLS}{current}.decl')
        if text is None:
            break
        text = text.lower()
        texts.append(text)
        for parm, path in TEXTURE.findall(text):
            textures.setdefault(parm, path)  # the inheriting decl wins over its template
        parent = INHERIT.search(text)
        if not parent:
            break
        current = parent[1]
        templates.append(current)
    return Material(name, textures, templates, '\n'.join(texts))


def slot(material, names):
    """The first real texture path of these parms; constant colours from textures/system are left out."""
    found = material.textures
    return next((found[n] for n in names if found.get(n) and found[n] != '_default'
                 and not found[n].startswith('textures/system/')), None)


def image_name(images, path, kind):
    """The image resource of a texture path: names add options such as $streamed$mtlkind=albedo."""
    candidates = images.get(path if '.' in path.rsplit('/', 1)[-1] else path + '.tga', [])
    return next((c for c in candidates if f'mtlkind={kind}' in c), candidates[0] if candidates else None)


# Images

FORMATS = {  # id Tech texture format: (DXGI format, block size in bytes or 0 for pixels, bytes per pixel)
    3: (28, 0, 4), 32: (29, 0, 4), 5: (61, 0, 1), 7: (49, 0, 2), 10: (71, 8, 0), 33: (72, 8, 0), 54: (71, 8, 0),
    11: (77, 16, 0), 34: (78, 16, 0), 24: (80, 8, 0), 25: (83, 16, 0), 22: (95, 16, 0), 23: (98, 16, 0), 35: (99, 16, 0)}
BC4, BC5 = 24, 25
RGBA8 = 3
# Larger images are read at the first mip level that fits: 4096 x 4096 textures would quadruple the
# scene's memory for no visible gain in an animation preview.
MAX_SIZE = 2048


class Image:
    __slots__ = ('kind', 'format', 'width', 'height', 'data')


def read_image(data, stream, key, max_size=MAX_SIZE):
    """The largest mip level of a 2D image, up to max_size, that is in the game's files.

    stream(key, size) reads the mip levels kept in the .streamdb files."""
    reader = Reader(data)
    if reader.take(3) != b'BIM':
        raise ValueError('Not a DOOM Eternal image.')
    reader.take(1)
    texture_type, kind, width, height, _, mip_count, _ = struct.unpack('<7i', reader.take(28))
    reader.take(8 + 1)  # albedo and specular bias and scale, environment
    texture_format = reader.int()
    reader.take(4 + 4 + 2 + 4)  # always 7, padding, atlas padding, flags
    streamed = reader.int() & 0x0F
    if texture_type != 0:
        raise ValueError('Only 2D images are converted.')
    mips = [struct.unpack('<9i', reader.take(36)) for _ in range(mip_count)]
    inline = {}
    for level in range(streamed, mip_count):
        inline[level] = reader.take(mips[level][5])
    fitting = [level for level in range(mip_count) if max(mips[level][2:4]) <= max_size]
    for level in fitting + [level for level in range(mip_count) if level not in fitting]:
        mip_level, _, mip_width, mip_height, _, size, _, _, _ = mips[level]
        pixels = inline.get(level)
        if pixels is None:
            pixels = stream((key << 4 | (mip_count - mip_level)) & MASK64, size)
        if pixels and len(pixels) == size:
            image = Image()
            image.kind, image.format, image.width, image.height, image.data = kind, texture_format, mip_width, mip_height, pixels
            return image
    raise ValueError('None of the image\'s mip levels is in the game\'s files.')


def decode_bc4(blocks):
    """(n, 8) BC4 blocks to (n, 16) values, texels in row order within each block."""
    a, b = blocks[:, 0].astype(np.int32), blocks[:, 1].astype(np.int32)
    bits = np.zeros(len(blocks), np.uint64)
    for byte in range(6):
        bits |= blocks[:, 2 + byte].astype(np.uint64) << np.uint64(8 * byte)
    index = (bits[:, None] >> (np.arange(16, dtype=np.uint64) * np.uint64(3)) & np.uint64(7)).astype(np.int64)
    palette = np.empty((len(blocks), 8), np.int32)
    palette[:, 0], palette[:, 1] = a, b
    six = a > b
    for step in range(1, 7):
        palette[:, step + 1] = ((7 - step) * a + step * b + 3) // 7
    for step in range(1, 5):
        palette[~six, step + 1] = ((5 - step) * a[~six] + step * b[~six] + 2) // 5
    palette[~six, 6], palette[~six, 7] = 0, 255
    return np.take_along_axis(palette, index, 1).astype(np.uint8)


def unblock(values, width, height):
    """(blocks, 16) texels to a (height, width) image."""
    across, down = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    return values.reshape(down, across, 4, 4).transpose(0, 2, 1, 3).reshape(down * 4, across * 4)[:height, :width]


def to_rgba(image):
    """BC4 and BC5 images as plain RGBA, which texconv writes to PNG. A BC5 normal map gets its Z rebuilt in blue."""
    if image.format not in (BC4, BC5):
        return image
    size = 8 if image.format == BC4 else 16
    blocks = np.frombuffer(image.data, np.uint8).reshape(-1, size)
    red = unblock(decode_bc4(blocks[:, :8]), image.width, image.height)
    rgba = np.full((image.height, image.width, 4), 255, np.uint8)
    if image.format == BC4:
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = red
    else:
        green = unblock(decode_bc4(blocks[:, 8:]), image.width, image.height)
        x, y = red / 127.5 - 1.0, green / 127.5 - 1.0
        z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = red, green, np.round((z + 1.0) * 127.5).astype(np.uint8)
    result = Image()
    result.kind, result.format, result.width, result.height, result.data = image.kind, RGBA8, image.width, image.height, rgba.tobytes()
    return result


def dds(image):
    """A DDS file with a DX10 header holding one mip level, for texconv."""
    image = to_rgba(image)
    if image.format not in FORMATS:
        raise ValueError(f'Image format {image.format} is not converted.')
    dxgi, block, pixel = FORMATS[image.format]
    blocks = max(1, (image.width + 3) // 4) * max(1, (image.height + 3) // 4)
    pitch = blocks * block if block else image.width * pixel  # linear size for block formats, row pitch otherwise
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x80000 if block else 0x8)
    header = struct.pack('<4s7I44x', b'DDS ', 124, flags, image.height, image.width, pitch, 0, 1)
    pixel_format = struct.pack('<2I4s5I', 32, 0x4, b'DX10', 0, 0, 0, 0, 0)
    caps = struct.pack('<5I', 0x1000, 0, 0, 0, 0)
    dx10 = struct.pack('<5I', dxgi, 3, 0, 1, 0)
    return header + pixel_format + caps + dx10 + bytes(image.data)
