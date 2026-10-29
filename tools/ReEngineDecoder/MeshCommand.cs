#nullable enable
using System.Numerics;
using ReeLib;
using ReeLib.Mesh;

namespace ReEngineDecoder;

/// <summary>
/// Writes the first level of detail of a mesh as typed arrays: a JSON description plus a little-endian binary
/// file with the vertex and face data. Positions and normals stay in the mesh's own space; faces keep the
/// mesh's winding.
/// </summary>
internal static class MeshCommand
{
    private const int Influences = 4;

    private sealed class ArrayWriter(BinaryWriter writer)
    {
        public readonly Dictionary<string, object> Arrays = new();

        public void Floats(string name, int rows, int columns, IEnumerable<float> values) =>
            Add(name, "f4", rows, columns, () => { foreach (var value in values) writer.Write(Program.Finite(value)); });

        public void Ints(string name, int rows, int columns, IEnumerable<int> values) =>
            Add(name, "i4", rows, columns, () => { foreach (var value in values) writer.Write(value); });

        private void Add(string name, string dtype, int rows, int columns, Action write)
        {
            writer.Flush();
            var offset = writer.BaseStream.Position;
            write();
            writer.Flush();
            var length = writer.BaseStream.Position - offset;
            var expected = (long)rows * columns * 4;
            if (length != expected)
                throw new InvalidOperationException($"Array {name} has {length} bytes instead of {expected}.");
            Arrays[name] = new { dtype, shape = columns == 1 ? new[] { rows } : new[] { rows, columns }, offset, length };
        }
    }

