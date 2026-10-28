"""Body figures: a Biped-style figure fitted to a skeleton once and kept for every clip of that skeleton.

3ds Max's Biped retargets by its figure: the animator fits a Biped to each character once, in Figure mode, and the
figure's proportions decide how far the feet step and how high the body jumps when a motion from another figure
loads. A figure here is that fit for the full-body bake. It is an armature of Biped-style parts, Pelvis, Spine,
Neck, Head and per side Clavicle, UpperArm, Forearm, Hand, Thigh, Calf, Foot, Toe and Heel, each linked to the
skeleton bone it stands for, made from what the bake finds in the skeleton and placed on its joints. The user moves
the parts' ends onto the character in Edit Mode: the Head's tip onto the top of the head, the Heel onto the back of
the heel on the ground, the Toe's tip onto the tip of the foot, the Thigh's head onto the hip joint, and changes a
link where the bake took the wrong bone. Saving keeps the figure on the rig and in a figure folder under the
skeleton's signature, its bone names and hierarchy, so that the next clip of that skeleton finds it.

The bake reads from a figure the body layout, which bones are the hips, spine, neck, head and limbs, and measures:
leg length, from the hips to the ankles, for travel; hip joints, for the feet's width; height, from the ground to
the top of the head, for jumps; arm and leg lengths and the torso, for props; and per foot its heel, ankle, ball and
toe tip, the points a planted foot can stand on, with the foot's length for the contact tolerances. A rig without a
saved figure takes the same measures from the figure that Create figure would make.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
from . import mapping as matching
from . import retarget

KEY = 'sekiro_figure'  # On the rig: its saved figure, as JSON.
OWNER = 'sekiro_figure_of'  # On a figure object: the rig it is fitted to.
PART = 'sekiro_figure_part'  # On a figure bone: its part.
LINK = 'sekiro_figure_bone'  # On a figure bone: the skeleton bone it stands for, or ''.
VERSION = 1
LIMB_PARTS = dict(arms=(('Clavicle', 'clavicle'), ('UpperArm', 'upperarm'), ('Forearm', 'forearm'), ('Hand', 'hand')),
                  legs=(('Thigh', 'thigh'), ('Calf', 'calf'), ('Foot', 'foot'), ('Toe', 'toe')))
SIDES = dict(L='L', R='R')


def signature(rig):
    """The skeleton's signature: its bone names and hierarchy, the same for every clip the bridge imports of it."""
    bones = sorted(f'{bone.name}|{bone.parent.name if bone.parent else ""}' for bone in rig.data.bones if 'sekiro_control' not in bone)
    return hashlib.sha1('\n'.join(bones).encode('utf-8')).hexdigest()[:12]


def folder():
    """The figure folder: the add-on preference, else Blender's configuration folder."""
    addon = bpy.context.preferences.addons.get(__package__)
    chosen = getattr(addon.preferences, 'figure_folder', '') if addon else ''
    chosen = os.environ.get('SEKIRO_FIGURE_FOLDER') or chosen
    path = Path(bpy.path.abspath(chosen)) if chosen else Path(bpy.utils.user_resource('CONFIG', path='sekiro_retarget/figures'))
    return path


def label(rig):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', rig.name).strip('_') or 'figure'


def frame(rig):
    """(up, forward) in the rig's armature space; forward is None where the rig has no body."""
    to_rig = rig.matrix_world.to_3x3().inverted()
    up = (to_rig @ Vector((0, 0, 1))).normalized()
    forward = matching.anatomy(retarget.rig_bones(rig)).get('forward')
    return up, (to_rig @ Vector(forward)).normalized() if forward else None


def rest_points(rig, sets):
    """Per key of sets, the rest positions, in the rig's armature space, of the vertices that the bones in its set
    deform most."""
    owner = {name: key for key, names in sets.items() for name in names}
    to_rig = rig.matrix_world.inverted()
    points = {key: [] for key in sets}
    for obj, armature in retarget.deformers(rig):
        groups = {group.index: group.name for group in obj.vertex_groups
                  if group.name in owner and group.name in armature.data.bones and group.name in rig.data.bones}
        if not groups:
            continue
        place = armature.matrix_world.inverted() @ obj.matrix_world
        post = to_rig @ armature.matrix_world
        # A bind adapter's bones follow the rig's bones of the same name from its own rest pose.
        moves = {name: rig.data.bones[name].matrix_local @ armature.data.bones[name].matrix_local.inverted() for name in groups.values()}
        for vertex in obj.data.vertices:
            best, weight = None, 0.0
            for item in vertex.groups:
                if item.weight > weight:
                    best, weight = item.group, item.weight
            if best in groups:
                points[owner[groups[best]]].append(post @ (moves[groups[best]] @ (place @ vertex.co)))
    return points


