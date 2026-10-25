"""Animator controls for bridge rigs: limb-aligned FK controls and IK arms and legs with an IK/FK switch.

An imported rig holds one short bone per game bone, oriented however the game
stores it. The control rig adds bones to the same armature: a root control, an
FK control per game bone that points along the limb, and for each arm and leg
an IK target, a pole target, a swivel ring and a two-bone IK chain. Every game
bone copies the world transform of a socket bone that hangs from its FK control
with the game bone's own rest matrix; an IK limb blends in a second socket on
its IK chain by the limb's IK/FK switch. The game bones keep their rest pose, so
character meshes and weapon sockets stay bound, and the exporter, which samples
the evaluated pose, writes whatever the controls do.

The swivel ring sits at the elbow or knee, around the line from the shoulder or
hip to the IK target. Turning it swings the joint around that line, on top of
where the pole puts it, while the hand or foot stays put, as when an arm clips
the body after a grip is adjusted.

Adding the rig bakes the active action onto the controls, FK and IK alike, so
the pose stays the same in either mode. The original action is kept; removing
the rig restores it or bakes the controls' motion back onto the game bones.
"""
import json
import math
import bpy
from mathutils import Matrix, Vector
from . import mapping, retarget

ROOT = 'CTRL-Root'
FK_CONSTRAINT, IK_CONSTRAINT, ROOT_CONSTRAINT, AIM_CONSTRAINT, HAND_CONSTRAINT = (
    'Control rig FK', 'Control rig IK', 'Control rig shoulder', 'Control rig IK solver', 'Control rig IK end')
# The swivel ring's frame: at the limb's root, aimed at the IK target, facing the pole, then moved to the joint.
SWIVEL_CONSTRAINTS = ('Control rig swivel root', 'Control rig swivel aim', 'Control rig swivel pole', 'Control rig swivel joint')
SWITCH = 'ik_fk'
# Bone collections and whether they start visible.
COLLECTIONS = (('Torso', True), ('FK limbs', True), ('IK limbs', True), ('Fingers & toes', True),
               ('Extras', False), ('Game bones', False), ('MCH', False))
COLORS = dict(L='THEME04', R='THEME01', C='THEME09', IK_L='THEME07', IK_R='THEME02', ROOT='THEME03', EXTRA='THEME13')
ARM, LEG = ('upperarm', 'forearm', 'hand'), ('thigh', 'calf', 'foot')
# The IK solver needs a bent chain to know which way to bend; lower IK bones start this far bent.
START_BEND = math.radians(15)


def _ring(count=32):
    return [(math.cos(2 * math.pi * i / count), 0.0, math.sin(2 * math.pi * i / count)) for i in range(count)]


def _loop(count, start=0):
    return [(start + i, start + (i + 1) % count) for i in range(count)]


