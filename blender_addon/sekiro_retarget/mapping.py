"""Bone matching without Blender dependencies or character-specific presets.

Names are normalized first: namespaces, a prefix shared by most of a rig's
bones (mixamorig, Bip01, CC_Base, J_Bip), Rigify DEF- layers and left/right
markers in any position. Bones then receive anatomical roles. Where names do
not say, rest positions do: the legs are the two chains descending from the
hips, the arms the two chains reaching sideways from the chest, the thumb is
the finger nearest the front, and a bone takes the side of the limb it belongs
to. Spine and neck chains are matched by their position below the head, so
chains of different lengths still line up, and fingers by finger and segment.
A bone between two matched bones in both hierarchies is matched structurally,
a helper beside a matched parent by a shared name part, and a weapon bone in a
matched hand by the weapon bone in the other rig's hand, leaving out weapons
that the source clip hides. Where only one hand holds a weapon in the source
and only the other one in the target, the weapon changes hands. Uncertain
bones stay unassigned with a suggestion for review.
"""
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re


@dataclass(frozen=True)
class Bone:
    name: str
    parent: str = ''
    head: tuple = None  # Rest position in armature space, when known.


SIDES = {'l': 'L', 'left': 'L', 'r': 'R', 'right': 'R'}
CENTER = {'c', 'center', 'centre'}
SPINE = {'spine', 'chest', 'upperchest', 'waist', 'torso', 'abdomen', 'lowerback', 'spinelower', 'spinemid',
         'spineupper', 'spinemiddle', 'abdomenlower', 'abdomenupper', 'chestlower', 'chestupper'}
NECK = {'neck', 'necktwist', 'neckupper', 'necklower'}
ROLES = {
    'hips': 'hips', 'pelvis': 'hips', 'head': 'head', 'jaw': 'jaw',
    'clavicle': 'clavicle', 'collarbone': 'clavicle',
    'upperarm': 'upperarm', 'uparm': 'upperarm', 'shldrbend': 'upperarm',
    'forearm': 'forearm', 'lowerarm': 'forearm', 'forearmbend': 'forearm',
    'hand': 'hand', 'wrist': 'hand',
    'thigh': 'thigh', 'upleg': 'thigh', 'upperleg': 'thigh', 'thighbend': 'thigh',
    'calf': 'calf', 'shin': 'calf', 'lowerleg': 'calf',
    'foot': 'foot', 'ankle': 'foot',
    'toe': 'toe', 'toes': 'toe', 'toebase': 'toe', 'ball': 'toe',
}
# Names whose meaning depends on the rest of the rig: Mixamo's LeftShoulder is a
# clavicle and its LeftLeg a shin, but FromSoftware rigs also have L_Shoulder,
# L_Knee and L_Hip helper bones beside their clavicle, calf and thigh.
CONTEXT = {'shoulder': 'clavicle', 'collar': 'clavicle', 'arm': 'upperarm', 'leg': 'calf', 'knee': 'calf',
           'hip': 'thigh'}
FINGERS = {'thumb': 0, 'index': 1, 'middle': 2, 'mid': 2, 'ring': 3, 'pinky': 4, 'pinkie': 4, 'little': 4, 'small': 4}
LIMBS = ('clavicle', 'upperarm', 'forearm', 'hand', 'thigh', 'calf', 'foot', 'toe')
# Rigify names its whole torso spine.NNN: hips, three spine bones, two neck bones and the head.
RIGIFY_TORSO = ['hips', 'spine', 'spine', 'spine', 'neck', 'neck', 'head']
# A weapon held in the hand: Sekiro's R_Weapon dummy, an enemy's R_Katana. Storage bones such as
# Katana_Saya_Storage and B_Wepon_Case hold a sheathed weapon elsewhere on the body.
WEAPONS = {'weapon', 'wepon', 'wpn', 'katana', 'sword', 'blade', 'yari', 'spear', 'lance', 'axe', 'hammer', 'mace',
           'club', 'gun', 'bow', 'staff', 'dagger', 'knife', 'whip', 'scythe', 'sickle', 'naginata', 'halberd'}
STORAGE = {'storage', 'case', 'saya', 'sheath', 'scabbard', 'holster', 'quiver'}


def words(name):
    name = re.split(r'[:|]', name)[-1]
    name = re.sub(r'^c\d{4}[_ .-]+', '', name, flags=re.I)
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    return re.findall(r'[a-z]+|\d+', name.lower())


def split_side(tokens):
    tokens = list(tokens)
    side = ''
    for index, token in enumerate(tokens):
        if token in SIDES:
            side = SIDES[token]
            del tokens[index]
            break
    return side, [token for token in tokens if token not in CENTER] or tokens


def identity(name):
    side, tokens = split_side(words(name))
    return side, ''.join(tokens)


def semantic(name):
    side, stem = identity(name)
    letters = re.sub(r'\d+', '', stem)
    return side, ROLES.get(letters, CONTEXT.get(letters, letters))


def weapon_name(name):
    """Whether a bone name says it holds a weapon (R_Weapon, R_Katana) rather than storing one (Katana_Saya_Storage)."""
    tokens = set(words(name))
    return bool(tokens & WEAPONS) and not tokens & STORAGE


def weapon_part(name):
    """Whether a bone name mentions a weapon, held or stored (R_Katana, R_Katana_Saya, back_Yari_Storage), or a shield:
    a bone that clips hide by scaling it to almost nothing."""
    return bool(set(words(name)) & (WEAPONS | STORAGE | {'shield'}))


