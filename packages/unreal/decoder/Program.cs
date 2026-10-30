#nullable enable
using System.Text.Json;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using OodleDotNet;
using Serilog;
using Serilog.Core;
using Serilog.Events;

namespace UnrealDecoder;

/// <summary>
/// Reads Unreal Engine 4 and 5 games for the bridge with CUE4Parse: the skeletons, animation sequences and
/// skeletal meshes of PAK and IoStore archives, their materials and textures. Every output stays in Unreal's own
/// space and units (Z up, left-handed, centimetres); the bridge converts with the basis written into each document.
/// </summary>
internal static class Program
{
    public const string VersionLine = "UnrealDecoder 0.1.0 (scan, decode, mesh; CUE4Parse 460fc477)";

    /// <summary>
    /// Unreal is Z-up and left-handed, and its skeletal meshes face +Y with their left side on +X.
    /// Flipping Y makes the space right-handed, faces the character towards Blender's front (-Y) and keeps its left on +X.
    /// </summary>
    public static readonly int[][] Basis = [[1, 0, 0], [0, -1, 0], [0, 0, 1]];

    /// <summary>Unreal units are centimetres.</summary>
    public const double UnitScale = 0.01;

    /// <summary>Warnings CUE4Parse logs while reading, so they reach stdout as notes instead of a console log.</summary>
    public static readonly List<string> LibraryWarnings = new();

    private const string UsageText =
        "Usage: UnrealDecoder --version\n" +
        "       UnrealDecoder scan <source.json> <output.json>\n" +
        "       UnrealDecoder decode <source.json> <animation path> <output.json> [--mesh <skeletal mesh path>]\n" +
        "       UnrealDecoder mesh <source.json> <output folder> <skeletal mesh path> [<skeletal mesh path> ...]\n" +
        "       UnrealDecoder dump <source.json> <object path>\n" +
        "       UnrealDecoder selftest\n" +
        "A source.json holds root (the game folder), engine (a CUE4Parse EGame name such as GAME_UE4_27) and,\n" +
        "when the game needs them, aesKey, mappings (a .usmap file) and oodle (an Oodle library to use instead of\n" +
        "the built-in decompressor). Asset paths are package or object paths such as /Game/Hero/Run.Run.";

    private static int Main(string[] args)
    {
        // CUE4Parse logs through Serilog; keep stdout for this tool's own lines.
        Log.Logger = new LoggerConfiguration().MinimumLevel.Warning().WriteTo.Sink(new NoteSink()).CreateLogger();
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
                "scan" when args.Length == 3 => SourceCommands.Scan(args[1], args[2]),
                "decode" when args.Length == 4 => MotionCommand.Decode(args[1], args[2], args[3], null),
                "decode" when args.Length == 6 && args[4] == "--mesh" => MotionCommand.Decode(args[1], args[2], args[3], args[5]),
                "mesh" when args.Length >= 4 => MeshCommand.Export(args[1], args[2], args[3..]),
                "dump" when args.Length == 3 => Dump(args[1], args[2]),
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
            Console.Error.WriteLine($"{args[0]} failed: {OneLine(Describe(ex))}");
            return 1;
        }
    }

    private static int Usage()
    {
        Console.Error.WriteLine(UsageText);
        return 2;
    }

    /// <summary>One object with its properties as JSON, as CUE4Parse reads it: for finding out what an asset holds.</summary>
    private static int Dump(string optionsPath, string objectPath)
    {
        var options = Source.Read(optionsPath);
        using var provider = Source.Open(options);
        var loaded = provider.LoadPackageObject(Source.ObjectPath(objectPath));
        Console.WriteLine(Newtonsoft.Json.JsonConvert.SerializeObject(loaded, Newtonsoft.Json.Formatting.Indented));
        return 0;
    }

    /// <summary>The innermost message that says something, since CUE4Parse wraps parser errors.</summary>
    private static string Describe(Exception ex)
    {
        var message = ex.Message;
        for (var inner = ex.InnerException; inner != null; inner = inner.InnerException)
        {
            if (!string.IsNullOrWhiteSpace(inner.Message)) message = $"{message} ({inner.Message})";
        }
        return message;
    }

    public static string OneLine(string text) => string.Join(' ', text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries));

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

    public static float Finite(float value) => float.IsFinite(value) ? value : 0f;

    public static float[] Array3(FVector value) => [Finite(value.X), Finite(value.Y), Finite(value.Z)];

    public static float[] Array4(FQuat value) => [Finite(value.X), Finite(value.Y), Finite(value.Z), Finite(value.W)];

    public static void WriteVector(Utf8JsonWriter json, string name, FVector value)
    {
        json.WriteStartArray(name);
        json.WriteNumberValue(Finite(value.X));
        json.WriteNumberValue(Finite(value.Y));
        json.WriteNumberValue(Finite(value.Z));
        json.WriteEndArray();
    }

    public static void WriteQuaternion(Utf8JsonWriter json, string name, FQuat value)
    {
        json.WriteStartArray(name);
        json.WriteNumberValue(Finite(value.X));
        json.WriteNumberValue(Finite(value.Y));
        json.WriteNumberValue(Finite(value.Z));
        json.WriteNumberValue(Finite(value.W));
        json.WriteEndArray();
    }

    public static void WriteBasis(Utf8JsonWriter json)
    {
        json.WriteStartArray("basis");
        foreach (var row in Basis)
        {
            json.WriteStartArray();
            foreach (var value in row) json.WriteNumberValue(value);
            json.WriteEndArray();
        }
        json.WriteEndArray();
        json.WriteNumber("unitScale", UnitScale);
    }

    public static void PrintLibraryWarnings()
    {
        var distinct = LibraryWarnings.Distinct().ToList();
        foreach (var warning in distinct.Take(12))
            Console.WriteLine($"NOTE {OneLine(warning)}");
        if (distinct.Count > 12)
            Console.WriteLine($"NOTE {distinct.Count - 12} more warnings from CUE4Parse");
    }

    private sealed class NoteSink : ILogEventSink
    {
        public void Emit(LogEvent logEvent)
        {
            var message = logEvent.RenderMessage();
            if (logEvent.Exception != null) message += $": {logEvent.Exception.Message}";
            lock (LibraryWarnings) LibraryWarnings.Add(message);
        }
    }
}

