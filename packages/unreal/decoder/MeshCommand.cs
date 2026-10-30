#nullable enable
using System.Text.RegularExpressions;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Material;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse_Conversion.Dto;
using CUE4Parse_Conversion.Options;
using CUE4Parse_Conversion.Textures;

namespace UnrealDecoder;

/// <summary>
/// Exports skeletal meshes for the bridge: the first level of detail as typed arrays in a .bin with a .json that
/// describes them, the reference skeleton, and each material slot with its base color, normal, mask and emissive
/// textures as PNG images. The meshes of one character share one mount and one texture folder.
/// </summary>
internal static class MeshCommand
{
    private const int Influences = 4;

    /// <summary>Textures are decoded at this size at most, which keeps a character's images to a few hundred megabytes.</summary>
    private const int MaxTextureSize = 2048;

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

    public static int Export(string optionsPath, string outputDirectory, string[] meshPaths)
    {
        var options = Source.Read(optionsPath);
        using var provider = Source.Open(options);
        var output = Path.GetFullPath(outputDirectory);
        var textures = new TextureFolder(Path.Combine(output, "textures"), provider.ProjectName);
        Directory.CreateDirectory(textures.Directory);
        var results = new List<object>();
        var exported = 0;
        for (var index = 0; index < meshPaths.Length; index++)
        {
            var objectPath = Source.ObjectPath(meshPaths[index]);
            try
            {
                var stem = Path.Combine(output, $"{index:00}_{SafeName(objectPath[(objectPath.LastIndexOf('.') + 1)..])}");
                ExportMesh(provider, objectPath, stem, options, textures);
                results.Add(new { path = objectPath, json = stem + ".json", error = "" });
                exported++;
            }
            catch (Exception ex)
            {
                var message = Program.OneLine(ex.InnerException is { } inner ? $"{ex.Message} ({inner.Message})" : ex.Message);
                Console.WriteLine($"NOTE {objectPath} could not be exported: {message}");
                results.Add(new { path = objectPath, json = "", error = message });
            }
        }
        var listing = Path.Combine(output, "meshes.json");
        Program.WriteJson(listing, new { format = "unreal-meshes", formatVersion = 1, meshes = results, textures = textures.Written });
        if (exported == 0)
            throw new InvalidDataException("None of the skeletal meshes could be exported.");
        Console.WriteLine($"Exported {exported} of {meshPaths.Length} skeletal meshes and {textures.Written.Count} textures");
        Program.PrintLibraryWarnings();
        Console.WriteLine(listing);
        return 0;
    }

