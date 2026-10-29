"""verify on owned synthetic scenes. Run with Blender --background --factory-startup --python this_file.py.

A box character that stands on its thighs, faces Blender's front and follows its pelvis passes every check and is
drawn from the front and the side. A clip that pulls one thigh away stretches the skin, which the advisory check
notes with its frame. The checks fail where they should: a mesh on a model bone outside the animation's skeleton never
moves, and an unpacked image whose file is deleted is missing.
"""
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_bridge import import_motion  # noqa: E402
from blender_character import import_character  # noqa: E402
from blender_verify import bone_side, verify_scene  # noqa: E402

COUNT = 5
# FromSoftware's space: Y is up, and source +X is Blender +X, the character's left.
BONES = [('Master', -1, [0, 0, 0]), ('Pelvis', 0, [0, 1.0, 0]), ('L_Thigh', 1, [.1, -.1, 0]), ('R_Thigh', 1, [-.1, -.1, 0])]

for name, side in (('L_Thigh', 'L'), ('Thigh.R', 'R'), ('mixamorig:LeftArm', 'L'), ('l_arm_upper', 'L'), ('lower_lip_l', 'L'),
                   ('R_Clavicle', 'R'), ('Pelvis', ''), ('Master', ''), ('Lid', ''), ('Spine1', '')):
    assert bone_side(name) == side, (name, bone_side(name), side)


def turn_y(angle):
    return [0, math.sin(angle / 2), 0, math.cos(angle / 2)]


def owned_motion(pull=0.0):
    """The pelvis rises and turns about the vertical; pull moves the left thigh out by that much per frame."""
    bones = [dict(index=i, name=n, parent=p, translation=t, rotation=[0, 0, 0, 1], scale=[1, 1, 1]) for i, (n, p, t) in enumerate(BONES)]

    def frame(i):
        rows = [dict(translation=list(b['translation']), rotation=[0, 0, 0, 1], scale=[1, 1, 1]) for b in bones]
        rows[1] = dict(translation=[0, 1.0 + .04 * i, 0], rotation=turn_y(.1 * i), scale=[1, 1, 1])
        rows[2]['translation'] = [.1 + pull * i, -.1, 0]
        return rows
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip='owned.hkx', skeletonName='Owned', game='sekiro',
                skeleton=dict(name='Owned', boneCount=len(bones), bones=bones), frameCount=COUNT, frameRate=30.0,
                duration=(COUNT - 1) / 30, trackCount=len(bones), blockCount=0, compression='interleaved',
                trackBoneIndices=list(range(len(bones))), trackNames=[b['name'] for b in bones],
                frames=[frame(i) for i in range(COUNT)], rootMotion=None, rootUp=None, rootForward=None)


def write_png(path):
    image = bpy.data.images.new('owned_a', 2, 2)
    image.pixels = [.8, .6, .4, 1] * 4
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def box_model(temp, name, bones=BONES, carrier=None):
    """A box 1.8 m tall in rings of four vertices: the lower half on the thighs by side, the upper half on the pelvis.

    carrier puts every vertex on that bone instead."""
    names = [b[0] for b in bones]
    rings = [0, .45, .8, 1.0, 1.35, 1.8]
    positions = np.asarray([[x, y, z] for y in rings for x, z in ((-.2, -.1), (.2, -.1), (.2, .1), (-.2, .1))], np.float32)
    faces = []
    for ring in range(len(rings) - 1):
        for corner in range(4):
            a, b = ring * 4 + corner, ring * 4 + (corner + 1) % 4
            faces += [[a, b, b + 4], [a, b + 4, a + 4]]
    owner = [names.index(carrier) if carrier else names.index('Pelvis') if y >= 1.0 else names.index('L_Thigh' if x > 0 else 'R_Thigh')
             for x, y, _ in positions]
    count = len(positions)
    data = Path(temp) / f'{name}.npz'
    np.savez(data, positions=positions, normals=np.zeros((count, 3), np.float32), uvs=np.zeros((count, 2), np.float32),
             uv_0=np.zeros((count, 2), np.float32), bone_indices=np.asarray([[i, 0, 0, 0] for i in owner], np.int32),
             bone_weights=np.asarray([[1, 0, 0, 0]] * count, np.float32), faces=np.asarray(faces, np.int32),
             face_materials=np.zeros(len(faces), np.int32), vertex_materials=np.zeros(count, np.int32),
             bone_names=np.asarray(names), bone_parents=np.asarray([b[1] for b in bones], np.int32),
             bone_translations=np.asarray([b[2] for b in bones], np.float32), bone_rotations=np.zeros((len(bones), 3), np.float32),
             bone_scales=np.ones((len(bones), 3), np.float32), material_names=np.asarray(['body']))
    image = Path(temp) / 'owned_a.png'
    if not image.is_file():
        write_png(image)
    material = dict(name='body', mtd='owned.mtd', albedo=dict(path=str(image), linear=False, uv=0, scale=[1, 1], stem='owned_a'),
                    normal=None, emissive=None, samplers=[], alpha=False, color=[1, 1, 1])
    return dict(name=name, source=f'{name}.chrbnd', data=str(data), materials=[material],
                stats=dict(vertices=count, triangles=len(faces)), attachment=None)


