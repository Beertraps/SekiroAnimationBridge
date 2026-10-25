"""The rig pair that a two-character bridge import recorded, filled into the panel when the file opens."""
import bpy

SOURCE_KEY = 'sekiro_bridge_retarget_source'


def imported_pair(scene):
    """(source, target) armatures that the bridge import recorded in this scene, or None."""
    pair = scene.get(SOURCE_KEY), scene.get('sekiro_bridge_export_rig')
    if not all(isinstance(rig, bpy.types.Object) and rig.type == 'ARMATURE' and rig.name in scene.objects for rig in pair):
        return None
    return pair if pair[0] != pair[1] else None


def fill(scene):
    """Use the imported pair while both rig fields are empty. Returns whether it filled them."""
    settings = getattr(scene, 'sekiro_retarget', None)
    pair = imported_pair(scene) if settings is not None and not (settings.source or settings.target) else None
    if pair is None:
        return False
    settings.source, settings.target = pair
    settings.status = f'The bridge import set {pair[0].name} as the source and {pair[1].name} as the target. Match bones next.'
    return True


@bpy.app.handlers.persistent
def fill_scenes(*_args):
    for scene in bpy.data.scenes:
        fill(scene)


def fill_open_file():
    """The add-on may be enabled while a file is open; fill its pair once the add-on can write to scenes."""
    fill_scenes()


def register():
    bpy.app.handlers.load_post.append(fill_scenes)
    bpy.app.timers.register(fill_open_file, first_interval=.1)


def unregister():
    if fill_scenes in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(fill_scenes)
    if bpy.app.timers.is_registered(fill_open_file):
        bpy.app.timers.unregister(fill_open_file)
