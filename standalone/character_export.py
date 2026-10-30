"""Export a new Sekiro character: a template character's files with a new model, skeleton, textures and clips.

docs/CHARACTER_EXPORT_PLAN.md explains the method. The template, a vanilla character such as c1010, gives the files
the bridge cannot make: behavior, HavokScript, TAE and parameters. The bridge writes the model, textures, skeleton
and clips new, moves the template's bone numbers in the copied behavior to the new skeleton, renames the template's
ID in member paths and file names, and points chosen map parts at the new character. The result is a mod folder with
the game's relative paths. Nothing is written into the game folder.

The model comes from a character export manifest that blender_character_export.py writes from any imported scene.
`clone` writes the template itself under the new ID, which tests the writer in the game without a new model.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path, PureWindowsPath

import numpy as np

import havok_tagfile
from games.interchange import check_character_export
from games.space import FROMSOFT

HERE = Path(__file__).resolve().parent
HOME = HERE.parent
APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
CLIP = re.compile(r'a\d{3}_\d{6}\.hkx', re.I)
ID = re.compile(r'c\d{4}')
# The bones that start every FromSoftware humanoid skeleton and that the template's behavior names by number.
FRAME_BONES = 8
REQUIRED = ('Pelvis', 'L_Thigh', 'L_Calf', 'L_Foot', 'R_Thigh', 'R_Calf', 'R_Foot')
LEGS = {'L_Foot_Target2': 'L_Thigh', 'L_Foot_Target1': 'L_Calf', 'L_Foot_Target': 'L_Foot',
        'R_Foot_Target2': 'R_Thigh', 'R_Foot_Target1': 'R_Calf', 'R_Foot_Target': 'R_Foot'}
MTD = 'N:\\NTC\\data\\Material\\mtd\\character\\C[AMSN]_Decal.mtd'
MTD_CUTOUT = 'N:\\NTC\\data\\Material\\mtd\\character\\C[AMSN]_e_Decal.mtd'
# TPF format numbers of c1010's textures: BC7 sRGB color, BC7 normal, BC4 metalness.
FORMATS = dict(a=(102, 'BC7_UNORM_SRGB'), n=(106, 'BC7_UNORM'), m=(103, 'BC4_UNORM'))
MAX_VERTICES = 65535


# Tools ---------------------------------------------------------------------------------------------------------------

def writer_path():
    """SekiroCharacterWriter.exe: a release's, the one build_decoder.cmd publishes, or a development build."""
    explicit = os.environ.get('SEKIRO_CHARACTER_WRITER', '')
    candidates = ([Path(explicit)] if explicit else []) + [
        HOME / 'decoder/SekiroCharacterWriter.exe', APP / 'decoder/SekiroCharacterWriter.exe',
        APP / 'build/bin/SekiroCharacterWriter/release/SekiroCharacterWriter.exe']
    found = next((path for path in candidates if path.is_file()), None)
    if found is None:
        raise ValueError('SekiroCharacterWriter.exe was not found. Run tools\\SekiroMotionDecoder\\build_decoder.cmd, '
                         'which builds it next to the decoder.')
    return found


def texconv_path():
    import soulstruct.base.textures as textures
    path = Path(textures.__file__).parent / 'texconv.exe'
    if not path.is_file():
        raise ValueError(f'texconv.exe is missing from Soulstruct: {path}. Run tools\\setup_writer.cmd again.')
    return path