    private static void ExportMesh(IFileProvider provider, string objectPath, string stem, SourceOptions options, TextureFolder textures)
    {
        var mesh = provider.LoadPackageObject<USkeletalMesh>(objectPath);
        using var dto = new SkeletalMeshDto(mesh, EMeshQuality.Highest);
        var lod = dto.LODs.FirstOrDefault() ?? throw new InvalidDataException("The mesh has no level of detail CUE4Parse can read.");
        var bones = Bones.Read(mesh.ReferenceSkeleton);
        var vertices = lod.Vertices;
        var count = vertices.Length;

        // The four strongest influences of each vertex, normalized; a vertex without any follows the root.
        var boneIndices = new int[count * Influences];
        var boneWeights = new float[count * Influences];
        var badWeights = 0;
        for (var vertex = 0; vertex < count; vertex++)
        {
            var strongest = vertices[vertex].Influences
                .Where(influence => influence.Weight > 0)
                .GroupBy(influence => (int)influence.Bone)
                .Select(group => (bone: group.Key, weight: group.Sum(influence => influence.Weight)))
                .OrderByDescending(pair => pair.weight).ThenBy(pair => pair.bone)
                .Take(Influences).ToArray();
            var sum = strongest.Sum(pair => pair.weight);
            if (sum <= 0 || strongest.Any(pair => pair.bone >= bones.Count))
            {
                badWeights++;
                boneWeights[vertex * Influences] = 1;
                continue;
            }
            for (var k = 0; k < strongest.Length; k++)
            {
                boneIndices[vertex * Influences + k] = strongest[k].bone;
                boneWeights[vertex * Influences + k] = strongest[k].weight / sum;
            }
        }

        // Triangles of every section, in the source's winding, with the material slot they use.
        var faces = new List<int>();
        var faceMaterials = new List<int>();
        var vertexMaterials = new int[count];
        foreach (var section in lod.Sections.Where(section => section.IsValid))
        {
            for (var face = 0; face < section.NumFaces; face++)
            {
                var first = section.FirstIndex + face * 3;
                if (first + 2 >= lod.Indices.Length) break;
                for (var corner = 0; corner < 3; corner++)
                {
                    var vertex = (int)lod.Indices[first + corner];
                    faces.Add(vertex);
                    if (vertex < count) vertexMaterials[vertex] = section.MaterialIndex;
                }
                faceMaterials.Add(section.MaterialIndex);
            }
        }

        var binPath = stem + ".bin";
        Dictionary<string, object> arrays;
        using (var stream = Program.CreateOutput(binPath))
        using (var writer = new BinaryWriter(stream))
        {
            var arrayWriter = new ArrayWriter(writer);
            arrayWriter.Floats("positions", count, 3, vertices.SelectMany(v => new[] { v.Position.X, v.Position.Y, v.Position.Z }));
            arrayWriter.Floats("normals", count, 3, vertices.SelectMany(v => new[] { v.Normal.X, v.Normal.Y, v.Normal.Z }));
            arrayWriter.Floats("uv_0", count, 2, vertices.SelectMany(v => new[] { v.Uv.U, v.Uv.V }));
            for (var set = 0; set < lod.ExtraUvs.Length; set++)
                arrayWriter.Floats($"uv_{set + 1}", count, 2, lod.ExtraUvs[set].Take(count).SelectMany(uv => new[] { uv.U, uv.V }));
            arrayWriter.Ints("bone_indices", count, Influences, boneIndices);
            arrayWriter.Floats("bone_weights", count, Influences, boneWeights);
            arrayWriter.Ints("faces", faceMaterials.Count, 3, faces);
            arrayWriter.Ints("face_materials", faceMaterials.Count, 1, faceMaterials);
            arrayWriter.Ints("vertex_materials", count, 1, vertexMaterials);
            arrays = arrayWriter.Arrays;
        }

        var materials = dto.Materials.Select(slot => Material(slot, textures)).ToArray();
        Program.WriteJson(stem + ".json", new
        {
            format = "unreal-mesh",
            formatVersion = 1,
            source = new { engine = "unreal", container = "package", version = options.Engine, member = objectPath },
            basis = Program.Basis,
            unitScale = Program.UnitScale,
            name = mesh.Name,
            skeleton = dto.SkeletonPathName ?? "",
            lod = lod.SourceLodIndex,
            lodCount = mesh.LODModels?.Length ?? 0,
            nanite = lod.IsNanite,
            bin = Path.GetFileName(binPath),
            vertexCount = count,
            faceCount = faceMaterials.Count,
            bones = bones.Select((bone, index) => new
            {
                index,
                name = bone.Name,
                parent = bone.Parent,
                translation = Program.Array3(bone.Rest.Translation),
                rotation = Program.Array4(bone.Rest.Rotation),
                scale = Program.Array3(bone.Rest.Scale3D),
            }).ToArray(),
            materials,
            arrays,
        });

        Console.WriteLine($"Mesh {mesh.Name}: vertices={count}, faces={faceMaterials.Count}, sections={lod.Sections.Length}, bones={bones.Count}, " +
                          $"materials={materials.Length}, uv sets={1 + lod.ExtraUvs.Length}, lod={lod.SourceLodIndex}");
        if (badWeights > 0)
            Console.WriteLine($"NOTE {mesh.Name}: {badWeights} vertices have no weight or weights for bones the mesh does not have; they follow the root");
        Console.WriteLine(stem + ".json");
    }

    /// <summary>A material slot with the textures and color the bridge can show.</summary>
    private static object Material(MeshMaterialDto slot, TextureFolder textures)
    {
        UMaterialInterface? material = null;
        if (slot.Material != null && slot.Material.TryLoad<UMaterialInterface>(out var loaded))
            material = loaded;
        if (material == null)
            return new { slot = slot.SlotName, name = slot.SlotName, path = "", blendMode = "", albedo = (object?)null, normal = (object?)null,
                         mask = (object?)null, emissive = (object?)null, color = (float[]?)null };