_CUBE = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
# Wire meshes for custom shapes; rings lie across the bone (the bone's Y axis is their normal).
SHAPES = {
    'circle': (_ring(), _loop(32)),
    'box': (_CUBE, [(a, b) for a in range(8) for b in range(a + 1, 8)
                    if sum(p != q for p, q in zip(_CUBE[a], _CUBE[b])) == 1]),
    'square': ([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], _loop(4)),
    'diamond': ([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
                [(a, b) for a in range(6) for b in range(a + 1, 6) if a // 2 != b // 2]),
    'root': (_ring() + [(-.12, 0, 1.0), (0, 0, 1.3), (.12, 0, 1.0)], _loop(32) + [(32, 33), (33, 34)]),
    # A ring with an arrow on its -Z side, which points the way the elbow or knee bends.
    'swivel': (_ring() + [(-.15, 0, -1.0), (0, 0, -1.35), (.15, 0, -1.0)], _loop(32) + [(32, 33), (33, 34)]),
}


def is_control(bone):
    """True for a bone (Bone or EditBone) that the control rig added."""
    return 'sekiro_control' in bone


def present(rig):
    return bool(rig and rig.type == 'ARMATURE' and rig.get('sekiro_control_rig'))


def layout(rig):
    """What the control rig of a rig consists of, as recorded when it was added."""
    return json.loads(rig['sekiro_control_rig'])


def target(context):
    """The armature the control rig tools work on: the active armature, else the bridge's export rig."""
    obj = context.object
    if obj and obj.type == 'ARMATURE':
        return obj
    recorded = context.scene.get('sekiro_bridge_export_rig')
    if not isinstance(recorded, bpy.types.Object):
        recorded = bpy.data.objects.get(context.scene.get('sekiro_bridge_active_rig', ''))
    return recorded if recorded and recorded.type == 'ARMATURE' else None


def _unit(vector, fallback):
    return vector.normalized() if vector.length > 1e-9 else fallback.normalized()


def _flat(vector, axis):
    """vector without its component along the unit vector axis."""
    return vector - axis * vector.dot(axis)


def _across(vector):
    """Some unit vector perpendicular to vector."""
    return max((_flat(Vector(axis), vector.normalized()) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))),
               key=lambda v: v.length).normalized()


def _descends(rig, name, ancestor):
    return ancestor in {parent.name for parent in rig.data.bones[name].parent_recursive}


def _make_active(context, obj):
    if not obj.visible_get():
        raise ValueError('Show the armature in the viewport first.')
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _frames(action, scene):
    """Whole frames of an action's keyframe range, or the current frame for a rig without bone animation."""
    if action is None or not retarget.action_bones(action):
        return [scene.frame_current]
    start, end = action.frame_range
    return list(range(int(math.floor(start)), int(math.ceil(end)) + 1))


def _sample(context, rig, names, frames):
    """Armature-space matrices of the named bones at each frame."""
    scene, original = context.scene, context.scene.frame_current
    manager = context.window_manager
    manager.progress_begin(0, len(frames))
    samples = []
    try:
        for index, frame in enumerate(frames):
            scene.frame_set(frame)
            samples.append({name: rig.pose.bones[name].matrix.copy() for name in names})
            manager.progress_update(index)
    finally:
        manager.progress_end()
        scene.frame_set(original)
    return samples


def _hinge(rig, chain, samples, natural):
    """The axis an IK limb bends around, in armature space at rest, oriented so its natural bend is positive.

    A limb bent at rest has one axis normal to both segments. A straight one
    takes the axis its animation bends around, measured in the upper bone's own
    frame, or failing that the axis that swings the lower segment toward
    natural: forward for elbows, backward for knees.
    """
    bones = rig.data.bones
    upper, lower, end = chain
    s, e, w = (bones[name].head_local for name in chain)
    u, l = (e - s).normalized(), (w - e).normalized()
    reference = u.cross(natural)
    measured, rest = Vector(), bones[upper].matrix_local.to_quaternion()
    for matrices in samples:
        a = matrices[lower].translation - matrices[upper].translation
        b = matrices[end].translation - matrices[lower].translation
        if a.length < 1e-9 or b.length < 1e-9:
            continue
        normal = a.normalized().cross(b.normalized())
        if normal.length > .09:  # Bends under five degrees say little about the axis.
            turn = matrices[upper].to_quaternion() @ rest.inverted()
            measured += (turn.inverted() @ normal.normalized()) * normal.length
    if measured.length > 1e-6:
        reference = measured
    bent = u.cross(l)
    if bent.length > math.sin(math.radians(1)):
        axis = bent.normalized()
        return -axis if axis.dot(reference) < 0 else axis
    axis = _flat(reference, u)
    return axis.normalized() if axis.length > 1e-6 else _across(u)


def plan(rig, samples):
    """Bones to add, in creation order, and the limbs that get IK.

    Each specification names the bone, its parent (a planned or existing bone),
    and either a game bone to copy or a head, direction (y), length and Z axis.
    """
    bones = sorted((bone for bone in rig.data.bones if not is_control(bone)), key=lambda bone: len(bone.parent_recursive))
    head = {bone.name: bone.head_local.copy() for bone in bones}
    children = {}
    for bone in bones:
        children.setdefault(bone.parent.name if bone.parent else '', []).append(bone.name)
    body = mapping.Rig(retarget.rig_bones(rig, bones))
    roles = body.roles
    spine, neck = body.chain('spine'), body.chain('neck')
    role_of = {name: role for (side, role), name in roles.items()}
    side = {bone.name: body.bones[bone.name].side if bone.name in body.bones else '' for bone in bones}

    # Directions in armature space: up from the object, forward from the body.
    inverse = rig.matrix_world.to_3x3().inverted_safe()
    up = _unit(inverse @ Vector((0, 0, 1)), Vector((0, 0, 1)))
    default = _flat(inverse @ Vector((0, -1, 0)), up)
    default = default.normalized() if default.length > 1e-6 else _across(up)
    if body.body:
        forward = inverse @ Vector(body.body['forward'])
    else:
        pairs = [(roles[('L', role)], roles[('R', role)]) for role in ('clavicle', 'upperarm', 'thigh', 'hand', 'foot')
                 if ('L', role) in roles and ('R', role) in roles]
        forward = sum((head[a] - head[b] for a, b in pairs), Vector()).cross(up) if pairs else default
    forward = _unit(_flat(forward, up), default)
    left = up.cross(forward)
    hips = roles.get(('', 'hips'))
    feet = [roles[(s, 'foot')] for s in 'LR' if (s, 'foot') in roles]
    size = abs((head[hips] - sum((head[f] for f in feet), Vector()) / len(feet)).dot(up)) if hips and feet else 0.0
    if size < 1e-3:
        low = Vector([min(h[i] for h in head.values()) for i in range(3)])
        high = Vector([max(h[i] for h in head.values()) for i in range(3)])
        size = max((high - low).length / 2, 1e-3)
    shortest = .005 * size

    # Groups: the body's centre line with the bones carrying it, limbs, fingers and toes, extras.
    head_bone = roles.get(('', 'head'))
    centre = ([hips] if hips else []) + spine + neck + ([head_bone] if head_bone else [])
    torso = set(centre)
    for name in filter(None, (hips, spine[0] if spine else None)):
        torso.update(parent.name for parent in rig.data.bones[name].parent_recursive)
    clavicles = {roles[(s, 'clavicle')] for s in 'LR' if (s, 'clavicle') in roles}
    torso |= clavicles
    limb_bones = {roles[(s, r)] for s in 'LR' for r in ARM + LEG if (s, r) in roles} - torso
    digits = (set(body.fingers) | {roles[(s, 'toe')] for s in 'LR' if (s, 'toe') in roles}) - torso - limb_bones

    def group(name):
        return 'Torso' if name in torso else 'FK limbs' if name in limb_bones else 'Fingers & toes' if name in digits else 'Extras'

    # Each control points at the next joint along its limb, else at its largest child.
    toward = {}

    def link(a, b):
        if a and b and a not in toward:
            toward[a] = b
    for a, b in zip(centre, centre[1:]):
        link(a, b)
    for s in 'LR':
        for sequence in (('clavicle',) + ARM, LEG + ('toe',)):
            parts = [roles.get((s, role)) for role in sequence]
            for a, b in zip(parts, parts[1:]):
                link(a, b)
    digit = {(side[name], finger): name for name, finger in body.fingers.items()}
    for (s, (finger, segment)), name in digit.items():
        link(name, digit.get((s, (finger, segment + 1))))
    for s in 'LR':
        bases = sorted((finger != 2, segment, name) for (other, (finger, segment)), name in digit.items() if other == s)
        if bases:
            link(roles.get((s, 'hand')), bases[0][2])
    weight = {}
    for bone in reversed(bones):
        weight[bone.name] = 1 + sum(weight[child] for child in children.get(bone.name, ()))

    fk = {}
    for bone in bones:
        name = bone.name
        parent = fk.get(bone.parent.name) if bone.parent else None
        role = role_of.get(name)
        vector = None
        if name in toward and (head[toward[name]] - head[name]).length >= shortest:
            vector = head[toward[name]] - head[name]
        elif role != 'head':  # The head continues the neck; its largest child is usually a face bone in front.
            near = [child for child in children.get(name, ()) if (head[child] - head[name]).length >= shortest]
            if near:
                vector = head[max(near, key=lambda child: (weight[child], (head[child] - head[name]).length))] - head[name]
        if vector is not None:
            y, length = vector.normalized(), vector.length
        elif role == 'head':
            y, length = parent['y'] if parent else up, .12 * size
        elif role == 'toe':
            y = _unit(_flat(parent['y'], up), forward) if parent else forward
            length = max(.4 * parent['length'], 4 * shortest) if parent else .05 * size
        elif parent:
            y, length = parent['y'], min(max(.5 * parent['length'], 4 * shortest), .1 * size)
        else:
            y, length = up, .1 * size
        if name in torso and name not in clavicles:
            hint = forward
        elif role in ('clavicle',) + ARM:
            hint = -forward
        elif role in ('thigh', 'calf'):
            hint = forward
        elif role in ('foot', 'toe') or name in body.fingers:
            hint = up
        else:
            hint = parent['z'] if parent else forward
        z = _flat(hint, y)
        if z.length < .3:
            z = max((_flat(axis, y) for axis in (up, forward, left)), key=lambda v: v.length)
        fk[name] = dict(head=head[name], y=y, z=z.normalized(), length=length)

    # A control turned away from its game bone cannot carry scale that differs per axis (it would need
    # shear), so bones the clip scales unevenly, such as muscle helpers, get controls on their own axes.
    uneven = set()
    for bone in bones:
        parent = bone.parent
        for matrices in samples:
            keywords = dict(parent_matrix=matrices[parent.name], parent_matrix_local=parent.matrix_local) if parent else {}
            scale = bone.convert_local_to_pose(matrices[bone.name], bone.matrix_local, invert=True, **keywords).to_scale()
            if max(scale) - min(scale) > 1e-4 * max(scale):
                uneven.add(bone.name)
                break

    limbs = []
    for kind, parts in (('arm', ARM), ('leg', LEG)):
        for s in 'LR':
            chain = [roles.get((s, role)) for role in parts]
            if not all(chain) or not _descends(rig, chain[1], chain[0]) or not _descends(rig, chain[2], chain[1]):
                continue
            a, b, c = (head[name] for name in chain)
            if min((b - a).length, (c - b).length) < 4 * shortest:
                continue
            u, l = (b - a).normalized(), (c - b).normalized()
            axis = _hinge(rig, chain, samples, forward if kind == 'arm' else -forward)
            x_upper, x_lower = _unit(_flat(axis, u), axis), _unit(_flat(axis, l), axis)
            elbow = -x_upper.cross(u)  # The side the elbow or knee points to.
            reach = (b - a).length + (c - b).length
            if kind == 'arm':
                end = dict(fk[chain[2]])
            else:
                toe = roles.get((s, 'toe'))
                step = _flat(head[toe] - c, up) if toe else Vector()
                end = dict(head=c, y=_unit(step, forward), z=up,
                           length=step.length if step.length > 4 * shortest else .15 * size)
            ground = min(head[name].dot(up) for name in chain + ([roles[(s, 'toe')]] if (s, 'toe') in roles else []))
            limbs.append(dict(kind=kind, side=s, label=('Left ' if s == 'L' else 'Right ') + kind, bones=chain,
                              upper=dict(head=a, y=u, z=x_upper.cross(u), length=(b - a).length),
                              lower=dict(head=b, y=l, z=x_lower.cross(l), length=(c - b).length), end=end,
                              bend=math.atan2(u.cross(l).dot(axis), u.dot(l)), elbow=elbow,
                              distance=.5 * reach, ankle=c.dot(up) - ground))

    driven = {name for limb in limbs for name in limb['bones']}
    specs = [dict(name=ROOT, kind='root', head=Vector(), y=up, z=forward, length=.25 * size, group='Torso', color='ROOT',
                  drives=[bone.name for bone in bones if not bone.parent],
                  shape=('root', (.55 * size,) * 3, (0, 0, 0)))]
    radius = dict(clavicle=.045, upperarm=.055, forearm=.045, hand=.04, thigh=.075, calf=.06, foot=.045, toe=.035)
    for bone in bones:
        name, info = bone.name, fk[bone.name]
        parent = bone.parent.name if bone.parent else None
        if parent is None:
            control_parent = ROOT
        elif parent in driven and name not in driven:
            control_parent = parent  # Follows the game bone, which blends FK and IK.
        else:
            control_parent = 'FK-' + parent
        role = role_of.get(name)
        if name in torso and name not in centre and name not in clavicles:
            depth = sum(1 for p in bone.parent_recursive if p.name in torso)
            shape = ('circle', ((.42 - .05 * min(depth, 4)) * size,) * 3, (0, 0, 0))
        elif name == hips:
            shape = ('circle', (.22 * size,) * 3, (0, 0, 0))
        else:
            scale = (.17 if name in spine else .07 if name in neck else .11 if name == head_bone else radius.get(role)
                     or (.012 if name in body.fingers else .02))
            shape = ('circle', (scale * size,) * 3, (0, 0 if name in uneven else .5 * info['length'], 0))
        kind = group(name)
        frame = dict(copy=name) if name in uneven else dict(head=info['head'], y=info['y'], z=info['z'])
        specs.append(dict(name='FK-' + name, kind='fk', parent=control_parent, length=info['length'], group=kind,
                          drives=[name], shape=shape, color='EXTRA' if kind == 'Extras' else side[name] or 'C', **frame))
        specs.append(dict(name='MCH-FK-' + name, kind='socket', parent='FK-' + name, copy=name, group='MCH'))
    for limb in limbs:
        upper, lower, end = limb['bones']
        parent = rig.data.bones[upper].parent
        tint = 'IK_' + limb['side']
        hand = limb['end']
        if limb['kind'] == 'arm':
            shape = ('box', (.03 * size, .5 * hand['length'] + .01 * size, .05 * size), (0, .5 * hand['length'], 0))
        else:
            length = hand['length']
            shape = ('square', (.45 * length, .825 * length, 1), (0, .475 * length, -limb['ankle']))
        elbow = limb['elbow']
        pole_z = _flat(up, elbow)
        line = _unit(head[end] - head[upper], limb['upper']['y'])
        bend_side = _flat(elbow, line)
        bend_side = bend_side.normalized() if bend_side.length > 1e-6 else _across(line)
        ring = (.07 if limb['kind'] == 'arm' else .09) * size
        specs += [
            dict(name='IK-' + end, kind='ik', parent=ROOT, group='IK limbs', color=tint, drives=list(limb['bones']),
                 shape=shape, **hand),
            dict(name='Pole-' + lower, kind='pole', parent=ROOT, head=head[lower] + elbow * limb['distance'], y=elbow,
                 z=pole_z.normalized() if pole_z.length > .3 else _across(elbow), length=.05 * size, group='IK limbs',
                 color=tint, drives=[upper, lower], shape=('diamond', (.035 * size,) * 3, (0, 0, 0))),
            # Constraints keep the frame on the line from the shoulder or hip to the IK target; the ring turns in it.
            dict(name='MCH-Swivel-' + lower, kind='swivel_frame', parent=ROOT, head=head[lower], y=line, z=-bend_side,
                 length=.05 * size, group='MCH'),
            dict(name='Swivel-' + lower, kind='swivel', parent='MCH-Swivel-' + lower, head=head[lower], y=line,
                 z=-bend_side, length=.05 * size, group='IK limbs', color=tint, drives=[upper, lower],
                 shape=('swivel', (ring,) * 3, (0, 0, 0))),
            dict(name='MCH-IK-' + upper, kind='chain', parent='FK-' + parent.name if parent else ROOT, group='MCH',
                 **limb['upper']),
            dict(name='MCH-IK-' + lower, kind='chain', parent='MCH-IK-' + upper, connect=True, group='MCH', **limb['lower']),
            dict(name='MCH-IK-' + end, kind='chain', parent='MCH-IK-' + lower, connect=True, group='MCH', **hand),
        ]
        specs += [dict(name='MCH-IKS-' + name, kind='ik_socket', parent='MCH-IK-' + name, copy=name, group='MCH')
                  for name in limb['bones']]
    return specs, limbs


def _widgets(rig):
    """Wire meshes for the custom shapes, in a hidden collection beside the rig."""
    collection = bpy.data.collections.new('Widgets - ' + rig.name)
    (rig.users_collection[0] if rig.users_collection else bpy.context.scene.collection).children.link(collection)
    collection.hide_viewport = collection.hide_render = True
    shapes = {}
    for kind, (vertices, edges) in SHAPES.items():
        mesh = bpy.data.meshes.new('WGT-' + rig.name + '-' + kind)
        mesh.from_pydata(vertices, edges, [])
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj['sekiro_control_widget'] = True
        collection.objects.link(obj)
        shapes[kind] = obj
    return collection, shapes


def _build(context, rig, specs):
    """Create the planned bones in edit mode; returns planned name -> actual name."""
    _make_active(context, rig)
    bpy.ops.object.mode_set(mode='EDIT')
    edit = rig.data.edit_bones
    names = {}
    try:
        for spec in specs:
            bone = edit.new(spec['name'])
            names[spec['name']] = bone.name
            if 'copy' in spec:
                source = edit[spec['copy']]
                bone.head, bone.tail, bone.roll = source.head.copy(), source.tail.copy(), source.roll
                if 'length' in spec:
                    bone.length = spec['length']  # Along the same axis, so the bone keeps the copied frame.
            else:
                bone.head = spec['head']
                bone.tail = spec['head'] + spec['y'] * spec['length']
                bone.align_roll(spec['z'])
            if spec.get('parent'):
                bone.parent = edit[names.get(spec['parent'], spec['parent'])]
            bone.use_connect = spec.get('connect', False)
            bone.use_deform = False
            bone['sekiro_control'] = spec['kind']
            if spec.get('drives'):
                bone['sekiro_control_for'] = json.dumps(spec['drives'])
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return names


def _driver(rig, constraint, control):
    curve = constraint.driver_add('influence')
    driver = curve.driver
    driver.type = 'AVERAGE'
    variable = driver.variables.new()
    variable.name, variable.type = 'switch', 'SINGLE_PROP'
    variable.targets[0].id_type = 'OBJECT'
    variable.targets[0].id = rig
    variable.targets[0].data_path = 'pose.bones["{}"]["{}"]'.format(bpy.utils.escape_identifier(control), SWITCH)


def _swivel_driver(rig, constraint, ring):
    """Drive an IK constraint's pole angle by the swivel ring's turn about its Y axis.

    The driver reads the ring's rotation property, not its evaluated transform,
    which follows the IK chain, so the dependency has no cycle. Its expression
    is a simple one, which Blender evaluates without running Python.
    """
    driver = constraint.driver_add('pole_angle').driver
    driver.type = 'SCRIPTED'
    variable = driver.variables.new()
    variable.name, variable.type = 'swivel', 'SINGLE_PROP'
    variable.targets[0].id_type = 'OBJECT'
    variable.targets[0].id = rig
    variable.targets[0].data_path = 'pose.bones["{}"].rotation_euler[1]'.format(bpy.utils.escape_identifier(ring))
    driver.expression = '-pi / 2 + swivel'  # A positive turn swings the joint the way the ring's arrow turns.


def _rest_on(socket, game):
    """Pose a socket so that it sits exactly at its game bone's rest relative to the socket's parent.

    A copied bone does not always rest exactly where the original does: Blender
    derives rest matrices through each parent, and a bone lying almost along
    its parent's -Y axis snaps onto it, by up to about 0.015 degrees.
    """
    location, rotation, scale = (socket.bone.matrix_local.inverted() @ game.matrix_local).decompose()
    socket.rotation_mode = 'QUATERNION'
    socket.location, socket.rotation_quaternion, socket.scale = location, rotation, scale


def _constraint(bone, kind, name, rig, subtarget, **settings):
    constraint = bone.constraints.new(kind)
    constraint.name, constraint.target, constraint.subtarget = name, rig, subtarget
    for key, value in settings.items():
        setattr(constraint, key, value)
    return constraint


def _setup(rig, specs, limbs, names):
    """Collections, colours, shapes, constraints and drivers for freshly built bones; returns the layout."""
    bones, pose = rig.data.bones, rig.pose.bones
    collections = {}
    for title, visible in COLLECTIONS:
        collection = rig.data.collections.new(title)
        collection.is_visible = visible
        collections[title] = collection
    widget_collection, shapes = _widgets(rig)
    game = [bone.name for bone in sorted((b for b in bones if not is_control(b)), key=lambda b: len(b.parent_recursive))]
    for name in game:
        collections['Game bones'].assign(bones[name])
    for spec in specs:
        name = names[spec['name']]
        collections[spec['group']].assign(bones[name])
        if spec.get('color'):
            bones[name].color.palette = COLORS[spec['color']]
        if spec.get('shape'):
            kind, scale, offset = spec['shape']
            bone = pose[name]
            bone.custom_shape = shapes[kind]
            bone.use_custom_shape_bone_size = False
            bone.custom_shape_scale_xyz = scale
            bone.custom_shape_translation = offset
            if hasattr(bone, 'custom_shape_wire_width') and spec['group'] != 'Extras':
                bone.custom_shape_wire_width = 2.0
    for name in game:
        _rest_on(pose[names['MCH-FK-' + name]], bones[name])
        _constraint(pose[name], 'COPY_TRANSFORMS', FK_CONSTRAINT, rig, names['MCH-FK-' + name])
    recorded = []
    for limb in limbs:
        upper, lower, end = limb['bones']
        control, pole = names['IK-' + end], names['Pole-' + lower]
        chain = [names['MCH-IK-' + name] for name in limb['bones']]
        sockets = [names['MCH-IKS-' + name] for name in limb['bones']]
        pose[control][SWITCH] = 0.0
        pose[control].id_properties_ui(SWITCH).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                                                      description='0 follows the FK controls, 1 the IK controls')
        pose[pole].lock_rotation = pose[pole].lock_scale = (True, True, True)
        pose[pole].lock_rotation_w = True
        # The chain starts where the FK upper bone is, which carries any translation the clip gives it.
        _constraint(pose[chain[0]], 'COPY_LOCATION', ROOT_CONSTRAINT, rig, names['FK-' + upper])
        solver = pose[chain[1]]
        solver.lock_ik_y = solver.lock_ik_z = True
        solver.use_ik_limit_x = True
        solver.ik_min_x, solver.ik_max_x = min(0.0, -limb['bend']), max(0.0, math.pi - limb['bend'] - 1e-3)
        solver.rotation_mode = 'QUATERNION'
        solver.rotation_quaternion = Matrix.Rotation(max(0.0, START_BEND - limb['bend']), 4, 'X').to_quaternion()
        # With pole_angle -90 degrees the chain's -Z axis, the elbow side, turns toward the pole.
        ik = _constraint(solver, 'IK', AIM_CONSTRAINT, rig, control, pole_target=rig, pole_subtarget=pole,
                         pole_angle=-math.pi / 2, chain_count=2, use_tail=True, use_stretch=False)
        _constraint(pose[chain[2]], 'COPY_ROTATION', HAND_CONSTRAINT, rig, control)
        for name, socket in zip(limb['bones'], sockets):
            _rest_on(pose[socket], bones[name])
            _driver(rig, _constraint(pose[name], 'COPY_TRANSFORMS', IK_CONSTRAINT, rig, socket), control)
        # The ring's frame runs along the line from the chain's root to the IK target, its -Z axis toward the pole
        # (and so toward the joint, at a zero swivel), and sits at the joint. A turn about that line, which the
        # ring keys as its Y rotation, adds to the pole angle.
        frame, swivel = names['MCH-Swivel-' + lower], names['Swivel-' + lower]
        root, aim, facing, joint = SWIVEL_CONSTRAINTS
        _constraint(pose[frame], 'COPY_LOCATION', root, rig, chain[0])
        _constraint(pose[frame], 'DAMPED_TRACK', aim, rig, control, track_axis='TRACK_Y')
        _constraint(pose[frame], 'LOCKED_TRACK', facing, rig, pole, lock_axis='LOCK_Y', track_axis='TRACK_NEGATIVE_Z')
        _constraint(pose[frame], 'COPY_LOCATION', joint, rig, chain[1])
        ring = pose[swivel]
        ring.rotation_mode = 'XYZ'
        ring.lock_location = ring.lock_scale = (True, True, True)
        ring.lock_rotation = (True, False, True)
        _swivel_driver(rig, ik, swivel)
        recorded.append(dict(label=limb['label'], kind=limb['kind'], side=limb['side'], bones=limb['bones'],
                             chain=chain, sockets=sockets, control=control, pole=pole, swivel=swivel,
                             swivel_frame=frame, elbow=list(limb['elbow']), distance=limb['distance']))
    return dict(version=1, root=names[ROOT], order=game, fk={name: names['FK-' + name] for name in game},
                sockets={name: names['MCH-FK-' + name] for name in game}, limbs=recorded,
                bones=sorted(names.values()), collections=[c.name for c in collections.values()],
                widgets=[obj.name for obj in shapes.values()], widget_collection=widget_collection.name)


