bl_info = {
    'name': 'Sekiro Retarget Assistant', 'author': 'Animation Bridge',
    'version': (0, 3, 0), 'blender': (4, 5, 0),
    'location': '3D View > Sidebar > Retarget', 'category': 'Animation',
    'description': 'Append bridge rigs, match bones, review mappings, bake retargeted motion, add a control rig and export HKX',
}

import json
import textwrap
from collections import Counter
from pathlib import Path
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList
from bpy_extras.io_utils import ImportHelper, ExportHelper
from . import control_rig, export, mapping, retarget


def armature_poll(self, obj):
    return obj.type == 'ARMATURE'


def pair_changed(self, context):
    self.rows.clear()
    self.status = 'Choose the rig pair, then Match bones.'


def source_changed(self, context):
    self.enabled = bool(self.source)
    self.confidence = 1.0 if self.source else 0
    self.reason = 'Manual mapping' if self.source else 'Unassigned'


def preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


class SKR_Preferences(AddonPreferences):
    bl_idname = __package__
    bridge_folder: StringProperty(name='Animation Bridge folder', subtype='DIR_PATH',
        description='Folder of the Animation Bridge (or its standalone folder). Empty: the installation that ran last')
    writer: StringProperty(name='Conversion Python', subtype='FILE_PATH',
        description='Python with the conversion libraries. Empty: the one chosen in the bridge settings')
    def draw(self,context):
        layout=self.layout
        layout.prop(self,'bridge_folder');layout.prop(self,'writer')
        folder=export.bridge_folder(self);writer=export.writer_python(self)
        layout.label(text='Bridge: '+(str(folder) if folder else 'not found; start the bridge UI once or set the folder'),
                     icon='CHECKMARK' if folder else 'ERROR')
        layout.label(text='Conversion Python: '+str(writer),icon='CHECKMARK' if writer.is_file() else 'ERROR')


class SKR_BoneMap(PropertyGroup):
    target: StringProperty(name='Target bone')
    source: StringProperty(name='Source bone', update=source_changed)
    enabled: BoolProperty(name='Use mapping', default=True)
    confidence: FloatProperty(name='Match strength', min=0, max=1)
    reason: StringProperty()
    suggestion: StringProperty()


