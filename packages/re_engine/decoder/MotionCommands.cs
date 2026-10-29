#nullable enable
using System.Numerics;
using System.Text.Json;
using ReeLib;
using ReeLib.Common;
using ReeLib.Mot;
using ReeLib.Motlist;

namespace ReEngineDecoder;

/// <summary>One slot of a motion list, or the single motion of a loose .mot file.</summary>
internal sealed record MotionSlot(int Index, int Id, MotFileBase? File, MotIndex? Entry);

internal sealed record MotionSource(string Kind, int Version, string Path, List<MotionSlot> Slots, bool HasMirrorFlags);

/// <summary>
/// The timing of a mot. The header's frameCount is the clip length in frames at the header's frame rate
/// (DMC5 and RE2 tracks also carry their own rate, which matches it in the files checked); the decoder samples
/// every whole frame from 0 to that length, so a clip of length L has ceil(L) + 1 samples.
/// </summary>
internal readonly record struct MotionTiming(float FrameRate, float Length, float LastKey, int SampleCount)
{
    public static MotionTiming Of(MotFile mot)
    {
        var rate = mot.Header.FrameRate > 0 ? mot.Header.FrameRate : 60f;
        var lastKey = 0f;
        foreach (var clip in mot.BoneClips)
        {
            foreach (var track in Tracks(clip))
            {
                var times = MotionCommands.KeyTimes(track, rate);
                if (times.Length > 0) lastKey = MathF.Max(lastKey, times[^1]);
            }
        }
        var length = mot.Header.frameCount > 0 && float.IsFinite(mot.Header.frameCount) ? mot.Header.frameCount : lastKey;
        var samples = (int)MathF.Ceiling(length - 0.001f) + 1;
        return new MotionTiming(rate, length, lastKey, Math.Max(samples, 1));
    }

    private static IEnumerable<Track> Tracks(BoneMotionClip clip)
    {
        if (clip.HasTranslation) yield return clip.Translation!;
        if (clip.HasRotation) yield return clip.Rotation!;
        if (clip.HasScale) yield return clip.Scale!;
    }
}

internal static class MotionCommands
{
    public static MotionSource Load(string path)
    {
        var handler = Program.OpenRead(path);
        var magic = handler.ReadUInt(4);
        if (magic == MotlistFile.Magic)
        {
            var list = new MotlistFile(handler);
            list.Read();
            var slots = list.Motions.Select((entry, index) => new MotionSlot(index, entry.motNumber, entry.MotFile, entry)).ToList();
            return new MotionSource("motlist", (int)list.Header.version, handler.FilePath!, slots,
                list.Header.version >= MotlistVersion.RE8);
        }
        if (magic == MotFile.Magic)
        {
            var mot = new MotFile(handler);
            mot.Read();
            return new MotionSource("mot", (int)mot.Header.version, handler.FilePath!, [new MotionSlot(0, 0, mot, null)], false);
        }
        throw new InvalidDataException($"{Path.GetFileName(path)} is not a motion list or a motion file.");
    }

    public static int ListMotions(string inputPath, string outputPath)
    {
        var source = Load(inputPath);
        var motions = source.Slots.Select(slot => Describe(slot, source.HasMirrorFlags)).ToArray();
        Program.WriteJson(outputPath, new
        {
            version = source.Version,
            kind = source.Kind,
            // Motion lists before RE8's format (DMC5, RE2: 85) do not store the mirror flag where REE-Lib reads it.
            mirrorFlags = source.HasMirrorFlags,
            motions,
        });
        var clips = source.Slots.Count(slot => slot.File is MotFile);
        Console.WriteLine($"Listed {source.Slots.Count} entries of {Path.GetFileName(inputPath)}: {clips} motions");
        Program.PrintLibraryWarnings();
        return 0;
    }

    private static object Describe(MotionSlot slot, bool hasMirrorFlags)
    {
        var notes = new List<string>();
        var mirror = hasMirrorFlags && slot.Entry != null && slot.Entry.flags.HasFlag(MotListElementFlags.Mirror);
        switch (slot.File)
        {
            case MotFile mot:
                var timing = MotionTiming.Of(mot);
                var tracks = mot.BoneClips.Count(clip => clip.HasTranslation || clip.HasRotation || clip.HasScale);
                if (tracks == 0) notes.Add("No bone tracks");
                return new
                {
                    index = slot.Index,
                    id = slot.Id,
                    name = mot.Name,
                    frameCount = timing.SampleCount,
                    frameRate = timing.FrameRate,
                    length = timing.Length,
                    lastKey = timing.LastKey,
                    boneCount = mot.Bones.Count,
                    trackCount = tracks,
                    mirror,
                    additive = (bool?)null,
                    notes,
                };
            case MotFileLink link:
                notes.Add($"Reference to {link.Path}");
                break;
            case MotTreeFile:
                notes.Add("Motion tree, not a skeletal clip");
                break;
            case null:
                notes.Add("Empty slot");
                break;
            default:
                notes.Add($"Unsupported entry {slot.File.GetType().Name}");
                break;
        }
        return new
        {
            index = slot.Index,
            id = slot.Id,
            name = slot.File?.Name ?? "",
            frameCount = 0,
            frameRate = 0f,
            length = 0f,
            lastKey = 0f,
            boneCount = 0,
            trackCount = 0,
            mirror,
            additive = (bool?)null,
            notes,
        };
    }

