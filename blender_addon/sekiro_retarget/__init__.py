bl_info = {
    'name': 'Sekiro Retarget Assistant', 'author': 'Animation Bridge',
    'version': (0, 9, 0), 'blender': (4, 5, 0),
    'location': '3D View > Sidebar > Retarget and Animate', 'category': 'Animation',
    'description': 'Append bridge rigs, match bones, review mappings, bake retargeted motion, mirror and join animations, '
                   'add a control rig with fixes and export HKX',
}

import json
import math
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path
import blf
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper, ExportHelper
from mathutils import Matrix
from . import control_rig, export, figure, fixes, join, mapping, mirror, retarget


def armature_poll(self, obj):
    return obj.type == 'ARMATURE' and not obj.get(figure.OWNER)


def pair_changed(self, context):
    self.rows.clear()
    self.status = 'Choose the rig pair, then Match bones.'


def source_changed(self, context):
    self.enabled = bool(self.source)
    self.confidence = 1.0 if self.source else 0
    self.reason = 'Manual mapping' if self.source else 'Unassigned'
    if self.source:
        # A source bone drives one target bone, so giving Godfrey's L_Axe to Isshin's spear takes it from his katana.
        for row in self.id_data.sekiro_retarget.rows:
            if row.source == self.source and row.as_pointer() != self.as_pointer():
                row.source = ''
                row.reason = 'Source moved to ' + self.target


def preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def tell(operator, context, message, alert=False):
    """Report a result in Blender's status bar and keep it in the add-on's Log panels."""
    settings = context.scene.sekiro_retarget
    settings.status, settings.status_alert = message, alert
    operator.report({'WARNING'} if alert else {'INFO'}, message)


class SKR_Preferences(AddonPreferences):
    bl_idname = __package__
    bridge_folder: StringProperty(name='Animation Bridge folder', subtype='DIR_PATH',
        description='Folder of the Animation Bridge (or its standalone folder). Empty: the installation that ran last')
    writer: StringProperty(name='Conversion Python', subtype='FILE_PATH',
        description='Python with the conversion libraries. Empty: the one chosen in the bridge settings')
    figure_folder: StringProperty(name='Figure folder', subtype='DIR_PATH',
        description='Folder where saved body figures are kept, one file per skeleton. Empty: Blender\'s configuration '
                    'folder, under sekiro_retarget/figures')
    def draw(self,context):
        layout=self.layout
        layout.prop(self,'bridge_folder');layout.prop(self,'writer');layout.prop(self,'figure_folder')
        layout.label(text='Figures: '+str(figure.folder()),icon='ARMATURE_DATA')
        folder=export.bridge_folder(self);writer=export.writer_python(self)
        layout.label(text='Bridge: '+(str(folder) if folder else 'not found; start the bridge UI once or set the folder'),
                     icon='CHECKMARK' if folder else 'ERROR')
        layout.label(text='Conversion Python: '+str(writer),icon='CHECKMARK' if writer.is_file() else 'ERROR')


class SKR_BoneMap(PropertyGroup):
    target: StringProperty(name='Target bone')
    source: StringProperty(name='Source bone', update=source_changed,
        description='The source bone whose motion this target bone takes. A source bone drives one target bone only')
    enabled: BoolProperty(name='Use mapping', default=True,
        description='Bake this target bone from its source bone. Off: it does what Unmapped bones says')
    hidden: BoolProperty(name='Hide', default=False,
        description='Hide this weapon on every frame of the bake by scaling it to 0.1%, as FromSoftware clips hide '
                    'weapons; the bones below it hide with it')
    confidence: FloatProperty(name='Match strength', min=0, max=1)
    reason: StringProperty()
    suggestion: StringProperty()


class SKR_GripOffset(PropertyGroup):
    weapon: StringProperty()
    hand: StringProperty()
    matrix: FloatVectorProperty(size=16)  # The move and turn in the hand's space, row by row.


HELD_ITEMS=[]  # Blender keeps only references to the strings of dynamic enum items.


def held_items(self,context):
    rig=self.target
    held=[item.split('|') for item in (rig.get(retarget.HELD,'') if rig else '').split(';') if '|' in item]
    HELD_ITEMS[:]=[(f'{weapon}|{hand}',f'{weapon} in {hand}','') for weapon,hand in held] or [('NONE','No weapon','Bake first')]
    return HELD_ITEMS


def grip_offset(settings,weapon):
    return next((item for item in settings.grip_offsets if item.weapon==weapon),None)


def binder_changed(self,context):
    """Turning on Add to animation binder fills in the clip's own archive, or a copy of it, where the scene records it."""
    if self.export_binder and not self.export_binder_path:
        self.export_binder_path=export.default_binder(self.target,self.export_path)


# Blender keeps only references to the item strings of a dynamic enum, so the list lives here.
EXPORT_GAMES = []


def export_game_items(self, context):
    """The games the bridge exports, from its registry (games.json), after 'Stored in scene'."""
    EXPORT_GAMES[:] = [('auto', 'Stored in scene', 'The game recorded when the clip was imported (bridge 0.5 and later)')] + \
        [(g['id'], g['name'], '') for g in export.registry() if g.get('capabilities', {}).get('export')]
    return EXPORT_GAMES