def _pole(rig, limb, matrices):
    """Where a pole target puts the elbow or knee as it is in the given pose.

    The pole lies on the elbow's side of the shoulder-to-wrist line. A nearly
    straight limb has no such side; there the rest elbow side, turned with the
    upper bone, decides, so the upper bone keeps its twist.
    """
    upper, lower, end = limb['bones']
    s, e, w = (matrices[name].translation for name in limb['bones'])
    line = _unit(w - s, e - s)
    offset = _flat(e - s, line)
    turn = matrices[upper].to_quaternion() @ rig.data.bones[upper].matrix_local.to_quaternion().inverted()
    fallback = _flat(turn @ Vector(limb['elbow']), line)
    fallback = fallback.normalized() if fallback.length > 1e-9 else _across(line)
    bend = _unit(e - s, line).cross(_unit(w - e, line)).length
    weight = min(1.0, max(0.0, (bend - .01) / .04))
    direction = (offset.normalized() if offset.length > 1e-9 else fallback) * weight + fallback * (1 - weight)
    return e + _unit(direction, fallback) * limb['distance']


def _worlds(rig, data, matrices, games=(), limbs=()):
    """Armature-space matrices of FK controls (of the named game bones) and IK controls that reproduce a pose."""
    bones = rig.data.bones
    worlds = {}
    for name in games:
        control = data['fk'][name]
        worlds[control] = matrices[name] @ bones[name].matrix_local.inverted() @ bones[control].matrix_local
    for limb in limbs:
        end = limb['bones'][2]
        control, pole = bones[limb['control']], bones[limb['pole']]
        worlds[control.name] = matrices[end] @ bones[end].matrix_local.inverted() @ control.matrix_local
        worlds[pole.name] = Matrix.Translation(_pole(rig, limb, matrices)) @ pole.matrix_local.to_3x3().to_4x4()
    return worlds