def scene(temp, models, pull=0.0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = import_motion(owned_motion(pull))
    manifest = Path(temp) / 'character.json'
    manifest.write_text(json.dumps(dict(version=4, game='sekiro', models=models, warnings=[], material_library='', texture_count=1)),
                        encoding='utf-8')
    import_character(manifest, rig)
    return rig


def verified(temp, render=None):
    info = verify_scene(Path(temp) / 'verify.json', render)
    return info, {check['name'].split(': ', 1)[1] if ': ' in check['name'] else check['name']: check for check in info['checks']
                  if not check['name'].startswith('C9991')}


with tempfile.TemporaryDirectory() as temp:
    scene(temp, [box_model(temp, 'c9990')])
    info, checks = verified(temp, Path(temp) / 'front.png')
    assert info['passed'], [c for c in info['checks'] if not c['ok']]
    rig = info['rigs'][0]
    assert rig['role'] == 'target' and abs(rig['height'] - 1.8) < 1e-3, rig
    assert rig['sides'] == dict(left=1, right=1), rig['sides']
    mesh = rig['meshes'][0]
    # The pelvis rises 16 cm and turns 0.4 rad over the clip; the box moves with it without stretching.
    assert mesh['moved'] > .15 and mesh['bonesMoved'] > .15, mesh
    assert mesh['stretch99'] < 1.001 and mesh['detachedVertices'] == 0 and mesh['unweighted'] == 0, mesh
    assert mesh['materials'][0]['baseColor'] and all(image['found'] for image in mesh['materials'][0]['images']), mesh
    for name in ('size', 'upright', 'left side on +X', 'follows its bones', 'skin stretch', 'bones in the animation', 'image files', 'base colors'):
        assert name in checks, (name, sorted(checks))
    assert [Path(p).name for p in info['renders']] == ['front.png', 'front-side.png'], info['renders']
    assert all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in info['renders'])

    # A thigh pulled 30 cm out per frame tears the skin between thigh and pelvis, most on the last frame. Cloth on real
    # characters stretches as far, so the check is advisory: it names the frame and the scene still passes.
    scene(temp, [box_model(temp, 'c9990')], pull=.3)
    info, checks = verified(temp)
    assert not checks['skin stretch']['ok'] and checks['skin stretch']['advisory'] and checks['follows its bones']['ok'], checks
    assert info['passed'] and not any(c['advisory'] for c in info['checks'] if c is not checks['skin stretch']), info['checks']
    mesh = info['rigs'][0]['meshes'][0]
    assert mesh['stretch99'] > 3 and mesh['stretchFrame'] == COUNT and f'frame {COUNT}' in checks['skin stretch']['detail'], mesh

    # A second model on a bone the animation does not have: the bridge adds it as a model bone that never moves.
    orphan = [*BONES, ('Orphan', -1, [0, 1.0, 0])]
    scene(temp, [box_model(temp, 'c9990'), box_model(temp, 'c9991', orphan, 'Orphan')])
    # The bridge packs its images, so only an image unpacked to a file that is then deleted goes missing.
    for image in bpy.data.images:
        if image.packed_file:
            image.unpack(method='USE_ORIGINAL')
    (Path(temp) / 'owned_a.png').unlink()
    info = verify_scene(Path(temp) / 'verify.json')
    by_name = {check['name']: check for check in info['checks']}
    loose = next(c for name, c in by_name.items() if name.startswith('C9991') and name.endswith('bones in the animation'))
    assert not loose['ok'] and 'Orphan' in loose['detail'], loose
    body = next(c for name, c in by_name.items() if name.startswith('C9990') and name.endswith('bones in the animation'))
    assert body['ok'], body
    missing = next(c for name, c in by_name.items() if name.endswith('image files'))
    assert not missing['ok'] and 'owned_a.png' in missing['detail'], missing
    assert not info['passed']

print('PASS: verify measures size, sides, skin and images, draws the scene, notes stretched skin with its frame, '
      'and fails on model bones outside the animation and missing images', flush=True)
