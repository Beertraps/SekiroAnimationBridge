#nullable enable
using CUE4Parse.Encryption.Aes;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Versions;
using CUE4Parse.Utils;
using CUE4Parse_Conversion.Writers.ActorX.Structs.Animations;

namespace UnrealDecoder;

/// <summary>Checks that need no game: option parsing, asset paths, key sampling, and which native features were built.</summary>
internal static class SelfTest
{
    public static int Run()
    {
        var failures = new List<string>();
        var checks = 0;
        void Check(bool passed, string what)
        {
            checks++;
            if (!passed) failures.Add(what);
        }

        Check(Source.Engine("GAME_UE4_27") == EGame.GAME_UE4_27, "engine names parse");
        Check(Source.Engine(" game_ue5_3 ") == EGame.GAME_UE5_3, "engine names parse without case or spaces");
        Check(Throws<UsageException>(() => Source.Engine("UE4_27")), "engine names need the GAME_ prefix");
        Check(Throws<UsageException>(() => Source.Engine("GAME_NOT_A_GAME")), "unknown engine names are refused");
        Check(!Throws<Exception>(() => _ = new FAesKey("0x" + new string('0', 64))), "AES keys parse");
        Check(Throws<DirectoryNotFoundException>(() => Source.Open(new SourceOptions { Root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N")), Engine = "GAME_UE4_27" })),
              "a missing game folder is refused");

        Check(Source.ObjectPath("/Game/Hero/Run") == "/Game/Hero/Run.Run", "package paths become object paths");
        Check(Source.ObjectPath("/Game/Hero/Run.Run") == "/Game/Hero/Run.Run", "object paths stay");
        Check(SourceCommands.ExportTextPath("/Script/Engine.Skeleton'/Game/Hero/SK_Hero.SK_Hero'") == "/Game/Hero/SK_Hero.SK_Hero", "export text references give their path");
        Check(SourceCommands.Normalize("FSD/Content/Hero/SK.SK", "FSD") == "/Game/Hero/SK.SK", "project content becomes /Game");
        Check(SourceCommands.Normalize("Engine/Content/Mannequin/SK.SK", "FSD") == "/Engine/Mannequin/SK.SK", "engine content becomes /Engine");
        Check(SourceCommands.Normalize("FSD/Plugins/Hats/Content/SK.SK", "FSD") == "/Hats/SK.SK", "plugin content becomes the plugin's root");
        Check(SourceCommands.Normalize("/Game/Hero/SK.SK", "FSD") == "/Game/Hero/SK.SK", "rooted paths stay");

        // Evenly spaced keys sample one per frame, and channels without keys keep what they held.
        var turn = new FQuat(0, 0, MathF.Sqrt(0.5f), MathF.Sqrt(0.5f));
        var track = new CAnimTrack { KeyQuat = [FQuat.Identity, turn] };
        var rotation = FQuat.Identity;
        var translation = new FVector(1, 2, 3);
        var scale = FVector.OneVector;
        track.GetBoneTransform(1, 2, ref rotation, ref translation, ref scale);
        Check(MathF.Abs(rotation.Z - turn.Z) < 1e-5f && MathF.Abs(rotation.W - turn.W) < 1e-5f, "the last key samples on the last frame");
        Check(translation.X == 1 && translation.Y == 2 && translation.Z == 3, "a channel without keys keeps its value");

        // The basis is a signed permutation that reflects, as Unreal's left-handed space needs.
        var basis = Program.Basis;
        var determinant = basis[0][0] * (basis[1][1] * basis[2][2] - basis[1][2] * basis[2][1])
                          - basis[0][1] * (basis[1][0] * basis[2][2] - basis[1][2] * basis[2][0])
                          + basis[0][2] * (basis[1][0] * basis[2][1] - basis[1][1] * basis[2][0]);
        Check(determinant == -1 && basis.All(row => row.Count(value => value != 0) == 1), "the basis reflects");

        var json = Path.Combine(Path.GetTempPath(), $"UnrealDecoder-selftest-{Guid.NewGuid():N}.json");
        try
        {
            Program.WriteJson(json, new { value = 1.5f, name = "Run" });
            Check(File.ReadAllText(json) == "{\"value\":1.5,\"name\":\"Run\"}", "JSON is written without formatting");
        }
        finally
        {
            File.Delete(json);
        }

        Console.WriteLine(CUE4ParseNatives.IsFeatureAvailable("ACL")
            ? "Native ACL decoding: available"
            : "Native ACL decoding: not built; clips compressed with ACL cannot be decoded");
        if (failures.Count > 0)
        {
            foreach (var failure in failures)
                Console.Error.WriteLine($"FAILED {failure}");
            Console.Error.WriteLine($"Self-test failed: {failures.Count} of {checks} checks");
            return 1;
        }
        Console.WriteLine($"Self-test passed: {checks} checks");
        return 0;
    }

    private static bool Throws<T>(Action action) where T : Exception
    {
        try
        {
            action();
            return false;
        }
        catch (T)
        {
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