    /// <summary>
    /// Key times in frames at the motion's rate. A track without frame indices has one key per frame.
    /// DMC5 and RE2 tracks carry their own frame rate; a different one is converted to the motion's.
    /// </summary>
    public static float[] KeyTimes(Track track, float motionRate)
    {
        var count = track.translations?.Length ?? track.rotations?.Length ?? track.floats?.Length ?? 0;
        var times = new float[count];
        var factor = track.frameRate > 0 && track.MotVersion <= MotVersion.RE2_DMC5 ? motionRate / track.frameRate : 1f;
        for (var key = 0; key < count; key++)
            times[key] = (track.frameIndexes != null && key < track.frameIndexes.Length ? track.frameIndexes[key] : key) * factor;
        return times;
    }

    private static int Segment(float[] times, float time)
    {
        var low = 0;
        var high = times.Length - 1;
        while (low < high)
        {
            var middle = (low + high + 1) / 2;
            if (times[middle] <= time) low = middle;
            else high = middle - 1;
        }
        return low;
    }

    public static Vector3 SampleVector(Vector3[]? values, float[] times, float time, Vector3 rest)
    {
        if (values == null || values.Length == 0) return rest;
        if (values.Length == 1 || time <= times[0]) return values[0];
        if (time >= times[^1]) return values[^1];
        var key = Segment(times, time);
        var span = times[key + 1] - times[key];
        var amount = span > 0 ? (time - times[key]) / span : 0f;
        return Vector3.Lerp(values[key], values[key + 1], amount);
    }

    public static Quaternion SampleRotation(Quaternion[]? values, float[] times, float time, Quaternion rest)
    {
        if (values == null || values.Length == 0) return rest;
        if (values.Length == 1 || time <= times[0]) return Normalize(values[0]);
        if (time >= times[^1]) return Normalize(values[^1]);
        var key = Segment(times, time);
        var span = times[key + 1] - times[key];
        var amount = span > 0 ? (time - times[key]) / span : 0f;
        // Slerp takes the shorter way; compressed keys rebuild W as positive, so neighbours can differ in sign.
        return Normalize(Quaternion.Slerp(Normalize(values[key]), Normalize(values[key + 1]), amount));
    }

    private static Quaternion Normalize(Quaternion value)
    {
        var length = value.Length();
        return length > 1e-8f ? Quaternion.Multiply(value, 1f / length) : Quaternion.Identity;
    }

