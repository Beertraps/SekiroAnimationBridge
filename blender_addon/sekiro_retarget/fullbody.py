"""The full-body bake: an experimental bake method beside the bone-by-bone one.

It needs no bone list for the body. Both rigs are characterized (see mapping.characterize): the hips, spine,
neck, head, clavicles, arms, legs, hands, feet and fingers are found by name where the matcher is sure and by the
skeleton's shape elsewhere. Each chain then takes the source chain's shape and twist over however many bones it
has (see mapping.body_pairs): a bone takes the source's motion at the same share of the way along its chain, and
its segment lies along the source chain over the same share. A last pass keeps the contacts that other
proportions break: each foot goes where the source's foot goes, measured from the hips and scaled by leg length,
set to the target's own hip width without sliding where it stands, with the pelvis lowered where a leg could not
reach otherwise, and where the source's hands are together, the target's hands come as close as the source's,
scaled by arm length. Elbows and knees keep pointing where the chain transfer turns them, which is where the
source's point; the hips, head, hands and feet keep the source's world rotations.

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
# A foot stands where it moves slower than this many leg lengths per second, measured where the game puts it.
STAND = .25
# Biped-style footsteps (see footsteps): a point of the foot is planted over a stretch of at least PLANT_TIME seconds
# where it stays within the tolerance of where the stretch starts, and pins and ground corrections ease in and out
# over EASE_TIME seconds; a whole pivot weighs on a pin from BLEND_TIME seconds into its stretch.
PLANT_TIME, EASE_TIME, BLEND_TIME = .1, .1, .05
PIVOTS = ('heel', 'ankle', 'ball', 'tip')
# A jump's arc is scaled by at most this factor either way.
ARC_LIMIT = 4.0


def plan(source, target, rows, tracked_only, given=(None, None)):
    """The body template of a source and target pair (see mapping.body_pairs), with the bone map for the bake.

    The bone map holds the directly paired bones, each chain bone with the source bone nearest to where it sits
    on its chain where no other target bone has that one (joints first), and for bones outside the body the bone
    list's rows, or what automatic matching finds where the list is empty. given holds the body layouts of the
    source's and the target's saved figures, or None for a rig without one (see figure.layout).
    """
    pairs = matching.body_pairs(retarget.rig_bones(source), retarget.rig_bones(target), given)
    if pairs is None:
        rig = 'source' if matching.characterize(retarget.rig_bones(source), given[0]) is None else 'target'
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
    them: a hunched source would otherwise hunch the target in every frame. A hand points to its knuckles and lies
    about that line as the source's hand (see retarget.align_hand). They and the other bones keep their nearest
    turned ancestor's rotation, as in retarget.stance_alignment. rotation maps source armature directions into the
    target's.
    """
    heads = {bone.name: bone.head_local for bone in source.data.bones}
    hands = retarget.stance_hands(source, target, bone_map)
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
        if bone.name in hands and bone.name not in kept:
            alignment = retarget.align_hand(alignment, bone.name, hands[bone.name], source, target, bone_map, rotation)
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


def level(vector, up):
    """vector without its part along up, of length 1; None where it points nearly along up."""
    flat = vector - up * vector.dot(up)
    return flat.normalized() if flat.length > .1 * vector.length > 0 else None


