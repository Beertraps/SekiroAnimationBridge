"""The full-body bake: an experimental bake method beside the bone-by-bone one.

It needs no bone list for the body. Both rigs are characterized (see mapping.characterize): the hips, spine,
neck, head, clavicles, arms, legs, hands, feet and fingers are found by name where the matcher is sure and by the
skeleton's shape elsewhere. Each chain then takes the source chain's shape and twist over however many bones it
has (see mapping.body_pairs): a bone takes the source's motion at the same share of the way along its chain, and
its segment lies along the source chain over the same share. A last pass keeps the contacts that other
proportions break: each foot goes where the source's foot goes, measured from the hips and scaled by leg length,
with the pelvis lowered where a leg could not reach otherwise, and where the source's hands are together, the
target's hands come as close as the source's, scaled by arm length. Elbows and knees keep pointing where the chain
transfer turns them, which is where the source's point; the hips, head, hands and feet keep the source's world
rotations.

The solver is closed-form rather than iterative: the pelvis drop is the smallest one that lets both legs reach,
and each limb is two-bone IK (retarget.move_hand), so the result is exact, takes no iterations and does not depend
on the order in which frames are baked. Bones outside the body, such as weapons and helpers, take their source
bones from the bone list, or from automatic matching where the list is empty, and the bake treats them as the
bone-by-bone method does, with weapons, grips, second hands and body clearance.
"""
import math
from mathutils import Quaternion, Vector
from . import mapping as matching
from . import retarget

# Legs reach their goals up to this part of their length, so that a straight leg does not lock.
REACH = .9999
# The pelvis drops at most this part of the shorter leg; a foot farther away than that is a matter of the motion,
# not of proportions, and its leg stops short.
DROP = .25


def plan(source, target, rows, tracked_only):
    """The body template of a source and target pair (see mapping.body_pairs), with the bone map for the bake.

    The bone map holds the directly paired bones, each chain bone with the source bone nearest to where it sits
    on its chain where no other target bone has that one (joints first), and for bones outside the body the bone
    list's rows, or what automatic matching finds where the list is empty.
    """
    pairs = matching.body_pairs(retarget.rig_bones(source), retarget.rig_bones(target))
    if pairs is None:
        rig = 'source' if matching.characterize(retarget.rig_bones(source)) is None else 'target'
        raise ValueError(f'The full-body bake finds no body in the {rig}: it needs hips and two legs with knees. '
                         'Bake bone by bone instead.')
    bone_map = dict(pairs['direct'])
    used = set(bone_map.values())
    ordered = sorted(pairs['chains'].items(), key=lambda item: item[1]['blend'][2] > 0)
    for name, spec in ordered:
        first, second, part = spec['blend']
        nearest = first if part < .5 else second
        if nearest not in used:
            bone_map[name] = nearest
            used.add(nearest)
    body = set(pairs['direct']) | set(pairs['chains']) | set(pairs['unpaired'])
    extras = rows
    if not rows:
        def infos(rig):
            return retarget.rig_bones(rig, retarget.bone_infos(rig, tracked_only))
        extras = {row['target']: row['source'] for row in
                  matching.match_bones(infos(source), infos(target), retarget.hidden_bones(source)) if row['source']}
    others = 0
    for name, source_name in extras.items():
        if name not in body and source_name not in used:
            bone_map[name] = source_name
            used.add(source_name)
            others += 1
    return dict(pairs, bone_map=bone_map, others=others, listed=bool(rows))


def anatomy(body, layout):
    """An anatomy (see mapping.anatomy) with the hips, head, limbs, spine and neck of a characterization, for the
    passes that read limbs from it, such as body clearance and the second hand."""
    result = dict(body)
    parts = [(side, role, arm[role]) for side, arm in layout['arms'].items() for role in ('clavicle', 'upperarm', 'forearm', 'hand')]
    parts += [(side, role, leg[role]) for side, leg in layout['legs'].items() for role in ('thigh', 'calf', 'foot', 'toe')]
    for side, role, name in parts + [('', 'hips', layout['hips']), ('', 'head', layout['head'])]:
        if name:
            result[(side, role)] = name
        else:
            result.pop((side, role), None)
    result.update(spine=list(layout['spine']), neck=list(layout['neck']))
    return result


def parts(shape):
    """The body parts that a characterization found by shape (its shape list), in body order."""
    kinds = {name.split('.')[-1] for name in shape}
    order = [('hips', {'hips'}), ('spine', {'spine'}), ('neck', {'neck'}), ('head', {'head'}),
             ('arms', {'clavicle', 'upperarm', 'forearm', 'hand'}), ('legs', {'thigh', 'calf', 'foot', 'toe'}), ('fingers', {'fingers'})]
    return [part for part, names in order if kinds & names]


def point(heads, place):
    """A spot along a source chain, (bone, next bone, part of the way between them), from the bones' heads."""
    first, second, part = place
    return heads[first].lerp(heads[second], part)