    public static int Decode(string inputPath, int index, string outputPath, string? skeletonPath)
    {
        var source = Load(inputPath);
        if (index >= source.Slots.Count)
            throw new UsageException($"{Path.GetFileName(inputPath)} has {source.Slots.Count} entries; index {index} does not exist.");
        var slot = source.Slots[index];
        if (slot.File is not MotFile mot)
            throw new InvalidDataException($"Entry {index} of {Path.GetFileName(inputPath)} is not a skeletal motion.");

        var (skeletonName, fileBones) = skeletonPath == null ? (mot.Name, Skeletons.FromMot(mot)) : Skeletons.Load(skeletonPath);
        var bones = Skeletons.ParentFirst(fileBones, out _);
        var timing = MotionTiming.Of(mot);

        var clipsByHash = new Dictionary<uint, BoneMotionClip>();
        foreach (var clip in mot.BoneClips)
        {
            if (clip.HasTranslation || clip.HasRotation || clip.HasScale)
                clipsByHash.TryAdd(clip.ClipHeader.boneHash, clip);
        }
        var trackBones = new List<int>();
        var trackClips = new List<BoneMotionClip>();
        var matched = new HashSet<uint>();
        for (var bone = 0; bone < bones.Count; bone++)
        {
            if (!clipsByHash.TryGetValue(bones[bone].Hash, out var clip) || !matched.Add(bones[bone].Hash)) continue;
            trackBones.Add(bone);
            trackClips.Add(clip);
        }
        var unmatched = clipsByHash.Where(pair => !matched.Contains(pair.Key))
            .Select(pair => pair.Value.ClipHeader.boneName ?? $"#{pair.Key:x8}").ToList();

        // Key times per track and component, once.
        var keyTimes = trackClips.Select(clip => (
            translation: clip.HasTranslation ? KeyTimes(clip.Translation!, timing.FrameRate) : [],
            rotation: clip.HasRotation ? KeyTimes(clip.Rotation!, timing.FrameRate) : [],
            scale: clip.HasScale ? KeyTimes(clip.Scale!, timing.FrameRate) : Array.Empty<float>())).ToArray();

        using (var stream = Program.CreateOutput(outputPath))
        using (var json = new Utf8JsonWriter(stream))
        {
            json.WriteStartObject();
            json.WriteString("format", "sekiro-animation-bridge");
            json.WriteNumber("formatVersion", 2);
            json.WriteStartObject("source");
            json.WriteString("engine", "re_engine");
            json.WriteString("container", source.Kind);
            json.WriteNumber("version", source.Version);
            json.WriteString("archive", source.Path);
            json.WriteString("member", mot.Name);
            json.WriteNumber("index", index);
            json.WriteEndObject();
            json.WriteStartArray("basis");
            foreach (var row in Program.Basis)
            {
                json.WriteStartArray();
                foreach (var value in row) json.WriteNumberValue(value);
                json.WriteEndArray();
            }
            json.WriteEndArray();
            json.WriteNumber("unitScale", 1.0);
            json.WriteString("clip", mot.Name + ".mot");
            json.WriteString("skeletonName", skeletonName);
            json.WriteStartObject("skeleton");
            json.WriteString("name", skeletonName);
            json.WriteNumber("boneCount", bones.Count);
            json.WriteStartArray("bones");
            for (var bone = 0; bone < bones.Count; bone++)
            {
                json.WriteStartObject();
                json.WriteNumber("index", bone);
                json.WriteString("name", bones[bone].Name);
                json.WriteNumber("parent", bones[bone].Parent);
                Program.WriteVector(json, "translation", bones[bone].Translation);
                Program.WriteQuaternion(json, "rotation", bones[bone].Rotation);
                Program.WriteVector(json, "scale", bones[bone].Scale);
                json.WriteEndObject();
            }
            json.WriteEndArray();
            json.WriteEndObject();
            json.WriteNumber("frameCount", timing.SampleCount);
            json.WriteNumber("frameRate", timing.FrameRate);
            json.WriteNumber("duration", (timing.SampleCount - 1) / timing.FrameRate);
            json.WriteNumber("trackCount", trackBones.Count);
            json.WriteNumber("blockCount", 0);
            json.WriteString("compression", "re-mot");
            json.WriteStartArray("trackBoneIndices");
            foreach (var bone in trackBones) json.WriteNumberValue(bone);
            json.WriteEndArray();
            json.WriteStartArray("trackNames");
            foreach (var bone in trackBones) json.WriteStringValue(bones[bone].Name);
            json.WriteEndArray();
            json.WriteNull("rootMotion");
            json.WriteNull("rootUp");
            json.WriteNull("rootForward");

            var previous = trackBones.Select(bone => bones[bone].Rotation).ToArray();
            json.WriteStartArray("frames");
            for (var frame = 0; frame < timing.SampleCount; frame++)
            {
                json.WriteStartArray();
                for (var track = 0; track < trackBones.Count; track++)
                {
                    var rest = bones[trackBones[track]];
                    var clip = trackClips[track];
                    var translation = SampleVector(clip.HasTranslation ? clip.Translation!.translations : null, keyTimes[track].translation, frame, rest.Translation);
                    var rotation = SampleRotation(clip.HasRotation ? clip.Rotation!.rotations : null, keyTimes[track].rotation, frame, rest.Rotation);
                    var scale = SampleVector(clip.HasScale ? clip.Scale!.translations : null, keyTimes[track].scale, frame, rest.Scale);
                    // Keep each track's quaternion on one hemisphere so the bridge's curves do not jump.
                    if (Quaternion.Dot(previous[track], rotation) < 0) rotation = Quaternion.Negate(rotation);
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

        Console.WriteLine($"Decoded {mot.Name}: skeleton={skeletonName}, bones={bones.Count}, frames={timing.SampleCount}, rate={timing.FrameRate}, tracks={trackBones.Count}, unmatched={unmatched.Count}");
        if (unmatched.Count > 0)
            Console.WriteLine($"NOTE {unmatched.Count} animated bones are not in the skeleton: {string.Join(", ", unmatched.Take(12))}{(unmatched.Count > 12 ? ", ..." : "")}");
        Program.PrintLibraryWarnings();
        Console.WriteLine(Path.GetFullPath(outputPath));
        return 0;
    }
}
