"""Additive clips: Havok's and DOOM Eternal's composition of a change on a base pose, the base clip, the schema and the
HKX's blendHint.

Fixtures are made up for these tests: a three-bone chain with turned rest bones and changes that no game holds.
"""
import copy
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from games import additive, interchange
from clip_preview import joint_positions


def turn(axis, degrees):
    half = math.radians(degrees) / 2
    length = math.sqrt(sum(v * v for v in axis))
    return [v / length * math.sin(half) for v in axis] + [math.cos(half)]


def sample(translation, rotation, scale=(1, 1, 1)):
    return dict(translation=list(translation), rotation=list(rotation), scale=list(scale))


def random_sample(rng, scale=False):
    axis = [rng.uniform(-1, 1) for _ in range(3)]
    return sample([rng.uniform(-1, 1) for _ in range(3)], turn(axis, rng.uniform(-170, 170)),
                  [rng.uniform(.5, 2) for _ in range(3)] if scale else (1, 1, 1))


def owned_skeleton():
    rest = [sample((0, 0, 0), turn((0, 1, 0), 90)), sample((0, 1, 0), turn((1, 0, 0), 20)),
            sample((0, .5, 0), turn((0, 0, 1), -30))]
    return [dict(index=i, name=f'Owned {i}', parent=i - 1, **bone) for i, bone in enumerate(rest)]


def owned_additive(frames=5, base=None):
    """An additive clip that bends the chain and comes back: no change on its first and last frames."""
    bones = owned_skeleton()
    samples = []
    for f in range(frames):
        amount = math.sin(math.pi * f / (frames - 1))
        samples.append([sample((0, 0, 0), turn((0, 0, 1), 0)),
                        sample((.02 * amount, 0, 0), turn((1, 0, 0), 40 * amount)),
                        sample((0, 0, 0), turn((0, 1, 0), -25 * amount))])
    motion = dict(format='sekiro-animation-bridge', formatVersion=1, clip='owned_add.hkx', skeletonName='Owned',
                  skeleton=dict(name='Owned', boneCount=3, bones=bones), frameCount=frames, frameRate=30.0,
                  duration=(frames - 1) / 30, trackCount=3, blockCount=0, compression='interleaved',
                  trackBoneIndices=[0, 1, 2], trackNames=[b['name'] for b in bones], rootMotion=None, rootUp=None,
                  rootForward=None, frames=samples, game='sekiro', archive='', member='',
                  additive=dict(blendHint=1, space='parent'))
    if base is not None:
        motion['additive']['base'] = base
    return motion


def close(test, a, b, places=6):
    for key in ('translation', 'scale'):
        for x, y in zip(a[key], b[key]):
            test.assertAlmostEqual(x, y, places=places, msg=key)
    dot = abs(sum(x * y for x, y in zip(a['rotation'], b['rotation'])))
    test.assertAlmostEqual(dot, 1.0, places=places, msg='rotation')


class Composition(unittest.TestCase):
    def test_difference_undoes_compose_in_every_space(self):
        rng = random.Random(7)
        for space in ('parent', 'child', 'separate'):
            for _ in range(50):
                change, base = random_sample(rng, scale=True), random_sample(rng, scale=True)
                with self.subTest(space=space):
                    pose = additive.compose(change, base, space)
                    close(self, additive.difference(pose, base, space), change)
                    close(self, additive.compose(additive.difference(pose, base, space), base, space), pose)

    def test_parent_space_is_havoks_product_of_the_change_and_the_base(self):
        # A quarter turn about Z moves the base's offset (1, 0, 0) to (0, 1, 0), then adds the change's own offset.
        change = sample((0, 0, .5), turn((0, 0, 1), 90), (2, 2, 2))
        base = sample((1, 0, 0), turn((1, 0, 0), 30), (1, .5, 1))
        pose = additive.compose(change, base)
        close(self, pose, sample((0, 1, .5), additive.multiply(turn((0, 0, 1), 90), turn((1, 0, 0), 30)), (2, 1, 2)))

    def test_child_space_turns_the_change_by_the_base(self):
        change = sample((1, 0, 0), turn((0, 0, 1), 10))
        base = sample((0, 0, 1), turn((0, 0, 1), 90))
        pose = additive.compose(change, base, 'child')
        close(self, pose, sample((0, 1, 1), turn((0, 0, 1), 100)))

    def test_separate_parts_add_the_offset_without_turning_it(self):
        # DOOM Eternal's form: the same change as above leaves the base's offset (1, 0, 0) where it is.
        change = sample((0, 0, .5), turn((0, 0, 1), 90), (2, 2, 2))
        base = sample((1, 0, 0), turn((1, 0, 0), 30), (1, .5, 1))
        pose = additive.compose(change, base, 'separate')
        close(self, pose, sample((1, 0, .5), additive.multiply(turn((0, 0, 1), 90), turn((1, 0, 0), 30)), (2, 1, 2)))

    def test_no_change_gives_the_base(self):
        base = random_sample(random.Random(3), scale=True)
        for space in ('parent', 'child', 'separate'):
            close(self, additive.compose(sample((0, 0, 0), (0, 0, 0, 1)), base, space), base)

    def test_a_base_scaled_to_nothing_keeps_its_scale(self):
        change = additive.difference(sample((0, 0, 0), (0, 0, 0, 1), (1, 1, 1)), sample((0, 0, 0), (0, 0, 0, 1), (0, 1, 1)))
        self.assertEqual(change['scale'], [1.0, 1.0, 1.0])

    def test_rotations_off_unit_length_compose_as_unit_ones(self):
        change, base = sample((0, 0, 0), [v * 1.01 for v in turn((0, 1, 0), 30)]), sample((1, 0, 0), turn((0, 1, 0), 10))
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in additive.compose(change, base)['rotation'])), 1.0, places=9)


