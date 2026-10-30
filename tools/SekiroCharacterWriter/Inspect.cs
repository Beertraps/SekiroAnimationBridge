#nullable enable
using System.Text.Json.Nodes;
using SoulsFormats;

// What a character's files hold that a new character copies or changes: its model, textures and placements. The
// bridge runs it on the template and on its own output; it reads the Havok skeleton and behavior itself
// (standalone/havok_tagfile.py).
static class Inspect
{
    public static Dictionary<string, object?> Run(JsonObject job)
    {
        var report = new Dictionary<string, object?>();
        string id = Json.OptionalText(job, "templateId") ?? "";
        if (Json.OptionalText(job, "flver") is { } flver)
            report["flver"] = Model(FLVER2.Read(File.ReadAllBytes(flver)));
        if (Json.OptionalText(job, "tpf") is { } tpf)
        {
            var textures = TPF.Read(File.ReadAllBytes(tpf));
            report["tpf"] = new
            {
                platform = textures.Platform.ToString(), encoding = (int)textures.Encoding, flag2 = (int)textures.Flag2,
                textures = textures.Textures.Select(t => new { name = t.Name, format = (int)t.Format, flags1 = (int)t.Flags1,
                    type = t.Type.ToString(), mipmaps = (int)t.Mipmaps, bytes = t.Bytes.Length }).ToList(),
            };
        }
        if (job["maps"] is JsonArray maps)
            report["parts"] = maps.SelectMany(m => Parts(m!["name"]!.GetValue<string>(), File.ReadAllBytes(m["path"]!.GetValue<string>()),
                Json.OptionalText(job, "model") ?? id)).ToList();
        return report;
    }

    public static object Model(FLVER2 flver) => new
    {
        version = flver.Header.Version,
        unicode = flver.Header.Unicode,
        boundingBoxMin = Json.V(flver.Header.BoundingBoxMin),
        boundingBoxMax = Json.V(flver.Header.BoundingBoxMax),
        bones = flver.Nodes.Select(n => new
        {
            name = n.Name, parent = (int)n.ParentIndex, translation = Json.V(n.Translation), rotation = Json.V(n.Rotation),
            scale = Json.V(n.Scale), boundingBoxMin = Json.V(n.BoundingBoxMin), boundingBoxMax = Json.V(n.BoundingBoxMax), flags = (int)n.Flags,
        }).ToList(),
        dummies = flver.Dummies.Select(d => new
        {
            referenceId = (int)d.ReferenceID, parentBone = (int)d.ParentBoneIndex, attachBone = (int)d.AttachBoneIndex,
            position = Json.V(d.Position), forward = Json.V(d.Forward), upward = Json.V(d.Upward), useUpward = d.UseUpwardVector,
            flag1 = d.Flag1, color = new[] { (int)d.Color.A, d.Color.R, d.Color.G, d.Color.B }, unk30 = d.Unk30, unk34 = d.Unk34,
        }).ToList(),
        materials = flver.Materials.Select(m => new
        {
            name = m.Name, mtd = m.MTD, gxIndex = m.GXIndex, index = m.Index,
            textures = m.Textures.Select(t => new { type = t.ParamName, path = t.Path, scale = new[] { t.TilingScale.X, t.TilingScale.Y } }).ToList(),
        }).ToList(),
        gxLists = flver.GXLists.Select(g => g.Select(i => new { id = i.ID, unk04 = i.Unk04, bytes = i.Data.Length }).ToList()).ToList(),
        layouts = flver.BufferLayouts.Select(l => l.Select(m => new { semantic = m.Semantic.ToString(), type = m.Type.ToString(), index = m.Index }).ToList()).ToList(),
        meshes = flver.Meshes.Select(m => new
        {
            material = m.MaterialIndex, node = m.NodeIndex, useBoneWeights = m.UseBoneWeights, boneIndices = m.BoneIndices.Count,
            vertices = m.Vertices.Count, layouts = m.VertexBuffers.Select(b => b.LayoutIndex).ToList(),
            maxVertexBone = m.Vertices.Count == 0 ? -1 : m.Vertices.Max(v => Math.Max(Math.Max(v.BoneIndices[0], v.BoneIndices[1]), Math.Max(v.BoneIndices[2], v.BoneIndices[3]))),
            faceSets = m.FaceSets.Select(f => new { flags = (uint)f.Flags, strip = f.TriangleStrip, cull = f.CullBackfaces, unk06 = f.Unk06, indices = f.Indices.Count }).ToList(),
            boundingBox = m.BoundingBox == null ? null : new { min = Json.V(m.BoundingBox.Min), max = Json.V(m.BoundingBox.Max), unk = Json.V(m.BoundingBox.Unk) },
        }).ToList(),
        skeletons = flver.Skeletons == null ? null : new { baseBones = flver.Skeletons.BaseSkeleton.Count, allBones = flver.Skeletons.AllSkeletons.Count },
    };

    // The enemy parts that use the model, with the IDs that tell them apart.
    public static IEnumerable<object> Parts(string map, byte[] data, string model)
    {
        var msb = MSBS.Read(data);
        return msb.Parts.Enemies.Where(e => string.Equals(e.ModelName, model, StringComparison.OrdinalIgnoreCase)).Select(e => new
        {
            map, name = e.Name, model = e.ModelName, entityId = e.EntityID, npcParamId = e.NPCParamID, thinkParamId = e.ThinkParamID,
            position = Json.V(e.Position),
        });
    }
}
