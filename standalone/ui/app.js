'use strict';
const $=id=>document.getElementById(id);
const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
try{const theme=localStorage.getItem('bridge-theme');if(theme==='light'||theme==='dark')document.documentElement.dataset.theme=theme;}catch(e){}
const ROW=36;
let config={}, parts=[], job=null, toastTimer, saveTimer, pollTimer, resolveTimer, activePicker=null, sceneInfo=null, lastSuggestedBlend='', autoMaterial='', autoBinder='', jobKey='', startJobId='', jobStarting=false;
let inputMethod='folder', sources=[], activeId='', catalog=null, catalogPath='', catalogLoading=false, characterId='', clipId='', clipView=[], archiveFor='', selection=null, resolving=false, resolveSequence=0, painting=false, extrasOpen=null;
let scanProblem=null, inventoryProblem=null;
let editing=null, detection=null, detectSequence=0, nameTouched=false, scenesTouched=false, dialogLayout='auto', dialogFolders={}, missingFolders=new Set(), removeTimer;
const handledJobs=new Set(), opened=new Set(), initiatedJobs=new Set(), jobSources=new Map(), jobCharacters=new Map();
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=name=>`<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const basename=p=>(p||'').split(/[\\/]/).pop();
const norm=p=>String(p||'').replace(/[\\/]+/g,'/').replace(/\/$/,'').toLowerCase();
const samePath=(a,b)=>norm(a)===norm(b);
const joinPath=(folder,name)=>String(folder||'').replace(/[\\/]+$/,'')+'\\'+name;
const relativeTo=(path,base)=>{const b=String(base||'').replace(/[\\/]+$/,'');return !b?path:samePath(path,b)?'.':norm(path).startsWith(norm(b)+'/')?path.slice(b.length+1):path;};
const plural=(n,word,many=word+'s')=>`${Number(n||0).toLocaleString('en')} ${Number(n)===1?word:many}`;
const formatNumber=value=>Number.isInteger(+value)?String(+value):(+value).toFixed(2);
const formatBytes=n=>n>=1e9?(n/1e9).toFixed(1)+' GB':n>=1e6?Math.round(n/1e6)+' MB':Math.max(1,Math.round((n||0)/1e3))+' KB';
const ago=time=>{const minutes=Math.round((Date.now()-time)/60000);return !time?'':minutes<1?'just now':minutes<60?minutes+' min ago':minutes<1440?Math.round(minutes/60)+' h ago':new Date(time).toLocaleDateString();};
const gameNames={sekiro:'Sekiro',ds1:'Dark Souls: Prepare to Die',ds1r:'Dark Souls Remastered',ds3:'Dark Souls III',er:'Elden Ring'};
const gameShort={sekiro:'SEK',ds1:'DS1',ds1r:'DSR',ds3:'DS3',er:'ER'};
// The bridge's game registry (standalone/games), from /api/state. The tables above are its FromSoftware games.
let gameProfiles={};
const exportable=game=>!!gameProfiles[game]?.capabilities?.export||(!Object.keys(gameProfiles).length&&game in gameShort);
const layoutNames={auto:'Detect',game:'Game folder',folder:'Collected folder',custom:'Custom layout'};
const kinds=[['animations','Animations','ANIBND'],['characters','Character models','CHRBND · FLVER'],['parts','Parts','PARTSBND'],['textures','Textures','TEXBND · TPF'],['materials','Material library','MTDBND · MATBINBND']];
const help={
 source:['Sources','A source is a folder the bridge reads game files from: an unpacked game, a mod folder in the game’s own structure, or a folder of archives you collected. Add as many as you like and switch between them; each one remembers its layout, game and your last selection.\n\nSource files are only read. Extracted animation inputs are cached in the bridge’s work folder, and scenes are saved where you choose.'],
 sourceGame:['Source game','Auto detect identifies the game by its executable (sekiro.exe, DarkSoulsIII.exe, eldenring.exe, DarkSoulsRemastered.exe or DarkSouls.exe), by Elden Ring’s MATBIN library, or by the authoring paths and Havok version inside one small animation archive. Choose the game yourself for a mod folder without an executable.\n\nA game folder or custom layout holds one game. A collected folder can mix games and keeps each game’s characters apart.'],
 layout:['Layout','Detect looks for the game’s own structure: a chr folder with ANIBND archives in the chosen folder, in its Game or DATA subfolder, or above a chosen chr, parts, mtd or material folder. Otherwise it reads the folder as a collected folder.\n\nGame folder reads chr for animations and character models, parts for outfits and weapons, chr and parts for textures, and mtd or material for the material library. Characters are listed by archive name at once; a character’s archives are read when you choose it, and again when they change.\n\nCollected folder reads every archive below the folder. Files that share a folder belong together.\n\nCustom layout names the folders for each kind yourself, relative to the source or absolute, for example animations from a mod and models from the unpacked game. When folders of one kind hold a file of the same name, the first folder wins, the way a mod overrides the game: add the mod’s folders first.'],
 fileList:['File list','RE Engine games such as Devil May Cry 5 keep their files in PAK archives, which store a number for each file instead of its name. A file list gives the names back: it is a text file with one path per line, such as DMC5_STM_Release.list from the community’s RE Engine file lists. The bridge reads only the character files it needs from the archives and keeps them in its cache; the game folder is never changed.\n\nA folder that holds an extracted natives folder needs no list.'],
 scenes:['Scenes folder','New Blender scenes are suggested here as character_animation.blend. A collected folder suggests its own Blender subfolder; a game or mod folder suggests Documents\\Animation Bridge\\<source name>. Scenes cannot be saved inside a game installation. You can still type any path in Save scene as.'],
 game:['Source game','Auto detect reads the actual Havok version and original archive paths. For a loose DS3 packfile, select Dark Souls III explicitly because other games share Havok 2014. Havok 2015 tagfiles are identified as Dark Souls Remastered. Sources in the library have their own game setting.'],
 exportGame:['Export source game','Normally leave this on Stored in scene. Version 0.5 remembers the original game and writes its native Havok version. Older scenes lack this information: select the game they came from, or import them again. This selector cannot convert a new scene into another game’s skeleton; use the retargeting workflow for that.'],
 assetClip:['Choose an animation','An archive can contain hundreds of animations, so choose which clip to import. The archive name tells duplicate clip names apart, and the archive filter shows one split archive at a time. A clip marked with a warning is missing inputs; the scene panel lists them. The skeleton always comes from the character the clip was made for.\n\nThe arrow keys, Page Up, Page Down, Home and End move through the list. Press / to search.'],
 skeletonCompendium:['Separate skeleton compendium','Optional compendium for the skeleton if it differs from the animation’s compendium. The source library fills this in using the type IDs stored inside the HKX files. For individual files, leave it empty to use the animation’s matching compendium.'],
 oodle:['Oodle library','KRAK-compressed DCX files use oo2core_6_win64.dll from your own Sekiro installation. This tool searches Steam libraries and the conversion environment automatically. Browse to the DLL here if it cannot be found. It is loaded in place and is not copied into the release ZIP. DFLT decompression uses Python’s built-in zlib.'],
 referenceModel:['Rig attachment model','For separate weapons, include the same game’s c0000.chrbnd.dcx or its extracted c0000.flver. Sekiro uses its verified weapon profiles. DS1, Remastered, DS3 and Elden Ring place any weapon with the game’s default sockets: right hand, with a scabbard or extra model on the opposite hip. Weapon placement also offers left hand, two-handed, sheathed and custom dummy IDs. Skeleton names such as Master are accepted; the actual attachment bones are checked. This model supplies the attachment dummies: their bone, position and orientation. It has no visible body mesh and is not selected as a character part. A source finds it automatically when it holds c0000.chrbnd.dcx.'],
 animation:['Animation HKX','Choose an animation extracted from the character’s animation binder with WitchyBND. Wolf and NPC animations are supported, in spline-compressed or interleaved HKX format. Edit the animation on the rig in Blender.'],
 compendium:['Matching compendium','Many original Sekiro HKX files share their type information through a compendium. Choose the .compendium from the same animation binder as the HKX. Leave this empty for a self-contained exported HKX.'],
 skeleton:['Skeleton HKX','Choose skeleton.hkx from this character’s animation binder, normally chr/cXXXX.anibnd.dcx. NPC skeletons may require the matching compendium too. This supplies the rest pose and bone hierarchy. The character-named HKX in a model binder can contain collision data.'],
 characterSource:['Character assets','For NPCs, choose a folder containing the character’s .chrbnd(.dcx) or extracted .flver(.dcx). One model is enough. Player outfit / modular parts selects unambiguous available outfit pieces. c0000 is the player ID in several games; it does not imply Wolf. A source in the library finds models itself.\n\nFor Wolf, choose the parts folder and an outfit. Standard Wolf uses FC_M_0200, AM_M_9000, BD_M_9000 and LG_M_9000. c0000.flver itself has no visible mesh.'],
 materialBinder:['Material library','MTD games can store texture paths and UV assignments in material definitions. Elden Ring uses MATBIN: provide material/allmaterial.matbinbnd.dcx; its old MTD library does not provide the active assignments. MATBIN definitions are matched by stem even when the model refers to .matxml or .mtd. A source finds the library in its material folders; a path you enter here is kept for that source.\n\nThe preview resolves each material’s base-color and normal map. It approximates Sekiro’s layered shaders and does not simulate Havok cloth.'],
 textureDirectory:['Additional textures','Optional folder containing .texbnd(.dcx), .tpf(.dcx) packages or extracted images. NPC texture IDs can differ from their model ID: Owl c5060 uses c5069.texbnd.dcx and shared common_body.tpf.dcx. A game folder finds such packages in chr and parts by the IDs its models and materials name; a collected folder reads the clip’s folder. A binder’s own TPF files are also read automatically.'],
 outputBlend:['Blender scene','Choose a new .blend filename. The imported action, original animation metadata, rigged character parts and used texture images are saved in the scene. Images are packed, so you can move the .blend file. Existing output is replaced only when the checkbox is enabled. A source suggests a name in its scenes folder.'],
 inputBlend:['Edited Blender scene','Choose a .blend scene created by this tool, or one where the retarget add-on baked motion onto a bridge rig. Save your changes in Blender first. Read actions lists the scene’s armature actions and frame ranges without changing the file.'],
 exportAction:['Action','The active action is the one assigned to the rig when the scene was saved. Read actions lists every action that keys this rig’s bones, with its frame range, so you can export another take without reassigning it in Blender. With the retarget add-on’s control rig on the armature, only actions that animate its controls are listed, because the game bones follow the controls. A matching root-motion action, named like the importer’s _RootMotion or the retarget add-on’s RootMotion action, is used with it. Actions that another armature in the scene plays, such as a retarget donor’s, are left out.'],
 donor:['Retarget donor','A donor is a second animation that the import places beside this character, so the retarget add-on can bake it onto this one without a second import. Choose the donor’s animation from any source or game and pin it, then choose the animation of the character that receives it.\n\nThe scene keeps the receiving character’s frame range, frame rate and export settings, so it exports as a single-character scene does. The donor’s rig, model, actions and HKX metadata are named Donor and stand to its side. In Blender, the retarget add-on fills in Source and Target by itself: Match bones and Bake come next.\n\nRemove the donor to import one character again.'],
 frameRange:['Frame range','Scene start to end uses the scene’s frame range; import and the retarget add-on set it to the clip length. Action keyframe range follows the chosen action’s first and last keys. Imported clip length samples frame 1 to the original frame count. Custom takes any start and end frame.\n\nThe pose is sampled by time. If the scene frame rate differs from the output rate, samples fall between frames and are interpolated.'],
 trackSet:['Tracks','Source clip tracks keeps the original track list. This is the safest choice: bones without a track stay under the game’s control, for example face, cloth or weapon bones driven by other animation layers.\n\nSource tracks + keyed bones adds the bones keyed in the chosen action. Every skeleton bone writes a track for each bone and holds unkeyed bones in their Blender pose. Added tracks follow the original ones, so existing track indices stay the same.'],
 frameRate:['Frame rate','Samples per second in the HKX. Leave this empty to keep the source clip’s rate, normally 30. The clip duration stays the same; a higher rate only adds samples. TAE event times are in seconds, so they stay aligned.'],
 rootMotion:['Root motion','Root motion moves the character’s capsule in game.\n\nHKX_RootMotion empty exports the empty created by the importer or the retarget add-on, when the scene has one. Extract from a bone’s travel turns a bone’s movement into root motion and removes that travel from the body, so the pose looks the same in game. The default is the bone that carries the whole body: Root, RootPos or Master, depending on the rig. Ground travel is extracted by default; include vertical travel for jumps or climbs, and turning for animations that change direction. No root motion writes none, even if the source clip had it.'],
 quantization:['Rotation precision','How spline compression stores rotations. 40-bit is the default. 48-bit is finer at a slightly larger size. Full floats store rotations without quantization. Interleaved output is not affected.'],
 tolerance:['Spline tolerance','The largest difference the spline compressor accepts while fitting curves, from 0.000001 to 0.1. Smaller values keep more detail and make larger files. The default is 0.001. With Read the HKX back enabled, the export reports the actual difference.'],
 outputHKX:['HKX output','Export writes a raw HKX and an adjacent .motion.json sidecar. Use WitchyBND to replace the animation member in a copy of your binder. Model geometry, TAE events and unrelated HKX metadata are not exported.\n\nRead the HKX back decodes the written file again and reports the largest rotation and translation differences from the sampled pose.'],
 partAnimations:['Animate weapon parts','Some weapons animate their own bones: the Loaded Umbrella opens, the Loaded Axe and Loaded Spear move, the Mortal Blade’s sheath turns. Their part binder holds an animation binder for the model, such as WP_A_0760_1.anibnd, with clips named after the character’s animation IDs.\n\nThe import keys each chosen weapon with the clip of the same ID. Where the character’s TAE gives several IDs one body clip, such as a076_412000 playing a070_412000, the part plays the clip of the ID in its own category. A part without a clip for the animation keeps its rest pose. The preview lists which clip each part plays.\n\nTAE events that hide a weapon or move it to another dummy are not applied.'],
 partView:['Part animations','Starts from a Sekiro weapon part: choose one on the left to list its clips, then one of its clips to list the player animations it plays in, each with the reason. The reason is the same animation ID, an ID that the part’s own TAE gives that clip, or an ID that the player’s TAE gives the same body clip, such as a076_412000 playing a070_412000. This is the import’s own pairing, read the other way round.\n\nChoosing an animation selects it and the weapon part for import, and turns on Animate weapon parts, so the scene keys the part with that clip. A part holds its rest pose, a999_000000, in every animation without a clip of its own; the rest pose is not listed.\n\nA game folder reads the player’s archives the first time. This view is shown for Sekiro sources only.'],
 addToBinder:['Add to an animation binder','Also puts the written HKX into an animation binder (ANIBND), so you need no WitchyBND step. The HKX and its .motion.json are still written under Save HKX as.\n\nWhen the binder holds a clip of the same name, that clip is replaced. Otherwise the HKX is added as a new clip, with the ID and folder that the binder’s other clips follow. A new animation ID needs a TAE entry and something that plays it before the game uses it.\n\nBefore its first change, the binder is copied to a .bak file beside it. Weapon part clips are not added; they are written beside the HKX.'],
 binder:['Animation binder','The .anibnd.dcx to add the HKX to. Read actions fills in the archive that the clip was imported from. Files in the game installation are protected, so for a clip from the game folder it suggests a copy of that archive in the HKX’s folder, made from the game’s archive the first time. Point it at the same file in your mod folder to change your mod directly.\n\nScenes imported before bridge 0.13 do not record their archive; choose it yourself.'],
 binderMember:['Name in the binder','The clip’s member name, such as a050_002000.hkx. Empty: the clip’s own name, which replaces the original clip. A name the binder does not hold yet adds a new animation.'],
 exportParts:['Export part animations','Also writes the clip of each animated weapon part in the scene, sampled from its weapon rig over the same frames as the character. Each file keeps the part clip’s member name, such as a076_405010_1.hkx, and its own frame rate; the format and settings follow the character’s HKX.\n\nReplace the file in the part’s animation binder with WitchyBND: for example WP_A_0760_1.anibnd inside parts/wp_a_0760.partsbnd.dcx. The bridge does not repack archives. Part clips are not yet tested in game.'],
 blender:['Blender executable','Choose blender.exe from your Blender installation. Version 4.5.14 is checked locally. The scripts use Blender’s built-in Python APIs and require no add-on. Compatibility with 5.2 still needs a run on that version.'],
 writer:['Conversion Python','Choose python.exe from the writer environment, normally %LOCALAPPDATA%\\SekiroAnimationBridge\\writer-env\\Scripts\\python.exe. The bridge creates it on the first start with Soulstruct, Soulstruct Havok and NumPy; tools/setup_writer.cmd repeats that setup. Blender’s bundled Python stays separate.'],
 packages:['Game packages','A game package teaches the bridge one more engine: how to find its games, list their animations and read clips and characters. Devil May Cry 5 is in the RE Engine package, a separate download beside each release.\n\nInstall package… reads the ZIP first and shows its name, games, tools and author. Nothing in it runs until you confirm, and nothing is downloaded. The package goes into %LOCALAPPDATA%\\SekiroAnimationBridge\\packages. A package runs its own code with your rights, like any program, so install packages only from people you trust.\n\nRemove deletes the package folder. Your sources stay; a source of a removed game cannot be scanned until you install the package again.'],
 decoder:['HKX decoder','Release ZIPs include SekiroMotionDecoder.exe in their decoder folder, and the bridge selects it automatically. In a source checkout, build it with tools/SekiroMotionDecoder/build_decoder.cmd; that path is under %LOCALAPPDATA%\\SekiroAnimationBridge\\decoder. Version 0.5 handles tagfiles, native PC packfiles, spline/interleaved animations and separate animation/skeleton compendiums.']
};
const pickTitles={package:'Game package ZIP',models:'Model files','src-path':'Source folder','src-scenes':'Scenes folder','src-list':'File list',folder:'Folder'};
// The game selects and the source-game help come from the registry, so a new game needs no change here.
function applyGames(list){
 if(!Array.isArray(list)||!list.length)return;
 gameProfiles=Object.fromEntries(list.map(g=>[g.id,g]));
 for(const g of list){gameNames[g.id]=g.name;gameShort[g.id]=g.short;}
 const options=(games,suffix='')=>games.map(g=>`<option value="${escape(g.id)}">${escape(g.name+(g.verified?'':' · untested')+suffix)}</option>`).join('');
 const first=id=>$(id).querySelector('option[value="auto"]').outerHTML;
 // Individual files are Havok files; export writes the games whose format the bridge writes.
 $('game').innerHTML=first('game')+options(list.filter(g=>g.engine==='fromsoft'));
 $('exportGame').innerHTML=first('exportGame')+options(list.filter(g=>g.capabilities?.export),' · legacy scene');
 $('src-game').innerHTML=first('src-game')+options(list);
 help.sourceGame[1]='Auto detect identifies the game by what the folder holds:\n'+list.map(g=>`• ${g.name}: ${g.hint}`).join('\n')+'\n\nChoose the game yourself for a mod folder without an executable. A game folder or custom layout holds one game. A collected folder can mix FromSoftware games and keeps each game’s characters apart.'+(list.some(g=>!g.verified)?'\n\nGames marked untested are supported by their engine but were not yet checked with the game’s own files.':'');
}
const filters={'src-list':'File list (*.list)|*.list|All files (*.*)|*.*',package:'Game package (*.zip)|*.zip',animation:'Havok animation (*.hkx)|*.hkx|All files (*.*)|*.*',skeleton:'Havok skeleton (*.hkx)|*.hkx|All files (*.*)|*.*',compendium:'Havok compendium (*.compendium)|*.compendium|All files (*.*)|*.*',skeletonCompendium:'Havok compendium (*.compendium)|*.compendium|All files (*.*)|*.*',blender:'Blender executable (blender.exe)|blender.exe|Executables (*.exe)|*.exe',writer:'Python executable (python.exe)|python.exe|Executables (*.exe)|*.exe',decoder:'Animation decoder (*.exe)|*.exe',oodle:'Oodle library (oo2core_6_win64.dll)|oo2core_6_win64.dll',materialBinder:'Material library (*.mtdbnd*;*.matbinbnd*;*.mtd;*.matbin)|*.mtdbnd;*.mtdbnd.dcx;*.matbinbnd;*.matbinbnd.dcx;*.mtd;*.matbin|All files (*.*)|*.*',referenceModel:'Model files (*.chrbnd*;*.flver*)|*.chrbnd;*.chrbnd.dcx;*.flver;*.flver.dcx|All files (*.*)|*.*',outputBlend:'Blender scene (*.blend)|*.blend',inputBlend:'Blender scene (*.blend)|*.blend',outputHKX:'Havok animation (*.hkx)|*.hkx',binder:'Animation binder (*.anibnd.dcx;*.anibnd)|*.anibnd.dcx;*.anibnd|All files (*.*)|*.*',models:'Model files (*.flver;*.flver.dcx;*.partsbnd;*.partsbnd.dcx;*.chrbnd.dcx)|*.flver;*.flver.dcx;*.partsbnd;*.partsbnd.dcx;*.chrbnd.dcx|All files (*.*)|*.*'};

async function api(path,data,signal){
 const response=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'X-Bridge-Token':token,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data),signal});
 const result=await response.json(); if(!response.ok)throw Error(result.error||'The workspace could not complete the request.'); return result;
}
// A modal dialog sits in the top layer; status messages move into it to stay visible.
function layer(el){const host=[...document.querySelectorAll('dialog[open]')].pop()||document.body;if(el.parentElement!==host)host.append(el);}
function toast(message,error=false){clearTimeout(toastTimer);layer($('toast'));$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,error?13000:4200);}

const pageTitles={import:['FROM GAME TO BLENDER','Import animation'],export:['FROM BLENDER TO GAME','Export animation'],sources:['WHERE FILES COME FROM','Sources'],settings:['THIS COMPUTER','Settings & setup']};
function currentPage(){return document.querySelector('.page.active')?.id.slice(5)||'import';}
function showPage(page){
 document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));
 document.querySelectorAll('.rail-item[data-page]').forEach(el=>{const on=el.dataset.page===page;el.classList.toggle('active',on);if(on)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 [$('page-eyebrow').textContent,$('page-title').textContent]=pageTitles[page];
 updateTopbar();closeSourceMenu();if(page==='import')requestAnimationFrame(paintClips);
 if(page==='settings')measureCache();
}
function updateTopbar(){const page=currentPage();$('source-switch').hidden=!(page==='sources'||page==='import'&&inputMethod==='folder');}

function values(){
 const result={...config}; document.querySelectorAll('[data-config]').forEach(el=>result[el.id]=el.type==='checkbox'?el.checked:el.value.trim());
 result.format=document.querySelector('[name="format"]:checked')?.value||'interleaved';
 result.models=parts.filter(p=>p.selected).map(p=>p.path);
 result.inputMethod=inputMethod;result.sources=sources;result.activeSource=activeId;
 const source=activeSource();
 if(inputMethod==='folder'&&source){
  Object.assign(result,{assetFolder:source.root||source.path,assetCatalog:source.catalog||'',sourceLayout:source.resolved||source.layout,sourceFolders:source.folders||{},sourceRecursive:source.recursive!==false,sourceFileList:source.fileList||'',game:source.game||'auto',assetCharacter:characterId,assetClip:clipId});
 }
 return result;
}
function rememberState(){
 const source=activeSource();if(!source||inputMethod!=='folder'||!catalog||catalogLoading)return;
 source.state={...source.state,character:characterId,clip:clipId,models:parts.filter(p=>p.selected).map(p=>p.path),preset:$('preset').value,outputBlend:$('outputBlend').value.trim(),suggested:lastSuggestedBlend};
}
function saveSoon(){clearTimeout(saveTimer);saveTimer=setTimeout(async()=>{rememberState();config=values();try{await api('settings',config);}catch(e){toast(e.message,true);}},450);}
const selectDefaults={preset:'auto',game:'auto',exportGame:'auto',frameRange:'scene',trackSet:'original',rootMotion:'auto',quantization:'threecomp40'};
function setValues(data){
 config=data;config.modelMasks||={};sources=Array.isArray(data.sources)?data.sources:[];activeId=sources.some(s=>s.id===data.activeSource)?data.activeSource:(sources[0]?.id||'');
 renderActions(data.exportAction||'');
 document.querySelectorAll('[data-config]').forEach(el=>{if(el.type==='checkbox')el.checked=!!data[el.id];else el.value=data[el.id]||selectDefaults[el.id]||'';});
 document.querySelectorAll('[name="format"]').forEach(el=>el.checked=el.value===data.format);
 $('import-force').checked=!!data.force;$('export-force').checked=!!data.force;
 applyTheme(data.theme||'auto');applyCacheMode(data.previewCache);toggleCharacter();updateExportOptions();
}
function applyCacheMode(mode){
 mode=mode==='aggressive'?mode:'standard';
 document.querySelectorAll('[data-cache-choice]').forEach(b=>{const on=b.dataset.cacheChoice===mode;b.classList.toggle('active',on);b.setAttribute('aria-checked',String(on));});
 $('cache-mode-note').textContent=mode==='aggressive'
  ?'Prepares every clip of the list, two at a time, nearest to the selection first. Keeps up to 2 GB of previews. Uses more processor time while the list is open.'
  :'Prepares the two clips on each side of the selected one. Keeps up to 256 MB of previews.';
}
function applyTheme(theme){
 if(theme==='light'||theme==='dark')document.documentElement.dataset.theme=theme;else delete document.documentElement.dataset.theme;
 document.querySelectorAll('[data-theme-choice]').forEach(b=>{const on=b.dataset.themeChoice===theme;b.classList.toggle('active',on);b.setAttribute('aria-checked',String(on));});
 try{localStorage.setItem('bridge-theme',theme);}catch(e){}
}

/* Export page */
function selectedAction(){return sceneInfo?.actions.find(a=>a.name===($('exportAction').value||sceneInfo.activeAction));}
function renderActions(selected=$('exportAction').value){
 const actions=sceneInfo?.actions||[],missing=selected&&!actions.some(a=>a.name===selected);
 const options=[['',sceneInfo?.activeAction?'Active action · '+sceneInfo.activeAction:'Active action in the saved scene'],...actions.map(a=>[a.name,`${a.name} · frames ${formatNumber(a.frameStart)}–${formatNumber(a.frameEnd)}`])];
 if(missing)options.push([selected,selected+(sceneInfo?' · not in this scene':' · read actions to check')]);
 $('exportAction').innerHTML=options.map(([value,label])=>`<option value="${escape(value)}">${escape(label)}</option>`).join('');
 $('exportAction').value=selected||'';
 const chosen=$('exportAction').value;
 const item=(value,title,detail,chip='')=>`<button type="button" class="action-item${chosen===value?' selected':''}" role="radio" aria-checked="${chosen===value}" data-action="${escape(value)}"><span class="radio"></span><b>${escape(title)}</b>${chip}<small>${escape(detail)}</small></button>`;
 $('action-list').innerHTML=item('',sceneInfo?.activeAction?'Active action · '+sceneInfo.activeAction:'Active action','The action assigned to the rig when the scene was saved')
  +actions.map(a=>item(a.name,a.name,`Frames ${formatNumber(a.frameStart)}–${formatNumber(a.frameEnd)} · ${plural(a.keyedBones,'keyed bone')}${a.untracked?.length?` · ${a.untracked.length} outside the clip’s tracks`:''}`,a.active?'<span class="chip ok">Active</span>':'')).join('')
  +(missing?item(selected,selected,sceneInfo?'Not in this scene':'Read actions to check this name'):'')
  +(sceneInfo?'':'<div class="action-empty">Read actions to list every action in the scene with its frames.</div>');
}
function renderScene(){
 const info=sceneInfo;$('scene-info').hidden=!info;
 if(info){
  const count=info.actions.length;
  $('scene-info').innerHTML=`<b>${escape(`${info.rig} · ${gameNames[info.game]||'Game not recorded'} · ${info.clip}`)}</b>${escape(`Source clip: ${info.frameCount} frames at ${formatNumber(info.frameRate)} fps · ${info.trackCount} tracks · ${info.rootObject?'root motion empty '+info.rootObject.name:'no root motion empty'}`)}<br>${escape(`Scene frames ${info.scene.frameStart}–${info.scene.frameEnd} at ${formatNumber(info.scene.fps)} fps · ${count} armature action${count===1?'':'s'}`)}`;
  $('scene-info').classList.toggle('warn',!info.game);
  $('bone-names').innerHTML=info.bones.map(name=>`<option value="${escape(name)}">`).join('');
  $('rootBone').placeholder=info.defaultRootBone;
  $('binderMember').placeholder=info.clip||'The clip’s own name';
  const binder=suggestedBinder();
  if(binder&&(!$('binder').value.trim()||$('binder').value.trim()===autoBinder)){$('binder').value=binder;autoBinder=binder;saveSoon();}
 }
 renderActions();updateExportOptions();
}
function forgetScene(){sceneInfo=null;renderActions('');renderScene();}
// The archive the clip came from, or a copy of it beside the HKX where the game's own files are protected.
function suggestedBinder(){
 const archive=sceneInfo?.archive;if(!archive)return '';
 const output=$('outputHKX').value.trim();
 return sceneInfo.archiveWritable?archive:output?joinPath(output.replace(/[\\/][^\\/]*$/,''),basename(archive)):'';
}
function binderNote(){
 const binder=$('binder').value.trim(),name=$('binderMember').value.trim()||sceneInfo?.clip||'the clip’s own name',archive=sceneInfo?.archive||'';
 if(!binder)return sceneInfo&&!archive?'This scene does not record the archive its clip came from. Choose the binder.':'Choose the binder to add the HKX to.';
 const copy=archive&&!sceneInfo.archiveWritable&&!samePath(binder,archive)&&basename(binder).toLowerCase()===basename(archive).toLowerCase();
 return `${name} replaces the clip of that name in ${basename(binder)}, or is added with a new ID.`+(copy?` The first export makes ${basename(binder)} as a copy of the game’s archive, which stays unchanged.`:'')+' The binder is kept as a .bak before its first change.';
}
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
 const root=$('rootMotion').value,tracks=$('trackSet').value,range=$('frameRange').value;
 $('parts-note').hidden=!$('exportParts').checked;
 $('binder-fields').hidden=!$('addToBinder').checked;$('binder-note').textContent=binderNote();
 document.querySelectorAll('#range-buttons [data-range]').forEach(b=>{const on=b.dataset.range===range;b.classList.toggle('active',on);b.setAttribute('aria-checked',String(on));});
 $('custom-range').hidden=range!=='custom';$('root-bone-fields').hidden=root!=='bone';
 $('spline-options').hidden=document.querySelector('[name="format"]:checked')?.value!=='spline';
 $('range-note').textContent=rangeNote();
 const rootLabel={auto:'root empty',bone:'root from '+($('rootBone').value.trim()||sceneInfo?.defaultRootBone||'the body root'),none:'no root motion'}[root];
 $('sampling-summary').textContent=`${{original:'Source tracks',keyed:'Source + keyed bones',all:'Every bone'}[tracks]} · ${$('frameRate').value.trim()?$('frameRate').value.trim()+' fps':'source rate'} · ${rootLabel}`;
 const untracked=selectedAction()?.untracked||[];
 $('track-note').hidden=!(untracked.length&&tracks==='original');
 const gameMissing=!!sceneInfo&&!sceneInfo.game&&$('exportGame').value==='auto';
 const importOnly=!!sceneInfo?.game&&!exportable(sceneInfo.game);
 $('game-note').hidden=!gameMissing&&!importOnly;
 if(gameMissing)$('game-note').textContent='This scene was imported before the bridge recorded its game. Choose the game it came from.';
 if(importOnly)$('game-note').textContent=`The bridge imports ${gameNames[sceneInfo.game]||sceneInfo.game} but cannot write its animation format. To use this motion in a game the bridge exports, import a character from that game with this clip as the retarget donor, bake it in Blender with the Retarget add-on, and export that scene.`;
 if(untracked.length)$('track-note').textContent=`${untracked.length} keyed bone${untracked.length===1?' is':'s are'} not a track of the source clip: ${untracked.slice(0,6).join(', ')}${untracked.length>6?', …':''}. Choose “Source tracks + keyed bones” to export ${untracked.length===1?'it':'them'}.`;
}

/* Sources */
const activeSource=()=>sources.find(s=>s.id===activeId);
const sourceGame=s=>s.game&&s.game!=='auto'?s.game:(s.detectedGame||'');
const layoutLabel=s=>layoutNames[s.resolved||s.layout]||'Detect';
function sourceStats(s){const st=s.stats;if(!st)return s.catalog?'Scanned':'Not scanned yet';return st.layout==='folder'?`${plural(st.characters,'character')} · ${plural(st.clips,'animation')}`:`${plural(st.characters,'character')} · ${plural(st.archives,'archive')}`;}
function glyphInfo(s){const game=sourceGame(s)||(s.layout==='custom'?'custom':'');return [game,gameShort[game]||(s.name||'?').slice(0,2).toUpperCase()];}
const glyphHtml=s=>{const [game,text]=glyphInfo(s);return `<span class="glyph" data-game="${escape(game)}">${escape(text)}</span>`;};
function renderSourceSwitch(){
 const s=activeSource(),el=$('source-glyph');
 if(s){const [game,text]=glyphInfo(s);el.className='glyph';el.dataset.game=game;el.textContent=text;}else{el.className='glyph blank';el.dataset.game='';el.textContent='+';}
 $('source-name').textContent=s?s.name:'No source yet';
 $('source-meta').textContent=s?[gameNames[sourceGame(s)]||'Game not identified',layoutLabel(s),sourceStats(s)].join(' · '):'Add a game or asset folder';
 $('source-button').title=s?(s.root||s.path):'';$('rescan').hidden=!s;
}
function renderSourceCards(){
 $('source-cards').innerHTML=sources.length?sources.map(s=>{
  const st=s.stats,count=st?`<span class="chip">${escape(plural(st.characters,'character'))}</span><span class="chip">${escape(st.layout==='folder'?plural(st.clips,'animation'):plural(st.archives,'archive'))}</span>${st.warnings?`<span class="chip warn">${escape(plural(st.warnings,'notice'))}</span>`:''}${st.scanned?`<span class="chip">Scanned ${escape(ago(st.scanned))}</span>`:''}`:`<span class="chip warn">${s.catalog?'Scanned':'Not scanned yet'}</span>`;
  return `<article class="source-card${s.id===activeId?' active':''}"><header>${glyphHtml(s)}<div class="block-title"><h3>${escape(s.name)}</h3><span>${escape([gameNames[sourceGame(s)]||'Game not identified',layoutLabel(s)].join(' · '))}</span></div></header><div class="path">${escape(s.root||s.path)}</div><div class="chips">${count}</div><footer>${s.id===activeId?'<span class="chip ok">In use</span>':`<button type="button" class="secondary" data-use="${escape(s.id)}">Use this source</button>`}<span class="grow"></span><button type="button" class="text-button" data-scan="${escape(s.id)}">${icon('refresh')}Scan</button><button type="button" class="text-button" data-edit="${escape(s.id)}">${icon('edit')}Edit</button></footer></article>`;
 }).join(''):`<div class="source-empty"><b>No sources yet</b>Add an unpacked game, a mod folder or a folder of archives. The bridge only reads from it.<br><button type="button" class="primary" data-menu="add">${icon('plus')}Add source</button></div>`;
}
function renderSources(){renderSourceSwitch();renderSourceCards();}
function openSourceMenu(){
 const menu=$('source-menu'),rect=$('source-button').getBoundingClientRect();
 menu.innerHTML=(sources.length?'<div class="menu-label">SOURCES</div>':'')+sources.map(s=>`<button type="button" class="menu-item" role="menuitemradio" aria-checked="${s.id===activeId}" data-source="${escape(s.id)}">${glyphHtml(s)}<span><b>${escape(s.name)}</b><small>${escape(layoutLabel(s)+' · '+(s.root||s.path))}</small></span>${s.id===activeId?'<svg class="check" aria-hidden="true"><use href="#i-check"/></svg>':''}</button>`).join('')
  +(sources.length?'<div class="menu-sep"></div>':'')+`<button type="button" class="menu-item command" role="menuitem" data-menu="add">${icon('plus')}Add source…</button><button type="button" class="menu-item command" role="menuitem" data-menu="manage">${icon('library')}Manage sources</button>`;
 menu.hidden=false;menu.style.left=Math.max(12,Math.min(rect.left,innerWidth-menu.offsetWidth-12))+'px';menu.style.top=(rect.bottom+6)+'px';
 $('source-button').setAttribute('aria-expanded','true');
 (menu.querySelector('[aria-checked="true"]')||menu.querySelector('.menu-item'))?.focus();
}
function closeSourceMenu(focus=false){if($('source-menu').hidden)return;$('source-menu').hidden=true;$('source-button').setAttribute('aria-expanded','false');if(focus)$('source-button').focus();}
async function activateSource(id,restore=false){
 if(!restore)rememberState();
 activeId=id;const source=activeSource(),state=source?.state||{};
 resolveSequence++;resolving=false;catalog=null;catalogPath='';selection=null;parts=[];archiveFor='';scanProblem=null;inventoryProblem=null;
 weapons=null;weaponsFor=null;weaponData=null;weaponDataFor=null;weaponPath=state.part?.path||'';weaponClip=state.part?.clip||'';pendingWeapon='';
 // Settings saved before sources existed carry the selection globally.
 characterId=state.character??(restore?config.assetCharacter||'':'');clipId=state.clip??(restore?config.assetClip||'':'');
 lastSuggestedBlend=state.suggested||'';if(state.outputBlend)$('outputBlend').value=state.outputBlend;
 if(source)$('game').value=source.game||'auto';
 $('character-filter').value='';$('clip-filter').value='';
 renderSources();renderLibrary();renderParts();
 if(source?.catalog&&inputMethod==='folder')await loadCatalog(source,true);
 saveSoon();
}
async function scanSource(source=activeSource()){
 if(!source)return openSourceDialog();
 try{
  await startJob({mode:'discover',assetFolder:source.path,assetCatalog:'',sourceLayout:source.layout,sourceFolders:source.folders||{},sourceRecursive:source.recursive!==false,sourceFileList:source.fileList||'',game:source.game||'auto'},{source:source.id});
  if(scanProblem?.source===source.id)scanProblem=null;
  renderLibrary();toast(`Scanning ${source.name}. Progress is shown below.`);
 }catch(e){toast(e.message,true);}
}
async function loadCatalog(source,restore=false){
 const path=source.catalog,folder=source.root||source.path;
 catalogLoading=true;renderLibrary();
 try{
  const found=await api('catalog',{path,folder});
  if(source.id!==activeId||source.catalog!==path)return;
  catalog=found;catalogPath=path;archiveFor='';
  Object.assign(source,{root:found.folder,resolved:found.layout,detectedGame:found.game||(found.games?.length===1?found.games[0]:'')});
  source.stats={...source.stats,layout:found.layout,characters:found.characters.length,clips:found.clips.length,archives:found.archiveCount,warnings:found.warnings.length};
  if(!found.characters.some(c=>c.id===characterId))characterId=found.characters.length===1?found.characters[0].id:'';
  catalogLoading=false;renderSources();restoreClip();renderLibrary();scrollToClip();ensureInventory();
  await resolveClip(restore);
 }catch(e){if(source.id!==activeId)return;catalog=null;catalogPath='';scanProblem={source:source.id,message:e.message};}
 finally{if(source.id===activeId&&catalogLoading){catalogLoading=false;renderLibrary();}}
}

/* Library */
const currentClip=()=>catalog?.clips.find(c=>c.id===clipId);
const currentCharacter=()=>catalog?.characters.find(c=>c.id===characterId);
const characterClips=()=>catalog&&characterId?catalog.clips.filter(c=>c.characterKey===characterId):[];
const isScanning=s=>job?.status==='running'&&job.mode==='discover'&&jobSources.get(job.id)===s?.id;
const isInventorying=id=>job?.status==='running'&&job.mode==='inventory'&&jobCharacters.get(job.id)===id&&jobSources.get(job.id)===activeId;
const skeletonRows='<div class="skeleton-rows"><span></span><span></span><span></span><span></span><span></span><span></span></div>';
function renderLibrary(){renderCharacters();renderClips();renderPartView();}
function renderCharacters(){
 const list=$('character-list'),empty=$('library-empty'),source=activeSource();
 let message='';
 if(!source)message='<b>No source yet</b>Its characters are listed here.';
 else if(!catalog&&isScanning(source))message=`<b>Scanning ${escape(source.name)}…</b>${skeletonRows}`;
 else if(!catalog&&catalogLoading)message=skeletonRows;
 else if(!catalog&&scanProblem?.source===source.id)message='<b>Not available</b>The scan could not be opened.';
 else if(!catalog)message='<b>Not scanned yet</b>Its characters are listed after a scan.';
 else if(!catalog.characters.length)message='<b>No characters found</b>';
 const needle=$('character-filter').value.toLowerCase().trim();
 const shown=message?[]:catalog.characters.filter(c=>!needle||[c.id,c.character,c.name,c.folder,gameNames[c.game],c.character==='c0000'?'player':''].join(' ').toLowerCase().includes(needle));
 if(!message&&!shown.length)message=`<b>No character matches “${escape(needle)}”</b>`;
 $('character-count').textContent=catalog?(needle?`${shown.length} of ${catalog.characters.length}`:String(catalog.characters.length)):'';
 list.hidden=!!message;empty.hidden=!message;
 if(message){empty.innerHTML=message;return;}
 const folder=catalog.layout==='folder';
 list.innerHTML=shown.map(c=>{
  const loaded=c.inventoried!==false,loading=isInventorying(c.id),small=folder?c.folder:c.character==='c0000'?'Player':'';
  const meta=folder?[gameNames[c.game]||'Unknown game',plural(c.count,'animation')]:loaded?[plural(c.count,'animation'),c.ready<c.count?`${c.ready} ready`:'',plural(c.archiveCount,'archive')]:[plural(c.archiveCount,'archive'),formatBytes(c.bytes),c.model?'model':''];
  const archives=(c.archives||[]).map(basename);
  return `<button type="button" class="char-row${c.id===characterId?' selected':''}" role="option" aria-selected="${c.id===characterId}" data-character="${escape(c.id)}" title="${escape(archives.length?archives.slice(0,8).join('\n')+(archives.length>8?'\n…':''):c.name)}"><span class="char-id">${escape((c.character||'Unknown').toUpperCase())}${small?`<small>${escape(small)}</small>`:''}</span><span class="char-flags"><i class="flag${loading?' loading':loaded?' on':''}" title="${loading?'Reading its archives':loaded?'Animations listed':'Read when you choose it'}"></i></span><span class="char-meta">${escape(meta.filter(Boolean).join(' · '))}</span></button>`;
 }).join('');
}
function selectCharacter(id){
 if(inventoryProblem?.key===activeId+'|'+id)inventoryProblem=null;
 if(id!==characterId){characterId=id;clipId='';$('clip-filter').value='';$('clip-list').scrollTop=0;restoreClip();}
 renderLibrary();scrollToClip();ensureInventory();
 resolveClip(false);saveSoon();
}
function restoreClip(){
 const all=characterClips();if(!all.length)return;
 const saved=activeSource()?.state?.clips?.[characterId];
 const found=all.find(c=>c.id===clipId)||(saved&&(all.find(c=>c.id===saved.id)||all.find(c=>c.name===saved.name&&basename(c.archive)===basename(saved.archive))))||all.find(c=>c.ready)||all[0];
 clipId=found.id;
}
async function ensureInventory(character=currentCharacter()){
 const source=activeSource();
 if(!source||inputMethod!=='folder'||!character||character.inventoried!==false||job?.status==='running'||jobStarting)return;
 if(inventoryProblem?.key===source.id+'|'+character.id)return;
 try{await startJob({mode:'inventory',assetCharacter:character.id},{source:source.id,character:character.id});}
 catch(e){inventoryProblem={key:source.id+'|'+character.id,message:e.message};}
 renderLibrary();
}
function renderClips(){
 const list=$('clip-list'),empty=$('clip-empty'),character=currentCharacter(),all=characterClips(),name=(character?.character||'').toUpperCase();
 $('clips-title').textContent=character?'Animations · '+name:'Animations';
 const select=$('archive-filter');
 if(archiveFor!==catalogPath+'|'+characterId+'|'+all.length){
  archiveFor=catalogPath+'|'+characterId+'|'+all.length;const counts=new Map();all.forEach(c=>counts.set(c.archive,(counts.get(c.archive)||0)+1));
  const previous=select.value;select.innerHTML='<option value="">All archives</option>'+[...counts].map(([path,n])=>`<option value="${escape(path)}">${escape(basename(path)||'unpacked file')} · ${n}</option>`).join('');
  select.value=counts.has(previous)?previous:'';select.hidden=counts.size<2;
 }
 let message='';
 const source=activeSource();
 if(!source)message=`<b>Start with a source</b>Add an unpacked game, a mod folder or a folder of archives. The bridge only reads from it.<button type="button" class="primary" data-menu="add">${icon('plus')}Add source</button>`;
 else if(!catalog&&isScanning(source))message=`<b>Scanning ${escape(source.name)}</b>Progress is shown in Activity below.`;
 else if(!catalog&&catalogLoading)message='<b>Opening the scan…</b>';
 else if(!catalog&&scanProblem?.source===source.id)message=`<b>The scan of ${escape(source.name)} could not be opened</b>${escape(scanProblem.message)}<span class="empty-actions"><button type="button" class="primary" data-scan-active>${icon('refresh')}Scan again</button><button type="button" class="secondary" data-edit="${escape(source.id)}">${icon('edit')}Edit source</button></span>`;
 else if(!catalog)message=`<b>${escape(source.name)} is not scanned yet</b>A scan lists its characters and animations. Files are only read.<button type="button" class="primary" data-scan-active>${icon('refresh')}Scan now</button>`;
 else if(!catalog.characters.length)message=`<b>No animation archives in ${escape(source.name)}</b>Check its folder and layout.<button type="button" class="secondary" data-edit="${escape(source.id)}">${icon('edit')}Edit source</button>`;
 else if(!character)message='<b>Choose a character</b>Its animations are listed here.';
 else if(character.inventoried===false){
  const problem=inventoryProblem?.key===activeId+'|'+character.id;
  message=problem?`<b>${escape(name)}’s archives were not read</b>${escape(inventoryProblem.message)}<button type="button" class="secondary" data-retry-inventory>${icon('refresh')}Try again</button>`
   :isInventorying(character.id)||!job||job.status!=='running'?`<b>Reading ${escape(name)}’s archives…</b>${skeletonRows}`
   :`<b>${escape(name)} is next</b>Its archives are read when the current operation ends.`;
 }
 else if(!all.length)message='<b>No animations</b>This character’s archives hold no animation clips.';
 const needle=$('clip-filter').value.toLowerCase().trim(),archive=select.value;
 clipView=message?[]:all.filter(c=>(!archive||c.archive===archive)&&(!needle||(c.name+' '+basename(c.archive)).toLowerCase().includes(needle)));
 if(!message&&!clipView.length)message=`<b>No animation matches “${escape(needle)}”</b>`;
 $('clip-count').textContent=all.length?(clipView.length<all.length?`${clipView.length.toLocaleString('en')} of ${all.length.toLocaleString('en')}`:all.length.toLocaleString('en')):'';
 const warnings=catalog?[...catalog.warnings,...(character?.errors||[])]:[];
 $('folder-notice').textContent=warnings.join('\n\n');$('folder-notice').hidden=!warnings.length;
 list.hidden=!!message;empty.hidden=!message;
 if(message){empty.innerHTML=message;return;}
 list.firstElementChild.style.height=(clipView.length*ROW+12)+'px';
 paintClips();
}
function clipRow(c,index){
 const stem=c.name.replace(/\.hkx$/i,''),selected=c.id===clipId;
 return `<div class="clip-row${selected?' selected':''}${c.ready?'':' blocked'}" role="option" id="clip-opt-${index}" aria-selected="${selected}" data-index="${index}" title="${escape(c.ready?c.member||c.name:c.issues.join('\n'))}"><span class="clip-state">${c.ready?'':icon('warn')}</span><span class="clip-name">${escape(stem)}<i>${stem.length<c.name.length?escape(c.name.slice(stem.length)):''}</i></span><span class="clip-archive">${escape(basename(c.archive)||'unpacked file')}</span></div>`;
}
function paintClips(){
 const list=$('clip-list');if(list.hidden||!clipView.length)return;
 const rows=list.lastElementChild,top=list.scrollTop,height=list.clientHeight||480;
 const first=Math.max(0,Math.floor(top/ROW)-8),last=Math.min(clipView.length,Math.ceil((top+height)/ROW)+8);
 rows.style.transform=`translateY(${first*ROW+6}px)`;
 rows.innerHTML=clipView.slice(first,last).map((c,i)=>clipRow(c,first+i)).join('');
 const index=clipView.findIndex(c=>c.id===clipId);
 if(index>=first&&index<last)list.setAttribute('aria-activedescendant','clip-opt-'+index);else list.removeAttribute('aria-activedescendant');
}
function scrollToClip(){
 const list=$('clip-list'),index=clipView.findIndex(c=>c.id===clipId);if(index<0||list.hidden)return;
 const top=index*ROW,bottom=top+ROW+12;
 if(top<list.scrollTop)list.scrollTop=top;else if(bottom>list.scrollTop+list.clientHeight)list.scrollTop=bottom-list.clientHeight;
 paintClips();
}
function selectClip(id,delay=0){
 clipId=id;paintClips();scrollToClip();
 const clip=currentClip(),state=activeSource()?.state;
 if(state&&clip)state.clips={...state.clips,[characterId]:{id:clip.id,name:clip.name,archive:clip.archive}};
 selection=null;resolving=!!clip?.ready;resolveSequence++;renderSceneHead();
 clearTimeout(resolveTimer);resolveTimer=setTimeout(()=>resolveClip(false),delay);
}
// Wolf keeps a chosen Wolf preset; other characters take the player or NPC preset.
function clipPreset(clip,current){
 const wolf=clip.character==='c0000'&&clip.game==='sekiro';
 return wolf?(['wolf','tutorial','mortal'].includes(current)?current:'wolf'):clip.character==='c0000'?'player':'npc';
}
async function resolveClip(restore=false){
 const clip=inputMethod==='folder'?currentClip():null,seq=++resolveSequence,weapon=pendingWeapon;pendingWeapon='';
 if(!clip||!clip.ready){
  selection=null;resolving=false;
  if(clip)for(const key of ['animation','skeleton','compendium','skeletonCompendium'])$(key).value='';
  if(inputMethod==='folder'){parts=[];renderParts();setNotice([]);}
  renderSceneHead();return;
 }
 resolving=true;renderSceneHead();
 try{
  const state=activeSource()?.state||{},current=restore?state.preset||$('preset').value:$('preset').value;
  const resolved=await api('resolve',{path:catalogPath,folder:catalog.folder,clip:clip.id,preset:clipPreset(clip,current)});
  if(seq!==resolveSequence)return;
  selection=resolved;
  for(const key of ['animation','skeleton','compendium','skeletonCompendium','characterSource','preset'])$(key).value=resolved[key]||'';
  for(const key of ['materialBinder','textureDirectory','referenceModel'])$(key).value=state.overrides?.[key]||resolved[key]||'';
  const npc=clip.character!=='c0000',saved=state.modelChoices?.[clip.character]||(restore&&state.character===characterId?(state.models||config.models||[])[0]:'');
  const models=new Set(restore?state.models||config.models||[]:[]);
  parts=resolved.parts;
  if(npc&&saved&&parts.some(p=>p.path===saved))parts.forEach(p=>p.selected=p.path===saved);
  else if(!npc&&models.size&&parts.some(p=>models.has(p.path)))parts.forEach(p=>p.selected=models.has(p.path));
  extrasOpen=null;renderParts();applyWeapon(weapon);
  const structured=resolved.layout!=='folder',notes=[];
  if(!parts.length)notes.push(clip.character==='c0000'?'No player outfit found. c0000.chrbnd is a skeleton reference with no visible body. Add outfit PARTSBND files from this game, or switch to Rig only.':structured?`This source has no ${clip.character}.chrbnd or FLVER. Choose model files, or switch to Rig only.`:'No matching model found. Add this character’s CHRBND, or switch to Rig only.');
  if(resolved.missing.length)notes.push('Missing outfit parts: '+resolved.missing.join(', ')+'. Available parts stay selectable.');
  if(resolved.game==='er'&&!$('materialBinder').value)notes.push('For Elden Ring materials, add material/allmaterial.matbinbnd.dcx. The legacy MTD library does not provide these assignments.');
  setNotice(notes);suggestBlend(clip,restore);saveSoon();
 }catch(e){if(seq!==resolveSequence)return;selection=null;setNotice([e.message],'error');toast(e.message,true);}
 finally{if(seq===resolveSequence){resolving=false;renderSceneHead();}}
}
function suggestBlend(clip,restore){
 const source=activeSource();if(!source)return;
 const donor=config.donor&&!donorIsCurrent()?'_from_'+config.donor.fileTag:'';
 const suggested=joinPath(source.scenes||joinPath(source.root||source.path,'Blender'),`${clip.character||'character'}_${clip.name.replace(/\.hkx$/i,'')}${donor}.blend`),current=$('outputBlend').value.trim();
 if(restore&&current)return;
 if(!lastSuggestedBlend||!current||current===lastSuggestedBlend){$('outputBlend').value=suggested;lastSuggestedBlend=suggested;}
}
function setNotice(lines,kind='warn'){$('scan-notice').textContent=lines.join('\n');$('scan-notice').className='notice '+kind;$('scan-notice').hidden=!lines.length;}

/* Part view: Sekiro's animated weapon parts, the clips of one, and the player animations each clip plays in */
let partView=false,weapons=null,weaponsFor=null,weaponSequence=0,weaponPath='',weaponData=null,weaponDataFor=null,weaponDataSequence=0,weaponClip='',pendingWeapon='';
try{partView=localStorage.getItem('bridge-part-view')==='1';}catch(e){}
const sekiroSource=()=>{const source=activeSource();return !!source&&(catalog?catalog.game==='sekiro'||(catalog.games||[]).includes('sekiro'):sourceGame(source)==='sekiro');};
const showsParts=()=>partView&&inputMethod==='folder'&&sekiroSource();
const partPlayer=()=>catalog?.characters.find(c=>c.id===weaponData?.characterKey);
const partClipRows=()=>weaponData?.models?weaponData.models.flatMap(m=>m.clips.map(c=>({...c,model:m.model,modelName:m.name,key:m.model+'|'+c.id}))):[];
const currentPartClip=()=>partClipRows().find(r=>r.key===weaponClip);
// Replaces a list's rows and keeps the keyboard focus on the same row.
function fill(list,html,attribute){
 const focused=list.contains(document.activeElement)?document.activeElement.getAttribute(attribute):null;
 list.innerHTML=html;
 if(focused!==null)[...list.querySelectorAll(`[${attribute}]`)].find(el=>el.getAttribute(attribute)===focused)?.focus({preventScroll:true});
}
// Scrolls a list, not the page, so that its selected row shows, as scrollToClip does for the clip list.
function scrollToSelected(list){
 const row=list.querySelector('[aria-selected="true"]');if(!row||list.hidden)return;
 const box=list.getBoundingClientRect(),at=row.getBoundingClientRect();
 if(at.top<box.top)list.scrollTop+=at.top-box.top;else if(at.bottom>box.bottom)list.scrollTop+=at.bottom-box.bottom;
}
function applyView(){
 const folder=inputMethod==='folder',sekiro=sekiroSource(),shown=folder&&partView&&sekiro,view=shown?'parts':inputMethod;
 $('parts-tab').hidden=!sekiro;
 document.querySelectorAll('[data-input]').forEach(b=>{const on=b.dataset.input===view;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));});
 $('characters-pane').hidden=!folder||shown;$('clips-pane').hidden=!folder||shown;$('weapons-pane').hidden=!shown;$('part-clips-pane').hidden=!shown;$('files-pane').hidden=folder;
 document.querySelector('.import-grid').classList.toggle('files',!folder);
 $('import-note').textContent=shown?'Pick a weapon part and one of its clips, then an animation that it plays in. Both are imported together.'
  :folder?'Pick a character and an animation. The scene settings follow your choice.':'Choose extracted HKX files. The animation, skeleton and compendium must come from the same character.';
}
function renderPartView(){
 applyView();if(!showsParts())return;
 if(catalog&&weaponsFor!==catalog)loadWeapons();
 else if(catalog&&weapons&&weaponPath&&weaponDataFor!==catalog)loadWeaponClips();
 // A game folder lists the player's archives by name until they are read.
 if(weaponData?.inventoried===false)ensureInventory(partPlayer());
 renderWeapons();renderWeaponClips();renderMatches();
}
async function loadWeapons(){
 const current=catalog,seq=++weaponSequence;weaponsFor=current;weapons=null;renderWeapons();
 let found;
 try{found=await api('part-list',{path:catalogPath,folder:current.folder});}
 catch(e){found={error:e.message,parts:[],notices:[],read:0};}
 if(seq!==weaponSequence||current!==catalog)return;
 weapons=found;
 if(weaponPath&&!found.parts.some(p=>p.path===weaponPath)){weaponPath='';weaponClip='';}
 weaponDataFor=null;renderWeapons();scrollToSelected($('weapon-list'));loadWeaponClips();
}
async function loadWeaponClips(){
 const current=catalog,part=weaponPath,seq=++weaponDataSequence;
 if(!current||!part){weaponData=null;weaponDataFor=null;renderWeaponClips();renderMatches();return;}
 weaponData={loading:true,path:part};weaponDataFor=current;renderWeaponClips();renderMatches();
 let found;
 try{found=await api('part-matches',{path:catalogPath,folder:current.folder,part});}
 catch(e){found={error:e.message,path:part};}
 if(seq!==weaponDataSequence||current!==catalog||part!==weaponPath)return;
 weaponData=found;
 // Without a saved clip, the view opens on the part clip that plays with the animation chosen for import.
 const rows=partClipRows();
 if(!rows.some(r=>r.key===weaponClip))weaponClip=rows.find(r=>r.matches.some(m=>m.clip===clipId))?.key||'';
 renderPartView();scrollToSelected($('part-clip-list'));
}
function rememberPart(){const source=activeSource();if(source){source.state={...source.state,part:{path:weaponPath,clip:weaponClip}};saveSoon();}}
function selectWeapon(path){
 if(path!==weaponPath){weaponPath=path;weaponClip='';weaponData=null;weaponDataFor=null;$('part-clip-filter').value='';rememberPart();loadWeaponClips();}
 renderWeapons();
}
function selectPartClip(key){
 weaponClip=key;rememberPart();
 const row=currentPartClip(),match=row&&(row.matches.find(m=>m.clip===clipId)||row.matches.find(m=>m.ready)||row.matches[0]);
 if(match)useMatch(match.clip);else{renderWeaponClips();renderMatches();}
}
function useMatch(id){
 const data=weaponData,match=currentPartClip()?.matches.find(m=>m.clip===id);if(!data?.characterKey||!match)return;
 // The view exists to import the part's clip with the animation, so it keys weapon parts.
 if(!$('partAnimations').checked){$('partAnimations').checked=true;$('partAnimations').dispatchEvent(new Event('change'));}
 if(characterId!==data.characterKey){characterId=data.characterKey;$('clip-filter').value='';$('clip-list').scrollTop=0;}
 if(id===clipId&&selection&&!resolving)applyWeapon(data.path);else{pendingWeapon=data.path;selectClip(id);}
 renderWeaponClips();renderMatches();saveSoon();
}
function applyWeapon(path){
 const part=path&&parts.find(p=>samePath(p.path,path));
 if(part&&!part.selected){part.selected=true;extrasOpen=true;renderParts();saveSoon();}
}
function renderWeapons(){
 const list=$('weapon-list'),empty=$('weapon-empty'),notice=$('weapon-notice');
 let message='';
 if(!catalog)message=catalogLoading||isScanning(activeSource())?skeletonRows:'<b>Not scanned yet</b>Scan the source in Source library to list its weapon parts.';
 else if(!weapons)message=skeletonRows;
 else if(weapons.error)message=`<b>The weapon parts could not be read</b>${escape(weapons.error)}`;
 else if(!weapons.parts.length)message=`<b>No animated weapon parts</b>${escape(plural(weapons.read,'Sekiro weapon part'))} read; none holds an animation binder.`;
 const needle=$('weapon-filter').value.toLowerCase().trim();
 const shown=message?[]:weapons.parts.filter(p=>!needle||[p.id,...weaponNames(p.id,'sekiro')].join(' ').toLowerCase().includes(needle));
 if(!message&&!shown.length)message=`<b>No weapon part matches “${escape(needle)}”</b>`;
 $('weapon-count').textContent=weapons?.parts?.length?(needle?`${shown.length} of ${weapons.parts.length}`:String(weapons.parts.length)):'';
 notice.textContent=(weapons?.notices||[]).join('\n');notice.hidden=!weapons?.notices?.length;
 list.hidden=!!message;empty.hidden=!message;
 if(message){empty.innerHTML=message;return;}
 fill(list,shown.map(p=>{
  const names=weaponNames(p.id,'sekiro'),selected=p.path===weaponPath;
  const meta=[plural(p.clips,'clip'),p.models.length>1?plural(p.models.length,'model'):'',names.length>1?'also '+names.slice(1).join(', '):''].filter(Boolean).join(' · ');
  return `<button type="button" class="char-row${selected?' selected':''}" role="option" aria-selected="${selected}" data-weapon-part="${escape(p.path)}" title="${escape([...names,p.path].join('\n'))}"><span class="char-id">${escape(p.name)}${names[0]?`<small>${escape(names[0])}</small>`:''}</span><span class="char-meta">${escape(meta)}</span></button>`;
 }).join(''),'data-weapon-part');
}
function renderWeaponClips(){
 const list=$('part-clip-list'),empty=$('part-clip-empty'),part=weapons?.parts?.find(p=>p.path===weaponPath),data=weaponData;
 $('part-clips-title').textContent=part?'Part clips · '+part.name:'Part clips';
 let message='';
 if(!part)message='<b>Choose a weapon part</b>Its clips are listed here, each with the animations it plays in.';
 else if(!data||data.loading)message=skeletonRows;
 else if(data.error)message=`<b>${escape(part.name)}’s clips could not be read</b>${escape(data.error)}`;
 const rows=message?[]:partClipRows(),needle=$('part-clip-filter').value.toLowerCase().trim();
 const shown=rows.filter(r=>!needle||[r.id,r.member,...r.matches.map(m=>m.name)].join(' ').toLowerCase().includes(needle));
 if(!message&&!rows.length)message=`<b>No clips</b>${escape(part.name)} holds only its rest pose.`;
 else if(!message&&!shown.length)message=`<b>No clip matches “${escape(needle)}”</b>`;
 $('part-clip-count').textContent=rows.length?(shown.length<rows.length?`${shown.length} of ${rows.length}`:String(rows.length)):'';
 list.hidden=!!message;empty.hidden=!message;
 if(message){empty.innerHTML=message;return;}
 const row=r=>{
  const selected=r.key===weaponClip,stem=r.member.replace(/\.hkx$/i,''),n=r.matches.length;
  return `<button type="button" class="clip-row part-clip-row${selected?' selected':''}${n?'':' blocked'}" role="option" aria-selected="${selected}" data-part-clip="${escape(r.key)}" title="${escape(r.member)}"><span class="clip-state"></span><span class="clip-name">${escape(r.id)}<i>${escape(stem.slice(r.id.length))}</i></span><span class="clip-archive">${n?plural(n,'animation'):'not played'}</span></button>`;
 };
 // A part with several animated models lists each model's clips under its name.
 const grouped=data.models.length>1;
 fill(list,grouped?data.models.map(m=>{const own=shown.filter(r=>r.model===m.model);return own.length?`<div role="group" aria-label="${escape(m.name)}"><div class="list-group" aria-hidden="true">${escape(m.name)}</div>${own.map(row).join('')}</div>`:'';}).join(''):shown.map(row).join(''),'data-part-clip');
}
function renderMatches(){
 const box=$('plays-in'),data=weaponData,ready=!!(showsParts()&&data?.models);
 box.hidden=!ready;if(!ready)return;
 const row=currentPartClip(),model=data.models.find(m=>m.model===row?.model)||(data.models.length===1?data.models[0]:null),player=(data.character||'c0000').toUpperCase(),notes=[];
 let retry=false;
 $('plays-in-title').textContent=row?`${row.member.replace(/\.hkx$/i,'')} plays in`:'Plays in';
 if(!data.characterKey)notes.push(`This source has no animation archives of ${player}, so no animation pairs with the part.`);
 else if(!data.inventoried){
  retry=inventoryProblem?.key===activeId+'|'+data.characterKey;
  notes.push(retry?`${player}’s archives were not read: ${inventoryProblem.message}`:isInventorying(data.characterKey)||!job||job.status!=='running'?`Reading ${player}’s archives…`:`${player}’s archives are read when the current operation ends.`);
 }
 else if(!data.playerClips)notes.push(`No ${player} animation is in the part’s folder.`);
 else if(!row)notes.push('Choose one of the part’s clips to see the animations it plays in.');
 else if(!row.matches.length)notes.push(`No ${player} animation in this source plays ${row.member}.`);
 if(data.inventoried&&data.playerClips&&!data.tae)notes.push(`Without ${player}’s TAE, only animations of the same ID are listed.`);
 if(model?.rest)notes.push(`${model.name} holds its rest pose, ${model.rest.replace(/\.hkx$/i,'')}, in every other animation.`);
 const matches=row?.matches||[];
 $('match-list').hidden=!matches.length;
 fill($('match-list'),matches.map(m=>{
  const selected=m.clip===clipId&&characterId===data.characterKey;
  return `<button type="button" class="char-row match-row${selected?' selected':''}" role="option" aria-selected="${selected}" data-match="${escape(m.clip)}" title="${escape(m.ready?m.reason:'This clip is missing inputs. Choose it to see which.')}"><span class="char-id">${escape(m.name.replace(/\.hkx$/i,''))}<small>${escape(m.archive)}</small></span><span class="char-flags">${m.ready?'':icon('warn')}</span><span class="char-meta">${escape(m.reason)}</span></button>`;
 }).join(''),'data-match');
 $('plays-in-note').innerHTML=escape(notes.join(' '))+(retry?` <button type="button" class="text-button" data-retry-inventory>${icon('refresh')}Try again</button>`:'');
}

/* Scene panel */
function sceneChecks(){
 const folder=inputMethod==='folder',clip=folder?currentClip():null,has=key=>!!$(key).value.trim();
 if(folder&&!clip)return [];
 if(folder&&!clip.ready)return [['bad','Missing inputs']];
 if(folder&&resolving)return [['wait','Matching files…']];
 if(folder&&!selection)return [];
 const checks=[[has('animation')?'ok':'bad','Animation'],[has('skeleton')?'ok':'bad','Skeleton'],has('compendium')?['ok','Compendium']:['','No animation compendium']];
 if(has('skeletonCompendium')&&$('skeletonCompendium').value.trim()!==$('compendium').value.trim())checks.push(['ok','Skeleton compendium']);
 if(!$('includeCharacter').checked)checks.push(['','Rig only']);
 else{const n=parts.filter(p=>p.selected).length;checks.push(n?['ok',n===1?'1 model':`${n} parts`]:['bad','No model'],has('materialBinder')?['ok','Materials']:[currentGame()==='er'?'bad':'','No material library']);}
 return checks;
}
function renderSceneHead(){
 const folder=inputMethod==='folder',clip=folder?currentClip():null;
 if(folder){$('scene-clip').textContent=clip?clip.name.replace(/\.hkx$/i,''):'Choose an animation';$('scene-clip-meta').textContent=clip?[(clip.character||'').toUpperCase(),gameNames[clip.game]||'',basename(clip.archive)].filter(Boolean).join(' · '):'Its rig, model and textures are put together here.';}
 else{const a=$('animation').value.trim();$('scene-clip').textContent=a?basename(a).replace(/\.hkx$/i,''):'Choose an animation file';$('scene-clip-meta').textContent=a?[gameNames[$('game').value]||'Game read from the file',$('skeleton').value.trim()?'skeleton '+basename($('skeleton').value.trim()):'no skeleton yet'].join(' · '):'Choose the extracted HKX files on the left.';}
 const checks=sceneChecks();
 $('scene-checks').innerHTML=checks.map(([kind,label])=>`<li class="${kind}">${kind==='ok'?icon('check'):kind==='bad'?icon('warn'):''}${escape(label)}</li>`).join('');$('scene-checks').hidden=!checks.length;
 const issues=folder&&clip&&!clip.ready?clip.issues:[];$('clip-issues').textContent=issues.join('\n\n');$('clip-issues').hidden=!issues.length;
 const value=key=>$(key).value.trim(),root=activeSource()?.root||'';
 const textures=[...(folder&&selection?.textureFolders||[]).map(f=>relativeTo(f,root)),...(value('textureDirectory')?[value('textureDirectory')]:[])];
 const models=parts.filter(p=>p.selected).map(p=>p.name);
 const rows=[['Animation',value('animation')],['Skeleton',value('skeleton')],['Compendium',value('compendium')],...(value('skeletonCompendium')&&value('skeletonCompendium')!==value('compendium')?[['Skeleton compendium',value('skeletonCompendium')]]:[]),['Models',$('includeCharacter').checked?models.join(', '):'Rig only',true],['Material library',value('materialBinder')],['Textures',textures.map(t=>t===value('textureDirectory')?t:t).join(', '),true],['Rig attachment',value('referenceModel')]];
 $('resolved-files').innerHTML=rows.map(([label,text,plain])=>`<dt>${escape(label)}</dt>${text?`<dd title="${escape(text)}">${escape(plain?text:basename(text))}</dd>`:'<dd class="none">None</dd>'}`).join('');
 const found=['animation','skeleton','compendium'].filter(key=>value(key));
 $('resolved-summary').textContent=found.length?`${found.map((k,i)=>i?k:k[0].toUpperCase()+k.slice(1)).join(', ').replace(/, ([^,]*)$/,' and $1')} ${folder?'matched':'chosen'}`:'Animation, skeleton and compendium';
 $('materials-summary').textContent=(value('materialBinder')?basename(value('materialBinder')):'No material library')+(textures.length?' · textures from '+textures.map(t=>basename(t)||t).join(', '):'');
 schedulePreview();
 renderDonor();
}

/* Retarget donor: a pinned second animation that the import places beside the selected one */
const donorKeys=['inputMethod','assetFolder','assetCatalog','sourceLayout','sourceFolders','sourceRecursive','sourceFileList','game','assetCharacter','assetClip',
 'animation','compendium','skeleton','skeletonCompendium','characterSource','preset','models','modelMasks','includeCharacter','materialBinder','textureDirectory','referenceModel','weaponAttachments'];
function donorIsCurrent(){
 const d=config.donor,source=activeSource();if(!d)return false;
 return d.inputMethod==='folder'?inputMethod==='folder'&&d.assetClip===clipId&&samePath(d.assetFolder,source?.root||source?.path):inputMethod==='manual'&&samePath(d.animation,$('animation').value.trim());
}
function renderDonor(){
 const d=config.donor,current=donorIsCurrent();
 $('donor-card').hidden=!d;if(d){$('donor-name').textContent=d.label;$('donor-meta').textContent=d.detail;}
 $('donor-summary').textContent=!d?'Optional. Pin an animation from any source or game, then choose the character that receives it.':current?'This animation is the donor. Now choose the animation of the character that receives it.':'Imported beside this character, for the retarget add-on to bake onto it.';
 $('donor-pin').hidden=current;$('donor-pin-label').textContent=d?'Replace the donor with this animation':'Use this animation as the donor';
}
function pinDonor(){
 const folder=inputMethod==='folder',clip=folder?currentClip():null;
 if(folder){
  if(!clip)throw Error('Choose the donor’s animation first.');
  if(!clip.ready)throw Error(clip.issues.join('\n'));
  if(resolving||!selection)throw Error('Wait until the animation’s files are matched.');
 }else requireFields(['animation','skeleton']);
 if($('includeCharacter').checked&&!parts.some(p=>p.selected))throw Error('Select one or more character parts for the donor, or switch to Rig only.');
 const v=values(),name=folder?clip.name.replace(/\.hkx$/i,''):basename(v.animation).replace(/\.hkx$/i,'');
 config.donor={...Object.fromEntries(donorKeys.map(key=>[key,v[key]])),modelMasks:{...v.modelMasks},label:name,fileTag:folder?`${clip.character||'character'}_${name}`:name,
  detail:(folder?[(clip.character||'').toUpperCase(),gameNames[clip.game]||'',activeSource()?.name||'']:[gameNames[v.game]||'Game read from the file','extracted files']).filter(Boolean).join(' · ')};
 renderDonor();saveSoon();toast('Donor pinned. Now choose the animation of the character that receives it.');
}
function removeDonor(){
 config.donor=null;renderDonor();if(inputMethod==='folder'&&currentClip())suggestBlend(currentClip(),false);saveSoon();
}

/* Clip preview: the clip's skeleton on a canvas, and the part clips that play with it */
let previewKey='',previewTimer,previewSequence=0,partKey='',partTimer,partSequence=0,partRows=null;
function previewInputs(){
 const v=key=>$(key).value.trim(),inputs={animation:v('animation'),skeleton:v('skeleton'),compendium:v('compendium'),skeletonCompendium:v('skeletonCompendium')};
 // Another engine's clip is read by its package from the selection the package made; the model parts do not change it.
 if(inputMethod==='folder'&&selection?.engine&&selection.engine!=='fromsoft'){
  const {parts,...chosen}=selection;
  Object.assign(inputs,{engine:selection.engine,game:selection.game,motion:String(selection.motion??''),selection:chosen});
 }
 return inputs;
}
function schedulePreview(){
 schedulePartClips();
 const folder=inputMethod==='folder',clip=folder?currentClip():null,inputs=previewInputs();
 const ready=folder?!!(clip?.ready&&selection&&!resolving):!!(inputs.animation&&inputs.skeleton);
 const waiting=folder?(!clip?'Choose an animation to see its skeleton move.':!clip.ready?'This clip is missing inputs, so it cannot be previewed.':'Matching files…'):'Choose the animation and skeleton files to see the clip.';
 // The clip is decoded only while the preview is open.
 const key=!ready?'wait:'+waiting:$('preview-block').open?JSON.stringify(inputs):'closed';
 if(key===previewKey)return;
 previewKey=key;clearTimeout(previewTimer);const seq=++previewSequence;
 if(!ready){ClipPreview.clear(waiting);$('preview-summary').textContent='The clip’s skeleton, before import';prefetchClips(false);return;}
 if(key==='closed'){ClipPreview.pause();prefetchClips(false);return;}
 ClipPreview.clear('Reading the clip…');
 let shown=false;
 const show=data=>{
  if(seq!==previewSequence||shown)return;shown=true;clearTimeout(previewTimer);
  ClipPreview.show(data);
  $('preview-summary').textContent=`${data.skeleton} · ${plural(data.bones.length,'bone')} · ${plural(data.frameCount,'frame')} at ${formatNumber(data.frameRate)} fps${data.root?' · root motion':''}`;
  prefetchClips(folder);
 };
 // A clip previewed before shows at once from the cache; decoding waits until the selection settles.
 api('preview',{...inputs,storedOnly:true}).then(data=>{if(data)show(data);},()=>{});
 previewTimer=setTimeout(async()=>{
  try{show(await api('preview',inputs));}
  catch(e){if(seq!==previewSequence||shown)return;previewKey='';ClipPreview.clear(e.message,'error');prefetchClips(folder);}
 },300);
}
// Once the selected clip shows, the bridge decodes the clips around it in the background, nearest first:
// two on each side, or with aggressive caching the whole list.
let prefetchKey='';
function prefetchClips(on){
 const index=on?clipView.findIndex(c=>c.id===clipId):-1,aggressive=config.previewCache==='aggressive',order=[];
 if(index>=0)for(let d=1;d<=(aggressive?clipView.length:2)&&order.length<5000;d++)for(const i of [index+d,index-d])if(clipView[i]?.ready)order.push(clipView[i]);
 const current=$('preset').value,clips=order.map(c=>({id:c.id,preset:clipPreset(c,current)}));
 const key=JSON.stringify([catalogPath,clips]);if(key===prefetchKey)return;prefetchKey=key;
 api('prefetch',clips.length?{path:catalogPath,folder:catalog.folder,clips}:{clips}).catch(()=>{prefetchKey='';});
}
function schedulePartClips(){
 const folder=inputMethod==='folder',clip=folder?currentClip():null,animation=$('animation').value.trim();
 const models=$('includeCharacter').checked?parts.filter(p=>p.selected&&/^wp_/i.test(p.id)).map(p=>p.path):[];
 $('part-option').hidden=!models.length;
 const ready=models.length&&(folder?!!(clip?.ready&&selection&&!resolving&&catalog):!!animation);
 const request=ready?(folder?{path:catalogPath,folder:catalog.folder,clip:clip.id,models}:{animation,models}):null;
 const key=request?JSON.stringify(request):'';
 if(key===partKey)return;
 partKey=key;clearTimeout(partTimer);const seq=++partSequence;
 if(!request){partRows=null;renderPartClips();return;}
 partTimer=setTimeout(async()=>{
  try{const found=await api('part-clips',request);if(seq===partSequence){partRows=found;renderPartClips();}}
  catch(e){if(seq===partSequence){partRows={error:e.message};renderPartClips();}}
 },250);
}
function renderPartClips(){
 const box=$('preview-parts'),r=partRows;box.hidden=!r;
 if(!r){box.innerHTML='';return;}
 if(r.error){box.innerHTML=`<small>${escape('The weapons’ part clips could not be read: '+r.error)}</small>`;return;}
 if(!r.parts.length){box.innerHTML='<small>The chosen weapons have no animated parts.</small>';return;}
 const playing=r.parts.filter(p=>!p.rest),resting=r.parts.filter(p=>p.rest),on=$('partAnimations').checked;
 box.innerHTML=`<b>${on?'Weapon part clips with this animation':'Weapon part clips · not imported while Animate weapon parts is off'}</b><ul>`
  +playing.map(p=>`<li><b>${escape(p.name)}</b><code>${escape(p.member.replace(/\.hkx$/i,''))}</code><small>${escape(p.reason)}</small></li>`).join('')
  +(resting.length?`<li><small>${escape('Rest pose: '+resting.map(p=>p.name).join(', '))}</small></li>`:'')
  +`</ul><small>${escape((r.tae?'':'Without the character’s TAE, only a clip of the same ID pairs. ')+'Parts are not drawn in the preview.')}</small>`;
}
function partSummary(mode,r){
 if(mode==='import'){
  const n=(r.partClips||[]).filter(p=>!p.rest).length,notes=(r.partNotices||[]).length,moved=(r.weaponPlaces||[]).length;
  return (n?` · ${plural(n,'part clip')}`:'')+(moved?` · ${plural(moved,'weapon')} placed by the TAE`:'')
   +(notes?` · ${plural(notes,'part notice')} (see Activity)`:'');
 }
 return r.parts?.length?' · '+r.parts.map(p=>p.clip).join(', '):'';
}
ClipPreview.mount({canvas:'preview-canvas',play:'preview-play',frame:'preview-frame',time:'preview-time',root:'preview-root',status:'preview-status'});
try{if(localStorage.getItem('bridge-preview-open')==='0')$('preview-block').open=false;}catch(e){}
$('preview-block').addEventListener('toggle',()=>{try{localStorage.setItem('bridge-preview-open',$('preview-block').open?'1':'0');}catch(e){}schedulePreview();});
$('partAnimations').addEventListener('change',renderPartClips);

/* Character model */
const wolfRoles=[['fc','Head'],['am','Arms','with prosthetic'],['bd','Torso'],['lg','Legs']];
const playerRoles=[['hd','Headwear'],['fc','Head'],['hr','Hair'],['am','Arms'],['bd','Torso'],['lg','Legs']];
const prefix=p=>p.id.split('_')[0].toLowerCase();
function currentGame(){return (inputMethod==='folder'?currentClip()?.game:'')||$('game').value;}
function isWolfAssembly(){return ['wolf','tutorial','mortal'].includes($('preset').value)&&!['ds1','ds1r','ds3','er'].includes(currentGame());}
function detectNpcModels(){if(parts.some(p=>/^(fc|hd|hr|am|bd|lg)_/i.test(p.id))){if(!isWolfAssembly())$('preset').value=!['ds1','ds1r','ds3','er'].includes(currentGame())&&parts.some(p=>['bd_m_9000','bd_m_9030','bd_m_9040'].includes(p.id))?'wolf':'player';}else if(parts.length)$('preset').value='npc';}
function toggleCharacter(){const enabled=$('includeCharacter').checked;$('character-fields').hidden=!enabled;$('rig-only').hidden=enabled;updateAssembly();}
function regionRow([role,label,sub]){
 const matches=parts.filter(p=>prefix(p)===role),selected=matches.find(p=>p.selected);
 const control=matches.length>40
  ?`<input class="text-input" list="parts-${role}" data-region-input="${role}" value="${escape(selected?.name||'')}" placeholder="Type a part ID · ${matches.length} available" spellcheck="false" aria-label="${escape(label)}" title="${escape(selected?.path||'')}"><datalist id="parts-${role}">${matches.map(p=>`<option value="${escape(p.name)}">`).join('')}</datalist>`
  :`<select data-region="${role}" aria-label="${escape(label)}" title="${escape(selected?.path||'Skip this part')}"><option value="">Skip this part</option>${matches.map(p=>`<option value="${escape(p.path)}" ${p===selected?'selected':''}>${escape(p.name)}</option>`).join('')}</select>`;
 return `<div class="part-row"><span>${escape(label)}${sub?`<small>${escape(sub)}</small>`:''}</span>${control}</div>`;
}
const modelRow=p=>`<label class="model-row" title="${escape(p.path)}"><input type="checkbox" data-model="${escape(p.path)}" ${p.selected?'checked':''}><span><strong>${escape(p.name)}</strong><small>${escape(p.role)} · ${escape(p.container)} · ${escape(basename(p.path))}</small></span>${icon('cube')}</label>`;
const maskCache=new Map();let maskPath='',maskSequence=0;
function renderModelMasks(){
 const box=$('model-masks'),model=parts.find(p=>p.selected&&/^c\d{4}$/i.test(p.id));
 const path=model?.path||'';
 if(path!==maskPath){maskPath=path;box.open=false;const seq=++maskSequence;
  if(path&&!maskCache.has(path))api('model-masks',{path}).then(groups=>{if(seq===maskSequence){maskCache.set(path,groups);renderModelMasks();}})
   .catch(error=>{if(seq===maskSequence){maskCache.set(path,[]);toast('Could not read model mesh groups: '+error.message,true);renderModelMasks();}});
 }
 const groups=maskCache.get(path)||[];
 box.hidden=!path||!groups.length;
 if(box.hidden){box.innerHTML='';return;}
 const chosen=config.modelMasks?.[path];
 const count=chosen?groups.filter(g=>chosen.includes(g.id)).length:groups.length;
 box.innerHTML=`<summary>Visible model meshes <span class="chip">${count} of ${groups.length}</span></summary><p class="note">Choose the groups for the character or costume you want in this scene. Unnumbered meshes are always included. In Blender, each imported NPC group can be hidden separately in the Outliner.</p>`
  +'<div class="model-mask-options">'+groups.map(g=>`<label title="${escape(g.example)}"><input type="checkbox" data-mask="${escape(g.id)}" ${!chosen||chosen.includes(g.id)?'checked':''}><span>#${escape(g.id)} <small>${escape(g.example)} · ${g.count}</small></span></label>`).join('')+'</div>';
}
// Sekiro's names for its weapon models, from EquipParamWeapon and the weapon name text. Tools that share a model follow the first.
const sekiroWeapons={wp_a_0300:['Katana / Kusabimaru'],wp_a_0310:['Mortal Blade'],
 wp_a_0700:['Loaded Shuriken','Spinning Shuriken','Gouging Top','Lazulite Shuriken'],wp_a_0701:['Phantom Kunai'],wp_a_0702:['Sen Throw'],
 wp_a_0710:['Shinobi Firecracker','Spring-load Firecracker','Long Spark'],wp_a_0711:['Purple Fume Spark'],
 wp_a_0720:['Flame Vent','Spring-load Flame Vent',"Okinaga's Flame Vent",'Lazulite Sacred Flame'],
 wp_a_0730:['Loaded Axe','Spring-load Axe'],wp_a_0731:['Sparking Axe'],wp_a_0732:['Lazulite Axe'],
 wp_a_0740:['Mist Raven'],wp_a_0741:['Aged Feather Mist Raven'],wp_a_0742:['Great Feather Mist Raven'],
 wp_a_0750:['Sabimaru','Improved Sabimaru','Piercing Sabimaru'],wp_a_0751:['Lazulite Sabimaru'],
 wp_a_0760:['Loaded Umbrella'],wp_a_0761:["Suzaku's Lotus Umbrella"],wp_a_0762:["Phoenix's Lilac Umbrella"],wp_a_0763:['Loaded Umbrella - Magnet'],
 wp_a_0770:['Divine Abduction'],wp_a_0771:['Double Divine Abduction'],wp_a_0772:['Golden Vortex'],
 wp_a_0780:['Loaded Spear','Loaded Spear Thrust type'],wp_a_0781:['Loaded Spear Cleave type','Leaping Flame'],wp_a_0782:['Spiral Spear'],
 wp_a_0790:['Finger Whistle','Mountain Echo','Malcontent']};