    public static int Export(string inputPath, string outputStem)
    {
        using var handler = Program.OpenRead(inputPath);
        var mesh = new MeshFile(handler);
        mesh.Read();
        if (mesh.StreamingBuffers?.Count > 0)
            throw new NotSupportedException("Streaming meshes are not supported yet.");
        var lods = mesh.MeshData?.LODs ?? throw new InvalidDataException("The mesh has no geometry.");
        if (lods.Count == 0) throw new InvalidDataException("The mesh has no levels of detail.");
        var lod = lods[0];

        // Bones in parent-first order; vertex weights point into the mesh's deform-bone table.
        var fileBones = mesh.BoneData == null ? new List<RestBone>() : Skeletons.FromMesh(mesh);
        var bones = Skeletons.ParentFirst(fileBones, out var newIndex);
        var deformToBone = mesh.BoneData?.DeformBones.Select(bone => newIndex[bone.index]).ToArray() ?? [];
        var restCheck = mesh.BoneData == null ? 0f : RestPoseError(mesh.BoneData);

        var positions = new List<Vector3>();
        var normals = new List<Vector3>();
        var uv0 = new List<Vector2>();
        var uv1 = new List<Vector2>();
        var boneIndices = new List<int>();
        var boneWeights = new List<float>();
        var vertexMaterials = new List<int>();
        var faces = new List<int>();
        var faceMaterials = new List<int>();
        var submeshes = new List<object>();
        var hasUv1 = lod.MeshGroups.SelectMany(group => group.Submeshes).Any(sub => sub.Buffer.UV1.Length > 0);
        var badWeights = 0;
        var absoluteFaces = 0;
        Span<int> indices = stackalloc int[Influences];
        Span<float> weights = stackalloc float[Influences];

        foreach (var group in lod.MeshGroups)
        {
            foreach (var sub in group.Submeshes)
            {
                var buffer = sub.Buffer;
                var vertexStart = positions.Count;
                var faceStart = faceMaterials.Count;
                for (var vertex = 0; vertex < sub.vertCount; vertex++)
                {
                    var source = sub.vertsIndexOffset + vertex;
                    positions.Add(buffer.Positions[source]);
                    var normal = source < buffer.NormalsTangents.Length ? buffer.NormalsTangents[source].Normal : Vector3.Zero;
                    normals.Add(normal.LengthSquared() > 0 ? Vector3.Normalize(normal) : normal);
                    uv0.Add(source < buffer.UV0.Length ? buffer.UV0[source].AsVector2 : Vector2.Zero);
                    if (hasUv1) uv1.Add(source < buffer.UV1.Length ? buffer.UV1[source].AsVector2 : Vector2.Zero);
                    indices.Clear();
                    weights.Clear();
                    if (source < buffer.Weights.Length && !TopInfluences(buffer.Weights[source], deformToBone, indices, weights))
                        badWeights++;
                    foreach (var value in indices) boneIndices.Add(value);
                    foreach (var value in weights) boneWeights.Add(value);
                    vertexMaterials.Add(sub.materialIndex);
                }

                var corners = ReadIndices(mesh, sub);
                // Face indices count from the submesh's first vertex; accept buffer-wide indices too.
                var offset = 0;
                if (sub.vertsIndexOffset > 0 && corners.Length > 0 && corners.Min() >= sub.vertsIndexOffset && corners.Max() < sub.vertsIndexOffset + sub.vertCount)
                {
                    offset = sub.vertsIndexOffset;
                    absoluteFaces++;
                }
                for (var corner = 0; corner + 2 < corners.Length; corner += 3)
                {
                    for (var k = 0; k < 3; k++)
                    {
                        var local = corners[corner + k] - offset;
                        if (local < 0 || local >= sub.vertCount)
                            throw new InvalidDataException($"Submesh {submeshes.Count} has a face index {corners[corner + k]} outside its {sub.vertCount} vertices.");
                        faces.Add(vertexStart + local);
                    }
                    faceMaterials.Add(sub.materialIndex);
                }
                submeshes.Add(new
                {
                    material = (int)sub.materialIndex,
                    materialName = sub.materialIndex < mesh.MaterialNames.Count ? mesh.MaterialNames[sub.materialIndex] : "",
                    group = (int)group.groupId,
                    vertexStart,
                    vertexCount = sub.vertCount,
                    faceStart,
                    faceCount = faceMaterials.Count - faceStart,
                });
            }
        }

        var stemPath = Path.GetFullPath(outputStem);
        var binPath = stemPath + ".bin";
        object arrays;
        using (var stream = Program.CreateOutput(binPath))
        using (var writer = new BinaryWriter(stream))
        {
            var output = new ArrayWriter(writer);
            var n = positions.Count;
            output.Floats("positions", n, 3, positions.SelectMany(Program.Array3));
            output.Floats("normals", n, 3, normals.SelectMany(Program.Array3));
            output.Floats("uv_0", n, 2, uv0.SelectMany(uv => new[] { uv.X, uv.Y }));
            if (hasUv1) output.Floats("uv_1", n, 2, uv1.SelectMany(uv => new[] { uv.X, uv.Y }));
            output.Ints("bone_indices", n, Influences, boneIndices);
            output.Floats("bone_weights", n, Influences, boneWeights);
            output.Ints("faces", faceMaterials.Count, 3, faces);
            output.Ints("face_materials", faceMaterials.Count, 1, faceMaterials);
            output.Ints("vertex_materials", n, 1, vertexMaterials);
            arrays = output.Arrays;
        }

        var symmetry = mesh.BoneData?.Bones.ToDictionary(bone => newIndex[bone.index],
            bone => bone.symmetryIndex >= 0 && bone.symmetryIndex < newIndex.Length ? newIndex[bone.symmetryIndex] : -1) ?? new();
        var deformIndex = mesh.BoneData?.Bones.ToDictionary(bone => newIndex[bone.index], bone => bone.remapIndex) ?? new();
        Program.WriteJson(stemPath + ".json", new
        {
            format = "re-engine-mesh",
            formatVersion = 1,
            source = new { engine = "re_engine", container = "mesh", version = Program.FileVersion(inputPath), internalVersion = mesh.Header.version, file = Path.GetFullPath(inputPath) },
            basis = Program.Basis,
            unitScale = 1.0,
            lod = 0,
            lodCount = lods.Count,
            bin = Path.GetFileName(binPath),
            vertexCount = positions.Count,
            faceCount = faceMaterials.Count,
            bones = bones.Select((bone, index) => new
            {
                index,
                name = bone.Name,
                parent = bone.Parent,
                translation = Program.Array3(bone.Translation),
                rotation = Program.Array4(bone.Rotation),
                scale = Program.Array3(bone.Scale),
                deformIndex = deformIndex.GetValueOrDefault(index, -1),
                symmetry = symmetry.GetValueOrDefault(index, -1),
            }).ToArray(),
            materials = mesh.MaterialNames.ToArray(),
            submeshes,
            arrays,
        });

        var extent = positions.Count == 0 ? (Vector3.Zero, Vector3.Zero) : (
            positions.Aggregate(new Vector3(float.MaxValue), Vector3.Min), positions.Aggregate(new Vector3(float.MinValue), Vector3.Max));
        Console.WriteLine($"Mesh {Path.GetFileName(inputPath)}: vertices={positions.Count}, faces={faceMaterials.Count}, submeshes={submeshes.Count}, bones={bones.Count}, deform={deformToBone.Length}, materials={mesh.MaterialNames.Count}, lods={lods.Count}");
        Console.WriteLine($"Bounds min=({extent.Item1.X:0.###}, {extent.Item1.Y:0.###}, {extent.Item1.Z:0.###}) max=({extent.Item2.X:0.###}, {extent.Item2.Y:0.###}, {extent.Item2.Z:0.###}); rest pose error={restCheck:0.######}; buffer-wide face indices in {absoluteFaces} submeshes");
        if (badWeights > 0) Console.WriteLine($"NOTE {badWeights} vertices have weights for bones outside the deform table or no weight at all");
        Program.PrintLibraryWarnings();
        Console.WriteLine(stemPath + ".json");
        return 0;
    }

