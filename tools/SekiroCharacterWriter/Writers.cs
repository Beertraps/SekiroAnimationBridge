#nullable enable
using System.Numerics;
using System.Text.Json.Nodes;
using SoulsFormats;

// A model from the template's FLVER: its header, buffer layout and GX lists, with new nodes, meshes, materials and
// dummy polys. The bridge sends world-space bind transforms; this tool works out local transforms, flags and the
// bounding boxes in the same matrix order as SoulsFormats.
static class FlverWriter
{
    const int VertexFloats = 22, VertexInts = 4;

    public static object Run(JsonObject job)
    {
        var template = FLVER2.Read(File.ReadAllBytes(Json.Text(job, "template")));
        var flver = new FLVER2 { Header = template.Header, GXLists = template.GXLists };

        // A single-buffer layout with position, bone indices and weights, and the fewest members.
        int layoutIndex = Enumerable.Range(0, template.BufferLayouts.Count)
            .Where(i => template.BufferLayouts[i].Any(m => m.Semantic == FLVER.LayoutSemantic.Position) &&
                        template.BufferLayouts[i].Any(m => m.Semantic == FLVER.LayoutSemantic.BoneWeights) &&
                        template.BufferLayouts[i].Any(m => m.Semantic == FLVER.LayoutSemantic.UV) &&
                        !template.BufferLayouts[i].Any(m => m.Semantic == FLVER.LayoutSemantic.Bitangent))
            .OrderBy(i => template.BufferLayouts[i].Count).First();
        var layout = template.BufferLayouts[layoutIndex];
        flver.BufferLayouts.Add(layout);
        int uvCount = layout.Where(m => m.Semantic == FLVER.LayoutSemantic.UV)
            .Sum(m => m.Type is FLVER.LayoutType.Short4 or FLVER.LayoutType.Float4 ? 2 : 1);
        int colorCount = layout.Count(m => m.Semantic == FLVER.LayoutSemantic.VertexColor);
        int tangentCount = layout.Count(m => m.Semantic == FLVER.LayoutSemantic.Tangent);
        var color = CommonColor(template);

        // Nodes. A node either copies a template node's local transform by name, or gives its world transform.
        var templateByName = template.Nodes.Select((n, i) => (n, i)).GroupBy(x => x.n.Name).ToDictionary(g => g.Key, g => g.First().i);
        var nodes = job["nodes"]!.AsArray();
        var worlds = new Matrix4x4[nodes.Count];
        var kinds = new string[nodes.Count];
        double worstNode = 0;
        for (int i = 0; i < nodes.Count; i++)
        {
            var spec = nodes[i]!.AsObject();
            int parent = spec["parent"]!.GetValue<int>();
            if (parent >= i) throw new ArgumentException($"Node {i} comes before its parent {parent}.");
            var parentWorld = parent >= 0 ? worlds[parent] : Matrix4x4.Identity;
            var node = new FLVER.Node { Name = Json.Text(spec, "name"), ParentIndex = (short)parent };
            kinds[i] = Json.OptionalText(spec, "kind") ?? "bone";
            if (Json.OptionalText(spec, "copy") is { } copy)
            {
                var source = template.Nodes[templateByName.TryGetValue(copy, out var at) ? at : throw new ArgumentException($"The template has no node {copy}.")];
                (node.Translation, node.Rotation, node.Scale) = (source.Translation, source.Rotation, source.Scale);
                worlds[i] = node.ComputeLocalTransform() * parentWorld;
            }
            else if (spec["world"] is JsonArray world)
            {
                var m = Matrix(Json.Floats(world));
                Matrix4x4.Invert(parentWorld, out var inverse);
                var local = m * inverse;
                if (!Matrix4x4.Decompose(local, out var scale, out _, out var translation))
                    throw new InvalidDataException($"The bind transform of {node.Name} cannot be split into scale, rotation and translation.");
                (node.Translation, node.Rotation, node.Scale) = (translation, Euler(local, scale), scale);
                worlds[i] = node.ComputeLocalTransform() * parentWorld;
                worstNode = Math.Max(worstNode, Difference(worlds[i], m));
            }
            else
            {
                worlds[i] = parentWorld;
            }
            flver.Nodes.Add(node);
        }
        if (worstNode > 1e-3) throw new InvalidDataException($"A node's rebuilt bind transform differs by {worstNode:0.####}.");
        Link(flver.Nodes);

