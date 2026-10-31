#nullable enable
using System.Text.Json;
using SoulsAssetPipeline.Animation;

if (args.Length == 1 && args[0] == "--version")
{
    Console.WriteLine("SekiroMotionDecoder 0.7.0 (spline, interleaved, skeleton-compendiums, separate-compendiums, native-packfiles, preview, additive)");
    return 0;
}

// --preview <samples>: write the UI's skeleton preview instead of the motion, at most that many joint samples.
int previewLimit = 0;
if (args.Length >= 2 && args[0] == "--preview")
{
    if (!int.TryParse(args[1], out previewLimit) || previewLimit < 1)
    {
        Console.Error.WriteLine("--preview needs a positive number of joint samples.");
        return 2;
    }
    args = args[2..];
}

if (args.Length != 4 && args.Length != 5)
{
    Console.Error.WriteLine("Usage: SekiroMotionDecoder [--preview <samples>] <animation.hkx> <matching.compendium|-> <skeleton.hkx> <output.json> [skeleton.compendium|-]");
    return 2;
}

string animationPath = Path.GetFullPath(args[0]);
string compendiumPath = Path.GetFullPath(args[1]);
string skeletonPath = Path.GetFullPath(args[2]);
string outputPath = Path.GetFullPath(args[3]);

try
{
    byte[]? compendium = args[1] == "-" ? null : File.ReadAllBytes(compendiumPath);
    byte[]? skeletonCompendium = args.Length == 5 ? (args[4] == "-" ? null : File.ReadAllBytes(args[4])) : compendium;
    // NPC skeleton tagfiles can reference the same external types as their clips.
    HKX ReadDocument(byte[] data, byte[]? types)
    {
        if (data.Length >= 16 && data[0] == 0x57 && data[1] == 0xE0 && data[2] == 0xE0 && data[3] == 0x57)
            return HKX.Read(data);
        return HKX.GenFakeFromTagFile(data, types);
    }
    HKX skeletonDocument = ReadDocument(File.ReadAllBytes(skeletonPath), skeletonCompendium);
    HKX motionDocument = ReadDocument(File.ReadAllBytes(animationPath), compendium);

    HKX.HKASkeleton skeleton = skeletonDocument.DataSection.Objects.OfType<HKX.HKASkeleton>().Single();
    var spline = motionDocument.DataSection.Objects.OfType<HKX.HKASplineCompressedAnimation>().SingleOrDefault();
    var interleaved = motionDocument.DataSection.Objects.OfType<HKX.HKAInterleavedUncompressedAnimation>().SingleOrDefault();
    HKX.HKAAnimationBinding binding = motionDocument.DataSection.Objects
        .OfType<HKX.HKAAnimationBinding>().Single();
    HKX.HKADefaultAnimatedReferenceFrame? referenceFrame = motionDocument.DataSection.Objects
        .OfType<HKX.HKADefaultAnimatedReferenceFrame>().SingleOrDefault();

    HavokAnimationData animationData;
    if (spline != null)
        animationData = new HavokAnimationData_SplineCompressed(0, Path.GetFileName(animationPath), skeleton, referenceFrame, binding, spline);
    else if (interleaved != null)
        animationData = new HavokAnimationData_InterleavedUncompressed(0, Path.GetFileName(animationPath), skeleton, referenceFrame, binding, interleaved);
    else
        throw new NotSupportedException("This HKX contains no supported spline or interleaved animation.");
    int floatTrackCount = spline?.FloatTrackCount ?? interleaved!.FloatTrackCount;
    if (floatTrackCount != 0)
        throw new NotSupportedException("This animation has float tracks. This version exports skeletal transform tracks only.");
    // An additive clip (blendHint 1 or 2) holds changes to the pose below it, not a pose. Its frames are written as
    // decoded: channels it does not animate are no change (translation 0, rotation identity, scale 1).
    int blendHint = (int)animationData.BlendHint;

    var trackToBone = animationData.TransformTrackIndexToHkxBoneMap;
    int trackCount = spline?.TransformTrackCount ?? interleaved!.TransformTrackCount;
    var namesByTrack = animationData.GetTransformTrackBoneNameMapping();
    string[] trackNames = Enumerable.Range(0, trackCount)
        .Select(i => namesByTrack.TryGetValue(i, out string? name) ? name : $"unmapped_{i}")
        .ToArray();

    if (previewLimit > 0)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        Preview.Write(outputPath, Path.GetFileName(animationPath), skeleton, animationData, trackToBone, trackCount, previewLimit, blendHint);
        Console.WriteLine(outputPath);
        return 0;
    }

    var frames = Enumerable.Range(0, animationData.FrameCount).Select(frameIndex =>
        Enumerable.Range(0, trackCount).Select(trackIndex =>
        {
            var transform = animationData.GetTransformOnFrame(trackIndex, frameIndex, false);
            return new
            {
                translation = new[] { transform.Translation.X, transform.Translation.Y, transform.Translation.Z },
                rotation = new[] { transform.Rotation.X, transform.Rotation.Y, transform.Rotation.Z, transform.Rotation.W },
                scale = new[] { transform.Scale.X, transform.Scale.Y, transform.Scale.Z },
            };
        }).ToArray()).ToArray();

    var bones = skeleton.Bones.GetArrayData().Elements;
    var parents = skeleton.ParentIndices.GetArrayData().Elements;
    var restTransforms = skeleton.Transforms.GetArrayData().Elements;
    var skeletonData = new
    {
        name = skeleton.Name.GetString(),
        boneCount = bones.Count,
        bones = bones.Select((bone, index) => new
        {
            index,
            name = bone.Name.GetString(),
            parent = (int)parents[index].data,
            translation = new[]
            {
                restTransforms[index].Position.Vector.X,
                restTransforms[index].Position.Vector.Y,
                restTransforms[index].Position.Vector.Z,
            },
            rotation = new[]
            {
                restTransforms[index].Rotation.Vector.X,
                restTransforms[index].Rotation.Vector.Y,
                restTransforms[index].Rotation.Vector.Z,
                restTransforms[index].Rotation.Vector.W,
            },
            scale = new[]
            {
                restTransforms[index].Scale.Vector.X,
                restTransforms[index].Scale.Vector.Y,
                restTransforms[index].Scale.Vector.Z,
            },
        }).ToArray(),
    };

    var motionData = new
    {
        format = "sekiro-animation-bridge",
        formatVersion = 1,
        clip = Path.GetFileName(animationPath),
        skeletonName = skeleton.Name.GetString(),
        skeleton = skeletonData,
        frameCount = animationData.FrameCount,
        frameRate = 1.0f / animationData.FrameDuration,
        duration = animationData.Duration,
        trackCount,
        blockCount = spline?.BlockCount ?? 0,
        compression = spline != null ? "spline" : "interleaved",
        trackBoneIndices = trackToBone,
        trackNames,
        rootMotion = animationData.RootMotion?.Frames.Select(v => new[] { v.X, v.Y, v.Z, v.W }).ToArray(),
        rootUp = referenceFrame == null ? null : new[] { referenceFrame.Up.X, referenceFrame.Up.Y, referenceFrame.Up.Z, referenceFrame.Up.W },
        rootForward = referenceFrame == null ? null : new[] { referenceFrame.Forward.X, referenceFrame.Forward.Y, referenceFrame.Forward.Z, referenceFrame.Forward.W },
        frames,
    };

    Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
    // Compact: a long clip's indented JSON runs to tens of megabytes, and the UI preview reads it all back.
    using (var stream = File.Create(outputPath))
    {
        if (animationData.IsAdditiveBlend)
        {
            // Only additive clips get the field, so a normal clip's JSON stays as earlier versions wrote it.
            var document = JsonSerializer.SerializeToNode(motionData)!.AsObject();
            document["additive"] = JsonSerializer.SerializeToNode(new { blendHint, space = blendHint == 1 ? "parent" : "child" });
            using var writer = new Utf8JsonWriter(stream);
            document.WriteTo(writer);
        }
        else
            JsonSerializer.Serialize(stream, motionData);
    }
    Console.WriteLine($"Decoded {Path.GetFileName(animationPath)}: skeleton={skeleton.Name.GetString()}, frames={animationData.FrameCount}, tracks={trackCount}, mapped={namesByTrack.Count}, rootMotion={animationData.RootMotion?.Frames.Length ?? 0}");
    Console.WriteLine(outputPath);
    return 0;
}
catch (Exception ex)
{
    string hint = ex.Message.Contains("Compendium", StringComparison.OrdinalIgnoreCase)
        ? " Select the matching .compendium from this character's animation binder; the skeleton may require it too."
        : "";
    Console.Error.WriteLine($"Could not decode {Path.GetFileName(animationPath)}: {ex.Message}{hint}");
    return 1;
}

