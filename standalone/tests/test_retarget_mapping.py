"""Bone matching of the Blender retarget add-on on owned synthetic skeletons (no Blender needed)."""
import importlib.util
import sys
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


if __name__ == '__main__':
    unittest.main()