internal sealed class UsageException(string message) : Exception(message);

/// <summary>What the bridge's package writes into source.json for each run.</summary>
internal sealed class SourceOptions
{
    public string Root { get; init; } = "";
    public string Engine { get; init; } = "";
    public string AesKey { get; init; } = "";
    public string Mappings { get; init; } = "";
    public string Oodle { get; init; } = "";
}

internal static class Source
{
    public static SourceOptions Read(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new UsageException($"The source options file {fullPath} does not exist.");
        return JsonSerializer.Deserialize<SourceOptions>(File.ReadAllText(fullPath), new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
               ?? throw new UsageException($"{fullPath} holds no source options.");
    }

    public static EGame Engine(string name) =>
        Enum.TryParse<EGame>(name.Trim(), true, out var game) && name.Trim().StartsWith("GAME_", StringComparison.OrdinalIgnoreCase)
            ? game
            : throw new UsageException($"{name} is not an engine version CUE4Parse knows. Use a name such as GAME_UE4_27 or GAME_UE5_3.");

    /// <summary>
    /// Mounts a game's archives in place. Nothing is downloaded: Oodle data uses CUE4Parse's built-in decompressor
    /// unless the source names an Oodle library, and an encrypted archive stays closed without its key.
    /// </summary>
    public static DefaultFileProvider Open(SourceOptions options)
    {
        if (!Directory.Exists(options.Root))
            throw new DirectoryNotFoundException($"The game folder {options.Root} does not exist.");
        var game = Engine(options.Engine);
        if (options.Oodle.Length > 0)
        {
            if (!File.Exists(options.Oodle))
                throw new FileNotFoundException($"The Oodle library {options.Oodle} does not exist.");
            OodleHelper.Initialize(new Oodle(options.Oodle));
        }
        var provider = new DefaultFileProvider(options.Root, SearchOption.AllDirectories, new VersionContainer(game), StringComparer.OrdinalIgnoreCase);
        if (options.Mappings.Length > 0)
        {
            if (!File.Exists(options.Mappings))
                throw new FileNotFoundException($"The mappings file {options.Mappings} does not exist.");
            provider.MappingsContainer = new FileUsmapTypeMappingsProvider(options.Mappings);
        }
        provider.Initialize();
        provider.Mount();
        if (options.AesKey.Length > 0)
        {
            FAesKey key;
            try
            {
                key = new FAesKey(options.AesKey.Trim());
            }
            catch (Exception)
            {
                throw new UsageException("The AES key must be 64 hexadecimal digits, with or without 0x in front.");
            }
            // Archives encrypted with the game's main key name the empty GUID.
            provider.SubmitKey(new FGuid(), key);
        }
        provider.PostMount();
        provider.LoadVirtualPaths();
        return provider;
    }

    /// <summary>The object path of a package path: /Game/Hero/Run becomes /Game/Hero/Run.Run.</summary>
    public static string ObjectPath(string path)
    {
        path = path.Trim();
        var name = path[(path.LastIndexOf('/') + 1)..];
        return name.Contains('.') ? path : $"{path}.{name}";
    }
}
