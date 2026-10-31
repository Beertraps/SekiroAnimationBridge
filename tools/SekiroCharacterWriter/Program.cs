#nullable enable
using System.Text.Json;
using System.Text.Json.Nodes;

// Writes the files of a new Sekiro character from a template character's files and the bridge's export data.
// Each command takes a JSON job and writes a JSON report: SekiroCharacterWriter <command> <job.json> <report.json>.
// The bridge unpacks and packs the binders and their DCX; this tool reads and writes the members inside them.

const string Version = "SekiroCharacterWriter 0.3.0 (inspect, flver, tpf, msb, tae)";
if (args.Length == 1 && args[0] == "--version")
{
    Console.WriteLine(Version);
    return 0;
}
if (args.Length != 3)
{
    Console.Error.WriteLine("Usage: SekiroCharacterWriter <inspect|flver|tpf|msb|tae> <job.json> <report.json>");
    return 2;
}

try
{
    var job = JsonNode.Parse(File.ReadAllText(args[1]))!.AsObject();
    object report = args[0] switch
    {
        "inspect" => Inspect.Run(job),
        "flver" => FlverWriter.Run(job),
        "tpf" => TextureWriter.Run(job),
        "msb" => MapWriter.Run(job),
        "tae" => TaeWriter.Run(job),
        _ => throw new ArgumentException($"Unknown command {args[0]}."),
    };
    File.WriteAllText(args[2], JsonSerializer.Serialize(report, Json.Options));
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex);
    Console.Error.WriteLine($"{args[0]} failed: {ex.Message}");
    return 1;
}

static class Json
{
    public static readonly JsonSerializerOptions Options = new() { WriteIndented = false, IncludeFields = true };

    public static string Text(JsonObject job, string key) =>
        job[key]?.GetValue<string>() ?? throw new ArgumentException($"The job has no {key}.");

    public static string? OptionalText(JsonObject job, string key) => job[key]?.GetValue<string>();

    public static float[] Floats(JsonNode? node) => node!.AsArray().Select(v => v!.GetValue<float>()).ToArray();

    public static float[] V(System.Numerics.Vector3 v) => new[] { v.X, v.Y, v.Z };

    public static System.Numerics.Vector3 Vector3(JsonNode? node)
    {
        var f = Floats(node);
        return new System.Numerics.Vector3(f[0], f[1], f[2]);
    }

    public static void WriteFile(string path, byte[] data)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        File.WriteAllBytes(path, data);
    }
}