def held(sides, flags, up):
    """Per frame, a sideways direction that holds still over each stretch of frames where flags is true, at the mean
    of sides over it. Elsewhere it turns with sides, off them by an angle about up that eases from the one at the end
    of the stretch before to the one at the start of the stretch after, so that it joins each stretch without a jump;
    before the first stretch and after the last it keeps the angle there. Without any stretch, sides as they are."""
    stretches = retarget.runs(flags)
    if not stretches:
        return list(sides)

    def off(side, mean):
        """The turn about up from side to mean, in radians."""
        return math.atan2(up.dot(side.cross(mean)), side.dot(mean))
    means = [(start, end, level(sum(sides[start:end], Vector()), up) or sides[start]) for start, end in stretches]
    first, last = off(sides[means[0][0]], means[0][2]), off(sides[means[-1][1] - 1], means[-1][2])
    result = [Quaternion(up, first) @ side for side in sides[:means[0][0]]]
    for (start, end, mean), following in zip(means, means[1:] + [None]):
        result += [mean] * (end - start)
        if following is None:
            result += [Quaternion(up, last) @ side for side in sides[end:]]
            continue
        leaving, joining, gap = off(sides[end - 1], mean), off(sides[following[0]], following[2]), following[0] - end + 1
        for t in range(end, following[0]):
            x = (t - end + 1) / gap
            result.append(Quaternion(up, leaving + (joining - leaving) * x * x * (3 - 2 * x)) @ sides[t])
    return result


def smooth(x):
    return x * x * (3 - 2 * x)


def footsteps(source, target, layout, legs, pose_frames, samples, feet, footing, travel, rate, rotation, game):
    """Biped-style footsteps: per leg, whether its foot is planted, sliding or free on each frame, and what pins it.

    Each source foot has four points it can stand on, its heel, ankle, ball and toe tip, from the source's figure
    (see figure.measures). The source's foot carries them on every frame (feet holds its armature-space matrices),
    and they are scaled into the target's place as the foot's goal is (see keep_contacts), where the game puts them.
    A point is planted over each stretch of at least PLANT_TIME where it stays on the ground and within footing's
    tolerance, in source foot lengths, scaled, of where the stretch starts, as Biped extracts footsteps from motion
    capture; a point counts as on the ground within the same tolerance of its height at rest. The foot is
    planted where any of its points is, and can roll from its heel to its toe. A foot that is not planted slides
    over each stretch of at least PLANT_TIME where its lowest point stays within the same tolerance of the ground,
    and is free elsewhere. The ground is the source figure's sole, scaled into the target's place like the feet.

    Per leg: aims, each point's place per frame in the target's armature space; stretches, each point's planted
    stretches; states; low, where its lowest point is on the ground; carry, each point on the target's foot as the
    bone that carries it and its place in that bone's rest space; correct, how far the target's foot stands higher
    than the scaled source foot when that point is on the ground, from its own sole and the target's ground.
    """
    hips, direct = layout['target']['hips'], layout['direct']
    mine, theirs = footing['target'], footing['source']
    bones, source_bones, up = target.data.bones, source.data.bones, mine['up']
    hips_t, hips_s = bones[hips].head_local, source_bones[direct[hips]].head_local
    # The source's ground, scaled into the target's place, and how far the target's own ground lies above it.
    floor = (hips_t + rotation @ (hips_s - theirs['up'] * (hips_s.dot(theirs['up']) - theirs['ground']) - hips_s) * travel).dot(up)
    shift = mine['ground'] - floor
    least, count = max(2, round(PLANT_TIME * rate)), len(pose_frames)
    result = []
    for leg in legs:
        side, foot, source_foot = leg['side'], leg['chain'][2], leg['source']
        theirs_at, mine_at = theirs['pivots'][side], mine['pivots'][side]
        tolerance = footing['tolerance'] * theirs['feet'][side] * travel
        # The toe tip rides on the toe bone where both feet have one, so that it stays down while the toes bend.
        toe = leg['toe'] if leg['toe'] in bones and direct.get(leg['toe']) in feet[0] else None
        carriers = {k: (toe, direct[toe]) if toe and k == 'tip' else (foot, source_foot) for k in PIVOTS}
        local = {k: source_bones[carriers[k][1]].matrix_local.inverted() @ theirs_at[k] for k in PIVOTS}
        carry = {k: (carriers[k][0], bones[carriers[k][0]].matrix_local.to_quaternion().inverted()
                     @ (mine_at[k] - bones[carriers[k][0]].head_local)) for k in PIVOTS}
        lift = {k: theirs_at[k].dot(theirs['up']) - theirs['ground'] for k in PIVOTS}
        correct = {k: shift + mine_at[k].dot(up) - mine['ground'] - travel * lift[k] for k in PIVOTS}
        aims = {k: [poses[hips].translation + rotation @ (frames[carriers[k][1]] @ local[k] - sample[direct[hips]]) * travel
                    for poses, sample, frames in zip(pose_frames, samples, feet)] for k in PIVOTS}
        places = {k: [game(t, aim) for t, aim in enumerate(values)] for k, values in aims.items()}
        heights = [{k: places[k][t].dot(up) - floor - travel * lift[k] for k in PIVOTS} for t in range(count)]
        stretches, planted = {}, [False] * count
        for k in PIVOTS:
            found, start = [], 0
            while start < count:
                end = start + 1 if heights[start][k] <= tolerance else start
                while end < count and heights[end][k] <= tolerance and (places[k][end] - places[k][start]).length <= tolerance:
                    end += 1
                if end - start >= least:
                    found.append((start, end))
                    planted[start:end] = [True] * (end - start)
                    start = end
                else:
                    start += 1
            stretches[k] = found
        low = [min(values.values()) <= tolerance for values in heights]
        sliding = [False] * count
        for start, end in retarget.runs([on and not still for on, still in zip(low, planted)]):
            if end - start >= least:
                sliding[start:end] = [True] * (end - start)
        result.append(dict(aims=aims, stretches=stretches, low=low, carry=carry, correct=correct,
                           states=['planted' if p else 'sliding' if s else 'free' for p, s in zip(planted, sliding)]))
    return result


