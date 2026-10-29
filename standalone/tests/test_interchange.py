"""The interchange schemas, the checker and source spaces, without Blender or game files."""
import copy
import json
import math
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from games import interchange
from games.space import FROMSOFT, RE_ENGINE, Space
from clip_preview import joint_positions

ROOT = Path(__file__).resolve().parents[2]


def owned_motion(version=1, frames=3):
    """A two-bone clip in the shape the decoders write, made up for this test."""
    root = dict(index=0, name='Owned root', parent=-1, translation=[0, 0, 0], rotation=[0, math.sqrt(.5), 0, math.sqrt(.5)], scale=[1, 1, 1])
    child = dict(index=1, name='Owned child', parent=0, translation=[0, 1, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1])
    samples = [[dict(translation=[.1 * f, 0, 0], rotation=root['rotation'], scale=[1, 1, 1]),
                dict(translation=[0, 1 + .1 * f, 0], rotation=child['rotation'], scale=[1, 1, 1])] for f in range(frames)]
    motion = dict(format='sekiro-animation-bridge', formatVersion=1, clip='owned.hkx', skeletonName='Owned',
                  skeleton=dict(name='Owned', boneCount=2, bones=[root, child]), frameCount=frames, frameRate=30.0,
                  duration=(frames - 1) / 30, trackCount=2, blockCount=0, compression='interleaved',
                  trackBoneIndices=[0, 1], trackNames=['Owned root', 'Owned child'],
                  rootMotion=[[.1 * f, 0, 0, .05 * f] for f in range(frames)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0],
                  frames=samples, game='sekiro', archive='', member='')
    if version == 2:
        motion = interchange.with_source(motion, RE_ENGINE, 're_engine', 'dmc5', 'motlist', 85, 'owned.motlist.85', 'owned', 0)
    return motion


def owned_manifest(version=4):
    image = dict(path='C:/owned/albedo.png', linear=False, uv=0, scale=[1, 1], stem='albedo')
    material = dict(name='Owned material', mtd='owned.mtd', albedo=image, normal=None, emissive=None, samplers=[], alpha=False, color=[1, 1, 1])
    manifest = dict(version=version, game='sekiro', models=[dict(name='c9990', source='c9990.chrbnd.dcx', data='C:/owned/00_c9990.npz',
                    materials=[material], stats=dict(vertices=3, triangles=1), attachment=None)], warnings=[], material_library='', texture_count=1)
    if version == 5:
        manifest.update(game='dmc5', boneRotation='quaternion', **RE_ENGINE.to_json())
        material['normal'] = dict(image, path='C:/owned/normal.png', linear=True, convention='directx', channels='xy')
    return manifest


def owned_preview(motion):
    positions = joint_positions(motion)
    return dict(clip=motion['clip'], skeleton=motion['skeletonName'], frameCount=motion['frameCount'], frameRate=motion['frameRate'],
                duration=motion['duration'], frameStep=1, bones=[b['name'] for b in motion['skeleton']['bones']],
                parents=[b['parent'] for b in motion['skeleton']['bones']], tracks=motion['trackCount'], positions=positions,
                detached=[], root=motion['rootMotion'])


def fromsoft_swap(sample):
    """The bridge's fixed conversion before source spaces (blender_bridge.game_to_bl_trs of 0.13), as (w, x, y, z)."""
    x, y, z, w = sample['rotation']
    t, s = sample['translation'], sample['scale']
    return (w, -x, -z, -y), (t[0], t[2], t[1]), (s[0], s[2], s[1])


class Schemas(unittest.TestCase):
    def test_version_1_and_2_motions_are_valid(self):
        for version in (1, 2):
            with self.subTest(version=version):
                interchange.check_motion(owned_motion(version))

    def test_version_2_needs_its_source_and_space(self):
        motion = owned_motion(2)
        del motion['basis']
        with self.assertRaisesRegex(ValueError, 'basis: missing'):
            interchange.check_motion(motion)

    def test_rules_between_fields(self):
        cases = {
            'comes before its parent': lambda m: m['skeleton']['bones'][0].update(parent=1),
            'frames does not have frameCount samples': lambda m: m.update(frameCount=4),
            'trackBoneIndices and trackNames': lambda m: m['trackNames'].pop(),
            'two tracks animate the same bone': lambda m: m.update(trackBoneIndices=[1, 1]),
            'a frame does not have trackCount samples': lambda m: m['frames'][1].pop(),
            'skeletonName does not match': lambda m: m.update(skeletonName='Other'),
            'rootMotion does not have frameCount samples': lambda m: m['rootMotion'].pop(),
        }
        for message, change in cases.items():
            with self.subTest(message):
                motion = owned_motion()
                change(motion)
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    interchange.check_motion(motion)

    def test_types_and_shapes(self):
        motion = owned_motion()
        motion['frames'][0][0]['rotation'] = [0, 0, 1]
        with self.assertRaisesRegex(ValueError, r'frames\[0\]\[0\]\.rotation: needs at least 4 items'):
            interchange.check_motion(motion)
        motion = owned_motion()
        motion['frameRate'] = 0
        with self.assertRaisesRegex(ValueError, 'frameRate: must be greater than 0'):
            interchange.check_motion(motion)
        motion = owned_motion(2)
        motion['basis'] = [[1, 0, 0], [0, 1, 0], [0, 1, 0]]
        with self.assertRaisesRegex(ValueError, 'signed permutation'):
            interchange.check_motion(motion)

    def test_manifests_4_and_5_are_valid(self):
        interchange.check_manifest(owned_manifest(4))
        interchange.check_manifest(owned_manifest(5))
        broken = owned_manifest(5)
        broken['boneRotation'] = 'euler_xyz'
        with self.assertRaisesRegex(ValueError, 'boneRotation: must be one of'):
            interchange.check_manifest(broken)

    def test_preview_from_joint_positions_is_valid(self):
        preview = owned_preview(owned_motion())
        interchange.check_preview(preview)
        interchange.check_preview(dict(preview, **RE_ENGINE.to_json()))
        preview['positions'][0] = preview['positions'][0][:-1]
        with self.assertRaisesRegex(ValueError, 'x, y, z for every bone'):
            interchange.check_preview(preview)

    def test_schemas_are_json_and_documented(self):
        documented = (ROOT / 'docs' / 'INTERCHANGE.md').read_text(encoding='utf-8')
        for path in sorted((ROOT / 'standalone' / 'schemas').glob('*.schema.json')):
            json.loads(path.read_text(encoding='utf-8'))
            self.assertIn(path.name, documented)