    private static int[] ReadIndices(MeshFile mesh, Submesh sub)
    {
        if (sub.Buffer.IntegerFaces != null) return sub.IntegerIndices.ToArray();
        if (sub.Buffer.Faces != null)
        {
            var span = sub.Indices;
            var result = new int[span.Length];
            for (var i = 0; i < span.Length; i++) result[i] = span[i];
            return result;
        }
        return [];
    }

    /// <summary>Keeps the four strongest influences, mapped from the deform table to skeleton bones, and normalizes them.</summary>
    private static bool TopInfluences(VertexBoneWeights source, int[] deformToBone, Span<int> indices, Span<float> weights)
    {
        var combined = new Dictionary<int, float>();
        var valid = true;
        for (var k = 0; k < source.IndexCount && k < source.boneWeights.Length; k++)
        {
            var weight = source.GetWeight(k);
            if (weight <= 0) continue;
            var deform = source.GetIndex(k);
            if (deform >= deformToBone.Length)
            {
                valid = false;
                continue;
            }
            var bone = deformToBone[deform];
            combined[bone] = combined.GetValueOrDefault(bone) + weight;
        }
        var strongest = combined.OrderByDescending(pair => pair.Value).ThenBy(pair => pair.Key).Take(Influences).ToArray();
        var sum = strongest.Sum(pair => pair.Value);
        if (sum <= 0) return false;
        for (var k = 0; k < strongest.Length; k++)
        {
            indices[k] = strongest[k].Key;
            weights[k] = strongest[k].Value / sum;
        }
        return valid;
    }

    /// <summary>How far each bone's stored world matrix is from its local matrix times its parent's world matrix.</summary>
    private static float RestPoseError(MeshBoneHierarchy data)
    {
        var error = 0f;
        foreach (var bone in data.Bones)
        {
            var local = Skeletons.ToMatrix(bone.localTransform);
            var expected = bone.parentIndex >= 0 ? local * Skeletons.ToMatrix(data.Bones[bone.parentIndex].globalTransform) : local;
            var actual = Skeletons.ToMatrix(bone.globalTransform);
            error = MathF.Max(error, MathF.Abs(expected.M41 - actual.M41) + MathF.Abs(expected.M42 - actual.M42) + MathF.Abs(expected.M43 - actual.M43));
        }
        return error;
    }
}
