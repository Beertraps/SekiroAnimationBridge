# Credits

Animation Bridge stands on the work of the FromSoftware modding community and of several open-source projects. Release ZIPs include two of them in binary form: the prebuilt decoder (SoulsAssetPipeline with its libraries and the .NET runtime) and uv. Everything else is downloaded on the first start or comes from your own installation. Each component keeps its own license terms.

## FromSoftware file formats

- **[Soulstruct](https://github.com/Grimrukh/soulstruct)** by Scott Mooney (Grimrukh) — DCX compression, binders, FLVER models and MTD/MATBIN materials. GPL-3.0-or-later (package metadata). Installed into the conversion Python on the first start, or by `tools\setup_writer.cmd`.
- **[Soulstruct Havok](https://github.com/Grimrukh/soulstruct-havok)** by Scott Mooney (Grimrukh) — the Havok packfile and tagfile classes that write each game's animation HKX and read it back for the export check. The bridge's `havok_compat.py` adjusts some of them at run time; the installed package is not modified. GPL-3.0-or-later (package metadata).
- **CompressAnim.exe**, distributed with Soulstruct Havok — spline compression of exported animations. SoulsAssetPipeline's build places another copy next to the decoder; release ZIPs leave it out because decoding does not use it.
- **[SoulsAssetPipeline](https://github.com/Meowmaritus/SoulsAssetPipeline)** by Meowmaritus — Havok animation and skeleton decoding in the C# decoder. Its repository includes **Havoc** and a copy of **SoulsFormats**. GPL-3.0. Release ZIPs include the decoder that the release workflow builds from a pinned commit; `tools\SekiroMotionDecoder\build_decoder.cmd` builds the same.
- **[SoulsFormats](https://github.com/JKAnderson/SoulsFormats)** by JKAnderson — the .NET format library at the core of SoulsAssetPipeline. GPL-3.0.
- **[WitchyBND](https://github.com/ividyon/WitchyBND)** by ividyon — recommended for packing exported HKX files into game binders. Not used by the bridge itself. GPL-3.0.

## Runtimes and libraries

- **[Blender](https://www.blender.org/)** — scene import, editing, sampling and the optional retarget add-on. GPL-2.0-or-later. Installed separately.
- **[uv](https://github.com/astral-sh/uv)** by Astral — included in release ZIPs; downloads Python and the pinned libraries on the first start. MIT or Apache-2.0; its MIT license is in `tools/uv/LICENSE-MIT`.
- **[Python](https://www.python.org/)** — the conversion environment and the UI server. uv downloads a [python-build-standalone](https://github.com/astral-sh/python-build-standalone) build of Python 3.13. PSF License.
- **[NumPy](https://numpy.org/)** — geometry and animation arrays. BSD-3-Clause and bundled terms.
- Soulstruct's own dependencies, installed with it: [SciPy](https://scipy.org/) (BSD-3-Clause), [constrata](https://github.com/Grimrukh/constrata) by Grimrukh (MIT), [python-zstandard](https://github.com/indygreg/python-zstandard) (BSD-3-Clause), Rich, Typer, frozendict, colorama and their dependencies.
- **[.NET 9](https://dotnet.microsoft.com/)** — the decoder runtime, included with the decoder. MIT.
- Libraries that SoulsAssetPipeline uses, included with the decoder: [AssimpNet](https://github.com/assimp/assimp-net) and TeximpNet (MIT) with the native [Assimp](https://github.com/assimp/assimp) (BSD-3-Clause), [FreeImage](https://freeimage.sourceforge.io/) (FreeImage Public License or GPL) and [NVIDIA Texture Tools](https://github.com/castano/nvidia-texture-tools) (MIT) libraries; [BouncyCastle.Cryptography](https://github.com/bcgit/bc-csharp) (MIT); DrSwizzler; and [ZstdNet](https://github.com/skbkontur/ZstdNet) (BSD-3-Clause) with [zstd](https://github.com/facebook/zstd) (BSD or GPL-2.0).

## Not distributed

- **Oodle** (`oo2core_6_win64.dll`) by RAD Game Tools / Epic Games decompresses KRAK DCX archives. The bridge loads it from your game installation or from Soulstruct's package, and never copies it into its releases.
- Game files, models, textures and animations stay on your computer. No game data is included in this project.

Animation Bridge is not affiliated with or endorsed by FromSoftware, its publishers, or Havok. Game names are trademarks of their owners.