class SKR_Settings(PropertyGroup):
    source: PointerProperty(name='Source rig', type=bpy.types.Object, poll=armature_poll, update=pair_changed)
    target: PointerProperty(name='Target rig', type=bpy.types.Object, poll=armature_poll, update=pair_changed)
    rows: CollectionProperty(type=SKR_BoneMap)
    active_row: IntProperty()
    review_only: BoolProperty(name='Show unmatched / uncertain only', default=False)
    tracked_only: BoolProperty(name='HKX animation bones only', default=True,
        description='For bridge rigs, map original HKX tracks; extra model bones follow their parents')
    rest_mode: EnumProperty(name='Rest stance', items=[
        ('ALIGN','Match source stance','Pose the target limbs like the source rest pose before applying motion, '
                 'so an A-pose target follows a T-pose source without lowered or raised arms'),
        ('REST','Keep target stance','Apply source rotations from the target rest pose; for rigs that share a rest stance')], default='ALIGN')
    root_motion: EnumProperty(name='Root motion', items=[
        ('AUTO','Automatic','The source root motion when the source has it; otherwise body travel becomes root motion '
                'when the body moves far, and none when it stays in place'),
        ('SOURCE','From source root','Copy the source HKX_RootMotion object, scaled to the target'),
        ('EXTRACT','From body travel','Ground travel of the body becomes root motion; the body stays over the root'),
        ('TARGET','Keep target root','Keep the target clip\'s original root motion (same length only)'),
        ('NONE','None','Hold the root still; the body travels inside the animation')], default='AUTO')
    root_yaw: BoolProperty(name='Turn root with the body', default=False,
        description='When body travel becomes root motion, the root also follows the body\'s heading')
    unmapped: EnumProperty(name='Unmapped bones', items=[
        ('KEEP','Keep target animation','Unmapped bones, such as cloth, face or weapon bones, keep the target clip\'s animation'),
        ('REST','Rest pose','Unmapped bones hold their rest pose; for bridge rigs, the HKX reference pose')], default='KEEP')
    auto_scale: BoolProperty(name='Scale travel by leg length', default=True,
        description='Scale body travel and root motion by the ratio of hip heights; bone lengths remain the target\'s')
    travel_scale: FloatProperty(name='Travel scale',default=1.0,min=.01,max=20.0)
    body_translation: BoolProperty(name='Move body with source hips', default=True,
        description='The bone above the target hips and spine follows the source hips, so legs and upper body move together')
    timing: EnumProperty(name='Clip timing', items=[
        ('SOURCE','Use source length','Update target metadata to the source duration'),
        ('TARGET','Fit target length','Resample source motion across the target clip length')], default='SOURCE')
    export_path: StringProperty(name='Output', subtype='FILE_PATH', description='HKX file to write; a .motion.json sidecar is written beside it')
    export_format: EnumProperty(name='Format', items=[
        ('interleaved','Interleaved','Every frame stored exactly; larger files'),
        ('spline','Spline','Compressed like the game\'s own clips; small differences within the tolerance')], default='interleaved')
    export_quantization: EnumProperty(name='Rotations', items=[
        ('threecomp40','40-bit','Default'),('threecomp48','48-bit','Finer'),('uncompressed','Full floats','Largest')], default='threecomp40')
    export_tolerance: FloatProperty(name='Tolerance', default=.001, min=1e-6, max=.1, precision=4,
        description='Largest position change, in metres, that spline compression may introduce')
    export_tracks: EnumProperty(name='Tracks', items=[
        ('original','Original clip tracks','Keep the track list of the clip the target was imported from; other bones stay under the game\'s control'),
        ('keyed','Original tracks + keyed bones','Also write tracks for bones keyed in the action'),
        ('all','Every skeleton bone','Write a track for each bone')], default='original')
    export_frames: EnumProperty(name='Frames', items=[
        ('scene','Scene range','The scene start and end frames (set by Bake)'),
        ('action','Action range','The keyframe range of the action'),
        ('clip','Clip length','Frames 1 to the clip\'s frame count')], default='scene')
    export_game: EnumProperty(name='Game', items=[
        ('auto','Stored in scene','The game recorded when the clip was imported (bridge 0.5 and later)'),
        ('sekiro','Sekiro',''),('ds1','Dark Souls: Prepare to Die',''),('ds1r','Dark Souls Remastered',''),
        ('ds3','Dark Souls III',''),('er','Elden Ring','')], default='auto',
        description='Game of the target clip; choose it for scenes imported before the bridge recorded it')
    export_root: EnumProperty(name='Root motion', items=[
        ('AUTO','As baked','The target\'s HKX_RootMotion object, when it has one'),
        ('NONE','None','Write no root motion')], default='AUTO')
    export_verify: BoolProperty(name='Read back and compare', default=True,
        description='Decode the written HKX again and report the largest difference')
    export_replace: BoolProperty(name='Replace existing', default=False)
    status: StringProperty(default='Open the receiving character first, then append a source.')


def build_mapping(settings):
    if not settings.source or not settings.target or settings.source == settings.target:
        raise ValueError('Choose two different armatures.')
    def infos(rig):
        return retarget.rig_bones(rig,retarget.bone_infos(rig,settings.tracked_only))
    rows = mapping.match_bones(infos(settings.source),infos(settings.target))
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
    bl_description='Match by name, anatomical role and rest position, respecting left/right and avoiding duplicate source assignments'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            build_mapping(context.scene.sekiro_retarget)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_use_active(Operator):
    bl_idname='sekiro_retarget.use_active'
    bl_label='Use active armature'
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
    bl_description='Create a new target action from the reviewed map; the original action is kept'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        try:
            result=retarget.bake(context.scene,settings)
            settings.status=(f"Baked {result['frames']} frames from {result['mapped']} mapped bones; travel scale {result['scale']:.3f}; "
                             f"root motion {result['root_motion'].lower()}."+''.join(' '+warning for warning in result['warnings']))
            if not settings.export_path and bpy.data.filepath:
                clip=(retarget.read_motion(settings.target) or {}).get('clip','')
                if clip:settings.export_path='//'+Path(clip).stem+'.hkx'
            self.report({'WARNING'} if result['warnings'] else {'INFO'},settings.status)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


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