def sub(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def distance(a, b):
    return dot(sub(a, b), sub(a, b)) ** .5


@dataclass
class Info:
    name: str
    parent: str
    side: str
    tokens: tuple
    head: tuple = None
    depth: int = 0

    @property
    def key(self):
        return self.side, ''.join(self.tokens)

    @property
    def letters(self):
        return ''.join(token for token in self.tokens if not token.isdigit())


class Rig:
    """Normalized names, hierarchy and anatomical roles of one armature."""

    def __init__(self, bones):
        bones = list(bones)
        self.rigify = any(bone.name.startswith('DEF-') for bone in bones)
        if self.rigify:
            # Deform bones carry the final motion; ORG- and MCH- layers would duplicate them.
            bones = [bone for bone in bones if bone.name.startswith('DEF-')]
        names = {bone.name for bone in bones}
        tokens = {bone.name: [t for t in words(bone.name) if t not in ('def', 'org', 'mch')] for bone in bones}
        prefix = self.shared_prefix(list(tokens.values()))
        self.bones = {}
        for bone in bones:
            items = tokens[bone.name]
            if prefix and tuple(items[:len(prefix)]) == prefix and len(items) > len(prefix):
                items = items[len(prefix):]
            side, items = split_side(items)
            if items and items[0] == 'f' and len(items) > 1 and items[1] in FINGERS:
                items = items[1:]  # Rigify finger prefix: f_index.01.L
            head = tuple(float(value) for value in bone.head) if bone.head is not None else None
            self.bones[bone.name] = Info(bone.name, bone.parent if bone.parent in names else '', side, tuple(items), head)
        for info in self.bones.values():
            parent, depth = info.parent, 0
            while parent:
                depth += 1
                parent = self.bones[parent].parent
            info.depth = depth
        self.children = {}
        for info in self.bones.values():
            self.children.setdefault(info.parent, []).append(info.name)
        self.body = self.infer_body() if len(self.bones) >= 8 and all(i.head for i in self.bones.values()) else None
        if self.body:
            for name, side in self.body['sides'].items():
                if not self.bones[name].side:
                    self.bones[name].side = side
        # What came from rest positions rather than names; such matches get lower confidence.
        self.inferred = set()
        self.fingers = {name: finger for name in self.bones for finger in [self.name_finger(name)] if finger}
        if not self.fingers and self.body and self.body['fingers']:
            self.fingers = dict(self.body['fingers'])
            self.inferred.add('fingers')
        self.roles = self.find_roles()

    @staticmethod
    def shared_prefix(token_lists):
        """A leading token sequence (mixamorig, bip 01, cc base, j bip) shared by most bones."""
        if len(token_lists) < 4:
            return ()
        vocabulary = set(ROLES) | set(CONTEXT) | SPINE | NECK | set(FINGERS) | set(SIDES) | {'finger', 'master', 'root'}
        for length in (2, 1):
            counts = Counter(tuple(tokens[:length]) for tokens in token_lists if len(tokens) > length)
            if counts:
                prefix, count = counts.most_common(1)[0]
                if count >= .6 * len(token_lists) and not vocabulary.intersection(prefix):
                    return prefix
        return ()

    def ancestors(self, name):
        result, parent = [], self.bones[name].parent
        while parent:
            result.append(parent)
            parent = self.bones[parent].parent
        return result

    def common_ancestor(self, a, b):
        """The lowest bone whose subtree holds both bones (one of them, if nested), or ''."""
        above = [a] + self.ancestors(a)
        for name in [b] + self.ancestors(b):
            if name in above:
                return name
        return ''

    def shallowest(self, names):
        """The single shallowest bone (Rigify's upper_arm before upper_arm.001), or None if tied."""
        if not names:
            return None
        names = sorted(names, key=lambda name: self.bones[name].depth)
        return names[0] if len(names) == 1 or self.bones[names[0]].depth < self.bones[names[1]].depth else None

    def infer_body(self):
        """Roles, sides, chains and fingers from the hierarchy and rest positions alone.

        Only the vertical axis is assumed (Blender's +Z). Distances are measured
        in leg lengths, so hanging wires or far-away helpers do not set the scale.
        Returns None when no bone has two leg-like chains below it.
        """
        heads = {name: info.head for name, info in self.bones.items()}
        subtree = {}
        for name in sorted(self.bones, key=lambda n: -self.bones[n].depth):
            subtree[name] = [name] + [item for child in self.children.get(name, ()) for item in subtree[child]]

        def path(top, bottom):
            result = [bottom]
            while result[-1] != top:
                result.append(self.bones[result[-1]].parent)
            return result[::-1]

        def flat(a, b):
            return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5

        def norm3(v):
            return dot(v, v) ** .5

        # Legs: two chains of three or more bones that start near a bone's height, drop
        # almost straight down and end on opposite sides at similar depths. Capes curve
        # away from the body, and foot targets under a floor-level root do not drop.
        found = None
        for name, info in self.bones.items():
            top = heads[name]
            legs = []
            for child in self.children.get(name, ()):
                end = min(subtree[child], key=lambda n: heads[n][2])
                drop = top[2] - heads[end][2]
                if drop > 0 and heads[child][2] > top[2] - .25 * drop and flat(heads[end], top) < .35 * drop:
                    chain = path(child, end)
                    if len(chain) >= 3:
                        legs.append((drop, chain))
            for axis in (0, 1):
                plus = [leg for leg in legs if heads[leg[1][-1]][axis] - top[axis] > .03 * leg[0]]
                minus = [leg for leg in legs if heads[leg[1][-1]][axis] - top[axis] < -.03 * leg[0]]
                if plus and minus:
                    a, b = max(plus), max(minus)
                    if min(a[0], b[0]) > .8 * max(a[0], b[0]):
                        score = (min(a[0], b[0]), info.depth)
                        if found is None or score > found[0]:
                            found = (score, name, a[1], b[1])
                    break
        if found is None:
            return None
        hips, legs = found[1], found[2:]
        ground = min(heads[leg[-1]][2] for leg in legs)
        # 3ds Max Biped hangs the thighs from its first spine bone; the pelvis is the parent
        # just below it, nearer the height of the hip joints.
        parent, joints = self.bones[hips].parent, (heads[legs[0][0]][2] + heads[legs[1][0]][2]) / 2
        if parent and heads[parent][2] < heads[hips][2] - .03 * (heads[hips][2] - ground) and \
                abs(heads[parent][2] - joints) < abs(heads[hips][2] - joints):
            hips = parent
        scale = heads[hips][2] - ground
        roles, sides, forward = {('', 'hips'): hips}, {}, [0.0, 0.0]
        leg_roles = []
        for chain in legs:
            # The foot is where the chain turns from downward to forward, below thigh and calf.
            foot = len(chain) - 1
            for k in range(2 if len(chain) > 3 else 1, len(chain) - 1):
                step = sub(heads[chain[k + 1]], heads[chain[k]])
                if flat(step, (0, 0, 0)) > .7 * abs(step[2]):
                    foot = k
                    break
            middle = (heads[chain[0]][2] + heads[chain[foot]][2]) / 2
            calf = min(chain[1:foot], key=lambda n: abs(heads[n][2] - middle)) if foot > 1 else None
            toe = chain[foot + 1] if foot + 1 < len(chain) else None
            if toe:
                step = sub(heads[toe], heads[chain[foot]])
                forward[0] += step[0]
                forward[1] += step[1]
            leg_roles.append((chain, dict(thigh=chain[0], calf=calf, foot=chain[foot], toe=toe)))
        length = (forward[0] ** 2 + forward[1] ** 2) ** .5
        if length > 1e-6:
            forward = (forward[0] / length, forward[1] / length, 0.0)
        else:
            # Blender's convention: characters face -Y, so their left is +X.
            span = sub(heads[legs[0][-1]], heads[legs[1][-1]])
            forward = (0.0, -1.0, 0.0) if abs(span[0]) >= abs(span[1]) else (1.0, 0.0, 0.0)
        left = (-forward[1], forward[0], 0.0)
        centre = heads[hips]
        for chain, parts in leg_roles:
            side = 'L' if dot(sub(heads[chain[-1]], centre), left) > 0 else 'R'
            sides.update((name, side) for name in subtree[chain[0]])
            roles.update(((side, role), name) for role, name in parts.items() if name)

        # Arms: the deepest bone with two different children reaching far to either side.
        excluded = {name for chain in legs for name in subtree[chain[0]]}
        found = None
        for name, info in self.bones.items():
            if name in excluded:
                continue
            arms = {}
            for child in self.children.get(name, ()):
                if child in excluded:
                    continue
                for sign, side in ((1, 'L'), (-1, 'R')):
                    reach = {n: sign * dot(sub(heads[n], heads[name]), left) for n in subtree[child]}
                    tip = max(reach, key=reach.get)
                    chain = path(child, tip)
                    if reach[tip] > .4 * scale and len(chain) >= 3 and min(reach[n] for n in chain) > -.03 * scale:
                        if side not in arms or reach[tip] > arms[side][0]:
                            arms[side] = (reach[tip], chain)
            if 'L' in arms and 'R' in arms and arms['L'][1][0] != arms['R'][1][0]:
                if found is None or info.depth > found[0]:
                    found = (info.depth, name, arms['L'][1], arms['R'][1])
        fingers, spine, neck = {}, [], []
        if found:
            chest, arm_roots, neck_start = found[1], {found[2][0], found[3][0]}, None
            if heads[chest][2] > sum(heads[name][2] for name in arm_roots) / 2 + .02 * scale and self.bones[chest].parent:
                # Biped hangs the clavicles from the neck, which starts above them; the chest is below.
                neck_start, chest = chest, self.bones[chest].parent
            for side, chain in zip('LR', found[2:]):
                sides.update((name, side) for name in subtree[chain[0]])
                # The hand is the first bone with two or more finger chains below it.
                hand = next((k for k in range(1, len(chain)) if
                             sum(len(subtree[c]) >= 2 for c in self.children.get(chain[k], ())) >= 2), len(chain) - 1)
                upper = 0
                if hand >= 3 and distance(heads[chain[0]], heads[chain[1]]) < .35 * distance(heads[chain[1]], heads[chain[hand]]):
                    roles[(side, 'clavicle')] = chain[0]
                    upper = 1
                roles[(side, 'upperarm')] = chain[upper]
                roles[(side, 'hand')] = chain[hand]
                elbow = [(a + b) / 2 for a, b in zip(heads[chain[upper]], heads[chain[hand]])]
                if hand - upper > 1:
                    roles[(side, 'forearm')] = min(chain[upper + 1:hand], key=lambda n: distance(heads[n], elbow))
                digits = []
                for child in self.children.get(chain[hand], ()):
                    if len(subtree[child]) >= 2:
                        digit = [child]
                        while self.children.get(digit[-1]):
                            digit.append(max(self.children[digit[-1]], key=lambda n: len(subtree[n])))
                        digits.append(digit)
                digits = sorted(digits, key=len, reverse=True)[:5]
                if len(digits) >= 2:
                    wrist = heads[chain[hand]]
                    reach = sorted((distance(heads[d[0]], wrist), i) for i, d in enumerate(digits))
                    if reach[0][0] < .75 * reach[1][0]:
                        # The thumb starts closest to the wrist...
                        thumb = digits[reach[0][1]]
                    else:
                        # ...or, where every finger has a metacarpal, points away from the others.
                        def aim(d):
                            v = sub(heads[d[-1]], wrist)
                            return [c / max(1e-9, dot(v, v) ** .5) for c in v]
                        thumb = min(digits, key=lambda d: sum(dot(aim(d), aim(o)) for o in digits if o is not d))
                    # The other fingers follow from the thumb tip's side: index, middle, ring, pinky.
                    others = sorted((d for d in digits if d is not thumb), key=lambda d: distance(heads[d[0]], heads[thumb[-1]]))
                    for number, digit in enumerate([thumb] + others):
                        for segment, name in enumerate(digit, 1):
                            fingers[name] = (number, segment)
            spine = path(self.common_ancestor(hips, chest), chest)[1:]
            # Rotation layers at hip height (Elden Ring's RootRotY/RootRotXZ) and short carriers
            # just below the spine (Dark Souls' Upper_Root) are not spine segments.
            while len(spine) > 1 and (heads[spine[0]][2] < centre[2] + .02 * scale or
                                      distance(heads[spine[0]], heads[spine[1]]) < .05 * scale):
                spine.pop(0)
            rising = [neck_start] if neck_start else [
                c for c in self.children.get(chest, ()) if c not in arm_roots and
                sum(heads[n][2] for n in subtree[c]) / len(subtree[c]) > heads[chest][2]]
            if rising:
                node = max(rising, key=lambda n: len(subtree[n]))
                chain = [node]
                while True:
                    kids = [kid for kid in self.children.get(node, ()) if kid not in arm_roots]
                    if not kids or len(kids) >= 3:
                        break
                    step = max(kids, key=lambda n: len(subtree[n]))
                    offset = sub(heads[step], heads[node])
                    if len(subtree[step]) == 1:
                        # A lone leaf just above is the head itself (UE's neck_02 > head). Far above, it
                        # marks the top of the skull; in front, it is a jaw.
                        if len(kids) == 1 and norm3(offset) < .15 * scale and offset[2] > 2 * flat(offset, (0, 0, 0)):
                            chain.append(step)
                        break
                    if norm3(offset) < .045 * scale:
                        break  # A group root at the same spot (Sekiro's Face_Root) belongs to the head.
                    node = step
                    chain.append(node)
                roles[('', 'head')] = chain[-1]
                neck = chain[:-1]
        if not any(info.side for info in self.bones.values()):
            # Names without any left/right marker: bones beside the body take the side they sit on.
            for name in self.bones:
                lateral = dot(sub(heads[name], centre), left)
                if name not in sides and abs(lateral) > .06 * scale:
                    sides[name] = 'L' if lateral > 0 else 'R'
        return dict(roles=roles, sides=sides, fingers=fingers, spine=spine, neck=neck, left=left, forward=forward,
                    centre=centre, scale=scale)

    def find_roles(self):
        roles = {}
        present = {(info.side, info.letters) for info in self.bones.values()}
        candidates = {}
        for info in self.bones.values():
            role = ROLES.get(info.letters)
            if role is None and info.letters in CONTEXT and info.side:
                target = CONTEXT[info.letters]
                if not any((info.side, stem) in present for stem, mapped in ROLES.items() if mapped == target):
                    role = target
            if role == 'hips' and info.side:
                role = None
            if role:
                candidates.setdefault((info.side if role in LIMBS else '', role), []).append(info.name)
        for key, names in candidates.items():
            chosen = self.shallowest(names)
            if chosen:
                roles[key] = chosen
        torso = self.rigify_torso()
        if torso:
            for info, role in zip(torso, RIGIFY_TORSO):
                if role in ('hips', 'head'):
                    roles[('', role)] = info.name
        if self.body:
            taken = set(roles.values())
            for key, name in self.body['roles'].items():
                if key not in roles and name not in taken:
                    roles[key] = name
                    taken.add(name)
                    self.inferred.add(key)
        return roles

    def rigify_torso(self):
        if not self.rigify:
            return None
        torso = sorted((info for info in self.bones.values() if info.letters == 'spine' and not info.side),
                       key=lambda info: info.depth)
        return torso if len(torso) == len(RIGIFY_TORSO) else None

    def chain(self, family):
        """Spine or neck bones below the head, ordered from the hips upward."""
        torso = self.rigify_torso()
        if torso:
            return [info.name for info, role in zip(torso, RIGIFY_TORSO) if role == family]
        stems = SPINE if family == 'spine' else NECK
        head = self.roles.get(('', 'head'))
        pool = reversed(self.ancestors(head)) if head else sorted(self.bones, key=lambda name: self.bones[name].depth)
        named = [name for name in pool if not self.bones[name].side and self.bones[name].letters in stems]
        if named or not self.body:
            return named
        self.inferred.add(family)
        return list(self.body[family])

    def name_finger(self, name):
        """(finger 0-4, segment) from a bone name, or None. Segment 0 is a metacarpal."""
        info = self.bones[name]
        tokens = list(info.tokens)
        if tokens and tokens[0] == 'hand':
            tokens = tokens[1:]  # Mixamo: LeftHandIndex1
        digits = [token for token in tokens if token.isdigit()]
        letters = [token for token in tokens if not token.isdigit()]
        if letters == ['finger'] and digits and len(digits[0]) <= 2:
            # Biped / FromSoftware: Finger0 thumb base, Finger01 its second segment, Finger12 index tip.
            value = digits[0]
            return int(value[0]), 1 if len(value) == 1 else int(value[1:]) + 1
        if letters and letters[0] in FINGERS:
            if letters[1:] in ([], ['proximal'], ['intermediate'], ['distal'], ['metacarpal']):
                segment = {'proximal': 1, 'intermediate': 2, 'distal': 3, 'metacarpal': 0}.get(
                    letters[1] if len(letters) > 1 else '', int(digits[0]) if digits else 1)
                return FINGERS[letters[0]], segment
        return None

    def finger(self, name):
        return self.fingers.get(name)

    def finger_roots(self, hand):
        """(finger, bone) for the first bone of each finger below a hand: thumb 0, index 1, middle 2, ring 3, little
        finger 4, in that order.

        A finger's first bone is its shallowest, so a metacarpal counts; bones between the hand and its fingers,
        such as a palm bone, are passed through."""
        roots, stack = {}, list(self.children.get(hand, ()))
        while stack:
            name = stack.pop()
            finger = self.finger(name)
            if not finger:
                stack.extend(self.children.get(name, ()))
            elif finger[0] not in roots or self.bones[name].depth < self.bones[roots[finger[0]]].depth:
                roots[finger[0]] = name
        return [(number, roots[number]) for number in sorted(roots)]

    def held(self, hand):
        """Weapon bones below a hand, outside its fingers."""
        found, stack = [], list(self.children.get(hand, ()))
        while stack:
            name = stack.pop()
            if self.finger(name):
                continue
            if weapon_name(name):
                found.append(name)
            stack.extend(self.children.get(name, ()))
        return found

    def rests_at(self, name, hand):
        """Whether a bone rests within three quarters of a forearm's length of a hand, as a weapon held there does.

        Isshin's spear L_Yari rests 1.7 m from his hand until a clip brings it in."""
        info, grip = self.bones.get(name), self.bones.get(hand)
        forearm = self.bones.get(self.roles.get((grip.side, 'forearm')) or grip.parent) if grip else None
        if not (info and info.head and grip.head and forearm and forearm.head):
            return False
        return distance(info.head, grip.head) <= .75 * distance(grip.head, forearm.head)

    def position(self, name):
        """Rest position relative to the hips in leg lengths (left, forward, up), or None."""
        if not self.body:
            return None
        offset = sub(self.bones[name].head, self.body['centre'])
        scale = self.body['scale']
        return dot(offset, self.body['left']) / scale, dot(offset, self.body['forward']) / scale, offset[2] / scale

    def counterpart(self, name):
        """The same bone on the other side (L_Hand for R_Hand), or ''."""
        info = self.bones.get(name)
        if not info or not info.side:
            return ''
        other = 'R' if info.side == 'L' else 'L'
        matches = [n for n, i in self.bones.items() if i.side == other and i.tokens == info.tokens]
        if len(matches) == 1:
            return matches[0]
        place = self.position(name)
        if place:
            # Unrelated names: the bone at the mirrored rest position.
            mirrored = (-place[0], place[1], place[2])
            near = sorted((distance(mirrored, self.position(n)), n) for n, i in self.bones.items() if i.side == other)
            if near and near[0][0] < .02 and (len(near) == 1 or near[1][0] > near[0][0] + .005):
                return near[0][1]
        return ''


def assignment(target, source, confidence, reason):
    return dict(target=target, source=source, confidence=confidence, reason=reason, suggestion='')


def match_bones(source, target, hidden=()):
    """Return one row per target; uncertain fuzzy suggestions stay unassigned.

    Left/right differences are forbidden, except for a weapon that changes
    hands. Source bones are used at most once.
    Anatomical roles and chains come before exact names, so a FromSoftware
    L_Shoulder helper cannot take Mixamo's LeftShoulder clavicle, and a
    three-bone spine maps its chest onto a two-bone spine's top bone.
    Source bones in hidden, such as the weapons that an enemy's clip scales
    to zero, are not taken as the weapon in a hand.
    """
    source_bones, target_bones = list(source), list(target)
    src, dst = Rig(source_bones), Rig(target_bones)
    assigned, used = {}, set()

    def assign(target_name, source_name, confidence, reason, across=False):
        if target_name in assigned or source_name in used or target_name not in dst.bones or source_name not in src.bones:
            return False
        if dst.bones[target_name].side != src.bones[source_name].side and not across:
            return False
        assigned[target_name] = assignment(target_name, source_name, confidence, reason)
        used.add(source_name)
        return True

    def same_name(target_name, source_name):
        return dst.bones[target_name].key == src.bones[source_name].key

    def by_role(key):
        t, s = dst.roles.get(key), src.roles.get(key)
        if not t or not s:
            return
        if same_name(t, s):
            assign(t, s, 1.0, 'Same normalized name')
        elif key in dst.inferred or key in src.inferred:
            assign(t, s, .9, 'Body structure: ' + key[1])
        else:
            assign(t, s, .96, 'Anatomical role: ' + key[1])

    for role in ('hips', 'head'):
        by_role(('', role))
    for family in ('spine', 'neck'):
        targets, sources = dst.chain(family), src.chain(family)
        if not targets or not sources:
            continue
        n, m = len(targets), len(sources)
        if n <= m:
            pairs = [(targets[i], sources[round(i * (m - 1) / (n - 1)) if n > 1 else 0]) for i in range(n)]
        else:
            pairs = [(targets[round(j * (n - 1) / (m - 1)) if m > 1 else 0], sources[j]) for j in range(m)]
        structural = family in dst.inferred or family in src.inferred
        for t, s in pairs:
            if n == m and same_name(t, s):
                assign(t, s, 1.0, 'Same normalized name')
            else:
                assign(t, s, .9 if structural else .95 if n == m else .92,
                       f'{family.title()} chain position ({n} target / {m} source bones)')
    for side in ('L', 'R'):
        for role in LIMBS:
            by_role((side, role))
    source_fingers = {}
    for name in src.bones:
        finger = src.finger(name)
        if finger:
            source_fingers.setdefault((src.bones[name].side, finger), []).append(name)
    structural = 'fingers' in dst.inferred or 'fingers' in src.inferred
    for name in dst.bones:
        finger = dst.finger(name)
        candidates = source_fingers.get((dst.bones[name].side, finger), []) if finger else []
        if len(candidates) == 1:
            if same_name(name, candidates[0]):
                assign(name, candidates[0], 1.0, 'Same normalized name')
            else:
                assign(name, candidates[0], .88 if structural else .95,
                       'Finger order and segment' if structural else 'Finger and segment')

    def unique_phase(key, confidence, reason):
        index = {}
        for name, info in src.bones.items():
            if name not in used:
                index.setdefault(key(info), []).append(name)
        for name, info in dst.bones.items():
            if name in assigned:
                continue
            candidates = [c for c in index.get(key(info), []) if c not in used]
            if len(candidates) > 1 and info.parent in assigned:
                # Parent identity disambiguates names after namespace removal.
                narrowed = [c for c in candidates if src.bones[c].parent == assigned[info.parent]['source']]
                candidates = narrowed if len(narrowed) == 1 else candidates
            if len(candidates) == 1:
                assign(name, candidates[0], confidence, reason)

    unique_phase(lambda info: info.key, 1.0, 'Same normalized name')
    unique_phase(lambda info: (info.side, ROLES.get(info.letters, info.letters)), .94, 'Common bone-name alias')

    # The weapon in a matched hand: Sekiro's R_Weapon dummy takes an enemy's R_Katana. Isshin's hand also
    # holds R_Gun and R_Katana_Wire; his clip hides the gun, and the katana is the hand's own child. Only a
    # single weapon bone on each side is matched; the bake turns weapons with meshes so that blades point alike.
    def weapons_in(hand, free=True):
        sources = [name for name in src.held(hand) if name not in hidden and not (free and name in used)]
        direct = [name for name in sources if src.bones[name].parent == hand]
        return direct if len(sources) > 1 and len(direct) == 1 else sources

    for side in ('L', 'R'):
        hand = dst.roles.get((side, 'hand'))
        if hand not in assigned:
            continue
        targets = [name for name in dst.held(hand) if name not in assigned]
        sources = weapons_in(assigned[hand]['source'])
        if len(targets) == 1 and len(sources) == 1:
            assign(targets[0], sources[0], .9, 'Weapon in the matched hand')

    # Where only one hand holds a weapon in the source and only the other one in the target, the weapon changes
    # hands: Godfrey holds his axe in the left hand and Isshin his katana in the right, so R_Katana takes L_Axe and
    # the bake puts it in Isshin's left hand. Weapons that rest away from the hand, as Isshin's spear does, are
    # left for review: the user may give the axe to the spear instead.
    hands = [dst.roles.get((side, 'hand')) for side in ('L', 'R')]
    if all(hand in assigned for hand in hands):
        targets = [[name for name in dst.held(hand) if dst.rests_at(name, hand)] for hand in hands]
        sources = [weapons_in(assigned[hand]['source'], free=False) for hand in hands]
        for this, other in ((0, 1), (1, 0)):
            if len(sources[this]) == 1 and not sources[other] and len(targets[other]) == 1 and not targets[this]:
                assign(targets[other][0], sources[this][0], .8, 'Weapon from the other hand', across=True)

    changed = True
    while changed:
        changed = False
        # A bone between two matched bones in both hierarchies: Lower_Root between a matched
        # Master and Pelvis takes the source bone between them, whatever either rig calls it.
        for name, info in dst.bones.items():
            if name in assigned or info.parent not in assigned:
                continue
            for child in dst.children.get(name, []):
                if child not in assigned:
                    continue
                middle = src.bones[assigned[child]['source']].parent
                if middle and middle not in used and src.bones[middle].parent == assigned[info.parent]['source']:
                    changed = assign(name, middle, .9, 'Between matched bones in both hierarchies') or changed
                    break
        # A helper beside a matched parent: L_ForeTwist and L_ForeArmTwist under matched forearms
        # share "twist". The closest name wins when several siblings share a part. Parts naming
        # the parent prove nothing: L_Thigh_Skirt and L_ThighTwist only share their thigh.
        proposals = {}
        for name, info in dst.bones.items():
            if name in assigned or info.parent not in assigned:
                continue
            parents = set(dst.bones[info.parent].tokens) | set(src.bones[assigned[info.parent]['source']].tokens)
            parts = {token for token in info.tokens if len(token) >= 3 and not token.isdigit()} - parents
            scored = sorted(((SequenceMatcher(None, ''.join(info.tokens), ''.join(src.bones[c].tokens)).ratio(), c)
                             for c in src.children.get(assigned[info.parent]['source'], ())
                             if c not in used and src.bones[c].side == info.side and parts & set(src.bones[c].tokens)),
                            reverse=True)
            if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] > .02):
                proposals.setdefault(scored[0][1], []).append((scored[0][0], name))
        for candidate, claims in proposals.items():
            claims.sort(reverse=True)
            if len(claims) == 1 or claims[0][0] - claims[1][0] > .02:
                changed = assign(claims[0][1], candidate, .88, 'Shares a name part under matched parents') or changed

    result = []
    for name, info in dst.bones.items():
        if name in assigned:
            result.append(assigned[name])
            continue
        mapped_parent = assigned.get(info.parent, {}).get('source', '')
        place = dst.position(name)
        guesses = []
        for candidate, other in src.bones.items():
            if candidate in used or other.side != info.side:
                continue
            score = SequenceMatcher(None, ''.join(info.tokens), ''.join(other.tokens)).ratio()
            if mapped_parent and other.parent == mapped_parent:
                score += .2  # Same place in the hierarchy.
            there = src.position(candidate)
            if place and there:
                score += max(0.0, .2 * (1 - distance(place, there) / .15))  # Same place on the body.
            guesses.append((min(score, .89), candidate))
        guesses.sort(reverse=True)
        best = guesses[0] if guesses and guesses[0][0] >= .6 else None
        result.append(dict(target=name, source='', confidence=best[0] if best else 0,
                           reason='Review suggestion' if best else 'No reliable match', suggestion=best[1] if best else ''))
    order = {bone.name: index for index, bone in enumerate(target_bones)}
    return sorted(result, key=lambda row: order.get(row['target'], len(order)))