def stance(source, target, bone_map, chains, rotation, kept=frozenset()):
    """Per target bone that the bake turns, the rotation that stands it like the source's rest pose.

    A chain bone of the limbs and fingers turns so that its segment lies along the source chain over the same share
    of the way. The bones in kept, the spine and neck, keep the target's own stance, as the bone-by-bone bake keeps
    them: a hunched source would otherwise hunch the target in every frame. They and the other bones keep their
    nearest turned ancestor's rotation, as in retarget.stance_alignment. rotation maps source armature directions
    into the target's.
    """
    heads = {bone.name: bone.head_local for bone in source.data.bones}
    result = {}
    for bone in sorted(target.data.bones, key=lambda b: len(b.parent_recursive)):
        if bone.name not in bone_map and bone.name not in chains:
            continue
        parent = bone.parent
        while parent and parent.name not in result:
            parent = parent.parent
        alignment = result[parent.name].copy() if parent else Quaternion()
        spec = chains.get(bone.name) if bone.name not in kept else None
        if spec:
            have = alignment @ (target.data.bones[spec['end']].head_local - bone.head_local)
            want = rotation @ (point(heads, spec['stop']) - point(heads, spec['start']))
            if have.length > 1e-6 and want.length > 1e-6:
                alignment = have.rotation_difference(want) @ alignment
        result[bone.name] = alignment
    return result


def turns(chains, source_poses, source_rest, target_rest, stance, rotation):
    """Per chain bone of the target, its armature-space rotation on one frame.

    The bone takes the source's turn from rest where it sits along its chain, the two source bones' turns there
    blended, and then the further swing that lays its segment along the source chain over the same share of the
    way, as far as that part of the source chain moved from its rest pose. With matched rest stances the segment
    then points along the source chain; with the target's own stance it turns as far as the source chain does.
    source_poses and source_rest hold the source bones' armature-space matrices on this frame and at rest.
    """
    inverse = rotation.inverted()
    heads = {name: matrix.translation for name, matrix in source_poses.items()}
    rest_heads = {name: matrix.translation for name, matrix in source_rest.items()}
    deltas = {}

    def delta(name):
        """A source bone's turn from rest, in target armature space."""
        if name not in deltas:
            deltas[name] = rotation @ (source_poses[name].to_quaternion() @ source_rest[name].to_quaternion().inverted()) @ inverse
        return deltas[name]
    result = {}
    for name, spec in chains.items():
        first, second, part = spec['blend']
        turn = delta(first)
        if part > 0:
            other = delta(second).copy()
            if turn.dot(other) < 0:
                other.negate()
            turn = turn.slerp(other, part)
        moved = turn @ (rotation @ (point(rest_heads, spec['stop']) - point(rest_heads, spec['start'])))
        chord = rotation @ (point(heads, spec['stop']) - point(heads, spec['start']))
        if moved.length > 1e-9 and chord.length > 1e-9:
            turn = moved.rotation_difference(chord) @ turn
        result[name] = turn @ stance.get(name, Quaternion()) @ target_rest[name].to_quaternion()
    return result


