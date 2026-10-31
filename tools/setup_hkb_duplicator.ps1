param(
    [string]$Directory = (Join-Path $env:LOCALAPPDATA "SekiroAnimationBridge\tools\SDT-HKB-Duplicator")
)

# Downloads the SDT HKB Duplicator by Ionian (https://github.com/Ionian-SR/SDT-HKB-Duplicator) at the commit the
# bridge was tested with. The bridge runs its "variation" operation to register a new animation ID in a behavior.
# Its source is not part of the bridge; it stays in this folder, outside the repository.
$ErrorActionPreference = "Stop"
$commit = "560426d59d2296f92200ba1ac996aefb5f9f924e"
$url = "https://codeload.github.com/Ionian-SR/SDT-HKB-Duplicator/zip/$commit"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("SDT-HKB-Duplicator-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $zip = Join-Path $temp "duplicator.zip"
    Write-Host "Downloading $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $temp "x")
    $source = Join-Path $temp "x\SDT-HKB-Duplicator-$commit"
    foreach ($file in "src\behavior.py", "src\project.py", "requirements.txt") {
        if (-not (Test-Path -LiteralPath (Join-Path $source $file))) { throw "The download has no $file." }
    }
    if (Test-Path -LiteralPath $Directory) { Remove-Item -LiteralPath $Directory -Recurse -Force }
    New-Item -ItemType Directory -Path (Split-Path $Directory) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $Directory
    # The bridge reads this to say which commit it found.
    Set-Content -LiteralPath (Join-Path $Directory "bridge-commit.txt") -Value $commit -Encoding ascii
    Write-Host "SDT HKB Duplicator ready: $Directory"
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