def counterpart(name, bones):
    """The same bone on the other side of a rig (L_Hand for R_Hand), or ''."""
    return Rig(bones).counterpart(name)


def anatomy(bones):
    """Role -> bone name for hips, head and limbs, plus the spine and neck chains and the direction the
    rest pose faces (None when the body is not found), used by the retarget."""
    rig = Rig(bones)
    result = dict(rig.roles)
    result['spine'] = rig.chain('spine')
    result['neck'] = rig.chain('neck')
    result['forward'] = rig.body['forward'] if rig.body else None
    return result


def limb_links(bones):
    """(bone, next bone) pairs along arms, legs and fingers, used to match rest stances."""
    rig = Rig(bones)
    links = []
    for side in ('L', 'R'):
        for roles in (('clavicle', 'upperarm', 'forearm', 'hand'), ('thigh', 'calf', 'foot')):
            chain = [rig.roles[(side, role)] for role in roles if (side, role) in rig.roles]
            links += list(zip(chain, chain[1:]))
    by_finger = {(rig.bones[name].side, finger): name for name, finger in rig.fingers.items()}
    for (side, (digit, segment)), name in by_finger.items():
        child = by_finger.get((side, (digit, segment + 1)))
        if child:
            links.append((name, child))
    return links


def foot_targets(bones):
    """FromSoftware's foot targets: {target: (foot, [the bones above the target, from the top])}.

    Each side of a FromSoftware rig hangs a straight chain from Master: L_Foot_Target2 at hip height,
    L_Foot_Target1 at knee height and L_Foot_Target at the ankle, where L_Foot rests. In the game's
    clips the chain stands on the foot like a column: it keeps its rest pose and its upright rest
    rotation, moved as one so that L_Foot_Target sits on the foot, and L_Foot_Target turns with the
    foot. The game reads these bones, so a clip whose targets leave the feet can make a foot snap
    when the game blends into another clip.
    """
    bones = list(bones)
    named = {identity(bone.name): bone.name for bone in bones}
    parents = {bone.name: bone.parent for bone in bones}
    targets = {}
    for bone in bones:
        side, stem = identity(bone.name)
        foot = named.get((side, 'foot'))
        if not side or stem != 'foottarget' or not foot:
            continue
        chain, parent = [], parents[bone.name]
        while parent in parents and identity(parent)[0] == side and re.fullmatch(r'foottarget\d+', identity(parent)[1]):
            chain.insert(0, parent)
            parent = parents[parent]
        targets[bone.name] = (foot, chain)
    return targets