        var parameters = new CMaterialParams2();
        material.GetParams(parameters, EMaterialDepth.AllLayers);
        // Materials that tint by parameters instead of a texture, as many games' creatures do, keep their base color tint.
        float[]? color = null;
        if (parameters.TryGetLinearColor(out var linear, CMaterialParams2.DiffuseColors[0]))
            color = [linear.R, linear.G, linear.B, linear.A];
        else if (parameters.Colors.Where(pair => BaseTint.IsMatch(pair.Key)).OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
                     .FirstOrDefault() is { Key: not null } tint)
            color = [tint.Value.R, tint.Value.G, tint.Value.B, tint.Value.A];
        // Textures come by their parameter names first. CUE4Parse also takes a parameter called just Texture for the base
        // color, and otherwise files a texture under a fallback name: one whose own name looks like a base color, normal
        // map and so on, or a material's only texture, which is often a mask or pattern. Such a guess gives way to a tint
        // when the texture's own name does not look like a base color. The engine's own textures, such as DefaultDiffuse
        // or its noise examples, stand in for a texture the material does not have.
        object? Texture(string[][] names, string fallback, string? guessed = null)
        {
            foreach (var name in names[0].Append(fallback))
            {
                if (!parameters.TryGetTexture2d(out var texture, name) || textures.PathOf(texture).StartsWith("/Engine/", StringComparison.OrdinalIgnoreCase))
                    continue;
                if (guessed != null && (name == fallback || name == "Texture") && !Regex.IsMatch(texture.Name, guessed, RegexOptions.IgnoreCase))
                    continue;
                var file = textures.Write(texture);
                return file == null ? null : new { texture = textures.PathOf(texture), file, srgb = texture.SRGB, normalMap = texture.IsNormalMap };
            }
            return null;
        }
        return new
        {
            slot = slot.SlotName,
            name = material.Name,
            path = SourceCommands.Normalize(material.GetPathName(), textures.Project),
            blendMode = parameters.BlendMode.ToString(),
            albedo = Texture(CMaterialParams2.Diffuse, CMaterialParams2.FallbackDiffuse, color == null ? null : CMaterialParams2.RegexDiffuse),
            normal = Texture(CMaterialParams2.Normals, CMaterialParams2.FallbackNormals),
            mask = Texture(CMaterialParams2.SpecularMasks, CMaterialParams2.FallbackSpecularMasks),
            emissive = Texture(CMaterialParams2.Emissive, CMaterialParams2.FallbackEmissive),
            color,
        };
    }

    private static string SafeName(string name) => Regex.Replace(name, @"[^A-Za-z0-9_.-]", "_");

    private static readonly Regex BaseTint = new(@"base ?colou?r|albedo|diffuse", RegexOptions.IgnoreCase);

    /// <summary>The PNG images of one export, each texture once, named after the texture.</summary>
    private sealed class TextureFolder(string directory, string project)
    {
        public readonly string Directory = directory;
        public readonly string Project = project;
        public readonly Dictionary<string, string> Written = new(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _failed = new(StringComparer.OrdinalIgnoreCase);

        public string PathOf(UTexture texture) => SourceCommands.Normalize(texture.GetPathName(), Project);

        public string? Write(UTexture texture)
        {
            var path = PathOf(texture);
            if (Written.TryGetValue(path, out var file)) return file;
            if (_failed.Contains(path)) return null;
            try
            {
                var decoded = texture.Decode(MaxTextureSize) ?? throw new InvalidDataException("CUE4Parse cannot decode its pixel format");
                var bytes = decoded.Encode(ETextureFormat.Png, false, out _);
                var stem = SafeName(texture.Name);
                file = Path.Combine(Directory, stem + ".png");
                for (var copy = 2; Written.Values.Contains(file, StringComparer.OrdinalIgnoreCase); copy++)
                    file = Path.Combine(Directory, $"{stem}_{copy}.png");
                File.WriteAllBytes(file, bytes);
                Written[path] = file;
                return file;
            }
            catch (Exception ex)
            {
                _failed.Add(path);
                Console.WriteLine($"NOTE Texture {texture.Name} could not be decoded: {Program.OneLine(ex.Message)}");
                return null;
            }
        }
    }
}
