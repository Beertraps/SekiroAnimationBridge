[CmdletBinding()]
param(
    [Parameter(Mandatory=$true,Position=0)][ValidateSet('import','export','inspect','ui','discover')][string]$Mode,
    [string]$BlenderExe,
    [string]$DecoderExe,
    [string]$WriterPython=(Join-Path $env:LOCALAPPDATA 'SekiroAnimationBridge\writer-env\Scripts\python.exe'),
    [string]$Animation,[string]$Compendium,[string]$Skeleton,[string]$SkeletonCompendium,
    [string]$AssetFolder,[string]$AssetCatalog,[string]$AssetClip,[string]$OodleDll,
    [switch]$RigOnly,
    [ValidateSet('auto','sekiro','ds1','ds1r','ds3','er')][string]$Game='auto',
    [string]$CharacterSource,
    [Alias('CharacterPreset')][ValidateSet('auto','npc','player','wolf','tutorial','mortal')][string]$WolfPreset='auto',
    [Alias('ModelFiles')][string[]]$PreviewModels,
    [string]$PreviewModel,[string]$PreviewTexture,
    [string]$TextureDirectory,[string]$MaterialBinder,
    [string]$ReferenceModel,[string]$WeaponAttachmentsFile,
    [string]$OutputBlend,[string]$InputBlend,[string]$OutputHKX,
    [ValidateSet('spline','interleaved')][string]$HKXFormat='interleaved',
    [string]$Action,
    [ValidateSet('scene','action','clip','custom')][string]$FrameRange='scene',
    [double]$FrameStart,[double]$FrameEnd,[double]$FrameRate,
    [ValidateSet('original','keyed','all')][string]$Tracks='original',
    [ValidateSet('auto','object','bone','none')][string]$RootMotion='auto',
    [string]$RootBone,[switch]$RootVertical,[switch]$RootYaw,
    [ValidateSet('threecomp40','threecomp48','uncompressed')][string]$Quantization='threecomp40',
    [double]$Tolerance=0.001,
    [switch]$NoVerify,
    [switch]$Force
)
$ErrorActionPreference='Stop'
if($Mode -eq 'ui'){ & (Join-Path $PSScriptRoot 'sekiro_animation_gui.ps1'); exit 0 }
if(!(Test-Path -LiteralPath $WriterPython -PathType Leaf)){
    throw 'Conversion Python is missing. Start the bridge once or run tools\setup_writer.cmd, or pass -WriterPython with the prepared python.exe.'
}
$models=@()
if($PreviewModels){$models+=@($PreviewModels)}
if($PreviewModel){$models+=@($PreviewModel)}
if($PreviewTexture -and !$models.Count -and !$CharacterSource){throw 'A texture override requires a character model.'}
$weaponAttachments=@{}
if($WeaponAttachmentsFile){$weaponAttachments=Get-Content -LiteralPath $WeaponAttachmentsFile -Raw | ConvertFrom-Json}
$request=@{
    mode=$Mode; game=$Game; exportGame=$Game; blender=$BlenderExe; decoder=$DecoderExe; writer=$WriterPython;
    animation=$Animation; compendium=$Compendium; skeleton=$Skeleton; skeletonCompendium=$SkeletonCompendium;
    assetFolder=$AssetFolder; assetCatalog=$AssetCatalog; assetClip=$AssetClip; oodle=$OodleDll;
    inputMethod=$(if($AssetFolder){'folder'}else{'manual'});
    characterSource=$CharacterSource; preset=$WolfPreset; models=@($models);
    includeCharacter=[bool](($CharacterSource -or $models.Count -or $AssetFolder) -and !$RigOnly);
    textureDirectory=$TextureDirectory; materialBinder=$MaterialBinder; previewTexture=$PreviewTexture;
    referenceModel=$ReferenceModel; weaponAttachments=$weaponAttachments;
    outputBlend=$OutputBlend; inputBlend=$InputBlend; outputHKX=$OutputHKX;
    format=$HKXFormat; force=[bool]$Force;
    exportAction=$Action; frameRange=$FrameRange; trackSet=$Tracks; rootMotion=$RootMotion;
    rootBone=$RootBone; rootVertical=[bool]$RootVertical; rootYaw=[bool]$RootYaw;
    quantization=$Quantization; tolerance=$Tolerance; verify=![bool]$NoVerify
}
if($PSBoundParameters.ContainsKey('FrameStart')){$request.frameStart=$FrameStart}
if($PSBoundParameters.ContainsKey('FrameEnd')){$request.frameEnd=$FrameEnd}
if($PSBoundParameters.ContainsKey('FrameRate')){$request.frameRate=$FrameRate}
$requestFile=Join-Path $env:TEMP ('SekiroBridgeRequest-'+[guid]::NewGuid().ToString('N')+'.json')
try {
    $request | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $requestFile -Encoding UTF8
    & $WriterPython -E -X utf8 (Join-Path $PSScriptRoot 'bridge_runtime.py') --request $requestFile
    $code=$LASTEXITCODE
} finally { [IO.File]::Delete($requestFile) }
exit $code