/// <summary>
/// The bridge UI's skeleton preview, as clip_preview.py builds it from the motion JSON:
/// world positions of every bone on every step-th frame, rounded to 0.1 mm.
/// </summary>
static class Preview
{
    // Rows of the 3x4 matrix of a rotation (x, y, z, w) and scale, then translation.
    static double[] Matrix(double x, double y, double z, double w, double sx, double sy, double sz, double tx, double ty, double tz) => new[]
    {
        sx * (1 - 2 * (y * y + z * z)), sy * 2 * (x * y - z * w), sz * 2 * (x * z + y * w), tx,
        sx * 2 * (x * y + z * w), sy * (1 - 2 * (x * x + z * z)), sz * 2 * (y * z - x * w), ty,
        sx * 2 * (x * z - y * w), sy * 2 * (y * z + x * w), sz * (1 - 2 * (x * x + y * y)), tz,
    };

    static void Compose(double[] above, double[] local, double[] result)
    {
        for (int row = 0; row < 3; row++)
        {
            for (int column = 0; column < 4; column++)
            {
                double value = above[row * 4] * local[column] + above[row * 4 + 1] * local[4 + column] + above[row * 4 + 2] * local[8 + column];
                result[row * 4 + column] = column == 3 ? value + above[row * 4 + 3] : value;
            }
        }
    }

