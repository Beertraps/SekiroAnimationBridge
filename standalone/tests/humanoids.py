"""Owned synthetic humanoid skeletons in common naming conventions, for matching and retarget tests.

Positions are Blender armature space in metres: +Z is up, the character faces
-Y and its left side is +X. Every bone carries a canonical label (L.hand,
spine.first, ...) or None for helpers such as twist, IK and cloth bones.
"""
import math
import random

FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')


def base(arm_angle=0.0, scale=1.0):
    """Canonical joints: label -> (parent label, head). arm_angle lowers both arms from a T-pose, in degrees."""
    joints = {}

    def add(label, parent, x, y, z):
        joints[label] = (parent, (x * scale, y * scale, z * scale))

    add('hips', None, 0, 0, 1.0)
    add('spine.first', 'hips', 0, .01, 1.1)
    add('spine.mid', 'spine.first', 0, .01, 1.25)
    add('spine.last', 'spine.mid', 0, 0, 1.4)
    add('neck', 'spine.last', 0, -.01, 1.55)
    add('head', 'neck', 0, -.02, 1.65)
    add('head.end', 'head', 0, -.02, 1.85)
    for side, s in (('L', 1), ('R', -1)):
        add(f'{side}.clavicle', 'spine.last', s * .04, -.02, 1.5)
        shoulder = (s * .17, 0, 1.5)
        arm = {f'{side}.upperarm': ((s * .17, 0, 1.5), f'{side}.clavicle'),
               f'{side}.forearm': ((s * .45, .01, 1.5), f'{side}.upperarm'),
               f'{side}.hand': ((s * .70, 0, 1.5), f'{side}.forearm')}
        starts = dict(thumb=(.72, -.035, 1.49), index=(.79, -.025, 1.5), middle=(.795, -.005, 1.5),
                      ring=(.79, .015, 1.5), pinky=(.78, .032, 1.5))
        steps = dict(thumb=(.025, -.02, -.005), index=(.03, 0, 0), middle=(.033, 0, 0), ring=(.03, 0, 0), pinky=(.025, 0, 0))
        for finger in FINGERS:
            parent = f'{side}.hand'
            for segment in (1, 2, 3):
                x, y, z = (start + (segment - 1) * step for start, step in zip(starts[finger], steps[finger]))
                arm[f'{side}.{finger}.{segment}'] = ((s * x, y, z), parent)
                parent = f'{side}.{finger}.{segment}'
        angle = math.radians(arm_angle) * s
        for label, (head, parent) in arm.items():
            dx, dy, dz = (head[i] - shoulder[i] for i in range(3))
            add(label, parent, shoulder[0] + dx * math.cos(angle) + dz * math.sin(angle), shoulder[1] + dy,
                shoulder[2] - dx * math.sin(angle) + dz * math.cos(angle))
        add(f'{side}.thigh', 'hips', s * .1, 0, .95)
        add(f'{side}.calf', f'{side}.thigh', s * .1, -.01, .52)
        add(f'{side}.foot', f'{side}.calf', s * .1, .02, .08)
        add(f'{side}.toe', f'{side}.foot', s * .1, -.12, .02)
    return joints


def between(joints, a, b, t=.5):
    pa, pb = joints[a][1], joints[b][1]
    return tuple(x + (y - x) * t for x, y in zip(pa, pb))


def build(joints, names, parents=None, extra=()):
    """Bones (name, parent name, head, label) in parent-first order.

    names maps labels to bone names; unnamed labels are left out and their
    children hang from the nearest named ancestor. parents overrides a label's
    parent with a bone name. extra adds (name, parent name, head) helpers.
    """
    parents = parents or {}
    bones = []
    for label, (parent, head) in joints.items():
        if label not in names:
            continue
        while parent and parent not in names:
            parent = joints[parent][0]
        bones.append([names[label], parents.get(label, names.get(parent, '')), head, label])
    for name, parent, head in extra:
        bones.append([name, parent, head, None])
    order, placed = [], set()
    while len(order) < len(bones):
        ready = [bone for bone in bones if bone[0] not in placed and (not bone[1] or bone[1] in placed)]
        if not ready:
            raise ValueError('Bones with unknown parents: ' + ', '.join(b[0] for b in bones if b[0] not in placed))
        for bone in ready:
            order.append(tuple(bone))
            placed.add(bone[0])
    return order