def _local(rig, name, worlds, known):
    """matrix_basis that gives a control the armature-space matrix worlds[name]."""
    bone = rig.data.bones[name]
    parent = bone.parent
    if parent is None:
        return bone.convert_local_to_pose(worlds[name], bone.matrix_local, invert=True)
    parent_matrix = worlds[parent.name] if parent.name in worlds else known[parent.name]
    return bone.convert_local_to_pose(worlds[name], bone.matrix_local, parent_matrix=parent_matrix,
                                      parent_matrix_local=parent.matrix_local, invert=True)


def _poses(rig, data, samples, games=(), limbs=()):
    """matrix_basis per frame of the controls that reproduce sampled poses (see _worlds). The limbs' swivel rings
    turn back to zero, since the poles alone place the elbows and knees."""
    poses = {}
    for known in samples:
        worlds = _worlds(rig, data, known, games, limbs)
        for name in worlds:
            poses.setdefault(name, []).append(_local(rig, name, worlds, known))
        for limb in limbs:
            if limb.get('swivel'):  # Control rigs added before swivel rings existed have none.
                poses.setdefault(limb['swivel'], []).append(Matrix())
    return poses


def _curves(rig, action):
    """Where the rig's F-curves in an action live: its slot's channel bag (Blender 4.4+) or the action itself."""
    if not hasattr(action, 'slots'):
        return action
    data = rig.animation_data
    slot = data.action_slot if data and data.action == action else None
    if slot is None:
        slot = next((s for s in action.slots if s.identifier == 'OB' + rig.name), None) or action.slots.new('OBJECT', rig.name)
    layer = action.layers[0] if action.layers else action.layers.new('Layer')
    strip = layer.strips[0] if layer.strips else layer.strips.new(type='KEYFRAME')
    return strip.channelbag(slot, ensure=True)