    static double Median(List<double> values)
    {
        values.Sort();
        int middle = values.Count / 2;
        return values.Count % 2 == 1 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
    }

    // Rounded like Python's round(value, 4); adding 0.0 turns -0 into 0.
    static void WriteRounded(Utf8JsonWriter json, double value) => json.WriteNumberValue(Math.Round(value, 4) + 0.0);

    static (double x, double y, double z, double w) Multiply((double x, double y, double z, double w) a, (double x, double y, double z, double w) b) =>
        (a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y, a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
         a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w, a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z);

    static (double x, double y, double z) Rotate((double x, double y, double z, double w) q, (double x, double y, double z) v)
    {
        var turned = Multiply(Multiply(q, (v.x, v.y, v.z, 0)), (-q.x, -q.y, -q.z, q.w));
        return (turned.x, turned.y, turned.z);
    }

    // An additive track's change on the bone's rest pose, as standalone/games/additive.py composes it: Havok's
    // product change * rest in the parent's space for blendHint 1, rest * change for blendHint 2.
    static (double x, double y, double z, double w) Normalized((double x, double y, double z, double w) q)
    {
        double length = Math.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
        return length > 0 ? (q.x / length, q.y / length, q.z / length, q.w / length) : (0, 0, 0, 1);
    }

    static double[] Additive(NewBlendableTransform change, HKX.Transform rest, int blendHint)
    {
        // Decoded rotations are unit length only to their compression's precision.
        var d = Normalized((change.Rotation.X, change.Rotation.Y, change.Rotation.Z, change.Rotation.W));
        var b = Normalized((rest.Rotation.Vector.X, rest.Rotation.Vector.Y, rest.Rotation.Vector.Z, rest.Rotation.Vector.W));
        (double x, double y, double z) dt = (change.Translation.X, change.Translation.Y, change.Translation.Z);
        (double x, double y, double z) bt = (rest.Position.Vector.X, rest.Position.Vector.Y, rest.Position.Vector.Z);
        var r = Normalized(blendHint == 1 ? Multiply(d, b) : Multiply(b, d));
        var moved = blendHint == 1 ? Rotate(d, bt) : Rotate(b, dt);
        var t = blendHint == 1 ? (dt.x + moved.x, dt.y + moved.y, dt.z + moved.z) : (bt.x + moved.x, bt.y + moved.y, bt.z + moved.z);
        return Matrix(r.x, r.y, r.z, r.w, change.Scale.X * rest.Scale.Vector.X,
            change.Scale.Y * rest.Scale.Vector.Y, change.Scale.Z * rest.Scale.Vector.Z, t.Item1, t.Item2, t.Item3);
    }

