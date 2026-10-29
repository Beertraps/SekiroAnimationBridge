"""Join animations of the retarget add-on on owned synthetic bridge clips. Run with
Blender --background --factory-startup --python this_file.py.

Two clips of one small skeleton are imported through the bridge into scenes of
their own: the first, 20 frames at 30 fps, turns the spine one way and walks
forward while turning; the second, 15 frames, turns it back and walks to the
side, both with root motion. A third clip, keyed at 60 fps, covers the same
time in twice the frames.

Checked: Load clip from .blend brings in the second scene's armature and root
motion actions without its objects or metadata, pairs the root motion by name
also where Blender numbers the names, and records a frame rate other than the
scene's; the joined clip plays the first clip, then the second, each pose
exactly as its clip has it outside the blend, and between the two over the
blend, easing from one to the other; with a blend of 0 the second clip starts
the frame after the first ends; the second clip's root motion goes on from
where the first one's root stands when it begins, without a jump; a 60 fps
clip plays at its own speed in a 30 fps scene; the scene's frame range
becomes the joined clip's; the originals stay; the export of the joined clip
has its frames and root motion; and the operators and their refusals work.
"""
import math
import shutil
import sys
import tempfile
from pathlib import Path
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
from blender_bridge import bl_to_game_trs, export_motion, import_motion
import sekiro_retarget
from sekiro_retarget import join, retarget

BONES = [('Master', None, (0, 0, 0)), ('Pelvis', 'Master', (0, 0, 1)), ('Spine', 'Pelvis', (0, 0, 1.2)),
         ('L_Arm', 'Spine', (.2, 0, 1.5)), ('R_Arm', 'Spine', (-.2, 0, 1.5))]


def motion(clip, count, rate, spine, root):
    """Bridge motion JSON: spine(t) turns the spine about Z, root(t) gives (x, y, z, yaw) of the game's root motion."""
    index = {name: i for i, (name, parent, head) in enumerate(BONES)}
    heads = {name: Vector(head) for name, parent, head in BONES}

    def local(name, parent, turn=Quaternion()):
        offset = heads[name] - (heads[parent] if parent else Vector())
        return bl_to_game_trs(offset, turn, Vector((1, 1, 1)))
    skeleton = [dict(index=i, name=name, parent=index[parent] if parent else -1, **local(name, parent))
                for i, (name, parent, head) in enumerate(BONES)]
    frames = []
    for f in range(count):
        t = f / (count - 1)
        frames.append([local(name, parent, Quaternion((0, 0, 1), spine(t)) if name == 'Spine' else Quaternion())
                       for name, parent, head in BONES])
    return dict(format='sekiro-animation-bridge', formatVersion=1, clip=clip, skeletonName='Owned', game='sekiro',
                skeleton=dict(name='Owned', boneCount=len(BONES), bones=skeleton), frameCount=count, frameRate=rate,
                duration=(count - 1) / rate, trackCount=len(BONES), trackBoneIndices=list(range(len(BONES))),
                trackNames=[name for name, parent, head in BONES], frames=frames,
                rootMotion=[list(root(f / (count - 1))) for f in range(count)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0])


FIRST = motion('a000_003000.hkx', 20, 30, lambda t: .6 * t, lambda t: (0, 0, 1.0 * t, .5 * t))
SECOND = motion('a000_003001.hkx', 15, 30, lambda t: -.4 + .4 * t, lambda t: (.5 * t, 0, 0, .3 * t))
FAST = motion('a000_003002.hkx', 29, 60, lambda t: -.4 + .4 * t, lambda t: (.5 * t, 0, 0, .3 * t))


