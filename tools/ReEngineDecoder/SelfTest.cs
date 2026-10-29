#nullable enable
using System.Numerics;
using System.Text.Json;
using ReeLib;
using ReeLib.Mot;

namespace ReEngineDecoder;

/// <summary>
/// Writes a small DMC5-format mot with REE-Lib, decodes it with the decode command and checks the samples,
/// so a build can be checked without game files.
/// </summary>
internal static class SelfTest
{
    public static int Run()
    {
        var folder = Path.Combine(Path.GetTempPath(), $"ReEngineDecoder-selftest-{Environment.ProcessId}");
        Directory.CreateDirectory(folder);
        try
        {
            var motPath = Path.Combine(folder, "selftest.mot.65");
            File.WriteAllBytes(motPath, WriteMot());
            var jsonPath = Path.Combine(folder, "selftest.json");
            var listPath = Path.Combine(folder, "selftest-list.json");
            using (var quiet = new StringWriter())
            {
                var stdout = Console.Out;
                Console.SetOut(quiet);
                try
                {
                    MotionCommands.ListMotions(motPath, listPath);
                    MotionCommands.Decode(motPath, 0, jsonPath, null);
                }
                finally
                {
                    Console.SetOut(stdout);
                }
            }

            using var listed = JsonDocument.Parse(File.ReadAllText(listPath));
            var entry = listed.RootElement.GetProperty("motions")[0];
            Check(entry.GetProperty("frameCount").GetInt32() == 11, "the motion list reports 11 frames");
            Check(entry.GetProperty("trackCount").GetInt32() == 1, "the motion list reports one animated bone");

            using var motion = JsonDocument.Parse(File.ReadAllText(jsonPath));
            var root = motion.RootElement;
            Check(root.GetProperty("formatVersion").GetInt32() == 2, "the motion is interchange version 2");
            Check(root.GetProperty("frameCount").GetInt32() == 11, "11 frames are sampled");
            Check(Math.Abs(root.GetProperty("frameRate").GetDouble() - 30) < 1e-6, "the frame rate is 30");
            Check(Math.Abs(root.GetProperty("duration").GetDouble() - 10.0 / 30) < 1e-6, "the duration is 10 frames");
            var bones = root.GetProperty("skeleton").GetProperty("bones");
            Check(bones.GetArrayLength() == 2 && bones[1].GetProperty("parent").GetInt32() == 0, "the skeleton keeps the parent");
            Check(root.GetProperty("trackNames")[0].GetString() == "spine", "the animated bone is spine");
            var middle = root.GetProperty("frames")[5][0];
            var translation = Floats(middle.GetProperty("translation"));
            var rotation = Floats(middle.GetProperty("rotation"));
            Check(Near(translation, [0, 1.5f, 0]), $"frame 5 translation is halfway, got {string.Join(", ", translation)}");
            var half = MathF.PI / 8;
            Check(Near(rotation, [0, MathF.Sin(half), 0, MathF.Cos(half)]), $"frame 5 rotation is 45 degrees about Y, got {string.Join(", ", rotation)}");
            var last = Floats(root.GetProperty("frames")[10][0].GetProperty("translation"));
            Check(Near(last, [0, 2, 0]), "the last frame reaches the last key");
            Console.WriteLine("Self-test passed: wrote a DMC5 mot with REE-Lib and decoded 11 frames with the expected values");
            return 0;
        }
        finally
        {
            Directory.Delete(folder, true);
        }
    }

    private static byte[] WriteMot()
    {
        var handler = new FileHandler(new MemoryStream(), "selftest.mot.65");
        var mot = new MotFile(handler);
        mot.Header.version = MotVersion.RE2_DMC5;
        mot.Header.motName = "selftest";
        mot.Header.FrameRate = 30;
        mot.Header.frameCount = 10;
        mot.Header.endFrame = 10;
        var root = new MotBone { boneName = "root", Index = 0, quaternion = Quaternion.Identity };
        var spine = new MotBone { boneName = "spine", Index = 1, translation = new Vector3(0, 1, 0), quaternion = Quaternion.Identity, Parent = root };
        mot.AddBone(root);
        mot.AddBone(spine);

        var header = new BoneClipHeader(MotVersion.RE2_DMC5) { boneIndex = 1, boneName = "spine", trackFlags = TrackFlag.Translation | TrackFlag.Rotation };
        var turn = Quaternion.CreateFromAxisAngle(Vector3.UnitY, MathF.PI / 2);
        mot.BoneClips.Add(new BoneMotionClip(header)
        {
            Translation = new Track(MotVersion.RE2_DMC5, TrackValueType.Vector3)
            {
                translations = [new Vector3(0, 1, 0), new Vector3(0, 2, 0)],
                frameIndexes = [0, 10],
                frameRate = 30,
                maxFrame = 10,
            },
            Rotation = new Track(MotVersion.RE2_DMC5, TrackValueType.Quaternion)
            {
                rotations = [Quaternion.Identity, turn],
                frameIndexes = [0, 10],
                frameRate = 30,
                maxFrame = 10,
            },
        });
        if (!mot.Write()) throw new InvalidOperationException("REE-Lib could not write the test motion.");
        return ((MemoryStream)handler.Stream).ToArray();
    }

    private static float[] Floats(JsonElement array) => array.EnumerateArray().Select(value => value.GetSingle()).ToArray();

    private static bool Near(float[] actual, float[] expected) =>
        actual.Length == expected.Length && actual.Zip(expected).All(pair => MathF.Abs(pair.First - pair.Second) < 1e-4f);

    private static void Check(bool condition, string what)
    {
        if (!condition) throw new InvalidOperationException($"Self-test failed: {what}.");
    }
}
