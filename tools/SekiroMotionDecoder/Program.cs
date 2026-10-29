#nullable enable
using System.Text.Json;
using SoulsAssetPipeline.Animation;

if (args.Length == 1 && args[0] == "--version")
{
    Console.WriteLine("SekiroMotionDecoder 0.5.0 (spline, interleaved, skeleton-compendiums, separate-compendiums, native-packfiles)");
    return 0;
}

if (args.Length != 4 && args.Length != 5)
{
    Console.Error.WriteLine("Usage: SekiroMotionDecoder <animation.hkx> <matching.compendium|-> <skeleton.hkx> <output.json> [skeleton.compendium|-]");
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
    if (animationData.IsAdditiveBlend)
        throw new NotSupportedException("This animation uses additive blending, which is not supported by this version.");

    var trackToBone = animationData.TransformTrackIndexToHkxBoneMap;
    int trackCount = spline?.TransformTrackCount ?? interleaved!.TransformTrackCount;
    var namesByTrack = animationData.GetTransformTrackBoneNameMapping();
    string[] trackNames = Enumerable.Range(0, trackCount)
        .Select(i => namesByTrack.TryGetValue(i, out string? name) ? name : $"unmapped_{i}")
        .ToArray();

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
        JsonSerializer.Serialize(stream, motionData);
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
