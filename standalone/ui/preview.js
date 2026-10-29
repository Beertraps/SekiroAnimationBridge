'use strict';
/* Skeleton preview: the decoded clip's joints as a stick figure on a canvas, with play, scrub, orbit and root motion.
   Positions arrive in game space (Y up). They are drawn in Blender's frame (Z up), so the clip looks as it does in Blender. */
const ClipPreview=(()=>{
 const FOV=35*Math.PI/180,FOCAL=1/Math.tan(FOV/2),VIEW={yaw:-.75,pitch:.3};
 const reduce=matchMedia('(prefers-reduced-motion: reduce)');
 const state={data:null,frame:0,time:0,playing:false,last:0,raf:0,root:false,yaw:VIEW.yaw,pitch:VIEW.pitch,drag:null,bounds:null,hidden:new Set()};
 let canvas,ctx,els={};
 const token=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
 function mount(ids){
  canvas=document.getElementById(ids.canvas);ctx=canvas.getContext('2d');
  for(const [key,id] of Object.entries(ids))els[key]=document.getElementById(id);
  els.play.addEventListener('click',()=>setPlaying(!state.playing));
  els.frame.addEventListener('input',()=>{setPlaying(false);seek(+els.frame.value);});
  els.root.addEventListener('change',()=>{state.root=els.root.checked;measure();draw();});
  canvas.addEventListener('pointerdown',event=>{if(!state.data)return;state.drag={x:event.clientX,y:event.clientY};canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{
   if(!state.drag)return;
   orbit((event.clientX-state.drag.x)*.01,(event.clientY-state.drag.y)*.01);state.drag={x:event.clientX,y:event.clientY};
  });
  const release=()=>{state.drag=null;};canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
  canvas.addEventListener('dblclick',()=>{state.yaw=VIEW.yaw;state.pitch=VIEW.pitch;draw();});
  canvas.addEventListener('keydown',event=>{
   const turn={ArrowLeft:[-.15,0],ArrowRight:[.15,0],ArrowUp:[0,-.12],ArrowDown:[0,.12]}[event.key];
   if(turn){event.preventDefault();orbit(...turn);}
   else if(event.key===' '||event.key==='Enter'){event.preventDefault();setPlaying(!state.playing);}
   else if(event.key===','||event.key==='.'){event.preventDefault();setPlaying(false);seek(state.frame+(event.key==='.'?1:-1));}
  });
  new ResizeObserver(()=>{resize();draw();}).observe(canvas);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>draw());
  new MutationObserver(()=>draw()).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)setPlaying(false);});
  message('Choose an animation to see its skeleton move.');
 }
 function resize(){
  const ratio=devicePixelRatio||1,width=Math.round(canvas.clientWidth*ratio),height=Math.round(canvas.clientHeight*ratio);
  if(width&&height&&(canvas.width!==width||canvas.height!==height)){canvas.width=width;canvas.height=height;}
 }
 function orbit(yaw,pitch){state.yaw+=yaw;state.pitch=Math.max(-.15,Math.min(1.45,state.pitch+pitch));draw();}
 // A game-space point in the view's Z-up space: unit*B*v with the preview's basis B (docs/INTERCHANGE.md); FromSoftware's swaps Y and Z.
 function view(v){
  const basis=state.data.basis||[[1,0,0],[0,0,1],[0,1,0]],unit=state.data.unitScale||1;
  return basis.map(row=>unit*(row[0]*v[0]+row[1]*v[1]+row[2]*v[2]));
 }
 function point(frame,bone){
  const p=state.data.positions[frame];let x=p[bone*3],y=p[bone*3+1],z=p[bone*3+2];
  const r=state.root&&state.data.root?state.data.root[frame]:null;
  // Root motion turns about the game's up axis, Y, before the view converts the point.
  if(r){const c=Math.cos(r[3]),s=Math.sin(r[3]);[x,z]=[c*x+s*z,-s*x+c*z];x+=r[0];y+=r[1];z+=r[2];}
  return view([x,y,z]);
 }
 function measure(){
  const d=state.data,low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
  for(let f=0;f<d.positions.length;f++)for(let b=0;b<d.bones.length;b++){if(state.hidden.has(b))continue;const p=point(f,b);for(let i=0;i<3;i++){low[i]=Math.min(low[i],p[i]);high[i]=Math.max(high[i],p[i]);}}
  low[2]=Math.min(low[2],0);
  const center=low.map((v,i)=>(v+high[i])/2),radius=Math.max(.35,Math.hypot(...high.map((v,i)=>v-low[i]))/2);
  state.bounds={center,radius,distance:radius*1.08/Math.sin(FOV/2),grid:Math.max(1,Math.ceil(radius*1.2*2)/2)};
 }
 function project(p){
  const b=state.bounds,x=p[0]-b.center[0],y=p[1]-b.center[1],z=p[2]-b.center[2];
  const cy=Math.cos(state.yaw),sy=Math.sin(state.yaw),cp=Math.cos(state.pitch),sp=Math.sin(state.pitch);
  // Turn about the vertical axis, then look down at the pitch angle from the camera's distance.
  const right=cy*x-sy*y,ahead=sy*x+cy*y,depth=cp*ahead-sp*z,up=sp*ahead+cp*z;
  const scale=FOCAL/Math.max(.05,b.distance+depth)*Math.min(canvas.width,canvas.height)/2;
  return [canvas.width/2+right*scale,canvas.height/2-up*scale];
 }
 function line(a,b){const p=project(a),q=project(b);ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);}
 function draw(){
  if(!ctx)return;resize();
  const ratio=devicePixelRatio||1;ctx.clearRect(0,0,canvas.width,canvas.height);
  const d=state.data;if(!d||!state.bounds)return;
  const b=state.bounds,g=b.grid,cx=Math.round(b.center[0]*2)/2,cy=Math.round(b.center[1]*2)/2;
  ctx.lineWidth=ratio;ctx.strokeStyle=token('--line-2');ctx.beginPath();
  for(let v=-g;v<=g+1e-6;v+=.5){line([cx+v,cy-g,0],[cx+v,cy+g,0]);line([cx-g,cy+v,0],[cx+g,cy+v,0]);}
  ctx.stroke();
  if(state.root&&d.root){
   ctx.strokeStyle=token('--ink-4');ctx.lineWidth=1.5*ratio;ctx.beginPath();
   d.root.forEach((r,i)=>{const q=view([r[0],0,r[2]]),p=project([q[0],q[1],0]);if(i)ctx.lineTo(p[0],p[1]);else ctx.moveTo(p[0],p[1]);});ctx.stroke();
  }
  const points=d.bones.map((_,i)=>point(state.frame,i));
  ctx.strokeStyle=token('--accent');ctx.lineWidth=1.8*ratio;ctx.lineCap='round';ctx.beginPath();
  // Bones far from the body, such as a camera dummy, are left out (clip_preview.detached).
  d.parents.forEach((parent,i)=>{if(parent>=0&&!state.hidden.has(i)&&!state.hidden.has(parent))line(points[parent],points[i]);});ctx.stroke();
  ctx.fillStyle=token('--ink-2');
  points.forEach((p,i)=>{if(state.hidden.has(i))return;const q=project(p);ctx.fillRect(q[0]-ratio,q[1]-ratio,2*ratio,2*ratio);});
 }
 function seek(frame){
  const d=state.data;if(!d)return;
  state.frame=Math.max(0,Math.min(d.positions.length-1,frame));state.time=state.frame*d.frameStep/d.frameRate;controls();draw();
 }
 function controls(){
  const d=state.data;els.frame.value=String(state.frame);
  els.time.textContent=d?`Frame ${Math.min(d.frameCount,state.frame*d.frameStep+1)} of ${d.frameCount} · ${state.time.toFixed(2)} s`:'';
  els.play.setAttribute('aria-pressed',String(state.playing));els.play.setAttribute('aria-label',state.playing?'Pause':'Play');
  els.play.innerHTML=`<svg aria-hidden="true"><use href="#i-${state.playing?'pause':'play'}"/></svg>`;
 }
 function setPlaying(on){
  const d=state.data;on=!!(on&&d&&d.positions.length>1);if(on===state.playing){controls();return;}
  state.playing=on;cancelAnimationFrame(state.raf);
  if(on){state.last=null;state.raf=requestAnimationFrame(tick);}
  controls();
 }
 function tick(now){
  if(!state.playing)return;
  const d=state.data,length=(d.frameCount-1)/d.frameRate||d.duration||1;
  // The clock starts on the first frame: after a long task, such as reading a large clip, a frame's timestamp
  // can be older than performance.now() when play began, and the time would run back before frame 0.
  state.time=(state.time+Math.max(0,now-(state.last??now))/1000)%length;state.last=now;
  state.frame=Math.max(0,Math.min(d.positions.length-1,Math.round(state.time*d.frameRate/d.frameStep)));
  controls();draw();state.raf=requestAnimationFrame(tick);
 }
 function message(text,kind=''){
  els.status.textContent=text;els.status.className='preview-status'+(kind?' '+kind:'');els.status.hidden=!text;
 }
 function show(data){
  setPlaying(false);state.data=data;state.frame=0;state.time=0;state.hidden=new Set(data.detached||[]);
  els.frame.max=String(Math.max(0,data.positions.length-1));els.frame.disabled=data.positions.length<2;els.play.disabled=data.positions.length<2;
  els.root.disabled=!data.root;if(!data.root){els.root.checked=false;state.root=false;}else state.root=els.root.checked;
  canvas.setAttribute('aria-label',`Skeleton preview of ${data.clip}: ${data.bones.length} bones, ${data.frameCount} frames at ${Math.round(data.frameRate*100)/100} fps`);
  message('');measure();controls();draw();
  if(!reduce.matches)setPlaying(true);
 }
 function clear(text,kind=''){
  setPlaying(false);state.data=null;state.bounds=null;els.frame.max='0';els.frame.disabled=true;els.play.disabled=true;els.root.disabled=true;
  canvas.setAttribute('aria-label','Skeleton preview');controls();draw();message(text,kind);
 }
 return {mount,show,clear,message,pause:()=>setPlaying(false)};
})();