def keep_contacts(source, target, layout, pose_frames, samples, travel, rate, rotation, carried, holds, placed, armed, forward):
    """Keep the feet on the source's footprint and the hands together where the source's are; returns what moved.

    Each foot's goal is where the source's foot is, measured from the source's hips, scaled by travel and measured
    from the target's hips, so a foot that stands still in the source stands still in the target. The pelvis first
    drops by the least that lets both legs reach their goals, at most DROP of the shorter leg, eased in and out over
    0.1 s. Each leg then reaches its goal by two-bone IK: the knee keeps the side it bends to, or bends forward
    where the leg is straight, and the foot keeps its rotation. Where the source's wrists come within 0.6 of its
    forearm's length of each other, the target's wrists move to the source's distance and direction apart, scaled
    by arm length, each by half; where only one hand holds a weapon, the other hand moves all the way, so that the
    weapon stays where the bake put it and Second hand can still put the free hand on its grip.
    The weight fades out by a forearm's length and is averaged over 0.05 s. samples
    holds the source bones' armature-space positions per frame; carried, the bones that move with the body; holds
    and placed, the weapons that the bake placed in a hand (see retarget.weapon_holds), which move with that hand;
    armed, the hands that hold a weapon (see retarget.hand_weapons).
    """
    bones, body, direct = target.data.bones, layout['target'], layout['direct']
    to_rig = target.matrix_world.to_3x3().inverted()
    up = (to_rig @ Vector((0, 0, 1))).normalized()
    ahead = (to_rig @ Vector(forward)).normalized() if forward else None
    hips = body['hips']
    rest_hips = bones[hips].matrix_local.to_quaternion().inverted()

    def limb(names, end, source_end, pole, kept=frozenset()):
        upper, fore = names
        heads = [bones[name].head_local for name in (upper, fore, end)]
        held = (retarget.subtree(bones, end) - kept).union(
            *(retarget.subtree(bones, name) for name, (holder, anchor) in holds.items() if holder == end))
        return dict(chain=(upper, fore, end), source=source_end, length=(heads[1] - heads[0]).length + (heads[2] - heads[1]).length,
                    held=held, upper=retarget.subtree(bones, upper) - retarget.subtree(bones, fore) - kept,
                    lower=retarget.subtree(bones, fore) - retarget.subtree(bones, end) - kept, pole=pole, frames=[], moved=0.0,
                    short=[], gap=0.0)
    legs = [dict(limb((leg['thigh'], leg['calf']), leg['foot'], direct[leg['foot']], ahead), side=side)
            for side, leg in sorted(body['legs'].items())]
    goals = [[poses[hips].translation + rotation @ (sample[leg['source']] - sample[direct[hips]]) * travel for leg in legs]
             for poses, sample in zip(pose_frames, samples)]
    drops, shortest = [], min(leg['length'] for leg in legs)
    for poses, aims in zip(pose_frames, goals):
        need = 0.0
        for leg, goal in zip(legs, aims):
            leg['moved'] = max(leg['moved'], (goal - poses[leg['chain'][2]].translation).length)
            offset = goal - poses[leg['chain'][0]].translation
            height, reach = offset.dot(up), REACH * leg['length']
            need = max(need, -height - math.sqrt(max(0.0, reach * reach - (offset.length_squared - height * height))))
        drops.append(max(0.0, min(need, DROP * shortest)))
    if any(drops):
        drops = retarget.ease(drops, max(1, round(.1 * rate)))
    for t, (poses, aims) in enumerate(zip(pose_frames, goals)):
        if drops[t] > 0:
            for name in carried:
                poses[name].translation -= up * drops[t]
        turn = poses[hips].to_quaternion() @ rest_hips
        for leg, goal in zip(legs, aims):
            foot = leg['chain'][2]
            retarget.move_hand(poses, leg['chain'], leg['held'], leg['upper'], leg['lower'], goal - poses[foot].translation,
                               turn @ ahead if ahead else None)
            gap = (poses[foot].translation - goal).length
            if gap > .01 * leg['length']:
                leg['short'].append(t + 1)
                leg['gap'] = max(leg['gap'], gap)

    arms = [dict(limb((arm['upperarm'], arm['forearm']), arm['hand'], direct[arm['hand']], -up, placed), side=side)
            for side, arm in sorted(body['arms'].items()) if arm['hand'] in direct]
    if len(arms) == 2:
        sides = [layout['source']['arms'][arm['side']] for arm in arms]
        rest = {bone.name: bone.head_local for bone in source.data.bones}
        forearms = [(rest[arm['hand']] - rest[arm['forearm']]).length for arm in sides]
        lengths = [(rest[arm['forearm']] - rest[arm['upperarm']]).length + forearm for arm, forearm in zip(sides, forearms)]
        unit, ratio = sum(forearms) / 2, sum(arm['length'] for arm in arms) / sum(lengths)
        weights = [retarget.fade((sample[arms[0]['source']] - sample[arms[1]['source']]).length / unit, .6, 1.0) for sample in samples]
        weights = retarget.smoothed(weights, max(1, round(.05 * rate)))
        holding = [arm['chain'][2] in armed for arm in arms]
        shares = (.5, .5) if holding[0] == holding[1] else tuple(0.0 if weapon else 1.0 for weapon in holding)
        for t, (poses, sample, weight) in enumerate(zip(pose_frames, samples, weights)):
            if weight < 1e-3:
                continue
            apart = rotation @ (sample[arms[1]['source']] - sample[arms[0]['source']]) * ratio
            wrists = [poses[arm['chain'][2]].translation.copy() for arm in arms]
            excess = (wrists[1] - wrists[0]) - apart
            for arm, share, sign in zip(arms, shares, (1, -1)):
                if not share:
                    continue
                shift = excess * (sign * share * weight)
                retarget.move_hand(poses, arm['chain'], arm['held'], arm['upper'], arm['lower'], shift, arm['pole'])
                arm['frames'].append(t + 1)
                arm['moved'] = max(arm['moved'], shift.length)
    scale = retarget.uniform_scale(target)
    return dict(drop=max(drops, default=0.0) * scale, dropped=[t + 1 for t, drop in enumerate(drops) if drop * scale > 1e-4],
                feet=[dict(side=leg['side'], foot=leg['chain'][2], moved=leg['moved'] * scale, short=leg['short'],
                           gap=leg['gap'] * scale) for leg in legs],
                hands=[dict(side=arm['side'], hand=arm['chain'][2], frames=arm['frames'], moved=arm['moved'] * scale)
                       for arm in arms if arm['frames']])
