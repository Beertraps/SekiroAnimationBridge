param(
    [string]$CUE4ParseRoot = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\CUE4Parse"),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\tools\unreal-decoder'),
    [string]$ArtifactsDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\unreal-build"),
    # Builds without CUE4Parse's native library even when CMake is installed. Clips compressed with ACL then cannot be decoded.
    [switch]$SkipNatives
)

$ErrorActionPreference = "Stop"
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the .NET 10 SDK before building the Unreal decoder. The runtime alone cannot build it.'
}
$installedSdks = @(& dotnet --list-sdks)
if (-not ($installedSdks | Where-Object { $_ -match '^(\d+)\.' -and [int]$Matches[1] -ge 10 })) {
    throw 'The .NET 10 SDK was not found. CUE4Parse needs it. Install the SDK (not only the runtime), then run build_decoder.cmd again.'
}
$repository = "https://github.com/FabianFG/CUE4Parse.git"
$commit = "460fc477bad0f9db3cfc387365a6699ee246377e"
$project = Join-Path $PSScriptRoot "UnrealDecoder.csproj"
$libProject = Join-Path $CUE4ParseRoot "CUE4Parse\CUE4Parse.csproj"

if (-not (Test-Path -LiteralPath $libProject)) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required to fetch CUE4Parse. Install Git or pass -CUE4ParseRoot pointing to a checkout at $commit."
    }
    if (Test-Path -LiteralPath $CUE4ParseRoot) {
        throw "The path '$CUE4ParseRoot' exists but does not contain CUE4Parse\CUE4Parse.csproj. Pass the root of the correct checkout."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $CUE4ParseRoot) | Out-Null
    git clone $repository $CUE4ParseRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not clone CUE4Parse." }
    $clonedForBridge = $true
} else {
    $clonedForBridge = (Test-Path -LiteralPath (Join-Path $CUE4ParseRoot '.bridge-checkout'))
}

$head = (git -C $CUE4ParseRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not read the CUE4Parse commit." }
if ($head -ne $commit) {
    if (-not $clonedForBridge) {
        throw "CUE4Parse at '$CUE4ParseRoot' is $head, but this decoder is pinned to $commit. Use a separate checkout path to avoid changing that repository."
    }
    git -C $CUE4ParseRoot checkout $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out the pinned CUE4Parse commit $commit." }
}
if ($clonedForBridge) {
    # Marks the checkout as the bridge's own, so a later build may move it to a new pinned commit.
    Set-Content -LiteralPath (Join-Path $CUE4ParseRoot '.bridge-checkout') -Value $commit -Encoding ascii
}

# ACL, the animation compression most UE5 games use, is decoded by CUE4Parse's native library. It needs CMake,
# a C++ compiler and the ACL sources; without them the decoder still reads every other clip.
$natives = -not $SkipNatives -and (Get-Command cmake -ErrorAction SilentlyContinue)
if ($natives) {
    git -C $CUE4ParseRoot submodule update --init --recursive CUE4Parse-Natives/ACL/external/acl
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch the ACL sources CUE4Parse's native library needs. Run again with -SkipNatives to build without it." }
} elseif (-not $SkipNatives) {
    Write-Warning 'CMake was not found, so CUE4Parse''s native library is not built. Clips compressed with ACL (common in Unreal Engine 5 games) will not decode. Install CMake and the Visual Studio C++ build tools, then run build_decoder.cmd again to add it.'
}

# Self-contained: CUE4Parse needs .NET 10, and the bridge's shared runtime is .NET 9 (tools\prepare_dotnet_runtime.cmd),
# so the decoder carries its own runtime and users need no .NET installed.
dotnet publish $project -c Release -r win-x64 --self-contained true `
    --artifacts-path $ArtifactsDirectory `
    -p:CUE4ParseRoot="$CUE4ParseRoot" `
    -p:CUE4PARSE_SKIP_NATIVE=$(if ($natives) { 'false' } else { 'true' }) `
    -o $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Unreal decoder build failed." }
# The publish carries the newest .NET 10 runtime that the SDK knows. Runtimes before 10.0.4 have a known vulnerability
# (CVE-2026-26127, the one that Microsoft.Bcl.Memory 9.0.14 also fixes), so an older SDK has to be updated first.
$runtimeConfig = Get-Content -LiteralPath (Join-Path $OutputDirectory 'UnrealDecoder.runtimeconfig.json') -Raw | ConvertFrom-Json
$runtime = ($runtimeConfig.runtimeOptions.includedFrameworks | Where-Object { $_.name -eq 'Microsoft.NETCore.App' }).version
if ([version]($runtime -split '-')[0] -lt [version]'10.0.4') {
    throw "The decoder would carry .NET $runtime, which has a known vulnerability (CVE-2026-26127). Update the .NET 10 SDK, then run build_decoder.cmd again."
}
foreach ($notice in 'LICENSE', 'NOTICE') {
    $source = Join-Path $CUE4ParseRoot $notice
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $OutputDirectory "CUE4Parse-$notice.txt") -Force }
}
$decoder = Join-Path $OutputDirectory 'UnrealDecoder.exe'
& $decoder selftest
if ($LASTEXITCODE -ne 0) { throw "The Unreal decoder failed its self-test." }
Write-Host "Unreal decoder ready: $decoder"