def jumps(steps, pose_frames, goals, carried, hips, ground, up, ratio):
    """Scale each jump's arc by ratio, keeping its time in the air; returns the jumps.

    A jump runs over the frames where no foot is planted, sliding or on the ground, between frames where one is.
    Biped's gravity scales with the figure's height, so that a jump of the same time in the air rises in proportion
    to the figure: the hips' height in the game, above the line from their height at lift-off to their height at
    touchdown, is scaled by ratio, the target's height against the source's, scaled by travel. The body and the
    feet in the air move with the hips.
    """
    count = len(pose_frames)
    airborne = [all(step['states'][t] == 'free' and not step['low'][t] for step in steps) for t in range(count)]

    def height(t):
        return (pose_frames[t][hips].translation + (ground[t][0] if ground else Vector())).dot(up)
    result = []
    for start, end in retarget.runs(airborne):
        if start == 0 or end == count or end - start < 2:
            continue
        before, after, span = height(start - 1), height(end), end - start + 1
        rises = []
        for t in range(start, end):
            rise = height(t) - (before + (after - before) * (t - start + 1) / span)
            change = (ratio - 1) * rise
            for name in carried:
                pose_frames[t][name].translation += up * change
            for i in range(len(goals[t])):
                goals[t][i] += up * change
            rises.append((rise, rise + change))
        top = max(rises, key=lambda item: abs(item[0]))
        result.append(dict(frames=(start + 1, end), rise=top[0], scaled=top[1]))
    return result


