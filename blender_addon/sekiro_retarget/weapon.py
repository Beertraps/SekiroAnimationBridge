"""Add a weapon to an armature: meshes placed in a hand become the mesh of a new weapon bone.

Place the weapon's meshes where the hand should hold them, on any frame, select them and add the weapon. The armature
gets a new bone under the hand, such as R_Weapon, and every chosen mesh is bound to it with an Armature modifier, so
the weapon stays where it was placed on that frame and follows the hand on every frame. To the character export
(docs/CHARACTER_EXPORT_PLAN.md) it is a mesh of the armature like any other, and to the bake a weapon bone.

The bone starts at the weapon's grip, the point of its long axis nearest the hand, and points along that axis to the
end farther from the hand, as a blade or a barrel goes; its roll follows the hand's. A mesh keeps the shape it shows:
its modifiers and shape keys are applied, and its vertex groups, parent and constraints give way to the new bone. An
object animation of its own stops playing, since the bone moves the mesh now.
"""
import bpy
import numpy as np
from mathutils import Matrix, Vector
from . import control_rig, figure, mapping, mirror, retarget

HANDS = {'LEFT': 'L', 'RIGHT': 'R'}
LENGTH = .05  # The shortest weapon bone, in the armature's units: a weapon's length along its long axis, or this.


def target(context):
    """The armature to arm: the active armature, else a selected one, else the armature the active object hangs
    from, else the bridge's export rig."""
    def armature(obj):
        return obj is not None and obj.type == 'ARMATURE' and not obj.get(figure.OWNER) and not obj.get('sekiro_weapon_rig')
    if armature(context.object):
        return context.object
    found = next((obj for obj in context.selected_objects if armature(obj)), None)
    parent = context.object.parent if context.object else None
    while found is None and parent is not None:
        found, parent = (parent if armature(parent) else None), parent.parent
    return found or control_rig.target(context)


def meshes(context, rig):
    """The selected meshes that become the weapon: those not yet bound to the armature."""
    if rig is None:
        return []
    return [obj for obj in context.selected_objects if obj.type == 'MESH' and not obj.get(figure.OWNER)
            and not any(m.type == 'ARMATURE' and m.object == rig for m in obj.modifiers)]


def hands(rig):
    """{'L': bone, 'R': bone}: the hands that the bone matcher finds in the armature."""
    anatomy = mapping.anatomy(retarget.rig_bones(rig))
    return {side: anatomy[(side, 'hand')] for side in ('L', 'R') if anatomy.get((side, 'hand'))}


def holder(rig, hand, bone=''):
    """(bone, side) that holds the weapon: a hand, or any bone of the armature, with its side for the weapon's name."""
    if hand == 'BONE':
        if bone not in rig.data.bones:
            raise ValueError('Choose the bone that holds the weapon under Bone.')
        return bone, next((side for side, name in hands(rig).items() if name == bone), '')
    found = hands(rig).get(HANDS[hand])
    if not found:
        raise ValueError(f'The bone matcher finds no {hand.lower()} hand in {rig.name}. Choose Bone and the hand\'s bone.')
    return found, HANDS[hand]


def free_name(rig, side):
    """R_Weapon, L_Weapon or Weapon, numbered from 2 where the armature has that bone already."""
    stem = f'{side}_Weapon' if side else 'Weapon'
    name, number = stem, 2
    while name in rig.data.bones:
        name, number = f'{stem}{number}', number + 1
    return name


def default_name(rig, hand, bone=''):
    """The name a weapon gets without one of its own, or '' where its holder is not found."""
    try:
        return free_name(rig, holder(rig, hand, bone)[1])
    except ValueError:
        return ''


