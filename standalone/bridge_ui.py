"""Local-only Animation Bridge UI. Uses Python's standard library; no web packages needed."""
from __future__ import annotations
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from bridge_runtime import APP, HERE, HOME, EVENT_PREFIX, default_decoder, remember_location
from character_assets import scan_character, asset_id, ROLES

SETTINGS = APP / 'ui-settings.json'
# Sources have their own file: an older bridge rewrites ui-settings.json with only the keys it knows.
SOURCES = APP / 'ui-sources.json'
SOURCE_KEYS = {'sources','activeSource'}
LOCK = threading.RLock()
JOB = None
CONFIG = {}
KEYS = {'blender','writer','decoder','animation','compendium','skeleton','characterSource','materialBinder',
        'textureDirectory','preset','outputBlend','inputBlend','outputHKX','format','includeCharacter','openWhenDone','force','models','previewTexture','lastImportedBlend',
        'assetFolder','assetCharacter','assetClip','assetCatalog','inputMethod','skeletonCompendium','oodle','referenceModel','weaponAttachments','game','exportGame',
        'exportAction','frameRange','frameStart','frameEnd','frameRate','trackSet','rootMotion','rootBone','rootVertical','rootYaw',
        'quantization','tolerance','verify','sources','activeSource','sourceLayout','sourceFolders','sourceRecursive','theme','donor',
        'partAnimations','exportParts'}


def find_blender():
    for base in [APP.parent/'Programs/Blender',
                 Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'Blender Foundation',
                 Path.home()/'Downloads']:
        if base.is_dir():
            candidates = list(base.glob('Blender*/blender.exe'))
            candidates += list(base.glob('blender*/blender.exe'))
            if candidates:
                return str(sorted(candidates)[-1])
    on_path = shutil.which('blender')
    if on_path:
        return on_path
    candidates = list((Path.home()/'Downloads/DoomSlayerTools').glob('Blender*/blender*-windows-x64/blender.exe'))
    return str(sorted(candidates)[-1]) if candidates else ''


def defaults():
    inputs = HOME/'work/input'
    source = inputs/'wolf_default_model/source/parts'
    if not source.is_dir(): source = inputs/'wolf_default_model'
    result = dict(blender=find_blender(), writer=str(APP/'writer-env/Scripts/python.exe'),
        decoder=str(default_decoder()), animation='', compendium='', skeleton='',
        characterSource=str(source) if source.is_dir() else '', materialBinder='', textureDirectory='',
        preset='auto', game='auto', exportGame='auto', models=[], includeCharacter=True, openWhenDone=False, force=False,
        inputMethod='folder', assetFolder='', assetCharacter='', assetClip='', assetCatalog='', skeletonCompendium='', oodle='',referenceModel='',weaponAttachments={},
        outputBlend=str(HOME/'work/wolf_animation.blend'), inputBlend='',
        outputHKX=str(HOME/'work/wolf_animation_edited.hkx'), format='interleaved',
        exportAction='', frameRange='scene', frameStart='', frameEnd='', frameRate='', trackSet='original', rootMotion='auto',
        rootBone='', rootVertical=False, rootYaw=False, quantization='threecomp40', tolerance='0.001', verify=True,
        sources=[], activeSource='', sourceLayout='folder', sourceFolders={}, sourceRecursive=True, theme='auto',
        partAnimations=True, exportParts=False)
    for key, name in [('animation','a000_000100.hkx'), ('compendium','a000_lo.compendium'), ('skeleton','c0000_skeleton.hkx')]:
        if (inputs/name).is_file(): result[key]=str(inputs/name)
    if SETTINGS.is_file():
        try:
            saved=json.loads(SETTINGS.read_text())
            result.update({k:v for k,v in saved.items() if k in KEYS})
            if 'inputMethod' not in saved: result['inputMethod']='manual'
        except (ValueError, OSError): pass
    try:
        saved=json.loads(SOURCES.read_text(encoding='utf-8')) if SOURCES.is_file() else None
    except (ValueError, OSError): saved=None
    if isinstance(saved,dict):
        result.update({k:v for k,v in saved.items() if k in SOURCE_KEYS})
    elif result['assetFolder'] and not result['sources']:
        # Before sources existed, the one assets folder was a collected folder.
        folder=Path(result['assetFolder'])
        source=dict(id=secrets.token_hex(4),name=folder.name or str(folder),path=str(folder),layout='folder',
                    game=result.get('game','auto'),folders={},recursive=True,scenes=str(folder/'Blender'),
                    catalog=result.get('assetCatalog',''),state={})
        result.update(sources=[source],activeSource=source['id'],sourceLayout='folder')
    # A release ZIP brings its own decoder. It replaces the build_decoder.cmd default
    # and the decoder of another unpacked bridge version; a custom choice stays.
    bundled, saved_decoder = HOME/'decoder/SekiroMotionDecoder.exe', Path(result['decoder'])
    if bundled.is_file() and (not saved_decoder.is_file() or saved_decoder == APP/'decoder/SekiroMotionDecoder.exe'
                              or (saved_decoder.parent.parent/'standalone/bridge_runtime.py').is_file()):
        result['decoder'] = str(bundled)
    return result


