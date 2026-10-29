param(
    [string]$SoulsAssetPipelineRoot = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\SoulsAssetPipeline"),
    [string]$OutputDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\decoder"),
    [string]$ArtifactsDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\build")
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the .NET 9 SDK before building the decoder. The runtime alone cannot build it.'
}
$installedSdks = @(& dotnet --list-sdks)
if (-not ($installedSdks | Where-Object { $_ -match '^9\.' })) {
    throw 'The .NET 9 SDK was not found. Install the SDK (not only the runtime), then run build_decoder.cmd again.'
}
$repository = "https://github.com/Meowmaritus/SoulsAssetPipeline.git"
$commit = "d11caf989c917c7a43e2c7559915b1c5af218153"
$project = Join-Path $PSScriptRoot "SekiroMotionDecoder.csproj"
$sapProject = Join-Path $SoulsAssetPipelineRoot "SoulsAssetPipeline\SoulsAssetPipeline.csproj"

if (-not (Test-Path -LiteralPath $sapProject)) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required to fetch SoulsAssetPipeline. Install Git or pass -SoulsAssetPipelineRoot pointing to a checkout at $commit."
    }
    if (Test-Path -LiteralPath $SoulsAssetPipelineRoot) {
        throw "The path '$SoulsAssetPipelineRoot' exists but does not contain SoulsAssetPipeline.csproj. Pass the root of the correct checkout."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $SoulsAssetPipelineRoot) | Out-Null
    # Under %LOCALAPPDATA%, Git for Windows refuses some generated Havok class file names unless long paths are on.
    git clone --config core.longpaths=true $repository $SoulsAssetPipelineRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not clone SoulsAssetPipeline." }
    $clonedForBridge = $true
} else {
    $clonedForBridge = $false
}

$head = (git -C $SoulsAssetPipelineRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not read the SoulsAssetPipeline commit." }
if ($head -ne $commit) {
    if (-not $clonedForBridge) {
        throw "SoulsAssetPipeline at '$SoulsAssetPipelineRoot' is $head, but this decoder is pinned to $commit. Use a separate checkout path to avoid changing that repository."
    }
    git -C $SoulsAssetPipelineRoot checkout $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out the pinned SoulsAssetPipeline commit $commit." }
}

# Framework-dependent: the bridge runs it with its shared .NET runtime (tools\prepare_dotnet_runtime.cmd).
dotnet publish $project -c Release -r win-x64 --self-contained false `
    --artifacts-path $ArtifactsDirectory `
    -p:SoulsAssetPipelineProject="$sapProject" `
    -o $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Decoder build failed." }
Write-Host "Decoder ready: $(Join-Path $OutputDirectory 'SekiroMotionDecoder.exe')"
