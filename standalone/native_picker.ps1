param([Parameter(Mandatory=$true)][string]$RequestFile)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$r=Get-Content -LiteralPath $RequestFile -Raw | ConvertFrom-Json
Add-Type -Path (Join-Path $PSScriptRoot 'native_picker.cs') -ReferencedAssemblies System.Windows.Forms,System.Drawing
if($r.kind -eq 'cancel') {
    if([AnimationBridge.NativePicker]::Cancel([string]$r.requestId)){
        ConvertTo-Json -InputObject ([string[]]@('cancelled')) -Compress
    } else {
        ConvertTo-Json -InputObject ([string[]]@()) -Compress
    }
    exit
}
$requestId=if($r.requestId){[string]$r.requestId}else{[Guid]::NewGuid().ToString()}
$paths=[AnimationBridge.NativePicker]::Show([string]$r.kind,[string]$r.current,[string]$r.title,[string]$r.filter,[bool]$r.multiple,$requestId)
ConvertTo-Json -InputObject ([string[]]@($paths)) -Compress