class SKR_Settings(PropertyGroup):
    source: PointerProperty(name='Source rig', type=bpy.types.Object, poll=armature_poll, update=pair_changed,
        description='The armature whose animation is copied, such as the donor of a two-character import')
    target: PointerProperty(name='Target rig', type=bpy.types.Object, poll=armature_poll, update=pair_changed,
        description='The armature that receives the animation: the character that the bridge imported into this scene')
    rows: CollectionProperty(type=SKR_BoneMap)
    active_row: IntProperty()
    review_only: BoolProperty(name='Show unmatched / uncertain only', default=False,
        description='List only the target bones without a source bone, switched off, or matched below 94%')
    tracked_only: BoolProperty(name='Only bones the clip animates', default=True,
        description='For rigs imported by the bridge, match only the bones that the HKX clip animates, its tracks; '
                    'the other bones of the model follow their parents. Takes effect at the next match')
    method: EnumProperty(name='Bake method', description='How the target takes the source\'s motion', items=[
        ('BONES','Bone by bone','Each target bone takes the motion of the source bone that the bone list gives it'),
        ('BODY','Full body','Finds the body in both rigs without a bone list: each chain, such as the '
                'spine or an arm, takes the source chain\'s shape over its own bones, the feet stay on the source\'s '
                'footprint, scaled to the legs, and the hands come together where the source\'s do. Bones outside the '
                'body, such as weapons, take their source bones from the bone list, or from automatic matching')],
        default='BONES')
    rest_mode: EnumProperty(name='Rest stance', description='How the target\'s limbs stand before the motion is applied', items=[
        ('ALIGN','Match source stance','Pose the target limbs and hands like the source rest pose before applying motion, '
                 'so an A-pose target follows a T-pose source without lowered or raised arms'),
        ('REST','Keep target stance','Apply source rotations from the target rest pose; for rigs that share a rest stance')], default='ALIGN')
    root_motion: EnumProperty(name='Root motion', description='Where the clip\'s root motion, the travel that moves the '
                                                              'character in the game, comes from', items=[
        ('AUTO','Automatic','The source root motion when the source has it; otherwise body travel becomes root motion '
                'when the body moves far, and none when it stays in place'),
        ('SOURCE','From source root','Copy the source HKX_RootMotion object, scaled to the target'),
        ('EXTRACT','From body travel','Ground travel of the body becomes root motion; the body stays over the root'),
        ('TARGET','Keep target root','Keep the target clip\'s original root motion (same length only)'),
        ('NONE','None','Hold the root still; the body travels inside the animation')], default='AUTO')
    root_yaw: BoolProperty(name='Turn root with the body', default=False,
        description='When body travel becomes root motion, the root also follows the body\'s heading')
    unmapped: EnumProperty(name='Unmapped bones', description='What target bones without a source bone do', items=[
        ('KEEP','Keep target animation','Unmapped bones, such as cloth, face or weapon bones, keep the target clip\'s animation'),
        ('REST','Rest pose','Unmapped bones hold their rest pose; for bridge rigs, the HKX reference pose')], default='KEEP')
    auto_scale: BoolProperty(name='Scale travel by leg length', default=True,
        description='Scale body travel and root motion by the ratio of hip heights; bone lengths remain the target\'s')
    travel_scale: FloatProperty(name='Travel scale',default=1.0,min=.01,max=20.0,
        description='Scale of body travel and root motion while Scale travel by leg length is off')
    body_translation: BoolProperty(name='Move body with source hips', default=True,
        description='The bone above the target hips and spine follows the source hips, so legs and upper body move together')
    use_figures: BoolProperty(name='Use saved figures', default=True,
        description='Where a body figure is saved for a rig\'s skeleton, the bake takes the body\'s bones and the leg '
                    'length, hip joints, height, limbs and feet from it. Off: from the skeleton, as without a figure')
    foot_contacts: EnumProperty(name='Foot contacts', description='How the full-body bake finds where a foot stands', items=[
        ('SPEED','Slow feet stand','A foot stands where it moves slower than a quarter leg length per second; it stands '
                 'where the source\'s foot stands, scaled'),
        ('PIVOT','Planted, sliding, free (Biped)','As 3ds Max\'s Biped finds footsteps: a foot is planted where its heel, '
                 'ankle, ball or toe tip stays on the ground and within the tolerance for 0.1 s, and that point then stands still on the '
                 'ground, the target\'s foot set on it by its own shape, so the foot can roll from heel to toe; it slides '
                 'where it moves along the ground, keeping its path on the target\'s ground; it is free elsewhere')],
        default='SPEED')
    plant_tolerance: FloatProperty(name='Plant tolerance', default=.15, min=.01, max=1.0, precision=2,
        description='How far a planted point of the foot may move and still count as planted, and how close to the '
                    'ground a sliding foot stays, in lengths of the source\'s foot. Biped\'s default is 0.15')
    jump_scale: BoolProperty(name='Scale jumps by height', default=False,
        description='As Biped scales gravity with the figure\'s height: where no foot is on the ground, the body rises '
                    'above the line from lift-off to touchdown as far as the target\'s height against the source\'s, '
                    'instead of by leg length; the time in the air stays the same')
    prop_scale: EnumProperty(name='Moving props', description='Where bones outside the body, whose source bones move away '
                                                              'from their parents, such as a thrown weapon, go', items=[
        ('NONE','Keep target place','They keep their place on their parent and turn like the source\'s'),
        ('HEIGHT','By height','They move from the nearest mapped bone above them as far as the source\'s, scaled by '
                  'the target\'s height against the source\'s'),
        ('LIMB','By limb size','As By height, scaled by the limb that carries them: the arm, the leg, the torso, or '
                'the leg length for a bone above the hips')], default='NONE')
    body_clearance: BoolProperty(name='Keep hands out of the body', default=False,
        description='Where a hand, or what it holds, would go into the target torso deeper than the source\'s hand goes '
                    'into its own body, move it out through the arm, easing in and out; for a target with a thicker body '
                    'than the source')
    arm_gap: BoolProperty(name='Keep arms close to the body', default=False,
        description='Where the source holds an arm close to its own body, turn the target\'s arm in at the shoulder until '
                    'it stands as close to the target\'s torso, at the target\'s size, easing in and out; for a source '
                    'with a wider body than the target. Needs body meshes on both rigs')
    weapon_grip: EnumProperty(name='Weapon grip', items=[
        ('REST','Rest-relative grip','The weapon stays at the target\'s own grip point in the hand, from its own clip or '
                'else its rest pose, and turns there as the source\'s weapon turns in the source\'s hand away from its rest '
                'pose, and each finger of both hands as the source\'s finger turns from its rest pose; needs no meshes. '
                'For rigs whose rest poses hold their weapons alike, as FromSoftware\'s do'),
        ('SOURCE','Source\'s grip','The weapon sits and turns in the hand as the source\'s weapon sits and turns in the '
                  'source\'s hand, scaled to the hand, with the source\'s fingers: the fist holds the part of the weapon '
                  'that matches the part the source\'s fist holds, found from both weapons\' shapes; for a weapon made '
                  'to fit the source\'s grip'),
        ('OWN','Target\'s own grip','The weapon sits in the hand as in the target\'s own clip, with the fingers closed '
               'around it as there; the wrist turns so that the blade follows the source\'s')], default='REST')
    blade_follow: FloatProperty(name='Blade follows source', default=100.0, min=0.0, max=100.0, subtype='PERCENTAGE', precision=0,
        description='How far the wrist turns so that the blade points as the source\'s does: 100% keeps the source\'s '
                    'blade directions, 0% keeps the wrist as the source turns it. Where the two grips differ, turning '
                    'bends the wrist sideways')
    finger_fit: BoolProperty(name='Bend fingers onto the weapon', default=False,
        description='With the rest-relative or the source\'s grip, bend each finger joint until its skin just touches '
                    'the weapon: open where it goes in, close a little where it stands off. Changes the source\'s '
                    'finger pose. Uses the meshes that the target deforms')
    second_hand: BoolProperty(name='Second hand on the weapon', default=False,
        description='Where the source holds its weapon with both hands, the target\'s other hand goes onto the target\'s '
                    'weapon at the matching place, through the arm, easing on and off')
    grip_offsets: CollectionProperty(type=SKR_GripOffset)
    grip_item: EnumProperty(name='Weapon',items=held_items,
        description='The weapon to align in its hand: one that the last bake put in a hand')
    grip_adjusting: StringProperty()  # weapon|hand while the user poses it.
    grip_frame: IntProperty()
    grip_start: FloatVectorProperty(size=16)  # The weapon in its hand when Adjust weapon started.
    timing: EnumProperty(name='Clip timing', description='How long the baked clip runs', items=[
        ('SOURCE','Use source length','Update target metadata to the source duration'),
        ('TARGET','Fit target length','Resample source motion across the target clip length')], default='SOURCE')
    export_path: StringProperty(name='Output', subtype='FILE_PATH', description='HKX file to write; a .motion.json sidecar is written beside it')
    export_format: EnumProperty(name='Format', description='How the HKX stores the frames', items=[
        ('interleaved','Interleaved','Every frame stored exactly; larger files'),
        ('spline','Spline','Compressed like the game\'s own clips; small differences within the tolerance')], default='interleaved')
    export_quantization: EnumProperty(name='Rotations', description='How precisely spline compression stores rotations', items=[
        ('threecomp40','40-bit','The default'),('threecomp48','48-bit','Finer rotations, a larger file'),
        ('uncompressed','Full floats','Exact rotations, the largest file')], default='threecomp40')
    export_tolerance: FloatProperty(name='Tolerance', default=.001, min=1e-6, max=.1, precision=4,
        description='Largest position change, in metres, that spline compression may introduce')
    export_tracks: EnumProperty(name='Tracks', description='Which bones get a track in the HKX', items=[
        ('original','Original clip tracks','Keep the track list of the clip the target was imported from; other bones stay under the game\'s control'),
        ('keyed','Original tracks + keyed bones','Also write tracks for bones keyed in the action'),
        ('all','Every skeleton bone','Write a track for each bone')], default='original')
    export_frames: EnumProperty(name='Frames', items=[
        ('scene','Scene range','The scene start and end frames (set by Bake)'),
        ('action','Action range','The keyframe range of the action'),
        ('clip','Clip length','Frames 1 to the clip\'s frame count')], default='scene')
    export_game: EnumProperty(name='Game', items=export_game_items, default=0,
        description='Game of the target clip; choose it for scenes imported before the bridge recorded it')
    export_root: EnumProperty(name='Root motion', description='The root motion that the HKX gets', items=[
        ('AUTO','As baked','The target\'s HKX_RootMotion object, when it has one'),
        ('NONE','None','Write no root motion')], default='AUTO')
    export_verify: BoolProperty(name='Read back and compare', default=True,
        description='Decode the written HKX again and report the largest difference')
    export_replace: BoolProperty(name='Replace existing', default=False,
        description='Write over the output .hkx and its .motion.json sidecar if they exist')
    export_binder: BoolProperty(name='Add to animation binder', default=False, update=binder_changed,
        description='Also put the HKX into an animation binder (.anibnd.dcx): it replaces the clip of the same name, or '
                    'is added as a new clip with the ID that the binder\'s clips follow. The binder is kept as .bak before '
                    'its first change')
    export_binder_path: StringProperty(name='Binder', subtype='FILE_PATH',
        description='The .anibnd.dcx to add the HKX to; at first the archive the clip came from. The game\'s own files '
                    'are protected: for a clip from the game folder, a copy of its archive beside the HKX, made from the '
                    'game\'s archive the first time')
    export_member: StringProperty(name='Name in binder',
        description='The clip\'s member name, such as a050_002000.hkx. Empty: the clip\'s own name, which replaces the '
                    'original clip. A name the binder does not hold yet adds a new animation, which needs a TAE entry '
                    'before the game plays it')
    status: StringProperty(default='Open the receiving character first, then append a source.')
    status_alert: BoolProperty()  # The last message warned or failed.


FIX_LIMBS=[]  # Blender keeps only references to the strings of dynamic enum items.


def fix_limb_items(self,context):
    rig=control_rig.target(context) if context else None
    items=[(str(index),limb['label'],'') for index,limb in fixes.limbs(rig,self.task)] if control_rig.present(rig) else []
    if self.task=='ADJUST':items.append((fixes.SELECTED,'Selected controls','The controls selected in Pose Mode'))
    FIX_LIMBS[:]=items or [('NONE','No limb','This rig has no limb with IK controls for this fix')]
    return FIX_LIMBS


def fix_task_changed(self,context):
    self.poses.clear();self.status=''
    rig=control_rig.target(context)
    if not control_rig.present(rig):return
    values=fixes.defaults(rig,self.task)
    if values['limb']:self.limb=values['limb']
    self.target,self.held=values['target'],values['held']
    if self.task=='HAND':self.span='CLIP'
    elif self.span=='CLIP':
        self.span='RANGE';self.frame_start=self.frame_end=context.scene.frame_current


def fix_limb_changed(self,context):
    self.poses.clear()
    rig=control_rig.target(context)
    if control_rig.present(rig) and self.limb.isdigit():
        values=fixes.defaults(rig,self.task,int(self.limb))
        self.target,self.held=values['target'],values['held']


def fix_held_changed(self,context):
    self.poses.clear()


class SKR_FixPose(PropertyGroup):
    frame: IntProperty()
    bone: StringProperty()
    matrix: FloatVectorProperty(size=16)
    basis: FloatVectorProperty(size=16)