def mixamo(arm_angle=0.0):
    joints = base(arm_angle)
    names = {'hips': 'mixamorig:Hips', 'spine.first': 'mixamorig:Spine', 'spine.mid': 'mixamorig:Spine1',
             'spine.last': 'mixamorig:Spine2', 'neck': 'mixamorig:Neck', 'head': 'mixamorig:Head',
             'head.end': 'mixamorig:HeadTop_End'}
    for side, word in (('L', 'Left'), ('R', 'Right')):
        names.update({f'{side}.clavicle': f'mixamorig:{word}Shoulder', f'{side}.upperarm': f'mixamorig:{word}Arm',
                      f'{side}.forearm': f'mixamorig:{word}ForeArm', f'{side}.hand': f'mixamorig:{word}Hand',
                      f'{side}.thigh': f'mixamorig:{word}UpLeg', f'{side}.calf': f'mixamorig:{word}Leg',
                      f'{side}.foot': f'mixamorig:{word}Foot', f'{side}.toe': f'mixamorig:{word}ToeBase'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'mixamorig:{word}Hand{finger.title()}{segment}'
    return build(joints, names)


def unreal(arm_angle=40.0):
    joints = base(arm_angle)
    names = {'hips': 'pelvis', 'spine.first': 'spine_01', 'spine.mid': 'spine_02', 'spine.last': 'spine_03',
             'neck': 'neck_01', 'head': 'head'}
    extra = [('root', '', (0, 0, 0)), ('ik_foot_root', 'root', (0, 0, 0)), ('ik_hand_root', 'root', (0, 0, 0)),
             ('ik_hand_gun', 'ik_hand_root', joints['R.hand'][1])]
    for side, s in (('L', 'l'), ('R', 'r')):
        names.update({f'{side}.clavicle': f'clavicle_{s}', f'{side}.upperarm': f'upperarm_{s}', f'{side}.forearm': f'lowerarm_{s}',
                      f'{side}.hand': f'hand_{s}', f'{side}.thigh': f'thigh_{s}', f'{side}.calf': f'calf_{s}',
                      f'{side}.foot': f'foot_{s}', f'{side}.toe': f'ball_{s}'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'{finger}_0{segment}_{s}'
        extra += [(f'upperarm_twist_01_{s}', f'upperarm_{s}', between(joints, f'{side}.upperarm', f'{side}.forearm')),
                  (f'lowerarm_twist_01_{s}', f'lowerarm_{s}', between(joints, f'{side}.forearm', f'{side}.hand')),
                  (f'thigh_twist_01_{s}', f'thigh_{s}', between(joints, f'{side}.thigh', f'{side}.calf')),
                  (f'calf_twist_01_{s}', f'calf_{s}', between(joints, f'{side}.calf', f'{side}.foot')),
                  (f'ik_foot_{s}', 'ik_foot_root', joints[f'{side}.foot'][1])]
    return build(joints, names, {'hips': 'root'}, extra)


def biped(arm_angle=0.0):
    """3ds Max Biped: thighs hang from the first spine bone and clavicles from the neck."""
    joints = base(arm_angle)
    names = {'hips': 'Bip01 Pelvis', 'spine.first': 'Bip01 Spine', 'spine.mid': 'Bip01 Spine1', 'spine.last': 'Bip01 Spine2',
             'neck': 'Bip01 Neck', 'head': 'Bip01 Head', 'head.end': 'Bip01 HeadNub'}
    parents = {'hips': 'Bip01'}
    for side in 'LR':
        names.update({f'{side}.clavicle': f'Bip01 {side} Clavicle', f'{side}.upperarm': f'Bip01 {side} UpperArm',
                      f'{side}.forearm': f'Bip01 {side} Forearm', f'{side}.hand': f'Bip01 {side} Hand',
                      f'{side}.thigh': f'Bip01 {side} Thigh', f'{side}.calf': f'Bip01 {side} Calf',
                      f'{side}.foot': f'Bip01 {side} Foot', f'{side}.toe': f'Bip01 {side} Toe0'})
        for number, finger in enumerate(FINGERS):
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'Bip01 {side} Finger{number}' + ('' if segment == 1 else str(segment - 1))
        parents.update({f'{side}.clavicle': 'Bip01 Neck', f'{side}.thigh': 'Bip01 Spine'})
    return build(joints, names, parents, [('Bip01', '', (0, 0, 1.0))])


def vroid(arm_angle=0.0):
    joints = base(arm_angle)
    names = {'hips': 'J_Bip_C_Hips', 'spine.first': 'J_Bip_C_Spine', 'spine.mid': 'J_Bip_C_Chest',
             'spine.last': 'J_Bip_C_UpperChest', 'neck': 'J_Bip_C_Neck', 'head': 'J_Bip_C_Head'}
    for side in 'LR':
        names.update({f'{side}.clavicle': f'J_Bip_{side}_Shoulder', f'{side}.upperarm': f'J_Bip_{side}_UpperArm',
                      f'{side}.forearm': f'J_Bip_{side}_LowerArm', f'{side}.hand': f'J_Bip_{side}_Hand',
                      f'{side}.thigh': f'J_Bip_{side}_UpperLeg', f'{side}.calf': f'J_Bip_{side}_LowerLeg',
                      f'{side}.foot': f'J_Bip_{side}_Foot', f'{side}.toe': f'J_Bip_{side}_ToeBase'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'J_Bip_{side}_{"Little" if finger == "pinky" else finger.title()}{segment}'
    return build(joints, names, {'hips': 'Root'}, [('Root', '', (0, 0, 0))])


def character_creator(arm_angle=35.0):
    """Character Creator 3/4: the hip bone carries both the pelvis (legs) and the waist (spine)."""
    joints = base(arm_angle)
    names = {'hips': 'CC_Base_Pelvis', 'spine.first': 'CC_Base_Waist', 'spine.mid': 'CC_Base_Spine01',
             'spine.last': 'CC_Base_Spine02', 'neck': 'CC_Base_NeckTwist01', 'head': 'CC_Base_Head'}
    for side in 'LR':
        names.update({f'{side}.clavicle': f'CC_Base_{side}_Clavicle', f'{side}.upperarm': f'CC_Base_{side}_Upperarm',
                      f'{side}.forearm': f'CC_Base_{side}_Forearm', f'{side}.hand': f'CC_Base_{side}_Hand',
                      f'{side}.thigh': f'CC_Base_{side}_Thigh', f'{side}.calf': f'CC_Base_{side}_Calf',
                      f'{side}.foot': f'CC_Base_{side}_Foot', f'{side}.toe': f'CC_Base_{side}_ToeBase'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'CC_Base_{side}_{"Mid" if finger == "middle" else finger.title()}{segment}'
    return build(joints, names, {'hips': 'CC_Base_Hip', 'spine.first': 'CC_Base_Hip'},
                 [('CC_Base_BoneRoot', '', (0, 0, 0)), ('CC_Base_Hip', 'CC_Base_BoneRoot', (0, 0, 1.0))])


def rigify(arm_angle=0.0):
    """Rigify's deform layer, with control and mechanism bones the matcher must ignore."""
    joints = base(arm_angle)
    names = {'hips': 'DEF-spine', 'spine.first': 'DEF-spine.001', 'spine.mid': 'DEF-spine.002', 'spine.last': 'DEF-spine.003',
             'neck': 'DEF-spine.004', 'head': 'DEF-spine.006'}
    extra = [('root', '', (0, 0, 0)), ('ORG-spine', 'root', (0, 0, 1.0)), ('MCH-torso.parent', 'root', (0, 0, 1.0)),
             ('torso', 'MCH-torso.parent', (0, 0, 1.0)), ('DEF-spine.005', 'DEF-spine.004', between(joints, 'neck', 'head'))]
    parents = {'hips': 'root', 'head': 'DEF-spine.005'}
    for side in 'LR':
        names.update({f'{side}.clavicle': f'DEF-shoulder.{side}', f'{side}.upperarm': f'DEF-upper_arm.{side}',
                      f'{side}.forearm': f'DEF-forearm.{side}', f'{side}.hand': f'DEF-hand.{side}',
                      f'{side}.thigh': f'DEF-thigh.{side}', f'{side}.calf': f'DEF-shin.{side}',
                      f'{side}.foot': f'DEF-foot.{side}', f'{side}.toe': f'DEF-toe.{side}'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = (f'DEF-thumb.0{segment}.{side}' if finger == 'thumb'
                                                       else f'DEF-f_{finger}.0{segment}.{side}')
        for limb, child in (('upper_arm', 'forearm'), ('forearm', 'hand'), ('thigh', 'calf'), ('shin', 'foot')):
            first = dict(upper_arm='upperarm', forearm='forearm', thigh='thigh', shin='calf')[limb]
            extra.append((f'DEF-{limb}.{side}.001', f'DEF-{limb}.{side}', between(joints, f'{side}.{first}', f'{side}.{child}')))
            parents[f'{side}.{child}'] = f'DEF-{limb}.{side}.001'
        extra += [(f'ORG-hand.{side}', 'root', joints[f'{side}.hand'][1]), (f'MCH-thigh_ik.{side}', 'root', joints[f'{side}.thigh'][1])]
    return build(joints, names, parents, extra)


def daz(arm_angle=45.0):
    """Daz Genesis 8: camel-case names with l/r prefixes, bend and twist bones."""
    joints = base(arm_angle)
    names = {'hips': 'pelvis', 'spine.first': 'abdomenLower', 'spine.mid': 'abdomenUpper', 'spine.last': 'chestUpper',
             'neck': 'neckLower', 'head': 'head'}
    extra = [('hip', '', (0, 0, 1.0)), ('chestLower', 'abdomenUpper', (0, .005, 1.33)),
             ('neckUpper', 'neckLower', between(joints, 'neck', 'head'))]
    parents = {'hips': 'hip', 'spine.first': 'hip', 'spine.last': 'chestLower', 'head': 'neckUpper'}
    for side, s in (('L', 'l'), ('R', 'r')):
        names.update({f'{side}.clavicle': f'{s}Collar', f'{side}.upperarm': f'{s}ShldrBend', f'{side}.forearm': f'{s}ForearmBend',
                      f'{side}.hand': f'{s}Hand', f'{side}.thigh': f'{s}ThighBend', f'{side}.calf': f'{s}Shin',
                      f'{side}.foot': f'{s}Foot', f'{side}.toe': f'{s}Toe'})
        for finger in FINGERS:
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'{s}{"Mid" if finger == "middle" else finger.title()}{segment}'
        extra += [(f'{s}ShldrTwist', f'{s}ShldrBend', between(joints, f'{side}.upperarm', f'{side}.forearm')),
                  (f'{s}ForearmTwist', f'{s}ForearmBend', between(joints, f'{side}.forearm', f'{side}.hand')),
                  (f'{s}ThighTwist', f'{s}ThighBend', between(joints, f'{side}.thigh', f'{side}.calf'))]
        parents.update({f'{side}.forearm': f'{s}ShldrTwist', f'{side}.hand': f'{s}ForearmTwist', f'{side}.calf': f'{s}ThighTwist'})
    return build(joints, names, parents, extra)


def fromsoftware(arm_angle=45.0, layout='elden'):
    """FromSoftware-style rig. layout 'elden': Master > RootPos > Pelvis, RootPos > RootRotY > RootRotXZ > Spine.
    'souls': Master > Lower_Root > Pelvis, Master > Upper_Root > Spine. Helper bones sit beside the limbs."""
    joints = base(arm_angle)
    names = {'hips': 'Pelvis', 'spine.first': 'Spine', 'spine.mid': 'Spine1', 'spine.last': 'Spine2', 'neck': 'Neck',
             'head': 'Head'}
    if layout == 'elden':
        extra = [('Master', '', (0, 0, 0)), ('RootPos', 'Master', (0, 0, 1.0)), ('RootRotY', 'RootPos', (0, 0, 1.0)),
                 ('RootRotXZ', 'RootRotY', (0, 0, 1.0))]
        parents = {'hips': 'RootPos', 'spine.first': 'RootRotXZ'}
    else:
        extra = [('Master', '', (0, 0, 1.0)), ('Lower_Root', 'Master', (0, 0, 1.0)), ('Upper_Root', 'Master', (0, 0, 1.08))]
        parents = {'hips': 'Lower_Root', 'spine.first': 'Upper_Root'}
    extra.append(('Face_Root', 'Head', joints['head'][1]))
    for side in 'LR':
        names.update({f'{side}.clavicle': f'{side}_Clavicle', f'{side}.upperarm': f'{side}_UpperArm', f'{side}.forearm': f'{side}_Forearm',
                      f'{side}.hand': f'{side}_Hand', f'{side}.thigh': f'{side}_Thigh', f'{side}.calf': f'{side}_Calf',
                      f'{side}.foot': f'{side}_Foot', f'{side}.toe': f'{side}_Toe0'})
        for number, finger in enumerate(FINGERS):
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'{side}_Finger{number}' + ('' if segment == 1 else str(segment - 1))
        extra += [(f'{side}_Shoulder', f'{side}_Clavicle', joints[f'{side}.upperarm'][1]),
                  (f'{side}_UpArmTwist', f'{side}_UpperArm', between(joints, f'{side}.upperarm', f'{side}.forearm')),
                  (f'{side}_Knee', f'{side}_Thigh', joints[f'{side}.calf'][1]),
                  (f'{side}_Hip', 'Pelvis', joints[f'{side}.thigh'][1]),
                  (f'{side}_Weapon', f'{side}_Hand', between(joints, f'{side}.hand', f'{side}.middle.1'))]
    return build(joints, names, parents, extra)


def proportioned(spine=3, clavicles=True, twists=False, legs=1.0, thighs=None, arms=(1.0, 1.0), hips=1.0, arm_angle=0.0):
    """A humanoid of other proportions and bone counts than base(), for the full-body bake.

    spine bones run between the hips and the neck, with or without clavicles, and twists adds a twist bone in series
    to each upper arm and forearm, 40% of the way down, and to each thigh and calf, half way. The legs are scaled by
    legs and the upper body rides on them; thighs is the thigh's share of the leg (base(): 0.49), arms scales the
    upper arm and the forearm, and hips the distance between the hip joints. Spine bones between the first and the
    last, and twist bones, carry no label.
    """
    lift = legs - 1.0
    bones = [('Root', '', (0, 0, 0), None), ('Hips', 'Root', (0, 0, legs), 'hips')]
    parent = 'Hips'
    for index in range(spine):
        name = 'Spine' + (str(index) if index else '')
        height = 1.1 + .3 * index / (spine - 1) if spine > 1 else 1.25
        bones.append((name, parent, (0, .01 if index < spine - 1 else 0, height + lift),
                      'spine.first' if index == 0 else 'spine.last' if index == spine - 1 else None))
        parent = name
    chest = parent
    bones += [('Neck', chest, (0, -.01, 1.55 + lift), 'neck'), ('Head', 'Neck', (0, -.02, 1.65 + lift), 'head'),
              ('HeadTop', 'Head', (0, -.02, 1.85 + lift), 'head.end')]
    share = (.95 - .52) / (.95 - .08) if thighs is None else thighs
    for side, s in (('L', 1), ('R', -1)):
        shoulder = (s * .17, 0, 1.5 + lift)
        angle = math.radians(arm_angle) * s

        def arm_point(dx, dy, dz):
            """A point of the arm in a T-pose, given from the shoulder, lowered by arm_angle like base()."""
            return (shoulder[0] + dx * math.cos(angle) + dz * math.sin(angle), shoulder[1] + dy,
                    shoulder[2] - dx * math.sin(angle) + dz * math.cos(angle))
        upper, fore = .28 * arms[0], .25 * arms[1]
        elbow, wrist = (s * upper, .01, 0), (s * (upper + fore), 0, 0)
        above = chest
        if clavicles:
            bones.append((f'{side}_Clavicle', chest, (s * .04, -.02, 1.5 + lift), f'{side}.clavicle'))
            above = f'{side}_Clavicle'
        bones.append((f'{side}_UpperArm', above, shoulder, f'{side}.upperarm'))
        above = f'{side}_UpperArm'
        if twists:
            bones.append((f'{side}_UpperArmTwist', above, arm_point(*(.4 * v for v in elbow)), None))
            above = f'{side}_UpperArmTwist'
        bones.append((f'{side}_Forearm', above, arm_point(*elbow), f'{side}.forearm'))
        above = f'{side}_Forearm'
        if twists:
            bones.append((f'{side}_ForearmTwist', above, arm_point(*(a + .4 * (b - a) for a, b in zip(elbow, wrist))), None))
            above = f'{side}_ForearmTwist'
        bones.append((f'{side}_Hand', above, arm_point(*wrist), f'{side}.hand'))
        starts = dict(thumb=(.02, -.035, -.01), index=(.09, -.025, 0), middle=(.095, -.005, 0), ring=(.09, .015, 0),
                      pinky=(.08, .032, 0))
        steps = dict(thumb=(.025, -.02, -.005), index=(.03, 0, 0), middle=(.033, 0, 0), ring=(.03, 0, 0), pinky=(.025, 0, 0))
        for finger in FINGERS:
            above = f'{side}_Hand'
            for segment in (1, 2, 3):
                x, y, z = (start + (segment - 1) * step for start, step in zip(starts[finger], steps[finger]))
                name = f'{side}_{finger.title()}{segment}'
                bones.append((name, above, arm_point(wrist[0] + s * x, y, z), f'{side}.{finger}.{segment}'))
                above = name
        x = s * .1 * hips
        knee = .95 * legs - share * .87 * legs
        joints = [('Thigh', (x, 0, .95 * legs), 'thigh'), ('Calf', (x, -.01, knee), 'calf'), ('Foot', (x, .02, .08 * legs), 'foot')]
        above = 'Hips'
        for index, (part, head, label) in enumerate(joints):
            bones.append((f'{side}_{part}', above, head, f'{side}.{label}'))
            above = f'{side}_{part}'
            if twists and index < 2:
                below = joints[index + 1][1]
                bones.append((f'{side}_{part}Twist', above, tuple((a + b) / 2 for a, b in zip(head, below)), None))
                above = f'{side}_{part}Twist'
        bones.append((f'{side}_Toe', f'{side}_Foot', (x, -.12, .02 * legs), f'{side}.toe'))
    return bones


def with_foot_targets(bones):
    """A FromSoftware-style rig with its foot target chains, as every Sekiro and Dark Souls III rig has them: from
    Master straight down, L_Foot_Target2 at hip height, L_Foot_Target1 at knee height and L_Foot_Target on the foot."""
    heads = {name: head for name, parent, head, label in bones}
    extra = []
    for side in 'LR':
        x, y, z = heads[f'{side}_Foot']
        extra += [(f'{side}_Foot_Target2', 'Master', (x, y, heads[f'{side}_Thigh'][2]), None),
                  (f'{side}_Foot_Target1', f'{side}_Foot_Target2', (x, y, heads[f'{side}_Calf'][2]), None),
                  (f'{side}_Foot_Target', f'{side}_Foot_Target1', (x, y, z), None)]
    return list(bones) + extra


CONVENTIONS = dict(mixamo=mixamo, unreal=unreal, biped=biped, vroid=vroid, character_creator=character_creator,
                   rigify=rigify, daz=daz, elden=lambda: fromsoftware(45, 'elden'), souls=lambda: fromsoftware(0, 'souls'))


def scrambled(bones, seed=1, prefix='Bone'):
    """The same rig with every name replaced by Bone_NNN in shuffled order."""
    order = list(range(len(bones)))
    random.Random(seed).shuffle(order)
    alias = {bone[0]: f'{prefix}_{order[index]:03d}' for index, bone in enumerate(bones)}
    return [(alias[name], alias.get(parent, ''), head, label) for name, parent, head, label in bones]