def _new_action(rig, name, base):
    """A new action for the rig, assigned to it; base is the action it was made from."""
    action = bpy.data.actions.new(name)
    if hasattr(action, 'slots'):
        action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(action.slots.new('OBJECT', rig.name), ensure=True)
    if base is not None:
        action['sekiro_control_rig_base'] = base
    retarget.assign_action(rig, action)
    return action


def _write(bag, path, group, frames, samples):
    """Key each component of samples at frames, replacing keys already there."""
    for axis in range(len(samples[0])):
        curve = bag.fcurves.find(path, index=axis)
        if curve is None:
            curve = bag.fcurves.new(path, index=axis)
            curve.group = group
        if len(curve.keyframe_points):
            # Without options, insert replaces a key on the frame or adds one; 'REPLACE' would only replace.
            for frame, sample in zip(frames, samples):
                curve.keyframe_points.insert(frame, sample[axis], options={'FAST'}).interpolation = 'LINEAR'
        else:
            curve.keyframe_points.add(len(frames))
            curve.keyframe_points.foreach_set('co', [v for f, s in zip(frames, samples) for v in (float(f), float(s[axis]))])
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        curve.update()


def _apply(rig, poses, frames, base=None, keyed=()):
    """Key the channels of each bone that change over the frames; set the others once.

    poses maps a bone to its matrix_basis per frame. A channel that is already
    animated is keyed even when it holds still, and so is the rotation of a bone
    in keyed, such as a swivel ring, so that turning it on one frame changes that
    frame only and Adjust over frames can spread it. A rig without an action gets
    one when anything moves.
    """
    data = rig.animation_data
    action = data.action if data else None
    bag = _curves(rig, action) if action else None
    animated = {curve.data_path for curve in bag.fcurves} if bag else set()
    for name, matrices in poses.items():
        bone = rig.pose.bones[name]
        mode = bone.rotation_mode
        if mode == 'AXIS_ANGLE':
            bone.rotation_mode = mode = 'QUATERNION'
        rotation_field = 'rotation_quaternion' if mode == 'QUATERNION' else 'rotation_euler'
        values, previous = [], None
        for matrix in matrices:
            location, rotation, scale = matrix.decompose()
            if mode == 'QUATERNION':
                if previous is not None and rotation.dot(previous) < 0:
                    rotation.negate()
                previous = rotation
            else:
                rotation = rotation.to_euler(mode, previous) if previous is not None else rotation.to_euler(mode)
                previous = rotation
            values.append((tuple(location), tuple(rotation), tuple(scale)))
        for index, field in enumerate(('location', rotation_field, 'scale')):
            samples = [value[index] for value in values]
            path = bone.path_from_id(field)
            moves = any(abs(a - b) > 1e-6 for sample in samples for a, b in zip(sample, samples[0]))
            if moves and bag is None:
                action = _new_action(rig, rig.name + ' Controls', base)
                bag = _curves(rig, action)
            if bag is not None and (moves or path in animated or (index == 1 and name in keyed)):
                group = bag.groups.get(name) or bag.groups.new(name)
                _write(bag, path, group, frames, samples)
            else:
                setattr(bone, field, samples[0])


