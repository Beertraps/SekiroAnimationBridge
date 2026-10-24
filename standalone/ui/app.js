'use strict';
const $=id=>document.getElementById(id);
const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
let config={}, parts=[], job=null, lastScan='', autoMaterial='', toastTimer, saveTimer, pollTimer, activePicker=null;
let catalog=null, catalogPath='', loadingCatalog='', folderBusy=false, resolvingClip=false, resolveSequence=0, lastSuggestedBlend='', sceneInfo=null;
const loadedScans=new Set();
const opened=new Set(), initiatedJobs=new Set();
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=name=>`<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const basename=p=>(p||'').split(/[\\/]/).pop();
const samePath=(a,b)=>String(a||'').replace(/[\\/]+/g,'/').replace(/\/$/,'').toLowerCase()===String(b||'').replace(/[\\/]+/g,'/').replace(/\/$/,'').toLowerCase();
const gameNames={sekiro:'Sekiro',ds1:'Dark Souls: Prepare to Die',ds1r:'Dark Souls Remastered',ds3:'Dark Souls III',er:'Elden Ring'};
function currentGame(){return (folderMode()?catalog?.clips.find(c=>c.id===$('assetClip').value)?.game:'')||$('game').value;}
const help={
 game:['Source game','Auto detect reads the actual Havok version and original archive paths. Folder mode keeps different games separate even when each has a c0000 character. Choosing a game filters the character list. For a loose DS3 packfile, select Dark Souls III explicitly because other games share Havok 2014. Havok 2015 tagfiles are identified as Dark Souls Remastered.'],
 exportGame:['Export source game','Normally leave this on Stored in scene. Version 0.5 remembers the original game and writes its native Havok version. Older scenes lack this information: select the game they came from, or import them again. This selector cannot convert a new scene into another game’s skeleton; use the retargeting workflow for that.'],
 assetFolder:['Character archives folder','Create a folder containing the original DCX files for a character. Subfolders are fine. Include the base cXXXX.anibnd.dcx for the skeleton, plus any split animation archives you want. The scan finds animations and matches their skeleton and compendium.\n\nFor a model preview, include cXXXX.chrbnd.dcx (NPCs), or player outfit PARTSBND files. Add TEXBND / TPF textures and the material library: allmaterialbnd.mtdbnd.dcx for MTD games, material/allmaterial.matbinbnd.dcx for Elden Ring. Different games keep separate character entries even when they share c0000. Texture package IDs can differ from the character ID. Original files are read only; extracted animation inputs are cached in the bridge’s work folder.'],
 assetClip:['Choose an animation','An archive can contain hundreds of animations, so choose which clip to import. The archive name is shown to distinguish duplicate clip names. A clip marked “missing inputs” needs the files listed below the selection. The tool never borrows a different character’s skeleton.'],
 skeletonCompendium:['Separate skeleton compendium','Optional compendium for the skeleton if it differs from the animation’s compendium. Folder mode fills this automatically using the type IDs stored inside HKX files. Leave empty in manual mode to use the animation’s matching compendium.'],
 oodle:['Oodle library','KRAK-compressed DCX files use oo2core_6_win64.dll from your own Sekiro installation. This tool searches Steam libraries and the conversion environment automatically. Browse to the DLL here if it cannot be found. It is loaded in place and is not copied into the release ZIP. DFLT decompression uses Python’s built-in zlib.'],
 referenceModel:['Rig attachment model','For separate weapons, include the same game’s c0000.chrbnd.dcx or its extracted c0000.flver. Sekiro uses its verified weapon profiles. DS1, Remastered, DS3 and Elden Ring place any weapon with the game’s default sockets: right hand, with a scabbard or extra model on the opposite hip. Weapon placement also offers left hand, two-handed, sheathed and custom dummy IDs. Skeleton names such as Master are accepted; the actual attachment bones are checked. This model supplies the attachment dummies: their bone, position and orientation. It has no visible body mesh and is not selected as a character part. Folder mode finds it automatically when present.'],
 animation:['Animation HKX','Choose an animation extracted from the character’s animation binder with WitchyBND. Wolf and NPC animations are supported, in spline-compressed or interleaved HKX format. Edit the animation on the rig in Blender.'],
 compendium:['Matching compendium','Many original Sekiro HKX files share their type information through a compendium. Choose the .compendium from the same animation binder as the HKX. Leave this empty for a self-contained exported HKX.'],
 skeleton:['Skeleton HKX','Choose skeleton.hkx from this character’s animation binder, normally chr/cXXXX.anibnd.dcx. NPC skeletons may require the matching compendium too. This supplies the rest pose and bone hierarchy. The character-named HKX in a model binder can contain collision data.'],
 characterSource:['Character assets','For NPCs, choose a folder containing the character’s .chrbnd(.dcx) or extracted .flver(.dcx). One model is enough. Player outfit / modular parts selects unambiguous available outfit pieces. c0000 is the player ID in several games; it does not imply Wolf. The assets folder is filled automatically in folder mode.\n\nFor Wolf, choose the parts folder and an outfit. Standard Wolf uses FC_M_0200, AM_M_9000, BD_M_9000 and LG_M_9000. c0000.flver itself has no visible mesh.'],
 materialBinder:['Material library','MTD games can store texture paths and UV assignments in material definitions. Elden Ring uses MATBIN: provide material/allmaterial.matbinbnd.dcx; its old MTD library does not provide the active assignments. MATBIN definitions are matched by stem even when the model refers to .matxml or .mtd. The tool looks for mtd/allmaterialbnd.mtdbnd.dcx beside the parts folder, or a supplied wolf.mtdbnd library.\n\nThe preview resolves each material’s base-color and normal map. It approximates Sekiro’s layered shaders and does not simulate Havok cloth.'],
 textureDirectory:['Additional textures','Optional folder containing .texbnd(.dcx), .tpf(.dcx) packages or extracted images. NPC texture IDs can differ from their model ID: Owl c5060 uses c5069.texbnd.dcx and shared common_body.tpf.dcx. Put the needed packages in a small character folder and choose it here. A binder’s own TPF files are also read automatically.'],
 outputBlend:['Blender scene','Choose a new .blend filename. The imported action, original animation metadata, rigged character parts and used texture images are saved in the scene. Images are packed, so you can move the .blend file. Existing output is replaced only when the checkbox is enabled.'],
 inputBlend:['Edited Blender scene','Choose a .blend scene created by this tool, or one where the retarget add-on baked motion onto a bridge rig. Save your changes in Blender first. Read actions lists the scene’s armature actions and frame ranges without changing the file.'],
 exportAction:['Action','The active action is the one assigned to the rig when the scene was saved. Read actions lists every action that keys this rig’s bones, with its frame range, so you can export another take without reassigning it in Blender. A matching root-motion action, named like the importer’s _RootMotion or the retarget add-on’s RootMotion action, is used with it.'],
 frameRange:['Frame range','Scene start to end uses the scene’s frame range; import and the retarget add-on set it to the clip length. Action keyframe range follows the chosen action’s first and last keys. Imported clip length samples frame 1 to the original frame count. Custom takes any start and end frame.\n\nThe pose is sampled by time. If the scene frame rate differs from the output rate, samples fall between frames and are interpolated.'],
 trackSet:['Tracks','Source clip tracks keeps the original track list. This is the safest choice: bones without a track stay under the game’s control, for example face, cloth or weapon bones driven by other animation layers.\n\nSource tracks + keyed bones adds the bones keyed in the chosen action. Every skeleton bone writes a track for each bone and holds unkeyed bones in their Blender pose. Added tracks follow the original ones, so existing track indices stay the same.'],
 frameRate:['Frame rate','Samples per second in the HKX. Leave this empty to keep the source clip’s rate, normally 30. The clip duration stays the same; a higher rate only adds samples. TAE event times are in seconds, so they stay aligned.'],
 rootMotion:['Root motion','Root motion moves the character’s capsule in game.\n\nHKX_RootMotion empty exports the empty created by the importer or the retarget add-on, when the scene has one. Extract from a bone’s travel turns a bone’s movement into root motion and removes that travel from the body, so the pose looks the same in game. The default is the bone that carries the whole body: Root, RootPos or Master, depending on the rig. Ground travel is extracted by default; include vertical travel for jumps or climbs, and turning for animations that change direction. No root motion writes none, even if the source clip had it.'],
 quantization:['Rotation precision','How spline compression stores rotations. 40-bit is the default. 48-bit is finer at a slightly larger size. Full floats store rotations without quantization. Interleaved output is not affected.'],
 tolerance:['Spline tolerance','The largest difference the spline compressor accepts while fitting curves, from 0.000001 to 0.1. Smaller values keep more detail and make larger files. The default is 0.001. With Read the HKX back enabled, the export reports the actual difference.'],
 outputHKX:['HKX output','Export writes a raw HKX and an adjacent .motion.json sidecar. Use WitchyBND to replace the animation member in a copy of your binder. Model geometry, TAE events and unrelated HKX metadata are not exported.\n\nRead the HKX back decodes the written file again and reports the largest rotation and translation differences from the sampled pose.'],
 blender:['Blender executable','Choose blender.exe from your Blender installation. Version 4.5.14 is checked locally. The scripts use Blender’s built-in Python APIs and require no add-on. Compatibility with 5.2 still needs a run on that version.'],
 writer:['Conversion Python','Choose python.exe from the writer environment, normally %LOCALAPPDATA%\\SekiroAnimationBridge\\writer-env\\Scripts\\python.exe. The bridge creates it on the first start with Soulstruct, Soulstruct Havok and NumPy; tools/setup_writer.cmd repeats that setup. Blender’s bundled Python stays separate.'],
 decoder:['HKX decoder','Release ZIPs include SekiroMotionDecoder.exe in their decoder folder, and the bridge selects it automatically. In a source checkout, build it with tools/SekiroMotionDecoder/build_decoder.cmd; that path is under %LOCALAPPDATA%\\SekiroAnimationBridge\\decoder. Version 0.5 handles tagfiles, native PC packfiles, spline/interleaved animations and separate animation/skeleton compendiums.']
};
const filters={animation:'Havok animation (*.hkx)|*.hkx|All files (*.*)|*.*',skeleton:'Havok skeleton (*.hkx)|*.hkx|All files (*.*)|*.*',compendium:'Havok compendium (*.compendium)|*.compendium|All files (*.*)|*.*',blender:'Blender executable (blender.exe)|blender.exe|Executables (*.exe)|*.exe',writer:'Python executable (python.exe)|python.exe|Executables (*.exe)|*.exe',decoder:'Animation decoder (*.exe)|*.exe',materialBinder:'Material library (*.mtdbnd*;*.matbinbnd*;*.mtd;*.matbin)|*.mtdbnd;*.mtdbnd.dcx;*.matbinbnd;*.matbinbnd.dcx;*.mtd;*.matbin|All files (*.*)|*.*',outputBlend:'Blender scene (*.blend)|*.blend',inputBlend:'Blender scene (*.blend)|*.blend',outputHKX:'Havok animation (*.hkx)|*.hkx'};
async function api(path,data,signal){
 const response=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'X-Bridge-Token':token,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data),signal});
 const result=await response.json(); if(!response.ok)throw Error(result.error||'The workspace could not complete the request.'); return result;
}
function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,error?13000:4200);}
function showPage(page){document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));$('breadcrumb').textContent={import:'IMPORT ANIMATION',export:'EXPORT ANIMATION',settings:'SETTINGS & SETUP'}[page];window.scrollTo({top:0,behavior:'smooth'});}
function values(){
 const result={...config}; document.querySelectorAll('[data-config]').forEach(el=>result[el.id]=el.type==='checkbox'?el.checked:el.value.trim());
 result.format=document.querySelector('[name="format"]:checked').value;
 result.models=parts.filter(p=>p.selected).map(p=>p.path);return result;
}
function saveSoon(){clearTimeout(saveTimer);saveTimer=setTimeout(async()=>{config=values();try{await api('settings',config);}catch(e){toast(e.message,true);}},450);}
const selectDefaults={preset:'auto',game:'auto',exportGame:'auto',frameRange:'scene',trackSet:'original',rootMotion:'auto',quantization:'threecomp40'};
function setValues(data){config=data;renderActions(data.exportAction||'');document.querySelectorAll('[data-config]').forEach(el=>{if(el.type==='checkbox')el.checked=!!data[el.id];else el.value=data[el.id]||selectDefaults[el.id]||'';});document.querySelectorAll('[name="format"]').forEach(el=>el.checked=el.value===data.format);$('import-force').checked=!!data.force;$('export-force').checked=!!data.force;toggleCharacter();updateExportOptions();}
const formatNumber=value=>Number.isInteger(+value)?String(+value):(+value).toFixed(2);
function selectedAction(){return sceneInfo?.actions.find(a=>a.name===($('exportAction').value||sceneInfo.activeAction));}
function renderActions(selected=$('exportAction').value){
 const actions=sceneInfo?.actions||[];
 const options=[['',sceneInfo?.activeAction?'Active action · '+sceneInfo.activeAction:'Active action in the saved scene'],...actions.map(a=>[a.name,`${a.name} · frames ${formatNumber(a.frameStart)}–${formatNumber(a.frameEnd)}`])];
 if(selected&&!actions.some(a=>a.name===selected))options.push([selected,selected+(sceneInfo?' · not in this scene':' · read actions to check')]);
 $('exportAction').innerHTML=options.map(([value,label])=>`<option value="${escape(value)}">${escape(label)}</option>`).join('');
 $('exportAction').value=selected||'';
}
function renderScene(){
 const info=sceneInfo;$('scene-info').hidden=!info;
 if(info){
  const count=info.actions.length;
  $('scene-info').textContent=[`${info.rig} · ${gameNames[info.game]||'Game not recorded'} · ${info.clip}`,
   `Source clip: ${info.frameCount} frames at ${formatNumber(info.frameRate)} fps · ${info.trackCount} tracks · ${info.rootObject?'root motion empty '+info.rootObject.name:'no root motion empty'}`,
   `Scene frames ${info.scene.frameStart}–${info.scene.frameEnd} at ${formatNumber(info.scene.fps)} fps · ${count} armature action${count===1?'':'s'}`].join('\n');
  $('bone-names').innerHTML=info.bones.map(name=>`<option value="${escape(name)}">`).join('');
  $('rootBone').placeholder=info.defaultRootBone;
 }
 renderActions();updateExportOptions();
}
function forgetScene(){sceneInfo=null;renderActions('');renderScene();}
function rangeNote(){
 const info=sceneInfo,mode=$('frameRange').value;
 if(!info)return mode==='clip'?'Samples frame 1 to the imported clip’s frame count.':'Read actions to preview the frames and list the scene’s actions.';
 const action=selectedAction();
 const [start,end]=mode==='scene'?[info.scene.frameStart,info.scene.frameEnd]:mode==='action'?(action?[action.frameStart,action.frameEnd]:[NaN,NaN]):mode==='clip'?[1,info.frameCount]:[parseFloat($('frameStart').value),parseFloat($('frameEnd').value)];
 if(!(end>start))return mode==='custom'?'Enter a start frame and a later end frame.':'This range has fewer than two frames.';
 const rate=parseFloat($('frameRate').value)||info.frameRate,seconds=(end-start)/info.scene.fps;
 return `Frames ${formatNumber(start)}–${formatNumber(end)} at ${formatNumber(info.scene.fps)} fps → ${Math.round(seconds*rate)+1} frames at ${formatNumber(rate)} fps (${seconds.toFixed(2)} s).`;
}
function updateExportOptions(){
 const root=$('rootMotion').value,tracks=$('trackSet').value;
 $('custom-range').hidden=$('frameRange').value!=='custom';$('root-bone-fields').hidden=root!=='bone';
 $('spline-options').hidden=document.querySelector('[name="format"]:checked')?.value!=='spline';
 $('range-note').textContent=rangeNote();
 const rootLabel={auto:'root empty',bone:'root from '+($('rootBone').value.trim()||sceneInfo?.defaultRootBone||'the body root'),none:'no root motion'}[root];
 $('sampling-summary').textContent=`${{original:'Source tracks',keyed:'Source + keyed bones',all:'Every bone'}[tracks]} · ${$('frameRate').value.trim()?$('frameRate').value.trim()+' fps':'source rate'} · ${rootLabel}`;
 const untracked=selectedAction()?.untracked||[];
 $('track-note').hidden=!(untracked.length&&tracks==='original');
 const gameMissing=!!sceneInfo&&!sceneInfo.game&&$('exportGame').value==='auto';
 $('game-note').hidden=!gameMissing;
 if(gameMissing)$('game-note').textContent='This scene was imported before the bridge recorded its game. Choose the game it came from.';
 if(untracked.length)$('track-note').textContent=`${untracked.length} keyed bone${untracked.length===1?' is':'s are'} not a track of the source clip: ${untracked.slice(0,6).join(', ')}${untracked.length>6?', …':''}. Choose “Source tracks + keyed bones” to export ${untracked.length===1?'it':'them'}.`;
}
function isWolfAssembly(){return ['wolf','tutorial','mortal'].includes($('preset').value)&&!['ds1','ds1r','ds3','er'].includes(currentGame());}
function detectNpcModels(){if(parts.some(p=>/^(fc|hd|hr|am|bd|lg)_/i.test(p.id))){if(!isWolfAssembly())$('preset').value=!['ds1','ds1r','ds3','er'].includes(currentGame())&&parts.some(p=>['bd_m_9000','bd_m_9030','bd_m_9040'].includes(p.id))?'wolf':'player';}else if(parts.length)$('preset').value='npc';}
function toggleCharacter(){const enabled=$('includeCharacter').checked;$('character-fields').hidden=!enabled;$('rig-only').hidden=enabled;$('character-mode').textContent=enabled?'Include model':'Rig only';updateAssembly();}
async function pick(key,multiple=false){
 if(activePicker)return toast('A Browse window is already open. Finish or cancel that selection first.');
 const picker={id:crypto.randomUUID(),controller:new AbortController(),timedOut:false};activePicker=picker;
 const buttons=[...document.querySelectorAll('[data-pick],#add-models')].map(button=>({button,disabled:button.disabled}));
 buttons.forEach(({button})=>button.disabled=true);
 $('picker-status').hidden=false;$('picker-message').textContent=`Choosing ${help[key]?.[0].toLowerCase()||'model files'}…`;$('cancel-picker').disabled=false;
 const timeout=setTimeout(()=>{picker.timedOut=true;picker.controller.abort();api('pick',{kind:'cancel',requestId:picker.id}).catch(()=>{});},310000);
 try{
  const result=await api('pick',{kind:['assetFolder','characterSource','textureDirectory'].includes(key)?'folder':(['outputBlend','outputHKX'].includes(key)?'save':'file'),current:$(key)?.value||$('characterSource').value||'',title:help[key]?.[0]||'Choose character files',multiple,requestId:picker.id,filter:filters[key]||(key==='oodle'?'Oodle library (oo2core_6_win64.dll)|oo2core_6_win64.dll':key==='skeletonCompendium'?filters.compendium:'Model files (*.flver;*.flver.dcx;*.partsbnd;*.partsbnd.dcx;*.chrbnd.dcx)|*.flver;*.flver.dcx;*.partsbnd;*.partsbnd.dcx;*.chrbnd.dcx|All files (*.*)|*.*')},picker.controller.signal);
  if(!result.paths?.length)return;
  if(multiple){const scan=await api('scan',{files:result.paths});parts=scan.parts;$('characterSource').value='';detectNpcModels();renderParts();}
  else{$(key).value=result.paths[0];$(key).closest('.path-row')?.classList.remove('invalid');if(key==='inputBlend')forgetScene();if(!folderMode()&&['animation','compendium','skeleton'].includes(key))$('skeletonCompendium').value='';if(key==='characterSource')await scanSource();if(key==='assetFolder'){invalidateFolder();await scanFolder();}}
  saveSoon();if(['blender','writer','decoder','oodle'].includes(key))await checkEnvironment();
 }catch(e){if(e.name!=='AbortError')toast(e.message,true);else if(picker.timedOut)toast('Browse timed out. Open Browse again to retry.',true);}
 finally{clearTimeout(timeout);if(activePicker===picker){activePicker=null;$('picker-status').hidden=true;buttons.forEach(({button,disabled})=>button.disabled=disabled);}}
}
function folderMode(){return $('inputMethod').value==='folder';}
function toggleInputMethod(){
 $('folder-fields').hidden=!folderMode();
 if(folderMode()&&catalog)renderCharacters();
}
function invalidateFolder(){
 resolveSequence++;resolvingClip=false;catalog=null;catalogPath='';config.assetCatalog='';config.assetClip='';config.assetCharacter='';
 $('assetCharacter').innerHTML='';$('assetClip').innerHTML='';$('folder-selection').hidden=true;
 $('folder-notice').hidden=true;$('folder-count').textContent='Scan this folder to find its inputs.';
 for(const key of ['animation','skeleton','compendium','skeletonCompendium','characterSource','materialBinder','textureDirectory','referenceModel'])$(key).value='';
 parts=[];renderParts();
}
async function scanFolder(){
 try{
  requireFields(['assetFolder']);if(job?.status==='running')throw Error('Wait for the current operation, or cancel it first.');
  invalidateFolder();config=values();
  job=await api('job',{...config,mode:'discover'});initiatedJobs.add(job.id);updateJob(job);
  toast('Scanning archives. You can cancel from Activity.');
 }catch(e){toast(e.message,true);}
}
async function loadFolderCatalog(path,folder){
 if(loadingCatalog===path)return;
 loadingCatalog=path;folderBusy=true;
 try{
  const found=await api('catalog',{path,folder});
  if(!samePath($('assetFolder').value.trim(),folder))return;
  catalog=found;catalogPath=path;config.assetCatalog=path;
  $('folder-count').textContent=`${catalog.archiveCount} archives · ${catalog.clips.length} animations · ${catalog.characters.length} characters`;
  $('folder-selection').hidden=!catalog.clips.length;
  $('folder-notice').textContent=catalog.warnings.join('\n\n');$('folder-notice').hidden=!catalog.warnings.length;
  renderCharacters();await resolveClip(true);saveSoon();
 }catch(e){toast(e.message,true);$('folder-notice').textContent=e.message;$('folder-notice').hidden=false;}
 finally{if(loadingCatalog===path){loadingCatalog='';folderBusy=false;}}
}
function renderCharacters(){
 if(!catalog)return;
 const previous=$('assetCharacter').value||config.assetCharacter;
 const characters=catalog.characters.filter(c=>$('game').value==='auto'||c.game===$('game').value);
 $('assetCharacter').innerHTML=characters.map(c=>`<option value="${escape(c.id)}">${escape(c.name)} · ${c.count} clips</option>`).join('');
 if(characters.some(c=>c.id===previous))$('assetCharacter').value=previous;
 renderClips();
}
function renderClips(){
 if(!catalog)return;
 const previous=$('assetClip').value||config.assetClip,needle=$('clip-filter').value.toLowerCase().trim();
 const clips=catalog.clips.filter(c=>c.characterKey===$('assetCharacter').value&&(!needle||(c.name+' '+basename(c.archive)).toLowerCase().includes(needle)));
 $('assetClip').innerHTML=clips.length?clips.map(c=>`<option value="${escape(c.id)}">${escape(c.name)} · ${escape(basename(c.archive)||'unpacked file')}${c.ready?'':' · missing inputs'}</option>`).join(''):'<option value="">No matching animations</option>';
 if(clips.some(c=>c.id===previous))$('assetClip').value=previous;
 else if(clips.some(c=>c.ready))$('assetClip').value=clips.find(c=>c.ready).id;
}
async function resolveClip(restore=false){
 if(!catalog)return;
 const seq=++resolveSequence,clip=catalog.clips.find(c=>c.id===$('assetClip').value);
 resolvingClip=false;
 config.assetClip=$('assetClip').value;config.assetCharacter=$('assetCharacter').value;
 $('folder-match').classList.toggle('error',!clip?.ready);
 if(!clip?.ready){
  $('folder-match').textContent=clip?clip.issues.join('\n\n'):'Choose an animation or change the search.';
  for(const key of ['animation','skeleton','compendium','skeletonCompendium'])$(key).value='';
  parts=[];renderParts();saveSoon();return;
 }
 try{
  resolvingClip=true;
  const wolf=clip.character==='c0000'&&clip.game==='sekiro';
  const preset=wolf?(['wolf','tutorial','mortal'].includes($('preset').value)?$('preset').value:'wolf'):clip.character==='c0000'?'player':'npc';
  const resolved=await api('resolve',{path:catalogPath,folder:catalog.folder,clip:clip.id,preset});
  if(seq!==resolveSequence)return;
  const selected=restore?new Set(config.models||[]):new Set();
  for(const key of ['animation','skeleton','compendium','skeletonCompendium','materialBinder','textureDirectory','characterSource','preset','referenceModel'])$(key).value=resolved[key]||'';
  parts=resolved.parts;if(selected.size&&parts.some(p=>selected.has(p.path)))parts.forEach(p=>p.selected=selected.has(p.path));renderParts();
  const notes=[gameNames[resolved.game]+' · matched animation, skeleton and '+(clip.compendium?'compendium.':'self-contained type information.')];
  if(clip.skeletonCompendium&&clip.skeletonCompendium!==clip.compendium)notes.push('The skeleton uses a separate matching compendium.');
  if(!parts.length)notes.push(clip.character==='c0000'?'No player outfit found. c0000.chrbnd is a skeleton reference with no visible body. Add outfit PARTSBND files from this game, or switch to Rig only.':'No matching model found. Add this character’s CHRBND, or switch to Rig only.');
  if(resolved.missing.length)notes.push('Missing outfit assets: '+resolved.missing.join(', ')+'. Available parts remain selectable.');
  if(resolved.game==='er'&&!resolved.materialBinder)notes.push('For Elden Ring materials, add material/allmaterial.matbinbnd.dcx and rescan. The legacy MTD binder is not used for these assignments.');
  notes.push('Inputs below show the selected files.');$('folder-match').textContent=notes.join('\n');
  if(!restore||!$('outputBlend').value){
   const suggested=catalog.folder.replace(/[\\/]$/,'')+'/Blender/'+(clip.character||'character')+'_'+clip.name.replace(/\.hkx$/i,'')+'.blend';
   if(!lastSuggestedBlend||$('outputBlend').value===lastSuggestedBlend||!$('outputBlend').value){$('outputBlend').value=suggested;lastSuggestedBlend=suggested;}
  }
  saveSoon();
 }catch(e){if(seq!==resolveSequence)return;$('folder-match').textContent=e.message;$('folder-match').classList.add('error');toast(e.message,true);}
 finally{if(seq===resolveSequence)resolvingClip=false;}
}
async function cancelPicker(){
 const picker=activePicker;if(!picker)return;$('cancel-picker').disabled=true;
 try{
  const result=await api('pick',{kind:'cancel',requestId:picker.id});
  if(result.paths?.includes('cancelled')){picker.controller.abort();toast('Browse cancelled.');}
  else if(activePicker===picker)toast('The Browse window is already closing.');
 }catch(e){toast(e.message,true);}finally{if(activePicker===picker)$('cancel-picker').disabled=false;}
}
async function scanSource(preserve=false){
 const source=$('characterSource').value.trim();if(!source){renderParts();return;}
 const activeClip=catalog?.clips.find(c=>c.id===$('assetClip').value);
 if(folderMode()&&activeClip&&samePath(source,activeClip.scope)){await resolveClip(true);return;}
 $('scan').disabled=true;$('scan').textContent='Finding…';$('scan-notice').hidden=true;
 try{
  const scan=await api('scan',{source,preset:$('preset').value,game:currentGame()});const selected=preserve?new Set(config.models||[]):new Set();parts=scan.parts;
  if(scan.preset)$('preset').value=scan.preset;
  if(selected.size&&parts.some(p=>selected.has(p.path)))parts.forEach(p=>p.selected=selected.has(p.path));
  if(scan.materials&&(!$('materialBinder').value||$('materialBinder').value===autoMaterial)){ $('materialBinder').value=scan.materials;autoMaterial=scan.materials; }
  lastScan=source;detectNpcModels();renderParts();
  if(isWolfAssembly()&&scan.missing.length){$('scan-notice').textContent='Some outfit parts are missing: '+scan.missing.join(', ')+'. You can choose available parts individually.';$('scan-notice').hidden=false;}
  if(!parts.length){$('scan-notice').textContent='No models were found. Choose a character folder or use Choose files to add a CHRBND or FLVER.';$('scan-notice').hidden=false;}
  saveSoon();
 }catch(e){parts=[];renderParts();$('scan-notice').textContent=e.message;$('scan-notice').hidden=false;toast(e.message,true);}
 finally{$('scan').disabled=false;$('scan').innerHTML=icon('cube')+'Find models';}
}
function renderParts(){
 const roles=['Head','Arms / prosthetic','Torso','Legs'];
 if(!parts.length){$('parts').innerHTML='<div class="empty-parts">Choose a character folder, then select <strong>Find models</strong>.<small>Reads CHRBND, PARTSBND and loose FLVER models.</small></div>';updateAssembly();return;}
 if(!isWolfAssembly()){
  const player=$('preset').value==='player';
  $('parts').innerHTML='<p class="npc-model-note">'+(player?'Player outfit parts. One choice per region is selected when unambiguous; choose an outfit if several are available.':'Select the model matching your animation skeleton. One model is enough.')+'</p>'+parts.map(p=>`<label class="npc-model-row" title="${escape(p.path)}"><input type="checkbox" data-model="${escape(p.path)}" ${p.selected?'checked':''}><span><strong>${escape(p.name)}</strong><small>${escape(p.role)} · ${escape(p.container)} · ${escape(basename(p.path))}</small></span>${icon('cube')}</label>`).join('');
  const weapons=parts.filter(p=>/^wp_/i.test(p.id)),sekiro=currentGame()==='sekiro';
  if(weapons.length)$('parts').insertAdjacentHTML('beforeend',`<details class="extras" ${weapons.some(p=>p.selected)?'open':''}><summary>Weapon placement</summary><p class="field-note">${sekiro?'Auto places the katana in the right hand, the Mortal Blade on the back and prosthetics on their authored sockets.':'Auto puts any weapon in the right hand and its scabbard or extra model on the left hip, like the game’s default WepAbsorpPosParam row. Two-handed keeps a scabbard on the hip. Sheathed hangs the whole weapon on the hip opposite its hand.'} Custom dummy IDs take one ID for every model, or a list such as 20, 30 for model 0, model 1. Sockets come from this game’s c0000.chrbnd; this is a fixed preview placement.</p>${weapons.map(p=>`<div class="equipment-row"><span>${escape(p.name)}</span>${weaponControl(p)}</div>`).join('')}${socketList()}</details>`);
  bindWeaponControls();
  $('parts').querySelectorAll('[data-model]').forEach(input=>input.addEventListener('change',()=>{parts.find(p=>p.path===input.dataset.model).selected=input.checked;updateAssembly();saveSoon();}));
  updateAssembly();return;
 }
 $('parts').innerHTML=roles.map((role,i)=>{
  const matches=parts.filter(p=>p.role===role),selected=matches.find(p=>p.selected);
  return `<div class="part-row"><span class="part-icon">${icon('cube')}</span><div class="part-label"><strong>${escape(role==='Arms / prosthetic'?'Arms / prosthetic':role)}</strong><small>${selected?escape(selected.container):'Not selected'}</small></div><select data-role="${escape(role)}" aria-label="Select ${escape(role)}" title="${escape(selected?.path||'Skip this part')}"><option value="">Skip this part</option>${matches.map(p=>`<option value="${escape(p.path)}" ${p===selected?'selected':''}>${escape(p.name)}</option>`).join('')}</select></div>`;
 }).join('');
 const extras=parts.filter(p=>!roles.includes(p.role));
 if(extras.length)$('parts').insertAdjacentHTML('beforeend',`<details class="extras" ${extras.some(p=>p.selected)?'open':''}><summary>Weapons & extra parts (${extras.length} available)</summary><p class="field-note">Weapons use the attachment points in c0000.chrbnd.dcx. Auto places the katana in the right hand, the Mortal Blade on the back, and prosthetics on their authored sockets. Choose a different preview placement below. HKX alone does not specify draw/sheath events.</p><div class="extras-list">${extras.map(p=>`<div class="equipment-row"><label class="extra-row"><input type="checkbox" data-extra="${escape(p.path)}" ${p.selected?'checked':''}><span>${escape(p.name)}${p.id==='wp_a_0300'?'<small>Katana / Kusabimaru</small>':p.id==='wp_a_0310'?'<small>Mortal Blade</small>':''}</span></label>${/^wp_/i.test(p.id)?weaponControl(p):''}</div>`).join('')}</div>${socketList()}</details>`);
 $('parts').querySelectorAll('[data-role]').forEach(select=>select.addEventListener('change',()=>{parts.filter(p=>p.role===select.dataset.role).forEach(p=>p.selected=p.path===select.value);renderParts();saveSoon();}));
 $('parts').querySelectorAll('[data-extra]').forEach(input=>input.addEventListener('change',()=>{parts.find(p=>p.path===input.dataset.extra).selected=input.checked;updateAssembly();saveSoon();}));
 bindWeaponControls();
 updateAssembly();
}
const weaponStates=game=>game==='sekiro'?[['auto','Auto · game socket'],['right','Drawn · right hand'],['left','Drawn · left hand'],['sheath','Hip sheath'],['back','Back sheath'],['custom','Custom dummy IDs…']]
 :[['auto','Auto · right hand'],['right','Right hand'],['left','Left hand'],['both','Two-handed'],['sheath','Sheathed · right-hand weapon'],['sheath-left','Sheathed · left-hand weapon'],['custom','Custom dummy IDs…']];
const socketHints={sekiro:[[20,'right hand'],[21,'left hand'],[147,'hip sheath'],[149,'back · Mortal Blade']],ds1:[[20,'right hand'],[21,'left hand'],[24,'right hand · two-handed'],[30,'left hip · L_Wepon_Case'],[31,'right hip · R_Wepon_Case']],
 souls:[[20,'right hand'],[21,'left hand'],[24,'right hand · two-handed'],[30,'left hip'],[31,'right hip'],[33,'back storage (first spine dummy)']]};
function socketList(){const game=currentGame(),hints=socketHints[game==='sekiro'?'sekiro':['ds1','ds1r'].includes(game)?'ds1':'souls'];return `<datalist id="weapon-sockets">${hints.map(([v,l])=>`<option value="${v}">${escape(l)}</option>`).join('')}</datalist>`;}
function weaponControl(p){
 const states=weaponStates(currentGame());let value=config.weaponAttachments?.[p.id]||'auto';const custom=value.startsWith('dummy:');
 // A state saved for another game falls back to Auto rather than failing the import.
 if(!custom&&!states.some(([v])=>v===value)){value='auto';if(config.weaponAttachments)delete config.weaponAttachments[p.id];}
 return `<select data-weapon="${escape(p.id)}" aria-label="Placement for ${escape(p.name)}">${states.map(([v,l])=>`<option value="${v}" ${value===v||v==='custom'&&custom?'selected':''}>${l}</option>`).join('')}</select><input type="text" inputmode="numeric" pattern="\\s*\\d{1,5}(\\s*,\\s*\\d{1,5}){0,7}\\s*" list="weapon-sockets" class="dummy-input" data-dummy="${escape(p.id)}" aria-label="Dummy IDs for ${escape(p.name)}, model 0 first" title="One ID moves every model. A list such as 20, 30 sets model 0, model 1." placeholder="20, 30" value="${escape(custom?value.slice(6).replace(/,/g,', '):'')}" ${custom?'':'hidden'}>`;
}
function bindWeaponControls(){
 $('parts').querySelectorAll('[data-weapon]').forEach(select=>select.addEventListener('change',()=>{
  config.weaponAttachments||={};const input=$('parts').querySelector(`[data-dummy="${select.dataset.weapon}"]`);input.hidden=select.value!=='custom';
  if(select.value==='custom'&&!input.value)input.value=currentGame()==='sekiro'?'20':'20, 30';
  config.weaponAttachments[select.dataset.weapon]=select.value==='custom'?'dummy:'+input.value.replace(/\s+/g,''):select.value;saveSoon();
 }));
 $('parts').querySelectorAll('[data-dummy]').forEach(input=>input.addEventListener('change',()=>{
  if(!input.value.trim()||!input.checkValidity())return toast('Enter one dummy ID, or a comma list such as 20, 30 for model 0, model 1.',true);
  config.weaponAttachments||={};config.weaponAttachments[input.dataset.dummy]='dummy:'+input.value.replace(/\s+/g,'');saveSoon();
 }));
}
function updateAssembly(){
 const enabled=$('includeCharacter')?.checked;
 const selected=enabled?parts.filter(p=>p.selected):[],roles=['Head','Arms / prosthetic','Torso','Legs'],count=roles.filter(r=>selected.some(p=>p.role===r)).length;
 const wolf=isWolfAssembly(),player=$('preset').value==='player',model=selected.find(p=>/^c\d{4}$/i.test(p.id));
 $('assembly-title').textContent=!enabled?'Animation rig only':wolf&&count===4?'Wolf, assembled':model?model.name+' selected':selected.length?'Character preview':'Choose a character';
 $('assembly-subtitle').textContent=!enabled?'No character mesh will be added.':selected.length?`${selected.length} selected model${selected.length===1?'':'s'} · one animation rig`:'Player outfit parts or an NPC model.';
 $('assembly-id').textContent=wolf||player?'C0000':model?model.name:'NPC / CUSTOM';
 $('rig-caption').textContent=wolf||player?'ONE RIG · MODULAR PARTS':'ONE RIG · CHARACTER MODEL';
 $('assembly-count').innerHTML=wolf?count+'<span>/ 4</span>':selected.length+'<span>MODEL'+(selected.length===1?'':'S')+'</span>';
 $('assembly-tags').innerHTML=wolf?roles.map((r,i)=>`<span class="${selected.some(p=>p.role===r)?'present':''}">${['Head','Arms','Torso','Legs'][i]}</span>`).join(''):`<span class="${selected.length?'present':''}">${player?'Player outfit':'NPC / custom'}</span><span>${escape(gameNames[currentGame()]||'Any model count')}</span>`;
}
async function checkEnvironment(){
 $('check-environment').disabled=true;
 try{
  config=values();await api('settings',config);const env=await api('environment');
  $('environment-cards').innerHTML=env.map(e=>`<div class="environment-card"><span><i class="dot ${e.ready?'green':''}"></i>${e.ready?'READY':'SETUP NEEDED'}</span><h3>${escape(e.title)}</h3><p>${escape(e.detail)}</p></div>`).join('');
  const b=env.find(e=>e.key==='blender');$('blender-ready').innerHTML=`<i class="dot ${b.ready?'green':''}"></i><span>${b.ready?'Blender executable selected':'Choose Blender in Settings'}</span><button class="text-button" data-page="settings">Change</button>`;
  $('setup-dot').classList.toggle('green',env.every(e=>e.ready));
 }catch(e){toast(e.message,true);}finally{$('check-environment').disabled=false;}
}
function requireFields(keys){
 for(const key of keys){if(!$(key).value.trim()){if(key==='blender')showPage('settings');const field=$(key);field.closest('.path-row')?.classList.add('invalid');field.scrollIntoView({behavior:'smooth',block:'center'});field.focus();throw Error(`Choose ${help[key]?.[0].toLowerCase()||key} first.`);}}
}
async function start(mode){
 try{
  if(mode==='import'&&folderMode()){
   if(folderBusy||resolvingClip||!catalog||catalogPath!==config.assetCatalog||!samePath(catalog.folder,$('assetFolder').value.trim()))throw Error('Scan the selected folder and choose an animation first.');
   const clip=catalog.clips.find(c=>c.id===$('assetClip').value);if(!clip?.ready)throw Error(clip?.issues.join('\n')||'Choose an animation first.');
  }
  requireFields(mode==='import'?['blender','animation','skeleton','outputBlend']:mode==='inspect'?['blender','inputBlend']:['blender','inputBlend','outputHKX']);
  if(mode==='import'&&$('includeCharacter').checked){
   if(!parts.length&&$('characterSource').value)await scanSource();
   if(!parts.some(p=>p.selected))throw Error('Select one or more character parts, or switch to Rig only.');
  }
  if(mode==='export'){
   if($('frameRange').value==='custom'&&!(parseFloat($('frameEnd').value)>parseFloat($('frameStart').value))){$('sampling-options').open=true;throw Error('Enter a custom frame range whose end frame is after its start frame.');}
   const rate=$('frameRate').value.trim(),tolerance=$('tolerance').value.trim();
   if(rate&&!(+rate>=1&&+rate<=240)){$('sampling-options').open=true;throw Error('Choose an output frame rate between 1 and 240 fps, or leave it empty for the source rate.');}
   if(!$('spline-options').hidden&&tolerance&&!(+tolerance>=1e-6&&+tolerance<=.1))throw Error('Spline tolerance must be between 0.000001 and 0.1.');
  }
  config=values();const request={...config,mode};if(mode!=='inspect')request.force=$(mode+'-force').checked;job=await api('job',request);initiatedJobs.add(job.id);updateJob(job);toast({import:'Creating your Blender scene…',export:'Exporting your animation…',inspect:'Reading the scene in Blender…'}[mode]);
 }catch(e){toast(e.message,true);}
}
function updateJob(value){
 if(!value)return;job=value;
 const running=value.status==='running',success=value.status==='success',error=value.status==='failed';
 document.body.classList.toggle('busy',running);$('run-import').disabled=running;$('run-export').disabled=running;$('scan-folder').disabled=running;$('inspect-scene').disabled=running;
 $('cancel-job').hidden=!running;$('activity').classList.toggle('error',error);$('activity').classList.toggle('success',success);
 $('job-message').textContent=value.message;$('job-status').textContent=running?'RUNNING':value.status.toUpperCase();
 const seconds=Math.max(0,Math.floor((value.ended||Date.now()/1000)-value.started));$('job-time').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
 $('progress-track').hidden=false;$('progress-fill').style.width=(success?100:value.progress)+'%';
 const stages=value.mode==='discover'?[['inventory','Scan archives'],['done','Choose animation']]:value.mode==='inspect'?[['validate','Check'],['blender','Read scene'],['done','Ready']]:value.mode==='import'?[['validate','Check'],['decode','Decode'],['character','Character'],['blender','Blender'],['done','Ready']]:[['validate','Check'],['blender','Sample'],['write','Write HKX'],['done','Ready']];
 const index=stages.findIndex(s=>s[0]===value.stage);$('job-stages').hidden=false;$('job-stages').innerHTML=stages.map((s,i)=>`<span class="${i<index||success?'complete':i===index?'current':''}">${i<index||success?'✓':'○'} ${s[1]}</span>`).join('');
 const pre=$('log'),atBottom=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-40;pre.textContent=value.logs.join('\n')||'Starting…';if(atBottom)pre.scrollTop=pre.scrollHeight;
 if(error){$('log-panel').hidden=false;$('toggle-log').setAttribute('aria-expanded','true');}
 $('result').hidden=!success;
 if(success&&value.mode==='discover'){
  if($('result').dataset.job!==value.id){
   $('result').dataset.job=value.id;const r=value.report||{};
   $('result').innerHTML=`<div class="result-info"><b>Folder scan complete</b><p>${escape(r.clips)} animations · ${escape(r.characters)} characters. Choose a clip above, then create your Blender scene.</p></div>`;
  }
  if(!loadedScans.has(value.id)&&samePath($('assetFolder').value.trim(),value.report.folder)){loadedScans.add(value.id);loadFolderCatalog(value.output,value.report.folder);}
  return;
 }
 if(success&&value.mode==='inspect'){
  if($('result').dataset.job!==value.id){
   $('result').dataset.job=value.id;const info=value.report?.scene;
   if(info&&samePath(value.output,$('inputBlend').value.trim())){sceneInfo=info;renderScene();}
   $('result').innerHTML=`<div class="result-info"><b title="${escape(value.output)}">${escape(basename(value.output))}</b><p>${escape(info?`Rig ${info.rig} · ${info.actions.length} armature action${info.actions.length===1?'':'s'} · choose the action and frames below`:'Scene read')}</p></div>`;
  }
  return;
 }
 if(success&&$('result').dataset.job!==value.id){
  $('result').dataset.job=value.id;const r=value.report||{};let details;
  if(value.mode==='import')details=`${r.frames} frames · ${r.parts} model parts · ${r.textures} material images`;
  else{
   const readback=r.readback;
   details=`${r.frames} frames${r.frameRate?' at '+formatNumber(r.frameRate)+' fps':''} · ${r.tracks} tracks · ${r.compression}${r.compression==='spline'&&r.quantization?' '+r.quantization:''}${r.bytes?` · ${Math.ceil(r.bytes/1024)} KB`:''}`;
   if(readback)details+=` · readback max ${readback.maxRotationDegrees.toFixed(3)}°, ${(readback.maxTranslation*1000).toFixed(2)} mm${readback.maxRotationDegrees>.5||readback.maxTranslation>.005?' (may be visible; lower the spline tolerance)':''}`;
  }
  const warnings=r.warnings?.length?` · ${r.warnings.length} ${value.mode==='import'?'material':'export'} notice${r.warnings.length===1?'':'s'} (see Activity)`:'';
  $('result').innerHTML=`<div class="result-info"><b title="${escape(value.output)}">${escape(basename(value.output))}</b><p>${escape(details+warnings)}</p></div>${value.mode==='import'?`<button class="secondary" data-open="blender">${icon('play')}Open Blender</button>`:''}<button class="secondary" data-open="reveal">${icon('folder')}Show file</button>`;
  $('result').querySelectorAll('[data-open]').forEach(el=>el.addEventListener('click',()=>openOutput(el.dataset.open,value.output)));
  if(value.mode==='import'){if(!samePath($('inputBlend').value.trim(),value.output))forgetScene();$('inputBlend').value=value.output;config.inputBlend=value.output;config.lastImportedBlend=value.output;saveSoon();}
  if(value.mode==='import'&&$('openWhenDone').checked&&initiatedJobs.has(value.id)&&!opened.has(value.id)){opened.add(value.id);openOutput('blender',value.output);}
 }
}
async function openOutput(action,path){try{await api('open',{action,path});}catch(e){toast(e.message,true);}}
async function poll(){
 try{const state=await api('state');if(state.job)updateJob(state.job);$('connection-text').textContent='On this computer';$('connection-text').previousElementSibling.classList.add('green');}
 catch(e){$('connection-text').textContent='Workspace disconnected';$('connection-text').previousElementSibling.classList.remove('green');}
 pollTimer=setTimeout(poll,job?.status==='running'?800:1800);
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-page]');if(button)showPage(button.dataset.page);});
document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();showPage('import');});
document.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>pick(b.dataset.pick)));
$('cancel-picker').addEventListener('click',cancelPicker);
document.querySelectorAll('[data-help]').forEach(b=>{b.title=help[b.dataset.help][0];b.addEventListener('click',()=>{$('help-title').textContent=help[b.dataset.help][0];$('help-text').textContent=help[b.dataset.help][1];$('help-dialog').showModal();});});
document.querySelectorAll('[data-config]').forEach(el=>el.addEventListener('change',()=>{
 el.closest('.path-row')?.classList.remove('invalid');
 if(el.id==='includeCharacter')toggleCharacter();if(el.id==='inputMethod')toggleInputMethod();
 if(el.id==='assetFolder')invalidateFolder();
 if(el.id==='game'&&folderMode()&&catalog){config.assetCharacter='';config.assetClip='';$('assetCharacter').innerHTML='';renderCharacters();resolveClip();}
 if(el.id==='preset'&&folderMode())resolveClip();else if(el.id==='characterSource'||el.id==='preset')scanSource();
 if(el.id==='animation'||el.id==='skeleton'||el.id==='compendium'){if(!folderMode())$('skeletonCompendium').value='';}
 if(el.id==='inputBlend')forgetScene();
 if(['exportAction','frameRange','frameStart','frameEnd','frameRate','trackSet','rootMotion','rootBone','exportGame'].includes(el.id))updateExportOptions();
 saveSoon();
}));
['frameStart','frameEnd','frameRate','rootBone'].forEach(id=>$(id).addEventListener('input',updateExportOptions));
$('inspect-scene').addEventListener('click',()=>start('inspect'));
$('scan-folder').addEventListener('click',scanFolder);
$('assetCharacter').addEventListener('change',()=>{config.assetClip='';$('clip-filter').value='';renderClips();resolveClip();});
$('assetClip').addEventListener('change',()=>resolveClip());
$('clip-filter').addEventListener('input',()=>{renderClips();resolveClip();});
document.querySelectorAll('[name="format"]').forEach(el=>el.addEventListener('change',()=>{updateExportOptions();saveSoon();}));
['import-force','export-force'].forEach(id=>$(id).addEventListener('change',()=>{config.force=$(id).checked;saveSoon();}));
$('scan').addEventListener('click',()=>scanSource());$('add-models').addEventListener('click',()=>pick('models',true));
$('run-import').addEventListener('click',()=>start('import'));$('run-export').addEventListener('click',()=>start('export'));
$('check-environment').addEventListener('click',checkEnvironment);
$('cancel-job').addEventListener('click',async()=>{try{updateJob(await api('cancel',{}));}catch(e){toast(e.message,true);}});
$('toggle-log').addEventListener('click',()=>{$('log-panel').hidden=!$('log-panel').hidden;$('toggle-log').setAttribute('aria-expanded',String(!$('log-panel').hidden));});
$('copy-log').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('log').textContent);toast('Activity log copied.');}catch(e){toast('Select the activity text and press Ctrl+C.');}});
$('close-help').addEventListener('click',()=>$('help-dialog').close());$('help-ok').addEventListener('click',()=>$('help-dialog').close());
$('help-dialog').addEventListener('click',e=>{if(e.target===$('help-dialog'))$('help-dialog').close();});
$('use-import').addEventListener('click',()=>{const path=job?.mode==='import'&&job.status==='success'?job.output:(config.lastImportedBlend||$('inputBlend').value);if(!path)return toast('Import an animation first, or browse to an existing scene.');if(!samePath($('inputBlend').value.trim(),path))forgetScene();$('inputBlend').value=path;saveSoon();toast('Imported scene selected.');});
$('shutdown').addEventListener('click',async()=>{try{await api('shutdown',{});clearTimeout(pollTimer);toast('Workspace closed. You can close this window.');$('connection-text').textContent='Workspace closed';document.querySelectorAll('button').forEach(b=>b.disabled=true);}catch(e){toast(e.message,true);}});
(async()=>{try{const state=await api('state');setValues(state.config);toggleInputMethod();if(folderMode()&&config.assetCatalog&&config.assetFolder)await loadFolderCatalog(config.assetCatalog,config.assetFolder);else if(config.characterSource)await scanSource(true);else if(config.models?.length){const scan=await api('scan',{files:config.models});parts=scan.parts;detectNpcModels();renderParts();}else renderParts();await checkEnvironment();if(state.job)updateJob(state.job);poll();}catch(e){toast('Could not connect to Animation Bridge. Reopen the UI launcher.\n'+e.message,true);}})();
