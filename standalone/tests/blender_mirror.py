"""Mirror animation of the retarget add-on on an owned synthetic bridge rig. Run with Blender --background --factory-startup --python this_file.py.

A FromSoftware-style skeleton is imported through the bridge with every rest
frame turned at random, so that no left bone rests as the mirror image of its
right one; FromSoftware's do not either, they differ by half a turn. The
shoulder helpers rest that way and the left one scales unevenly. Cloth bones on
either hip have names without a side, a sash hangs on the left hip only, the
cloth of the left sleeve hangs on the forearm, pouches on either hip rest 5 mm
from each other's mirrored places, and the right weapon bone rests 3 cm away
from the mirrored place of the left one. Gear as FromSoftware keeps
it: a spear rests 2.5 m out to the left, with a fin on either side, and its
keys bring it into the left hand; a cord in the right hand ends in a bone that
rests 13 m below and is keyed up to it; a scabbard on the left hip has a mesh
of its own; a sheath on
the left hip bends together with the left thigh, as Wolf's is part of his
clothes; and hip cases without a mesh hold the place where the game hangs
sheathed weapons. The clip swings the left arm, turns and leans the body,
travels sideways and turns with root motion.
Checked: the mirrored clip is the reflection of the original, bone by bone,
wherever a pair rests at mirrored places: the right arm does what the left arm
did, the body leans and turns the other way, and the cloth bones pair by place
but the pouches do not;
gear is placed at the reflection of where it was, so the weapons change hands
with the motion, the spear goes into the right hand, the bones below gear
mirror across the piece's own plane, so that the spear's fins swap and the cord
and its far bone reflect their own motion on it, and the scabbard goes to the
right hip; the sheath that
bends with the body, the cases, the sash and the sleeve cloth stay on their
side, attached, the sash mirroring its own turn and the others keeping their
own motion; root motion changes sign sideways and in its turn; the original
action and root motion stay unchanged; mirroring twice gives the original back;
the export of the mirrored clip, active or by name, has the same tracks and
reads back as the mirrored clip; a keyed custom property moves to the
counterpart; names are numbered rather than reused; and the operator, its panel
row and its refusal with a control rig work.
"""
import json
import math
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import bl_to_game_trs, export_motion, import_motion
import sekiro_retarget
from sekiro_retarget import control_rig, mirror, retarget

COUNT, RATE = 30, 30
FLIP = Matrix.Diagonal((-1, 1, 1, 1))
# Gear bones keyed to sit at a place in another bone: (that bone, the place in its frame).
HELD = {'L_Spear': ('L_Hand', Vector((0, .04, 0))), 'R_Katana_Wire': ('Wire_01', Vector((0, .03, 0)))}
# Vertices of a mesh the rig bends: {bone: weight} each. The sheath bends together with the thigh, the spear has a
# mesh of its own, and the cord's two bones bend one vertex together.
SKIN = ({'Sheath': .5, 'L_Thigh': .5}, {'Sheath': 1.0}, {'L_Spear': 1.0}, {'Wire_02': .6, 'R_Katana_Wire': .4},
        {'L_Sleeve_Cloth': .5, 'L_Forearm': .5})
# The scabbard's mesh in its bone's rest frame: a wedge along its Y axis, the same on both sides of its X and Z axes
# but not of its Y axis, so that only a flip of X or Z maps it onto itself.
SAYA = [(side * (.03 - .033 * y), y, flat * .015) for y in (0, .2, .4, .6) for side in (-1, 1) for flat in (-1, 1)]