        // Materials: a template material's textures, MTD and GX list, with the new texture paths by role.
        foreach (var spec in job["materials"]!.AsArray().Select(m => m!.AsObject()))
        {
            var source = template.Materials[spec["template"]!.GetValue<int>()];
            var material = new FLVER2.Material
            {
                Name = Json.Text(spec, "name"), MTD = Json.OptionalText(spec, "mtd") ?? source.MTD,
                GXIndex = source.GXIndex, Index = flver.Materials.Count,
            };
            var paths = spec["textures"]?.AsObject() ?? new JsonObject();
            foreach (var texture in source.Textures)
            {
                var role = Role(texture.ParamName);
                material.Textures.Add(new FLVER2.Texture(texture.ParamName, role != null && paths[role] is { } path ? path.GetValue<string>() : "",
                    texture.TilingScale, texture.TilingTypeU, texture.TilingTypeV, texture.Unk14, texture.Unk18, texture.Unk1C));
            }
            flver.Materials.Add(material);
        }

        // Meshes from the bridge's binary vertex and index files.
        var used = new HashSet<int>();
        var boneBoxes = new (Vector3 Min, Vector3 Max)[nodes.Count];
        for (int i = 0; i < boneBoxes.Length; i++) boneBoxes[i] = (new Vector3(float.MaxValue), new Vector3(float.MinValue));
        var inverseWorlds = worlds.Select(m => Matrix4x4.Invert(m, out var inv) ? inv : Matrix4x4.Identity).ToArray();
        var flags = template.Meshes.SelectMany(m => m.FaceSets).Select(f => f.Flags).Distinct().OrderBy(f => (uint)f).ToList();
        var modelMin = new Vector3(float.MaxValue); var modelMax = new Vector3(float.MinValue);
        int vertexTotal = 0, faceTotal = 0;
        foreach (var spec in job["meshes"]!.AsArray().Select(m => m!.AsObject()))
        {
            var mesh = new FLVER2.Mesh
            {
                MaterialIndex = spec["material"]!.GetValue<int>(), NodeIndex = spec["node"]!.GetValue<int>(), UseBoneWeights = true,
            };
            mesh.VertexBuffers.Add(new FLVER2.VertexBuffer(0));
            var raw = File.ReadAllBytes(Json.Text(spec, "vertices"));
            int stride = (VertexFloats + VertexInts) * 4;
            if (raw.Length % stride != 0) throw new InvalidDataException($"{Json.Text(spec, "vertices")} is not a whole number of vertices.");
            var min = new Vector3(float.MaxValue); var max = new Vector3(float.MinValue);
            var meshBones = new HashSet<int>();
            for (int at = 0; at < raw.Length; at += stride)
            {
                float F(int k) => BitConverter.ToSingle(raw, at + k * 4);
                int I(int k) => BitConverter.ToInt32(raw, at + (VertexFloats + k) * 4);
                var v = new FLVER.Vertex { Position = new Vector3(F(0), F(1), F(2)), Normal = new Vector3(F(3), F(4), F(5)), NormalW = 0 };
                for (int k = 0; k < tangentCount; k++) v.Tangents.Add(new Vector4(F(6), F(7), F(8), F(9)));
                v.UVs.Add(new Vector3(F(10), F(11), 0));
                for (int k = 1; k < uvCount; k++) v.UVs.Add(new Vector3(F(12), F(13), 0));
                for (int k = 0; k < colorCount; k++) v.Colors.Add(color);
                var weights = new[] { F(14), F(15), F(16), F(17) };
                for (int k = 0; k < 4; k++)
                {
                    int bone = weights[k] > 0 ? I(k) : 0;
                    if (bone < 0 || bone >= nodes.Count || bone > byte.MaxValue && layout.Any(m => m.Semantic == FLVER.LayoutSemantic.BoneIndices && m.Type == FLVER.LayoutType.UByte4))
                        throw new InvalidDataException($"A vertex names node {bone}, which this layout cannot hold.");
                    v.BoneIndices[k] = bone;
                    v.BoneWeights[k] = weights[k];
                    if (weights[k] <= 0) continue;
                    used.Add(bone); meshBones.Add(bone);
                    var local = Vector3.Transform(v.Position, inverseWorlds[bone]);
                    boneBoxes[bone] = (Vector3.Min(boneBoxes[bone].Min, local), Vector3.Max(boneBoxes[bone].Max, local));
                }
                min = Vector3.Min(min, v.Position); max = Vector3.Max(max, v.Position);
                mesh.Vertices.Add(v);
            }
            var indexData = File.ReadAllBytes(Json.Text(spec, "indices"));
            var indices = Enumerable.Range(0, indexData.Length / 4).Select(k => BitConverter.ToInt32(indexData, k * 4)).ToList();
            if (indices.Count % 3 != 0 || indices.Any(k => k < 0 || k >= mesh.Vertices.Count))
                throw new InvalidDataException($"{Json.Text(spec, "indices")} does not hold whole triangles of this mesh.");
            bool cull = spec["cullBackfaces"]?.GetValue<bool>() ?? true;
            foreach (var flag in flags)
                mesh.FaceSets.Add(new FLVER2.FaceSet(flag, false, cull, (short)meshBones.Count, indices));
            // Sekiro's mesh box is an oriented box: half size, rotation and center.
            mesh.BoundingBox = new FLVER2.Mesh.BoundingBoxes { Min = (max - min) / 2, Max = Vector3.Zero, Unk = (max + min) / 2 };
            modelMin = Vector3.Min(modelMin, min); modelMax = Vector3.Max(modelMax, max);
            vertexTotal += mesh.Vertices.Count; faceTotal += indices.Count / 3;
            flver.Meshes.Add(mesh);
        }
        flver.Header.BoundingBoxMin = modelMin;
        flver.Header.BoundingBoxMax = modelMax;