def layout(body):
    """The body layout of a characterization (see mapping.characterize), as a figure saves it."""
    return dict(hips=body['hips'], spine=list(body['spine']), neck=list(body['neck']), head=body['head'],
                arms={side: {part: arm[part] for name, part in LIMB_PARTS['arms']} for side, arm in body['arms'].items()},
                legs={side: {part: leg[part] for name, part in LIMB_PARTS['legs']} for side, leg in body['legs'].items()})


def fit(rig, given=None):
    """A figure fitted to a rig from its skeleton and meshes: {layout, parts: {part: (head, tail, link)}}, or None
    without a body. given is a body layout to fit instead of the one the bake finds.

    Each part lies from its joint to the next one. The Head reaches the top of the head mesh, the Hand the middle of
    its knuckles, the Foot the ball of the foot (the toe joint) and the Toe the tip of the foot mesh; the Heel stands
    on the ground at the back of the foot mesh. Without meshes, the head is taken as 0.13 of the head joint's height
    above the ground, the heel a quarter of the foot behind the ankle and the toe tip 0.6 of it ahead of the ball;
    without a toe bone, the ball lies half way. The ground is the lowest point of the foot meshes, else the armature's
    origin where the feet rest just above it, as FromSoftware's do, else the lowest foot joint.
    """
    body = matching.characterize(retarget.rig_bones(rig), given)
    if body is None:
        return None
    bones = rig.data.bones
    up, forward = frame(rig)

    def at(name):
        return bones[name].head_local.copy()

    def height(point):
        return point.dot(up)

    def flat(vector):
        return vector - up * vector.dot(up)
    feet = {side: leg for side, leg in body['legs'].items()}
    lowest = min(height(at(name)) for leg in feet.values() for name in (leg['foot'], leg['toe']) if name)
    hips = at(body['hips'])
    legs = sum(((hips - at(leg['foot'])).length for leg in feet.values()), 0.0) / len(feet)
    sets = {side: retarget.subtree(bones, leg['foot']) for side, leg in feet.items()}
    if body['head']:
        sets['head'] = retarget.subtree(bones, body['head'])
    found = rest_points(rig, sets)
    sole = {side: found[side] for side in feet}
    meshed = [point for points in sole.values() for point in points]
    ground = min(height(point) for point in meshed) if meshed else 0.0 if 0.0 <= lowest <= .25 * legs else lowest
    parts = {}

    def chain(names, prefix, end):
        """Parts along a chain of skeleton bones, each ending where the next one starts, the last at end."""
        for index, name in enumerate(names):
            tail = at(names[index + 1]) if index + 1 < len(names) else end
            parts[prefix + (str(index) if index else '')] = (at(name), tail, name)
    top = (body['neck'] or [body['head']])[0] if body['head'] or body['neck'] else None
    chain([body['hips']], 'Pelvis', at(body['spine'][0]) if body['spine'] else hips + up * .1 * legs)
    if body['spine']:
        chain(body['spine'], 'Spine', at(top) if top else at(body['spine'][-1]) + up * .1 * legs)
    if body['head']:
        if body['neck']:
            chain(body['neck'], 'Neck', at(body['head']))
        crown = found['head']
        joint = at(body['head'])
        rise = max(height(point) for point in crown) - height(joint) if crown else .13 * (height(joint) - ground)
        parts['Head'] = (joint, joint + up * max(rise, .02 * legs), body['head'])
    for side, arm in body['arms'].items():
        names = [arm[part] for name, part in LIMB_PARTS['arms'] if arm[part]]
        labels = [name for name, part in LIMB_PARTS['arms'] if arm[part]]
        roots = [names[0] for number, names in body['fingers'].get(side, {}).items() if number != 0]
        knuckles = sum((at(name) for name in roots), Vector()) / len(roots) if roots else \
            at(arm['hand']) + (at(arm['hand']) - at(arm['forearm'])) * .35
        for index, (name, part) in enumerate(zip(names, labels)):
            parts[f'{side} {part}'] = (at(name), at(names[index + 1]) if index + 1 < len(names) else knuckles, name)
    for side, leg in feet.items():
        for name, part in LIMB_PARTS['legs'][:2]:
            parts[f'{side} {name}'] = (at(leg[part]), at(leg['calf'] if part == 'thigh' else leg['foot']), leg[part])
        ankle = at(leg['foot'])
        points = sole[side]
        ahead = flat(at(leg['toe']) - ankle) if leg['toe'] else flat(forward) if forward else flat(Vector((0, -1, 0)))
        ahead = ahead.normalized() if ahead.length > 1e-9 else Vector((0, -1, 0))
        base = ankle - up * (height(ankle) - ground)
        if points:
            along = [(point - ankle).dot(ahead) for point in points]
            heel, tip = base + ahead * min(along), base + ahead * max(along)
            ball = at(leg['toe']) if leg['toe'] else base.lerp(tip, .5) + up * .5 * (height(ankle) - ground)
        else:
            rise = height(ankle) - ground
            ball = at(leg['toe']) if leg['toe'] else base + ahead * 1.2 * rise + up * .3 * rise
            reach = flat(ball - ankle).length
            heel, tip = base - ahead * .25 * reach, base + ahead * (flat(ball - ankle).length + .6 * reach)
        parts[f'{side} Foot'] = (ankle, ball, leg['foot'])
        parts[f'{side} Toe'] = (ball, tip, leg['toe'] or '')
        parts[f'{side} Heel'] = (heel, heel + ahead * .02 * legs, '')
    return dict(layout=layout(body), parts=parts)