def skeleton():
    """The skeleton's bones (name, parent, head, label), with cloth, a sash, gear and an offset right weapon."""
    bones = [(name, parent, (head[0], head[1] + .03, head[2]) if name == 'R_Weapon' else head, label)
             for name, parent, head, label in humanoids.fromsoftware(45, 'elden')]
    heads = {name: Vector(head) for name, parent, head, label in bones}
    wire = heads['R_Weapon'] + Vector((-.02, 0, -.02))
    extra = [('Cloth_01', 'Pelvis', (.12, .10, .92)), ('Cloth_02', 'Pelvis', (-.12, .10, .92)),
             ('Cloth_03', 'Cloth_01', (.13, .11, .72)), ('Cloth_04', 'Cloth_02', (-.13, .11, .72)),
             ('L_Sash', 'Pelvis', (.16, .06, .98)), ('Sheath', 'Pelvis', (.18, .03, .9)),
             ('L_Spear', 'L_Hand', (2.5, 0, 1.3)), ('Wire_01', 'R_Hand', tuple(wire)),
             ('Wire_02', 'Wire_01', tuple(wire + Vector((0, 0, -.1)))), ('R_Katana_Wire', 'Wire_01', (wire.x, wire.y, -13.0)),
             ('Saya_Storage', 'Pelvis', (.22, -.04, 1.0)),
             ('L_Sleeve_Cloth', 'L_Forearm', tuple(heads['L_Forearm'] + Vector((0, .05, -.05)))),
             ('L_Wepon_Case', 'Pelvis', (.185, -.006, 1.005)), ('R_Wepon_Case', 'Pelvis', (-.185, -.006, 1.005)),
             ('Spear_L_Fin', 'L_Spear', (2.55, 0, 1.4)), ('Spear_R_Fin', 'L_Spear', (2.45, 0, 1.4)),
             ('Pouch_1', 'Pelvis', (.2, .12, 1.0)), ('Pouch_2', 'Pelvis', (-.205, .12, 1.0))]
    return bones + [(name, parent, head, None) for name, parent, head in extra]


def rests(bones, seed):
    """Rest matrices at the heads with randomly turned frames; the shoulders rest as FromSoftware's pairs do."""
    rng = random.Random(seed)
    rest = {}
    for name, parent, head, label in bones:
        axis = Vector([rng.uniform(-1, 1) for _ in range(3)]).normalized()
        rest[name] = Matrix.LocRotScale(Vector(head), Quaternion(axis, rng.uniform(-math.pi, math.pi)), None)
    rest['R_Shoulder'] = FLIP @ rest['L_Shoulder'] @ FLIP @ Matrix.Rotation(math.pi, 4, 'Z')
    return rest


def pose(bones, rest, turns, travel):
    """Armature-space matrices with each bone turned in world space by turns[name] after its parent; held gear sits
    at its place in the bone that holds it."""
    deltas, result = {}, {}
    for name, parent, head, label in bones:
        deltas[name] = (deltas[parent] if parent else Quaternion()) @ turns.get(name, Quaternion())
        position = result[parent] @ (rest[parent].inverted() @ rest[name]).translation if parent else rest[name].translation.copy()
        if name in HELD:
            position = result[HELD[name][0]] @ HELD[name][1]
        result[name] = Matrix.LocRotScale(position + travel.get(name, Vector()), deltas[name] @ rest[name].to_quaternion(), None)
    return result