def add(context, rig):
    """Add the control rig to a rig and bake its action onto the controls. Returns a summary."""
    if rig is None or rig.type != 'ARMATURE':
        raise ValueError('Select the armature to add the control rig to.')
    if present(rig) or any(is_control(bone) for bone in rig.data.bones):
        raise ValueError('This armature already has a control rig.')
    if rig.library or rig.data.library:
        raise ValueError('The armature is linked from another file. Make it local first.')
    data = rig.animation_data
    if data and any(not track.mute for track in data.nla_tracks):
        raise ValueError('Mute the NLA tracks of this armature first, so its action alone gives the motion to bake.')
    action = data.action if data else None
    frames = _frames(action, context.scene)
    game = [bone.name for bone in rig.data.bones]
    samples = _sample(context, rig, game, frames)
    specs, limbs = plan(rig, samples)
    names = _build(context, rig, specs)
    record = _setup(rig, specs, limbs, names)
    if action is not None:
        action.use_fake_user = True  # The original clip stays and comes back when the rig is removed.
        rig['sekiro_control_rig_action'] = action
        _new_action(rig, action.name + ' Controls', action)['sekiro_control_rig'] = True
    root = rig.data.bones[record['root']]
    for known in samples:
        known[root.name] = root.matrix_local
    _apply(rig, _poses(rig, record, samples, record['order'], record['limbs']), frames, action,
           {limb['swivel'] for limb in record['limbs']})
    record['in_front'] = rig.show_in_front
    rig.show_in_front = True  # Most controls lie inside the character's mesh.
    rig['sekiro_control_rig'] = json.dumps(record)
    context.scene.frame_set(context.scene.frame_current)
    bpy.ops.object.mode_set(mode='POSE')
    return dict(controls=len(record['order']) + 1 + 3 * len(record['limbs']), limbs=[limb['label'] for limb in record['limbs']],
                frames=len(frames) if action is not None else 0)


