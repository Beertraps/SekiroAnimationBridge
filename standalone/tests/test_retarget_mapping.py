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


if __name__ == '__main__':
    unittest.main()
