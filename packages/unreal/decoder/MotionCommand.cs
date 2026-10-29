#nullable enable
using System.Text.Json;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.Utils;
using CUE4Parse_Conversion.Animations;
using CUE4Parse_Conversion.Writers.ActorX.Structs.Animations;

namespace UnrealDecoder;

/// <summary>A bone of a reference skeleton, with its local rest transform.</summary>
internal sealed record RestBone(string Name, int Parent, FTransform Rest);

internal static class Bones
{
    /// <summary>The bones of a reference skeleton. Unreal keeps parents before their children; anything else is refused.</summary>
    public static List<RestBone> Read(FReferenceSkeleton skeleton)
    {
        var bones = new List<RestBone>(skeleton.FinalRefBoneInfo.Length);
        for (var index = 0; index < skeleton.FinalRefBoneInfo.Length; index++)
        {
            var info = skeleton.FinalRefBoneInfo[index];
            if (info.ParentIndex >= index)
                throw new InvalidDataException($"Bone {info.Name.Text} comes before its parent in the reference skeleton.");
            var rest = index < skeleton.FinalRefBonePose.Length ? skeleton.FinalRefBonePose[index] : FTransform.Identity;
            bones.Add(new RestBone(info.Name.Text, info.ParentIndex, rest));
        }
        return bones;
    }

    /// <summary>Bone names by index; Unreal compares names without case.</summary>
    public static Dictionary<string, int> Index(IEnumerable<RestBone> bones)
    {
        var index = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var (bone, position) in bones.Select((bone, position) => (bone, position)))
            index.TryAdd(bone.Name, position);
        return index;
    }
}