// The katana and Mortal Blade were named for every game before the other names came.
const weaponNames=(id,game=currentGame())=>game==='sekiro'||id==='wp_a_0300'||id==='wp_a_0310'?sekiroWeapons[id]||[]:[];
const extraName=p=>{const name=weaponNames(p.id)[0];return name?`<small>${escape(name)}</small>`:'';};
function weaponNote(){
 return (currentGame()==='sekiro'?'Auto places the katana in the right hand, the Mortal Blade on the back and prosthetics on their authored sockets.':'Auto puts any weapon in the right hand and its scabbard or extra model on the left hip, like the game’s default WepAbsorpPosParam row. Two-handed keeps a scabbard on the hip. Sheathed hangs the whole weapon on the hip opposite its hand.')
  +' Custom dummy IDs take one ID for every model, or a list such as 20, 30 for model 0, model 1. Sockets come from this game’s c0000.chrbnd; this is a fixed preview placement, and HKX alone does not specify draw or sheath events.';
}
function extrasBlock(extras,title){
 const many=extras.length>12,chosen=extras.filter(p=>p.selected),shown=many?chosen:extras,open=extrasOpen??chosen.length>0;
 return `<details class="extras"${open?' open':''}><summary>${escape(title)} <span class="chip">${chosen.length} of ${extras.length}</span></summary><p class="note">${escape(weaponNote())}</p>`
  +shown.map(p=>`<div class="equip-row"><label title="${escape(p.path)}"><input type="checkbox" data-extra="${escape(p.path)}" ${p.selected?'checked':''}><span>${escape(p.name)}${extraName(p)}</span></label>${/^wp_/i.test(p.id)?weaponControl(p):''}</div>`).join('')
  +(many?`<div class="add-extra"><input class="text-input" list="extra-parts" id="extra-input" placeholder="Add a weapon or part · type its ID" spellcheck="false" aria-label="Add a weapon or part"><datalist id="extra-parts">${extras.filter(p=>!p.selected).map(p=>`<option value="${escape(p.name)}">`).join('')}</datalist><button type="button" class="secondary" id="extra-add">${icon('plus')}Add</button></div>`:'')
  +socketList()+'</details>';
}
function renderParts(){
 const box=$('parts'),folder=inputMethod==='folder',clip=folder?currentClip():null;
 $('manual-model-tools').hidden=folder;$('scan').hidden=folder;document.querySelector('.model-tools').hidden=folder&&!clip;
 $('preset').hidden=folder&&!(clip?.character==='c0000'&&clip?.game==='sekiro');
 if(!parts.length){box.innerHTML='';renderModelMasks();updateAssembly();return;}
 if(folder&&clip&&clip.character!=='c0000'){
  const selected=parts.find(p=>p.selected),options=parts.map(p=>`<option value="${escape(p.path)}" ${p===selected?'selected':''}>${escape(p.name)} · ${escape(basename(p.path))}</option>`).join('');
  box.innerHTML=`<div class="part-row"><span>Model file</span><select data-npc-model aria-label="Character model for this animation" title="${escape(selected?.path||'')}"><option value="">Choose a model</option>${options}</select></div>`;
  renderModelMasks();updateAssembly();return;
 }
 const wolf=isWolfAssembly(),player=!wolf&&parts.some(p=>/^(fc|hd|hr|am|bd|lg)_/i.test(p.id));
 const roles=wolf?wolfRoles:player?playerRoles.filter(([r])=>parts.some(p=>prefix(p)===r)):[];
 const regions=new Set(roles.map(([r])=>r)),weapons=parts.filter(p=>/^wp_/i.test(p.id)),others=parts.filter(p=>!regions.has(prefix(p))&&!/^wp_/i.test(p.id));
 let html=roles.length?(player?'<p class="note">One piece per region is chosen when only one is available. Pick the outfit pieces you want.</p>':'')+roles.map(regionRow).join(''):(others.length?`<p class="note">Select the model that matches the animation’s skeleton. One model is enough.</p>${others.map(modelRow).join('')}`:'');
 const extras=roles.length?[...others,...weapons]:weapons;
 if(extras.length)html+=extrasBlock(extras,roles.length?'Weapons & extra parts':'Weapon placement');
 box.innerHTML=html;renderModelMasks();updateAssembly();
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
function addExtra(){
 const input=$('extra-input');if(!input)return;
 const value=input.value.trim().toLowerCase(),found=parts.find(p=>!p.selected&&(p.id.toLowerCase()===value||p.name.toLowerCase()===value));
 if(!found)return toast(value?`No part is named ${input.value.trim()}.`:'Type a part ID such as WP_A_0300.',true);
 found.selected=true;extrasOpen=true;renderParts();saveSoon();
}
function updateAssembly(){
 const enabled=$('includeCharacter').checked,selected=enabled?parts.filter(p=>p.selected):[],whole=selected.some(p=>/^c\d{4}$/i.test(p.id));
 const regions={head:/^(fc|hd|hr)_/i,arms:/^am_/i,torso:/^bd_/i,legs:/^lg_/i};
 document.querySelectorAll('#figure .region').forEach(g=>g.classList.toggle('on',whole||selected.some(p=>regions[g.dataset.region].test(p.id))));
 $('figure').classList.toggle('rig',!enabled);
 const count=['fc','am','bd','lg'].filter(r=>selected.some(p=>prefix(p)===r)).length,model=selected.find(p=>/^c\d{4}$/i.test(p.id));
 $('model-summary').textContent=!enabled?'Rig only: no model is added.':!parts.length?(inputMethod==='folder'?(currentClip()?(resolving?'Finding the model…':'No model found for this animation.'):'Choose an animation first.'):'Choose a character folder, then Find models.')
  :isWolfAssembly()?`Wolf · ${count} of 4 parts${selected.length>count?` · ${selected.length-count} extra`:''}`:model?`${model.name} · ${model.container}`:selected.length?plural(selected.length,'part')+' selected':'Choose the parts to include.';
 $('character-mode').textContent=enabled?'Model':'Rig only';
 renderSceneHead();
}
async function findModels(preserve=false){
 const source=$('characterSource').value.trim();if(!source){parts=[];renderParts();return;}
 $('scan').disabled=true;$('scan').textContent='Finding…';setNotice([]);
 try{
  const scan=await api('scan',{source,preset:$('preset').value,game:currentGame()});const selected=preserve?new Set(config.models||[]):new Set();parts=scan.parts;
  if(scan.preset)$('preset').value=scan.preset;
  if(selected.size&&parts.some(p=>selected.has(p.path)))parts.forEach(p=>p.selected=selected.has(p.path));
  if(scan.materials&&(!$('materialBinder').value||$('materialBinder').value===autoMaterial)){$('materialBinder').value=scan.materials;autoMaterial=scan.materials;}
  detectNpcModels();extrasOpen=null;renderParts();
  const notes=[];if(isWolfAssembly()&&scan.missing.length)notes.push('Some outfit parts are missing: '+scan.missing.join(', ')+'. You can choose available parts individually.');
  if(!parts.length)notes.push('No models were found. Choose a character folder, or use Choose files to add a CHRBND or FLVER.');
  setNotice(notes);saveSoon();
 }catch(e){parts=[];renderParts();setNotice([e.message],'error');toast(e.message,true);}
 finally{$('scan').disabled=false;$('scan').innerHTML=icon('cube')+'Find models';}
}
function setInputMethod(method,apply=true){
 const previous=inputMethod;
 inputMethod=method==='manual'?'manual':'folder';const folder=inputMethod==='folder';
 // The part view is the source library seen from a weapon part: the import is the same.
 if(apply){partView=method==='parts';try{localStorage.setItem('bridge-part-view',partView?'1':'0');}catch(e){}}
 applyView();updateTopbar();
 if(!apply)return;
 if(folder&&previous==='folder')return renderLibrary();
 if(folder){const source=activeSource();if(source&&!catalog)activateSource(source.id,true);else if(catalog){renderLibrary();resolveClip(true);}}
 else setNotice([]);
 renderParts();renderSceneHead();saveSoon();
}

/* Source dialog */
function openSourceDialog(source=null){
 closeSourceMenu();editing=source;detection=null;missingFolders=new Set();nameTouched=!!source;scenesTouched=!!source;
 $('source-dialog-title').textContent=source?'Edit source':'Add a source';
 $('src-path').value=source?.path||'';$('src-path').closest('.path-row').classList.remove('invalid');
 $('src-name').value=source?.name||'';$('src-game').value=source?.game||'auto';
 $('src-recursive').checked=source?.recursive!==false;$('src-scenes').value=source?.scenes||'';$('src-list').value=source?.fileList||'';$('src-list-field').hidden=!source?.fileList;
 dialogFolders=JSON.parse(JSON.stringify(source?.folders||{}));
 clearTimeout(removeTimer);$('src-remove').hidden=!source;$('src-remove').dataset.armed='';$('src-remove').textContent='Remove source';
 $('src-save').textContent=source?'Save':'Save and scan';$('src-detect').hidden=true;
 $('source-dialog').showModal();setDialogLayout(source?.layout||'auto');
 if(source?.path)detectPath();else $('src-path').focus();
}
function setDialogLayout(layout){
 dialogLayout=layout;
 document.querySelectorAll('#src-layout [data-layout]').forEach(b=>{const on=b.dataset.layout===layout;b.classList.toggle('active',on);b.setAttribute('aria-checked',String(on));});
 $('src-custom').hidden=layout!=='custom';
 if(layout==='custom'){if(!kinds.some(([k])=>dialogFolders[k]?.length))fillGameFolders();else renderFolders();}
 layoutNote();suggestScenes();
}
function layoutNote(){
 const d=detection,found=d?(d.layout==='game'?`a game folder${d.game?' ('+gameNames[d.game]+')':''}`:'a collected folder'):'';
 if(d?.engine&&d.engine!=='fromsoft'&&['auto','game'].includes(dialogLayout)){$('src-layout-note').textContent=d.container==='pak'?`Reads ${gameNames[d.game]||'the game'}’s PAK archives by the names in its file list.`:'Reads the extracted natives folder.';return;}
 $('src-layout-note').textContent={auto:d?`Detect reads this as ${found}.`:'Detect chooses Game folder or Collected from what is inside.',game:'Reads chr, parts and mtd or material, like the game’s own data folder.',folder:'Reads every archive below the folder. Files that share a folder belong together.',custom:'Name the folders for each kind yourself, relative to the source folder or absolute.'}[dialogLayout];
}
function suggestScenes(){
 if(scenesTouched||!detection?.sceneFolders)return;
 const effective=dialogLayout==='auto'?detection.layout:dialogLayout;
 $('src-scenes').value=detection.sceneFolders[effective==='folder'?'folder':'game']||'';
}
const gameFolders=game=>({animations:['chr'],characters:['chr'],parts:['parts'],textures:['chr','parts'],materials:game==='er'?['material']:game?['mtd']:['mtd','material']});
function fillGameFolders(){dialogFolders=gameFolders($('src-game').value!=='auto'?$('src-game').value:(detection?.game||''));renderFolders();checkFolders();}
function renderFolders(){
 $('src-folders').innerHTML=kinds.map(([kind,label,types])=>`<div class="folder-kind"><span>${escape(label)}<small>${escape(types)}</small></span><div class="folder-entries">${(dialogFolders[kind]||[]).map((f,i)=>`<span class="folder-chip${missingFolders.has(kind+'|'+f)?' missing':''}" title="${escape(missingFolders.has(kind+'|'+f)?f+' · this folder does not exist':f)}"><span>${escape(f)}</span><button type="button" data-remove-folder="${kind}|${i}" aria-label="Remove ${escape(f)}">${icon('close')}</button></span>`).join('')}<span class="folder-add"><input data-add-input="${kind}" placeholder="folder" spellcheck="false" aria-label="Add a folder for ${escape(label.toLowerCase())}"><button type="button" data-add-folder="${kind}" aria-label="Add the typed folder">${icon('plus')}</button><button type="button" data-browse-folder="${kind}" aria-label="Browse for a folder for ${escape(label.toLowerCase())}">${icon('folder')}</button></span></div></div>`).join('');
}
function addFolder(kind,entry){
 entry=String(entry||'').trim().replace(/[\\/]+$/,'');if(!entry)return;
 const list=dialogFolders[kind]||(dialogFolders[kind]=[]);if(!list.some(f=>samePath(f,entry)))list.push(entry);
 renderFolders();checkFolders();
}
let checkTimer;
function checkFolders(){clearTimeout(checkTimer);checkTimer=setTimeout(()=>{if($('src-path').value.trim())detectPath();},300);}
async function detectPath(){
 const path=$('src-path').value.trim(),seq=++detectSequence;
 if(!path){detection=null;$('src-detect').hidden=true;layoutNote();return;}
 $('src-detect').hidden=false;$('src-detect').className='detect';$('src-detect').innerHTML=`${icon('search')}<div><b>Looking at the folder…</b></div>`;
 try{
  const found=await api('detect',{path,folders:dialogLayout==='custom'?dialogFolders:{},recursive:$('src-recursive').checked,fileList:$('src-list').value.trim()});
  if(seq!==detectSequence)return;
  detection=found;missingFolders=new Set(found.missing||[]);
  // A chosen chr, parts or Game folder stands for the game folder that holds it.
  if(found.layout==='game'&&!samePath(found.root,path)&&dialogLayout!=='folder'){$('src-path').value=found.root;if(dialogLayout==='custom')return detectPath();}
  if(!nameTouched)$('src-name').value=found.name||basename(found.root);
  renderDetection();layoutNote();suggestScenes();if(dialogLayout==='custom')renderFolders();
 }catch(e){if(seq!==detectSequence)return;detection=null;$('src-list-field').hidden=!$('src-list').value.trim();$('src-detect').className='detect warn';$('src-detect').innerHTML=`${icon('warn')}<div><b>The bridge cannot read this folder</b>${escape(e.message)}</div>`;layoutNote();}
}
function renderDetection(){
 // A custom layout is described by its own folders, not by what the source folder holds.
 const d=detection,custom=dialogLayout==='custom'&&d.custom,c=(custom?d.custom.counts:d.counts)||{},game=!custom&&d.layout==='game';
 $('src-list-field').hidden=!d.needsFileList;
 const chips=[[c.animations,'animation archive'],[c.characters,'model'],[c.parts,'part'],[c.textures,'texture package'],[c.materials,'material library','material libraries']].filter(([n])=>n).map(([n,w,m])=>`<span class="chip">${escape(plural(n,w,m))}</span>`).join('');
 const nested=custom?'':(d.nested||[]).map(n=>`<button type="button" class="text-button" data-nested="${escape(n.path)}">${icon('arrow')}${escape(n.name)}${n.game?' · '+escape(gameNames[n.game]):''}</button>`).join('');
 const title=custom?'Custom layout':game?`Game folder · ${gameNames[d.game]||'game not identified'}`:c.animations?'Collected folder':nested?'A folder of games':'No animation archives here';
 const lines=(custom?[c.animations?'Files are matched by character across these folders.':'The animation folders hold no ANIBND archives yet.',missingFolders.size?`${plural(missingFolders.size,'folder')} not found; ${missingFolders.size===1?'it is':'they are'} skipped.`:'',d.custom.limited?'Counted the first 50,000 files of each folder.':'']
  :[game?(d.evidence?`Identified by ${d.evidence}.`:'No executable or archive names the game; choose it below.'):c.animations?'Archives that share a folder are matched together.':nested?'Choose one of the game folders inside.':'A source needs ANIBND archives such as c0000.anibnd.dcx.',d.note,d.limited?'Counted the first 50,000 files.':'']).filter(Boolean);
 $('src-detect').className='detect '+((game||c.animations)&&!(custom&&missingFolders.size)?'ok':'warn');
 $('src-detect').innerHTML=`${game?glyphHtml({game:d.game,name:d.name}):`<span class="glyph" data-game="custom">${icon(c.animations?'folder':'warn')}</span>`}<div class="grow"><b>${escape(title)}</b>${lines.map(escape).join('<br>')}${chips?`<div class="chips">${chips}</div>`:''}${nested?`<div class="nested">${nested}</div>`:''}</div>`;
}
async function saveSource(){
 const path=$('src-path').value.trim();
 if(!path){$('src-path').closest('.path-row').classList.add('invalid');$('src-path').focus();return toast('Choose the source folder first.',true);}
 if(!detection||!samePath(detection.path,path)&&!samePath(detection.root,path))await detectPath();
 if(!detection){$('src-path').closest('.path-row').classList.add('invalid');return toast('Choose an existing folder for this source.',true);}
 if(dialogLayout==='custom'&&!dialogFolders.animations?.length)return toast('A custom layout needs at least one animation folder.',true);
 const finalPath=$('src-path').value.trim(),folders=dialogLayout==='custom'?Object.fromEntries(kinds.map(([k])=>[k,dialogFolders[k]||[]])):{};
 const effective=dialogLayout==='auto'?detection.layout:dialogLayout;
 const draft={name:$('src-name').value.trim()||basename(finalPath)||finalPath,path:finalPath,layout:dialogLayout,game:$('src-game').value,folders,recursive:$('src-recursive').checked,
  fileList:detection.needsFileList?$('src-list').value.trim():'',
  scenes:$('src-scenes').value.trim()||detection.sceneFolders?.[effective==='folder'?'folder':'game']||joinPath(finalPath,'Blender')};
 let source=editing;
 const changed=!source||['path','layout','game','recursive','fileList'].some(k=>(source[k]||'')!==(draft[k]||''))||JSON.stringify(source.folders||{})!==JSON.stringify(folders);
 if(source)Object.assign(source,draft);else{source={id:crypto.randomUUID().slice(0,8),...draft,catalog:'',state:{}};sources.push(source);}
 if(changed)Object.assign(source,{catalog:'',root:'',resolved:'',detectedGame:'',stats:null});
 $('source-dialog').close();
 if(!editing||source.id===activeId&&changed)await activateSource(source.id);else renderSources();
 if(changed)await scanSource(source);
 saveSoon();
}
function removeSource(){
 const button=$('src-remove');
 if(button.dataset.armed!=='1'){button.dataset.armed='1';button.textContent='Click again to remove';clearTimeout(removeTimer);removeTimer=setTimeout(()=>{button.dataset.armed='';button.textContent='Remove source';},3500);return;}
 const removed=editing;sources=sources.filter(s=>s!==removed);$('source-dialog').close();
 if(removed.id===activeId)activateSource(sources[0]?.id||'',true);else renderSources();
 saveSoon();toast(`Removed ${removed.name}. Its files were not touched.`);
}

/* Browse */
async function pick(key,{multiple=false,apply}={}){
 if(activePicker)return toast('A Browse window is already open. Finish or cancel that selection first.');
 const picker={id:crypto.randomUUID(),controller:new AbortController(),timedOut:false};activePicker=picker;
 const buttons=[...document.querySelectorAll('[data-pick],#add-models,#src-browse,#src-scenes-browse,#src-list-browse,[data-browse-folder]')].map(button=>({button,disabled:button.disabled}));
 buttons.forEach(({button})=>button.disabled=true);
 const title=help[key]?.[0]||pickTitles[key]||'Files';
 layer($('picker-status'));$('picker-status').hidden=false;$('picker-message').textContent=`Choosing ${title.toLowerCase()}…`;$('cancel-picker').disabled=false;
 const timeout=setTimeout(()=>{picker.timedOut=true;picker.controller.abort();api('pick',{kind:'cancel',requestId:picker.id}).catch(()=>{});},310000);
 try{
  const kind=['characterSource','textureDirectory','src-path','src-scenes','folder'].includes(key)?'folder':['outputBlend','outputHKX'].includes(key)?'save':'file';
  const current=(key==='folder'?$('src-path').value:$(key)?.value)||$('characterSource').value||'';
  const result=await api('pick',{kind,current,title,multiple,requestId:picker.id,filter:filters[key]||''},picker.controller.signal);
  if(!result.paths?.length)return;
  if(apply)return await apply(result.paths);
  if(multiple){
   const scan=await api('scan',{files:result.paths});
   if(inputMethod==='folder'){const known=new Set(parts.map(p=>p.path));parts.push(...scan.parts.filter(p=>!known.has(p.path)));}
   else{parts=scan.parts;$('characterSource').value='';detectNpcModels();}
   renderParts();saveSoon();return;
  }
  $(key).value=result.paths[0];$(key).dispatchEvent(new Event('change',{bubbles:true}));
 }catch(e){if(e.name!=='AbortError')toast(e.message,true);else if(picker.timedOut)toast('Browse timed out. Open Browse again to retry.',true);}
 finally{clearTimeout(timeout);if(activePicker===picker){activePicker=null;$('picker-status').hidden=true;buttons.forEach(({button,disabled})=>button.disabled=disabled);}}
}
async function cancelPicker(){
 const picker=activePicker;if(!picker)return;$('cancel-picker').disabled=true;
 try{
  const result=await api('pick',{kind:'cancel',requestId:picker.id});
  if(result.paths?.includes('cancelled')){picker.controller.abort();toast('Browse cancelled.');}
  else if(activePicker===picker)toast('The Browse window is already closing.');
 }catch(e){toast(e.message,true);}finally{if(activePicker===picker)$('cancel-picker').disabled=false;}
}

/* Jobs */
function requireFields(keys){
 for(const key of keys){if(!$(key).value.trim()){if(key==='blender')showPage('settings');const field=$(key);field.closest('.path-row')?.classList.add('invalid');field.scrollIntoView({behavior:'smooth',block:'center'});field.focus();throw Error(`Choose ${help[key]?.[0].toLowerCase()||key} first.`);}}
}
async function startJob(extra,{source='',character=''}={}){
 if(jobStarting||job?.status==='running')throw Error('Wait for the current operation, or cancel it first.');
 jobStarting=true;
 try{
  rememberState();const started=await api('job',{...values(),...extra});
  initiatedJobs.add(started.id);if(source)jobSources.set(started.id,source);if(character)jobCharacters.set(started.id,character);
  updateJob(started);return started;
 }finally{jobStarting=false;}
}
async function start(mode){
 try{
  if(job?.status==='running')throw Error('Wait for the current operation, or cancel it first.');
  const folder=inputMethod==='folder';
  if(mode==='import'&&folder){
   const clip=currentClip();
   if(!activeSource())throw Error('Add a source first.');
   if(!catalog||catalogLoading)throw Error('Scan the source and choose an animation first.');
   if(!clip)throw Error('Choose an animation first.');
   if(!clip.ready)throw Error(clip.issues.join('\n'));
   if(resolving||!selection)throw Error('Wait until the animation’s files are matched.');
  }
  if(mode==='import'&&donorIsCurrent())throw Error('This animation is the retarget donor. Choose the animation of the character that receives it, or remove the donor.');
  requireFields(mode==='import'?(folder?['blender','outputBlend']:['blender','animation','skeleton','outputBlend']):mode==='inspect'?['blender','inputBlend']:['blender','inputBlend','outputHKX']);
  if(mode==='import'&&$('includeCharacter').checked){
   if(!folder&&!parts.length&&$('characterSource').value)await findModels();
   if(!parts.some(p=>p.selected))throw Error('Select one or more character parts, or switch to Rig only.');
  }
  if(mode==='export'){
   if($('frameRange').value==='custom'&&!(parseFloat($('frameEnd').value)>parseFloat($('frameStart').value))){$('sampling-options').open=true;throw Error('Enter a custom frame range whose end frame is after its start frame.');}
   const rate=$('frameRate').value.trim(),tolerance=$('tolerance').value.trim();
   if(rate&&!(+rate>=1&&+rate<=240)){$('sampling-options').open=true;throw Error('Choose an output frame rate between 1 and 240 fps, or leave it empty for the source rate.');}
   if(!$('spline-options').hidden&&tolerance&&!(+tolerance>=1e-6&&+tolerance<=.1))throw Error('Spline tolerance must be between 0.000001 and 0.1.');
   if($('addToBinder').checked){
    if(!$('binder').value.trim()&&suggestedBinder())$('binder').value=suggestedBinder();
    requireFields(['binder']);
    const name=$('binderMember').value.trim();
    if(name&&!/^a\d{3}_\d{6}\.hkx$/i.test(name))throw Error('Name the HKX in the binder like the game’s clips, aXXX_YYYYYY.hkx, such as a050_002000.hkx.');
   }
  }
  const extra={mode};if(mode!=='inspect')extra.force=$(mode+'-force').checked;
  await startJob(extra);toast({import:'Creating your Blender scene…',export:'Exporting your animation…',inspect:'Reading the scene in Blender…'}[mode]);
 }catch(e){toast(e.message,true);}
}
const stageSets={discover:[['inventory','Scan source'],['done','Choose a character']],inventory:[['inventory','Read archives'],['done','Animations listed']],inspect:[['validate','Check'],['blender','Read scene'],['done','Ready']],
 import:[['validate','Check'],['decode','Decode'],['character','Character'],['blender','Blender'],['done','Ready']],export:[['validate','Check'],['blender','Sample'],['write','Write HKX'],['done','Ready']]};
function updateJob(value){
 if(!value)return;job=value;
 const running=value.status==='running',success=value.status==='success',error=value.status==='failed';
 ['run-import','run-export','inspect-scene','rescan'].forEach(id=>$(id).disabled=running);
 $('rescan').classList.toggle('spinning',running&&value.mode==='discover');
 $('cancel-job').hidden=!running;
 const dock=$('activity');dock.classList.toggle('running',running);dock.classList.toggle('error',error);dock.classList.toggle('success',success);
 $('job-message').textContent=value.message;$('job-status').textContent=running?'RUNNING':value.status.toUpperCase();
 const seconds=Math.max(0,Math.floor((value.ended||Date.now()/1000)-value.started));$('job-time').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
 $('progress-track').hidden=false;$('progress-fill').style.width=(success?100:value.progress)+'%';
 const stages=stageSets[value.mode]||stageSets.export;let index=stages.findIndex(s=>s[0]===value.stage);
 // Import reads a changed archive again before it decodes.
 if(index<0&&value.stage==='inventory')index=0;
 $('job-stages').hidden=false;$('job-stages').innerHTML=stages.map((s,i)=>`<span class="${i<index||success?'complete':i===index?'current':''}">${i<index||success?'✓':'○'} ${s[1]}</span>`).join('');
 const pre=$('log'),atBottom=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-40;pre.textContent=value.logs.join('\n')||'Starting…';if(atBottom)pre.scrollTop=pre.scrollHeight;
 if(error){$('log-panel').hidden=false;$('toggle-log').setAttribute('aria-expanded','true');}
 renderResult(value);
 if(!running&&!handledJobs.has(value.id)){handledJobs.add(value.id);if(value.id!==startJobId)finishJob(value);}
 const key=value.id+value.status;if(key!==jobKey){jobKey=key;renderLibrary();}
}
function renderResult(value){
 // Scans show their result in the library itself.
 const box=$('result'),r=value.report||{};box.hidden=value.status!=='success'||['inventory','discover'].includes(value.mode);
 if(box.hidden||box.dataset.job===value.id)return;
 box.dataset.job=value.id;
 if(value.mode==='inspect'){const info=r.scene;box.innerHTML=`<div class="result-info"><b title="${escape(value.output)}">${escape(basename(value.output))}</b><p>${escape(info?`Rig ${info.rig} · ${plural(info.actions.length,'armature action')} · choose the action and frames`:'Scene read')}</p></div>`;return;}
 let details;
 if(value.mode==='import')details=`${plural(r.frames,'frame')} · ${plural(r.parts,'model part')} · ${plural(r.textures,'material image')}${r.donor?` · donor ${String(r.donor.clip).replace(/\.hkx$/i,'')}, ${plural(r.donor.frames,'frame')}`:''}`;
 else{
  const readback=r.readback;
  details=`${plural(r.frames,'frame')}${r.frameRate?' at '+formatNumber(r.frameRate)+' fps':''} · ${plural(r.tracks,'track')} ·${r.compression}${r.compression==='spline'&&r.quantization?' '+r.quantization:''}${r.bytes?` · ${Math.ceil(r.bytes/1024)} KB`:''}`;
  if(readback)details+=` · readback max ${readback.maxRotationDegrees.toFixed(3)}°, ${(readback.maxTranslation*1000).toFixed(2)} mm${readback.maxRotationDegrees>.5||readback.maxTranslation>.005?' (may be visible; lower the spline tolerance)':''}`;
 }
 details+=partSummary(value.mode,r);
 if(r.binder)details+=` · ${r.binder.replaced?'replaced':'added as new clip'} ${basename(r.binder.member)} in ${basename(r.binder.binder)}`;
 const warnings=r.warnings?.length?` · ${r.warnings.length} ${value.mode==='import'?'material':'export'} notice${r.warnings.length===1?'':'s'} (see Activity)`:'';
 box.innerHTML=`<div class="result-info"><b title="${escape(value.output)}">${escape(basename(value.output))}</b><p>${escape(details+warnings)}</p></div>${value.mode==='import'?`<button type="button" class="secondary" data-open="blender">${icon('play')}Open Blender</button>`:''}<button type="button" class="secondary" data-open="reveal">${icon('folder')}Show file</button>`;
 box.querySelectorAll('[data-open]').forEach(el=>el.addEventListener('click',()=>openOutput(el.dataset.open,value.output)));
}
function finishJob(value){
 const r=value.report||{},success=value.status==='success';
 if(value.mode==='discover'){
  const source=sources.find(s=>s.id===jobSources.get(value.id))||sources.find(s=>samePath(s.root||s.path,r.folder)||samePath(s.path,r.folder));
  if(source&&success){
   Object.assign(source,{catalog:r.catalog,root:r.folder,resolved:r.layout,detectedGame:r.game||'',stats:{layout:r.layout,characters:r.characters,clips:r.clips,warnings:r.warnings?.length||0,scanned:Date.now()}});
   if(source.id===activeId&&inputMethod==='folder')loadCatalog(source,true);
   renderSources();saveSoon();
  }else if(source&&!catalog)scanProblem={source:source.id,message:value.message};
 }
 if(value.mode==='inventory'){
  const source=sources.find(s=>s.id===jobSources.get(value.id)),character=jobCharacters.get(value.id);
  if(success&&activeSource()&&samePath(r.catalog,catalogPath))return loadCatalog(activeSource());
  if(!success&&source&&character)inventoryProblem={key:source.id+'|'+character,message:value.status==='cancelled'?'Reading was cancelled.':value.message};
 }
 if(value.mode==='import'&&success){
  if(!samePath($('inputBlend').value.trim(),value.output))forgetScene();$('inputBlend').value=value.output;config.inputBlend=value.output;config.lastImportedBlend=value.output;saveSoon();
  if($('openWhenDone').checked&&initiatedJobs.has(value.id)&&!opened.has(value.id)){opened.add(value.id);openOutput('blender',value.output);}
  if(r.catalogRefreshed&&activeSource()?.catalog)loadCatalog(activeSource(),true);
 }
 if(value.mode==='inspect'&&success&&r.scene&&samePath(value.output,$('inputBlend').value.trim())){sceneInfo=r.scene;renderScene();}
 renderLibrary();ensureInventory();
}
async function openOutput(action,path){try{await api('open',{action,path});}catch(e){toast(e.message,true);}}
async function poll(){
 try{const state=await api('state');if(state.job)updateJob(state.job);$('connection-text').textContent='On this computer';$('connection-text').previousElementSibling.classList.add('green');}
 catch(e){$('connection-text').textContent='Workspace disconnected';$('connection-text').previousElementSibling.classList.remove('green');}
 pollTimer=setTimeout(poll,job?.status==='running'?700:1800);
}
/* Cache: what work\asset-cache holds, and removing what no source uses */
function showCache(u){
 const rows=[['Total',u.total],['Unpacked animations',u.archives],['Scans',u.catalogs],['Skeleton previews',u.previews],['Not used by any source',u.unused]];
 $('cache-usage').innerHTML=rows.map(([label,n])=>`<dt>${escape(label)}</dt><dd>${n?formatBytes(n):'None'}</dd>`).join('');
 $('cache-clean').disabled=!u.unused;
}
let cacheBusy=false;
async function measureCache(action){
 if(cacheBusy)return;cacheBusy=true;$('cache-clean').disabled=true;
 if(action)$('cache-usage').innerHTML='<dt>Total</dt><dd>Removing unused files…</dd>';
 try{
  const u=await api('cache',action?{action}:{});showCache(u);
  if(action)toast(u.freed?`Removed ${formatBytes(u.freed)} of unused files.`:'Nothing to remove: every cached file is in use.');
 }catch(e){$('cache-usage').innerHTML='<dt>Total</dt><dd>Not measured</dd>';toast(e.message,true);}finally{cacheBusy=false;}
}
async function checkEnvironment(){
 $('check-environment').disabled=true;
 try{
  rememberState();config=values();await api('settings',config);const env=await api('environment');
  $('environment-cards').innerHTML=env.map(e=>`<div class="env-card"><span class="state"><i class="dot ${e.ready?'green':''}"></i>${e.ready?'READY':e.optional?'OPTIONAL':'SETUP NEEDED'}</span><h3>${escape(e.title)}</h3><p>${escape(e.detail)}</p></div>`).join('');
  const b=env.find(e=>e.key==='blender');$('blender-ready').innerHTML=`<i class="dot ${b.ready?'green':''}"></i><span>${b.ready?'Blender is ready':'Choose Blender in Setup'}</span><button type="button" class="text-button" data-page="settings">Change</button>`;
  $('setup-dot').classList.toggle('green',env.every(e=>e.ready||e.optional));
 }catch(e){toast(e.message,true);}finally{$('check-environment').disabled=false;}
}

/* Game packages */
let packageAction=null;
function renderPackages(state){
 $('package-folder').textContent=`Installed packages go to ${state.folder}.`;
 const list=state.packages||[];
 $('package-list').innerHTML=list.length?list.map(p=>{
  const games=p.games.map(g=>g.name+(g.verified?'':' · untested')).join(', ');
  const problem=p.error||(p.duplicate?'Not used: an earlier folder has the same package.':'');
  const where=p.installed?'':' <span class="optional">BRIDGE FOLDER</span>';
  const remove=p.installed?`<button type="button" class="text-button danger" data-remove-package="${escape(p.id)}">Remove</button>`:'';
  return `<div class="package-row"><div><b>${escape(p.name)}</b> <span class="package-version">${escape(p.version)}</span>${where}<p>${escape(games||'No games')}</p>${problem?`<p class="danger">${escape(problem)}</p>`:''}${p.problems.map(x=>`<p>${escape(x)}</p>`).join('')}</div>${remove}</div>`;
 }).join(''):'<p class="note">No game packages installed.</p>';
}
async function loadPackages(){
 try{renderPackages(await api('packages'));}catch(e){$('package-list').innerHTML=`<p class="note">${escape(e.message)}</p>`;}
}
function openPackageDialog(action){
 packageAction=action;const info=action.info;
 const fact=(name,value)=>value?`<dt>${escape(name)}</dt><dd>${escape(value)}</dd>`:'';
 if(action.mode==='install'){
  $('package-dialog-title').textContent=info.replaces?`Replace ${info.name} ${info.replaces}`:`Install ${info.name}`;
  $('package-facts').innerHTML=fact('Package',`${info.name} ${info.version} (${info.id})`)+fact('Games',info.games.join(', '))+fact('Tools',info.tools.join(', '))
   +fact('Authors',info.authors.join(', '))+fact('License',info.license)+fact('Homepage',info.homepage)+fact('Files',`${info.files} files, ${formatBytes(info.bytes)}`)+fact('ZIP',action.zip);
  $('package-warning').textContent='A game package runs its own code on this computer with your rights, like any program you download. Install it only if you trust where it came from.'
   +(info.replaces?` It replaces the installed version ${info.replaces}.`:'')+(info.shadowedBy?` The copy in ${info.shadowedBy} stays in use while it is there; the bridge folder comes first.`:'');
  $('package-confirm').textContent='Install';
 }else{
  $('package-dialog-title').textContent=`Remove ${info.name}`;
  $('package-facts').innerHTML=fact('Package',`${info.name} ${info.version} (${info.id})`)+fact('Folder',info.folder);
  $('package-warning').textContent='This deletes the package folder. Your sources and scenes stay, but sources of its games cannot be scanned until you install the package again.';
  $('package-confirm').textContent='Remove';
 }
 $('package-dialog').showModal();
}
async function confirmPackage(){
 const action=packageAction;if(!action)return;$('package-confirm').disabled=true;
 try{
  const state=action.mode==='install'?await api('packages/install',{zip:action.zip,confirm:true}):await api('packages/remove',{id:action.info.id,confirm:true});
  $('package-dialog').close();renderPackages(state);applyGames((await api('games')).games);await checkEnvironment();
  toast(action.mode==='install'?`Installed ${action.info.name} ${action.info.version}.`:`Removed ${action.info.name}.`);
 }catch(e){toast(e.message,true);}finally{$('package-confirm').disabled=false;}
}
$('package-install').addEventListener('click',()=>pick('package',{apply:async paths=>openPackageDialog({mode:'install',zip:paths[0],info:await api('packages/inspect',{zip:paths[0]})})}));
$('package-form').addEventListener('submit',event=>{event.preventDefault();confirmPackage();});
$('package-dialog').addEventListener('close',()=>packageAction=null);

/* Events */
document.addEventListener('click',event=>{
 const t=event.target,hit=s=>t.closest(s);let el;
 if(!$('source-menu').hidden&&!hit('#source-menu')&&!hit('#source-button'))closeSourceMenu();
 if((el=hit('[data-help]'))){const entry=help[el.dataset.help];if(entry){layer($('help-dialog'));$('help-title').textContent=entry[0];$('help-text').textContent=entry[1];$('help-dialog').showModal();}return;}
 if((el=hit('[data-page]')))return showPage(el.dataset.page);
 if((el=hit('[data-menu]'))){closeSourceMenu();return el.dataset.menu==='add'?openSourceDialog():showPage('sources');}
 if((el=hit('[data-source]'))){closeSourceMenu(true);if(el.dataset.source!==activeId)activateSource(el.dataset.source);return;}
 if((el=hit('[data-use]')))return activateSource(el.dataset.use);
 if((el=hit('[data-scan]')))return scanSource(sources.find(s=>s.id===el.dataset.scan));
 if((el=hit('[data-edit]')))return openSourceDialog(sources.find(s=>s.id===el.dataset.edit));
 if(hit('[data-scan-active]'))return scanSource();
 if(hit('[data-retry-inventory]')){inventoryProblem=null;renderClips();renderMatches();return ensureInventory(showsParts()?partPlayer():currentCharacter());}
 if((el=hit('[data-weapon-part]')))return selectWeapon(el.dataset.weaponPart);
 if((el=hit('[data-part-clip]')))return selectPartClip(el.dataset.partClip);
 if((el=hit('[data-match]')))return useMatch(el.dataset.match);
 if((el=hit('[data-character]')))return selectCharacter(el.dataset.character);
 if((el=hit('.clip-row'))){$('clip-list').focus({preventScroll:true});return selectClip(clipView[+el.dataset.index].id);}
 if((el=hit('[data-action]'))){$('exportAction').value=el.dataset.action;renderActions();updateExportOptions();return saveSoon();}
 if((el=hit('[data-range]'))){$('frameRange').value=el.dataset.range;updateExportOptions();return saveSoon();}
 if((el=hit('[data-theme-choice]'))){config.theme=el.dataset.themeChoice;applyTheme(config.theme);return saveSoon();}
 if((el=hit('[data-cache-choice]'))){config.previewCache=el.dataset.cacheChoice;applyCacheMode(config.previewCache);saveSoon();
  prefetchClips(inputMethod==='folder'&&$('preview-block').open&&!!selection);return setTimeout(measureCache,700);}
 if((el=hit('[data-input]')))return el.dataset.input!==(partView&&inputMethod==='folder'?'parts':inputMethod)&&setInputMethod(el.dataset.input);
 if((el=hit('[data-layout]'))){setDialogLayout(el.dataset.layout);return checkFolders();}
 if((el=hit('[data-nested]'))){$('src-path').value=el.dataset.nested;nameTouched=false;return detectPath();}
 if((el=hit('[data-remove-folder]'))){const [kind,i]=el.dataset.removeFolder.split('|');dialogFolders[kind].splice(+i,1);renderFolders();return checkFolders();}
 if((el=hit('[data-add-folder]'))){const input=document.querySelector(`[data-add-input="${el.dataset.addFolder}"]`);return addFolder(el.dataset.addFolder,input.value);}
 if((el=hit('[data-browse-folder]'))){const kind=el.dataset.browseFolder;return pick('folder',{apply:paths=>addFolder(kind,relativeTo(paths[0],$('src-path').value.trim()))});}
 if((el=hit('[data-pick]')))return pick(el.dataset.pick);
 if((el=hit('[data-remove-package]'))){const id=el.dataset.removePackage;api('packages').then(state=>{const info=state.packages.find(p=>p.id===id&&p.installed);if(info)openPackageDialog({mode:'remove',info});}).catch(e=>toast(e.message,true));return;}
 if(hit('[data-close-package]'))return $('package-dialog').close();
 if(hit('[data-close]'))return $('source-dialog').close();
});
document.addEventListener('keydown',event=>{
 const tag=document.activeElement?.tagName;
 if(event.key==='/'&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!/^(INPUT|SELECT|TEXTAREA)$/.test(tag)&&!document.querySelector('dialog[open]')&&currentPage()==='import'&&inputMethod==='folder'){event.preventDefault();const filter=$(showsParts()?'part-clip-filter':'clip-filter');filter.focus();filter.select();}
 if(event.key==='Enter'&&event.target.matches?.('[data-add-input]')){event.preventDefault();addFolder(event.target.dataset.addInput,event.target.value);}
 if(event.key==='Enter'&&event.target.id==='extra-input'){event.preventDefault();addExtra();}
});
$('source-button').addEventListener('click',()=>$('source-menu').hidden?openSourceMenu():closeSourceMenu());
$('source-menu').addEventListener('keydown',event=>{
 const items=[...$('source-menu').querySelectorAll('.menu-item')],index=items.indexOf(document.activeElement);
 if(event.key==='Escape'){event.preventDefault();closeSourceMenu(true);}
 else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();items[(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
 else if(event.key==='Tab')closeSourceMenu();
});
addEventListener('resize',()=>closeSourceMenu());
$('rescan').addEventListener('click',()=>scanSource());
$('add-source').addEventListener('click',()=>openSourceDialog());
document.querySelector('.rail-brand').addEventListener('click',e=>{e.preventDefault();showPage('import');});
$('character-filter').addEventListener('input',renderCharacters);
$('character-list').addEventListener('keydown',event=>{
 if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;event.preventDefault();
 const rows=[...$('character-list').querySelectorAll('.char-row')],index=rows.indexOf(document.activeElement);
 rows[Math.max(0,Math.min(rows.length-1,index+(event.key==='ArrowDown'?1:-1)))]?.focus();
});
$('weapon-filter').addEventListener('input',renderWeapons);
$('part-clip-filter').addEventListener('input',renderWeaponClips);
// Arrow keys, Home and End move between the rows of the part view's lists.
for(const [id,selector] of [['weapon-list','.char-row'],['part-clip-list','.part-clip-row'],['match-list','.match-row']])$(id).addEventListener('keydown',event=>{
 const rows=[...$(id).querySelectorAll(selector)],index=rows.indexOf(document.activeElement);
 const target={ArrowDown:index+1,ArrowUp:index-1,Home:0,End:rows.length-1}[event.key];
 if(target===undefined||!rows.length)return;event.preventDefault();
 rows[Math.max(0,Math.min(rows.length-1,index<0?0:target))].focus();
});
$('clip-filter').addEventListener('input',()=>{$('clip-list').scrollTop=0;renderClips();scrollToClip();});
$('archive-filter').addEventListener('change',()=>{$('clip-list').scrollTop=0;renderClips();scrollToClip();});
$('clip-list').addEventListener('scroll',()=>{if(!painting){painting=true;requestAnimationFrame(()=>{painting=false;paintClips();});}},{passive:true});
new ResizeObserver(()=>paintClips()).observe($('clip-list'));
$('clip-list').addEventListener('keydown',event=>{
 const page=Math.max(1,Math.floor($('clip-list').clientHeight/ROW)-1),index=clipView.findIndex(c=>c.id===clipId);
 const target={ArrowDown:index+1,ArrowUp:index-1,PageDown:index+page,PageUp:index-page,Home:0,End:clipView.length-1}[event.key];
 if(target===undefined||!clipView.length)return;event.preventDefault();
 selectClip(clipView[Math.max(0,Math.min(clipView.length-1,index<0?0:target))].id,160);
});
$('parts').addEventListener('change',event=>{
 const el=event.target,d=el.dataset;
 if(d.npcModel!==undefined){
  parts.forEach(p=>p.selected=p.path===el.value);
  const source=activeSource(),clip=currentClip();
  if(source&&clip)source.state={...source.state,modelChoices:{...source.state?.modelChoices,[clip.character]:el.value}};
  renderParts();return saveSoon();
 }
 if(d.model||d.extra){const part=parts.find(p=>p.path===(d.model||d.extra));if(part)part.selected=el.checked;if(d.extra&&!el.checked&&document.getElementById('extra-input'))renderParts();else{renderModelMasks();updateAssembly();}return saveSoon();}
 if(d.region!==undefined){parts.filter(p=>prefix(p)===d.region).forEach(p=>p.selected=p.path===el.value);renderParts();return saveSoon();}
 if(d.regionInput!==undefined){
  const value=el.value.trim().toLowerCase(),matches=parts.filter(p=>prefix(p)===d.regionInput),found=matches.find(p=>p.id.toLowerCase()===value||p.name.toLowerCase()===value);
  if(value&&!found){toast(`No ${d.regionInput.toUpperCase()} part is named ${el.value.trim()}.`,true);return renderParts();}
  matches.forEach(p=>p.selected=p===found);renderParts();return saveSoon();
 }
 if(d.weapon){
  config.weaponAttachments||={};const input=$('parts').querySelector(`[data-dummy="${CSS.escape(d.weapon)}"]`);input.hidden=el.value!=='custom';
  if(el.value==='custom'&&!input.value)input.value=currentGame()==='sekiro'?'20':'20, 30';
  config.weaponAttachments[d.weapon]=el.value==='custom'?'dummy:'+input.value.replace(/\s+/g,''):el.value;return saveSoon();
 }
 if(d.dummy){
  if(!el.value.trim()||!el.checkValidity())return toast('Enter one dummy ID, or a comma list such as 20, 30 for model 0, model 1.',true);
  config.weaponAttachments||={};config.weaponAttachments[d.dummy]='dummy:'+el.value.replace(/\s+/g,'');saveSoon();
 }
});
$('parts').addEventListener('click',event=>{if(event.target.closest('#extra-add'))addExtra();});
$('model-masks').addEventListener('change',event=>{
 const id=event.target.dataset.mask;if(id===undefined)return;
 const path=maskPath,groups=maskCache.get(path)||[];
 config.modelMasks||={};
 const selected=new Set(config.modelMasks[path]||groups.map(group=>group.id));
 if(event.target.checked)selected.add(id);else selected.delete(id);
 config.modelMasks[path]=[...selected];renderModelMasks();saveSoon();
});
$('parts').addEventListener('toggle',event=>{if(event.target.matches('.extras'))extrasOpen=event.target.open;},true);
document.querySelectorAll('[data-config]').forEach(el=>el.addEventListener('change',()=>{
 const id=el.id,folder=inputMethod==='folder';el.closest('.path-row')?.classList.remove('invalid');
 if(id==='includeCharacter')toggleCharacter();
 if(id==='preset'){if(folder)resolveClip();else findModels();}
 if(id==='characterSource')findModels();
 if(['animation','skeleton','compendium'].includes(id)&&!folder)$('skeletonCompendium').value='';
 if(['materialBinder','textureDirectory','referenceModel'].includes(id)&&folder&&activeSource()){
  // A path entered here is kept for this source; clearing it brings back the one the source provides.
  const source=activeSource(),overrides={...source.state?.overrides};
  if(el.value.trim())overrides[id]=el.value.trim();else{delete overrides[id];el.value=selection?.[id]||'';}
  source.state={...source.state,overrides};
 }
 if(id==='game'&&folder)$('game').value=activeSource()?.game||'auto';
 if(id==='inputBlend')forgetScene();
 if(['exportAction','frameRange','frameStart','frameEnd','frameRate','trackSet','rootMotion','rootBone','exportGame','exportParts','addToBinder','binder','binderMember','outputHKX'].includes(id))updateExportOptions();
 if(['blender','writer','decoder','oodle'].includes(id))checkEnvironment();
 renderSceneHead();saveSoon();
}));
['frameStart','frameEnd','frameRate','rootBone'].forEach(id=>$(id).addEventListener('input',updateExportOptions));
document.querySelectorAll('[name="format"]').forEach(el=>el.addEventListener('change',()=>{updateExportOptions();saveSoon();}));
['import-force','export-force'].forEach(id=>$(id).addEventListener('change',()=>{config.force=$(id).checked;saveSoon();}));
$('scan').addEventListener('click',()=>findModels());$('add-models').addEventListener('click',()=>pick('models',{multiple:true}));
$('donor-pin').addEventListener('click',()=>{try{pinDonor();}catch(e){toast(e.message,true);}});$('donor-remove').addEventListener('click',removeDonor);
$('run-import').addEventListener('click',()=>start('import'));$('run-export').addEventListener('click',()=>start('export'));$('inspect-scene').addEventListener('click',()=>start('inspect'));
$('check-environment').addEventListener('click',checkEnvironment);
$('cache-clean').addEventListener('click',()=>measureCache('clean'));
$('cancel-picker').addEventListener('click',cancelPicker);
$('cancel-job').addEventListener('click',async()=>{try{updateJob(await api('cancel',{}));}catch(e){toast(e.message,true);}});
$('toggle-log').addEventListener('click',()=>{$('log-panel').hidden=!$('log-panel').hidden;$('toggle-log').setAttribute('aria-expanded',String(!$('log-panel').hidden));});
$('copy-log').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('log').textContent);toast('Activity log copied.');}catch(e){toast('Select the activity text and press Ctrl+C.');}});
$('close-help').addEventListener('click',()=>$('help-dialog').close());$('help-ok').addEventListener('click',()=>$('help-dialog').close());
$('help-dialog').addEventListener('click',e=>{if(e.target===$('help-dialog'))$('help-dialog').close();});
$('source-form').addEventListener('submit',e=>{e.preventDefault();saveSource();});
$('src-path').addEventListener('change',()=>{$('src-path').closest('.path-row').classList.remove('invalid');detectPath();});
$('src-name').addEventListener('input',()=>nameTouched=true);
$('src-scenes').addEventListener('input',()=>scenesTouched=true);
$('src-game').addEventListener('change',layoutNote);
$('src-recursive').addEventListener('change',()=>{if(dialogLayout==='custom')checkFolders();});
$('src-from-game').addEventListener('click',fillGameFolders);
$('src-remove').addEventListener('click',removeSource);
$('src-browse').addEventListener('click',()=>pick('src-path',{apply:paths=>{$('src-path').value=paths[0];$('src-path').closest('.path-row').classList.remove('invalid');nameTouched=!!editing&&nameTouched;return detectPath();}}));
$('src-scenes-browse').addEventListener('click',()=>pick('src-scenes',{apply:paths=>{$('src-scenes').value=paths[0];scenesTouched=true;}}));
$('src-list-browse').addEventListener('click',()=>pick('src-list',{apply:paths=>{$('src-list').value=paths[0];return detectPath();}}));
$('src-list').addEventListener('change',()=>checkFolders());
$('source-dialog').addEventListener('close',()=>{detectSequence++;layer($('toast'));});
$('use-import').addEventListener('click',()=>{const path=job?.mode==='import'&&job.status==='success'?job.output:(config.lastImportedBlend||$('inputBlend').value);if(!path)return toast('Import an animation first, or browse to an existing scene.');if(!samePath($('inputBlend').value.trim(),path))forgetScene();$('inputBlend').value=path;saveSoon();toast('Imported scene selected.');});
$('shutdown').addEventListener('click',async()=>{try{await api('shutdown',{});clearTimeout(pollTimer);toast('Workspace closed. You can close this window.');$('connection-text').textContent='Workspace closed';document.querySelectorAll('button').forEach(b=>b.disabled=true);}catch(e){toast(e.message,true);}});
document.querySelectorAll('[data-help]').forEach(b=>{const entry=help[b.dataset.help];if(entry)b.title=entry[0];});
(async()=>{
 try{
  const state=await api('state');
  $('app-version').textContent=state.version?'v'+state.version:'';
  applyGames(state.games);
  setValues(state.config);
  if(state.job&&state.job.status!=='running')startJobId=state.job.id;
  setInputMethod(state.config.inputMethod,false);renderSources();
  if(inputMethod==='folder'&&activeSource())await activateSource(activeId,true);
  else{
   renderLibrary();
   if(inputMethod==='manual'){if(config.characterSource)await findModels(true);else if(config.models?.length){const scan=await api('scan',{files:config.models});parts=scan.parts;detectNpcModels();}}
  }
  renderParts();await checkEnvironment();loadPackages();if(state.job)updateJob(state.job);poll();
 }catch(e){toast('Could not connect to Animation Bridge. Reopen the UI launcher.\n'+e.message,true);}
})();
