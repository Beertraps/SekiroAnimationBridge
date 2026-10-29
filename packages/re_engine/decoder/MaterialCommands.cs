#nullable enable
using ReeLib;

namespace ReEngineDecoder;

/// <summary>Writes a material file's materials with their texture slots and parameters.</summary>
internal static class MaterialCommand
{
    public static int Export(string inputPath, string outputPath)
    {
        using var handler = Program.OpenRead(inputPath);
        var file = new MdfFile(handler);
        file.Read();
        var materials = file.Materials.Select(material => new
        {
            name = material.Name,
            shader = material.MasterMaterial,
            shadingType = material.Header.shaderType.ToString(),
            // Texture paths stay as the file stores them, without natives/x64/ and without the .tex version.
            textures = material.Textures.Select(texture => new { slot = texture.texType, path = texture.texPath }).ToArray(),
            @params = material.Parameters.Select(parameter => new
            {
                name = parameter.paramName,
                value = parameter.componentCount == 4
                    ? new[] { parameter.parameter.X, parameter.parameter.Y, parameter.parameter.Z, parameter.parameter.W }.Select(Program.Finite).ToArray()
                    : [Program.Finite(parameter.parameter.X)],
            }).ToArray(),
        }).ToArray();
        Program.WriteJson(outputPath, new { materials });
        Console.WriteLine($"Materials {Path.GetFileName(inputPath)}: {materials.Length} materials, {materials.Sum(material => material.textures.Length)} texture slots");
        Program.PrintLibraryWarnings();
        return 0;
    }
}

/// <summary>Converts a texture to DDS, keeping only the largest mip level.</summary>
internal static class TextureCommand
{
    public static int Export(string inputPath, string outputPath)
    {
        using var handler = Program.OpenRead(inputPath);
        var texture = new TexFile(handler);
        texture.Read();
        using (var stream = Program.CreateOutput(outputPath))
        {
            // TexFile.SaveAsDDS ignores its mip arguments at this REE-Lib commit, so call ConvertToDDS directly.
            texture.ConvertToDDS(new FileHandler(stream, Path.GetFullPath(outputPath)), imageIndex: 0, startMipMap: 0, maxMipCount: 1);
        }
        var header = texture.Header;
        Console.WriteLine($"Texture {Path.GetFileName(inputPath)}: {header.width}x{header.height} {header.format}, {header.mipCount} mips, {header.imageCount} images");
        Program.PrintLibraryWarnings();
        Console.WriteLine(Path.GetFullPath(outputPath));
        return 0;
    }
}