def clip(bones, rest):
    """Bridge motion JSON: the left arm swings wide, the right one barely moves, the body turns, leans and travels."""
    poses = []
    for f in range(COUNT):
        t = f / (COUNT - 1)
        s = math.sin(2 * math.pi * t)
        turns = {
            'Pelvis': Quaternion((0, 0, 1), .4 * s), 'Spine': Quaternion((0, 1, 0), .25 * s),
            'Neck': Quaternion((0, 0, 1), .3 * s),
            'L_UpperArm': Quaternion(Vector((.3, 1, .2)).normalized(), -1.1 * s),
            'L_Forearm': Quaternion((0, 0, 1), .2 + s * s), 'L_Hand': Quaternion(Vector((1, .5, .3)).normalized(), .7 * s),
            'L_Weapon': Quaternion((1, 0, 0), .5 * s), 'L_Finger1': Quaternion((0, 1, 0), .6 * s * s),
            'R_UpperArm': Quaternion((1, 0, 0), .1 * s), 'R_Weapon': Quaternion((0, 1, 0), .3 * s),
            'L_Thigh': Quaternion((1, 0, 0), .7 * s), 'L_Calf': Quaternion((1, 0, 0), -.6 * s * s),
            'R_Thigh': Quaternion((0, 1, 0), .2 * s),
            'Cloth_01': Quaternion((1, 0, 0), .5 * s), 'Cloth_03': Quaternion((0, 1, 0), .4 * s),
            'Cloth_02': Quaternion((0, 0, 1), .2 * s), 'L_Sash': Quaternion((1, 0, 0), .6 * s),
            'Sheath': Quaternion((0, 1, 0), .5 * s), 'L_Spear': Quaternion((0, 0, 1), .5 * s),
            'Wire_01': Quaternion((1, 0, 0), .3 * s), 'Wire_02': Quaternion((0, 1, 0), .4 * s),
            'R_Katana_Wire': Quaternion((0, 0, 1), .2 * s), 'Saya_Storage': Quaternion((1, 0, 0), .3 * s),
            'L_Sleeve_Cloth': Quaternion((0, 1, 0), .5 * s), 'L_Wepon_Case': Quaternion((1, 0, 0), .2 * s),
            'Spear_L_Fin': Quaternion((1, 0, 0), .6 * s), 'Spear_R_Fin': Quaternion((0, 0, 1), .1 * s)}
        poses.append(pose(bones, rest, turns, {'RootPos': Vector((.15 * t, -.4 * t, .03 * s))}))
        # The left shoulder helper scales unevenly along its own axes.
        poses[-1]['L_Shoulder'] = poses[-1]['L_Shoulder'] @ Matrix.Diagonal((1 + .15 * s, 1, 1 - .1 * s, 1))
    index = {bone[0]: i for i, bone in enumerate(bones)}

    def local(matrices, name, parent):
        return matrices[parent].inverted() @ matrices[name] if parent else matrices[name]
    skeleton = [dict(index=i, name=name, parent=index[parent] if parent else -1,
                     **bl_to_game_trs(*local(rest, name, parent).decompose()))
                for i, (name, parent, head, label) in enumerate(bones)]
    tracks = [i for i, bone in enumerate(bones) if bone[0] != 'Face_Root']
    frames = [[bl_to_game_trs(*local(p, bones[i][0], bones[i][1]).decompose()) for i in tracks] for p in poses]
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip='a000_003000.hkx', skeletonName='Owned', game='sekiro',
                skeleton=dict(name='Owned', boneCount=len(skeleton), bones=skeleton), frameCount=COUNT, frameRate=RATE,
                duration=(COUNT - 1) / RATE, trackCount=len(tracks), trackBoneIndices=tracks,
                trackNames=[bones[i][0] for i in tracks], frames=frames,
                rootMotion=[[.01 * f, .002 * f, .02 * f, .005 * f] for f in range(COUNT)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


def skin(rig, name, points, weights):
    """A mesh that the rig bends, with a {bone: weight} for each of its points."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], [])
    body = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(body)
    body.modifiers.new('Armature', 'ARMATURE').object = rig
    for index, items in enumerate(weights):
        for bone, weight in items.items():
            (body.vertex_groups.get(bone) or body.vertex_groups.new(name=bone)).add([index], weight, 'REPLACE')
    return body


def shapes(rig, body):
    """The points of a mesh as the rig bends them at each frame, in the armature's space."""
    scene = bpy.context.scene
    result = {}
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        result[frame] = [rig.matrix_world.inverted() @ body.matrix_world @ vertex.co for vertex in mesh.vertices]
        evaluated.to_mesh_clear()
    return result


def evaluate(rig, names):
    scene = bpy.context.scene
    result = {}
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        result[frame] = {name: rig.pose.bones[name].matrix.copy() for name in names}
    return result


def root_poses(root):
    scene = bpy.context.scene
    result = []
    for frame in range(1, COUNT + 1):
        scene.frame_set(frame)
        result.append((root.location.copy(), Vector(root.rotation_euler)))
    return result


def gap(a, b):
    """The largest difference between two matrices' entries."""
    return max(abs(x - y) for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))