        // Dummy polys: the template's, each moved with its attach bone. The offset from that bone stays as it was.
        var templateWorlds = new Matrix4x4[template.Nodes.Count];
        for (int i = 0; i < template.Nodes.Count; i++)
            templateWorlds[i] = template.Nodes[i].ComputeLocalTransform() * (template.Nodes[i].ParentIndex >= 0 ? templateWorlds[template.Nodes[i].ParentIndex] : Matrix4x4.Identity);
        var nodeIndex = flver.Nodes.Select((n, i) => (n, i)).GroupBy(x => x.n.Name).ToDictionary(g => g.Key, g => g.First().i);
        var dummyMap = job["dummyBones"]?.AsObject() ?? new JsonObject();
        int Moved(int templateNode) => templateNode < 0 ? -1
            : dummyMap[template.Nodes[templateNode].Name] is { } to && nodeIndex.TryGetValue(to.GetValue<string>(), out var n) ? n
            : nodeIndex.TryGetValue(template.Nodes[templateNode].Name, out var same) ? same : -1;
        int dropped = 0;
        foreach (var d in template.Dummies)
        {
            int attach = Moved(d.AttachBoneIndex), parent = Moved(d.ParentBoneIndex);
            if (d.AttachBoneIndex >= 0 && attach < 0 || d.ParentBoneIndex >= 0 && parent < 0) { dropped++; continue; }
            var copy = new FLVER.Dummy
            {
                ReferenceID = d.ReferenceID, AttachBoneIndex = (short)attach, ParentBoneIndex = (short)parent, Flag1 = d.Flag1,
                UseUpwardVector = d.UseUpwardVector, Color = d.Color, Unk30 = d.Unk30, Unk34 = d.Unk34,
                Position = d.Position, Forward = d.Forward, Upward = d.Upward,
            };
            if (d.AttachBoneIndex >= 0)
            {
                // Model space of the template, through the template attach bone's space, into the new attach bone's.
                var parentOld = d.ParentBoneIndex >= 0 ? templateWorlds[d.ParentBoneIndex] : Matrix4x4.Identity;
                var parentNew = parent >= 0 ? worlds[parent] : Matrix4x4.Identity;
                Matrix4x4.Invert(templateWorlds[d.AttachBoneIndex], out var toOldBone);
                Matrix4x4.Invert(parentNew, out var toNewParent);
                var move = parentOld * toOldBone * worlds[attach] * toNewParent;
                copy.Position = Vector3.Transform(d.Position, move);
                copy.Forward = Vector3.TransformNormal(d.Forward, move);
                copy.Upward = Vector3.TransformNormal(d.Upward, move);
            }
            flver.Dummies.Add(copy);
        }