class Clips(unittest.TestCase):
    def test_space_of(self):
        self.assertIsNone(additive.space_of(dict(frames=[])))
        self.assertEqual(additive.space_of(dict(additive=dict(blendHint=1))), 'parent')
        self.assertEqual(additive.space_of(dict(additive=dict(blendHint=2))), 'child')
        self.assertEqual(additive.space_of(dict(additive=dict(space='separate'))), 'separate')
        with self.assertRaisesRegex(ValueError, 'Unknown additive space'):
            additive.space_of(dict(additive=dict(blendHint=1, space='world')))

    def test_an_hkx_export_writes_havoks_spaces(self):
        self.assertEqual([additive.havok_space(space) for space in ('parent', 'child', 'separate')],
                         ['parent', 'child', 'parent'])
        self.assertEqual(additive.BLEND_HINTS, dict(parent=1, child=2))

    def test_a_normal_clips_frames_stay_as_they_are(self):
        motion = owned_additive()
        del motion['additive']
        self.assertIs(additive.posed_frames(motion), motion['frames'])

    def test_an_additive_clip_shows_on_the_rest_pose(self):
        motion = owned_additive()
        posed = additive.posed_frames(motion)
        rest = additive.rest_pose(motion)
        for track in range(3):
            close(self, posed[0][track], rest[track])
            close(self, posed[-1][track], rest[track])
        close(self, posed[2][1], additive.compose(motion['frames'][2][1], rest[1]))

    def test_a_base_clip_repeats_from_its_start(self):
        base = dict(clip='owned_base.hkx', frameRate=30.0, trackBoneIndices=[1],
                    frames=[[sample((0, 1, 0), turn((1, 0, 0), angle))] for angle in (0, 10, 20, 0)])
        self.assertEqual([additive.base_frame(base, f / 30) for f in range(8)], [0, 1, 2, 0, 1, 2, 0, 1])
        self.assertEqual(additive.base_frame(dict(base, frames=base['frames'][:1]), 1.0), 0)
        motion = owned_additive(frames=5, base=base)
        posed = additive.posed_frames(motion)
        rest = additive.rest_pose(motion)
        # Bone 1 follows the base clip (frame 4 is the base's frame 1 again); bones 0 and 2 keep the rest pose.
        close(self, posed[4][1], base['frames'][1][0])
        close(self, posed[1][1], additive.compose(motion['frames'][1][1], base['frames'][1][0]))
        close(self, posed[1][2], additive.compose(motion['frames'][1][2], rest[2]))
        self.assertEqual(additive.base_tracks(motion), {1})

    def test_the_base_must_be_a_normal_clip(self):
        with self.assertRaisesRegex(ValueError, 'additive clip itself'):
            additive.base_clip(owned_additive())
        normal = owned_additive()
        del normal['additive']
        base = additive.base_clip(normal)
        self.assertEqual((base['clip'], base['trackBoneIndices'], len(base['frames'])), ('owned_add.hkx', [0, 1, 2], 5))

    def test_preview_shows_the_composed_pose(self):
        motion = owned_additive()
        composed = copy.deepcopy(motion)
        del composed['additive']
        composed['frames'] = additive.posed_frames(motion)
        for a, b in zip(joint_positions(motion), joint_positions(composed)):
            self.assertAlmostEqual(a, b, places=9)


class Schema(unittest.TestCase):
    def test_additive_motions_are_valid(self):
        interchange.check_motion(owned_additive())
        normal = owned_additive()
        del normal['additive']
        base = additive.base_clip(normal)
        interchange.check_motion(owned_additive(base=base))
        interchange.check_motion(owned_additive(base=None))
        # Another engine's changes have a space and no Havok blend hint.
        interchange.check_motion(dict(owned_additive(), additive=dict(space='separate')))

    def test_unknown_blend_hints_and_spaces_are_refused(self):
        for change in (dict(blendHint=3, space='parent'), dict(blendHint=1, space='world'), dict(blendHint=1)):
            motion = owned_additive()
            motion['additive'] = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                interchange.check_motion(motion)