    public static void Write(string outputPath, string clip, HKX.HKASkeleton skeleton, HavokAnimationData animation,
        int[] trackToBone, int trackCount, int limit, int blendHint)
    {
        var bones = skeleton.Bones.GetArrayData().Elements;
        var parents = skeleton.ParentIndices.GetArrayData().Elements.Select(p => (int)p.data).ToArray();
        var restTransforms = skeleton.Transforms.GetArrayData().Elements;
        var rest = restTransforms.Select(t => Matrix(
            t.Rotation.Vector.X, t.Rotation.Vector.Y, t.Rotation.Vector.Z, t.Rotation.Vector.W,
            t.Scale.Vector.X, t.Scale.Vector.Y, t.Scale.Vector.Z,
            t.Position.Vector.X, t.Position.Vector.Y, t.Position.Vector.Z)).ToArray();
        int count = bones.Count, frameCount = animation.FrameCount;
        // A longer clip keeps only every second (third, ...) frame, and only those are decoded.
        int step = Math.Max(1, (int)Math.Ceiling((double)frameCount * count / limit));

        var positions = new List<double[]>();
        var local = new double[count][];
        var world = Enumerable.Range(0, count).Select(_ => new double[12]).ToArray();
        for (int frame = 0; frame < frameCount; frame += step)
        {
            Array.Copy(rest, local, count);
            for (int track = 0; track < trackCount; track++)
            {
                int bone = trackToBone[track];
                if (bone < 0 || bone >= count)
                    continue;
                var t = animation.GetTransformOnFrame(track, frame, false);
                local[bone] = blendHint != 0 ? Additive(t, restTransforms[bone], blendHint)
                    : Matrix(t.Rotation.X, t.Rotation.Y, t.Rotation.Z, t.Rotation.W,
                        t.Scale.X, t.Scale.Y, t.Scale.Z, t.Translation.X, t.Translation.Y, t.Translation.Z);
            }
            var row = new double[count * 3];
            for (int bone = 0; bone < count; bone++)
            {
                if (parents[bone] < 0)
                    Array.Copy(local[bone], world[bone], 12);
                else
                    Compose(world[parents[bone]], local[bone], world[bone]);
                for (int axis = 0; axis < 3; axis++)
                    row[bone * 3 + axis] = Math.Round(world[bone][axis * 4 + 3], 4) + 0.0;
            }
            positions.Add(row);
        }

        // Bones that a frame places far from the rest of the skeleton, such as Wolf's camera
        // dummy 4 m away. The preview leaves them out, so that the body fills the view.
        var spans = new double[count];
        var values = new List<double>(count);
        var centre = new double[3];
        foreach (var row in positions)
        {
            for (int axis = 0; axis < 3; axis++)
            {
                values.Clear();
                for (int bone = 0; bone < count; bone++)
                    values.Add(row[bone * 3 + axis]);
                centre[axis] = Median(values);
            }
            for (int bone = 0; bone < count; bone++)
            {
                double dx = row[bone * 3] - centre[0], dy = row[bone * 3 + 1] - centre[1], dz = row[bone * 3 + 2] - centre[2];
                spans[bone] = Math.Max(spans[bone], Math.Sqrt(dx * dx + dy * dy + dz * dz));
            }
        }
        double far = positions.Count == 0 || count == 0 ? double.PositiveInfinity : Math.Max(4 * Median(spans.ToList()), .5);

        using var stream = File.Create(outputPath);
        using var json = new Utf8JsonWriter(stream);
        float frameRate = 1.0f / animation.FrameDuration;
        json.WriteStartObject();
        json.WriteString("clip", clip);
        json.WriteString("skeleton", skeleton.Name.GetString());
        json.WriteNumber("frameCount", frameCount);
        json.WriteNumber("frameRate", frameRate);
        json.WriteNumber("duration", animation.Duration != 0 ? animation.Duration : (frameCount - 1) / frameRate);
        json.WriteNumber("frameStep", step);
        json.WriteStartArray("bones");
        foreach (var bone in bones)
            json.WriteStringValue(bone.Name.GetString());
        json.WriteEndArray();
        json.WriteStartArray("parents");
        foreach (int parent in parents)
            json.WriteNumberValue(parent);
        json.WriteEndArray();
        json.WriteNumber("tracks", trackCount);
        json.WriteStartArray("positions");
        foreach (var row in positions)
        {
            json.WriteStartArray();
            foreach (double value in row)
                json.WriteNumberValue(value);
            json.WriteEndArray();
        }
        json.WriteEndArray();
        json.WriteStartArray("detached");
        for (int bone = 0; bone < count; bone++)
            if (spans[bone] > far)
                json.WriteNumberValue(bone);
        json.WriteEndArray();
        var root = animation.RootMotion?.Frames;
        if (root == null || root.Length == 0)
            json.WriteNull("root");
        else
        {
            json.WriteStartArray("root");
            for (int frame = 0; frame < root.Length; frame += step)
            {
                json.WriteStartArray();
                WriteRounded(json, root[frame].X);
                WriteRounded(json, root[frame].Y);
                WriteRounded(json, root[frame].Z);
                WriteRounded(json, root[frame].W);
                json.WriteEndArray();
            }
            json.WriteEndArray();
        }
        json.WriteEndObject();
    }
}
