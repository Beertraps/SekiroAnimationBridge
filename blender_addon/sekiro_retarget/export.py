"""Write the target's action as HKX with the Animation Bridge installed on this computer.

Blender samples the open scene with the bridge's own exporter (blender_bridge.py),
so nothing has to be saved first. The bridge's conversion Python then writes and
checks the HKX exactly as the export page and the CLI do.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
import bpy
from . import retarget

APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
EVENT_PREFIX = 'BRIDGE_EVENT '


def ui_settings():
    try:
        return json.loads((APP / 'ui-settings.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def bridge_folder(preferences=None):
    """The bridge's standalone folder: from the preferences, the last bridge run, or this add-on's own checkout."""
    candidates = []
    if preferences is not None and preferences.bridge_folder:
        candidates.append(Path(bpy.path.abspath(preferences.bridge_folder)))
    try:
        candidates.append(Path(json.loads((APP / 'bridge-location.json').read_text(encoding='utf-8'))['folder']))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    candidates.append(Path(__file__).resolve().parents[2])
    for folder in candidates:
        for path in (folder, folder / 'standalone'):
            if (path / 'bridge_runtime.py').is_file() and (path / 'blender_bridge.py').is_file():
                return path
    return None


def writer_python(preferences=None):
    """The bridge's conversion Python: from the preferences, the bridge settings, or the setup default."""
    if preferences is not None and preferences.writer:
        return Path(bpy.path.abspath(preferences.writer))
    return Path(ui_settings().get('writer') or APP / 'writer-env/Scripts/python.exe')