try:
    import numpy  # noqa: F401
    import soulstruct  # noqa: F401
    WRITER = True
except ImportError:
    WRITER = False


@unittest.skipUnless(WRITER, 'Writing HKX needs the conversion Python (NumPy and Soulstruct)')
class Writer(unittest.TestCase):
    def write(self, document):
        from build_animation import build
        from havok_compat import readable
        from game_profiles import animation_class
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'motion.json', Path(temp) / 'out.hkx'
            source.write_text(json.dumps(document), encoding='utf-8')
            stats = build(source, output, 'interleaved', 'auto', verify=True)
            written = readable(animation_class('sekiro')).from_bytes(output.read_bytes())
            return stats, [b.blendHint for b in written.animation_container.hkx_container.bindings]

    def test_an_additive_clip_is_written_with_its_blend_hint(self):
        stats, hints = self.write(owned_additive())
        self.assertEqual((stats['blendHint'], hints), (1, [1]))
        self.assertLess(stats['readback']['maxRotationDegrees'], 1e-3)

    def test_a_normal_clip_keeps_blend_hint_0(self):
        motion = owned_additive()
        del motion['additive']
        stats, hints = self.write(motion)
        self.assertNotIn('blendHint', stats)
        self.assertEqual(hints, [0])

    def test_an_unknown_blend_hint_is_refused(self):
        motion = owned_additive()
        motion['additive'] = dict(blendHint=4, space='parent')
        with self.assertRaisesRegex(ValueError, 'blend hint 4'):
            self.write(motion)


class Runtime(unittest.TestCase):
    def test_a_base_clip_needs_an_additive_clip_and_a_catalog(self):
        try:
            import bridge_runtime
        except ImportError as error:
            self.skipTest(f'bridge_runtime needs {error.name}')
        normal = owned_additive()
        del normal['additive']
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'not an additive clip'):
                bridge_runtime.additive_base(normal, dict(additiveBase='a000_000100'), {}, 'decoder.exe', Path(temp))
            with self.assertRaisesRegex(ValueError, 'scanned source'):
                bridge_runtime.additive_base(owned_additive(), dict(additiveBase='a000_000100'), None, 'decoder.exe',
                                             Path(temp))


class Packages(unittest.TestCase):
    """A game package's additive clip takes its base from the package's preview, a whole motion JSON of the clip."""

    CATALOG = dict(clips=[dict(id='owned/additive/idle', name='additive/idle', characterKey='owned'),
                          dict(id='owned/idle', name='idle', characterKey='owned'),
                          dict(id='other/run', name='run', characterKey='other')])

    def base_of(self, document, wanted, base):
        from games.packages import PackageEngine
        engine = SimpleNamespace(package=SimpleNamespace(name='Owned'), context=lambda *args: None,
                                 selection=lambda catalog, clip: dict(animation=clip),
                                 module=SimpleNamespace(preview=lambda selection, ctx: copy.deepcopy(base)))
        request = dict(assetClip='owned/additive/idle', additiveBase=wanted)
        return PackageEngine.additive_base(engine, document, request, self.CATALOG, lambda *args: None)

    def test_a_clip_of_the_same_character_is_the_base(self):
        normal = owned_additive()
        del normal['additive']
        separate = dict(owned_additive(), additive=dict(space='separate'))
        for wanted in ('IDLE', 'owned/idle'):
            result = self.base_of(separate, wanted, dict(normal, clip='idle.md6anim'))
            self.assertEqual((result['space'], result['base']['clip']), ('separate', 'idle.md6anim'))
            interchange.check_motion(dict(separate, additive=result))
        with self.assertRaisesRegex(ValueError, 'no clip run'):
            self.base_of(separate, 'run', normal)

    def test_the_base_is_a_normal_clip_on_the_same_skeleton(self):
        normal = owned_additive()
        del normal['additive']
        separate = dict(owned_additive(), additive=dict(space='separate'))
        with self.assertRaisesRegex(ValueError, 'not an additive clip'):
            self.base_of(normal, 'idle', normal)
        with self.assertRaisesRegex(ValueError, 'additive clip itself'):
            self.base_of(separate, 'idle', separate)
        other = copy.deepcopy(normal)
        other['skeleton']['bones'][2]['name'] = 'Other 2'
        with self.assertRaisesRegex(ValueError, 'another skeleton'):
            self.base_of(separate, 'idle', other)


if __name__ == '__main__':
    unittest.main()
