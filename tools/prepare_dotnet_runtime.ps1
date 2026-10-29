param(
    [string]$OutputDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\dotnet-runtime")
)

# Copies the installed .NET 9 runtime into the folder that the bridge's framework-dependent tools share.
$ErrorActionPreference = "Stop"
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory).TrimEnd('\')
$dotnet = Get-Command dotnet -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dotnet) {
    throw 'dotnet was not found. Install the .NET 9 runtime or SDK, then run prepare_dotnet_runtime.cmd again.'
}
$dotnetRoot = Split-Path -Parent (Resolve-Path -LiteralPath $dotnet.Source).Path

function Get-Latest9([string]$folder) {
    if (-not (Test-Path -LiteralPath $folder)) { return $null }
    Get-ChildItem -LiteralPath $folder -Directory | Where-Object { $_.Name -match '^9\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } | Select-Object -Last 1
}

$framework = Get-Latest9 (Join-Path $dotnetRoot 'shared\Microsoft.NETCore.App')
$fxr = Get-Latest9 (Join-Path $dotnetRoot 'host\fxr')
if (-not $framework -or -not $fxr -or -not (Test-Path -LiteralPath (Join-Path $fxr.FullName 'hostfxr.dll'))) {
    throw "No .NET 9 runtime was found in '$dotnetRoot'. Install the .NET 9 runtime or SDK, then run prepare_dotnet_runtime.cmd again."
}

$inside = { param($path, $folder) $path.Equals($folder, 'OrdinalIgnoreCase') -or $path.StartsWith($folder + '\', 'OrdinalIgnoreCase') }
if ((& $inside $OutputDirectory $dotnetRoot) -or (& $inside $dotnetRoot $OutputDirectory)) {
    throw "The output folder '$OutputDirectory' overlaps the .NET installation in '$dotnetRoot'. Choose another -OutputDirectory."
}
if ((Test-Path -LiteralPath $OutputDirectory) -and -not (Test-Path -LiteralPath (Join-Path $OutputDirectory 'host\fxr'))) {
    throw "The folder '$OutputDirectory' exists and does not hold a .NET runtime. Choose another -OutputDirectory or remove that folder."
}

# Copy into a new folder first, so an interrupted copy never replaces a working runtime.
$staging = Join-Path (Split-Path -Parent $OutputDirectory) ((Split-Path -Leaf $OutputDirectory) + ".partial-$PID")
try {
    $sharedTarget = Join-Path $staging 'shared\Microsoft.NETCore.App'
    $fxrTarget = Join-Path $staging 'host\fxr'
    New-Item -ItemType Directory -Force -Path $sharedTarget, $fxrTarget | Out-Null
    Copy-Item -LiteralPath $framework.FullName -Destination $sharedTarget -Recurse
    Copy-Item -LiteralPath $fxr.FullName -Destination $fxrTarget -Recurse
    foreach ($name in 'LICENSE.txt', 'ThirdPartyNotices.txt') {
        $notice = Join-Path $dotnetRoot $name
        if (Test-Path -LiteralPath $notice) { Copy-Item -LiteralPath $notice -Destination $staging }
    }
    if (Test-Path -LiteralPath $OutputDirectory) { Remove-Item -LiteralPath $OutputDirectory -Recurse -Force }
    Move-Item -LiteralPath $staging -Destination $OutputDirectory
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
Write-Host ".NET runtime $($framework.Name) ready: $OutputDirectory"