def load_exporter(folder):
    spec = importlib.util.spec_from_file_location('sekiro_animation_bridge_exporter', folder / 'blender_bridge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The bridge writes its game registry here (bridge_runtime.remember_location); these are the games known before it did.
GAMES_FILE = APP / 'games.json'
KNOWN_GAMES = [dict(id=key, name=name, executables=[exe], capabilities=dict(export=True))
               for key, name, exe in (('sekiro', 'Sekiro', 'sekiro.exe'), ('ds1', 'Dark Souls: Prepare to Die', 'DarkSouls.exe'),
                                      ('ds1r', 'Dark Souls Remastered', 'DarkSoulsRemastered.exe'),
                                      ('ds3', 'Dark Souls III', 'DarkSoulsIII.exe'), ('er', 'Elden Ring', 'eldenring.exe'))]


def registry():
    """The bridge's games: its registry when it has run on this computer, else the games every bridge exports."""
    try:
        games = json.loads(GAMES_FILE.read_text(encoding='utf-8'))['games']
        if isinstance(games, list) and all(isinstance(g, dict) and 'id' in g for g in games):
            return games
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return KNOWN_GAMES


def exportable(game):
    """Whether the bridge writes this game's animation format."""
    return any(g['id'] == game and g.get('capabilities', {}).get('export') for g in registry())


def game_name(game):
    return next((g['name'] for g in registry() if g['id'] == game), game)


GAME_EXECUTABLES = tuple(sorted({exe for g in KNOWN_GAMES + registry() for exe in g.get('executables', [])}))


def in_game_folder(path):
    """Whether a path lies in a game installation, where the bridge writes nothing (as its protect_output)."""
    return any((folder / name).is_file() for folder in Path(path).resolve().parents for name in GAME_EXECUTABLES)


def default_binder(target, output=''):
    """The binder to add the HKX to: the archive the clip came from, or a copy of it beside the HKX where that archive
    is in the game installation; '' where the scene does not record it."""
    archive = (retarget.read_motion(target) or {}).get('archive', '') if target else ''
    if not archive or not in_game_folder(archive):
        return archive
    folder = Path(bpy.path.abspath(output)).parent if output else Path(bpy.path.abspath('//') or '.')
    return str(folder / Path(archive).name)


class Job:
    """The conversion Python writing one HKX, read line by line on a worker thread."""

    def __init__(self, command, scratch, sampled):
        self.scratch, self.sampled = scratch, sampled
        self.stage, self.message, self.progress, self.report, self.log = 'write', 'Writing HKX', 0, {}, []
        self.done, self.code = False, None
        self.process = subprocess.Popen(
            [str(part) for part in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace', env={**os.environ, 'TEMP': str(scratch), 'TMP': str(scratch)},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                try:
                    data = json.loads(line[len(EVENT_PREFIX):]) if line.startswith(EVENT_PREFIX) else None
                except ValueError:
                    data = None
                if isinstance(data, dict):
                    self.stage = data.get('stage', self.stage)
                    self.message = data.get('message', self.message)
                    self.progress = data.get('progress', self.progress)
                    self.report = data.get('report') or self.report
                else:
                    self.log = (self.log + [line])[-200:]
            self.code = self.process.wait()
        finally:
            shutil.rmtree(self.scratch, ignore_errors=True)
            self.done = True

    @property
    def failed(self):
        return self.done and (self.code != 0 or self.stage != 'done')

    def cancel(self):
        if self.process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], capture_output=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                self.process.kill()


def start(context, settings, preferences=None):
    """Sample the target into motion JSON and start writing the HKX. Returns the running Job."""
    scene, target = context.scene, settings.target
    retarget.set_export_target(scene, target)
    recorded = (retarget.read_motion(target) or {}).get('game')
    if settings.export_game == 'auto' and not recorded:
        raise ValueError('This scene was imported before the bridge recorded the game. Choose the Game under '
                         '4. Export HKX > Export settings.')
    game = recorded if settings.export_game == 'auto' else settings.export_game
    if not exportable(game):
        raise ValueError(f'The bridge imports {game_name(game)} but cannot write its animation format. Make a character from '
                         'Sekiro, Dark Souls or Elden Ring the target, bake onto it and export that.')
    if not settings.export_path:
        raise ValueError('Choose an output .hkx file.')
    output = Path(bpy.path.abspath(settings.export_path)).resolve()
    if output.suffix.lower() != '.hkx':
        raise ValueError('Choose an output filename ending in .hkx.')
    if not settings.export_replace and (output.exists() or output.with_suffix('.motion.json').exists()):
        raise ValueError('The output exists. Choose a new name or enable Replace existing.\n' + str(output))
    binder = bpy.path.abspath(settings.export_binder_path).strip() if settings.export_binder else ''
    if settings.export_binder and not binder:
        raise ValueError('Choose the Binder to add the HKX to, or turn off Add to animation binder.')
    folder = bridge_folder(preferences)
    if folder is None:
        raise ValueError('The Animation Bridge was not found. Start its UI once, or set its folder in the add-on preferences.')
    writer = writer_python(preferences)
    if not writer.is_file():
        raise ValueError('The conversion Python was not found. Run the bridge setup, or set it in the add-on preferences.\n' + str(writer))
    scratch = Path(tempfile.mkdtemp(prefix='SekiroRetargetExport-'))
    try:
        motion = scratch / 'sampled.motion.json'
        sampled = load_exporter(folder).export_motion(
            motion, frame_range=settings.export_frames, tracks=settings.export_tracks,
            root_motion='none' if settings.export_root == 'NONE' else 'auto')
        request = dict(mode='write', motionJson=str(motion), outputHKX=str(output), writer=str(writer),
                       format=settings.export_format, quantization=settings.export_quantization,
                       tolerance=f'{settings.export_tolerance:g}', verify=settings.export_verify,
                       force=settings.export_replace, exportGame=settings.export_game, oodle=ui_settings().get('oodle', ''),
                       addToBinder=bool(binder), binder=binder, binderMember=settings.export_member.strip())
        (scratch / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        return Job([writer, '-E', '-X', 'utf8', folder / 'bridge_runtime.py', '--request', scratch / 'request.json'],
                   scratch, sampled)
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def summary(job):
    """One status line for a finished export."""
    if job.failed:
        detail = next((line for line in reversed(job.log) if line.strip()), '')
        return 'HKX export failed: ' + (job.message if job.stage == 'error' else detail or job.message)
    report = job.report
    text = f"Exported {report.get('frames', '?')} frames, {report.get('tracks', '?')} tracks, {report.get('compression', '')}"
    if report.get('bytes'):
        text += f", {report['bytes']:,} bytes"
    readback = report.get('readback') or {}
    if 'maxRotationDegrees' in readback:
        text += f"; readback max {readback['maxRotationDegrees']:.3f}°, {readback.get('maxTranslation', 0) * 1000:.2f} mm"
    root = report.get('rootMotion') or job.sampled.get('rootMotion', '')
    text += f"; root motion: {root}" if root else ''
    binder = report.get('binder')
    if binder:
        text += (f"; {'replaced' if binder['replaced'] else 'added as a new clip'} {Path(binder['member'].replace(chr(92), '/')).name} "
                 f"in {Path(binder['binder']).name}")
        text += f", the binder before kept as {Path(binder['backup']).name}" if binder.get('backup') else ''
        if not binder['replaced']:
            text += '. A new animation ID needs a TAE entry before the game plays it'
    warnings = report.get('warnings') or job.sampled.get('warnings') or []
    return text + '.' + ''.join(' ' + warning for warning in warnings)