def angle(matrix):
    """The turn of a matrix in degrees; atan2 of the half-angle sine stays exact for small angles."""
    q = matrix.to_quaternion()
    return math.degrees(2 * math.atan2(Vector(q[1:]).length, abs(q[0])))


def worst(first, second, names=None):
    """Largest matrix entry difference between two evaluations over all frames and the given bones."""
    return max(gap(matrices[name], second[frame][name]) for frame, matrices in first.items() for name in names or matrices)


def local(rig, matrices, name):
    """A bone's pose relative to its rest and its parent: what its keys hold."""
    bone = rig.data.bones[name]
    parent = bone.parent
    return (parent.matrix_local.inverted() @ bone.matrix_local).inverted() @ matrices[parent.name].inverted() @ matrices[name]


def keys(action):
    return {(curve.data_path, curve.array_index): [tuple(point.co) for point in curve.keyframe_points]
            for curve in retarget.action_curves(action)}


def path(evaluation, name, carrier='Spine2'):
    """How far a bone's head travels over the clip, seen from the chest."""
    def place(frame):
        return (evaluation[frame][carrier].inverted() @ evaluation[frame][name]).translation
    return sum((place(frame + 1) - place(frame)).length for frame in range(1, COUNT))


def side(evaluation, frame, name, rest_local):
    """Where a bone's head is seen from the pelvis as it stands at rest: x > 0 on the left."""
    return ((evaluation[frame]['Pelvis'] @ rest_local['Pelvis'].inverted()).inverted() @ evaluation[frame][name].translation).x