def pins(legs, steps, goals, widths, pose_frames, rate, game, ungame, up):
    """Move each foot's goal so that its planted points stand still and a sliding foot stays on the ground.

    A planted point of the target's own foot stays where it stands on average over its stretch: along the ground
    where the foot's goal carries it, as high as the source's point, scaled, and raised by the point's ground
    correction (see footsteps). The ankle goes where that point, turned as the foot is, lies on that place. Where
    several points are planted, the ankle takes their places' mean along the ground, each point weighing in fully
    from BLEND_TIME into its stretch, so that the foot rolls from heel to toe. A foot stands as high as the lowest of
    its points needs, the planted ones or, sliding, all of them, so that a foot the target holds at another angle
    than the source does keeps its points on or above the ground; a sliding foot keeps the source's path along it.
    The change eases out over EASE_TIME into the frames on either side: the height of a sliding foot and all of a
    free foot's. Returns per leg its steps, slides, the largest pin in armature units and the points it stood on.
    """
    count = len(goals)
    reach, blend = max(1, round(EASE_TIME * rate)), max(1, round(BLEND_TIME * rate))
    result = []
    for i, (leg, step) in enumerate(zip(legs, steps)):
        foot, states = leg['chain'][2], step['states']

        def away(t, k):
            """Point k of the target's foot from its ankle on frame t."""
            bone, offset = step['carry'][k]
            pose = pose_frames[t][bone]
            return pose.translation - pose_frames[t][foot].translation + pose.to_quaternion() @ offset

        def ankle(t, k, point):
            """The ankle that puts point k of the target's foot on a place, on the ground, on frame t."""
            return point + up * step['correct'][k] - away(t, k)

        def place(t, k):
            """Where point k of the target's foot stands on frame t, in the game: along the ground where the foot's
            goal carries it, at the height of the source's point."""
            mine = game(t, goals[t][i] + away(t, k))
            return mine - up * mine.dot(up) + up * game(t, step['aims'][k][t] + widths[i][t]).dot(up)
        shares, used = [{} for _ in range(count)], {}
        for k, found in step['stretches'].items():
            for start, end in found:
                anchor = sum((place(t, k) for t in range(start, end)), Vector()) / (end - start)
                for t in range(start, end):
                    shares[t][k] = (smooth(min(1.0, (t - start + 1) / blend, (end - t) / blend)), ankle(t, k, ungame(t, anchor)))
        raw, largest = [None] * count, 0.0
        for t in range(count):
            if states[t] == 'planted':
                total = sum(weight for weight, place in shares[t].values())
                mean = sum((place * weight for weight, place in shares[t].values()), Vector()) / total
                # The ankle as high as the lowest planted point needs, eased by its weight, so that no point sinks.
                height = mean.dot(up)
                height = max(height + weight * (place.dot(up) - height) for weight, place in shares[t].values())
                raw[t] = mean + up * (height - mean.dot(up)) - goals[t][i]
                largest = max(largest, raw[t].length)
                main = max(shares[t], key=lambda k: shares[t][k][0])
                used[main] = used.get(main, 0) + 1
            elif states[t] == 'sliding':
                height = max(ankle(t, k, step['aims'][k][t] + widths[i][t]).dot(up) for k in PIVOTS)
                raw[t] = up * (height - goals[t][i].dot(up))

        def nearest(t, kinds, values):
            """The change on the nearest frame within reach whose state is in kinds, eased by distance, or None."""
            for distance in range(1, reach + 1):
                for u in (t - distance, t + distance):
                    if 0 <= u < count and states[u] in kinds and values[u] is not None:
                        return values[u] * smooth(1 - distance / (reach + 1))
            return None
        final = list(raw)
        for t in range(count):
            if states[t] == 'sliding':
                near = nearest(t, ('planted',), raw)
                if near is not None:
                    final[t] = raw[t] + near - up * near.dot(up)
        for t in range(count):
            if states[t] == 'free':
                final[t] = nearest(t, ('planted', 'sliding'), final)
        for t in range(count):
            if final[t] is not None:
                goals[t][i] += final[t]
        result.append(dict(steps=len(retarget.runs([state == 'planted' for state in states])),
                           slides=len(retarget.runs([state == 'sliding' for state in states])),
                           sliding=[t + 1 for t in range(count) if states[t] == 'sliding'], pinned=largest,
                           pivots={k: used[k] for k in PIVOTS if k in used}))
    return result