def characterize(bones):
    """The body of a rig for the full-body bake, whatever its bones are called; None without hips, two legs and rest
    positions.

    Gives the hips, the spine from the hips up, the neck and the head, and per side an arm, a leg and the fingers. An
    arm's chain runs from its clavicle, where it has one, or its upper arm to its hand, and a leg's from its thigh to
    its foot, twist bones in series included. A finger lists its bones from the first one after any metacarpal.
    Names decide where the matcher is sure, the skeleton's shape elsewhere (see Rig.infer_body), with one check that
    matching does without: a clavicle found by shape must start nearer the middle of the body than the hip joint on
    its side, since an upper arm followed by a twist bone in series looks like a clavicle followed by an upper arm. An
    elbow or knee that names do not place on its limb is the bone nearest the middle of the limb. shape lists the
    parts that came from the skeleton's shape: hips, spine, neck, head, fingers, and limb parts such as L.forearm.
    """
    rig = Rig(bones)
    heads = {name: info.head for name, info in rig.bones.items()}
    hips = rig.roles.get(('', 'hips'))
    if not hips or None in heads.values():
        return None
    dropped = set()  # Clavicles that the shape check turned back into upper arms.

    def path(top, bottom):
        """The bones from top down to bottom, or [] where bottom does not hang below top."""
        if top not in rig.bones or bottom not in rig.bones:
            return []
        result = [bottom]
        while result[-1] != top:
            if not rig.bones[result[-1]].parent:
                return []
            result.append(rig.bones[result[-1]].parent)
        return result[::-1]

    def joint(chain, named):
        """A limb's middle joint: the named one where it lies on the limb, else the bone nearest the limb's middle."""
        if named in chain[1:-1]:
            return named
        middle = [(a + b) / 2 for a, b in zip(heads[chain[0]], heads[chain[-1]])]
        return min(chain[1:-1], key=lambda name: distance(heads[name], middle))

    legs = {}
    for side in 'LR':
        chain = path(rig.roles.get((side, 'thigh')), rig.roles.get((side, 'foot')))
        if len(chain) >= 3:
            toe = rig.roles.get((side, 'toe'))
            legs[side] = dict(thigh=chain[0], calf=joint(chain, rig.roles.get((side, 'calf'))), foot=chain[-1],
                              toe=toe if toe and chain[-1] in rig.ancestors(toe) else None, chain=chain)
    if len(legs) < 2:
        return None
    arms = {}
    for side in 'LR':
        clavicle, upper, hand = (rig.roles.get((side, role)) for role in ('clavicle', 'upperarm', 'hand'))
        forearm = rig.roles.get((side, 'forearm'))
        if clavicle and (side, 'clavicle') in rig.inferred and rig.body:
            centre, left = rig.body['centre'], rig.body['left']
            if abs(dot(sub(heads[clavicle], centre), left)) >= abs(dot(sub(heads[legs[side]['thigh']], centre), left)):
                clavicle, upper, forearm = None, clavicle, None
                dropped.add(side + '.clavicle')
        chain = path(upper, hand)
        if len(chain) < 3:
            continue
        if clavicle and clavicle not in rig.ancestors(upper):
            clavicle = None
        arms[side] = dict(clavicle=clavicle, upperarm=upper, forearm=joint(chain, forearm), hand=hand,
                          chain=path(clavicle, hand) if clavicle else chain)
    spine, neck, head = rig.chain('spine'), rig.chain('neck'), rig.roles.get(('', 'head'))
    spine = path(spine[0], spine[-1]) or spine if spine else []
    if neck and head:
        neck = path(neck[0], head)[:-1] or neck
    fingers, metacarpals = {}, {}
    for name, (number, segment) in rig.fingers.items():
        side = rig.bones[name].side
        if side in arms and arms[side]['hand'] in rig.ancestors(name):
            if segment == 0:
                metacarpals.setdefault(side, {})[number] = name
            else:
                fingers.setdefault(side, {}).setdefault(number, []).append(name)
    for digits in fingers.values():
        for names in digits.values():
            names.sort(key=lambda name: rig.bones[name].depth)
    found = {'.'.join(filter(None, key)) if isinstance(key, tuple) else key for key in rig.inferred} - dropped
    return dict(hips=hips, spine=spine, neck=neck, head=head, arms=arms, legs=legs, fingers=fingers,
                metacarpals=metacarpals, shape=sorted(found))