class Layout:
    """Stands in for a panel's layout: records what it draws; the operators it shows must exist."""
    def __init__(self, drawn):
        self.drawn = drawn

    def __getattr__(self, name):
        if name in ('row', 'column', 'grid_flow'):
            return lambda *args, **kwargs: Layout(self.drawn)
        if name == 'separator':
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def label(self, text='', **kwargs):
        self.drawn.append(text)

    def prop(self, data, name, text='', **kwargs):
        self.drawn.append(text)

    def operator(self, idname, text='', **kwargs):
        group, name = idname.split('.')
        assert getattr(getattr(bpy.ops, group), name).get_rna_type()
        self.drawn.append(idname)
        return SimpleNamespace()


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sekiro_retarget.register()
    scene = bpy.context.scene
    bones = skeleton()
    rest = rests(bones, 11)
    rig = import_motion(clip(bones, rest))
    names = [bone[0] for bone in bones]
    rest_local = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
    skin(rig, 'Gear', [(0, 0, .01 * index) for index in range(len(SKIN))], SKIN)
    saya = skin(rig, 'Saya', [rest_local['Saya_Storage'] @ Vector(point) for point in SAYA], [{'Saya_Storage': 1.0}] * len(SAYA))
    saya_before = shapes(rig, saya)
    root = retarget.root_object(rig)
    original_action, original_root = rig.animation_data.action, root.animation_data.action
    # A custom property keyed on the left hand only.
    hand = rig.pose.bones['L_Hand']
    for frame, value in ((1, 0.0), (COUNT, 1.0)):
        hand['grip'] = value
        hand.keyframe_insert('["grip"]', frame=frame)
    before = keys(original_action), keys(original_root)
    original, original_root_poses = evaluate(rig, names), root_poses(root)
    work = Path(tempfile.mkdtemp(prefix='MirrorTest-'))
    export_motion(work / 'original.motion.json')
    original_export = json.loads((work / 'original.motion.json').read_text(encoding='utf-8'))

    # Pairs: by name, and by place for the cloth bones, whose names give no side.
    pairs = mirror.counterparts(rig)[0]
    assert pairs['L_Hand'] == 'R_Hand' and pairs['R_Weapon'] == 'L_Weapon' and pairs['L_Shoulder'] == 'R_Shoulder'
    assert pairs['Cloth_01'] == 'Cloth_02' and pairs['Cloth_04'] == 'Cloth_03' and pairs['L_Wepon_Case'] == 'R_Wepon_Case', pairs
    assert not {'L_Sash', 'Sheath', 'Pelvis', 'Spine', 'Head', 'L_Spear', 'Wire_01', 'Saya_Storage', 'L_Sleeve_Cloth'} & set(pairs)
    # Pouches 5 mm from each other's mirrored places were placed by hand rather than mirrored, so they do not pair.
    assert not {'Pouch_1', 'Pouch_2'} & set(pairs)
    # The hands' rests are no mirror images, not even up to flipped axes, as Paste Flipped Pose would need.
    turn = mirror.reflection(rig.data.bones['R_Hand'], rig.data.bones['L_Hand'])[0]
    assert min(max(abs(value) for value in row) for row in turn) < .95, turn
    # The spear sits in the left hand only through its keys.
    reach = min((original[f]['L_Spear'].translation - original[f]['L_Hand'].translation).length for f in original)
    assert (rest_local['L_Spear'].translation - rest_local['L_Hand'].translation).length > 1.5 and reach < .1, reach

    started = time.perf_counter()
    result = mirror.mirror(bpy.context, rig)
    seconds = time.perf_counter() - started
    action = rig.animation_data.action
    assert action == result['action'] and action.name == original_action.name + ' Mirrored', action.name
    assert root.animation_data.action == result['root'] and result['root'].name == action.name + ' RootMotion'
    assert all(item.use_fake_user for item in (original_action, original_root, action, result['root']))
    assert action['sekiro_mirrored_from'] == original_action and not action.get('sekiro_retarget')
    rules = result['rules']
    expected = dict(L_Weapon='follow', R_Weapon='follow', L_Spear='follow', Wire_01='follow', Saya_Storage='follow',
                    Wire_02='reflect', R_Katana_Wire='reflect', Spear_L_Fin='swap', Spear_R_Fin='swap', Sheath='keep',
                    L_Sleeve_Cloth='keep', L_Wepon_Case='swap', R_Wepon_Case='swap', L_Sash='reflect', Cloth_01='swap',
                    Pelvis='reflect', L_Hand='swap', Pouch_1='reflect', Pouch_2='reflect')
    assert {name: rules[name] for name in expected} == expected, {name: rules[name] for name in expected}
    assert any('Gear changes sides' in note and 'L_Spear, L_Weapon, R_Weapon, Saya_Storage, Wire_01' in note
               for note in result['notes']), result['notes']
    assert any('keeps its side: L_Wepon_Case, R_Wepon_Case, Sheath.' in line for line in result['warnings']), result['warnings']
    assert any('mirror their own motion: L_Sash.' in line for line in result['warnings']), result['warnings']
    assert any('carries them: L_Sleeve_Cloth.' in line for line in result['warnings']), result['warnings']
    assert (keys(original_action), keys(original_root)) == before, 'the original clip changed'
    mirrored = evaluate(rig, names)

    # Wherever a pair rests at mirrored places, each bone is its counterpart reflected across the middle plane:
    # pose' = flip · counterpart's pose · its rest⁻¹ · flip · own rest. Off the middle line, a bone without a
    # counterpart cannot be, and neither can the bones below it.
    loose = {name for name in names if rules[name] in ('follow', 'keep')
             or rules[name] == 'reflect' and abs(rest_local[name].translation.x) > .01}
    exact = [name for name in names if not ({name} | {p.name for p in rig.data.bones[name].parent_recursive}) & loose]
    reflection_error = max(
        gap(mirrored[frame][name], FLIP @ original[frame][other] @ rest_local[other].inverted() @ FLIP @ rest_local[name])
        for frame in mirrored for name in exact for other in [pairs.get(name, name)])
    assert reflection_error < 1e-4 and {'L_Wepon_Case', 'Cloth_03', 'R_Shoulder'} <= set(exact), reflection_error
    # The right arm does what the left arm did; the left one does the little the right one did.
    assert path(original, 'L_Hand') > 5 * path(original, 'R_Hand'), (path(original, 'L_Hand'), path(original, 'R_Hand'))
    hand_error = max((mirrored[f]['R_Hand'].translation - FLIP.to_3x3() @ original[f]['L_Hand'].translation).length
                     for f in mirrored)
    assert hand_error < 1e-4 and abs(path(mirrored, 'R_Hand') - path(original, 'L_Hand')) < 1e-4, hand_error
    assert abs(path(mirrored, 'L_Hand') - path(original, 'R_Hand')) < 1e-4
    # The body leans the other way: the head moves to the other side.
    lean = max(abs(original[f]['Head'].translation.x) for f in original)
    assert lean > .05 and max(abs(mirrored[f]['Head'].translation.x + original[f]['Head'].translation.x)
                              for f in original) < 1e-4, lean
    # The unevenly scaled shoulder helper scales the same way on the other side.
    scale_error = max((mirrored[f]['R_Shoulder'].to_scale() - original[f]['L_Shoulder'].to_scale()).length for f in original)
    assert scale_error < 1e-5 and max(abs(original[f]['L_Shoulder'].to_scale()[0] - 1) for f in original) > .1, scale_error

    # Gear is placed at the reflection of where it was, turned by a reflection W in its rest frame: pose' = flip ·
    # pose · W, so the weapons change hands with the motion and the spear goes into the right hand. Without a mesh
    # that says otherwise, W is armature X seen from the rest frame. The scabbard's mesh maps onto itself only under
    # a flip of its own X or Z, so W is that, and the mirrored scabbard is the flipped original, point for point.
    turns = mirror.symmetry(rig, [name for name in names if rules[name] == 'follow'])
    own = {name: rest_local[name].to_3x3().transposed() @ FLIP.to_3x3() @ rest_local[name].to_3x3() for name in turns}
    assert all(gap(turns[name], own[name]) < 1e-5 for name in ('L_Weapon', 'R_Weapon', 'L_Spear', 'Wire_01')), turns
    assert gap(turns['Saya_Storage'], own['Saya_Storage']) > .5 and abs(turns['Saya_Storage'][1][1] - 1) < 1e-9 and \
        sorted(turns['Saya_Storage'][row][row] for row in range(3)) == [-1, 1, 1], turns['Saya_Storage']
    gear_error = max(gap(mirrored[f][name], FLIP @ original[f][name] @ turns[name].to_4x4())
                     for f in mirrored for name in turns)
    assert gear_error < 1e-4, gear_error
    saya_after = shapes(rig, saya)
    saya_error = max(min((point - FLIP.to_3x3() @ other).length for other in saya_before[f])
                     for f in saya_after for point in saya_after[f])
    assert saya_error < 1e-4, saya_error
    grip_error = max(abs((mirrored[f][weapon].translation - mirrored[f][hand].translation).length
                         - (original[f][weapon].translation - original[f][other].translation).length)
                     for f in mirrored for weapon, hand, other in (('R_Weapon', 'L_Hand', 'R_Hand'),
                                                                  ('L_Weapon', 'R_Hand', 'L_Hand'),
                                                                  ('L_Spear', 'R_Hand', 'L_Hand')))
    assert grip_error < 1e-5 and max((mirrored[f]['L_Spear'].translation - mirrored[f]['R_Hand'].translation).length
                                     for f in mirrored) < .1, grip_error
    assert all(side(mirrored, f, 'Saya_Storage', rest_local) < -.1 < .1 < side(original, f, 'Saya_Storage', rest_local)
               for f in mirrored)
    # The bones below gear mirror across the piece's own plane Q, the reflection W of its bone at that bone's rest:
    # pose' = flip · counterpart's pose · its rest⁻¹ · Q · own rest. The cord's bones rest on the cord's plane and
    # reflect their own motion; the spear's fins rest at each other's mirrored places across the spear's, and swap.
    plane = {name: rest_local[name] @ turns[name].to_4x4() @ rest_local[name].inverted() for name in ('Wire_01', 'L_Spear')}
    piece_error = max(gap(mirrored[f][name], FLIP @ original[f][other] @ rest_local[other].inverted() @ plane[root]
                          @ rest_local[name])
                      for f in mirrored for name, other, root in (
                          ('Wire_02', 'Wire_02', 'Wire_01'), ('R_Katana_Wire', 'R_Katana_Wire', 'Wire_01'),
                          ('Spear_L_Fin', 'Spear_R_Fin', 'L_Spear'), ('Spear_R_Fin', 'Spear_L_Fin', 'L_Spear')))
    assert piece_error < 1e-4, piece_error
    fin_turn = max(angle(local(rig, original[f], 'Spear_L_Fin')) for f in original)
    assert fin_turn > 20 and max(abs(angle(local(rig, mirrored[f], 'Spear_R_Fin')) - angle(local(rig, original[f], 'Spear_L_Fin')))
                                 for f in mirrored) < 1e-3, fin_turn
    # Bones that keep their own motion have the original's poses relative to rest: gear that bends with the body,
    # and cloth that a bone with a counterpart carries.
    kept = max(gap(local(rig, mirrored[f], name), local(rig, original[f], name))
               for f in mirrored for name in ('Sheath', 'L_Sleeve_Cloth'))
    assert kept < 1e-5, kept

    # Bones without a counterpart stay on their side, attached: the sash mirrors its own turn, the sheath keeps it.
    for name in ('L_Sash', 'Sheath'):
        assert all(side(mirrored, f, name, rest_local) > .1 for f in mirrored), name
        assert max(abs(angle(local(rig, mirrored[f], name)) - angle(local(rig, original[f], name))) for f in mirrored) < 1e-3
        assert max(angle(local(rig, original[f], name)) for f in original) > 20
    attached = max((mirrored[f][name].translation - mirrored[f][parent] @ (rest_local[parent].inverted() @ rest_local[name]).translation).length
                   for f in mirrored for name, parent in (('L_Sash', 'Pelvis'), ('Sheath', 'Pelvis'), ('L_Sleeve_Cloth', 'L_Forearm')))
    assert attached < 1e-5, attached

    # Root motion: sideways travel and the turn change sign.
    root_error = max(max(abs(a.x + b.x), abs(a.y - b.y), abs(a.z - b.z), abs(r.x - q.x), abs(r.y + q.y), abs(r.z + q.z))
                     for (a, r), (b, q) in zip(root_poses(root), original_root_poses))
    assert root_error < 1e-6 and max(abs(r.z) for a, r in original_root_poses) > .1, root_error

    # The keyed custom property moves to the right hand, which gets the property.
    curves = keys(action)
    assert curves.get(('pose.bones["R_Hand"]["grip"]', 0)) == before[0][('pose.bones["L_Hand"]["grip"]', 0)]
    assert ('pose.bones["L_Hand"]["grip"]', 0) not in curves and 'grip' in rig.pose.bones['R_Hand']

    # Export: the same tracks, mirrored root motion, and the motion reads back.
    summary = export_motion(work / 'mirrored.motion.json')
    exported = json.loads((work / 'mirrored.motion.json').read_text(encoding='utf-8'))
    assert summary['action'] == action.name and not summary['warnings'], summary
    assert exported['trackNames'] == original_export['trackNames']
    root_sample_error = max(max(abs(a[0] + b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]), abs(a[3] + b[3]))
                            for a, b in zip(exported['rootMotion'], original_export['rootMotion']))
    assert root_sample_error < 1e-6 and max(abs(b[3]) for b in original_export['rootMotion']) > .1, root_sample_error

    # Mirroring twice, through the operator and its panel row, gives the original back.
    drawn = []
    sekiro_retarget.SKR_PT_control_rig.draw(SimpleNamespace(layout=Layout(drawn)), SimpleNamespace(object=rig, scene=scene, region=SimpleNamespace(width=300)))
    assert 'sekiro_retarget.mirror_animation' in drawn, drawn
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert sekiro_retarget.SKR_OT_mirror_animation.poll(bpy.context)
    assert bpy.ops.sekiro_retarget.mirror_animation() == {'FINISHED'}
    twice = rig.animation_data.action
    assert twice.name == action.name + ' Mirrored' and root.animation_data.action.name == twice.name + ' RootMotion'
    twice_error = worst(original, evaluate(rig, names))
    root_twice = max(max((a - b).length, (r - q).length) for (a, r), (b, q) in zip(root_poses(root), original_root_poses))
    # The cord's far bone is keyed 14 m from its rest, where a float key holds about 1e-6.
    assert twice_error < 3e-5 and root_twice < 1e-6, (twice_error, root_twice)

    # By name: with the original playing, the export of the mirrored clip pairs its root motion by name.
    retarget.assign_action(rig, original_action)
    retarget.assign_action(root, original_root)
    by_name = export_motion(work / 'by_name.motion.json', action=action.name)
    named = json.loads((work / 'by_name.motion.json').read_text(encoding='utf-8'))
    assert not by_name['warnings'] and named['rootMotion'] == exported['rootMotion'], by_name
    assert named['frames'] == exported['frames']
    assert rig.animation_data.action == original_action and root.animation_data.action == original_root

    # Mirroring the original again numbers the new clip rather than reusing a name.
    again = mirror.mirror(bpy.context, rig)
    assert again['action'].name == original_action.name + ' Mirrored.001', again['action'].name
    assert again['root'].name == again['action'].name + ' RootMotion'
    assert worst(mirrored, evaluate(rig, names)) < 1e-6

    # With a control rig the game bones follow the controls: the operator is greyed out and the mirror refuses.
    retarget.assign_action(rig, original_action)
    retarget.assign_action(root, original_root)
    control_rig.add(bpy.context, rig)
    assert not sekiro_retarget.SKR_OT_mirror_animation.poll(bpy.context)
    try:
        mirror.mirror(bpy.context, rig)
        raise AssertionError('mirrored a rig with a control rig')
    except ValueError as exc:
        assert 'control rig' in str(exc), exc
    control_rig.remove(bpy.context, rig, keep_edits=False)

    # The export reads back as the mirrored clip.
    readback = import_motion(exported)
    readback_error = worst(mirrored, evaluate(readback, names))
    assert readback_error < 1e-4, readback_error
    readback_root = max(max((a - b).length, (r - q).length) for (a, r), (b, q) in zip(
        root_poses(retarget.root_object(readback)), [(Vector((-a.x, a.y, a.z)), Vector((r.x, -r.y, -r.z)))
                                                     for a, r in original_root_poses]))
    assert readback_root < 1e-5, readback_root

    bpy.ops.wm.read_factory_settings(use_empty=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f"Mirrored {result['pairs']} pairs over {COUNT} frames in {seconds:.2f} s; "
          f"{len(exact)} of {len(names)} bones reflect exactly within {reflection_error:.1e}")
    print(f'Right hand follows the left one within {hand_error:.1e} m; shoulder scale within {scale_error:.1e}; '
          f'root motion within {root_error:.1e}')
    print(f'Gear placed at its reflection within {gear_error:.1e}, grips within {grip_error:.1e} m, scabbard mesh mirrored '
          f'within {saya_error:.1e} m, bones below gear across its plane within {piece_error:.1e}; bones that keep their '
          f'motion within {kept:.1e}; bones on their side attached within {attached:.1e} m')
    print(f'Twice: original back within {twice_error:.1e} (root {root_twice:.1e}); export root motion within '
          f'{root_sample_error:.1e}; readback within {readback_error:.1e} (root {readback_root:.1e})')
    print('Mirror check passed')


main()