class SKR_OT_export_hkx(Operator):
    bl_idname='sekiro_retarget.export_hkx'
    bl_label='Export HKX'
    bl_description='Sample the target action and write HKX with the Animation Bridge, as its export page does. Esc cancels'
    _timer=None
    def execute(self,context):
        settings=context.scene.sekiro_retarget
        try:
            self.job=export.start(context,settings,preferences(context))
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        settings.status='Writing HKX...'
        self._timer=context.window_manager.event_timer_add(.25,window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def modal(self,context,event):
        settings=context.scene.sekiro_retarget
        if event.type=='ESC':self.job.cancel()
        if event.type!='TIMER':return {'PASS_THROUGH'}
        if not self.job.done:
            settings.status=f'{self.job.message} ({self.job.progress}%)'
        else:
            context.window_manager.event_timer_remove(self._timer)
            settings.status=export.summary(self.job)
        for area in context.screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()
        if not self.job.done:return {'PASS_THROUGH'}
        self.report({'ERROR'} if self.job.failed else {'INFO'},settings.status)
        return {'CANCELLED'} if self.job.failed else {'FINISHED'}


class SKR_OT_save_map(Operator,ExportHelper):
    bl_idname='sekiro_retarget.save_map'
    bl_label='Save bone map'
    filename_ext='.json'
    filter_glob: StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            rows=context.scene.sekiro_retarget.rows
            document=dict(format='sekiro-retarget-map',version=1,mappings=[dict(target=r.target,source=r.source,enabled=r.enabled) for r in rows])
            Path(self.filepath).write_text(json.dumps(document,indent=2),encoding='utf-8')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class SKR_OT_load_map(Operator,ImportHelper):
    bl_idname='sekiro_retarget.load_map'
    bl_label='Load bone map'
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


class SKR_UL_bones(UIList):
    def filter_items(self,context,data,property):
        rows=getattr(data,property)
        return [self.bitflag_filter_item if not data.review_only or not row.source or not row.enabled or row.confidence<.94 else 0 for row in rows],[]
    def draw_item(self,context,layout,data,item,icon,active_data,active_property,index):
        column=layout.column(align=True)
        row=column.row(align=True)
        row.prop(item,'enabled',text='')
        row.label(text=item.target,icon='BONE_DATA')
        row.label(text=f'{round(item.confidence*100)}%' if item.source else '—',icon='CHECKMARK' if item.source else 'QUESTION')
        if data.source:column.prop_search(item,'source',data.source.data,'bones',text='From')
        else:column.label(text='Select source')


class SKR_PT_panel(Panel):
    bl_label='Sekiro Retarget Assistant'
    bl_idname='SKR_PT_retarget'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Retarget'
    def draw(self,context):
        layout=self.layout;settings=context.scene.sekiro_retarget
        layout.label(text='1. Source → receiving character',icon='ARMATURE_DATA')
        for role in ('source','target'):
            layout.label(text='Source (animated)' if role=='source' else 'Target (receiving)')
            row=layout.row(align=True);row.prop(settings,role,text='')
            operator=row.operator('sekiro_retarget.use_active',text='',icon='EYEDROPPER');operator.role=role
        layout.operator('sekiro_retarget.append_source',icon='APPEND_BLEND')
        layout.separator();layout.label(text='2. Match and review',icon='BONE_DATA')
        layout.prop(settings,'tracked_only')
        row=layout.row();row.enabled=bool(settings.source and settings.target and settings.source!=settings.target)
        row.operator('sekiro_retarget.match_bones',icon='CONSTRAINT_BONE')
        if settings.rows:
            count=sum(bool(r.enabled and r.source) for r in settings.rows)
            layout.label(text=f'{count} / {len(settings.rows)} target bones assigned')
            layout.prop(settings,'review_only')
            layout.template_list('SKR_UL_bones','',settings,'rows',settings,'active_row',rows=5)
            if settings.active_row<len(settings.rows):
                item=settings.rows[settings.active_row]
                box=layout.box();box.label(text=item.reason or 'Unassigned')
                if not item.source and item.suggestion:
                    box.label(text='Suggestion: '+item.suggestion)
                    box.operator('sekiro_retarget.accept_suggestion').index=settings.active_row
            if any(not r.source and r.suggestion for r in settings.rows):
                layout.operator('sekiro_retarget.accept_all_suggestions',icon='CHECKMARK')
            row=layout.row(align=True)
            row.operator('sekiro_retarget.mirror_mappings',text='Mirror L → R',icon='MOD_MIRROR').side='L'
            row.operator('sekiro_retarget.mirror_mappings',text='Mirror R → L').side='R'
            row=layout.row(align=True);row.operator('sekiro_retarget.save_map',text='Save map');row.operator('sekiro_retarget.load_map',text='Load map')
        layout.separator();layout.label(text='3. Bake a new action',icon='ACTION')
        layout.prop(settings,'rest_mode');layout.prop(settings,'root_motion')
        if settings.root_motion in ('AUTO','EXTRACT'):layout.prop(settings,'root_yaw')
        layout.prop(settings,'unmapped');layout.prop(settings,'timing')
        layout.prop(settings,'body_translation');layout.prop(settings,'auto_scale')
        if not settings.auto_scale:layout.prop(settings,'travel_scale')
        row=layout.row();row.enabled=bool(settings.rows)
        row.operator('sekiro_retarget.bake',icon='ACTION')
        layout.separator();layout.label(text='4. Export HKX',icon='EXPORT')
        if settings.target and settings.target.get('sekiro_animation_bridge'):
            layout.prop(settings,'export_path')
            layout.prop(settings,'export_game');layout.prop(settings,'export_format')
            if settings.export_format=='spline':
                row=layout.row(align=True);row.prop(settings,'export_quantization',text='');row.prop(settings,'export_tolerance')
            layout.prop(settings,'export_tracks');layout.prop(settings,'export_frames');layout.prop(settings,'export_root')
            row=layout.row();row.prop(settings,'export_verify');row.prop(settings,'export_replace')
            row=layout.row();row.enabled=bool(settings.export_path)
            row.operator('sekiro_retarget.export_hkx',icon='EXPORT')
            layout.operator('sekiro_retarget.set_export_target',icon='FILE_BLEND')
        else:
            layout.label(text='Export needs a target imported by the bridge.',icon='INFO')
        box=layout.box()
        for line in textwrap.wrap(settings.status,width=max(28,int(context.region.width/7))):box.label(text=line)


class SKR_PT_control_rig(Panel):
    bl_label='Control rig'
    bl_idname='SKR_PT_control_rig'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Retarget'
    def draw(self,context):
        layout=self.layout;rig=control_rig.target(context)
        if not rig:
            layout.label(text='Select an armature.',icon='INFO');return
        layout.label(text=rig.name,icon='ARMATURE_DATA')
        if not control_rig.present(rig):
            layout.operator('sekiro_retarget.add_control_rig',icon='BONE_DATA');return
        data=control_rig.layout(rig)
        for index,limb in enumerate(data['limbs']):
            bone=rig.pose.bones.get(limb['control'])
            if not bone:continue
            column=layout.column(align=True)
            column.prop(bone,f'["{control_rig.SWITCH}"]',text=limb['label']+' IK',slider=True)
            row=column.row(align=True)
            for mode in ('IK','FK'):
                operator=row.operator('sekiro_retarget.control_rig_switch',text='Switch to '+mode);operator.limb=index;operator.mode=mode
        if not data['limbs']:layout.label(text='No arms or legs were recognised for IK.',icon='INFO')
        layout.label(text='Show')
        grid=layout.grid_flow(columns=2,align=True)
        for (title,visible),name in zip(control_rig.COLLECTIONS,data['collections']):
            collection=rig.data.collections.get(name)
            if collection and title!='MCH':grid.prop(collection,'is_visible',text=title,toggle=True)
        layout.operator('sekiro_retarget.remove_control_rig',icon='X')


CLASSES=(SKR_Preferences,SKR_BoneMap,SKR_Settings,SKR_OT_match,SKR_OT_use_active,SKR_OT_append,SKR_OT_suggestion,
    SKR_OT_accept_all,SKR_OT_mirror,SKR_OT_bake,SKR_OT_export_target,SKR_OT_export_hkx,SKR_OT_save_map,SKR_OT_load_map,
    SKR_OT_add_control_rig,SKR_OT_remove_control_rig,SKR_OT_control_rig_switch,SKR_UL_bones,SKR_PT_panel,SKR_PT_control_rig)


def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.sekiro_retarget=PointerProperty(type=SKR_Settings)


def unregister():
    del bpy.types.Scene.sekiro_retarget
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