        // Flags and bone boxes, as the template's nodes have them.
        var dummyOwners = flver.Dummies.SelectMany(d => new int[] { d.AttachBoneIndex, d.ParentBoneIndex }).Where(i => i >= 0).ToHashSet();
        for (int i = 0; i < flver.Nodes.Count; i++)
        {
            var node = flver.Nodes[i];
            node.Flags = kinds[i] switch
            {
                "mesh" => FLVER.Node.NodeFlags.Mesh,
                "dummy" => FLVER.Node.NodeFlags.DummyOwner,
                "disabled" => FLVER.Node.NodeFlags.Disabled,
                _ => FLVER.Node.NodeFlags.Bone,
            };
            if (dummyOwners.Contains(i) && kinds[i] != "mesh") node.Flags |= FLVER.Node.NodeFlags.DummyOwner;
            (node.BoundingBoxMin, node.BoundingBoxMax) = used.Contains(i) ? boneBoxes[i] : (new Vector3(float.MaxValue), new Vector3(float.MinValue));
            if (used.Contains(i) && kinds[i] != "bone") throw new InvalidDataException($"Vertices are weighted to {node.Name}, which is not a bone.");
        }
        flver.Skeletons = new FLVER2.SkeletonSet();
        for (int i = 0; i < flver.Nodes.Count; i++)
        {
            var n = flver.Nodes[i];
            var bone = new FLVER2.SkeletonSet.Bone(i)
            {
                ParentIndex = n.ParentIndex, FirstChildIndex = n.FirstChildIndex, NextSiblingIndex = n.NextSiblingIndex,
                PreviousSiblingIndex = n.PreviousSiblingIndex,
            };
            flver.Skeletons.BaseSkeleton.Add(bone);
            flver.Skeletons.AllSkeletons.Add(new FLVER2.SkeletonSet.Bone(i)
            {
                ParentIndex = n.ParentIndex, FirstChildIndex = n.FirstChildIndex, NextSiblingIndex = n.NextSiblingIndex,
                PreviousSiblingIndex = n.PreviousSiblingIndex,
            });
        }

        var data = flver.Write();
        Json.WriteFile(Json.Text(job, "output"), data);
        var check = FLVER2.Read(data);
        if (check.Meshes.Count != flver.Meshes.Count || check.Meshes.Sum(m => m.Vertices.Count) != vertexTotal || check.Nodes.Count != flver.Nodes.Count)
            throw new InvalidDataException("The written model reads back with other counts.");
        return new
        {
            bytes = data.Length, nodes = flver.Nodes.Count, meshes = flver.Meshes.Count, vertices = vertexTotal, triangles = faceTotal,
            materials = flver.Materials.Count, dummies = flver.Dummies.Count, droppedDummies = dropped, layout = layoutIndex,
            weightedBones = used.Count, faceSetFlags = flags.Select(f => f.ToString()).ToList(),
            boundingBox = new { min = Json.V(modelMin), max = Json.V(modelMax) },
        };
    }