class SKR_Fix(PropertyGroup):
    task: EnumProperty(name='Fix',items=fixes.TASKS,default='HAND',update=fix_task_changed,
        description='The cleanup that the fix makes with the control rig')
    limb: EnumProperty(name='Limb',items=fix_limb_items,update=fix_limb_changed,
        description='The arm or leg whose IK controls the fix keys')
    target: StringProperty(name='Follow',description='The bone to keep the hand or its weapon on; empty: the fix\'s default')
    held: StringProperty(name='Weapon',update=fix_held_changed,
        description='The weapon bone that the hand holds; empty: the weapon in that hand')
    span: EnumProperty(name='Frames',items=[('CLIP','Whole clip','Every frame of the scene range'),
        ('RANGE','Frames','From the start frame to the end frame')],default='CLIP',
        description='The frames on which the fix holds')
    frame_start: IntProperty(name='Start',default=1,description='First frame on which the fix holds fully')
    frame_end: IntProperty(name='End',default=1,description='Last frame on which the fix holds fully')
    blend: FloatProperty(name='Blend',default=.2,min=0,soft_max=1,step=5,precision=2,unit='TIME_ABSOLUTE',
        description='How long the fix eases in before the start frame and out after the end frame')
    poses: CollectionProperty(type=SKR_FixPose)
    pose_rig: StringProperty()
    status: StringProperty()


def second_poll(self,action):
    rig=control_rig.target(bpy.context)
    current=rig.animation_data.action if rig and rig.animation_data else None
    return action!=current and join.joinable(action,rig)


class SKR_Join(PropertyGroup):
    second: PointerProperty(name='Then',type=bpy.types.Action,poll=second_poll,
        description='The animation that plays after the armature\'s own: an action of this armature\'s bones, such as '
                    'one brought in with Load clip from .blend')
    blend: FloatProperty(name='Blend',default=.2,min=0,soft_max=1,step=5,precision=2,unit='TIME_ABSOLUTE',
        description='How long the end of the first animation and the start of the second play at once, the pose '
                    'easing from the one to the other. 0 cuts from the one to the other')


def fix_limb(rig,fix):
    """The Fixes panel's limb as an index into the control rig's limbs, or None for the selected controls."""
    if fix.limb.isdigit() and any(index==int(fix.limb) for index,limb in fixes.limbs(rig,fix.task)):return int(fix.limb)
    if fix.task=='ADJUST' and fix.limb==fixes.SELECTED:return None
    value=fixes.defaults(rig,fix.task)['limb']
    return int(value) if value.isdigit() else None


def fix_frames(context,fix):
    scene=context.scene
    return (scene.frame_start,scene.frame_end) if fix.span=='CLIP' else (fix.frame_start,fix.frame_end)


def fix_blend(context,fix):
    scene=context.scene
    return max(0,round(fix.blend*scene.render.fps/scene.render.fps_base))


def fix_posed(rig,fix):
    """{frame: {bone: (armature-space matrix, matrix_basis)}} of the frames posed with Use this pose."""
    posed={}
    if fix.pose_rig!=rig.name:return posed
    for item in fix.poses:
        matrix,basis=list(item.matrix),list(item.basis)
        posed.setdefault(item.frame,{})[item.bone]=(Matrix([matrix[i:i+4] for i in range(0,16,4)]),
                                                     Matrix([basis[i:i+4] for i in range(0,16,4)]))
    return posed


def selected_controls(context):
    return [bone.name for bone in (getattr(context,'selected_pose_bones',None) or [])]


def build_mapping(settings):
    if not settings.source or not settings.target or settings.source == settings.target:
        raise ValueError('Choose two different armatures.')
    def infos(rig):
        return retarget.rig_bones(rig,retarget.bone_infos(rig,settings.tracked_only))
    rows = mapping.match_bones(infos(settings.source),infos(settings.target),retarget.hidden_bones(settings.source))
    settings.rows.clear()
    for item in rows:
        row=settings.rows.add()
        row.target=item['target'];row.source=item['source'];row.enabled=bool(item['source'])
        row.confidence=item['confidence'];row.reason=item['reason'];row.suggestion=item['suggestion']
    count=sum(bool(row.source and row.enabled) for row in settings.rows)
    settings.status=f'{count} / {len(rows)} target bones matched. Review the rest before baking.'
    return count


class SKR_OT_match(Operator):
    bl_idname='sekiro_retarget.match_bones'
    bl_label='Match bones automatically'
    bl_description=('Match by name, anatomical role and rest position, respecting left/right and avoiding duplicate source '
                    'assignments. A new match replaces the bone list, changes included')
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            settings=context.scene.sekiro_retarget
            build_mapping(settings);self.report({'INFO'},settings.status)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_use_active(Operator):
    bl_idname='sekiro_retarget.use_active'
    bl_label='Use selected armature'
    bl_description='Fill this field with the armature selected in the viewport or Outliner'
    bl_options={'REGISTER','UNDO'}
    role: EnumProperty(items=[('source','Source',''),('target','Target','')])
    def execute(self,context):
        if not context.object or context.object.type!='ARMATURE':
            self.report({'ERROR'},'Select an armature in the Outliner or viewport.');return {'CANCELLED'}
        setattr(context.scene.sekiro_retarget,self.role,context.object)
        return {'FINISHED'}


