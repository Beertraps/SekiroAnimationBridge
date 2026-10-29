#nullable enable
using System.Numerics;
using System.Text.Json;
using ReeLib;
using ReeLib.Common;
using ReeLib.via;

namespace ReEngineDecoder;

/// <summary>
/// Reads RE Engine files (Devil May Cry 5, Resident Evil 2) for the bridge: PAK listing and extraction,
/// motion lists and motions, meshes, materials and textures. Every output stays in the game's own
/// space and units; the bridge converts with the basis written into each document.
/// </summary>
internal static class Program
{
    public const string VersionLine = "ReEngineDecoder 0.1.0 (motlist, decode, mesh, mdf2, tex, pak)";

    /// <summary>RE Engine is Y-up and right-handed; this maps its axes to Blender's Z-up axes.</summary>
    public static readonly int[][] Basis = [[1, 0, 0], [0, 0, -1], [0, 1, 0]];

    /// <summary>Warnings REE-Lib reports while reading, so they reach stdout as notes instead of the console log.</summary>
    public static readonly List<string> LibraryWarnings = new();

    private const string UsageText =
        "Usage: ReEngineDecoder --version\n" +
        "       ReEngineDecoder pak-list <paths.list> <output.json> <regex> <pak...>\n" +
        "       ReEngineDecoder pak-extract <paths.list|-> <output-dir> <wanted.txt> <pak...>\n" +
        "       ReEngineDecoder motlist <file.motlist|file.mot> <output.json>\n" +
        "       ReEngineDecoder decode <file.motlist|file.mot> <index> <output.json> [--skeleton <file.mesh|file.fbxskel>]\n" +
        "       ReEngineDecoder mesh <file.mesh> <output-stem>\n" +
        "       ReEngineDecoder mdf2 <file.mdf2> <output.json>\n" +
        "       ReEngineDecoder tex <file.tex> <output.dds>\n" +
        "       ReEngineDecoder selftest";