    // The texture role of a FromSoftware sampler name.
    public static string? Role(string paramName)
    {
        var name = paramName.ToLowerInvariant();
        if (name.Contains("albedo") || name.Contains("diffuse")) return "albedo";
        if (name.Contains("normalmap") || name.Contains("bumpmap")) return "normal";
        if (name.Contains("reflectance") || name.Contains("metallic") || name.Contains("specular")) return "metallic";
        if (name.Contains("emissive")) return "emissive";
        return null;
    }

    // Row-major 4x4, in System.Numerics' row-vector order: the last row holds the translation.
    static Matrix4x4 Matrix(float[] f) => new(f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11], f[12], f[13], f[14], f[15]);

    static double Difference(Matrix4x4 a, Matrix4x4 b)
    {
        var d = a - b;
        return new[] { d.M11, d.M12, d.M13, d.M21, d.M22, d.M23, d.M31, d.M32, d.M33, d.M41, d.M42, d.M43 }.Max(v => Math.Abs((double)v));
    }

    // Angles for FLVER.Node.ComputeLocalTransform, which rotates about X, then Z, then Y, from a local transform and the
    // scale Matrix4x4.Decompose found in it. They come from the rotation rows in double, not through a float quaternion:
    // that round trip left a bone turned exactly 90° about Z (Wolf's B_Wepon_Case0_R) just off the gimbal, where X and Y
    // then followed rounding noise and the node missed its bind by 0.0142. Near 90° about Z, X and Y turn about one axis,
    // so both splits are tried and the one that rebuilds the rotation better is kept.
    public static Vector3 Euler(Matrix4x4 local, Vector3 scale)
    {
        var r = new double[3, 3]
        {
            { local.M11 / (double)scale.X, local.M12 / (double)scale.X, local.M13 / (double)scale.X },
            { local.M21 / (double)scale.Y, local.M22 / (double)scale.Y, local.M23 / (double)scale.Y },
            { local.M31 / (double)scale.Z, local.M32 / (double)scale.Z, local.M33 / (double)scale.Z },
        };
        double z = Math.Asin(Math.Clamp(r[0, 1], -1, 1));
        var split = (X: Math.Atan2(-r[2, 1], r[1, 1]), Y: Math.Atan2(-r[0, 2], r[0, 0]));
        var gimbal = (X: 0.0, Y: Math.Atan2(r[2, 0], r[2, 2]));
        var best = Miss(split.X, split.Y, z, r) <= Miss(gimbal.X, gimbal.Y, z, r) ? split : gimbal;
        return new Vector3((float)best.X, (float)best.Y, (float)z);
    }

    // How far the rotation X, then Z, then Y (row vectors, as System.Numerics) lies from r.
    static double Miss(double x, double y, double z, double[,] r)
    {
        double cx = Math.Cos(x), sx = Math.Sin(x), cy = Math.Cos(y), sy = Math.Sin(y), cz = Math.Cos(z), sz = Math.Sin(z);
        var m = new double[3, 3]
        {
            { cz * cy, sz, -cz * sy },
            { -cx * sz * cy + sx * sy, cx * cz, cx * sz * sy + sx * cy },
            { sx * sz * cy + cx * sy, -sx * cz, -sx * sz * sy + cx * cy },
        };
        double miss = 0;
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                miss = Math.Max(miss, Math.Abs(m[i, j] - r[i, j]));
        return miss;
    }

    static void Link(List<FLVER.Node> nodes)
    {
        foreach (var n in nodes) n.FirstChildIndex = n.NextSiblingIndex = n.PreviousSiblingIndex = -1;
        for (int i = 0; i < nodes.Count; i++)
        {
            int parent = nodes[i].ParentIndex;
            // Root nodes are not linked as siblings, as in the game's own models.
            if (parent < 0) continue;
            if (nodes[parent].FirstChildIndex < 0) { nodes[parent].FirstChildIndex = (short)i; continue; }
            int last = nodes[parent].FirstChildIndex;
            while (nodes[last].NextSiblingIndex >= 0) last = nodes[last].NextSiblingIndex;
            nodes[last].NextSiblingIndex = (short)i;
            nodes[i].PreviousSiblingIndex = (short)last;
        }
    }

    // The vertex color most of the template's vertices carry; the game's shaders read these channels as data.
    static FLVER.VertexColor CommonColor(FLVER2 template)
    {
        var colors = template.Meshes.SelectMany(m => m.Vertices.Take(64)).Where(v => v.Colors.Count > 0).Select(v => v.Colors[0]);
        var best = colors.GroupBy(c => (c.R, c.G, c.B, c.A)).OrderByDescending(g => g.Count()).FirstOrDefault();
        return best == null ? new FLVER.VertexColor(1f, 1f, 1f, 1f) : best.First();
    }
}