class SKR_OT_append(Operator,ImportHelper):
    bl_idname='sekiro_retarget.append_source'
    bl_label='Append source .blend'
    bl_description='Bring in the source rig, meshes, animation, root motion and embedded bridge metadata'
    bl_options={'REGISTER','UNDO'}
    filename_ext='.blend'
    filter_glob: StringProperty(default='*.blend',options={'HIDDEN'})
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        try:
            if not settings.target:
                recorded=context.scene.get('sekiro_bridge_export_rig')
                recorded=recorded if isinstance(recorded,bpy.types.Object) else bpy.data.objects.get(context.scene.get('sekiro_bridge_active_rig',''))
                if recorded and recorded.type=='ARMATURE':settings.target=recorded
            path=Path(self.filepath).resolve()
            if bpy.data.filepath and path==Path(bpy.data.filepath).resolve():
                raise ValueError('Choose a different source file from the receiving character scene.')
            with bpy.data.libraries.load(str(path),link=False) as (src,dst):
                original_objects=list(src.objects)
                original_texts=[name for name in src.texts if name.startswith('Sekiro Source - ')]
                dst.collections=list(src.collections);dst.objects=original_objects;dst.texts=original_texts
            object_map=dict(zip(original_objects,dst.objects));text_map=dict(zip(original_texts,dst.texts))
            collections=[c for c in dst.collections if c]
            children={child for c in collections for child in c.children}
            for collection in collections:
                if collection not in children:context.scene.collection.children.link(collection)
            for obj in dst.objects:
                if obj and not obj.users_collection:context.scene.collection.objects.link(obj)
            imported=[obj for obj in dst.objects if obj and obj.type=='ARMATURE']
            for rig in imported:
                text=text_map.get(rig.get('sekiro_bridge_source_text',''))
                if text:
                    rig['sekiro_bridge_source_text']=text.name;rig['sekiro_bridge_source_text_data']=text
                root=object_map.get(rig.get('sekiro_root_motion_object',''))
                if root:
                    rig['sekiro_root_motion_object']=root.name;rig['sekiro_root_motion_data']=root
            animated=[obj for obj in imported if obj.animation_data and obj.animation_data.action]
            preferred=[obj for obj in animated if obj.get('sekiro_animation_bridge')]
            if not (preferred or animated):raise ValueError('The source file contains no animated armature.')
            settings.source=(preferred or animated)[0]
            if settings.target:build_mapping(settings)
            self.report({'INFO'},f'Appended {len(imported)} armature(s); source is {settings.source.name}.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_suggestion(Operator):
    bl_idname='sekiro_retarget.accept_suggestion'
    bl_label='Use suggestion'
    bl_description='Give this target bone the suggested source bone'
    bl_options={'REGISTER','UNDO'}
    index: IntProperty()
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        row=settings.rows[self.index]
        if row.suggestion:
            if any(other.enabled and other.source==row.suggestion for other in settings.rows):
                self.report({'ERROR'},'That source bone is already assigned.');return {'CANCELLED'}
            row.source=row.suggestion;row.reason='Suggestion accepted manually'
        return {'FINISHED'}


class SKR_OT_accept_all(Operator):
    bl_idname='sekiro_retarget.accept_all_suggestions'
    bl_label='Accept all suggestions'
    bl_description='Assign every suggested source bone that no other bone uses or is suggested for'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        used={row.source for row in settings.rows if row.enabled and row.source}
        wanted=Counter(row.suggestion for row in settings.rows if not row.source and row.suggestion)
        count=0
        for row in settings.rows:
            if not row.source and row.suggestion and row.suggestion not in used and wanted[row.suggestion]==1:
                row.source=row.suggestion;row.reason='Suggestion accepted';used.add(row.source);count+=1
        skipped=sum(1 for row in settings.rows if not row.source and row.suggestion)
        self.report({'INFO'},f'Accepted {count} suggestions'+(f'; {skipped} share a source bone and need review.' if skipped else '.'))
        return {'FINISHED'}


class SKR_OT_mirror(Operator):
    bl_idname='sekiro_retarget.mirror_mappings'
    bl_label='Mirror mappings'
    bl_description='Copy the assignments of one side to the matching bones on the other side of both rigs'
    bl_options={'REGISTER','UNDO'}
    side: EnumProperty(items=[('L','Left to right',''),('R','Right to left','')])
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        if not settings.rows:
            self.report({'ERROR'},'Run Match bones first.');return {'CANCELLED'}
        targets=mapping.Rig(retarget.rig_bones(settings.target));sources=mapping.Rig(retarget.rig_bones(settings.source))
        rows={row.target:row for row in settings.rows}
        used={row.source for row in settings.rows if row.enabled and row.source}
        count=0
        for row in list(settings.rows):
            info=targets.bones.get(row.target)
            if not row.enabled or not row.source or not info or info.side!=self.side:continue
            other=rows.get(targets.counterpart(row.target));source=sources.counterpart(row.source)
            if not other or not source or other.source==source or source in used:continue
            used.discard(other.source)
            other.source=source;other.reason='Mirrored from '+row.target;used.add(source);count+=1
        self.report({'INFO'},f'Mirrored {count} assignments.')
        return {'FINISHED'}


class SKR_OT_bake(Operator):
    bl_idname='sekiro_retarget.bake'
    bl_label='Bake motion onto target'
    bl_description=('Create a new target action from the reviewed map, or with the full-body method from the bodies of '
                    'both rigs; the original action is kept')
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        return run_bake(self,context)


def no_open_figures(settings):
    """Refuse while a body figure is open: its rig shows its Rest Position, not its animation."""
    for rig in (settings.source,settings.target):
        if rig and figure.edited(rig):
            raise ValueError(f'The figure of {rig.name} is open, and {rig.name} shows its rest pose. Save or close the '
                             'figure first (Body figures).')


def run_bake(operator,context):
    settings=context.scene.sekiro_retarget
    try:
        no_open_figures(settings)
        result=retarget.bake(context.scene,settings)
        source=('the full body' if result['bake_method']=='BODY' else f"{result['mapped']} mapped bones")
        settings.status=(f"Baked {result['frames']} frames from {source}; travel scale {result['scale']:.3f}; "
                         f"root motion {result['root_motion'].lower()}."+''.join(' '+line for line in result['notes']+result['warnings']))
        settings.status_alert=bool(result['warnings'])
        if not settings.export_path and bpy.data.filepath:
            clip=(retarget.read_motion(settings.target) or {}).get('clip','')
            if clip:settings.export_path='//'+Path(clip).stem+'.hkx'
        operator.report({'WARNING'} if result['warnings'] else {'INFO'},settings.status)
        return {'FINISHED'}
    except Exception as exc:
        operator.report({'ERROR'},str(exc));return {'CANCELLED'}


def held_weapon(settings):
    """(weapon, hand) chosen under Weapon in hand, or None where the target has no such bones."""
    rig=settings.target
    if not rig or '|' not in settings.grip_item:return None
    weapon,hand=settings.grip_item.split('|')
    return (weapon,hand) if weapon in rig.pose.bones and hand in rig.pose.bones else None


def weapon_in_hand(rig,weapon,hand):
    bones=rig.pose.bones
    return retarget.in_hand_of({weapon:bones[weapon].matrix,hand:bones[hand].matrix},hand,weapon)


class SKR_OT_grip_adjust(Operator):
    bl_idname='sekiro_retarget.grip_adjust'
    bl_label='Adjust weapon'
    bl_description=('Select the weapon on this frame, so that you can turn (R) and move (G) it in the hand; Apply to all '
                    'frames then bakes again with the weapon sitting in the hand that way on every frame')
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        settings=context.scene.sekiro_retarget;held=held_weapon(settings);rig=settings.target
        if not held:
            self.report({'ERROR'},'Bake first: Weapon in hand aligns a weapon that the bake put in a hand.');return {'CANCELLED'}
        weapon,hand=held
        if rig.mode!='POSE':
            if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            for obj in context.selected_objects:obj.select_set(False)
            rig.hide_set(False);rig.select_set(True);context.view_layer.objects.active=rig
            bpy.ops.object.mode_set(mode='POSE')
        for bone in rig.pose.bones:bone.bone.select=bone.name==weapon
        rig.data.bones.active=rig.data.bones[weapon]
        context.view_layer.update()
        settings.grip_start=[value for row in weapon_in_hand(rig,weapon,hand) for value in row]
        settings.grip_frame=context.scene.frame_current;settings.grip_adjusting=settings.grip_item
        return {'FINISHED'}


class SKR_OT_grip_apply(Operator):
    bl_idname='sekiro_retarget.grip_apply'
    bl_label='Apply to all frames'
    bl_description=('Bake again, with the weapon sitting in the hand on every frame as you posed it on this one. The '
                    'alignment stays for later bakes until you reset it')
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        scene=context.scene;settings=scene.sekiro_retarget;rig=settings.target
        if '|' not in settings.grip_adjusting:return {'CANCELLED'}
        weapon,hand=settings.grip_adjusting.split('|')
        if scene.frame_current!=settings.grip_frame:
            self.report({'ERROR'},f'Go back to frame {settings.grip_frame}, where you started, and pose the weapon there; '
                                  'changing the frame resets an unkeyed pose.');return {'CANCELLED'}
        context.view_layer.update()
        change=weapon_in_hand(rig,weapon,hand)@retarget.matrix_of(settings.grip_start).inverted()
        item=grip_offset(settings,weapon)
        if item is None:
            item=settings.grip_offsets.add();item.weapon=weapon;item.matrix=[float(i%5==0) for i in range(16)]
        item.hand=hand
        item.matrix=[value for row in change@retarget.matrix_of(item.matrix) for value in row]
        settings.grip_adjusting=''
        return run_bake(self,context)


class SKR_OT_grip_cancel(Operator):
    bl_idname='sekiro_retarget.grip_cancel'
    bl_label='Cancel'
    bl_description='Put the weapon back where the bake put it'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        settings=context.scene.sekiro_retarget;settings.grip_adjusting=''
        context.scene.frame_set(context.scene.frame_current)
        return {'FINISHED'}


class SKR_OT_grip_reset(Operator):
    bl_idname='sekiro_retarget.grip_reset'
    bl_label='Reset'
    bl_description='Forget your alignment of this weapon and bake again with the grip alone'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        settings=context.scene.sekiro_retarget;held=held_weapon(settings)
        if not held:return {'CANCELLED'}
        for index,item in enumerate(settings.grip_offsets):
            if item.weapon==held[0]:settings.grip_offsets.remove(index);break
        settings.grip_adjusting=''
        return run_bake(self,context)


class SKR_OT_export_target(Operator):
    bl_idname='sekiro_retarget.set_export_target'
    bl_label='Use target in the bridge UI'
    bl_description='Make the target the rig that the Animation Bridge UI and CLI export from this .blend'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            retarget.set_export_target(context.scene,context.scene.sekiro_retarget.target)
            self.report({'INFO'},'Bridge export target updated. Save this .blend before exporting with the bridge UI.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


EXPORTING=set()  # Scenes whose HKX export is running, so that its panel shows the progress.


class SKR_OT_export_hkx(Operator):
    bl_idname='sekiro_retarget.export_hkx'
    bl_label='Export HKX'
    bl_description='Sample the target action and write HKX with the Animation Bridge, as its export page does. Esc cancels'
    _timer=None
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        try:
            no_open_figures(settings)
            self.job=export.start(context,settings,preferences(context))
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        settings.status,settings.status_alert='Writing HKX...',False
        EXPORTING.add(context.scene.name)
        self._timer=context.window_manager.event_timer_add(.25,window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def modal(self,context,event):
        settings=context.scene.sekiro_retarget
        if event.type=='ESC':self.job.cancel()
        if event.type!='TIMER':return {'PASS_THROUGH'}
        if not self.job.done:
            settings.status=f'{self.job.message} ({self.job.progress}%). Esc cancels.'
        else:
            context.window_manager.event_timer_remove(self._timer)
            settings.status,settings.status_alert=export.summary(self.job),self.job.failed
            EXPORTING.discard(context.scene.name)
        for area in context.screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()
        if not self.job.done:return {'PASS_THROUGH'}
        self.report({'ERROR'} if self.job.failed else {'INFO'},settings.status)
        return {'CANCELLED'} if self.job.failed else {'FINISHED'}


class SKR_OT_save_map(Operator,ExportHelper):
    bl_idname='sekiro_retarget.save_map'
    bl_label='Save bone map'
    bl_description='Save the bone list to a .json file, to load it for other clips of the same two characters'
    filename_ext='.json'
    filter_glob: StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            rows=context.scene.sekiro_retarget.rows
            document=dict(format='sekiro-retarget-map',version=1,
                          mappings=[dict(target=r.target,source=r.source,enabled=r.enabled,hidden=r.hidden) for r in rows])
            Path(self.filepath).write_text(json.dumps(document,indent=2),encoding='utf-8')
            self.report({'INFO'},f'Saved {len(rows)} bones to {Path(self.filepath).name}.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_load_map(Operator,ImportHelper):
    bl_idname='sekiro_retarget.load_map'
    bl_label='Load bone map'
    bl_description='Match bones, then give the target bones of a saved bone map the source bones it names'
    bl_options={'REGISTER','UNDO'}
    filename_ext='.json'
    filter_glob: StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            settings=context.scene.sekiro_retarget
            document=json.loads(Path(self.filepath).read_text(encoding='utf-8-sig'))
            if document.get('format')!='sekiro-retarget-map' or document.get('version')!=1:
                raise ValueError('Choose a Sekiro Retarget Assistant mapping file.')
            build_mapping(settings)
            rows={row.target:row for row in settings.rows}
            for item in document['mappings']:
                if item['target'] not in rows:continue
                row=rows[item['target']]
                row.source=item['source'] if item['source'] in settings.source.data.bones else ''
                row.enabled=bool(row.source and item.get('enabled',True));row.reason='Loaded bone map'
                row.hidden=bool(item.get('hidden',False))
            count=sum(bool(row.source and row.enabled) for row in settings.rows)
            settings.status=(f'Loaded {Path(self.filepath).name}: {count} / {len(settings.rows)} target bones matched. '
                             'Review the rest before baking.')
            self.report({'INFO'},settings.status)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_add_control_rig(Operator):
    bl_idname='sekiro_retarget.add_control_rig'
    bl_label='Add control rig'
    bl_description=('Add FK controls along the limbs and IK arms and legs with an IK/FK switch to the armature, '
                    'and bake its action onto them. The game bones follow the controls, so export works as before')
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            result=control_rig.add(context,control_rig.target(context))
            limbs=', '.join(result['limbs']).lower() or 'no recognised arms or legs'
            self.report({'INFO'},f"Added {result['controls']} controls with IK for {limbs}"+
                        (f"; baked {result['frames']} frames." if result['frames'] else '.'))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_remove_control_rig(Operator):
    bl_idname='sekiro_retarget.remove_control_rig'
    bl_label='Remove control rig'
    bl_description='Remove the control rig, keeping the motion it gives or restoring the action from before it was added'
    bl_options={'REGISTER','UNDO'}
    keep: EnumProperty(name='Animation',items=[
        ('EDITED','Keep the edited motion','Bake what the controls do onto the game bones as a new action'),
        ('ORIGINAL','Restore the original action','Drop the control rig animation and play the action from before it was added')],
        default='EDITED')
    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)
    def execute(self,context):
        try:
            action=control_rig.remove(context,control_rig.target(context),self.keep=='EDITED')
            self.report({'INFO'},'Control rig removed'+(f'; the armature plays {action.name}.' if action else '.'))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_mirror_animation(Operator):
    bl_idname='sekiro_retarget.mirror_animation'
    bl_label='Mirror animation'
    bl_description=('Add a left-right mirrored copy of the armature\'s action, with mirrored root motion, and play it, '
                    'so a right-handed slash becomes left-handed. The original action is kept')
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        if control_rig.present(control_rig.target(context)):
            cls.poll_message_set('Remove the control rig first; you can add it again after mirroring.');return False
        return control_rig.target(context) is not None
    def execute(self,context):
        try:
            result=mirror.mirror(context,control_rig.target(context))
            tell(self,context,mirror.summary(result),bool(result['warnings']))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_join_load(Operator,ImportHelper):
    bl_idname='sekiro_retarget.join_load'
    bl_label='Load clip from .blend'
    bl_description=('Bring in the animations of another bridge scene of the same skeleton, with their root motion, '
                    'without its objects, to join one after the armature\'s own')
    bl_options={'REGISTER','UNDO'}
    filename_ext='.blend'
    filter_glob: StringProperty(default='*.blend',options={'HIDDEN'})
    def execute(self,context):
        try:
            rig=control_rig.target(context)
            if rig is None:raise ValueError('Select the armature whose animations to join.')
            actions=join.load(self.filepath,rig)
            context.scene.sekiro_join.second=actions[0]
            tell(self,context,f'Loaded {mirror.listed([action.name for action in actions])} from {Path(self.filepath).name}; '
                              f'{actions[0].name} plays after {rig.name}\'s own animation when you join them.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_join(Operator):
    bl_idname='sekiro_retarget.join_animations'
    bl_label='Join animations'
    bl_description=('Add one animation that plays the armature\'s own and then the one under Then, blended over the '
                    'blend, with root motion that goes on from where the first leaves it, and play it. Both originals '
                    'are kept')
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        rig=control_rig.target(context)
        if control_rig.present(rig):
            cls.poll_message_set('Remove the control rig first; you can add it again after joining.');return False
        if not context.scene.sekiro_join.second:
            cls.poll_message_set('Choose the animation that comes after it under Then.');return False
        return rig is not None
    def execute(self,context):
        try:
            rig=control_rig.target(context);data=rig.animation_data
            result=join.join(context,rig,data.action if data else None,context.scene.sekiro_join.second,
                             context.scene.sekiro_join.blend)
            context.scene.sekiro_join.second=None
            tell(self,context,join.summary(result),bool(result['warnings']))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_control_rig_switch(Operator):
    bl_idname='sekiro_retarget.control_rig_switch'
    bl_label='Switch IK/FK'
    bl_options={'REGISTER','UNDO'}
    limb: IntProperty(options={'HIDDEN'})
    mode: EnumProperty(name='Switch to',items=[('IK','IK',''),('FK','FK','')])
    every_frame: BoolProperty(name='Match every frame',default=True,
        description='Match the controls at every frame of the scene range; otherwise at the current frame only')
    @classmethod
    def description(cls,context,properties):
        return f"Match the limb's {properties.mode} controls to its current pose, then switch the limb to {properties.mode}"
    def execute(self,context):
        try:
            rig=control_rig.target(context)
            frames=control_rig.switch(context,rig,self.limb,self.mode,self.every_frame)
            label=control_rig.layout(rig)['limbs'][self.limb]['label']
            self.report({'INFO'},f'{label} switched to {self.mode}, matched over {frames} frame'+('s.' if frames!=1 else '.'))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_fix_frame(Operator):
    bl_idname='sekiro_retarget.fix_frame'
    bl_label='Use current frame'
    bl_description='Set this to the current frame'
    bl_options={'REGISTER','UNDO'}
    end: BoolProperty(options={'HIDDEN'})
    def execute(self,context):
        setattr(context.scene.sekiro_fix,'frame_end' if self.end else 'frame_start',context.scene.frame_current)
        return {'FINISHED'}


class SKR_OT_fix_pose(Operator):
    bl_idname='sekiro_retarget.fix_pose'
    bl_label='Use this pose'
    bl_description='Remember the pose on this frame for the fix, so that you can pose other frames before you apply it'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        fix=context.scene.sekiro_fix
        try:
            rig=control_rig.target(context)
            if not control_rig.present(rig):raise ValueError('Add the control rig first.')
            limb=fix_limb(rig,fix)
            entry=control_rig.layout(rig)['limbs'][limb] if limb is not None else None
            held=fix.held or (fixes.defaults(rig,fix.task,limb)['held'] if limb is not None else '')
            names=fixes.movers(rig,fix.task,entry,held,selected_controls(context))
            if not names:raise ValueError('Select the controls to adjust in Pose Mode, or choose a limb.')
            frame=context.scene.frame_current
            if entry is not None:fixes.check_ik(rig,entry,(frame,frame))
            pose=fixes.capture(context,rig,names)
            if fix.pose_rig!=rig.name:
                fix.poses.clear();fix.pose_rig=rig.name
            for index in reversed(range(len(fix.poses))):
                if fix.poses[index].frame==frame:fix.poses.remove(index)
            for name,(matrix,basis) in pose.items():
                item=fix.poses.add();item.frame=frame;item.bone=name
                item.matrix=[value for row in matrix for value in row];item.basis=[value for row in basis for value in row]
            fix.status=f'Posed frame {retarget.spans(sorted({item.frame for item in fix.poses}))}. Pose another frame, or click Apply fix.'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_fix_clear(Operator):
    bl_idname='sekiro_retarget.fix_clear'
    bl_label='Clear posed frames'
    bl_description='Forget the frames posed with Use this pose'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        fix=context.scene.sekiro_fix
        fix.poses.clear();fix.status=''
        return {'FINISHED'}


class SKR_OT_fix_apply(Operator):
    bl_idname='sekiro_retarget.fix_apply'
    bl_label='Apply fix'
    bl_description='Key the controls so that the fix holds on the chosen frames and eases in and out over the blend'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        fix=context.scene.sekiro_fix
        try:
            rig=control_rig.target(context)
            if not control_rig.present(rig):raise ValueError('Add the control rig first.')
            report=fixes.run(context,rig,fix.task,fix_limb(rig,fix),fix_frames(context,fix),fix_blend(context,fix),
                             fix_posed(rig,fix),fix.target,fix.held,selected_controls(context))
            fix.poses.clear();fix.status=report['message']
            self.report({'WARNING'} if report['warned'] else {'INFO'},fix.status)
            return {'FINISHED'}
        except Exception as exc:
            fix.status=str(exc)
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


ROLES=[('target','Target',''),('source','Source','')]


def figure_rig(context,role):
    rig=getattr(context.scene.sekiro_retarget,role)
    if not rig:raise ValueError(f'Choose the {role} rig first.')
    return rig


class SKR_OT_figure_create(Operator):
    bl_idname='sekiro_retarget.figure_create'
    bl_label='Create figure'
    bl_description=('Place a Biped-style figure on this rig\'s joints, or its saved figure, and open it in Edit Mode so '
                    'that you can move its parts onto the character. The rig shows its Rest Position until the figure '
                    'is saved or closed')
    bl_options={'REGISTER','UNDO'}
    role: EnumProperty(items=ROLES)
    def execute(self,context):
        try:
            rig=figure_rig(context,self.role)
            if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            data=figure.saved(rig) or figure.fit(rig)
            if data is None:raise ValueError(f'{rig.name} has no body to fit a figure to: it needs hips and two legs with knees.')
            obj=figure.build(rig,data)
            for other in context.view_layer.objects:other.select_set(False)
            context.view_layer.objects.active=obj;obj.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')
            context.scene.sekiro_retarget.status=(f'Figure of {rig.name} in Edit Mode, on its rest pose: click a part\'s end and '
                                                  'press G to move it, then Save figure.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_figure_save(Operator):
    bl_idname='sekiro_retarget.figure_save'
    bl_label='Save figure'
    bl_description=('Keep the figure for this rig\'s skeleton, on the rig and in the figure folder, for every clip of '
                    'it, and close it')
    bl_options={'REGISTER','UNDO'}
    role: EnumProperty(items=ROLES)
    def execute(self,context):
        try:
            rig=figure_rig(context,self.role);obj=figure.edited(rig)
            if not obj:raise ValueError('Create the figure first.')
            if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            path=figure.save(rig,obj)
            figure.close(rig)
            context.scene.sekiro_retarget.status=f'Saved the figure of {rig.name} to {path}. {rig.name} shows its pose again.'
            self.report({'INFO'},context.scene.sekiro_retarget.status)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_figure_remove(Operator):
    bl_idname='sekiro_retarget.figure_remove'
    bl_label='Close figure'
    bl_description='Remove the figure from the scene without saving, and show the rig\'s pose again. A saved figure stays saved'
    bl_options={'REGISTER','UNDO'}
    role: EnumProperty(items=ROLES)
    def execute(self,context):
        try:
            figure.close(figure_rig(context,self.role))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_figure_forget(Operator):
    bl_idname='sekiro_retarget.figure_forget'
    bl_label='Delete saved figure'
    bl_description='Delete the figure saved for this rig\'s skeleton, from the rig and from the figure folder'
    bl_options={'REGISTER','UNDO'}
    role: EnumProperty(items=ROLES)
    def invoke(self,context,event):
        return context.window_manager.invoke_confirm(self,event)
    def execute(self,context):
        try:
            rig=figure_rig(context,self.role)
            removed=figure.forget(rig)
            self.report({'INFO'},f'Deleted the saved figure of {rig.name}'+(f' and {removed} file(s).' if removed else '.'))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


REVIEW=.94  # Matches below this strength are listed for review.


def needs_review(row):
    return not row.source or not row.enabled or row.confidence<REVIEW


def pair_blocked(settings):
    """Why bones cannot be matched yet, or ''."""
    if not settings.target:return 'Choose the target first.' if settings.source else 'Choose the target and the source first.'
    if not settings.source:return 'Choose the source, or append it, first.'
    return 'Choose two different armatures.' if settings.source==settings.target else ''


def bake_blocked(settings):
    """Why Bake cannot run now, or ''."""
    if pair_blocked(settings) or (not settings.rows and settings.method!='BODY'):return pair_blocked(settings) or 'Match bones first.'
    if control_rig.present(settings.target):
        return 'The target has a control rig. Remove it under Control rig before baking; you can add it again afterwards.'
    return ''


def bridge_target(settings):
    return bool(settings.target and settings.target.get('sekiro_animation_bridge'))


def wrap(context,message,margin):
    """The words of message in lines that fit the region less margin pixels, measured in the interface font."""
    preferences=bpy.context.preferences;scale=preferences.system.ui_scale or 1
    blf.size(0,preferences.ui_styles[0].widget.points*scale)
    room=context.region.width-margin*scale;lines=[]
    for word in message.split():
        line=lines[-1]+' '+word if lines else word
        if lines and blf.dimensions(0,line)[0]<=room:lines[-1]=line
        else:lines.append(word)
    return lines


def text(layout,context,message,icon='NONE',boxed=False):
    """A message on as many label rows as it needs, the rows after an icon indented to its text; boxed: in a box."""
    column=layout.column(align=True)
    for index,line in enumerate(wrap(context,message,(74 if boxed else 58)+(28 if icon!='NONE' else 0))):
        column.label(text=line,icon=icon if not index else 'BLANK1' if icon!='NONE' else 'NONE')
    return column


def menu(layout,data,name):
    """A menu with its name on the row above, since the sidebar is too narrow for both on one row."""
    column=layout.column(align=True)
    column.label(text=data.bl_rna.properties[name].name);column.prop(data,name,text='')


class SKR_UL_bones(UIList):
    def filter_items(self,context,data,property):
        rows=getattr(data,property);pattern='*'+self.filter_name.lower()+'*'
        flags=[self.bitflag_filter_item if (not data.review_only or needs_review(row)) and
               (fnmatchcase(row.target.lower(),pattern) or fnmatchcase(row.source.lower(),pattern)) else 0 for row in rows]
        return flags,bpy.types.UI_UL_list.sort_items_by_name(rows,'target') if self.use_filter_sort_alpha else []
    def draw_item(self,context,layout,data,item,icon,active_data,active_property,index):
        column=layout.column(align=True)
        row=column.row(align=True)
        row.prop(item,'enabled',text='')
        row.label(text=item.target,icon='BONE_DATA')
        row.label(text=f'{round(item.confidence*100)}%' if item.source else '—',icon='QUESTION' if needs_review(item) else 'CHECKMARK')
        if mapping.weapon_part(item.target) or item.hidden:
            row.prop(item,'hidden',text='',icon='HIDE_ON' if item.hidden else 'HIDE_OFF',emboss=False)
        if data.source:column.prop_search(item,'source',data.source.data,'bones',text='From')
        else:column.label(text='Choose a source rig')


class SKR_PT_panel(Panel):
    bl_label='Sekiro Retarget Assistant'
    bl_idname='SKR_PT_retarget'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Retarget'
    def draw(self,context):
        pass  # The steps are its sub-panels.


class SidebarPanel:
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Retarget';bl_parent_id='SKR_PT_retarget'


class SKR_PT_rigs(SidebarPanel,Panel):
    bl_label='1. Choose rigs'
    bl_idname='SKR_PT_retarget_rigs'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        for role,title in (('target','Target (receives the motion)'),('source','Source (gives the motion)')):
            column=layout.column(align=True);column.label(text=title)
            row=column.row(align=True);row.prop(settings,role,text='')
            row.operator('sekiro_retarget.use_active',text='',icon='RESTRICT_SELECT_OFF').role=role
        layout.operator('sekiro_retarget.append_source',icon='APPEND_BLEND')
        if settings.source and settings.source==settings.target:
            text(layout,context,'Source and target are the same armature. Choose two different ones.',icon='ERROR').alert=True


FIGURE_HELP=('In Edit Mode, click the end of a part and press G to move it: the Head\'s tip to the top of the head, '
             'each Heel to the back of the heel on the ground, each Toe\'s tip to the tip of the foot, and the Thighs\' '
             'heads to the hip joints. Only where the parts start and end counts, not how they turn. Then Save figure.')


class SKR_PT_figures(SidebarPanel,Panel):
    bl_label='Body figures'
    bl_idname='SKR_PT_retarget_figures'
    bl_parent_id='SKR_PT_retarget_rigs';bl_options={'DEFAULT_CLOSED'}
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        text(layout,context,'As with 3ds Max\'s Biped, fit a figure to each character once. The full-body bake then takes '
                            'the body\'s bones, leg length, hip joints, height and feet from it, for every clip of that skeleton.')
        for role,title,unused in ROLES:
            rig=getattr(settings,role)
            if not rig:continue
            box=layout.box();box.label(text=f'{title}: {rig.name}',icon='ARMATURE_DATA')
            kept=figure.saved(rig);obj=figure.edited(rig)
            box.label(text='Saved figure' if kept else 'Automatic figure (none saved)',icon='CHECKMARK' if kept else 'INFO')
            row=box.row(align=True)
            row.operator('sekiro_retarget.figure_create',text='Edit figure' if kept or obj else 'Create figure',icon='EDITMODE_HLT').role=role
            if obj:
                row.operator('sekiro_retarget.figure_save',icon='FILE_TICK').role=role
                row.operator('sekiro_retarget.figure_remove',text='',icon='X').role=role
                text(box,context,FIGURE_HELP)
                bone=context.active_bone if context.object==obj else None
                if bone and figure.LINK in bone:
                    box.prop_search(bone,f'["{figure.LINK}"]',rig.data,'bones',text=bone.name)
                    text(box,context,'The skeleton bone this part stands for.')
            if kept:box.operator('sekiro_retarget.figure_forget',icon='TRASH').role=role
        if settings.target or settings.source:layout.prop(settings,'use_figures')


class SKR_PT_bones(SidebarPanel,Panel):
    bl_label='2. Match bones'
    bl_idname='SKR_PT_retarget_bones'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget;rows=settings.rows;blocked=pair_blocked(settings)
        layout.prop(settings,'tracked_only')
        row=layout.row();row.enabled=not blocked;row.scale_y=1.3
        row.operator('sekiro_retarget.match_bones',text='Match bones again' if rows else 'Match bones automatically',icon='CONSTRAINT_BONE')
        if blocked:
            text(layout,context,blocked,icon='INFO');return
        if rows:
            count=sum(bool(row.enabled and row.source) for row in rows);review=sum(needs_review(row) for row in rows)
            text(layout,context,f'{count} of {len(rows)} bones matched'+(f', {review} to review.' if review else '.'))
            layout.prop(settings,'review_only')
            layout.template_list('SKR_UL_bones','',settings,'rows',settings,'active_row',rows=5)
            if settings.active_row<len(rows):
                item=rows[settings.active_row]
                box=layout.box();text(box,context,item.target+': '+(item.reason or 'Unassigned'),boxed=True)
                if not item.source and item.suggestion:
                    box.label(text='Suggestion: '+item.suggestion)
                    box.operator('sekiro_retarget.accept_suggestion').index=settings.active_row
            if any(not row.source and row.suggestion for row in rows):
                layout.operator('sekiro_retarget.accept_all_suggestions',icon='CHECKMARK')
            row=layout.row(align=True)
            row.operator('sekiro_retarget.mirror_mappings',text='Mirror L → R',icon='MOD_MIRROR').side='L'
            row.operator('sekiro_retarget.mirror_mappings',text='Mirror R → L',icon='MOD_MIRROR').side='R'
        row=layout.row(align=True)
        save=row.row(align=True);save.enabled=bool(rows);save.operator('sekiro_retarget.save_map',text='Save map',icon='FILE_TICK')
        row.operator('sekiro_retarget.load_map',text='Load map',icon='FILE_FOLDER')


class SKR_PT_bake(SidebarPanel,Panel):
    bl_label='3. Bake motion'
    bl_idname='SKR_PT_retarget_bake'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget;blocked=bake_blocked(settings)
        menu(layout,settings,'method')
        if settings.method=='BODY':
            text(layout,context,'Finds the body in both rigs and keeps the feet on the source\'s footprint. '
                 'Bones outside the body, such as weapons, follow the bone list, or automatic matching without one.',
                 icon='ARMATURE_DATA')
        row=layout.row();row.enabled=not blocked;row.scale_y=1.3;row.operator('sekiro_retarget.bake',icon='ACTION')
        if blocked:text(layout,context,blocked,icon='INFO')


class BakeOptions(SidebarPanel):
    bl_parent_id='SKR_PT_retarget_bake';bl_options={'DEFAULT_CLOSED'}


class SKR_PT_bake_pose(BakeOptions,Panel):
    bl_label='Pose and timing'
    bl_idname='SKR_PT_retarget_bake_pose'
    def draw(self,context):
        for name in ('rest_mode','unmapped','timing'):menu(self.layout,context.scene.sekiro_retarget,name)


class SKR_PT_bake_travel(BakeOptions,Panel):
    bl_label='Body travel'
    bl_idname='SKR_PT_retarget_bake_travel'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        layout.prop(settings,'body_translation');layout.prop(settings,'auto_scale')
        if not settings.auto_scale:layout.prop(settings,'travel_scale')
        menu(layout,settings,'root_motion')
        if settings.root_motion in ('AUTO','EXTRACT'):layout.prop(settings,'root_yaw')


class SKR_PT_bake_biped(BakeOptions,Panel):
    bl_label='Feet, jumps and props (Biped)'
    bl_idname='SKR_PT_retarget_bake_biped'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        column=layout.column();column.active=settings.method=='BODY'
        menu(column,settings,'foot_contacts')
        if settings.foot_contacts=='PIVOT':column.prop(settings,'plant_tolerance')
        column.prop(settings,'jump_scale')
        if settings.method!='BODY':text(layout,context,'Foot contacts and jumps work with the full-body bake.',icon='INFO')
        menu(layout,settings,'prop_scale')


class SKR_PT_bake_arms(BakeOptions,Panel):
    bl_label='Arms and hands'
    bl_idname='SKR_PT_retarget_bake_arms'
    def draw(self,context):
        settings=context.scene.sekiro_retarget
        self.layout.prop(settings,'body_clearance');self.layout.prop(settings,'arm_gap')


GRIP_HINTS={
    'REST':'Keeps the weapon at the target\'s own grip point, turned as the source\'s turns from its rest pose.',
    'SOURCE':'Puts the weapon where the source\'s sits in the source\'s hand, scaled to the hand.',
    'OWN':'Holds the weapon as the target\'s own clip does, with that clip\'s fingers.'}


class SKR_PT_bake_weapons(BakeOptions,Panel):
    bl_label='Weapons'
    bl_idname='SKR_PT_retarget_bake_weapons'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        menu(layout,settings,'weapon_grip')
        text(layout,context,GRIP_HINTS[settings.weapon_grip])
        if settings.weapon_grip=='OWN':layout.prop(settings,'blade_follow',slider=True)
        else:layout.prop(settings,'finger_fit')
        layout.prop(settings,'second_hand')


class SKR_PT_bake_grip(SidebarPanel,Panel):
    bl_label='Weapon in hand'
    bl_idname='SKR_PT_retarget_bake_grip'
    bl_parent_id='SKR_PT_retarget_bake';bl_options={'DEFAULT_CLOSED'}
    @classmethod
    def poll(cls,context):
        rig=context.scene.sekiro_retarget.target
        return bool(rig and rig.get(retarget.HELD))
    def draw(self,context):
        layout=self.layout;scene=context.scene;settings=scene.sekiro_retarget
        if not settings.grip_adjusting:layout.prop(settings,'grip_item',text='')
        held=held_weapon(settings)
        if settings.grip_adjusting:
            weapon,hand=settings.grip_adjusting.split('|')
            text(layout,context,f'Frame {settings.grip_frame}: turn (R) or move (G) {weapon} until it sits in {hand} as you '
                                'want, then click Apply to all frames. Stay on this frame.',icon='INFO')
            if scene.frame_current!=settings.grip_frame:
                text(layout,context,f'Go back to frame {settings.grip_frame}.',icon='ERROR').alert=True
            row=layout.row(align=True);row.scale_y=1.3
            row.operator('sekiro_retarget.grip_apply',icon='CHECKMARK');row.operator('sekiro_retarget.grip_cancel',icon='X')
            return
        text(layout,context,'Pose the weapon in the hand on one frame; the bake then keeps it there on every frame.')
        layout.operator('sekiro_retarget.grip_adjust',icon='TOOL_SETTINGS')
        item=grip_offset(settings,held[0]) if held else None
        if item:
            change=retarget.matrix_of(item.matrix)
            moved=change.translation.length*retarget.uniform_scale(settings.target)*100
            row=layout.row(align=True)
            row.label(text=f'Aligned: {moved:.1f} cm, {math.degrees(change.to_quaternion().angle):.1f}°')
            row.operator('sekiro_retarget.grip_reset',icon='LOOP_BACK')


class SKR_PT_export(SidebarPanel,Panel):
    bl_label='4. Export HKX'
    bl_idname='SKR_PT_retarget_export'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        if not bridge_target(settings):
            text(layout,context,'Export needs a target imported by the bridge.',icon='INFO');return
        layout.prop(settings,'export_path');layout.prop(settings,'export_replace')
        layout.prop(settings,'export_binder')
        if settings.export_binder:
            column=layout.column(align=True)
            column.prop(settings,'export_binder_path');column.prop(settings,'export_member')
            clip=(retarget.read_motion(settings.target) or {}).get('clip','')
            if not settings.export_member and clip:column.label(text='Uses '+clip,icon='INFO')
            if not settings.export_binder_path:
                text(layout,context,'This scene does not record the archive its clip came from. Choose the binder.',icon='INFO')
        row=layout.row();row.enabled=bool(settings.export_path) and context.scene.name not in EXPORTING;row.scale_y=1.3
        row.operator('sekiro_retarget.export_hkx',icon='EXPORT')
        if context.scene.name in EXPORTING:text(layout,context,settings.status,icon='SORTTIME')
        if not settings.export_path:text(layout,context,'Choose the Output file first.',icon='INFO')
        layout.operator('sekiro_retarget.set_export_target',icon='FILE_BLEND')


class SKR_PT_export_settings(SidebarPanel,Panel):
    bl_label='Export settings'
    bl_idname='SKR_PT_retarget_export_settings'
    bl_parent_id='SKR_PT_retarget_export';bl_options={'DEFAULT_CLOSED'}
    @classmethod
    def poll(cls,context):
        return bridge_target(context.scene.sekiro_retarget)
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        menu(layout,settings,'export_game');menu(layout,settings,'export_format')
        if settings.export_format=='spline':
            menu(layout,settings,'export_quantization');layout.prop(settings,'export_tolerance')
        for name in ('export_tracks','export_frames','export_root'):menu(layout,settings,name)
        layout.prop(settings,'export_verify')


class LogPanel:
    """The last result of the add-on, closed at first; its header shows whether it warned."""
    bl_label='Log'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_options={'DEFAULT_CLOSED'}
    @classmethod
    def poll(cls,context):
        return bool(context.scene.sekiro_retarget.status)
    def draw_header_preset(self,context):
        alert=context.scene.sekiro_retarget.status_alert
        row=self.layout.row();row.alert=alert
        row.label(text='Warnings' if alert else '',icon='ERROR' if alert else 'INFO')
    def draw(self,context):
        text(self.layout,context,context.scene.sekiro_retarget.status)


class SKR_PT_status(LogPanel,Panel):
    bl_idname='SKR_PT_retarget_status'
    bl_category='Retarget'


ANIMATE='Animate'  # The sidebar tab of the tools that edit an armature's own animation.


class SKR_PT_clip(Panel):
    bl_label='Animation'
    bl_idname='SKR_PT_animate_clip'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category=ANIMATE
    def draw(self,context):
        layout=self.layout;rig=control_rig.target(context)
        if not rig:
            text(layout,context,'Select the armature to animate, such as the target after a bake.',icon='INFO');return
        data=rig.animation_data
        layout.label(text=rig.name,icon='ARMATURE_DATA')
        text(layout,context,data.action.name if data and data.action else 'No action',icon='ACTION')
        layout.operator('sekiro_retarget.mirror_animation',icon='MOD_MIRROR')


class SKR_PT_join(Panel):
    bl_label='Join animations'
    bl_idname='SKR_PT_animate_join'
    bl_parent_id='SKR_PT_animate_clip'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category=ANIMATE
    @classmethod
    def poll(cls,context):
        return control_rig.target(context) is not None
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_join
        text(layout,context,'Plays the armature\'s own animation, then another one, as one clip; the root motion goes on '
                            'from where the first leaves it.')
        column=layout.column(align=True);column.label(text='Then')
        row=column.row(align=True);row.prop(settings,'second',text='')
        row.operator('sekiro_retarget.join_load',text='',icon='FILE_FOLDER')
        layout.prop(settings,'blend')
        row=layout.row();row.scale_y=1.3;row.operator('sekiro_retarget.join_animations',icon='NLA_PUSHDOWN')


class SKR_PT_control_rig(Panel):
    bl_label='Control rig'
    bl_idname='SKR_PT_control_rig'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category=ANIMATE
    def draw(self,context):
        layout=self.layout;rig=control_rig.target(context)
        if not rig:
            text(layout,context,'Select the armature to pose, such as the target after a bake.',icon='INFO');return
        layout.label(text=rig.name,icon='ARMATURE_DATA')
        if not control_rig.present(rig):
            text(layout,context,'Adds controls to pose the arms and legs, in FK or with IK that keeps hands and feet in '
                                'place. The game bones follow the controls, so export works as before.')
            row=layout.row();row.scale_y=1.3;row.operator('sekiro_retarget.add_control_rig',icon='ADD');return
        data=control_rig.layout(rig)
        if rig.mode!='POSE':
            if context.object==rig:
                text(layout,context,'The controls are posed in Pose Mode.',icon='INFO')
                layout.operator('object.mode_set',text='Pose Mode',icon='POSE_HLT').mode='POSE'
            else:text(layout,context,'Select the armature to pose its controls in Pose Mode.',icon='INFO')
        if data['limbs']:text(layout,context,'IK slider: 0 follows FK, 1 follows IK.')
        for index,limb in enumerate(data['limbs']):
            bone=rig.pose.bones.get(limb['control'])
            if not bone:continue
            layout.separator()
            column=layout.column(align=True)
            column.prop(bone,f'["{control_rig.SWITCH}"]',text=limb['label']+' IK',slider=True)
            swivel=rig.pose.bones.get(limb.get('swivel',''))
            if swivel:
                row=column.row(align=True);row.active=bone.get(control_rig.SWITCH,0.0)>0
                row.prop(swivel,'rotation_euler',index=1,text=('Elbow' if limb['kind']=='arm' else 'Knee')+' swivel')
            row=column.row(align=True)
            for mode in ('IK','FK'):
                operator=row.operator('sekiro_retarget.control_rig_switch',text='Switch to '+mode);operator.limb=index;operator.mode=mode
        if not data['limbs']:text(layout,context,'No arms or legs were recognised for IK.',icon='INFO')
        layout.label(text='Show')
        grid=layout.grid_flow(columns=2,align=True)
        for (title,visible),name in zip(control_rig.COLLECTIONS,data['collections']):
            collection=rig.data.collections.get(name)
            if collection and title!='MCH':grid.prop(collection,'is_visible',text=title,toggle=True)
        layout.operator('sekiro_retarget.remove_control_rig',icon='X')


class SKR_PT_fixes(Panel):
    bl_label='Fixes'
    bl_idname='SKR_PT_control_rig_fixes'
    bl_parent_id='SKR_PT_control_rig'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category=ANIMATE
    @classmethod
    def poll(cls,context):
        return control_rig.present(control_rig.target(context))
    def draw(self,context):
        layout=self.layout;scene=context.scene;fix=scene.sekiro_fix;rig=control_rig.target(context)
        layout.prop(fix,'task',text='')
        text(layout,context,fixes.HINTS[fix.task])
        if fix.task=='ADJUST' and scene.tool_settings.use_keyframe_insert_auto:
            text(layout,context,'Auto keying is on. Turn it off before you pose: Adjust compares your pose with the '
                                'animation.',icon='ERROR').alert=True
        layout.prop(fix,'limb')
        limb=fix_limb(rig,fix)
        if limb is not None:
            entry=control_rig.layout(rig)['limbs'][limb];bone=rig.pose.bones.get(entry['control'])
            if bone and bone.get(control_rig.SWITCH,0.0)<.999:
                text(layout,context,entry['label']+' is not in IK on this frame. The fix moves its IK controls, so switch '
                                    'it to IK first.',icon='ERROR').alert=True
                operator=layout.operator('sekiro_retarget.control_rig_switch',text='Switch to IK');operator.limb=limb;operator.mode='IK'
            if fix.task in ('HAND','SHEATH'):
                values=fixes.defaults(rig,fix.task,limb)
                fields=[('target','Follow' if fix.task=='HAND' else 'Sheath')]+([('held','Weapon')] if fix.task=='SHEATH' else [])
                for name,title in fields:
                    column=layout.column(align=True);column.prop_search(fix,name,rig.data,'bones',text=title)
                    if values[name] and not getattr(fix,name):column.label(text='Uses '+values[name],icon='INFO')
        layout.row().prop(fix,'span',expand=True)
        if fix.span=='RANGE':
            row=layout.row(align=True)
            row.prop(fix,'frame_start');row.operator('sekiro_retarget.fix_frame',text='',icon='TIME').end=False
            row.prop(fix,'frame_end');row.operator('sekiro_retarget.fix_frame',text='',icon='TIME').end=True
        row=layout.row();row.prop(fix,'blend');row.label(text=f'{fix_blend(context,fix)} frames')
        posed=sorted({item.frame for item in fix.poses}) if fix.pose_rig==rig.name else []
        row=layout.row(align=True);row.operator('sekiro_retarget.fix_pose',icon='POSE_HLT')
        if posed:
            row.operator('sekiro_retarget.fix_clear',text='',icon='X')
            layout.label(text='Posed frames: '+retarget.spans(posed))
        row=layout.row();row.scale_y=1.3;row.operator('sekiro_retarget.fix_apply',icon='CHECKMARK')
        if fix.status:text(layout.box(),context,fix.status,boxed=True)


class SKR_PT_animate_log(LogPanel,Panel):
    bl_idname='SKR_PT_animate_log'
    bl_category=ANIMATE


CLASSES=(SKR_Preferences,SKR_BoneMap,SKR_GripOffset,SKR_Settings,SKR_FixPose,SKR_Fix,SKR_Join,SKR_OT_match,SKR_OT_use_active,
    SKR_OT_append,SKR_OT_suggestion,SKR_OT_accept_all,SKR_OT_mirror,SKR_OT_bake,SKR_OT_export_target,SKR_OT_export_hkx,
    SKR_OT_grip_adjust,SKR_OT_grip_apply,SKR_OT_grip_cancel,SKR_OT_grip_reset,SKR_OT_save_map,
    SKR_OT_load_map,SKR_OT_add_control_rig,SKR_OT_remove_control_rig,SKR_OT_mirror_animation,SKR_OT_join_load,SKR_OT_join,
    SKR_OT_control_rig_switch,SKR_OT_fix_frame,
    SKR_OT_fix_pose,SKR_OT_fix_clear,SKR_OT_fix_apply,SKR_OT_figure_create,SKR_OT_figure_save,SKR_OT_figure_remove,
    SKR_OT_figure_forget,SKR_UL_bones,SKR_PT_panel)
# The Animate tab's panels, in the order they are shown.
CLASSES+=(SKR_PT_clip,SKR_PT_join,SKR_PT_control_rig,SKR_PT_fixes,SKR_PT_animate_log)
# The steps of the retarget panel, after it and in the order they are shown.
CLASSES+=(SKR_PT_rigs,SKR_PT_figures,SKR_PT_bones,SKR_PT_bake,SKR_PT_bake_pose,SKR_PT_bake_travel,SKR_PT_bake_biped,
          SKR_PT_bake_arms,SKR_PT_bake_weapons,SKR_PT_bake_grip,
          SKR_PT_export,SKR_PT_export_settings,SKR_PT_status)


def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.sekiro_retarget=PointerProperty(type=SKR_Settings)
    bpy.types.Scene.sekiro_fix=PointerProperty(type=SKR_Fix)
    bpy.types.Scene.sekiro_join=PointerProperty(type=SKR_Join)
    from . import imported_pair
    imported_pair.register()


def unregister():
    from . import imported_pair
    imported_pair.unregister()
    del bpy.types.Scene.sekiro_join
    del bpy.types.Scene.sekiro_fix
    del bpy.types.Scene.sekiro_retarget
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