def last(parts, stem, fallback):
    """The last part of a chain (Spine2 after Spine and Spine1), else fallback."""
    found = [key for key in parts if re.fullmatch(stem + r'\d*', key)]
    return max(found, key=lambda key: int(key[len(stem):] or 0)) if found else fallback


def parent_part(part, parts):
    """The figure part a part hangs from, as a Biped's parts hang."""
    side, name = part.split(' ', 1) if ' ' in part else ('', part)
    stem = name.rstrip('0123456789')
    number = int(name[len(stem):] or 0)
    if number:
        return stem + (str(number - 1) if number > 1 else '')
    chest = last(parts, 'Spine', 'Pelvis')
    above = {'Spine': 'Pelvis', 'Neck': chest, 'Head': last(parts, 'Neck', chest), 'Clavicle': chest,
             'UpperArm': f'{side} Clavicle' if f'{side} Clavicle' in parts else chest, 'Forearm': f'{side} UpperArm',
             'Hand': f'{side} Forearm', 'Thigh': 'Pelvis', 'Calf': f'{side} Thigh', 'Foot': f'{side} Calf',
             'Toe': f'{side} Foot', 'Heel': f'{side} Foot'}
    return above.get(stem)


def build(rig, data):
    """The figure as an armature object parented to the rig, its parts in the rig's armature space."""
    old = edited(rig)
    if old:
        bpy.data.objects.remove(old)
    armature = bpy.data.armatures.new(rig.name + ' Figure')
    obj = bpy.data.objects.new(rig.name + ' Figure', armature)
    (rig.users_collection[0] if rig.users_collection else bpy.context.scene.collection).objects.link(obj)
    obj.parent, obj.matrix_parent_inverse, obj.matrix_basis = rig, Matrix.Identity(4), Matrix.Identity(4)
    obj[OWNER] = rig
    obj.show_in_front = True
    armature.display_type = 'STICK'
    view = bpy.context.view_layer
    previous = view.objects.active
    for other in view.objects:
        other.select_set(False)
    view.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for part, (head, tail, link) in data['parts'].items():
            edit = armature.edit_bones.new(part)
            edit.head, edit.tail = Vector(head), Vector(tail)
            if (edit.tail - edit.head).length < 1e-5:
                edit.tail = edit.head + Vector((0, 0, .01))
            edit[PART], edit[LINK] = part, link or ''
        for part in data['parts']:
            parent = parent_part(part, data['parts'])
            if parent and parent in armature.edit_bones:
                armature.edit_bones[part].parent = armature.edit_bones[parent]
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    view.objects.active = previous if previous else obj
    return obj


def edited(rig):
    """The figure object being fitted to a rig, or None."""
    return next((obj for obj in bpy.data.objects if obj.type == 'ARMATURE' and obj.get(OWNER) == rig), None)


def read(obj, rig):
    """A figure object's parts and layout, in the rig's armature space."""
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    parts = {bone.name: (tuple(to_rig @ bone.head_local), tuple(to_rig @ bone.tail_local), bone.get(LINK, ''))
             for bone in obj.data.bones}
    for part, (head, tail, link) in parts.items():
        if link and link not in rig.data.bones:
            raise ValueError(f'Figure part {part} links to {link}, which {rig.name} does not have. Choose another bone.')
    for needed in ('Pelvis', 'L Thigh', 'R Thigh', 'L Calf', 'R Calf', 'L Foot', 'R Foot'):
        if not parts.get(needed, ('', '', ''))[2]:
            raise ValueError(f'Figure part {needed} needs a skeleton bone.')

    def links(prefix):
        return [parts[key][2] for key in sorted((key for key in parts if re.fullmatch(prefix + r'\d*', key)),
                                                key=lambda key: int(key[len(prefix):] or 0)) if parts[key][2]]
    given = dict(hips=parts['Pelvis'][2], spine=links('Spine'), neck=links('Neck'), head=parts.get('Head', ('', '', ''))[2] or None,
                 arms={}, legs={})
    for kind, names in LIMB_PARTS.items():
        for side in SIDES:
            limb = {part: parts.get(f'{side} {name}', ('', '', ''))[2] or None for name, part in names}
            if any(limb.values()):
                given[kind][side] = limb
    return dict(layout=given, parts=parts)