// A TPF of DDS files, with the template TPF's platform and flags.
static class TextureWriter
{
    public static object Run(JsonObject job)
    {
        var template = TPF.Read(File.ReadAllBytes(Json.Text(job, "template")));
        var tpf = new TPF { Platform = template.Platform, Encoding = template.Encoding, Flag2 = template.Flag2 };
        foreach (var spec in job["textures"]!.AsArray().Select(t => t!.AsObject()))
        {
            var bytes = File.ReadAllBytes(Json.Text(spec, "dds"));
            var texture = new TPF.Texture(Json.Text(spec, "name"), (byte)spec["format"]!.GetValue<int>(), 0, bytes, tpf.Platform);
            texture.Mipmaps = (byte)Math.Max(1, BitConverter.ToInt32(bytes, 28));
            tpf.Textures.Add(texture);
        }
        var data = tpf.Write();
        Json.WriteFile(Json.Text(job, "output"), data);
        var check = TPF.Read(data);
        return new { bytes = data.Length, textures = check.Textures.Select(t => new { name = t.Name, format = (int)t.Format, mipmaps = (int)t.Mipmaps, bytes = t.Bytes.Length }).ToList() };
    }
}

// A map with a model entry for the new character, copied from the template's, and the chosen parts set to it.
static class MapWriter
{
    public static object Run(JsonObject job)
    {
        var msb = MSBS.Read(File.ReadAllBytes(Json.Text(job, "input")));
        string templateModel = Json.Text(job, "templateModel"), model = Json.Text(job, "model");
        var source = msb.Models.Enemies.FirstOrDefault(m => string.Equals(m.Name, templateModel, StringComparison.OrdinalIgnoreCase))
            ?? throw new ArgumentException($"The map has no model {templateModel}.");
        if (!msb.Models.Enemies.Any(m => string.Equals(m.Name, model, StringComparison.OrdinalIgnoreCase)))
        {
            var added = (MSBS.Model.Enemy)source.DeepCopy();
            added.Name = model;
            added.SibPath = source.SibPath.Replace(templateModel, model, StringComparison.OrdinalIgnoreCase);
            msb.Models.Enemies.Add(added);
        }
        var changed = new List<object>();
        foreach (var name in job["parts"]!.AsArray().Select(p => p!.GetValue<string>()))
        {
            var part = msb.Parts.Enemies.FirstOrDefault(e => e.Name == name) ?? throw new ArgumentException($"The map has no enemy part {name}.");
            if (!string.Equals(part.ModelName, templateModel, StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException($"Part {name} uses model {part.ModelName}, not {templateModel}.");
            part.ModelName = model;
            changed.Add(new { name, entityId = part.EntityID, npcParamId = part.NPCParamID, thinkParamId = part.ThinkParamID });
        }
        var data = msb.Write();
        Json.WriteFile(Json.Text(job, "output"), data);
        var check = MSBS.Read(data);
        return new
        {
            bytes = data.Length, models = check.Models.Enemies.Count, enemies = check.Parts.Enemies.Count, parts = changed,
            readback = check.Parts.Enemies.Where(e => string.Equals(e.ModelName, model, StringComparison.OrdinalIgnoreCase)).Select(e => e.Name).ToList(),
        };
    }
}
