"""Extract all FLVER vertex streams and skin data without importing Soulstruct in Blender."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from soulstruct.flver import FLVER


def vertex_field(mesh, name):
    for stream in mesh.vertex_arrays:
        if name in stream.array.dtype.names:
            return np.asarray(stream.array[name])
    return None


def influences(mesh, bone_count, count):
    weights = vertex_field(mesh, "bone_weights")
    indices = vertex_field(mesh, "bone_indices")
    if weights is None:
        weights = np.zeros((count, 4), dtype=np.float32)
        weights[:, 0] = 1
    else:
        weights = np.maximum(np.asarray(weights, dtype=np.float32).reshape(count, -1), 0)
    if indices is None:
        indices = vertex_field(mesh, "normal_w")
        if indices is None:
            indices = np.full((count, 1), mesh.default_bone_index, dtype=np.int32)
        else:
            indices = np.asarray(indices).reshape(count, -1)[:, :1]
    indices = np.asarray(indices, dtype=np.int32).reshape(count, -1)
    weights = np.pad(weights[:, :4], ((0, 0), (0, max(0, 4 - weights.shape[1]))))
    indices = np.pad(indices[:, :4], ((0, 0), (0, max(0, 4 - indices.shape[1]))))
    zero = weights.sum(axis=1) <= 1e-8
    weights[zero, 0] = 1
    active = weights > 1e-8
    indices[~active] = 0
    if mesh.bone_indices is not None:
        table = np.asarray(mesh.bone_indices, dtype=np.int32)
        if np.any((indices[active] < 0) | (indices[active] >= len(table))):
            raise ValueError("A weighted vertex refers outside its mesh bone table.")
        indices = table[indices]
    if np.any((indices[active] < 0) | (indices[active] >= bone_count)):
        raise ValueError("A weighted vertex refers outside the FLVER skeleton.")
    indices[~active] = 0
    return indices, weights / weights.sum(axis=1, keepdims=True)


def extract_model(flver, output_path: Path, label="FLVER"):
    if not flver.bones or not flver.meshes:
        raise ValueError(f"{label} has no visible skinned geometry. Player c0000.flver is a skeleton reference; select outfit PARTSBND files instead.")
    positions, weights, indices, faces, face_materials = [], [], [], [], []
    uv_fields = sorted({name for mesh in flver.meshes for va in mesh.vertex_arrays
                        for name in va.array.dtype.names if name.startswith("uv_")}, key=lambda s: int(s[3:])) or ["uv_0"]
    uv_layers = {field: [] for field in uv_fields}
    normals = []
    offset = 0
    for mesh_index, mesh in enumerate(flver.meshes):
        pos = vertex_field(mesh, "position")
        if pos is None:
            raise ValueError(f"{label} mesh {mesh_index} has no position stream.")
        count = len(pos)
        if any(len(va) != count for va in mesh.vertex_arrays):
            raise ValueError(f"{label} mesh {mesh_index} has mismatched vertex stream lengths.")
        ix, w = influences(mesh, len(flver.bones), count)
        tri = mesh.triangulate_flver0() if flver.version.is_flver0() else mesh.triangulate_flver2()
        tri = np.asarray(tri, dtype=np.int32).reshape(-1, 3)
        if np.any((tri < 0) | (tri >= count)):
            raise ValueError(f"{label} mesh {mesh_index} has invalid triangle indices.")
        tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
        positions.append(np.asarray(pos[:, :3], dtype=np.float32))
        indices.append(ix); weights.append(w)
        n = vertex_field(mesh, "normal")
        normals.append(np.asarray(n[:, :3], dtype=np.float32) if n is not None else np.zeros((count, 3), np.float32))
        faces.append(tri + offset)
        face_materials.append(np.full(len(tri), mesh_index, dtype=np.int32))
        for field in uv_fields:
            uv = vertex_field(mesh, field)
            uv_layers[field].append(np.asarray(uv[:, :2], dtype=np.float32) if uv is not None else np.zeros((count, 2), np.float32))
        offset += count
    output_path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {key: np.concatenate(value) for key, value in uv_layers.items()}
    np.savez_compressed(output_path, positions=np.concatenate(positions), bone_indices=np.concatenate(indices),
        bone_weights=np.concatenate(weights), faces=np.concatenate(faces), face_materials=np.concatenate(face_materials),
        normals=np.concatenate(normals), uvs=arrays[uv_fields[0]],
        bone_names=np.asarray([b.name for b in flver.bones], dtype="U"),
        bone_parents=np.asarray([b.parent_bone_index for b in flver.bones], dtype=np.int32),
        bone_translations=np.asarray([list(b.translate) for b in flver.bones], dtype=np.float32),
        bone_rotations=np.asarray([list(b.rotate) for b in flver.bones], dtype=np.float32),
        bone_scales=np.asarray([list(b.scale) for b in flver.bones], dtype=np.float32),
        material_names=np.asarray([m.material.name or f"Material {i}" for i, m in enumerate(flver.meshes)], dtype="U"),
        **arrays)
    summary = dict(vertices=offset, triangles=sum(len(f) for f in faces), bones=len(flver.bones),
                   materials=len(flver.meshes), uv_layers=len(uv_fields))
    print(f"Prepared {label}: {summary['vertices']:,} vertices, {summary['triangles']:,} triangles, {summary['uv_layers']} UV layers", flush=True)
    return summary


def extract_flver(flver_path, output_path):
    return extract_model(FLVER.from_path(flver_path), Path(output_path), Path(flver_path).name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flver", type=Path); parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract_flver(args.flver, args.output)