def switch(context, rig, index, mode, every_frame=True):
    """Match one limb's IK (or FK) controls to its current pose, then switch the limb to IK (or FK).

    With every_frame, the controls are matched at every frame of the scene
    range, so the whole animation looks the same after the switch; otherwise at
    the current frame only. Matching the IK controls turns the swivel ring back
    to zero, as the pole then places the elbow or knee where it is.
    """
    data = layout(rig)
    limb = data['limbs'][index]
    scene = context.scene
    frames = list(range(scene.frame_start, scene.frame_end + 1)) if every_frame else [scene.frame_current]
    if mode == 'IK':
        targets, games, limbs = [limb['control'], limb['pole']], (), [limb]
    else:
        games, limbs = limb['bones'], ()
        targets = [data['fk'][name] for name in games]
    parents = {rig.data.bones[name].parent.name for name in targets if rig.data.bones[name].parent} - set(targets)
    context.view_layer.update()
    samples = _sample(context, rig, list(limb['bones']) + sorted(parents), frames)
    _apply(rig, _poses(rig, data, samples, games, limbs), frames, rig.get('sekiro_control_rig_action'),
           {limb['swivel']} if limb.get('swivel') else ())
    control = rig.pose.bones[limb['control']]
    control[SWITCH] = 1.0 if mode == 'IK' else 0.0
    rig.update_tag()  # Setting a custom property alone does not re-evaluate the drivers that read it.
    action = rig.animation_data.action if rig.animation_data else None
    path = control.path_from_id('["{}"]'.format(SWITCH))
    if action is not None:
        bag = _curves(rig, action)
        if bag.fcurves.find(path) is not None:
            _write(bag, path, bag.groups.get(control.name) or bag.groups.new(control.name), frames,
                   [(control[SWITCH],)] * len(frames))
    scene.frame_set(scene.frame_current)
    return len(frames)