def run_writer(command, job, folder, name=None):
    """Run one writer command on a JSON job. Returns its JSON report."""
    folder.mkdir(parents=True, exist_ok=True)
    name = name or command
    job_path, report_path = folder / f'{name}.job.json', folder / f'{name}.report.json'
    job_path.write_text(json.dumps(job, indent=1), encoding='utf-8')
    result = subprocess.run([str(writer_path()), command, str(job_path), str(report_path)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f'exit code {result.returncode}'
        raise RuntimeError(f'SekiroCharacterWriter {command}: {detail}')
    return json.loads(report_path.read_text(encoding='utf-8'))


def load_mapping():
    """The Retarget Assistant's bone matcher, which needs no Blender."""
    path = HOME / 'blender_addon/sekiro_retarget/mapping.py'
    spec = importlib.util.spec_from_file_location('sekiro_retarget_mapping', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Files ---------------------------------------------------------------------------------------------------------------

def template_files(game_root, template, map_name=''):
    """The template's files in an unpacked Sekiro folder, by kind."""
    root = Path(game_root)
    files = dict(chrbnd=root / f'chr/{template}.chrbnd.dcx', texbnd=root / f'chr/{template}.texbnd.dcx',
                 anibnd=root / f'chr/{template}.anibnd.dcx', behbnd=root / f'chr/{template}.behbnd.dcx',
                 hks=root / f'action/script/{template}.hks')
    if map_name:
        files['map'] = root / f'map/mapstudio/{map_name}.msb.dcx'
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise ValueError('The game folder lacks ' + ', '.join(missing) + '. Choose an unpacked Sekiro folder (UXM).')
    return files


def read_binder(path):
    from binder_members import Binder
    from dcx_codec import unwrap
    raw, kind = unwrap(Path(path).read_bytes())
    return Binder(raw), kind


def pack(data, kind):
    from soulstruct.dcx import DCXType, compress
    from dcx_codec import unwrap
    if kind == DCXType.Null:
        return data
    packed = compress(data, kind)
    if unwrap(packed)[0] != data:
        raise RuntimeError('A DCX readback differs from the data written.')
    return packed


def member(binder, test):
    found = [m for m in binder.members if test(PureWindowsPath(m[1]).name)]
    if not found:
        raise ValueError('The binder lacks a member the export needs.')
    return found[0]


def rename(text, old, new):
    return re.sub(re.escape(old), new, text, flags=re.I)


def write_binder(binder, kind, path, old, new):
    """Rename the template ID in every member path and write the binder with the template's DCX type."""
    from binder_members import Binder
    from dcx_codec import protect_output
    for entry in binder.members:
        entry[1] = rename(entry[1], old, new)
    data = binder.to_bytes()
    check = Binder(data)
    if [m[1] for m in check.members] != [m[1] for m in binder.members]:
        raise RuntimeError(f'{path.name} did not read back with its members.')
    protect_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack(data, kind))
    return dict(file=str(path), members=len(binder.members))


def write_file(path, data):
    from dcx_codec import protect_output
    protect_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def extract(binder, test, path):
    entry = member(binder, test)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(entry[2])
    return entry


def havok_report(skeleton_path, compendium_path, behaviors, template=''):
    """The skeleton and, per behavior member, its bone references and the strings that name the template."""
    compendium = Path(compendium_path).read_bytes() if compendium_path else None
    skeleton = havok_tagfile.skeleton(Path(skeleton_path).read_bytes(), compendium)
    found = []
    for behavior in behaviors:
        data = Path(behavior['path']).read_bytes()
        entry = dict(name=behavior['name'], boneFields=[], strings=[])
        if data[4:8] == b'TAG0':
            tag = havok_tagfile.Tagfile(data, compendium)
            entry['boneFields'] = [{k: v for k, v in f.items() if k in ('kind', 'path', 'field', 'value', 'values')}
                                   for f in havok_tagfile.bone_fields(tag, len(skeleton['bones']))]
            if template:
                entry['strings'] = [dict(path=v.path, field=v.field, value=text) for v, text in havok_tagfile.strings(tag, template)]
        found.append(entry)
    return skeleton, found


def inspect_template(files, template, work):
    """The template's skeleton, behavior bone references, model, textures and map parts."""
    from dcx_codec import unwrap
    anibnd, _ = read_binder(files['anibnd'])
    chrbnd, _ = read_binder(files['chrbnd'])
    texbnd, _ = read_binder(files['texbnd'])
    behbnd, _ = read_binder(files['behbnd'])
    folder = work / 'template'
    skeleton = extract(anibnd, lambda n: n.lower() == 'skeleton.hkx', folder / 'skeleton.hkx')
    compendium = extract(anibnd, lambda n: n.lower().endswith('.compendium'), folder / 'types.compendium')
    extract(chrbnd, lambda n: n.lower().endswith('.flver'), folder / 'model.flver')
    extract(texbnd, lambda n: n.lower().endswith('.tpf'), folder / 'textures.tpf')
    behaviors = []
    for index, entry in enumerate(behbnd.members):
        path = folder / f'behavior_{index}.hkx'
        path.write_bytes(entry[2])
        behaviors.append(dict(name=entry[1], path=str(path)))
    job = dict(templateId=template, flver=str(folder / 'model.flver'), tpf=str(folder / 'textures.tpf'), model=template)
    if 'map' in files:
        (folder / 'map.msb').write_bytes(unwrap(files['map'].read_bytes())[0])
        job['maps'] = [dict(name=files['map'].name.split('.')[0], path=str(folder / 'map.msb'))]
    report = run_writer('inspect', job, folder)
    report['skeleton'], report['behaviors'] = havok_report(folder / 'skeleton.hkx', folder / 'types.compendium', behaviors, template)
    report['paths'] = dict(job, skeleton=str(folder / 'skeleton.hkx'), compendium=str(folder / 'types.compendium'),
                           behaviors=behaviors, skeletonMember=skeleton[1], compendiumMember=compendium[1])
    return report


# Space ---------------------------------------------------------------------------------------------------------------

def basis_matrix(space=FROMSOFT):
    """P with v_blender = P @ v_game, as a 4x4 for points (unit included) and directions."""
    matrix = np.zeros((4, 4))
    for row, (index, sign) in enumerate(zip(space.indices, space.signs)):
        matrix[row, index] = sign * space.unit
    matrix[3, 3] = 1
    return matrix


def to_game(matrices, space=FROMSOFT):
    """Blender world matrices (..., 4, 4) as the game's: the same transforms in the game's axes."""
    p = basis_matrix(space)
    # The unit cancels in the rotation part and divides the translation.
    return np.linalg.inv(p) @ np.asarray(matrices, np.float64) @ p


def quaternion(rotation):
    """[x, y, z, w] of a 3x3 rotation matrix (column vectors)."""
    m = np.asarray(rotation, np.float64)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = np.sqrt(trace + 1) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, s / 4]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [s / 4, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, s / 4, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, s / 4, (m[1, 0] - m[0, 1]) / s]
    q = np.asarray(q)
    return q / np.linalg.norm(q)


def matrix(translation, rotation, scale=(1, 1, 1)):
    x, y, z, w = (float(v) for v in rotation)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    result = np.eye(4)
    result[:3, :3] = r * np.asarray(scale, np.float64)
    result[:3, 3] = translation
    return result


def trs(m):
    """(translation, [x, y, z, w], scale) of a 4x4 without shear."""
    scale = np.linalg.norm(m[:3, :3], axis=0)
    return m[:3, 3].copy(), quaternion(m[:3, :3] / np.where(scale > 1e-9, scale, 1)), scale


def worlds_of(locals_, parents):
    result = []
    for index, parent in enumerate(parents):
        result.append(result[parent] @ locals_[index] if parent >= 0 else locals_[index])
    return result


# Skeleton ------------------------------------------------------------------------------------------------------------

def mirror_name(name):
    for a, b in (('L_', 'R_'), ('_L_', '_R_'), ('Left', 'Right'), ('_L', '_R')):
        for x, y in ((a, b), (b, a)):
            if x in name:
                return name.replace(x, y, 1)
    return name


def pair_bones(source, template_bones, template_worlds, mapping, overrides=None, game=''):
    """{template name: source name} for the template's body bones, from the Retarget Assistant's matcher.

    source is [(name, parent, world 4x4 in game space)]. Positions go to the matcher in Blender's space, where its
    side and height rules hold. game is the source rig's game: the matcher reads the bone names of its package
    (games.json) in place of the rig's own names, as the add-on does.
    """
    p = basis_matrix()
    head = lambda world: tuple(float(v) for v in (p @ world[:, 3])[:3])
    names = [b['name'] for b in template_bones]
    target = [mapping.Bone(b['name'], names[b['parent']] if b['parent'] >= 0 else '', head(template_worlds[i]))
              for i, b in enumerate(template_bones) if i >= FRAME_BONES]
    alias = mapping.game_aliases(APP / 'games.json', game)
    bones = [mapping.Bone(name, source[parent][0] if parent >= 0 else '', head(world), alias(name))
             for name, parent, world in source]
    rows = mapping.match_bones(bones, target)
    pairs = {row['target']: row['source'] for row in rows if row['source']}
    for target_name, source_name in (overrides or {}).items():
        pairs = {t: s for t, s in pairs.items() if s != source_name and t != target_name}
        if source_name:
            pairs[target_name] = source_name
    missing = [name for name in REQUIRED if name in names and name not in pairs]
    if missing:
        raise ValueError('These template bones have no partner in the scene: ' + ', '.join(missing) +
                         '. Name the partners with --pair TEMPLATE=SOURCE, or check the bone list in the Retarget Assistant.')
    return pairs, rows


def build_skeleton(manifest, template_report, pairs):
    """The new skeleton: the template's frame bones, then every source bone, top bones under Root.

    Returns a dict with names, parents, local and world rest matrices (game space) and the index maps.
    """
    template_bones = template_report['skeleton']['bones']
    t_locals = [matrix(b['translation'], b['rotation'], b['scale']) for b in template_bones]
    t_parents = [b['parent'] for b in template_bones]
    t_worlds = worlds_of(t_locals, t_parents)
    t_names = [b['name'] for b in template_bones]
    frame = t_names[:FRAME_BONES]
    if frame[0] != 'Master' or frame[-1] != 'Root' or set(frame[1:-1]) != set(LEGS):
        raise ValueError('The template skeleton does not start with Master, the foot target chains and Root.')

    source = manifest['bones']
    src_worlds = to_game(np.array([np.reshape(b['rest'], (4, 4)) for b in source]))
    # Partnered bones take the template's names; another bone of the same name, or a frame bone's, gets a suffix.
    renamed = {s: t for t, s in pairs.items()}
    taken = {name.lower() for name in frame} | {name.lower() for name in pairs}
    names = list(frame)
    for bone in source:
        name = renamed.get(bone['name'])
        if name is None:
            name = bone['name']
            while name.lower() in taken:
                name += '_'
            taken.add(name.lower())
        names.append(name)
    parents = t_parents[:FRAME_BONES] + [b['parent'] + FRAME_BONES if b['parent'] >= 0 else FRAME_BONES - 1 for b in source]
    index = {name: i for i, name in enumerate(names)}

    worlds = list(t_worlds[:FRAME_BONES]) + list(src_worlds)
    # Root rests at the hips, turned as the template's; each foot target chain rests on its leg, as c1010's does.
    root = worlds[FRAME_BONES - 1].copy()
    root[:3, 3] = worlds[index['Pelvis']][:3, 3]
    worlds[FRAME_BONES - 1] = root
    for target, leg in LEGS.items():
        worlds[index[target]] = worlds[index[leg]].copy()
    locals_ = [np.linalg.inv(worlds[parent]) @ world if parent >= 0 else world for world, parent in zip(worlds, parents)]

    # Template bone number -> new number; a template bone without a partner takes its nearest partnered ancestor.
    bone_map = []
    for i, name in enumerate(t_names):
        j = i
        while j >= FRAME_BONES and t_names[j] not in pairs:
            j = t_parents[j]
        bone_map.append(j if j < FRAME_BONES else index[t_names[j]])
    weight_source = []
    for i, name in enumerate(names):
        if i < FRAME_BONES:
            weight_source.append(i)
        elif name in t_names and name in pairs:
            weight_source.append(t_names.index(name))
        else:
            weight_source.append(weight_source[parents[i]])
    mirror = [index.get(mirror_name(name), i) for i, name in enumerate(names)]
    return dict(names=names, parents=parents, locals=locals_, worlds=worlds, index=index, sourceOffset=FRAME_BONES,
                boneMap=bone_map, weightSource=weight_source, mirror=mirror, templateNames=t_names,
                templateWorlds=t_worlds, templateParents=t_parents)


def skeleton_bones(skeleton):
    bones = []
    for name, parent, local in zip(skeleton['names'], skeleton['parents'], skeleton['locals']):
        t, r, s = trs(local)
        bones.append(dict(name=name, parent=parent, translation=t.tolist(), rotation=r.tolist(), scale=s.tolist()))
    return bones


# Clips ---------------------------------------------------------------------------------------------------------------

def sample_motion(manifest, skeleton, rate=30.0):
    """Local transforms of the new skeleton per frame, from the scene's sampled world matrices.

    The frame bones keep their rest pose; each foot target chain stands on its foot as export_motion places it.
    """
    data = np.load(manifest['motion']['data'])['matrices']
    source_rate = float(manifest['motion']['frameRate'])
    step = source_rate / rate if source_rate > rate and abs(source_rate / rate - round(source_rate / rate)) < 1e-6 else 1
    if step == 1:
        rate = source_rate
    data = data[::int(round(step))]
    if len(data) < 2:
        raise ValueError('The action has fewer than two frames. Widen its frame range.')
    worlds = to_game(data)
    names, parents, rest_locals = skeleton['names'], skeleton['parents'], skeleton['locals']
    rest_worlds = skeleton['worlds']
    offset = skeleton['sourceOffset']
    index = skeleton['index']
    frames = []
    for frame in worlds:
        world = list(rest_worlds[:offset]) + list(frame)
        world[offset - 1] = rest_worlds[offset - 1]
        for target, leg in LEGS.items():
            chain = []
            parent = parents[index[target]]
            while parent >= 0 and names[parent] in LEGS:
                chain.insert(0, parent)
                parent = parents[parent]
            hanging, current = {}, world[parent] if parent >= 0 else np.eye(4)
            for i in (*chain, index[target]):
                current = hanging[i] = current @ rest_locals[i]
            foot = index[leg]
            wanted = world[foot] @ np.linalg.inv(rest_worlds[foot]) @ rest_worlds[index[target]]
            shift = wanted[:3, 3] - hanging[index[target]][:3, 3]
            for i in chain:
                moved = hanging[i].copy()
                moved[:3, 3] += shift
                world[i] = moved
            world[index[target]] = wanted
        frames.append([np.linalg.inv(world[p]) @ world[i] if p >= 0 else world[i] for i, p in enumerate(parents)])
    return frames, rate


def motion_document(skeleton, frames, rate, skeleton_name, clip='a000_000000.hkx'):
    """A FromSoftware motion JSON for build_animation: one track per bone that moves or leaves its rest pose."""
    bones = skeleton_bones(skeleton)
    locals_ = np.asarray(frames)
    rest = np.asarray(skeleton['locals'])
    moving = np.abs(locals_ - rest[None]).max(axis=(0, 2, 3)) > 1e-5
    tracks = [i for i in range(len(bones)) if moving[i] or i < FRAME_BONES]
    samples, previous = [], {}
    for frame in frames:
        row = []
        for i in tracks:
            t, r, s = trs(frame[i])
            if i in previous and float(np.dot(r, previous[i])) < 0:
                r = -r
            previous[i] = r
            row.append(dict(translation=t.tolist(), rotation=r.tolist(), scale=s.tolist()))
        samples.append(row)
    return dict(format='sekiro-animation-bridge', formatVersion=2, game='sekiro', clip=clip, skeletonName=skeleton_name,
                skeleton=dict(name=skeleton_name, boneCount=len(bones),
                              bones=[dict(index=i, **bone) for i, bone in enumerate(bones)]),
                frameCount=len(samples), frameRate=rate, duration=(len(samples) - 1) / rate, trackCount=len(tracks),
                trackBoneIndices=tracks, trackNames=[bones[i]['name'] for i in tracks], frames=samples,
                compression='interleaved', blockCount=0, rootMotion=None, rootUp=None, rootForward=None,
                source=dict(engine='fromsoft', game='sekiro', container='hkx'), **FROMSOFT.to_json())


def build_clip(document, folder, output_format='spline'):
    from build_animation import build
    folder.mkdir(parents=True, exist_ok=True)
    motion, hkx = folder / 'clip.json', folder / 'clip.hkx'
    motion.write_text(json.dumps(document, separators=(',', ':')), encoding='utf-8')
    stats = build(motion, hkx, output_format, game='sekiro', verify=True)
    return hkx.read_bytes(), stats


# Model ---------------------------------------------------------------------------------------------------------------

def mesh_parts(npz, node_of_source, hidden=(), space=FROMSOFT):
    """Per material, FLVER-ready vertex and triangle arrays from one exported mesh, split below 65,536 vertices.
    Materials in hidden are left out."""
    data = np.load(npz)
    p = basis_matrix(space)[:3, :3]
    directions = np.linalg.inv(p / space.unit)
    loop_vertex = data['loop_vertex']
    positions = (data['positions'] @ np.linalg.inv(p).T)[loop_vertex]
    normals = data['normals'] @ directions.T
    tangents = data['tangents'].copy()
    tangents[:, :3] = tangents[:, :3] @ directions.T
    uv0 = data['uv_0'] if 'uv_0' in data.files else np.zeros((len(loop_vertex), 2), np.float32)
    uv1 = data['uv_1'] if 'uv_1' in data.files else uv0
    uv0, uv1 = uv0.copy(), uv1.copy()
    uv0[:, 1], uv1[:, 1] = 1 - uv0[:, 1], 1 - uv1[:, 1]
    bones = node_of_source[data['bone_indices']][loop_vertex]
    weights = data['bone_weights'][loop_vertex]
    empty = weights.sum(axis=1) == 0
    weights[empty, 0] = 1
    floats = np.zeros((len(loop_vertex), 22), np.float32)
    floats[:, 0:3], floats[:, 3:6], floats[:, 6:10] = positions, normals, tangents
    floats[:, 10:12], floats[:, 12:14], floats[:, 14:18] = uv0, uv1, weights
    triangles = data['triangles']
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    along = np.einsum('ij,ij->i', np.cross(b - a, c - a), normals[triangles].sum(axis=1)) > 0
    key =np.column_stack([loop_vertex, np.round(normals * 1e4), np.round(uv0 * 1e5), np.round(uv1 * 1e5),
                           np.sign(tangents[:, 3])]).astype(np.int64)
    parts = []
    for material in np.unique(data['triangle_materials']):
        if int(material) in hidden:
            continue
        chosen = triangles[data['triangle_materials'] == material]
        # Sekiro's triangles wind against their normals (c1010: 99.7% of them). The axis change mirrors, so a mesh
        # wound as Blender winds, with its normals, as the import now winds every game's, arrives here wound against
        # them. A FromSoftware scene imported before that, wound the other way in Blender, arrives wound with them.
        # A material is turned around when most of its triangles wind with their normals; otherwise the game lights
        # it from behind.
        if along[data['triangle_materials'] == material].mean() > 0.5:
            chosen = chosen[:, [0, 2, 1]]
        pending = [chosen]
        while pending:
            tris = pending.pop()
            corners = tris.ravel()
            unique, first, inverse_index = np.unique(key[corners], axis=0, return_index=True, return_inverse=True)
            if len(unique) > MAX_VERTICES - 1 and len(tris) > 1:
                half = len(tris) // 2
                pending += [tris[:half], tris[half:]]
                continue
            rows = corners[first]
            parts.append((int(material), floats[rows], bones[rows].astype(np.int32), inverse_index.reshape(-1, 3).astype(np.int32)))
    return parts


def reduce_weighted_bones(meshes, parents, limit):
    """Which bone each bone's weights go to, so that the weighted bones and their ancestors number at most limit.

    A Sekiro vertex names its bones with one byte. Until the bones fit, the bone with the least weight in total among
    those that hold no other needed bone gives its weights to its parent. Returns (target per bone, merged bones).
    """
    import heapq
    total = np.zeros(len(parents))
    for data in meshes:
        np.add.at(total, data['bone_indices'].ravel(), data['bone_weights'].ravel())
    needed = set()
    for bone in np.nonzero(total > 0)[0].tolist():
        while bone >= 0 and bone not in needed:
            needed.add(bone)
            bone = parents[bone]
    children = {bone: 0 for bone in needed}
    for bone in needed:
        if parents[bone] >= 0:
            children[parents[bone]] += 1
    heap = [(total[bone], bone) for bone in needed if children[bone] == 0]
    heapq.heapify(heap)
    target = list(range(len(parents)))
    merged = []
    while len(needed) > limit and heap:
        weight, bone = heapq.heappop(heap)
        parent = parents[bone]
        if bone not in needed or children[bone] or weight != total[bone] or parent < 0:
            continue
        needed.remove(bone)
        merged.append(bone)
        target[bone] = parent
        total[parent] += total[bone]
        total[bone] = 0
        children[parent] -= 1
        if children[parent] == 0:
            heapq.heappush(heap, (total[parent], parent))
    for bone in merged:
        while target[target[bone]] != target[bone]:
            target[bone] = target[target[bone]]
    return np.array(target, np.int64), sorted(merged)


def write_mesh(folder, name, floats, bones, triangles):
    vertices, indices = folder / f'{name}.vertices', folder / f'{name}.indices'
    record = np.zeros(len(floats), dtype=[('f', '<f4', 22), ('i', '<i4', 4)])
    record['f'], record['i'] = floats, bones
    vertices.write_bytes(record.tobytes())
    indices.write_bytes(triangles.astype('<i4').tobytes())
    return str(vertices), str(indices)


# Textures ------------------------------------------------------------------------------------------------------------

def dds_header(width, height, dxgi):
    """The 148-byte header of an uncompressed DDS with a DX10 extension: magic, DDS_HEADER, DDS_HEADER_DXT10."""
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000  # caps, height, width, pitch, pixel format
    return (struct.pack('<4s7I44s2I4s5I5I', b'DDS ', 124, flags, height, width, width * 4, 0, 1, b'\0' * 44,
                        32, 0x4, b'DX10', 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
            + struct.pack('<5I', dxgi, 3, 0, 1, 0))


def read_rgba(path, folder, size=0):
    """An image as (height, width, 4) uint8 through texconv, reduced so that its longer side is at most size."""
    out = folder / 'raw'
    out.mkdir(parents=True, exist_ok=True)

    def convert(extra=()):
        # -srgb keeps the stored values: texconv would otherwise turn an sRGB-tagged PNG into linear values.
        result = subprocess.run([str(texconv_path()), '-nologo', '-f', 'R8G8B8A8_UNORM', '-m', '1', '-dx10', '-srgb', '-y',
                                 *extra, '-o', str(out), str(path)], capture_output=True, text=True, encoding='utf-8',
                                errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        raw_path = out / (Path(path).stem + '.dds')
        if result.returncode or not raw_path.is_file():
            raise RuntimeError(f'texconv could not read {path}: {result.stdout.strip()[-300:]}')
        raw = raw_path.read_bytes()
        height, width = struct.unpack_from('<II', raw, 12)
        return raw, width, height

    raw, width, height = convert()
    if size and max(width, height) > size:
        factor = size / max(width, height)
        raw, width, height = convert(['-w', str(max(4, round(width * factor))), '-h', str(max(4, round(height * factor)))])
    return np.frombuffer(raw, np.uint8, width * height * 4, 148).reshape(height, width, 4).copy()


def write_texture(pixels, name, kind, folder):
    """Compress RGBA pixels into a DDS of the kind's format. Returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    height, width = pixels.shape[:2]
    # Both sides a multiple of 4 for block compression.
    if width % 4 or height % 4:
        pixels = np.pad(pixels, ((0, -height % 4), (0, -width % 4), (0, 0)), mode='edge')
        height, width = pixels.shape[:2]
    # The source as sRGB data for color, so texconv does not convert its values.
    source = folder / f'{name}.source.dds'
    source.write_bytes(dds_header(width, height, 29 if kind == 'a' else 28) + pixels.astype(np.uint8).tobytes())
    out = folder / 'dds'
    out.mkdir(exist_ok=True)
    result = subprocess.run([str(texconv_path()), '-nologo', '-f', FORMATS[kind][1], '-dx10', '-y', '-o', str(out), str(source)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    made = out / f'{name}.source.dds'
    if result.returncode or not made.is_file():
        raise RuntimeError(f'texconv could not compress {name}: {result.stdout.strip()[-300:]}')
    final = out / f'{name}.dds'
    made.replace(final)
    return final


def channel(pixels, which):
    return pixels[..., 'RGBA'.index(which)] if which in ('R', 'G', 'B', 'A') else pixels[..., 0]


def template_normal_fill(report, folder):
    """The median blue and alpha of the template's _n textures, which hold data other than the normal."""
    from soulstruct.containers.tpf import TPF
    tpf = TPF.from_path(report['paths']['tpf'])
    folder.mkdir(parents=True, exist_ok=True)
    values = []
    for texture in tpf.textures:
        if texture.stem.lower().endswith('_n'):
            path = folder / f'{texture.stem}.dds'
            path.write_bytes(texture.data)
            pixels = read_rgba(path, folder, 64)
            values.append(np.median(pixels[..., 2:4].reshape(-1, 2), axis=0))
    return np.median(values, axis=0).astype(np.uint8) if values else np.array([128, 255], np.uint8)


def material_textures(material, stem, folder, size, normal_fill, cache):
    """Sekiro _a, _n and _m textures for one exported material. Returns {role: (name, dds path, TPF format)}."""
    roles = material.get('roles', {})
    made = {}

    def load(role):
        spec = roles[role]
        key = spec['path']
        if key not in cache:
            cache[key] = read_rgba(spec['path'], folder, size)
        return cache[key]

    if 'albedo' in roles:
        albedo = load('albedo').copy()
        if 'opacity' in roles:
            opacity = load('opacity')
            mask = channel(opacity, roles['opacity'].get('channel', 'A'))
            if mask.shape != albedo.shape[:2]:
                mask = mask[np.linspace(0, mask.shape[0] - 1, albedo.shape[0]).astype(int)][:, np.linspace(0, mask.shape[1] - 1, albedo.shape[1]).astype(int)]
            albedo[..., 3] = mask
        else:
            albedo[..., 3] = 255
        made['albedo'] = (f'{stem}_a', write_texture(albedo, f'{stem}_a', 'a', folder), FORMATS['a'][0])
    elif material.get('color'):
        # No color image: a small one in the material's fixed color, so the game does not show its default texture.
        linear = np.clip(np.asarray(material['color'][:3], np.float64), 0, 1)
        srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
        pixels = np.empty((4, 4, 4), np.uint8)
        pixels[..., :3], pixels[..., 3] = np.round(srgb * 255), 255
        made['albedo'] = (f'{stem}_a', write_texture(pixels, f'{stem}_a', 'a', folder), FORMATS['a'][0])
    if 'normal' in roles:
        normal = load('normal').copy()
        if roles['normal'].get('convention') == 'opengl':
            normal[..., 1] = 255 - normal[..., 1]
        normal[..., 2], normal[..., 3] = normal_fill
        made['normal'] = (f'{stem}_n', write_texture(normal, f'{stem}_n', 'n', folder), FORMATS['n'][0])
    if 'metalness' in roles:
        metal = channel(load('metalness'), roles['metalness'].get('channel', 'R'))
        pixels = np.repeat(metal[..., None], 4, axis=2)
        pixels[..., 3] = 255
        made['metallic'] = (f'{stem}_m', write_texture(pixels, f'{stem}_m', 'm', folder), FORMATS['m'][0])
    return made


# Export --------------------------------------------------------------------------------------------------------------

def check_ids(template, new_id):
    if not ID.fullmatch(template) or not ID.fullmatch(new_id):
        raise ValueError('Character IDs look like c1010: a c and four digits.')
    if template == new_id:
        raise ValueError('Choose a new ID that differs from the template.')


def me3_profile(output, name):
    """A me3 profile beside the mod folder that loads it for Sekiro."""
    profile = output.parent / f'{name}.me3'
    profile.write_text(f'profileVersion = "v1"\n\n[[supports]]\ngame = "sekiro"\n\n[[packages]]\nid = "{name}"\npath = "{output.name}"\n',
                       encoding='utf-8')
    return profile


def write_common(files, template, new_id, output, report, parts, behaviors, skeleton_data, clip_data, work):
    """The binders, script and map shared by clone and export. behaviors maps a behbnd member index to new bytes."""
    written = []
    # Behavior: edited members, the others as they are.
    behbnd, kind = read_binder(files['behbnd'])
    for index, data in behaviors.items():
        behbnd.members[index][2] = data
    written.append(write_binder(behbnd, kind, output / f'chr/{new_id}.behbnd.dcx', template, new_id))
    # Animation: the new skeleton; every clip slot of the template.
    anibnd, kind = read_binder(files['anibnd'])
    clips = 0
    for entry in anibnd.members:
        name = PureWindowsPath(entry[1]).name
        if name.lower() == 'skeleton.hkx' and skeleton_data is not None:
            entry[2] = skeleton_data
        elif CLIP.fullmatch(name) and clip_data is not None:
            entry[2] = clip_data
            clips += 1
    written.append(dict(write_binder(anibnd, kind, output / f'chr/{new_id}.anibnd.dcx', template, new_id), clips=clips))
    script = output / f'action/script/{new_id}.hks'
    write_file(script, files['hks'].read_bytes())
    written.append(dict(file=str(script)))
    if parts:
        from dcx_codec import unwrap
        raw, kind = unwrap(files['map'].read_bytes())
        source = work / 'map.source.msb'
        source.write_bytes(raw)
        result = run_writer('msb', dict(input=str(source), output=str(work / 'map.msb'), templateModel=template,
                                        model=new_id, parts=list(parts)), work)
        target = output / f'map/mapstudio/{files["map"].name}'
        write_file(target, pack((work / 'map.msb').read_bytes(), kind))
        written.append(dict(file=str(target), parts=result['parts'], models=result['models']))
    report['files'] = written
    return written


def clone(game_root, template, new_id, output, map_name='', parts=(), work=None):
    """Write the template as a character of its own under new_id: the M0 test of the writer, the renames and the map."""
    from dcx_codec import configure_oodle
    check_ids(template, new_id)
    configure_oodle()
    output = Path(output)
    work = Path(work) if work else output.with_name(output.name + '.work')
    files = template_files(game_root, template, map_name if parts else '')
    info = inspect_template(files, template, work)
    report = dict(mode='clone', template=template, id=new_id, output=str(output))
    # The skeleton as it is; the behavior with renamed file names and the same bone numbers.
    identity = list(range(len(info['skeleton']['bones'])))
    behaviors = edit_behaviors(info, template, new_id, identity, identity, None, len(identity))
    # Model and textures go through SoulsFormats only in the export; the clone copies them.
    chrbnd, kind = read_binder(files['chrbnd'])
    chrbnd.members = [m for m in chrbnd.members
                      if PureWindowsPath(m[1]).suffix.lower() == '.flver' or ragdoll_member(template, m[1])]
    texbnd, tex_kind = read_binder(files['texbnd'])
    written = [write_binder(chrbnd, kind, output / f'chr/{new_id}.chrbnd.dcx', template, new_id),
               write_binder(texbnd, tex_kind, output / f'chr/{new_id}.texbnd.dcx', template, new_id)]
    write_common(files, template, new_id, output, report, parts, behaviors, None, None, work)
    report['files'] = written + report['files']
    report['profile'] = str(me3_profile(output, output.name))
    report['verify'] = verify(output, new_id, game_root, template, work / 'verify')
    return report


def edit_behaviors(info, template, new_id, bone_map, weight_source, mirror, count):
    """New bytes for each behavior member that names the template or a moved bone; the others stay as they are.

    The members are patched in place (havok_tagfile), so every value the new character does not change keeps the
    template's bytes.
    """
    compendium = Path(info['paths']['compendium']).read_bytes()
    edited = {}
    for index, behavior in enumerate(info['paths']['behaviors']):
        data = Path(behavior['path']).read_bytes()
        if data[4:8] != b'TAG0':
            continue
        new, changes = havok_tagfile.edit_behavior(data, compendium, bone_map, weight_source, mirror, count,
                                                   renames=[(template, new_id)])
        info['behaviors'][index]['changes'] = changes
        if changes:
            edited[index] = new
    return edited


# Ragdoll -------------------------------------------------------------------------------------------------------------

def ragdoll_member(character, path):
    """The chrbnd members that give a character its hit capsules: the ragdoll <id>.hkx and its <id>.hkxpwv. The
    cloth (<id>_c.hkx, <id>_c.clm2) is left out, as it moves the template's model."""
    return PureWindowsPath(path).name.lower() in (f'{character}.hkx', f'{character}.hkxpwv')


def turn_between(old, new):
    """The smallest rotation (3x3) that turns direction old into direction new."""
    a, b = np.asarray(old) / np.linalg.norm(old), np.asarray(new) / np.linalg.norm(new)
    axis, cos = np.cross(a, b), float(np.dot(a, b))
    if cos < -1 + 1e-9:
        # Opposite directions: half a turn about an axis across them.
        side = np.cross(a, [1.0, 0, 0] if abs(a[0]) < .9 else [0, 1.0, 0])
        side /= np.linalg.norm(side)
        return 2 * np.outer(side, side) - np.eye(3)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + k + k @ k / (1 + cos)


def ragdoll_rest(parents, rest, drivers, template_worlds, new_worlds, bone_map):
    """The rest of each ragdoll bone on the new skeleton (4x4, game space).

    A ragdoll bone rests on the template bone that drives it, and its body's capsule lies along that bone. It moves to
    the driver's partner and turns as the limb does from the template's rest to the new one: the limb is the direction
    to the ragdoll child nearest the middle (Spine for Pelvis, Head for Spine2). A bone without such a child turns
    as its parent; one without a driver keeps its place on its parent.
    """
    turns, rests = [], []
    for r, parent in enumerate(parents):
        turn = turns[parent] if parent >= 0 else np.eye(3)
        children = [c for c, p in enumerate(parents) if p == r and c in drivers]
        if r in drivers and children:
            c = min(children, key=lambda c: abs(template_worlds[drivers[c]][0, 3]))
            old = template_worlds[drivers[c]][:3, 3] - template_worlds[drivers[r]][:3, 3]
            new = new_worlds[bone_map[drivers[c]]][:3, 3] - new_worlds[bone_map[drivers[r]]][:3, 3]
            if np.linalg.norm(old) > 1e-6 and np.linalg.norm(new) > 1e-6:
                turn = turn_between(old, new)
        turns.append(turn)
        if r in drivers:
            t = drivers[r]
            world = np.eye(4)
            world[:3, :3] = turn @ rest[r][:3, :3]
            world[:3, 3] = new_worlds[bone_map[t]][:3, 3] + turn @ (rest[r][:3, 3] - template_worlds[t][:3, 3])
        elif parent >= 0:
            world = rests[parent] @ np.linalg.inv(rest[parent]) @ rest[r]
        else:
            world = rest[r].copy()
        rests.append(world)
    return rests


def edit_ragdoll(data, skeleton):
    """The template's ragdoll file on the new skeleton. Its bodies' capsules are what attacks hit.

    The file's copy of the animation skeleton becomes the new skeleton, its mappers name the partnered bones, and each
    ragdoll bone and body rests on its partner (ragdoll_rest). The capsules keep the template's sizes. The mappers'
    transforms follow from the two rests, as the template's do. Returns (bytes, report).
    """
    found = havok_tagfile.ragdoll(data)
    t_names = skeleton['templateNames']
    animation = next((k for k, s in found['skeletons'].items() if [b['name'] for b in s['bones']] == t_names), None)
    if animation is None:
        raise ValueError("The template's ragdoll holds no copy of its skeleton.")
    rag = found['ragdollSkeleton']
    rag_bones = found['skeletons'][rag]['bones']
    rag_parents = [b['parent'] for b in rag_bones]
    rag_rest = worlds_of([matrix(*pose) for pose in found['skeletons'][rag]['pose']], rag_parents)
    t_worlds = worlds_of([matrix(*pose) for pose in found['skeletons'][animation]['pose']],
                         [b['parent'] for b in found['skeletons'][animation]['bones']])
    n_worlds, n_parents, bone_map = skeleton['worlds'], skeleton['parents'], skeleton['boneMap']
    drivers = {}
    for mapper in found['mappers']:
        if (mapper['a'], mapper['b']) == (animation, rag):
            for a, b in mapper['simple']:
                drivers.setdefault(b, a)
    rests = ragdoll_rest(rag_parents, rag_rest, drivers, t_worlds, n_worlds, bone_map)
    worlds = {animation: n_worlds, rag: rests}
    parents = {animation: n_parents, rag: rag_parents}

    def number(item, bone):
        return bone_map[bone] if item == animation else bone

    def chain(item, start, end):
        bones, bone = [], end
        while bone != start:
            if bone < 0:
                raise ValueError(f"A chain of the template's ragdoll, {t_names[start]} to {t_names[end]}, is no chain "
                                 'of the new skeleton. Pair those bones with --pair.')
            bones.append(bone)
            bone = parents[item][bone]
        return bones + [start]

    mappers = []
    for m in found['mappers']:
        a, b = worlds[m['a']], worlds[m['b']]
        simple = [(number(m['a'], i), number(m['b'], j)) for i, j in m['simple']]
        simple = [(i, j, trs(np.linalg.inv(a[i]) @ b[j])) for i, j in simple]
        chains, chained = [], set()
        for sa, ea, sb, eb in m['chains']:
            sa, ea, sb, eb = number(m['a'], sa), number(m['a'], ea), number(m['b'], sb), number(m['b'], eb)
            chain(m['a'], sa, ea)
            chained.update(chain(m['b'], sb, eb))
            chains.append((sa, ea, sb, eb, trs(np.linalg.inv(a[sa]) @ b[sb]), trs(np.linalg.inv(a[ea]) @ b[eb])))
        unmapped = m['unmapped']
        if m['b'] == animation:
            mapped = {j for _, j, _ in simple} | chained
            unmapped = [i for i in range(len(n_worlds)) if i not in mapped]
        mappers.append(dict(simple=simple, chains=chains, unmapped=unmapped))
    bodies = [None] * found['bodies']
    for r, body in enumerate(found['boneToBody']):
        if 0 <= body < len(bodies):
            t, q, _ = trs(rests[r])
            bodies[body] = (t, q)
    if any(body is None for body in bodies):
        raise ValueError("A body of the template's ragdoll has no ragdoll bone.")
    pose = [trs(np.linalg.inv(rests[p]) @ rests[r] if p >= 0 else rests[r]) for r, p in enumerate(rag_parents)]
    new = havok_tagfile.write_ragdoll(data, animation, skeleton_bones(skeleton), pose, mappers, bodies)
    # A driver without a partner of its own follows its nearest partnered ancestor.
    names = skeleton['names']
    borrowed = [f"{rag_bones[r]['name']} on {names[bone_map[t]]}" for r, t in sorted(drivers.items())
                if names[bone_map[t]] != t_names[t]]
    return new, dict(bodies=len(bodies), bones=len(rag_bones), onAncestor=borrowed)


def edit_pwv(data, weight_source):
    """The ragdoll's .hkxpwv for a new skeleton.

    After a 32-byte header (version 1, a zero, ragdoll bones, animation bones, ragdoll bones again) come 4 bytes per
    ragdoll bone, 8 per animation bone and 16 per ragdoll bone; that layout holds for all 33 Sekiro characters that
    have the file. Each new bone takes the row of the template bone its weights come from. In every one of those files
    the animation bones' rows are empty.
    """
    version, _, ragdoll, bones, again = struct.unpack_from('<I4h', data, 0)
    start = 32 + 4 * ragdoll
    if version != 1 or ragdoll != again or start + 8 * bones + 16 * again != len(data):
        raise ValueError("The template's .hkxpwv has a layout the export does not know.")
    rows = [data[start + 8 * i:start + 8 * i + 8] for i in range(bones)]
    header = bytearray(data[:32])
    struct.pack_into('<h', header, 8, len(weight_source))
    return bytes(header) + data[32:start] + b''.join(rows[i] for i in weight_source) + data[start + 8 * bones:]


def export(manifest_path, game_root, template, new_id, output, map_name='', parts=(), work=None, pairs=None,
           texture_size=2048, clip_format='spline'):
    """Write the scene of an export manifest as a new character. Returns a report of what was written and checked."""
    from dcx_codec import configure_oodle
    check_ids(template, new_id)
    configure_oodle()
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('format') != 'sekiro-animation-bridge-character-export':
        raise ValueError('This file is not a character export manifest. Write one with blender_bridge.py export-character.')
    check_character_export(manifest)
    output = Path(output)
    work = Path(work) if work else output.with_name(output.name + '.work')
    files = template_files(game_root, template, map_name if parts else '')
    info = inspect_template(files, template, work)
    report = dict(mode='export', template=template, id=new_id, output=str(output), warnings=list(manifest.get('warnings', [])))

    # Bones: pairs, skeleton, maps.
    template_bones = info['skeleton']['bones']
    t_worlds = worlds_of([matrix(b['translation'], b['rotation'], b['scale']) for b in template_bones],
                         [b['parent'] for b in template_bones])
    src_worlds = to_game(np.array([np.reshape(b['rest'], (4, 4)) for b in manifest['bones']]))
    source = [(b['name'], b['parent'], w) for b, w in zip(manifest['bones'], src_worlds)]
    paired, rows = pair_bones(source, template_bones, t_worlds, load_mapping(), pairs, manifest.get('game', ''))
    skeleton = build_skeleton(manifest, info, paired)
    report['bones'] = dict(skeleton=len(skeleton['names']), paired=len(paired),
                           pairs={t: s for t, s in paired.items()}, unpaired=[r['target'] for r in rows if not r['source']])
    skeleton_data = havok_tagfile.write_skeleton(Path(info['paths']['skeleton']).read_bytes(), skeleton_bones(skeleton),
                                                 Path(info['paths']['compendium']).read_bytes(), renames=[(template, new_id)])
    behaviors = edit_behaviors(info, template, new_id, skeleton['boneMap'], skeleton['weightSource'], skeleton['mirror'],
                               len(skeleton['names']))
    report['behaviors'] = [dict(name=b['name'], edited=i in behaviors, changes=len(b.get('changes', [])))
                           for i, b in enumerate(info['behaviors'])]

    # Model nodes: Master, Root, the source bones (weighted ones and their ancestors first, for byte bone indices),
    # the template's dummy poly holders, one node per mesh.
    meshes = [np.load(m['data']) for m in manifest['meshes']]
    source_parents = [b['parent'] for b in manifest['bones']]
    weight_target, merged = reduce_weighted_bones(meshes, source_parents, 256 - 2)
    if merged:
        report['warnings'].append(f'{len(merged)} bones gave their weights to a parent, because a Sekiro model skins '
                                  f'with 256 bones at most: ' + ', '.join(manifest['bones'][b]['name'] for b in merged[:12]) +
                                  (' ...' if len(merged) > 12 else ''))
    report['bones']['mergedWeights'] = [manifest['bones'][b]['name'] for b in merged]
    weighted = set()
    for data in meshes:
        weighted.update(np.unique(weight_target[data['bone_indices'][data['bone_weights'] > 0]]).tolist())
    offset = skeleton['sourceOffset']
    needed = set()
    for b in weighted:
        while b >= 0 and b not in needed:
            needed.add(b)
            b = manifest['bones'][b]['parent']
    order = [i for i in range(len(manifest['bones'])) if i in needed] + [i for i in range(len(manifest['bones'])) if i not in needed]
    node_names, node_specs = [], []

    def add_node(spec):
        node_specs.append(spec)
        node_names.append(spec['name'])
        return len(node_specs) - 1

    def world_rows(world):
        return [float(v) for v in np.asarray(world).T.ravel()]

    flver_index = {}
    for i in (0, offset - 1):
        flver_index[i] = add_node(dict(name=skeleton['names'][i], parent=flver_index.get(skeleton['parents'][i], -1),
                                       world=world_rows(skeleton['worlds'][i])))
    for s in order:
        i = s + offset
        flver_index[i] = add_node(dict(name=skeleton['names'][i], parent=flver_index[skeleton['parents'][i]],
                                       world=world_rows(skeleton['worlds'][i])))
    node_of_source = np.array([flver_index[s + offset] for s in range(len(manifest['bones']))], np.int32)[weight_target]
    if any(node_of_source[b] > 255 for b in weighted):
        raise ValueError(f'{len(needed)} bones carry weights or hold weighted bones; a Sekiro model holds 256. '
                         'Remove weights from helper bones or join small meshes onto fewer bones.')
    flver_bones = info['flver']['bones']
    holders = [b for b in flver_bones if b['flags'] == 2]
    for b in holders:
        add_node(dict(name=b['name'], parent=-1, kind='dummy', copy=b['name']))
    # Template bones that a dummy poly hangs on and the new model lacks follow their nearest present ancestor.
    present = set(node_names)
    dummy_bones = {}
    for b in flver_bones:
        if b['flags'] & 8 and b['name'] not in present:
            j = b['parent']
            while j >= 0 and flver_bones[j]['name'] not in present:
                j = flver_bones[j]['parent']
            if j >= 0:
                dummy_bones[b['name']] = flver_bones[j]['name']

    # Materials and textures. A material whose fixed alpha is 0 is invisible in the scene, such as an eye's wetness
    # overlay; its triangles are left out, since the game would draw them opaque.
    hidden = {i for i, m in enumerate(manifest['materials']) if m.get('alpha') == 0}
    report['hiddenMaterials'] = [manifest['materials'][i]['name'] for i in sorted(hidden)]
    template_materials = info['flver']['materials']
    plain = next((i for i, m in enumerate(template_materials) if '_e_' not in m['mtd'].lower()), 0)
    cutout = next((i for i, m in enumerate(template_materials) if '_e_' in m['mtd'].lower()), plain)
    folder = work / 'textures'
    normal_fill = template_normal_fill(info, folder / 'template')
    textures, flver_materials, cache, by_roles = [], [], {}, {}
    for index, material in enumerate(manifest['materials']):
        short = re.sub(r'[^A-Za-z0-9]+', '_', material['name'].split(' / ')[-1]).strip('_')[:24] or f'm{index}'
        key = json.dumps([material.get('roles', {}), material.get('color') if 'albedo' not in material.get('roles', {}) else None],
                         sort_keys=True)
        if key not in by_roles:
            by_roles[key] = material_textures(material, f'{new_id}_{short}', folder, texture_size, normal_fill, cache)
            textures += [dict(name=name, dds=str(path), format=fmt) for name, path, fmt in by_roles[key].values()]
        made = by_roles[key]
        cut = 'opacity' in material.get('roles', {})
        flver_materials.append(dict(name=short, mtd=MTD_CUTOUT if cut else MTD, template=cutout if cut else plain,
                                    textures={role: f'N:\\NTC\\data\\Model\\chr\\{new_id}\\tex\\{name}.tif'
                                              for role, (name, _, _) in made.items()}))
    report['textures'] = run_writer('tpf', dict(template=info['paths']['tpf'], textures=textures,
                                                output=str(work / f'{new_id}.tpf')), work)

    # Meshes.
    mesh_folder = work / 'meshes'
    mesh_folder.mkdir(parents=True, exist_ok=True)
    flver_meshes = []
    for m, data in zip(manifest['meshes'], meshes):
        for k, (material, floats, bones, triangles) in enumerate(mesh_parts(m['data'], node_of_source, hidden)):
            name = re.sub(r'[^A-Za-z0-9_]+', '_', m['name'])[:40] + f'_{k}'
            node = add_node(dict(name=name, parent=-1, kind='mesh'))
            vertices, indices = write_mesh(mesh_folder, name, floats, bones, triangles)
            flver_meshes.append(dict(material=material, node=node, vertices=vertices, indices=indices,
                                     cullBackfaces=not manifest['materials'][material].get('doubleSided', False)))
    report['model'] = run_writer('flver', dict(template=info['paths']['flver'], nodes=node_specs, materials=flver_materials,
                                               meshes=flver_meshes, dummyBones=dummy_bones,
                                               output=str(work / f'{new_id}.flver')), work)

    # The clip, into every slot of the template's animation binder.
    frames, rate = sample_motion(manifest, skeleton)
    document = motion_document(skeleton, frames, rate, rename(info['skeleton']['name'], template, new_id))
    clip_data, stats = build_clip(document, work / 'clip', clip_format)
    report['clip'] = dict(action=manifest['motion']['action'], frames=len(frames), frameRate=rate,
                          tracks=document['trackCount'], bytes=len(clip_data), readback=stats.get('readback'))

    chrbnd, kind = read_binder(files['chrbnd'])
    flver_entry = member(chrbnd, lambda n: n.lower().endswith('.flver'))
    flver_entry[2] = (work / f'{new_id}.flver').read_bytes()
    chrbnd.members = [m for m in chrbnd.members if m is flver_entry or ragdoll_member(template, m[1])]
    # The ragdoll's bodies are what attacks hit; they move onto the new skeleton.
    for entry in chrbnd.members:
        if PureWindowsPath(entry[1]).suffix.lower() == '.hkx':
            entry[2], report['ragdoll'] = edit_ragdoll(entry[2], skeleton)
        elif PureWindowsPath(entry[1]).suffix.lower() == '.hkxpwv':
            entry[2] = edit_pwv(entry[2], skeleton['weightSource'])
    if 'ragdoll' not in report:
        report['warnings'].append(f'{template} has no ragdoll ({template}.hkx in its chrbnd), so attacks cannot hit '
                                  'the new character.')
    elif report['ragdoll']['onAncestor']:
        report['warnings'].append(f"{len(report['ragdoll']['onAncestor'])} hit bodies rest on a parent bone, because "
                                  'their own bone has no partner: ' + ', '.join(report['ragdoll']['onAncestor']))
    texbnd, tex_kind = read_binder(files['texbnd'])
    member(texbnd, lambda n: n.lower().endswith('.tpf'))[2] = (work / f'{new_id}.tpf').read_bytes()
    written = [write_binder(chrbnd, kind, output / f'chr/{new_id}.chrbnd.dcx', template, new_id),
               write_binder(texbnd, tex_kind, output / f'chr/{new_id}.texbnd.dcx', template, new_id)]
    write_common(files, template, new_id, output, report, parts, behaviors, skeleton_data, clip_data, work)
    report['files'] = written + report['files']
    report['profile'] = str(me3_profile(output, output.name))
    report['verify'] = verify(output, new_id, game_root, template, work / 'verify')
    return report


# Verify --------------------------------------------------------------------------------------------------------------

def verify(output, new_id, game_root='', template='', work=None):
    """Read every written file back with the writer and check that its parts fit together."""
    from dcx_codec import configure_oodle, unwrap
    configure_oodle()
    output = Path(output)
    work = Path(work) if work else output.with_name(output.name + '.work') / 'verify'
    checks = []

    def check(name, passed, detail):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    paths = {kind: output / f'chr/{new_id}.{kind}.dcx' for kind in ('chrbnd', 'texbnd', 'anibnd', 'behbnd')}
    missing = [str(p) for p in paths.values() if not p.is_file()]
    check('files', not missing, 'all four binders are present' if not missing else 'missing: ' + ', '.join(missing))
    if missing:
        return dict(passed=False, checks=checks)
    binders = {kind: read_binder(path)[0] for kind, path in paths.items()}
    stale = [m[1] for b in binders.values() for m in b.members if template and template.lower() in m[1].lower()]
    unnamed = [kind for kind, b in binders.items() if not any(new_id.lower() in m[1].lower() for m in b.members)]
    check('member paths', not stale and not unnamed, f'member paths name {new_id}' + (f', none {template}' if template else '')
          if not stale and not unnamed else 'still named: ' + ', '.join(stale[:3] + unnamed))
    work.mkdir(parents=True, exist_ok=True)
    skeleton = extract(binders['anibnd'], lambda n: n.lower() == 'skeleton.hkx', work / 'skeleton.hkx')
    extract(binders['anibnd'], lambda n: n.lower().endswith('.compendium'), work / 'types.compendium')
    extract(binders['chrbnd'], lambda n: n.lower().endswith('.flver'), work / 'model.flver')
    extract(binders['texbnd'], lambda n: n.lower().endswith('.tpf'), work / 'textures.tpf')
    behaviors = []
    for index, entry in enumerate(binders['behbnd'].members):
        (work / f'behavior_{index}.hkx').write_bytes(entry[2])
        behaviors.append(dict(name=entry[1], path=str(work / f'behavior_{index}.hkx')))
    job = dict(templateId=template or new_id, flver=str(work / 'model.flver'), tpf=str(work / 'textures.tpf'), model=new_id)
    maps = sorted((output / 'map/mapstudio').glob('*.msb.dcx')) if (output / 'map/mapstudio').is_dir() else []
    if maps:
        (work / 'map.msb').write_bytes(unwrap(maps[0].read_bytes())[0])
        job['maps'] = [dict(name=maps[0].name.split('.')[0], path=str(work / 'map.msb'))]
    info = run_writer('inspect', job, work)
    info['skeleton'], info['behaviors'] = havok_report(work / 'skeleton.hkx', work / 'types.compendium', behaviors, template)
    bones = info['skeleton']['bones']
    names = {b['name'] for b in bones}
    check('skeleton', len(bones) > FRAME_BONES and [b['name'] for b in bones[:1]] == ['Master'],
          f'{len(bones)} bones, starting with {bones[0]["name"]}')
    numbers = [(b['name'], f['field'], v) for b in info['behaviors'] for f in b['boneFields']
               for v in ([f['value']] if f['kind'] in ('index', 'property') else f['values'] if f['kind'] == 'indices' else [])]
    out_of_range = [f'{name}: {field} {value}' for name, field, value in numbers if not -1 <= value < len(bones)]
    sized = [f"{b['name']}: {f['field']} {len(f['values'])}" for b in info['behaviors'] for f in b['boneFields']
             if f['kind'] in ('weights', 'mirror') and len(f['values']) != len(bones)]
    check('behavior lists', not sized, 'every per-bone list has one entry per bone' if not sized
          else 'wrong length: ' + '; '.join(sized[:4]))
    # The game's loader turns only the slots that the PTCH table lists into addresses.
    compendium = (work / 'types.compendium').read_bytes()
    unlisted = []
    for name, path in [('skeleton.hkx', work / 'skeleton.hkx')] + [(b['name'], Path(b['path'])) for b in behaviors]:
        data = path.read_bytes()
        if data[4:8] == b'TAG0':
            missing, extra = havok_tagfile.Tagfile(data, compendium).unpatched()
            if missing or extra:
                unlisted.append(f'{PureWindowsPath(name).name}: {len(missing)} unlisted, {len(extra)} stale')
    check('havok tables', not unlisted, 'every pointer, string and list slot is in its PTCH table' if not unlisted
          else '; '.join(unlisted))
    check('behavior bones', not out_of_range, 'every bone number names a bone of the skeleton' if not out_of_range
          else 'out of range: ' + '; '.join(out_of_range[:4]))
    old_names = [s['value'] for b in info['behaviors'] for s in b['strings']] if template else []
    check('behavior names', not old_names, f'no file name names {template}' if not old_names else 'still named: ' + ', '.join(old_names[:4]))
    check('ragdoll', *ragdoll_check(binders['chrbnd'], new_id, [b['name'] for b in bones]))
    flver = info['flver']
    model_bones = [b['name'] for b in flver['bones'] if b['flags'] & 8]
    outside = [n for n in model_bones if n not in names]
    check('model bones', not outside, f'{len(model_bones)} model bones, all in the skeleton' if not outside
          else 'not in the skeleton: ' + ', '.join(outside[:6]))
    stems = {t['name'].lower() for t in info['tpf']['textures']}
    unresolved = sorted({PureWindowsPath(t['path']).stem for m in flver['materials'] for t in m['textures']
                         if t['path'] and PureWindowsPath(t['path']).stem.lower() not in stems})
    check('textures', not unresolved, f"{len(stems)} textures; every material path resolves" if not unresolved
          else 'not in the TPF: ' + ', '.join(unresolved[:6]))
    clips = [m for m in binders['anibnd'].members if CLIP.fullmatch(PureWindowsPath(m[1]).name)]
    expected = None
    if game_root and template:
        expected = sum(1 for m in read_binder(Path(game_root) / f'chr/{template}.anibnd.dcx')[0].members
                       if CLIP.fullmatch(PureWindowsPath(m[1]).name))
    check('clips', clips and (expected is None or len(clips) == expected),
          f'{len(clips)} clips' + (f' of the template\'s {expected}' if expected is not None else ''))
    if maps:
        parts = info.get('parts', [])
        check('map', bool(parts), f"{maps[0].name}: {len(parts)} part(s) use {new_id}: " + ', '.join(p['name'] for p in parts[:6]))
    return dict(passed=all(c['passed'] for c in checks), checks=checks)


def ragdoll_check(chrbnd, new_id, names):
    """Whether the chrbnd's ragdoll fits the skeleton: (passed, detail)."""
    entries = {PureWindowsPath(m[1]).name.lower(): m[2] for m in chrbnd.members if ragdoll_member(new_id, m[1])}
    data = entries.get(f'{new_id}.hkx')
    if data is None:
        return False, f'no {new_id}.hkx in the chrbnd, so attacks cannot hit the character'
    found = havok_tagfile.ragdoll(data)
    sizes = {k: len(s['bones']) for k, s in found['skeletons'].items()}
    faults = []

    def inside(bone, item):
        return 0 <= bone < sizes[item]

    if not any([b['name'] for b in s['bones']] == names for s in found['skeletons'].values()):
        faults.append('no copy of the skeleton')
    for m in found['mappers']:
        if not all(inside(a, m['a']) and inside(b, m['b']) for a, b in m['simple']) or not all(
                inside(sa, m['a']) and inside(ea, m['a']) and inside(sb, m['b']) and inside(eb, m['b'])
                for sa, ea, sb, eb in m['chains']) or not all(inside(b, m['b']) for b in m['unmapped']):
            faults.append('a mapper names a bone out of range')
    missing, extra = havok_tagfile.Tagfile(data).unpatched()
    if missing or extra:
        faults.append(f'{len(missing)} unlisted, {len(extra)} stale PTCH slots')
    pwv = entries.get(f'{new_id}.hkxpwv')
    if pwv is not None and struct.unpack_from('<h', pwv, 8)[0] != len(names):
        faults.append(f'the .hkxpwv counts {struct.unpack_from("<h", pwv, 8)[0]} bones')
    return not faults, (f"{found['bodies']} hit bodies on {sizes[found['ragdollSkeleton']]} ragdoll bones fit the skeleton"
                        if not faults else '; '.join(faults))


def list_parts(game_root, template, map_name, work):
    """The template's enemy parts in a map, for choosing which ones become the new character."""
    from dcx_codec import configure_oodle, unwrap
    configure_oodle()
    files = template_files(game_root, template, map_name)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'map.msb').write_bytes(unwrap(files['map'].read_bytes())[0])
    return run_writer('inspect', dict(templateId=template, model=template,
                                      maps=[dict(name=map_name, path=str(work / 'map.msb'))]), work, 'parts')['parts']