    private static int Main(string[] args)
    {
        // REE-Lib writes its log to the console by default; keep stdout for this tool's own lines.
        Log.LogCallback = (level, message) =>
        {
            if (level >= Log.LogLevel.Warn) LibraryWarnings.Add(message);
        };
        if (args.Length == 1 && args[0] == "--version")
        {
            Console.WriteLine(VersionLine);
            return 0;
        }
        if (args.Length == 0)
            return Usage();
        try
        {
            return args[0] switch
            {
                "pak-list" when args.Length >= 5 => PakCommands.List(args[1], args[2], args[3], args[4..]),
                "pak-extract" when args.Length >= 5 => PakCommands.Extract(args[1], args[2], args[3], args[4..]),
                "motlist" when args.Length == 3 => MotionCommands.ListMotions(args[1], args[2]),
                "decode" when args.Length == 4 => MotionCommands.Decode(args[1], ParseIndex(args[2]), args[3], null),
                "decode" when args.Length == 6 && args[4] == "--skeleton" => MotionCommands.Decode(args[1], ParseIndex(args[2]), args[3], args[5]),
                "mesh" when args.Length == 3 => MeshCommand.Export(args[1], args[2]),
                "mdf2" when args.Length == 3 => MaterialCommand.Export(args[1], args[2]),
                "tex" when args.Length == 3 => TextureCommand.Export(args[1], args[2]),
                "selftest" when args.Length == 1 => SelfTest.Run(),
                _ => Usage(),
            };
        }
        catch (UsageException ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"{args[0]} failed: {OneLine(ex.Message)}");
            return 1;
        }
    }

    private static int Usage()
    {
        Console.Error.WriteLine(UsageText);
        return 2;
    }

    private static int ParseIndex(string text) =>
        int.TryParse(text, out var index) && index >= 0 ? index : throw new UsageException("The motion index must be a number of 0 or more.");

    public static string OneLine(string text) => string.Join(' ', text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries));

    /// <summary>Reads a whole file into memory: REE-Lib's own path constructor opens files for writing.</summary>
    public static FileHandler OpenRead(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException($"{fullPath} does not exist.");
        // The file version in the name (.mesh.1808282334) selects the layout, so keep the path.
        return new FileHandler(new MemoryStream(File.ReadAllBytes(fullPath)), fullPath);
    }

    public static FileStream CreateOutput(string path)
    {
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        return File.Create(fullPath);
    }

    public static void WriteJson(string path, object document)
    {
        using var stream = CreateOutput(path);
        JsonSerializer.Serialize(stream, document);
    }

    /// <summary>The last number in a file name such as pl0100.mesh.1808282334, or 0.</summary>
    public static int FileVersion(string path)
    {
        var extension = Path.GetExtension(path).TrimStart('.');
        return int.TryParse(extension, out var version) ? version : 0;
    }

    public static float Finite(float value) => float.IsFinite(value) ? value : 0f;

    public static float[] Array3(Vector3 value) => [Finite(value.X), Finite(value.Y), Finite(value.Z)];

    public static float[] Array4(Quaternion value) => [Finite(value.X), Finite(value.Y), Finite(value.Z), Finite(value.W)];

    public static void WriteVector(Utf8JsonWriter json, string name, Vector3 value)
    {
        json.WriteStartArray(name);
        json.WriteNumberValue(Finite(value.X));
        json.WriteNumberValue(Finite(value.Y));
        json.WriteNumberValue(Finite(value.Z));
        json.WriteEndArray();
    }

    public static void WriteQuaternion(Utf8JsonWriter json, string name, Quaternion value)
    {
        json.WriteStartArray(name);
        json.WriteNumberValue(Finite(value.X));
        json.WriteNumberValue(Finite(value.Y));
        json.WriteNumberValue(Finite(value.Z));
        json.WriteNumberValue(Finite(value.W));
        json.WriteEndArray();
    }

    public static void PrintLibraryWarnings()
    {
        foreach (var warning in LibraryWarnings.Distinct())
            Console.WriteLine($"NOTE {OneLine(warning)}");
    }
}

internal sealed class UsageException(string message) : Exception(message);

/// <summary>A rest-pose bone in local space, as a skeleton source gives it.</summary>
internal sealed record RestBone(string Name, int Parent, Vector3 Translation, Quaternion Rotation, Vector3 Scale, uint Hash);

internal static class Skeletons
{
    /// <summary>Orders bones so every parent comes before its children, keeping the file order otherwise.</summary>
    public static List<RestBone> ParentFirst(IReadOnlyList<RestBone> bones, out int[] newIndex)
    {
        var order = new List<int>(bones.Count);
        var state = new byte[bones.Count];
        void Visit(int index)
        {
            if (state[index] == 2) return;
            if (state[index] == 1) throw new InvalidDataException($"The skeleton has a parent loop at bone {bones[index].Name}.");
            state[index] = 1;
            var parent = bones[index].Parent;
            if (parent >= 0 && parent < bones.Count) Visit(parent);
            state[index] = 2;
            order.Add(index);
        }
        for (var index = 0; index < bones.Count; index++) Visit(index);

        newIndex = new int[bones.Count];
        for (var position = 0; position < order.Count; position++) newIndex[order[position]] = position;
        var map = newIndex;
        return order.Select(index =>
        {
            var bone = bones[index];
            var parent = bone.Parent >= 0 && bone.Parent < bones.Count ? map[bone.Parent] : -1;
            return bone with { Parent = parent };
        }).ToList();
    }