def remove(context, rig, keep_edits=True):
    """Remove the control rig. keep_edits bakes the controls' motion onto the game bones; otherwise the
    action from before the control rig comes back. Returns the action the rig is left with."""
    data = layout(rig)
    scene = context.scene
    base = rig.get('sekiro_control_rig_action')
    base = base if isinstance(base, bpy.types.Action) else None
    current = rig.animation_data.action if rig.animation_data else None
    game = [name for name in data['order'] if name in rig.data.bones]
    if keep_edits:
        frames = _frames(current, scene)
        samples = _sample(context, rig, game, frames)
    for name in game:
        bone = rig.pose.bones[name]
        for constraint in list(bone.constraints):
            if constraint.name in (FK_CONSTRAINT, IK_CONSTRAINT):
                constraint.driver_remove('influence')
                bone.constraints.remove(constraint)
    for limb in data['limbs']:
        solver = rig.pose.bones.get(limb['chain'][1])
        constraint = solver.constraints.get(AIM_CONSTRAINT) if solver else None
        if constraint:
            constraint.driver_remove('pole_angle')  # A driver stays behind when the bone it drives is deleted.
    _make_active(context, rig)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = rig.data.edit_bones
        for bone in [bone for bone in edit if is_control(bone)]:
            edit.remove(bone)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    for name in data['collections']:
        collection = rig.data.collections.get(name)
        if collection:
            rig.data.collections.remove(collection)
    for name in data['widgets']:
        obj = bpy.data.objects.get(name)
        if obj and obj.get('sekiro_control_widget'):
            mesh = obj.data
            bpy.data.objects.remove(obj)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    collection = bpy.data.collections.get(data['widget_collection'])
    if collection and not collection.all_objects:
        bpy.data.collections.remove(collection)
    for key in ('sekiro_control_rig', 'sekiro_control_rig_action'):
        if key in rig:
            del rig[key]
    rig.show_in_front = data.get('in_front', rig.show_in_front)
    if keep_edits:
        bones = rig.data.bones
        poses = {}
        for known in samples:
            for name in game:
                bone = bones[name]
                keywords = dict(parent_matrix=known[bone.parent.name], parent_matrix_local=bone.parent.matrix_local) if bone.parent else {}
                poses.setdefault(name, []).append(bone.convert_local_to_pose(known[name], bone.matrix_local, invert=True, **keywords))
        if current is not None:
            _new_action(rig, (base or current).name + ' Edited', base)
        _apply(rig, poses, frames, base)
    else:
        retarget.assign_action(rig, base)
    if current is not None and current.get('sekiro_control_rig') and current.users == 0:
        bpy.data.actions.remove(current)  # The controls it animated are gone.
    scene.frame_set(scene.frame_current)
    return rig.animation_data.action if rig.animation_data else None