def environment():
    result = []
    for key, title in [('blender','Blender'),('writer','Python + conversion libraries'),('decoder','HKX decoder')]:
        path=CONFIG.get(key, '')
        ready=bool(path and Path(path).is_file())
        detail='Ready' if ready else 'Choose the executable or run setup'
        if ready and key=='writer':
            try:
                p=subprocess.run([path,'-E','-X','utf8','-c','import soulstruct.flver,soulstruct.havok,numpy; print("Conversion libraries ready")'],
                    capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                ready=p.returncode==0; detail='Conversion libraries ready' if ready else 'Run tools\\setup_writer.cmd to install the libraries'
            except (OSError, subprocess.TimeoutExpired): ready=False; detail='Python could not start'
        if ready and key=='decoder':
            try:
                p=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=10,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                ready=p.returncode==0 and 'native-packfiles' in p.stdout
                detail='Tagfile + packfile decoder ready' if ready else 'Select the decoder of a current release ZIP, or rebuild it with tools\\SekiroMotionDecoder\\build_decoder.cmd'
            except (OSError, subprocess.TimeoutExpired): ready=False; detail='The decoder could not start'
        result.append(dict(key=key,title=title,ready=ready,detail=detail))
    # Soulstruct Havok's 32-bit CompressAnim.exe links against the Visual C++ 2010 runtime.
    runtime=Path(os.environ.get('SystemRoot','C:/Windows'))/'SysWOW64/msvcr100.dll'
    result.append(dict(key='spline',title='Spline compression',ready=runtime.is_file(),optional=True,
        detail='Visual C++ 2010 runtime ready' if runtime.is_file() else
            'Spline export needs the Microsoft Visual C++ 2010 Redistributable (x86). Interleaved export works without it.'))
    try:
        path=CONFIG.get('writer', '')
        p=subprocess.run([path,'-E','-X','utf8',str(HERE/'dcx_codec.py'),'status','--oodle',CONFIG.get('oodle','')],
            capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        status=json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode==0 else {}
        ready=bool(status.get('ready'))
        result.append(dict(key='dcx',title='DCX / Oodle',ready=ready,
            detail='KRAK + DFLT ready · '+status.get('path','') if ready else 'Select your game’s oo2core_6_win64.dll for KRAK archives.'))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        result.append(dict(key='dcx',title='DCX / Oodle',ready=False,detail='Prepare conversion Python, then choose the game’s Oodle DLL if needed.'))
    return result


def persist(config):
    with LOCK:
        CONFIG.update({k:v for k,v in config.items() if k in KEYS})
        SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        for path,value in ((SETTINGS,{k:v for k,v in CONFIG.items() if k not in SOURCE_KEYS}),
                           (SOURCES,{k:CONFIG[k] for k in SOURCE_KEYS if k in CONFIG})):
            staging=path.with_suffix('.tmp')
            staging.write_text(json.dumps(value,indent=2),encoding='utf-8'); os.replace(staging,path)


def snapshot():
    with LOCK:
        if not JOB: return None
        return {k:v for k,v in JOB.items() if k not in ('process',)}


def worker(job, request):
    logs=HOME/'work/logs'; logs.mkdir(parents=True,exist_ok=True)
    log_path=logs/(time.strftime('%Y%m%d-%H%M%S')+'-'+request['mode']+'-'+job['id'][:6]+'.log')
    try:
        with tempfile.TemporaryDirectory(prefix='SekiroBridgeUI-') as tmp:
            p=Path(tmp)/'request.json'; p.write_text(json.dumps(request),encoding='utf-8')
            writer=request.get('writer') or sys.executable
            if not Path(writer).is_file(): raise ValueError('Writer Python is missing. Open Settings and select it, or run tools/setup_writer.cmd.')
            with LOCK:
                if job['status']=='cancelled': return
                process=subprocess.Popen([writer,'-E','-X','utf8',str(HERE/'bridge_runtime.py'),'--request',str(p)],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                    env={**os.environ,'TEMP':tmp,'TMP':tmp},
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                job['process']=process
            with log_path.open('w',encoding='utf-8') as log:
                for line in process.stdout:
                    line=line.rstrip(); log.write(line+'\n'); log.flush()
                    with LOCK:
                        if line.startswith(EVENT_PREFIX):
                            data=json.loads(line[len(EVENT_PREFIX):])
                            job.update({k:v for k,v in data.items() if k in ('stage','message','progress','output','report')})
                        else:
                            job['logs'].append(line); job['logs']=job['logs'][-400:]
            code=process.wait()
            with LOCK:
                if job['status']!='cancelled':
                    # A reported 'done' event and successful exit are both required.
                    job['status']='success' if code==0 and job.get('stage')=='done' else 'failed'
                    if job['status']=='failed' and job.get('stage')!='error': job['message']='Conversion stopped. Expand Activity for the details.'
    except Exception as exc:
        with LOCK: job.update(status='failed',message=str(exc),stage='error')
    finally:
        with LOCK: job['ended']=time.time(); job['logFile']=str(log_path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_json(self, obj, status=200):
        data=json.dumps(obj).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)
    def authorized(self):
        host=f'127.0.0.1:{self.server.server_port}'
        origin=self.headers.get('Origin')
        allowed=self.headers.get('Host')==host and (not origin or origin=='http://'+host) and secrets.compare_digest(self.headers.get('X-Bridge-Token',''),self.server.token)
        if allowed: self.server.last_seen=time.monotonic()
        return allowed
    def do_GET(self):
        if self.path.startswith('/api/'):
            if not self.authorized(): return self.send_json({'error':'This workspace session is not authorized. Reopen the UI launcher.'},403)
            if self.path=='/api/state':
                version=(HOME/'VERSION').read_text(encoding='utf-8').strip() if (HOME/'VERSION').is_file() else ''
                return self.send_json(dict(config=CONFIG,job=snapshot(),root=str(HOME),version=version))
            if self.path=='/api/environment': return self.send_json(environment())
            return self.send_json({'error':'Unknown route'},404)
        routes={'/':('ui/index.html','text/html'),'/style.css':('ui/style.css','text/css'),'/app.js':('ui/app.js','text/javascript'),
                '/preview.js':('ui/preview.js','text/javascript'),
                '/favicon.ico':('ui/icons/bridge.ico','image/vnd.microsoft.icon')}
        # Keep assets explicitly allowlisted, just like the other UI files.
        for name,mime in [('bridge.svg','image/svg+xml'),('favicon.svg','image/svg+xml'),
                          ('favicon-32.png','image/png'),('apple-touch-icon.png','image/png'),
                          ('bridge-192.png','image/png'),('bridge-512.png','image/png'),
                          ('bridge.ico','image/vnd.microsoft.icon')]:
            routes['/icons/'+name]=('ui/icons/'+name,mime)
        if self.path not in routes: return self.send_error(404)
        file,mime=routes[self.path]; data=(HERE/file).read_bytes()
        self.send_response(200); self.send_header('Content-Type',mime+('; charset=utf-8' if mime.startswith('text/') else ''))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        global JOB
        if not self.authorized(): return self.send_json({'error':'Unauthorized workspace session'},403)
        try:
            length=int(self.headers.get('Content-Length',0))
            if length>1024*1024: raise ValueError('Request is too large.')
            data=json.loads(self.rfile.read(length) or b'{}')
            if self.path=='/api/settings':
                persist(data); return self.send_json({'ok':True})
            if self.path=='/api/detect':
                from asset_discovery import detect_source
                found=detect_source(data.get('path',''),CONFIG.get('oodle',''))
                # Custom layout folders are relative to the chosen folder unless absolute.
                folders=data.get('folders') if isinstance(data.get('folders'),dict) else {}
                base=Path(found['path'])
                found['missing']=[f'{kind}|{entry}' for kind,entries in folders.items() for entry in entries
                                  if not (Path(entry) if Path(entry).is_absolute() else base/entry).is_dir()]
                if folders:
                    from asset_sources import count_custom
                    counts,limited=count_custom(base,folders,data.get('recursive') is not False)
                    found['custom']={'counts':counts,'limited':limited}
                return self.send_json(found)
            if self.path=='/api/catalog':
                from asset_discovery import load_catalog, ui_catalog
                path=Path(data['path']).resolve()
                cache=(HOME/'work/asset-cache/catalogs').resolve()
                if path.parent != cache or not path.is_file(): raise ValueError('Scan the assets folder to create a catalog first.')
                return self.send_json(ui_catalog(load_catalog(path,data['folder'])))
            if self.path=='/api/resolve':
                from asset_discovery import load_catalog, selection
                path=Path(data['path']).resolve()
                if path.parent != (HOME/'work/asset-cache/catalogs').resolve(): raise ValueError('Invalid folder catalog.')
                return self.send_json(selection(load_catalog(path,data['folder']),data['clip'],data.get('preset','auto')))
            if self.path=='/api/preview':
                # The configured decoder only; the request names the clip's files.
                from clip_preview import preview
                decoder=CONFIG.get('decoder') or str(default_decoder())
                return self.send_json(preview({k:str(data.get(k) or '') for k in ('animation','skeleton','compendium','skeletonCompendium')},
                                              decoder,HOME/'work/asset-cache/previews',CONFIG.get('oodle','')))
            if self.path=='/api/part-clips':
                from clip_preview import part_rows
                catalog=None
                if data.get('path'):
                    path=Path(data['path']).resolve()
                    if path.parent != (HOME/'work/asset-cache/catalogs').resolve(): raise ValueError('Invalid folder catalog.')
                    from asset_discovery import load_catalog
                    catalog=load_catalog(path,data['folder'])
                return self.send_json(part_rows(catalog,data.get('clip',''),str(data.get('animation') or ''),
                                                [str(p) for p in data.get('models') or []],CONFIG.get('oodle','')))
            if self.path=='/api/scan':
                if data.get('files'):
                    parts=[dict(id=asset_id(p),name=asset_id(p).upper(),role=ROLES.get(asset_id(p).split('_')[0],'Extra model'),path=p,selected=True,container='Model file') for p in data['files']]
                    return self.send_json(dict(parts=parts,missing=[],materials='',count=len(parts)))
                return self.send_json(scan_character(data['source'],data.get('preset','auto'),data.get('game','auto')))
            if self.path=='/api/job':
                with LOCK:
                    if JOB and JOB['status']=='running': raise ValueError('A conversion is already running.')
                    request={k:v for k,v in data.items() if k in KEYS or k=='mode'}
                    if request.get('mode') not in ('import','export','discover','inventory','inspect'): raise ValueError('Unknown conversion mode.')
                    if request['mode']=='discover': required=['assetFolder','writer']
                    elif request['mode']=='inventory': required=['assetFolder','assetCatalog','assetCharacter','writer']
                    elif request['mode']=='inspect': required=['blender','inputBlend']
                    elif request['mode']=='import' and request.get('inputMethod')=='folder': required=['blender','assetFolder','assetCatalog','assetClip','outputBlend']
                    else: required=['blender','animation','skeleton','outputBlend'] if request['mode']=='import' else ['blender','inputBlend','outputHKX']
                    for key in required:
                        if not request.get(key): raise ValueError(f'Choose a path for {key} first.')
                    persist(request)
                    JOB=dict(id=secrets.token_hex(8),status='running',mode=request['mode'],stage='validate',progress=0,
                        message='Starting conversion',started=time.time(),ended=None,logs=[],output='',report={})
                    threading.Thread(target=worker,args=(JOB,request),daemon=True).start()
                return self.send_json(snapshot())
            if self.path=='/api/cancel':
                with LOCK:
                    if JOB and JOB['status']=='running':
                        JOB.update(status='cancelled',message='Conversion cancelled',stage='cancelled')
                        process=JOB.get('process')
                        if process and process.poll() is None:
                            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                return self.send_json(snapshot())
            if self.path=='/api/pick':
                with tempfile.TemporaryDirectory(prefix='SekiroBridgePicker-') as tmp:
                    p=Path(tmp)/'picker.json'; p.write_text(json.dumps(data),encoding='utf-8')
                    picker=subprocess.run(['powershell.exe','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(HERE/'native_picker.ps1'),'-RequestFile',str(p)],
                        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=315,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if picker.returncode: raise ValueError('The file picker could not open: '+picker.stderr.strip())
                    return self.send_json({'paths':json.loads(picker.stdout.strip().lstrip('\ufeff') or '[]')})
            if self.path=='/api/open':
                path=Path(data['path']).resolve()
                if not path.exists(): raise ValueError('The file has not been created yet.')
                if data['action']=='blender':
                    if path.suffix.lower()!='.blend': raise ValueError('Choose a .blend scene to open in Blender.')
                    subprocess.Popen([CONFIG['blender'],str(path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                elif data['action']=='reveal':
                    subprocess.Popen(['explorer.exe','/select,',str(path)])
                else: raise ValueError('Unknown open action.')
                return self.send_json({'ok':True})
            if self.path=='/api/shutdown':
                if JOB and JOB['status']=='running': raise ValueError('Cancel the active conversion before closing the workspace.')
                self.send_json({'ok':True}); threading.Thread(target=self.server.shutdown,daemon=True).start(); return
            self.send_json({'error':'Unknown route'},404)
        except subprocess.TimeoutExpired:
            self.send_json({'error':'Browse timed out. Open Browse again to retry.'},408)
        except (ValueError, KeyError, OSError) as exc:
            self.send_json({'error':str(exc)},400)
        except Exception as exc:
            self.send_json({'error':str(exc)},500)


def open_browser(url):
    edge=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
    if edge.is_file():
        subprocess.Popen([str(edge),'--app='+url,'--window-size=1360,940','--user-data-dir='+str(APP/'browser-profile'),
            '--no-first-run','--no-default-browser-check','--disable-extensions','--disable-sync',
            '--disable-background-networking'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else: webbrowser.open(url)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=0); parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--state-file',type=Path,default=APP/'ui-instance.json')
    args=parser.parse_args(); APP.mkdir(parents=True,exist_ok=True); remember_location()
    if args.state_file.is_file() and not args.no_browser:
        try:
            from urllib.request import Request,urlopen
            old=json.loads(args.state_file.read_text())
            req=Request(old['base']+'/api/state',headers={'X-Bridge-Token':old['token']})
            with urlopen(req,timeout=2) as response:
                if response.status==200: open_browser(old['url']); return
        except (OSError,ValueError,KeyError): pass
    CONFIG.update(defaults())
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler); server.daemon_threads=True
    server.token=secrets.token_urlsafe(32)
    server.last_seen=time.monotonic()
    base=f'http://127.0.0.1:{server.server_port}'
    url=base+'/#token='+server.token
    args.state_file.parent.mkdir(parents=True,exist_ok=True)
    args.state_file.write_text(json.dumps(dict(base=base,url=url,token=server.token,pid=os.getpid())),encoding='utf-8')
    print('Animation Bridge workspace: '+base,flush=True)
    if not args.no_browser:
        open_browser(url)
        def stop_when_closed():
            while True:
                time.sleep(20)
                with LOCK: busy=JOB and JOB['status']=='running'
                if not busy and time.monotonic()-server.last_seen>120:
                    server.shutdown(); return
        threading.Thread(target=stop_when_closed,daemon=True).start()
    try: server.serve_forever(poll_interval=.3)
    finally: server.server_close(); args.state_file.unlink(missing_ok=True)


if __name__=='__main__': main()
