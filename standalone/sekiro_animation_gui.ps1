$ErrorActionPreference='Stop'
$server=Join-Path $PSScriptRoot 'bridge_ui.py'
$environment=Join-Path $env:LOCALAPPDATA 'SekiroAnimationBridge\writer-env'
$python=Join-Path $environment 'Scripts\pythonw.exe'
$requirements=Join-Path (Split-Path $PSScriptRoot) 'requirements-writer.txt'
$prepared=Join-Path $environment 'bridge-requirements.txt'
# Prepare the conversion Python on the first start, and again when an update pins other libraries.
if(!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $prepared) -or
   ((Get-Content -LiteralPath $prepared) -join "`n") -ne ((Get-Content -LiteralPath $requirements) -join "`n")){
    Write-Host 'Preparing the conversion Python and its libraries. This happens once and takes a few minutes.'
    try{ & (Join-Path (Split-Path $PSScriptRoot) 'tools\setup_writer.ps1') }catch{
        Write-Host $_.Exception.Message -ForegroundColor Red
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Setup could not finish: $($_.Exception.Message)`n`nCheck the internet connection and start the bridge again, or run tools\setup_writer.cmd to see the details.",'Animation Bridge setup') | Out-Null
        exit 1
    }
}
$info=[Diagnostics.ProcessStartInfo]::new()
$info.FileName=$python
# Extra arguments such as --no-browser or --port go to the UI server.
$info.Arguments='-E -X utf8 "'+$server+'"'+(($args | ForEach-Object { ' "'+$_+'"' }) -join '')
$info.WorkingDirectory=$PSScriptRoot
$info.UseShellExecute=$false
$info.CreateNoWindow=$true
[Diagnostics.Process]::Start($info) | Out-Null