class Spaces(unittest.TestCase):
    samples = [dict(translation=[.3, -1.2, 2.5], rotation=[.1, -.7, .2, math.sqrt(1 - .01 - .49 - .04)], scale=[1, 2, 3]),
               dict(translation=[0, 0, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1])]

    def test_fromsoft_space_equals_the_earlier_swap(self):
        for sample in self.samples:
            rotation, translation, scale = fromsoft_swap(sample)
            self.assertEqual(FROMSOFT.quaternion(sample['rotation']), tuple(float(v) for v in rotation))
            self.assertEqual(FROMSOFT.point(sample['translation']), tuple(float(v) for v in translation))
            self.assertEqual(FROMSOFT.scale(sample['scale']), tuple(float(v) for v in scale))
        self.assertTrue(FROMSOFT.reflects)
        self.assertEqual(FROMSOFT.yaw(.4), -.4)

    def test_documents_without_a_basis_are_fromsoft(self):
        self.assertEqual(Space.of(owned_motion(1)), FROMSOFT)
        self.assertEqual(Space.of(owned_motion(2)), RE_ENGINE)
        self.assertEqual(Space.of({}), FROMSOFT)

    def test_re_engine_turns_y_up_into_z_up_without_mirroring(self):
        self.assertFalse(RE_ENGINE.reflects)
        self.assertEqual(RE_ENGINE.point((0, 1, 0)), (0, 0, 1))
        self.assertEqual(RE_ENGINE.point((0, 0, 1)), (0, -1, 0))
        # A quarter turn about the source's up axis is a quarter turn about Blender's Z.
        half = math.sqrt(.5)
        self.assertEqual(RE_ENGINE.quaternion((0, half, 0, half)), (half, 0, 0, half))
        self.assertEqual(RE_ENGINE.yaw(.4), .4)

    def test_round_trips(self):
        for space in (FROMSOFT, RE_ENGINE, Space(((0, -1, 0), (0, 0, 1), (-1, 0, 0)), 0.01)):
            for sample in self.samples:
                with self.subTest(space=space, sample=sample):
                    back = space.inverse_point(space.point(sample['translation']))
                    self.assertTrue(all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(back, sample['translation'])))
                    self.assertEqual(space.inverse_scale(space.scale(sample['scale'])), tuple(float(v) for v in sample['scale']))
                    rotation = space.inverse_quaternion(space.quaternion(sample['rotation']))
                    self.assertTrue(all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(rotation, sample['rotation'])))

    def test_matrix_conjugation_matches_the_quaternion_rule(self):
        """C * R * C^-1 of a source rotation matrix equals the rotation of the converted quaternion."""
        def rotation_matrix(w, x, y, z):
            return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        def multiply(a, b):
            return [[sum(a[r][k] * b[k][c] for k in range(len(b))) for c in range(len(b[0]))] for r in range(len(a))]
        for space in (FROMSOFT, RE_ENGINE, Space(((0, -1, 0), (0, 0, 1), (-1, 0, 0)), 0.01)):
            x, y, z, w = self.samples[0]['rotation']
            source = [row + [t] for row, t in zip(rotation_matrix(w, x, y, z), self.samples[0]['translation'])] + [[0, 0, 0, 1]]
            converted = multiply(multiply(space.matrix(), source), space.inverse_matrix())
            expected = rotation_matrix(*space.quaternion(self.samples[0]['rotation']))
            for r in range(3):
                for c in range(3):
                    self.assertAlmostEqual(converted[r][c], expected[r][c], places=12)
                self.assertAlmostEqual(converted[r][3], space.point(self.samples[0]['translation'])[r], places=12)

    def test_basis_must_be_a_signed_permutation(self):
        for basis in ([[1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 2, 0], [0, 0, 1]], [[1, 0, 0], [1, 0, 0], [0, 0, 1]]):
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                Space(basis)
        with self.assertRaises(ValueError):
            Space(unit=0)


if __name__ == '__main__':
    unittest.main()
