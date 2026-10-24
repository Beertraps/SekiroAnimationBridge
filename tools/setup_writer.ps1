param(
    [string]$VenvDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\writer-env"),
    [string]$PythonDirectory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\python"),
    [string]$Python313 = ""
)

$ErrorActionPreference = "Stop"
$requirements = Join-Path (Split-Path $PSScriptRoot) "requirements-writer.txt"
$python = Join-Path $VenvDirectory "Scripts\python.exe"
# Release ZIPs include uv.exe; an installed uv works as well. uv downloads Python 3.13 itself.
$uv = Join-Path $PSScriptRoot "uv\uv.exe"
if (-not (Test-Path -LiteralPath $uv)) { $uv = (Get-Command uv.exe -ErrorAction SilentlyContinue).Source }

function Invoke-Tool([string]$Failure) {
    # uv and pip report progress on stderr. Windows PowerShell turns redirected stderr into
    # errors, which "Stop" would make fatal, so this checks the exit code instead.
    $ErrorActionPreference = "Continue"
    $command, $arguments = $args
    & $command @arguments 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

if ($uv -and [string]::IsNullOrWhiteSpace($Python313)) {
    $env:UV_PYTHON_INSTALL_DIR = $PythonDirectory
    if (-not (Test-Path -LiteralPath $python)) {
        Invoke-Tool "Could not create the Python 3.13 writer environment." $uv venv --managed-python --python 3.13 $VenvDirectory
    }
    Invoke-Tool "Could not install the pinned writer dependencies." $uv pip install --python $python -r $requirements
} else {
    if (-not (Test-Path -LiteralPath $python)) {
        if ([string]::IsNullOrWhiteSpace($Python313)) {
            if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
                throw "Install uv, or Python 3.13 with the Windows py launcher, or pass -Python313 with python.exe."
            }
            Invoke-Tool "Could not create the Python 3.13 writer environment." py -3.13 -m venv $VenvDirectory
        } else {
            if (-not (Test-Path -LiteralPath $Python313)) { throw "Python executable not found: $Python313" }
            Invoke-Tool "Could not create the Python 3.13 writer environment." $Python313 -m venv $VenvDirectory
        }
    }
    Invoke-Tool "Could not update pip." $python -m pip install --upgrade pip
    Invoke-Tool "Could not install the pinned writer dependencies." $python -m pip install -r $requirements
}

# The launcher repeats setup when this copy differs from requirements-writer.txt, e.g. after an update.
Copy-Item -LiteralPath $requirements -Destination (Join-Path $VenvDirectory "bridge-requirements.txt") -Force
Write-Host "Writer Python ready: $python"