def body_pairs(source, target):
    """Where each bone of the target's body takes its motion from on the source's body; None when either rig has no
    body (see characterize).

    Chains pair up between the joints that both rigs have: the spine from its first bone through the chest to the
    neck, the neck to the head, an arm through its shoulder (and clavicle, where both rigs have one) and elbow to the
    wrist, a leg through its knee to the ankle, a finger from its first bone to its last. Between two joints the bone
    counts may differ: a target bone takes the source's chain at the same share of the way, by length, the motion of
    the two source bones there blended, and its segment follows the source chain over the same share. Where both rigs
    have as many bones between two joints, the bones pair one to one. The hips, head, hands, feet, toes, metacarpals
    and the last bone of each finger pair directly.

    Returns dict(source=, target= the two characterizations, direct={target bone: source bone}, chains={target bone:
    dict(end=the target bone whose head ends its segment, blend=, start=, stop=)}, unpaired=[target body bones without
    a counterpart, such as a clavicle where the source has none]). blend names the two source bones whose motions mix
    and the second one's part; start and stop are the ends of the source segment, each as (source bone, source bone,
    part of the way from the first one's head to the second's).
    """
    source, target = list(source), list(target)
    src, dst = characterize(source), characterize(target)
    if not src or not dst:
        return None
    source_heads = {bone.name: tuple(bone.head) for bone in source}
    target_heads = {bone.name: tuple(bone.head) for bone in target}
    direct, chains, unpaired = {dst['hips']: src['hips']}, {}, []

    def shares(points, heads):
        """Each point's share of the way along a chain, by length."""
        lengths = [0.0]
        for a, b in zip(points, points[1:]):
            lengths.append(lengths[-1] + distance(heads[a], heads[b]))
        return [length / lengths[-1] if lengths[-1] > 1e-9 else index / (len(points) - 1) for index, length in enumerate(lengths)]

    def chain(mine, theirs, joints):
        """Pair a target chain with a source chain, each listed with the bone that ends it; joints are the (target
        index, source index) of the joints they share, in order from the first bones to the end."""
        for (a, c), (b, d) in zip(joints, joints[1:]):
            part, other = mine[a:b + 1], theirs[c:d + 1]
            if len(part) < 2 or len(other) < 2:
                continue
            if len(part) == len(other):
                for k, name in enumerate(part[:-1]):
                    chains[name] = dict(end=part[k + 1], blend=(other[k], other[k], 0.0), start=(other[k], other[k], 0.0),
                                        stop=(other[k + 1], other[k + 1], 0.0))
                continue
            along, scale = shares(part, target_heads), shares(other, source_heads)

            def at(share):
                k = next((k for k in range(len(other) - 1) if share <= scale[k + 1] + 1e-9), len(other) - 2)
                span = scale[k + 1] - scale[k]
                return other[k], other[k + 1], min(1.0, max(0.0, (share - scale[k]) / span)) if span > 1e-9 else 0.0
            for k, name in enumerate(part[:-1]):
                chains[name] = dict(end=part[k + 1], blend=at(along[k]), start=at(along[k]), stop=at(along[k + 1]))

    tops = [(body['neck'] or [body['head']])[0] for body in (dst, src)]
    if dst['spine'] and src['spine']:
        mine, theirs = dst['spine'] + tops[:1], src['spine'] + tops[1:]
        if not all(tops):
            # Nothing above the chest: the chests pair directly and the chains end at them.
            mine, theirs = dst['spine'], src['spine']
            direct[mine[-1]] = theirs[-1]
        joints = [(0, 0)]
        if all(tops) and len(dst['spine']) > 1 and len(src['spine']) > 1:
            joints.append((len(dst['spine']) - 1, len(src['spine']) - 1))  # The chests, which carry arms and neck.
        chain(mine, theirs, joints + [(len(mine) - 1, len(theirs) - 1)])
    else:
        unpaired += dst['spine']
    if dst['neck'] and src['neck'] and dst['head'] and src['head']:
        chain(dst['neck'] + [dst['head']], src['neck'] + [src['head']], [(0, 0), (len(dst['neck']), len(src['neck']))])
    else:
        unpaired += dst['neck']
    if dst['head'] and src['head']:
        direct[dst['head']] = src['head']
    elif dst['head']:
        unpaired.append(dst['head'])
    for side in 'LR':
        mine, theirs = dst['legs'][side], src['legs'][side]
        a, b = mine['chain'], theirs['chain']
        chain(a, b, [(0, 0), (a.index(mine['calf']), b.index(theirs['calf'])), (len(a) - 1, len(b) - 1)])
        direct[mine['foot']] = theirs['foot']
        if mine['toe'] and theirs['toe']:
            direct[mine['toe']] = theirs['toe']
        elif mine['toe']:
            unpaired.append(mine['toe'])
        mine, theirs = dst['arms'].get(side), src['arms'].get(side)
        if not mine or not theirs:
            unpaired += mine['chain'] if mine else []
            continue
        a, b = mine['chain'], theirs['chain']
        roles = ('upperarm', 'forearm')
        if mine['clavicle'] and theirs['clavicle']:
            roles = ('clavicle',) + roles
        else:
            unpaired += a[:a.index(mine['upperarm'])]
            a, b = a[a.index(mine['upperarm']):], b[b.index(theirs['upperarm']):]
        chain(a, b, [(a.index(mine[role]), b.index(theirs[role])) for role in roles] + [(len(a) - 1, len(b) - 1)])
        direct[mine['hand']] = theirs['hand']
        digits, others = dst['fingers'].get(side, {}), src['fingers'].get(side, {})
        for number, a in digits.items():
            b = others.get(number)
            if not b:
                unpaired += a
            elif len(a) > 1 and len(b) > 1:
                chain(a, b, [(0, 0), (len(a) - 1, len(b) - 1)])
                direct[a[-1]] = b[-1]
            else:
                direct[a[0]] = b[0]
                unpaired += a[1:]
        for number, name in dst['metacarpals'].get(side, {}).items():
            if number in src['metacarpals'].get(side, {}):
                direct[name] = src['metacarpals'][side][number]
            else:
                unpaired.append(name)
    return dict(source=src, target=dst, direct=direct, chains=chains, unpaired=unpaired)
