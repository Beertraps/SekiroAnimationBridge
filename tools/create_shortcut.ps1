param([string]$Destination = [Environment]::GetFolderPath('Desktop'))
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$launcher = Join-Path $root 'standalone\sekiro_animation_gui.ps1'
$icon = Join-Path $root 'standalone\ui\icons\bridge.ico'
if (!(Test-Path -LiteralPath $launcher) -or !(Test-Path -LiteralPath $icon)) {
    throw 'Keep the shortcut tool inside the extracted Animation Bridge folder.'
}
if (!(Test-Path -LiteralPath $Destination -PathType Container)) {
    throw "Shortcut folder does not exist: $Destination"
}
$shortcutPath = Join-Path $Destination 'Sekiro Animation Bridge.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoLogo -NoProfile -WindowStyle Hidden -STA -ExecutionPolicy Bypass -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $icon + ',0'
$shortcut.Description = 'Animation Bridge - edit game animations in Blender'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host "Created $shortcutPath"
