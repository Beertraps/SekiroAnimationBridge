[CmdletBinding()]
param(
    [Parameter(Mandatory=$true,Position=0)][ValidateSet('import','export','inspect','ui','discover')][string]$Mode,
    [string]$BlenderExe,
    [string]$DecoderExe,
    [string]$WriterPython=(Join-Path $env:LOCALAPPDATA 'SekiroAnimationBridge\writer-env\Scripts\python.exe'),
    [string]$Animation,[string]$Compendium,[string]$Skeleton,[string]$SkeletonCompendium,
    [string]$AssetFolder,[string]$AssetCatalog,[string]$AssetClip,[string]$AssetCharacter,[string]$OodleDll,
    [ValidateSet('auto','folder','game','custom')][string]$SourceLayout='folder',[string]$SourceLayoutFile,
    [switch]$RigOnly,
    [ValidateSet('auto','sekiro','ds1','ds1r','ds3','er')][string]$Game='auto',
    [string]$CharacterSource,
    [Alias('CharacterPreset')][ValidateSet('auto','npc','player','wolf','tutorial','mortal')][string]$WolfPreset='auto',
    [Alias('ModelFiles')][string[]]$PreviewModels,
    [string]$PreviewModel,[string]$PreviewTexture,
    [string]$TextureDirectory,[string]$MaterialBinder,
    [string]$ReferenceModel,[string]$WeaponAttachmentsFile,
    # Retarget donor: a second clip and character that the import places beside the target.
    [string]$DonorAnimation,[string]$DonorCompendium,[string]$DonorSkeleton,[string]$DonorSkeletonCompendium,
    [string]$DonorAssetFolder,[string]$DonorAssetCatalog,[string]$DonorAssetClip,[string]$DonorAssetCharacter,
    [ValidateSet('auto','folder','game','custom')][string]$DonorSourceLayout,[string]$DonorSourceLayoutFile,
    [switch]$DonorRigOnly,
    [ValidateSet('auto','sekiro','ds1','ds1r','ds3','er')][string]$DonorGame,
    [string]$DonorCharacterSource,
    [ValidateSet('auto','npc','player','wolf','tutorial','mortal')][string]$DonorPreset,
    [string[]]$DonorModels,
    [string]$DonorTextureDirectory,[string]$DonorMaterialBinder,[string]$DonorReferenceModel,
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
    # Weapon part clips: import keys each animated part with its clip; export can write those clips too.
    [switch]$NoPartAnimations,[switch]$ExportParts,
    # Export can also put the HKX into an animation binder, replacing the member of the same name or adding it.
    [string]$Binder,[string]$BinderMember,
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
# A custom layout names the folders per kind: {"animations":["anims"],"characters":["models"],...}
$sourceFolders=@{}
if($SourceLayoutFile){$sourceFolders=Get-Content -LiteralPath $SourceLayoutFile -Raw | ConvertFrom-Json; if($SourceLayout -eq 'folder'){$SourceLayout='custom'}}
$request=@{
    mode=$Mode; game=$Game; exportGame=$Game; blender=$BlenderExe; decoder=$DecoderExe; writer=$WriterPython;
    animation=$Animation; compendium=$Compendium; skeleton=$Skeleton; skeletonCompendium=$SkeletonCompendium;
    assetFolder=$AssetFolder; assetCatalog=$AssetCatalog; assetClip=$AssetClip; assetCharacter=$AssetCharacter; oodle=$OodleDll;
    sourceLayout=$SourceLayout; sourceFolders=$sourceFolders; sourceRecursive=$true;
    inputMethod=$(if($AssetFolder){'folder'}else{'manual'});
    characterSource=$CharacterSource; preset=$WolfPreset; models=@($models);
    includeCharacter=[bool](($CharacterSource -or $models.Count -or $AssetFolder) -and !$RigOnly);
    textureDirectory=$TextureDirectory; materialBinder=$MaterialBinder; previewTexture=$PreviewTexture;
    referenceModel=$ReferenceModel; weaponAttachments=$weaponAttachments;
    outputBlend=$OutputBlend; inputBlend=$InputBlend; outputHKX=$OutputHKX;
    format=$HKXFormat; force=[bool]$Force;
    exportAction=$Action; frameRange=$FrameRange; trackSet=$Tracks; rootMotion=$RootMotion;
    rootBone=$RootBone; rootVertical=[bool]$RootVertical; rootYaw=[bool]$RootYaw;
    quantization=$Quantization; tolerance=$Tolerance; verify=![bool]$NoVerify;
    partAnimations=![bool]$NoPartAnimations; exportParts=[bool]$ExportParts;
    addToBinder=[bool]$Binder; binder=$Binder; binderMember=$BinderMember
}
if($PSBoundParameters.ContainsKey('FrameStart')){$request.frameStart=$FrameStart}
if($PSBoundParameters.ContainsKey('FrameEnd')){$request.frameEnd=$FrameEnd}
if($PSBoundParameters.ContainsKey('FrameRate')){$request.frameRate=$FrameRate}
if(@($PSBoundParameters.Keys | Where-Object {$_ -like 'Donor*'}).Count){
    if($Mode -ne 'import'){throw 'The -Donor options add a retarget donor to an import. Use them with import.'}
    # Without its own folder or files, the donor reads the target's source with its layout and game.
    $shared=!$DonorAssetFolder -and !$DonorAnimation
    $donorFolder=$(if($shared){$AssetFolder}else{$DonorAssetFolder})
    $donorLayout=$(if($DonorSourceLayout){$DonorSourceLayout}elseif($shared){$SourceLayout}else{'folder'})
    $donorFolders=$(if($shared){$sourceFolders}else{@{}})
    if($DonorSourceLayoutFile){$donorFolders=Get-Content -LiteralPath $DonorSourceLayoutFile -Raw | ConvertFrom-Json; if($donorLayout -eq 'folder'){$donorLayout='custom'}}
    $donorModels=@()
    if($DonorModels){$donorModels+=@($DonorModels)}
    $request.donor=@{
        game=$(if($DonorGame){$DonorGame}elseif($shared){$Game}else{'auto'});
        animation=$DonorAnimation; compendium=$DonorCompendium; skeleton=$DonorSkeleton; skeletonCompendium=$DonorSkeletonCompendium;
        assetFolder=$donorFolder; assetCatalog=$(if($DonorAssetCatalog){$DonorAssetCatalog}elseif($shared){$AssetCatalog}else{''});
        assetClip=$DonorAssetClip; assetCharacter=$DonorAssetCharacter;
        sourceLayout=$donorLayout; sourceFolders=$donorFolders; sourceRecursive=$true;
        inputMethod=$(if($donorFolder){'folder'}else{'manual'});
        characterSource=$DonorCharacterSource; preset=$(if($DonorPreset){$DonorPreset}else{'auto'}); models=@($donorModels);
        includeCharacter=[bool](($DonorCharacterSource -or $donorModels.Count -or $donorFolder) -and !$DonorRigOnly);
        textureDirectory=$DonorTextureDirectory; materialBinder=$DonorMaterialBinder; referenceModel=$DonorReferenceModel
    }
}
$requestFile=Join-Path $env:TEMP ('SekiroBridgeRequest-'+[guid]::NewGuid().ToString('N')+'.json')
try {
    $request | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $requestFile -Encoding UTF8
    & $WriterPython -E -X utf8 (Join-Path $PSScriptRoot 'bridge_runtime.py') --request $requestFile
    $code=$LASTEXITCODE
} finally { [IO.File]::Delete($requestFile) }
exit $code
