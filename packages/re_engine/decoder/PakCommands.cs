#nullable enable
using System.Text.RegularExpressions;
using ReeLib;
using ReeLib.Pak;

namespace ReEngineDecoder;

/// <summary>
/// Lists and extracts files from a game's PAK files. PAKs store only path hashes, so the paths come from a list
/// file. The PAKs are given base first and patches after; a file in a later PAK replaces the same path in an earlier one.
/// </summary>
internal static class PakCommands
{
    public static int List(string listPath, string outputPath, string pattern, string[] paks)
    {
        CheckPaks(paks);
        Regex filter;
        try
        {
            filter = new Regex(pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        }
        catch (ArgumentException ex)
        {
            throw new UsageException($"The path pattern is not a valid regular expression: {ex.Message}");
        }
        var wanted = new Dictionary<ulong, string>();
        foreach (var line in File.ReadLines(listPath))
        {
            var path = NormalizePath(line);
            if (path.Length > 0 && filter.IsMatch(path.ToLowerInvariant()))
                wanted.TryAdd(PakUtils.GetFilepathHash(path), path);
        }

        var found = new Dictionary<ulong, (string path, long size)>();
        foreach (var pak in NewestFirst(paks))
        {
            using var file = new PakFile { filepath = pak };
            file.ReadContents(pak, wanted);
            foreach (var entry in file.Entries)
            {
                if (entry.path != null)
                    found.TryAdd(entry.pathHash, (entry.path, entry.decompressedSize));
            }
        }

        Program.WriteJson(outputPath, new
        {
            files = found.Values.OrderBy(item => item.path, StringComparer.Ordinal).Select(item => new { item.path, item.size }).ToArray(),
            pakCount = paks.Length,
            listed = wanted.Count,
        });
        Console.WriteLine($"Found {found.Count} of {wanted.Count} matching listed paths in {paks.Length} PAK files");
        return 0;
    }

    public static int Extract(string listPath, string outputDirectory, string wantedPath, string[] paks)
    {
        CheckPaks(paks);
        if (listPath != "-" && !File.Exists(listPath))
            throw new FileNotFoundException($"{listPath} does not exist.");
        var root = Path.GetFullPath(outputDirectory);
        foreach (var pak in paks)
        {
            var gameFolder = Path.GetDirectoryName(Path.GetFullPath(pak))!;
            if (IsInside(root, gameFolder))
                throw new InvalidOperationException($"Refusing to extract into the game folder {gameFolder}. Choose a cache folder outside it.");
        }

        // The PAK hash ignores case, so the list file is not needed to find a path; it stays in the
        // command line so both PAK commands take the same inputs.
        var remaining = new Dictionary<ulong, string>();
        foreach (var line in File.ReadLines(wantedPath))
        {
            var path = NormalizePath(line);
            if (path.Length == 0) continue;
            if (Path.IsPathRooted(path) || !IsInside(Path.GetFullPath(Path.Combine(root, path)), root))
                throw new InvalidDataException($"{path} is not a path inside the PAK files.");
            remaining.TryAdd(PakUtils.GetFilepathHash(path), path);
        }

        var extracted = 0;
        foreach (var pak in NewestFirst(paks))
        {
            if (remaining.Count == 0) break;
            using var file = new PakFile { filepath = pak };
            file.ReadContents(pak, remaining);
            foreach (var entry in file.Entries)
            {
                if (entry.path == null || !remaining.Remove(entry.pathHash)) continue;
                using (var output = Program.CreateOutput(Path.Combine(root, entry.path)))
                    file.Read(entry, output);
                extracted++;
            }
        }

        foreach (var path in remaining.Values.OrderBy(path => path, StringComparer.Ordinal))
            Console.WriteLine($"MISSING {path}");
        Console.WriteLine($"Extracted {extracted} files");
        return 0;
    }

    private static void CheckPaks(string[] paks)
    {
        foreach (var pak in paks)
        {
            if (!File.Exists(pak))
                throw new FileNotFoundException($"PAK file {pak} does not exist.");
        }
    }

    private static IEnumerable<string> NewestFirst(string[] paks) => Enumerable.Reverse(paks).Select(Path.GetFullPath);

    private static string NormalizePath(string line) => line.Trim().Replace('\\', '/');

    private static bool IsInside(string path, string folder)
    {
        var prefix = Path.TrimEndingDirectorySeparator(Path.GetFullPath(folder)) + Path.DirectorySeparatorChar;
        var full = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path)) + Path.DirectorySeparatorChar;
        return full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }
}