def scene_of(document, path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_motion(document)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def spine_angle(rig, frame):
    bpy.context.scene.frame_set(frame)
    return rig.pose.bones['Spine'].matrix_basis.to_quaternion().angle * math.copysign(
        1, rig.pose.bones['Spine'].matrix_basis.to_quaternion().axis.z or 1)


def root_at(root, frame):
    bpy.context.scene.frame_set(frame)
    return Matrix.LocRotScale(root.location, root.rotation_euler, None)


def close(a, b, limit=1e-4):
    return abs(a - b) <= limit


def main():
    folder = Path(tempfile.mkdtemp(prefix='SekiroJoin-'))
    try:
        scene_of(SECOND, folder / 'second.blend')
        scene_of(FAST, folder / 'fast.blend')
        scene_of(FIRST, folder / 'first.blend')
        sekiro_retarget.register()
        context, scene = bpy.context, bpy.context.scene
        rig = next(obj for obj in scene.objects if obj.type == 'ARMATURE')
        root = retarget.root_object(rig)
        bpy.context.view_layer.objects.active = rig
        first = rig.animation_data.action
        assert first.name == 'a000_003000_Sekiro', first.name
        before = {name for name in bpy.data.objects.keys()}

        # Blender numbers names it has already: give the scene the second clip's names first.
        bpy.data.actions.new('a000_003001_Sekiro')
        bpy.data.actions.new('a000_003001_RootMotion')
        assert bpy.ops.sekiro_retarget.join_load(filepath=str(folder / 'second.blend')) == {'FINISHED'}
        second = scene.sekiro_join.second
        assert second is not None and second.name == 'a000_003001_Sekiro.001', second
        assert join.named_root(second) is not None and join.named_root(second).name == second.name + ' RootMotion', \
            [a.name for a in bpy.data.actions]
        assert set(bpy.data.objects.keys()) == before, 'Load brought in objects'
        assert not any(text.name.endswith('a000_003001.json') for text in bpy.data.texts), 'Load kept the metadata'
        assert join.RATE in second and second[join.RATE] == 30, dict(second)
        print('Load: the second clip and its root motion came in, paired by name although Blender numbered both')

        # A blend of 0.1 s is 3 frames at 30 fps: the second clip starts on frame 21 - 3 = 18 and ends on 18 + 14.
        scene.sekiro_join.blend = .1
        assert bpy.ops.sekiro_retarget.join_animations() == {'FINISHED'}, scene.sekiro_retarget.status
        joined = rig.animation_data.action
        assert joined.name == 'a000_003000 + a000_003001', joined.name
        assert root.animation_data.action.name == joined.name + ' RootMotion', root.animation_data.action.name
        assert (scene.frame_start, scene.frame_end) == (1, 32), (scene.frame_start, scene.frame_end)
        assert 'a000_003000_Sekiro' in bpy.data.actions and first.use_fake_user and second.use_fake_user
        assert 'Joined a000_003000_Sekiro and a000_003001_Sekiro.001' in scene.sekiro_retarget.status, scene.sekiro_retarget.status
        for frame in (1, 10, 17):
            assert close(spine_angle(rig, frame), .6 * (frame - 1) / 19), (frame, spine_angle(rig, frame))
        for frame in (21, 25, 32):
            assert close(spine_angle(rig, frame), -.4 + .4 * (frame - 18) / 14), (frame, spine_angle(rig, frame))
        for frame in (18, 19, 20):
            a, b = .6 * (frame - 1) / 19, -.4 + .4 * (frame - 18) / 14
            w = join.ease((frame - 18 + 1) / 4)
            assert close(spine_angle(rig, frame), a + (b - a) * w, 1e-3), (frame, spine_angle(rig, frame), a, b, w)
        print('Poses: frames 1-17 are the first clip, 21-32 the second, 18-20 ease from one to the other')

        # Root motion: before the blend the first clip's root, after it the second's, starting from the first's on 18.
        def game_root(values):
            x, y, z, yaw = values
            return Matrix.LocRotScale(Vector((x, z, y)), Euler((0, 0, -yaw)), None)
        anchor = game_root((0, 0, 1.0 * 17 / 19, .5 * 17 / 19))
        for frame in (5, 17):
            t = (frame - 1) / 19
            assert (root_at(root, frame).translation - game_root((0, 0, t, .5 * t)).translation).length < 1e-4, frame
        for frame in (21, 32):
            t = (frame - 18) / 14
            wanted = anchor @ game_root((.5 * t, 0, 0, .3 * t))
            got = root_at(root, frame)
            assert (got.translation - wanted.translation).length < 1e-4, (frame, got.translation, wanted.translation)
            assert got.to_quaternion().rotation_difference(wanted.to_quaternion()).angle < 1e-4, frame
        steps = [(root_at(root, frame + 1).translation - root_at(root, frame).translation).length for frame in range(1, 32)]
        assert max(steps) < .06, steps  # The first clip walks 0.053 per frame, the second 0.036.
        print(f'Root motion: goes on from frame 18 without a jump; the largest step is {max(steps):.4f}')

        # The export samples the joined clip with its root motion.
        output = folder / 'joined.motion.json'
        summary = export_motion(output)
        assert summary['action'] == joined.name and summary['frames'] == 32, summary
        import json
        exported = json.loads(output.read_text(encoding='utf-8'))
        assert len(exported['rootMotion']) == 32 and exported['frameCount'] == 32
        print('Export: 32 frames with root motion')

        # A cut: blend 0 puts the second clip on the frame after the first ends.
        retarget.assign_action(rig, first)
        retarget.assign_action(root, bpy.data.actions['a000_003000_RootMotion'])
        result = join.join(context, rig, first, second, 0)
        assert result['start'] == 21 and result['range'] == (1, 35) and result['overlap'] == 0, result
        assert rig.animation_data.action.name == 'a000_003000 + a000_003001.001', rig.animation_data.action.name
        assert close(spine_angle(rig, 20), .6) and close(spine_angle(rig, 21), -.4), (spine_angle(rig, 20), spine_angle(rig, 21))
        print('Cut: the second clip starts on frame 21; the name is numbered')

        # A 60 fps clip plays at its own speed: 28 of its frames are 14 of the scene's.
        retarget.assign_action(rig, first)
        retarget.assign_action(root, bpy.data.actions['a000_003000_RootMotion'])
        fast = join.load(folder / 'fast.blend', rig)[0]
        assert fast[join.RATE] == 60, dict(fast)
        result = join.join(context, rig, first, fast, 0)
        assert result['range'] == (1, 35), result
        assert close(spine_angle(rig, 28), -.4 + .4 * 7 / 14), spine_angle(rig, 28)
        assert any('60 fps' in line for line in result['warnings']), result['warnings']
        print('Frame rate: the 60 fps clip spans 14 frames of the 30 fps scene')

        # Refusals.
        for call, message in ((lambda: join.join(context, rig, first, first, 0), 'another animation'),
                              (lambda: join.join(context, rig, first, None, 0), 'Then'),
                              (lambda: join.load(folder / 'first.blend', rig), 'another .blend')):
            try:
                call()
                raise AssertionError('no refusal: ' + message)
            except ValueError as exc:
                assert message in str(exc), exc
        print('Join check passed')
    finally:
        sekiro_retarget.unregister()
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    main()
