"""Bone matching of the Blender retarget add-on on owned synthetic skeletons (no Blender needed)."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import humanoids

# The add-on package imports bpy, so load its Blender-free matcher on its own.
spec = importlib.util.spec_from_file_location('retarget_mapping', HERE.parents[1] / 'blender_addon/sekiro_retarget/mapping.py')
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)

CORE = {'hips', 'spine.first', 'spine.last', 'neck', 'head'} | {
    f'{side}.{part}' for side in 'LR' for part in ('clavicle', 'upperarm', 'forearm', 'hand', 'thigh', 'calf', 'foot', 'toe')} | {
    f'{side}.{finger}.{segment}' for side in 'LR' for finger in humanoids.FINGERS for segment in (1, 2, 3)}
ROLE_LABELS = {('', 'hips'): 'hips', ('', 'head'): 'head'} | {
    (side, part): f'{side}.{part}' for side in 'LR' for part in ('clavicle', 'upperarm', 'forearm', 'hand', 'thigh', 'calf', 'foot', 'toe')}


def rigs():
    result = {name: build() for name, build in humanoids.CONVENTIONS.items()}
    # Names removed: only the hierarchy and rest positions remain.
    result.update(unnamed_mixamo=humanoids.scrambled(humanoids.mixamo(40), 1, 'Bone'),
                  unnamed_souls=humanoids.scrambled(humanoids.fromsoftware(0, 'souls'), 7, 'Item'),
                  unnamed_unreal=humanoids.scrambled(humanoids.unreal(40), 3, 'Joint'),
                  unnamed_daz=humanoids.scrambled(humanoids.daz(45), 5, 'Node'),
                  unnamed_biped=humanoids.scrambled(humanoids.biped(0), 11, 'Seg'))
    return result


def bones(rig):
    return [mapping.Bone(name, parent, head) for name, parent, head, label in rig]


def labels(rig):
    return {name: label for name, parent, head, label in rig}


class MatchConventions(unittest.TestCase):
    def test_every_convention_pair_matches_core_bones(self):
        everything = rigs()
        for target_name, target in everything.items():
            for source_name, source in everything.items():
                if source_name == target_name:
                    continue
                with self.subTest(source=source_name, target=target_name):
                    target_labels, source_labels = labels(target), labels(source)
                    present = set(source_labels.values())
                    wrong = []
                    for row in mapping.match_bones(bones(source), bones(target)):
                        label, got = target_labels[row['target']], source_labels.get(row['source'])
                        if label in CORE and label in present and got != label:
                            wrong.append(f"{label} <- {row['source'] or 'nothing'} ({row['reason']})")
                        if label is None and got in CORE:
                            wrong.append(f"helper {row['target']} took {row['source']}")
                    self.assertEqual(wrong, [])

    def test_unnamed_rigs_get_roles_chains_and_fingers_from_positions(self):
        for name, rig in rigs().items():
            if not name.startswith('unnamed'):
                continue
            with self.subTest(rig=name):
                found = mapping.Rig(bones(rig))
                truth = labels(rig)
                roles = {key: truth[bone] for key, bone in found.roles.items() if key in ROLE_LABELS}
                self.assertEqual(roles, {key: label for key, label in ROLE_LABELS.items() if label in truth.values()})
                self.assertEqual(truth[found.chain('spine')[0]], 'spine.first')
                self.assertEqual(truth[found.chain('spine')[-1]], 'spine.last')
                self.assertEqual(truth[found.chain('neck')[0]], 'neck')  # Daz adds neckUpper
                fingers = {truth[bone]: value for bone, value in found.fingers.items()}
                for side in 'LR':
                    for number, finger in enumerate(humanoids.FINGERS):
                        self.assertEqual(fingers[f'{side}.{finger}.1'], (number, 1))
                        self.assertEqual(fingers[f'{side}.{finger}.3'], (number, 3))

    def test_finger_roots_give_the_first_bone_of_each_finger_thumb_first(self):
        # Named and unnamed, with weapon, twist and helper bones beside the fingers in some conventions.
        expected = [(number, finger) for number, finger in enumerate(humanoids.FINGERS)]
        for name, rig in rigs().items():
            with self.subTest(rig=name):
                found, truth = mapping.Rig(bones(rig)), labels(rig)
                for side in 'LR':
                    roots = found.finger_roots(found.roles[(side, 'hand')])
                    self.assertEqual([(number, truth[bone]) for number, bone in roots],
                                     [(number, f'{side}.{finger}.1') for number, finger in expected])

    def test_tracked_subset_without_fingers_or_helpers_still_matches(self):
        full = humanoids.fromsoftware(45, 'elden')
        subset = [bone for bone in full if bone[3] and '.thumb' not in bone[3] and '.index' not in bone[3]
                  and '.middle' not in bone[3] and '.ring' not in bone[3] and '.pinky' not in bone[3]]
        names = {bone[0] for bone in subset}
        tracked = [mapping.Bone(name, parent if parent in names else 'RootPos' if label == 'hips' else '', head)
                   for name, parent, head, label in subset]
        rows = {row['target']: row['source'] for row in mapping.match_bones(bones(humanoids.mixamo()), tracked)}
        self.assertEqual(rows['Pelvis'], 'mixamorig:Hips')
        self.assertEqual(rows['L_Forearm'], 'mixamorig:LeftForeArm')
        self.assertEqual(rows['R_Toe0'], 'mixamorig:RightToeBase')
        self.assertEqual(rows['Spine2'], 'mixamorig:Spine2')

    def test_weapon_in_a_matched_hand_leaves_out_hidden_and_stored_weapons(self):
        # Isshin-like source: R_Katana, R_Gun and a wire katana in the right hand, a spear and a gun in the
        # left, and weapons stored on the body. His clip hides the gun and the spear by scaling them to zero.
        renamed = {'R_Weapon': 'R_Katana', 'L_Weapon': 'L_Yari'}
        source = [mapping.Bone(renamed.get(name, name), parent, head) for name, parent, head, label in humanoids.fromsoftware(0, 'souls')]
        heads = {bone.name: bone.head for bone in source}
        source += [mapping.Bone('R_Gun', 'R_Hand', heads['R_Katana']), mapping.Bone('Wire_01', 'R_Hand', heads['R_Hand']),
                   mapping.Bone('R_Katana_Wire', 'Wire_01', heads['R_Katana']), mapping.Bone('L_Gun', 'L_Hand', heads['L_Yari']),
                   mapping.Bone('Katana_Saya_Storage', 'Pelvis', heads['Pelvis']), mapping.Bone('L_Yari_Storage', 'Spine2', heads['Spine2'])]
        target = bones(humanoids.fromsoftware(45, 'elden'))
        rows = {row['target']: row for row in mapping.match_bones(source, target, hidden={'R_Gun', 'L_Yari', 'L_Gun'})}
        self.assertEqual((rows['R_Weapon']['source'], rows['R_Weapon']['reason']), ('R_Katana', 'Weapon in the matched hand'))
        self.assertEqual(rows['L_Weapon']['source'], '')  # Both weapons in the left hand are hidden.
        taken = {row['source'] for row in rows.values()}
        self.assertFalse(taken & {'R_Gun', 'L_Gun', 'R_Katana_Wire', 'Katana_Saya_Storage', 'L_Yari_Storage'})
        self.assertEqual(rows['R_Finger1']['source'], 'R_Finger1')
        # Without the clip's help, R_Katana and R_Gun both hang from the hand, so the weapon is left for review.
        unhidden = {row['target']: row['source'] for row in mapping.match_bones(source, target)}
        self.assertEqual(unhidden['R_Weapon'], '')
        self.assertTrue(mapping.weapon_name('R_Katana') and mapping.weapon_name('R_Weapon') and mapping.weapon_name('L_Yari'))
        self.assertFalse(any(mapping.weapon_name(name) for name in ('Katana_Saya_Storage', 'B_Wepon_Case', 'R_Finger1', 'L_Shield')))

    def test_weapon_parts_are_held_and_stored_weapons_and_shields(self):
        # The bones that get a Hide toggle in the bone list.
        self.assertTrue(all(mapping.weapon_part(name) for name in (
            'R_Katana', 'R_Katana_Saya', 'back_Yari_Storage', 'Katana_Saya_Storage', 'B_Wepon_Case', 'L_Shield', 'c4720_L_Axe')))
        self.assertFalse(any(mapping.weapon_part(name) for name in ('R_Hand', 'R_Finger1', 'Spine2', 'Pelvis', 'L_ForeArmTwist')))

    def test_weapon_changes_hands_when_only_the_other_hand_holds_one(self):
        # Godfrey-like source: an axe in the left hand, nothing in the right. Isshin-like target: a katana at the
        # right hand, and a spear and a gun that rest 1.7 m and 1.2 m from the left hand until a clip brings them in.
        source = [mapping.Bone('L_Axe' if name == 'L_Weapon' else name, parent, head)
                  for name, parent, head, label in humanoids.fromsoftware(45, 'elden') if name != 'R_Weapon']
        renamed = {'R_Weapon': 'R_Katana', 'L_Weapon': 'L_Yari'}
        target = [mapping.Bone(renamed.get(name, name), parent, head) for name, parent, head, label in humanoids.fromsoftware(0, 'souls')]
        heads = {bone.name: bone.head for bone in target}
        away = lambda distance: tuple(h + d for h, d in zip(heads['L_Hand'], (distance * .8, -distance * .6, 0)))
        target = [mapping.Bone(bone.name, bone.parent, away(1.7)) if bone.name == 'L_Yari' else bone for bone in target]
        target.append(mapping.Bone('L_Gun', 'L_Hand', away(1.2)))
        rig = mapping.Rig(target)
        self.assertTrue(rig.rests_at('R_Katana', 'R_Hand'))
        self.assertFalse(rig.rests_at('L_Yari', 'L_Hand') or rig.rests_at('L_Gun', 'L_Hand'))
        rows = {row['target']: row for row in mapping.match_bones(source, target)}
        self.assertEqual((rows['R_Katana']['source'], rows['R_Katana']['reason'], rows['R_Katana']['confidence']),
                         ('L_Axe', 'Weapon from the other hand', .8))
        self.assertEqual((rows['L_Yari']['source'], rows['L_Gun']['source']), ('', ''))
        # A weapon at the target's left hand keeps the axe on its own side.
        own = target + [mapping.Bone('L_Katana', 'L_Hand', heads['L_Hand'])]
        rows = {row['target']: row['source'] for row in mapping.match_bones(source, own)}
        self.assertEqual((rows['R_Katana'], rows['L_Katana']), ('', ''))  # Three in the left hand: left for review.
        single = [bone for bone in own if bone.name not in ('L_Yari', 'L_Gun')]
        rows = {row['target']: row['source'] for row in mapping.match_bones(source, single)}
        self.assertEqual((rows['R_Katana'], rows['L_Katana']), ('', 'L_Axe'))

    def test_counterparts_by_name_and_by_mirrored_position(self):
        named = mapping.Rig(bones(humanoids.unreal()))
        self.assertEqual(named.counterpart('lowerarm_l'), 'lowerarm_r')
        self.assertEqual(named.counterpart('pelvis'), '')
        rig = humanoids.scrambled(humanoids.mixamo(40))
        unnamed, truth = mapping.Rig(bones(rig)), labels(rig)
        name = {label: bone for bone, label in truth.items()}
        self.assertEqual(truth[unnamed.counterpart(name['L.forearm'])], 'R.forearm')
        self.assertEqual(truth[unnamed.counterpart(name['R.index.2'])], 'L.index.2')

    def test_limb_links_follow_arms_legs_and_fingers(self):
        links = set(mapping.limb_links(bones(humanoids.daz())))
        for pair in [('lCollar', 'lShldrBend'), ('lShldrBend', 'lForearmBend'), ('lForearmBend', 'lHand'),
                     ('rThighBend', 'rShin'), ('rShin', 'rFoot'), ('lIndex1', 'lIndex2'), ('rThumb2', 'rThumb3')]:
            self.assertIn(pair, links)
        self.assertNotIn(('lShldrBend', 'lShldrTwist'), links)

    def test_anatomy_reports_the_body_chain_for_the_retarget(self):
        body = mapping.anatomy(bones(humanoids.fromsoftware(45, 'elden')))
        self.assertEqual(body[('', 'hips')], 'Pelvis')
        self.assertEqual(body['spine'], ['Spine', 'Spine1', 'Spine2'])
        self.assertEqual(body['neck'], ['Neck'])
        rigify = mapping.anatomy(bones(humanoids.rigify()))
        self.assertEqual(rigify[('', 'hips')], 'DEF-spine')
        self.assertEqual(rigify[('L', 'upperarm')], 'DEF-upper_arm.L')

    def test_foot_targets_follow_their_feet_with_the_chains_above_them(self):
        for layout in ('elden', 'souls'):
            with self.subTest(layout=layout):
                rig = humanoids.with_foot_targets(humanoids.fromsoftware(45, layout))
                self.assertEqual(mapping.foot_targets(bones(rig)), {
                    'L_Foot_Target': ('L_Foot', ['L_Foot_Target2', 'L_Foot_Target1']),
                    'R_Foot_Target': ('R_Foot', ['R_Foot_Target2', 'R_Foot_Target1'])})
                # The chains drop from Master like legs, but the body keeps its own legs and feet.
                body = mapping.anatomy(bones(rig))
                self.assertEqual((body[('', 'hips')], body[('L', 'foot')], body[('R', 'foot')]), ('Pelvis', 'L_Foot', 'R_Foot'))
        self.assertEqual(mapping.foot_targets(bones(humanoids.mixamo())), {})
        # A target without a foot on its side is left alone.
        lone = [mapping.Bone('Master'), mapping.Bone('L_Foot_Target', 'Master', (.1, 0, .1)), mapping.Bone('R_Foot', 'Master', (-.1, 0, .1))]
        self.assertEqual(mapping.foot_targets(lone), {})


SPECIAL = dict(
    # No clavicles, a twist bone in series in each limb part, a two-bone spine and short legs with long thighs.
    twisted=humanoids.proportioned(2, clavicles=False, twists=True, legs=.85, thighs=.6, arms=(.9, 1.25), arm_angle=40),
    # A four-bone spine and long legs with short thighs, the hip joints closer together.
    tall=humanoids.proportioned(4, legs=1.2, thighs=.42, arms=(1.1, .85), hips=.6))


class BodyTemplate(unittest.TestCase):
    def test_characterize_finds_the_body_by_name_and_by_shape(self):
        everything = rigs()
        for name, rig in SPECIAL.items():
            everything[name] = rig
            everything['unnamed_' + name] = humanoids.scrambled(rig, 13, 'Part')
        roles = ('clavicle', 'upperarm', 'forearm', 'hand')
        for name, rig in everything.items():
            with self.subTest(rig=name):
                body, truth = mapping.characterize(bones(rig)), labels(rig)
                present = set(truth.values())
                self.assertEqual((truth[body['hips']], truth[body['head']], truth[body['neck'][0]]), ('hips', 'head', 'neck'))
                self.assertEqual((truth[body['spine'][0]], truth[body['spine'][-1]]), ('spine.first', 'spine.last'))
                for side in 'LR':
                    arm, leg = body['arms'][side], body['legs'][side]
                    self.assertEqual({role: truth.get(arm[role]) for role in roles},
                                     {role: f'{side}.{role}' if f'{side}.{role}' in present else None for role in roles})
                    self.assertEqual([truth[leg[role]] for role in ('thigh', 'calf', 'foot', 'toe')],
                                     [f'{side}.{role}' for role in ('thigh', 'calf', 'foot', 'toe')])
                    self.assertEqual({number: [truth[bone] for bone in digit] for number, digit in body['fingers'][side].items()},
                                     {number: [f'{side}.{finger}.{segment}' for segment in (1, 2, 3)]
                                      for number, finger in enumerate(humanoids.FINGERS)})
                self.assertEqual(bool(body['shape']), name.startswith('unnamed'))

    def test_an_upper_arm_with_a_twist_bone_in_series_is_no_clavicle(self):
        rig = humanoids.scrambled(SPECIAL['twisted'], 13, 'Part')
        truth = labels(rig)
        # Matching alone takes the upper arm and its twist bone for a clavicle and an upper arm.
        self.assertEqual(truth[mapping.Rig(bones(rig)).roles[('L', 'clavicle')]], 'L.upperarm')
        body = mapping.characterize(bones(rig))
        for side in 'LR':
            self.assertIsNone(body['arms'][side]['clavicle'])
            self.assertEqual(truth[body['arms'][side]['upperarm']], f'{side}.upperarm')
            self.assertNotIn(f'{side}.clavicle', body['shape'])

    def test_chains_pair_across_bone_counts(self):
        pairs = mapping.body_pairs(bones(humanoids.mixamo()), bones(SPECIAL['twisted']))
        chains = pairs['chains']
        # A two-bone spine: the lower bone spans the source's lower two, the chest pairs with the chest.
        self.assertEqual(chains['Spine']['start'], ('mixamorig:Spine', 'mixamorig:Spine1', 0.0))
        self.assertEqual(chains['Spine']['stop'], ('mixamorig:Spine1', 'mixamorig:Spine2', 1.0))
        self.assertEqual(chains['Spine1']['blend'], ('mixamorig:Spine2', 'mixamorig:Spine2', 0.0))
        # A twist bone in series takes the source's motion 40% of the way down the upper arm.
        first, second, part = chains['L_UpperArmTwist']['blend']
        self.assertEqual((first, second), ('mixamorig:LeftArm', 'mixamorig:LeftForeArm'))
        self.assertAlmostEqual(part, .4, places=2)
        self.assertEqual(chains['L_Forearm']['blend'], ('mixamorig:LeftForeArm', 'mixamorig:LeftHand', 0.0))
        # The source's clavicles have no partner in a target without clavicles.
        self.assertNotIn('mixamorig:LeftShoulder', {bone for spec in chains.values() for bone in spec['blend'][:2]})
        self.assertEqual((pairs['direct']['L_Hand'], pairs['direct']['R_Toe']), ('mixamorig:LeftHand', 'mixamorig:RightToeBase'))
        self.assertEqual(pairs['unpaired'], [])
        # The other way round: the target's clavicles have no partner, and its spine spreads over the source's two bones.
        back = mapping.body_pairs(bones(SPECIAL['twisted']), bones(humanoids.mixamo()))
        self.assertEqual(sorted(back['unpaired']), ['mixamorig:LeftShoulder', 'mixamorig:RightShoulder'])
        self.assertEqual(back['chains']['mixamorig:LeftArm']['stop'], ('L_UpperArmTwist', 'L_Forearm', 1.0))
        first, second, part = back['chains']['mixamorig:Spine1']['blend']
        self.assertEqual((first, second), ('Spine', 'Spine1'))
        self.assertAlmostEqual(part, .5, places=2)

    def test_same_bone_counts_pair_one_to_one(self):
        pairs = mapping.body_pairs(bones(humanoids.mixamo()), bones(humanoids.fromsoftware(45, 'elden')))
        self.assertTrue(all(spec['blend'][0] == spec['blend'][1] and spec['blend'][2] == 0 for spec in pairs['chains'].values()))
        self.assertEqual(pairs['chains']['Spine1']['blend'][0], 'mixamorig:Spine1')
        self.assertEqual(pairs['chains']['L_Clavicle']['stop'][0], 'mixamorig:LeftArm')
        self.assertEqual(pairs['chains']['L_Forearm']['stop'][0], 'mixamorig:LeftHand')
        self.assertEqual(pairs['direct']['Pelvis'], 'mixamorig:Hips')
        # Helpers beside the limbs are not part of the body.
        body = set(pairs['direct']) | set(pairs['chains']) | set(pairs['unpaired'])
        self.assertFalse(body & {'L_Shoulder', 'L_UpArmTwist', 'L_Knee', 'L_Hip', 'L_Weapon', 'Face_Root'})

    def test_a_rig_without_legs_has_no_body(self):
        arm = [mapping.Bone('Root', '', (0, 0, 1)), mapping.Bone('Upper', 'Root', (.2, 0, 1)), mapping.Bone('Lower', 'Upper', (.5, 0, 1))]
        self.assertIsNone(mapping.characterize(arm))
        self.assertIsNone(mapping.body_pairs(bones(humanoids.mixamo()), arm))


GERMAN_FINGERS = dict(zip(humanoids.FINGERS, ('Daumen', 'Zeigefinger', 'Mittelfinger', 'Ringfinger', 'Kleinfinger')))


def german():
    """A rig named in German, which the generic name rules do not read, with a sword in its right hand, and the bone
    names that a game package would give it."""
    names = {'hips': 'Becken', 'spine.first': 'Wirbel_1', 'spine.mid': 'Wirbel_2', 'spine.last': 'Brustkorb', 'neck': 'Hals',
             'head': 'Kopf'}
    parts = dict(clavicle=('Schluesselbein', 'Clavicle'), upperarm=('Oberarm', 'UpperArm'), forearm=('Unterarm', 'Forearm'),
                 hand=('Handgelenk', 'Hand'), thigh=('Oberschenkel', 'Thigh'), calf=('Unterschenkel', 'Calf'),
                 foot=('Fuss', 'Foot'), toe=('Zehen', 'Toe'))
    aliases = {'Becken': 'Pelvis', 'Brustkorb': 'Chest', 'Hals': 'Neck', 'Kopf': 'Head', 'R_Schwert': 'R_Sword'}
    for side in 'LR':
        for part, (word, english) in parts.items():
            names[f'{side}.{part}'] = f'{side}_{word}'
            aliases[f'{side}_{word}'] = f'{side}_{english}'
        for finger, word in GERMAN_FINGERS.items():
            for segment in (1, 2, 3):
                names[f'{side}.{finger}.{segment}'] = f'{side}_{word}_{segment}'
    joints = humanoids.base()
    rig = humanoids.build(joints, names, extra=[('R_Schwert', 'R_Handgelenk', humanoids.between(joints, 'R.hand', 'R.middle.1'))])
    patterns = [{'match': r'Wirbel_(\d)', 'as': r'Spine\1'}] + [
        {'match': rf'([LR])_{word}_(\d)', 'as': rf'\1_{finger.title()}\2'} for finger, word in GERMAN_FINGERS.items()]
    return rig, dict(names=aliases, patterns=patterns)


class GameBoneNames(unittest.TestCase):
    def test_aliases_let_a_rig_in_another_language_match_and_rows_keep_the_real_names(self):
        rig, game = german()
        alias = mapping.alias_rule(game)
        standard = humanoids.mixamo()
        german_names = {label: name for name, label in labels(rig).items() if label}
        standard_names = {label: name for name, label in labels(standard).items() if label}
        # Without rest positions only names tell, so the German rig matches through its aliases alone.
        plain = [mapping.Bone(name, parent) for name, parent, head, label in rig]
        aliased = [mapping.Bone(name, parent, None, alias(name)) for name, parent, head, label in rig]
        self.assertEqual(aliased[0].alias, 'Pelvis')
        for target, source in ((plain, bones(standard)), (aliased, bones(standard)), (bones(standard), plain),
                               (bones(standard), aliased)):
            reverse = source in (plain, aliased)
            with self.subTest(aliases=aliased in (source, target), german='source' if reverse else 'target'):
                rows = mapping.match_bones(source, target)
                pairs = {(row['source'], row['target']) if reverse else (row['target'], row['source']) for row in rows}
                matched = {label for label in CORE if (german_names[label], standard_names[label]) in pairs}
                if aliased in (source, target):
                    self.assertEqual(matched, CORE)
                    self.assertEqual({row['target'] for row in rows}, {bone.name for bone in target})
                    self.assertLessEqual({row['source'] for row in rows} - {''}, {bone.name for bone in source})
                else:
                    self.assertEqual(matched, set())
        # A weapon named in German is held in the matched hand.
        rows = {row['target']: row for row in mapping.match_bones(aliased, bones(humanoids.fromsoftware(45, 'elden')))}
        self.assertEqual((rows['R_Weapon']['source'], rows['R_Weapon']['reason']), ('R_Schwert', 'Weapon in the matched hand'))
        self.assertEqual(rows['L_Thigh']['source'], 'L_Oberschenkel')
        # With rest positions, aliases make the match by name rather than by body structure.
        rows = {row['target']: row for row in mapping.match_bones(bones(standard), bones(rig))}
        self.assertEqual(rows['L_Oberschenkel']['reason'], 'Body structure: thigh')
        located = [mapping.Bone(name, parent, head, alias(name)) for name, parent, head, label in rig]
        rows = {row['target']: row for row in mapping.match_bones(bones(standard), located)}
        self.assertEqual((rows['L_Oberschenkel']['source'], rows['L_Oberschenkel']['reason']),
                         ('mixamorig:LeftUpLeg', 'Anatomical role: thigh'))
        self.assertEqual((rows['R_Zeigefinger_2']['source'], rows['R_Zeigefinger_2']['reason']),
                         ('mixamorig:RightHandIndex2', 'Finger and segment'))
        self.assertEqual(mapping.Rig(located).counterpart('L_Kleinfinger_3'), 'R_Kleinfinger_3')

    def test_real_names_pair_before_aliases(self):
        # Two rigs of one game, only one of them with the game's bone names: every bone takes its namesake.
        rig, game = german()
        alias = mapping.alias_rule(game)
        plain = [mapping.Bone(name, parent) for name, parent, head, label in rig]
        aliased = [mapping.Bone(name, parent, None, alias(name)) for name, parent, head, label in rig]
        for source, target in ((aliased, plain), (plain, aliased)):
            rows = mapping.match_bones(source, target)
            self.assertEqual({row['target']: row['source'] for row in rows}, {bone.name: bone.name for bone in target})
            self.assertTrue(all(row['confidence'] == 1.0 for row in rows))

    def test_bone_names_come_from_the_game_in_games_json(self):
        self.assertEqual(mapping.alias_rule(None)('Becken'), '')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'games.json'
            self.assertEqual(mapping.game_aliases(path, 'dmc5')('Becken'), '')  # No games.json yet.

            def write(document, stamp):
                path.write_text(document if isinstance(document, str) else json.dumps(document), encoding='utf-8')
                os.utime(path, ns=(stamp, stamp))
            bones = dict(names={'Becken': 'Pelvis', 'Kopf': 7}, patterns=[
                {'match': '(', 'as': 'broken'}, {'match': r'([LR])_Zeh(\d)', 'as': r'\3'},
                {'match': r'([LR])_Zeh(\d)', 'as': r'\1_Toe\2'}, {'match': r'[LR]_[A-Za-z]+', 'as': 'Arm'}, 'Hals'])
            write({'games': [{'id': 'sekiro', 'name': 'Sekiro'}, {'id': 'dmc5', 'name': 'Devil May Cry 5', 'bones': bones}]},
                  10 ** 18)
            alias = mapping.game_aliases(path, 'dmc5')
            self.assertEqual([alias(name) for name in ('Becken', 'Kopf', 'L_Zeh0', 'R_Hand', 'R_Hand2', 'Hals')],
                             ['Pelvis', '', 'L_Toe0', 'Arm', '', ''])
            self.assertEqual((mapping.game_aliases(path, 'sekiro')('Becken'), mapping.game_aliases(path, 'other')('Becken')), ('', ''))
            self.assertIs(mapping.game_aliases(path, 'dmc5'), alias)  # Read once while the file stays.
            write({'games': [{'id': 'dmc5', 'name': 'Devil May Cry 5', 'bones': {'names': {'Becken': 'Hip'}}}]}, 2 * 10 ** 18)
            self.assertEqual(mapping.game_aliases(path, 'dmc5')('Becken'), 'Hip')
            for broken in ('{"games": ', '{"games": 3}', '[]', json.dumps({'games': [{'id': 'dmc5', 'bones': [1]}]})):
                write(broken, 3 * 10 ** 18 + len(broken))
                self.assertEqual(mapping.game_aliases(path, 'dmc5')('Becken'), '', broken)
            path.unlink()
            self.assertEqual(mapping.game_aliases(path, 'dmc5')('Becken'), '')


if __name__ == '__main__':
    unittest.main()
