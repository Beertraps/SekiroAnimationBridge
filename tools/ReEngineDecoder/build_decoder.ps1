param(
    [string]$REELibRoot = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\REE-Lib"),
    [string]$OutputDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\re-decoder"),
    [string]$ArtifactsDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\re-build")
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the .NET 9 SDK before building the RE Engine decoder. The runtime alone cannot build it.'
}
$installedSdks = @(& dotnet --list-sdks)
if (-not ($installedSdks | Where-Object { $_ -match '^9\.' })) {
    throw 'The .NET 9 SDK was not found. Install the SDK (not only the runtime), then run build_decoder.cmd again.'
}
$repository = "https://github.com/kagenocookie/RE-Engine-Lib.git"
$commit = "383be0b5be346c0f037def6e503446ace679bed5"
$project = Join-Path $PSScriptRoot "ReEngineDecoder.csproj"
$libProject = Join-Path $REELibRoot "REE-Lib\REE-Lib.csproj"

if (-not (Test-Path -LiteralPath $libProject)) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required to fetch REE-Lib. Install Git or pass -REELibRoot pointing to a checkout at $commit."
    }
    if (Test-Path -LiteralPath $REELibRoot) {
        throw "The path '$REELibRoot' exists but does not contain REE-Lib\REE-Lib.csproj. Pass the root of the correct checkout."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $REELibRoot) | Out-Null
    git clone $repository $REELibRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not clone REE-Lib." }
    $clonedForBridge = $true
} else {
    $clonedForBridge = $false
}

$head = (git -C $REELibRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not read the REE-Lib commit." }
if ($head -ne $commit) {
    if (-not $clonedForBridge) {
        throw "REE-Lib at '$REELibRoot' is $head, but this decoder is pinned to $commit. Use a separate checkout path to avoid changing that repository."
    }
    git -C $REELibRoot checkout $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out the pinned REE-Lib commit $commit." }
}

dotnet publish $project -c Release -r win-x64 --self-contained true `
    --artifacts-path $ArtifactsDirectory `
    -p:REELibProject="$libProject" `
    -o $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "RE Engine decoder build failed." }
$decoder = Join-Path $OutputDirectory 'ReEngineDecoder.exe'
& $decoder selftest
if ($LASTEXITCODE -ne 0) { throw "The RE Engine decoder failed its self-test." }
Write-Host "RE Engine decoder ready: $decoder"