def grip(points, bone):
    """Head and tail of the weapon bone in the armature's space, for the weapon's points there and its holder bone:
    from the point of the weapon's long axis nearest the holder's head to the farther end of that axis."""
    centre = points.mean(axis=0)
    if len(points) < 2 or np.ptp(points, axis=0).max() < 1e-6:
        axis = np.array(bone.matrix_local.col[1][:3])
        return Vector(centre), Vector(centre + axis * LENGTH * 2)
    axis = np.linalg.svd(points - centre, full_matrices=False)[2][0]
    along = (points - centre) @ axis
    low, high = float(along.min()), float(along.max())
    at = min(max(float((np.array(bone.head_local) - centre) @ axis), low), high)
    far = high if high - at >= at - low else low
    head = centre + axis * at
    return Vector(head), Vector(head + axis * (far - at if abs(far - at) >= LENGTH else LENGTH * (1 if far >= at else -1)))


def add(context, rig, objects, hand, bone='', name=''):
    """Make objects, placed where the holder should hold them on the current frame, the meshes of a new bone under it.

    Each vertex goes from where it shows now to where it sits when the holder rests, so that the bone, at rest under
    its holder, puts it back where it was on this frame. Returns a result for summary().
    """
    if not objects:
        raise ValueError("Select the weapon's meshes.")
    holder_name, side = holder(rig, hand, bone)
    name = name.strip() or free_name(rig, side)
    if name in rig.data.bones:
        raise ValueError(f'{rig.name} has a bone named {name} already. Choose another name.')
    if context.object is not None and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    depsgraph = context.evaluated_depsgraph_get()
    rest = rig.matrix_world @ rig.data.bones[holder_name].matrix_local
    pose = rig.matrix_world @ rig.pose.bones[holder_name].matrix
    back = rig.matrix_world.inverted() @ rest @ pose.inverted()
    notes, points = [], []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        world = evaluated.matrix_world.copy()
        if obj.modifiers or obj.data.shape_keys is not None:
            if obj.modifiers:
                notes.append(f'{obj.name}: its modifiers were applied.')
            obj.data = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
            obj.modifiers.clear()
        elif obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.transform(back @ world)
        obj.constraints.clear()
        if obj.animation_data and obj.animation_data.action:
            notes.append(f'{obj.name}: its own animation, {obj.animation_data.action.name}, no longer plays.')
            obj.animation_data.action = None
        obj.parent, obj.parent_type = rig, 'OBJECT'
        obj.matrix_parent_inverse, obj.matrix_basis = Matrix(), Matrix()
        obj.vertex_groups.clear()
        obj.vertex_groups.new(name=name).add(range(len(obj.data.vertices)), 1.0, 'REPLACE')
        obj.modifiers.new('Armature', 'ARMATURE').object = rig
        cloud = np.empty(len(obj.data.vertices) * 3)
        obj.data.vertices.foreach_get('co', cloud)
        points.append(cloud.reshape(-1, 3))
    head, tail = grip(np.concatenate(points), rig.data.bones[holder_name])

    context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    edits = rig.data.edit_bones
    edit = edits.new(name)
    edit.head, edit.tail = head, tail
    edit.align_roll(edits[holder_name].z_axis)
    edit.parent, edit.use_connect, edit.use_deform = edits[holder_name], False, True
    for collection in edits[holder_name].collections:
        collection.assign(edit)
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.pose.bones[name].rotation_mode = rig.pose.bones[holder_name].rotation_mode
    settings = context.scene.sekiro_retarget
    if settings.target == rig and settings.rows:
        notes.append('Match bones again in the Retarget tab to list it in the bone list.')
    return dict(rig=rig.name, bone=name, holder=holder_name, meshes=[obj.name for obj in objects],
                length=(tail - head).length * retarget.uniform_scale(rig), frame=context.scene.frame_current, notes=notes)


def summary(result):
    """One status line for an added weapon."""
    return (f"Added {result['bone']} under {result['holder']} with {mirror.listed(result['meshes'])}, "
            f"{result['length'] * 100:.0f} cm long: it stays where it was on frame {result['frame']} and follows "
            f"{result['holder']} on every frame." + ''.join(' ' + note for note in result['notes']))