/// <summary>
/// Decodes one animation sequence. With a skeletal mesh the clip is retargeted to the mesh's bones the way the engine
/// plays it on that mesh; without one it plays on its skeleton's reference pose.
/// </summary>
internal static class MotionCommand
{
    public static int Decode(string optionsPath, string animationPath, string outputPath, string? meshPath)
    {
        var options = Source.Read(optionsPath);
        using var provider = Source.Open(options);
        var objectPath = Source.ObjectPath(animationPath);
        var sequence = provider.LoadPackageObject<UAnimSequence>(objectPath);
        if (sequence.Skeleton == null || !sequence.Skeleton.TryLoad<USkeleton>(out var skeleton))
            throw new InvalidDataException($"{objectPath} names no skeleton that loads.");
        var mesh = meshPath == null ? null : provider.LoadPackageObject<USkeletalMesh>(Source.ObjectPath(meshPath));
        var bones = Bones.Read(mesh?.ReferenceSkeleton ?? skeleton.ReferenceSkeleton);
        var boneIndex = Bones.Index(bones);

        var compression = sequence.RawAnimationData is { Length: > 0 }
            ? "raw"
            : sequence.CompressedDataStructure?.GetType().Name switch
            {
                "FACLCompressedAnimData" => "acl",
                "FUECompressedAnimData" => "unreal",
                null => "none",
                var name => name,
            };
        const string noAcl = "uses ACL compression, and this decoder was built without CUE4Parse's native ACL library. " +
                             "Install CMake and the Visual Studio C++ tools, then run decoder\\build_decoder.cmd again.";
        if (compression == "acl" && !CUE4ParseNatives.IsFeatureAvailable("ACL"))
            throw new InvalidDataException($"{objectPath} {noAcl}");

        CAnimSequence clip;
        try
        {
            clip = skeleton.ConvertAnims(sequence).Sequences.FirstOrDefault()
                   ?? throw new InvalidDataException($"{objectPath} holds no animation data CUE4Parse can read.");
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            throw new InvalidDataException($"{objectPath} {noAcl}", ex);
        }
        var frameCount = clip.NumFrames;
        if (frameCount <= 0)
            throw new InvalidDataException($"{objectPath} has no frames.");
        // NumFrames counts keys, so a one-second clip at 30 frames per second has 31.
        var frameRate = frameCount > 1 && sequence.SequenceLength > 0 ? Math.Round((frameCount - 1) / (double)sequence.SequenceLength, 3) : 30.0;

        // One track for every skeleton bone with keys that the output skeleton has.
        var source = skeleton.ReferenceSkeleton;
        var trackBones = new List<int>();
        var trackSources = new List<int>();
        var unmatched = new List<string>();
        for (var bone = 0; bone < Math.Min(clip.Tracks.Count, source.FinalRefBoneInfo.Length); bone++)
        {
            if (!clip.Tracks[bone].HasKeys()) continue;
            var name = source.FinalRefBoneInfo[bone].Name.Text;
            if (!boneIndex.TryGetValue(name, out var target))
            {
                unmatched.Add(name);
                continue;
            }
            if (trackBones.Contains(target)) continue;
            trackBones.Add(target);
            trackSources.Add(bone);
        }

        using (var stream = Program.CreateOutput(outputPath))
        using (var json = new Utf8JsonWriter(stream))
        {
            json.WriteStartObject();
            json.WriteString("format", "sekiro-animation-bridge");
            json.WriteNumber("formatVersion", 2);
            json.WriteStartObject("source");
            json.WriteString("engine", "unreal");
            json.WriteString("container", "package");
            json.WriteString("version", options.Engine);
            json.WriteString("member", objectPath);
            json.WriteEndObject();
            Program.WriteBasis(json);
            json.WriteString("clip", sequence.Name + ".uasset");
            json.WriteString("skeletonName", skeleton.Name);
            json.WriteStartObject("skeleton");
            json.WriteString("name", skeleton.Name);
            json.WriteNumber("boneCount", bones.Count);
            json.WriteStartArray("bones");
            for (var bone = 0; bone < bones.Count; bone++)
            {
                json.WriteStartObject();
                json.WriteNumber("index", bone);
                json.WriteString("name", bones[bone].Name);
                json.WriteNumber("parent", bones[bone].Parent);
                Program.WriteVector(json, "translation", bones[bone].Rest.Translation);
                Program.WriteQuaternion(json, "rotation", bones[bone].Rest.Rotation);
                Program.WriteVector(json, "scale", bones[bone].Rest.Scale3D);
                json.WriteEndObject();
            }
            json.WriteEndArray();
            json.WriteEndObject();
            json.WriteNumber("frameCount", frameCount);
            json.WriteNumber("frameRate", frameRate);
            json.WriteNumber("duration", (frameCount - 1) / frameRate);
            json.WriteNumber("trackCount", trackBones.Count);
            json.WriteNumber("blockCount", 0);
            json.WriteString("compression", compression);
            json.WriteStartArray("trackBoneIndices");
            foreach (var bone in trackBones) json.WriteNumberValue(bone);
            json.WriteEndArray();
            json.WriteStartArray("trackNames");
            foreach (var bone in trackBones) json.WriteStringValue(bones[bone].Name);
            json.WriteEndArray();
            // The bridge's root motion assumes a Y-up source; an Unreal root bone keeps its movement instead.
            json.WriteNull("rootMotion");
            json.WriteNull("rootUp");
            json.WriteNull("rootForward");

            var previous = trackBones.Select(bone => bones[bone].Rest.Rotation).ToArray();
            json.WriteStartArray("frames");
            for (var frame = 0; frame < frameCount; frame++)
            {
                json.WriteStartArray();
                for (var track = 0; track < trackBones.Count; track++)
                {
                    var bone = trackSources[track];
                    // Channels without keys keep the pose the clip was made on, as CUE4Parse's exporters do.
                    var rest = clip.RetargetBasePose is { } basePose && bone < basePose.Length ? basePose[bone] : source.FinalRefBonePose[bone];
                    var rotation = rest.Rotation;
                    var translation = rest.Translation;
                    var scale = rest.Scale3D;
                    clip.Tracks[bone].GetBoneTransform(frame, frameCount, ref rotation, ref translation, ref scale);
                    clip.RetargetBoneTransform(bone, bones[trackBones[track]].Rest, ref rotation, ref translation, ref scale);
                    rotation.Normalize();
                    // Keep each track's quaternion on one hemisphere so the bridge's curves do not jump.
                    var last = previous[track];
                    if (last.X * rotation.X + last.Y * rotation.Y + last.Z * rotation.Z + last.W * rotation.W < 0)
                        rotation = new FQuat(-rotation.X, -rotation.Y, -rotation.Z, -rotation.W);
                    previous[track] = rotation;
                    json.WriteStartObject();
                    Program.WriteVector(json, "translation", translation);
                    Program.WriteQuaternion(json, "rotation", rotation);
                    Program.WriteVector(json, "scale", scale);
                    json.WriteEndObject();
                }
                json.WriteEndArray();
            }
            json.WriteEndArray();
            json.WriteEndObject();
        }

        Console.WriteLine($"Decoded {sequence.Name}: skeleton={skeleton.Name}, bones={bones.Count}, frames={frameCount}, rate={frameRate}, " +
                          $"tracks={trackBones.Count}, compression={compression}, mesh={mesh?.Name ?? "none"}");
        if (unmatched.Count > 0)
            Console.WriteLine($"NOTE {unmatched.Count} animated bones are not in the mesh: {string.Join(", ", unmatched.Take(12))}{(unmatched.Count > 12 ? ", ..." : "")}");
        if (sequence.IsValidAdditive())
            Console.WriteLine($"NOTE {sequence.Name} is an additive clip; it was added to its base pose ({sequence.RefPoseType})");
        if (sequence.bEnableRootMotion)
            Console.WriteLine($"NOTE The game takes root motion from {sequence.Name}; here its root bone keeps that movement");
        if (sequence.RateScale > 0 && Math.Abs(sequence.RateScale - 1) > 1e-3)
            Console.WriteLine($"NOTE The game plays {sequence.Name} at {sequence.RateScale:0.###} times its speed; the clip keeps its own timing");
        Program.PrintLibraryWarnings();
        Console.WriteLine(Path.GetFullPath(outputPath));
        return 0;
    }
}