def keep_contacts(source, target, layout, pose_frames, samples, travel, rate, rotation, carried, holds, placed, armed, forward,
                  ground=None, gripped=None, knuckles=None, footing=None):
    """Keep the feet on the source's footprint and the hands together where the source's are; returns what moved.

    Each foot's goal is where the source's foot is, measured from the source's hips, scaled by travel and measured
    from the target's hips, so a foot that stands still in the source stands still in the target. The goal then moves
    sideways by how much farther from the middle the target's hip joint sits than the source's, scaled, so that the
    feet stand the target's own hip width apart and each leg leans out as far as the source's. That move points
    sideways from the pelvis, but holds still over each stretch of frames where the foot stands, moving slower than
    STAND leg lengths per second, so that it adds no sliding; while the foot steps, it turns with the pelvis again.
    ground gives per frame the move and the turn about up that root motion adds, in armature units, where the target
    takes the source's root motion, so that standing is measured where the game puts the feet. The pelvis then drops
    by the least that lets both legs reach their goals, at most DROP of the shorter leg, eased in and out over 0.1 s.
    Each leg then reaches its goal by two-bone IK: the knee keeps the side it bends to, or bends forward
    where the leg is straight, and the foot keeps its rotation. Where the source's wrists come within 0.6 of its
    forearm's length of each other, the target's wrists move to the source's distance and direction apart, scaled
    by arm length, each by half; where only one hand holds a weapon, the other hand moves all the way, so that the
    weapon stays where the bake put it and Second hand can still put the free hand on its grip.
    The weight fades out by a forearm's length, but holds wherever gripped, per frame from 0 to 1, says the source holds
    its weapon with both hands (see retarget.both_hands), so that the hands stay together on a long hilt such as Owl's,
    where his wrists are 0.6 to 0.9 of his forearm apart; it is averaged over 0.05 s. As far as gripped says, the
    middles of the knuckles keep the source's distance and direction apart rather than the wrists, since the hilt
    passes through them and hands of other sizes than the arms', such as Isshin's against Owl's, put them elsewhere;
    knuckles gives per target hand its finger roots and the source's (see retarget.stance_hands). samples
    holds the source bones' armature-space positions per frame; carried, the bones that move with the body; holds
    and placed, the weapons that the bake placed in a hand (see retarget.weapon_holds), which move with that hand;
    armed, the hands that hold a weapon (see retarget.hand_weapons).

    footing turns on what Biped does with footsteps: dict(source=, target= the two figures' measures (see
    figure.measures), feet= the source feet's armature-space matrices per frame, tolerance= in foot lengths,
    pins=, jumps=, ratio= the jumps' scale). With pins, a foot stands where footsteps finds it planted or sliding
    rather than where it moves slower than STAND, and its planted points stand still on the ground (see pins);
    with jumps, each jump's arc is scaled by ratio (see jumps), before the feet's goals are set to the hip width.
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
    legs = [dict(limb((leg['thigh'], leg['calf']), leg['foot'], direct[leg['foot']], ahead), side=side, toe=leg.get('toe'))
            for side, leg in sorted(body['legs'].items())]
    goals = [[poses[hips].translation + rotation @ (sample[leg['source']] - sample[direct[hips]]) * travel for leg in legs]
             for poses, sample in zip(pose_frames, samples)]

    def turn_of(t):
        """The turn about up that root motion adds on frame t."""
        return Quaternion(up, ground[t][1]) if ground else Quaternion()

    def game(t, point):
        """Where the game puts a point of the target's armature space on frame t."""
        return turn_of(t) @ point + (ground[t][0] if ground else Vector())

    def ungame(t, point):
        return turn_of(t).inverted() @ (point - (ground[t][0] if ground else Vector()))
    steps = footsteps(source, target, layout, legs, pose_frames, samples, footing['feet'], footing, travel, rate, rotation,
                      game) if footing else None
    leaps = jumps(steps, pose_frames, goals, carried, hips, ground, up, footing['ratio']) if footing and footing['jumps'] else []
    widths = [[Vector()] * len(goals) for leg in legs]
    across = level(bones[legs[0]['chain'][0]].head_local - bones[legs[-1]['chain'][0]].head_local, up)  # Toward the left.
    if across is not None:
        heads, sources = {bone.name: bone.head_local for bone in source.data.bones}, layout['source']['legs']
        # With figures, the hip joints are where the figures put them.
        figures = (footing['target'], footing['source']) if footing else None
        sides, last = [], across  # The pelvis's sideways direction per frame, where the game turns it.
        for t, poses in enumerate(pose_frames):
            last = level(turn_of(t) @ poses[hips].to_quaternion() @ rest_hips @ across, up) or last
            sides.append(last)
        for i, leg in enumerate(legs):
            if figures and leg['side'] in figures[0]['thighs'] and leg['side'] in figures[1]['thighs']:
                own = figures[0]['thighs'][leg['side']] - figures[0]['hips']
                theirs = rotation @ (figures[1]['thighs'][leg['side']] - figures[1]['hips']) * travel
            else:
                own = bones[leg['chain'][0]].head_local - bones[hips].head_local
                theirs = rotation @ (heads[sources[leg['side']]['thigh']] - heads[direct[hips]]) * travel
            leg['width'] = (own - theirs).dot(across)
            if footing and footing['pins']:
                stands = [state != 'free' for state in steps[i]['states']]
            else:
                places = [game(t, aims[i]) for t, aims in enumerate(goals)]
                limit, end = STAND * leg['length'] / rate, len(places) - 1
                stands = [(places[min(end, t + 1)] - places[max(0, t - 1)]).length <= limit * (min(end, t + 1) - max(0, t - 1))
                          for t in range(len(places))]
            leg['stands'] = len(retarget.runs(stands))
            for t, side in enumerate(held(sides, stands, up)):
                widths[i][t] = turn_of(t).inverted() @ side * leg['width']
                goals[t][i] += widths[i][t]
    placing = pins(legs, steps, goals, widths, pose_frames, rate, game, ungame, up) if footing and footing['pins'] else None
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
        weights = [max(retarget.fade((sample[arms[0]['source']] - sample[arms[1]['source']]).length / unit, .6, 1.0),
                       gripped[t] if gripped else 0.0) for t, sample in enumerate(samples)]
        weights = retarget.smoothed(weights, max(1, round(.05 * rate)))
        holding = [arm['chain'][2] in armed for arm in arms]
        shares = (.5, .5) if holding[0] == holding[1] else tuple(0.0 if weapon else 1.0 for weapon in holding)
        roots = [knuckles.get(arm['chain'][2]) for arm in arms] if knuckles else [None, None]

        def end(t, i, places, own):
            """The wrist of arm i, or as far toward its knuckles as gripped says, where the hilt passes through."""
            wrist = places[arms[i]['chain'][2] if own else arms[i]['source']]
            wrist = wrist.translation if own else wrist
            grip = gripped[t] if gripped and all(roots) else 0.0
            if grip < 1e-3:
                return wrist.copy()
            names = roots[i][0 if own else 1]
            middle = sum(((places[name].translation if own else places[name]) for name in names), Vector()) / len(names)
            return wrist.lerp(middle, grip)
        for t, (poses, sample, weight) in enumerate(zip(pose_frames, samples, weights)):
            if weight < 1e-3:
                continue
            apart = rotation @ (end(t, 1, sample, False) - end(t, 0, sample, False)) * ratio
            excess = (end(t, 1, poses, True) - end(t, 0, poses, True)) - apart
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
                           gap=leg['gap'] * scale, stands=leg.get('stands', 0),
                           outward=leg.get('width', 0.0) * (1 if leg['side'] == 'L' else -1) * scale) for leg in legs],
                hands=[dict(side=arm['side'], hand=arm['chain'][2], frames=arm['frames'], moved=arm['moved'] * scale)
                       for arm in arms if arm['frames']],
                footsteps=[dict(item, side=leg['side'], pinned=item['pinned'] * scale) for leg, item in zip(legs, placing)]
                if placing else None,
                jumps=[dict(item, rise=item['rise'] * scale, scaled=item['scaled'] * scale) for item in leaps])