def save(rig, obj):
    """Keep the figure object's fit on the rig and in the figure folder; returns the file it wrote."""
    data = read(obj, rig)
    if matching.characterize(retarget.rig_bones(rig), data['layout']) is None:
        raise ValueError('The figure needs hips and two legs with knees linked to the skeleton.')
    data.update(version=VERSION, signature=signature(rig), rig=rig.name)
    text = json.dumps(data, indent=1)
    rig[KEY] = text
    path = folder()
    path.mkdir(parents=True, exist_ok=True)
    target = path / f'{label(rig)}_{data["signature"]}.json'
    for old in path.glob(f'*_{data["signature"]}.json'):
        if old != target:
            old.unlink()
    target.write_text(text, encoding='utf-8')
    return target


def saved(rig):
    """The figure saved for a rig's skeleton, on the rig or in the figure folder; None without one."""
    if rig is None:
        return None
    mark = signature(rig)
    try:
        data = json.loads(rig.get(KEY, '') or 'null')
    except ValueError:
        data = None
    if data and data.get('signature') == mark:
        return data
    path = folder()
    for item in sorted(path.glob(f'*_{mark}.json')) if path.is_dir() else ():
        try:
            data = json.loads(item.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if data.get('signature') == mark:
            return data
    return None


def forget(rig):
    """Remove the figure saved for a rig's skeleton from the rig and the figure folder; returns how many files went."""
    mark = signature(rig)
    rig.pop(KEY, None)
    path = folder()
    removed = 0
    for item in path.glob(f'*_{mark}.json') if path.is_dir() else ():
        item.unlink()
        removed += 1
    return removed


def measures(rig, data=None):
    """What the bake reads from a rig's figure (see the module), in the rig's armature units; None without a body.

    data is a saved figure; without it, the figure that Create figure would make. Points lie in the rig's armature
    space; pivots per side hold the heel, ankle, ball and toe tip, ground the height of the soles, and up the rig's
    up direction.
    """
    data = data or fit(rig)
    if data is None:
        return None
    parts = {part: (Vector(head), Vector(tail)) for part, (head, tail, link) in data['parts'].items()}
    up, forward = frame(rig)

    def length(*names):
        return sum((parts[name][1] - parts[name][0]).length for name in names if name in parts)
    hips = parts['Pelvis'][0]
    sides = [side for side in SIDES if f'{side} Foot' in parts]
    ankles = {side: parts[f'{side} Foot'][0] for side in sides}
    soles = {side: (parts[f'{side} Heel'][0].dot(up) + parts[f'{side} Toe'][1].dot(up)) / 2 for side in sides}
    ground = sum(soles.values()) / len(soles)
    top = parts['Head'][1].dot(up) if 'Head' in parts else max(head.dot(up) for head, tail in parts.values())
    neck = next((parts[name][0] for name in ('Neck', 'Head') if name in parts), parts['Pelvis'][1])
    pivots = {side: dict(heel=parts[f'{side} Heel'][0], ankle=ankles[side], ball=parts[f'{side} Toe'][0],
                         tip=parts[f'{side} Toe'][1]) for side in sides}
    feet = {side: (pivot['tip'] - pivot['heel'] - up * (pivot['tip'] - pivot['heel']).dot(up)).length for side, pivot in pivots.items()}
    return dict(layout=data['layout'], saved=data is not None and 'signature' in data, up=up, forward=forward,
                hips=hips, thighs={side: parts[f'{side} Thigh'][0] for side in sides if f'{side} Thigh' in parts},
                leg=sum((hips - ankle).length for ankle in ankles.values()) / len(ankles), ground=ground,
                height=top - ground, torso=(neck - hips).length,
                arms={side: length(f'{side} UpperArm', f'{side} Forearm') for side in SIDES if f'{side} UpperArm' in parts},
                legs={side: length(f'{side} Thigh', f'{side} Calf') for side in sides},
                pivots=pivots, feet=feet, soles=soles)
