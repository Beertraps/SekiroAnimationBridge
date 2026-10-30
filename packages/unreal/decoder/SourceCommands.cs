#nullable enable
using System.Diagnostics;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.AssetRegistry;
using CUE4Parse.UE4.AssetRegistry.Objects;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.VirtualFileSystem;

namespace UnrealDecoder;

/// <summary>One skeleton, animation sequence or skeletal mesh of a game, by its object path.</summary>
internal sealed class AssetEntry
{
    public string Kind { get; set; } = "";
    public string Path { get; set; } = "";
    public string Name { get; set; } = "";
    public string Skeleton { get; set; } = "";
    public string Archive { get; set; } = "";
    public int? Frames { get; set; }
    public float? Length { get; set; }
    public bool? Additive { get; set; }
    public bool? RootMotion { get; set; }
}

/// <summary>
/// Lists the characters of a game without loading them: skeletons, the animation sequences that play on each,
/// and the skeletal meshes that use each. The cooked asset registry names them with their skeleton; a game
/// without one is read from its package headers, which takes longer.
/// </summary>
internal static class SourceCommands
{
    private static readonly Dictionary<string, string> Kinds = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Skeleton"] = "skeleton", ["AnimSequence"] = "animation", ["SkeletalMesh"] = "mesh",
    };

    // Asset registry tags of a clip's length, by engine version.
    private static readonly string[] FrameTags = ["NumFrames", "NumberOfSampledKeys", "NumberOfKeys", "Number of Frames"];
    private static readonly string[] LengthTags = ["SequenceLength", "PlayLength", "Length"];

    public static int Scan(string optionsPath, string outputPath)
    {
        var options = Source.Read(optionsPath);
        var clock = Stopwatch.StartNew();
        using var provider = Source.Open(options);
        var project = provider.ProjectName;
        var assets = new Dictionary<string, AssetEntry>(StringComparer.OrdinalIgnoreCase);
        var registries = provider.Files.Keys.Where(key => key.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)).ToList();
        foreach (var registry in registries)
        {
            try
            {
                ReadRegistry(provider, registry, project, assets);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"NOTE {registry} could not be read: {Program.OneLine(ex.Message)}");
            }
        }

        // Without a registry, or with one whose tags were filtered when the game was cooked, read package headers.
        var headerScan = !assets.Values.Any(a => a.Kind == "animation");
        if (headerScan)
        {
            Console.WriteLine(registries.Count == 0
                ? "No asset registry in the archives; reading package headers"
                : "The asset registry lists no animation sequences; reading package headers");
            ReadHeaders(provider, project, assets);
        }
        var unassigned = assets.Values.Where(a => a.Kind != "skeleton" && a.Skeleton.Length == 0).ToList();
        if (unassigned.Count > 0)
        {
            Console.WriteLine($"Finding the skeletons of {unassigned.Count} assets from their package headers");
            var failures = new Dictionary<string, (int Count, string Message)>();
            foreach (var asset in unassigned)
                asset.Skeleton = SkeletonOf(provider, asset.Path, project, failures);
            // Headers that cannot be read usually mean the wrong engine version, or a game that needs a mappings file.
            if (failures.Count > 0)
            {
                var common = failures.Values.MaxBy(failure => failure.Count);
                Console.WriteLine($"NOTE {failures.Values.Sum(failure => failure.Count)} of {unassigned.Count} package headers could not be read, " +
                                  $"so their assets name no skeleton. {common.Count} of them fail like this: {common.Message}");
            }
        }
        // The archive that holds each package, so the bridge can tell when a game update changes a character.
        foreach (var asset in assets.Values)
        {
            var package = asset.Path.Contains('.') ? asset.Path[..asset.Path.LastIndexOf('.')] : asset.Path;
            if (provider.TryGetGameFile(package + ".uasset", out var file) && file is VfsEntry entry)
                asset.Archive = entry.Vfs.Name;
        }

        // Only encrypted archives wait for a key. CUE4Parse never mounts global.utoc as an archive: it reads it as shared data.
        var closed = provider.UnloadedVfs.Where(vfs => vfs.IsEncrypted).Select(vfs => vfs.Name)
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase).ToArray();
        var ordered = assets.Values.OrderBy(a => a.Path, StringComparer.OrdinalIgnoreCase).ToList();
        Program.WriteJson(outputPath, new
        {
            format = "unreal-scan",
            formatVersion = 1,
            project,
            engine = provider.Versions.Game.ToString(),
            mounted = provider.MountedVfs.Count,
            closed,
            requiredKeys = provider.RequiredKeys.Select(guid => guid.ToString()).ToArray(),
            files = provider.Files.Count,
            registries,
            headerScan,
            skeletons = ordered.Where(a => a.Kind == "skeleton").Select(a => new { path = a.Path, name = a.Name, archive = a.Archive }).ToArray(),
            animations = ordered.Where(a => a.Kind == "animation").Select(a => new
            {
                path = a.Path, name = a.Name, skeleton = a.Skeleton, archive = a.Archive, frames = a.Frames, length = a.Length,
                additive = a.Additive, rootMotion = a.RootMotion,
            }).ToArray(),
            meshes = ordered.Where(a => a.Kind == "mesh").Select(a => new { path = a.Path, name = a.Name, skeleton = a.Skeleton, archive = a.Archive }).ToArray(),
        });
        Console.WriteLine($"Scanned {project}: {provider.MountedVfs.Count} archives, {provider.Files.Count} files, " +
                          $"{ordered.Count(a => a.Kind == "skeleton")} skeletons, {ordered.Count(a => a.Kind == "animation")} animations, " +
                          $"{ordered.Count(a => a.Kind == "mesh")} skeletal meshes in {clock.Elapsed.TotalSeconds:0.0} s");
        if (closed.Length > 0)
            Console.WriteLine($"NOTE {closed.Length} archives stay closed without their AES key: {string.Join(", ", closed.Take(6))}{(closed.Length > 6 ? ", ..." : "")}");
        Program.PrintLibraryWarnings();
        Console.WriteLine(Path.GetFullPath(outputPath));
        return 0;
    }

    private static void ReadRegistry(IFileProvider provider, string path, string project, Dictionary<string, AssetEntry> assets)
    {
        if (!provider.TryCreateReader(path, out var reader))
            throw new InvalidDataException("it is not in the mounted archives");
        using (reader)
        {
            var state = new FAssetRegistryState(reader);
            foreach (var data in state.PreallocatedAssetDataBuffers)
            {
                if (!Kinds.TryGetValue(data.AssetClass.Text, out var kind)) continue;
                var objectPath = Normalize(data.ObjectPath, project);
                var entry = new AssetEntry { Kind = kind, Path = objectPath, Name = data.AssetName.Text };
                var tags = data.TagsAndValues ?? new Dictionary<FName, string>();
                string? Tag(params string[] names) =>
                    names.Select(name => tags.FirstOrDefault(pair => pair.Key.Text.Equals(name, StringComparison.OrdinalIgnoreCase)).Value)
                        .FirstOrDefault(value => !string.IsNullOrEmpty(value));
                if (kind != "skeleton")
                    entry.Skeleton = Normalize(ExportTextPath(Tag("Skeleton") ?? ""), project);
                if (kind == "animation")
                {
                    if (int.TryParse(Tag(FrameTags), out var frames)) entry.Frames = frames;
                    if (float.TryParse(Tag(LengthTags), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var length)) entry.Length = length;
                    var additive = Tag("AdditiveAnimType");
                    if (additive != null) entry.Additive = !additive.EndsWith("AAT_None", StringComparison.OrdinalIgnoreCase);
                    var rootMotion = Tag("bEnableRootMotion");
                    if (rootMotion != null) entry.RootMotion = rootMotion.Equals("True", StringComparison.OrdinalIgnoreCase);
                }
                assets[objectPath] = entry;
            }
        }
    }

    /// <summary>The classes of every package's exports, for games without an asset registry.</summary>
    private static void ReadHeaders(IFileProvider provider, string project, Dictionary<string, AssetEntry> assets)
    {
        var packages = provider.Files.Keys.Where(key => key.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)).ToList();
        var failed = 0;
        for (var index = 0; index < packages.Count; index++)
        {
            if (index % 5000 == 0)
                Console.WriteLine($"Reading package headers {index}/{packages.Count}");
            try
            {
                if (!provider.TryLoadPackage(packages[index], out var package)) continue;
                for (var export = 0; export < package.ExportMapLength; export++)
                {
                    var resolved = package.ResolvePackageIndex(new FPackageIndex(package, export + 1));
                    var className = resolved?.Class?.Name.Text ?? "";
                    if (resolved == null || !Kinds.TryGetValue(className, out var kind)) continue;
                    var objectPath = Normalize(resolved.GetPathName(), project);
                    assets.TryAdd(objectPath, new AssetEntry
                    {
                        Kind = kind, Path = objectPath, Name = resolved.Name.Text,
                        Skeleton = kind == "skeleton" ? "" : ImportedSkeleton(package, project),
                    });
                }
            }
            catch (Exception)
            {
                failed++;
            }
        }
        if (failed > 0)
            Console.WriteLine($"NOTE {failed} package headers could not be read");
    }

    /// <summary>
    /// The skeleton of one asset. A package that cannot be read is counted by the kind of error, with the first message
    /// as the example, since CUE4Parse names the package in many messages.
    /// </summary>
    private static string SkeletonOf(IFileProvider provider, string objectPath, string project, Dictionary<string, (int Count, string Message)> failures)
    {
        try
        {
            // LoadPackage, unlike TryLoadPackage, keeps CUE4Parse's reason, such as a missing mappings file.
            return ImportedSkeleton(provider.LoadPackage(objectPath[..objectPath.LastIndexOf('.')]), project);
        }
        catch (Exception ex)
        {
            var kind = ex.GetType().FullName ?? "";
            failures[kind] = failures.TryGetValue(kind, out var seen) ? (seen.Count + 1, seen.Message) : (1, Program.OneLine(ex.Message));
            return "";
        }
    }

    /// <summary>The skeleton an animation or mesh package imports; an asset uses one skeleton.</summary>
    private static string ImportedSkeleton(IPackage package, string project)
    {
        for (var import = 0; import < package.ImportMapLength; import++)
        {
            var resolved = package.ResolvePackageIndex(new FPackageIndex(package, -(import + 1)));
            if (resolved?.Class?.Name.Text.Equals("Skeleton", StringComparison.OrdinalIgnoreCase) == true)
                return Normalize(resolved.GetPathName(), project);
        }
        return "";
    }

    /// <summary>The path inside an export text reference: Skeleton'/Game/Hero/SK_Hero.SK_Hero' gives /Game/Hero/SK_Hero.SK_Hero.</summary>
    public static string ExportTextPath(string value)
    {
        var start = value.IndexOf('\'');
        var end = value.LastIndexOf('\'');
        return start >= 0 && end > start ? value[(start + 1)..end] : value.Trim();
    }

    /// <summary>
    /// A path in the form the game's own references use: Hero/Content/Characters/SK.SK becomes /Game/Characters/SK.SK,
    /// and a plugin's Content folder becomes /PluginName.
    /// </summary>
    public static string Normalize(string path, string project)
    {
        path = path.Replace('\\', '/').Trim();
        if (path.Length == 0 || path.StartsWith('/')) return path;
        var parts = path.Split('/');
        var content = Array.FindIndex(parts, part => part.Equals("Content", StringComparison.OrdinalIgnoreCase));
        if (content <= 0) return "/" + path;
        var rest = string.Join('/', parts[(content + 1)..]);
        var owner = parts[content - 1];
        if (content == 1 && owner.Equals(project, StringComparison.OrdinalIgnoreCase)) return "/Game/" + rest;
        if (content == 1 && owner.Equals("Engine", StringComparison.OrdinalIgnoreCase)) return "/Engine/" + rest;
        return $"/{owner}/{rest}";
    }
}