    public static (Vector3 translation, Quaternion rotation, Vector3 scale) Decompose(mat4 value)
    {
        // RE Engine stores row-vector matrices with the translation in the fourth row, as System.Numerics does.
        var matrix = new Matrix4x4(
            value.m00, value.m01, value.m02, value.m03,
            value.m10, value.m11, value.m12, value.m13,
            value.m20, value.m21, value.m22, value.m23,
            value.m30, value.m31, value.m32, value.m33);
        if (Matrix4x4.Decompose(matrix, out var scale, out var rotation, out var translation))
            return (translation, Quaternion.Normalize(rotation), scale);
        var axisX = new Vector3(matrix.M11, matrix.M12, matrix.M13);
        var axisY = new Vector3(matrix.M21, matrix.M22, matrix.M23);
        var axisZ = new Vector3(matrix.M31, matrix.M32, matrix.M33);
        scale = new Vector3(axisX.Length(), axisY.Length(), axisZ.Length());
        var normalized = Matrix4x4.Identity;
        if (scale.X > 0 && scale.Y > 0 && scale.Z > 0)
        {
            normalized.M11 = axisX.X / scale.X; normalized.M12 = axisX.Y / scale.X; normalized.M13 = axisX.Z / scale.X;
            normalized.M21 = axisY.X / scale.Y; normalized.M22 = axisY.Y / scale.Y; normalized.M23 = axisY.Z / scale.Y;
            normalized.M31 = axisZ.X / scale.Z; normalized.M32 = axisZ.Y / scale.Z; normalized.M33 = axisZ.Z / scale.Z;
        }
        return (new Vector3(matrix.M41, matrix.M42, matrix.M43), Quaternion.Normalize(Quaternion.CreateFromRotationMatrix(normalized)), scale);
    }

    public static Matrix4x4 ToMatrix(mat4 value) => new(
        value.m00, value.m01, value.m02, value.m03,
        value.m10, value.m11, value.m12, value.m13,
        value.m20, value.m21, value.m22, value.m23,
        value.m30, value.m31, value.m32, value.m33);

    public static List<RestBone> FromMesh(MeshFile mesh)
    {
        var data = mesh.BoneData ?? throw new InvalidDataException("The mesh has no skeleton.");
        return data.Bones.Select(bone =>
        {
            var (translation, rotation, scale) = Decompose(bone.localTransform);
            return new RestBone(bone.name, bone.parentIndex, translation, rotation, scale, MurMur3HashUtils.GetHash(bone.name ?? string.Empty));
        }).ToList();
    }

    public static List<RestBone> FromFbxSkel(FbxSkelFile skeleton) =>
        skeleton.Bones.Select(bone => new RestBone(bone.name, bone.parentIndex, bone.position, Quaternion.Normalize(bone.rotation),
            bone.scale == Vector3.Zero ? Vector3.One : bone.scale, MurMur3HashUtils.GetHash(bone.name))).ToList();

    public static List<RestBone> FromMot(ReeLib.MotFile mot) =>
        mot.Bones.Select(bone => new RestBone(bone.boneName, bone.Parent == null ? -1 : mot.Bones.IndexOf(bone.Parent), bone.translation,
            Quaternion.Normalize(bone.quaternion), Vector3.One,
            string.IsNullOrEmpty(bone.boneName) ? bone.boneHash : MurMur3HashUtils.GetHash(bone.boneName))).ToList();

    /// <summary>Reads a skeleton from a mesh or an fbxskel file, chosen by the file name.</summary>
    public static (string name, List<RestBone> bones) Load(string path)
    {
        var fileName = Path.GetFileName(path).ToLowerInvariant();
        var stem = fileName.Split('.')[0];
        using var handler = Program.OpenRead(path);
        if (fileName.Contains(".fbxskel"))
        {
            var skeleton = new FbxSkelFile(handler);
            skeleton.Read();
            return (stem, FromFbxSkel(skeleton));
        }
        if (fileName.Contains(".mesh"))
        {
            var mesh = new MeshFile(handler);
            mesh.Read();
            return (stem, FromMesh(mesh));
        }
        throw new UsageException("--skeleton needs a .mesh or .fbxskel file.");
    }
}
