"""Panels of the retarget add-on in each of their main states, on owned synthetic bridge rigs. Run with
Blender --background --factory-startup --python this_file.py [-- output folder].

Background Blender draws no interface, so each panel's draw() runs against a
stand-in layout that checks every call against the real UILayout: the function
and its arguments, icons, layout attributes, the properties of the data, enum
values, operators and the properties set on their buttons, and UI lists with
their rows. Any draw error fails the check. The stand-in also writes each
panel as rows of text; an output folder after -- receives them as panels.txt.

The states: nothing chosen; a rig imported by the bridge; source and target
chosen; bones matched; after a bake; every conditional option shown; the
control rig on the target; fixes in progress: a posed frame, a limb in FK,
auto keying on for Adjust over frames, and the status after Apply fix; and the
control rig in Object Mode, as after opening the file again. Each state must
show its expected rows, and no label may be wider than the sidebar gives it.
"""
import math
import sys
from pathlib import Path
from types import SimpleNamespace
import blf
import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'blender_addon'))
import humanoids
from blender_bridge import import_motion
import sekiro_retarget
from sekiro_retarget import control_rig

COUNT, RATE = 24, 30
# The sidebar's width in Blender 4.5 at factory settings and a resolution scale of 1, measured in a window.
WIDTH = 280
# Room for a label's text in a sub-panel: the sidebar less this margin, 16 less in a box and 28 less with an icon,
# measured likewise; a sub-panel gives its rows a few pixels less than a top-level panel.
MARGIN = 58
UI = bpy.types.UILayout.bl_rna
# The motion of both clips: bones turning about the game's X axis, by these angles at their peak.
ANIMATED = {'Spine': .2, 'L_UpperArm': .8, 'R_UpperArm': -.6, 'L_Forearm': .5, 'R_Forearm': .4,
            'L_Thigh': .7, 'R_Thigh': -.7, 'L_Calf': -.6, 'R_Calf': -.5, 'Master': .2, 'R_Weapon': .3}


def arguments(name, args, kwargs):
    """The arguments of a call to UILayout.<name> by parameter, checked against the function's RNA definition."""
    function = UI.functions.get(name)
    assert function is not None, f'UILayout has no function {name}()'
    parameters = [p for p in function.parameters if not p.is_output]
    names = [p.identifier for p in parameters]
    assert len(args) <= len(names), f'{name}() takes {len(names)} arguments, got {len(args)}'
    given = dict(zip(names, args))
    for key, value in kwargs.items():
        assert key in names, f'{name}() has no argument {key!r}'
        assert key not in given, f'{name}() got {key!r} twice'
        given[key] = value
    for parameter in parameters:
        if parameter.is_required:
            assert parameter.identifier in given, f'{name}() needs {parameter.identifier!r}'
        if parameter.identifier in given:
            check(f'{name}({parameter.identifier}=)', parameter, given[parameter.identifier])
    return given


def check(where, rna, value):
    """A value fits an RNA property or parameter: its type, its enum items, Blender data for a pointer."""
    if rna.type == 'STRING':
        assert isinstance(value, str), f'{where} needs text, got {value!r}'
    elif rna.type in ('BOOLEAN', 'INT'):
        assert isinstance(value, int), f'{where} needs a whole number or bool, got {value!r}'
    elif rna.type == 'FLOAT':
        assert isinstance(value, (int, float)), f'{where} needs a number, got {value!r}'
    elif rna.type == 'ENUM':
        items = rna.enum_items.keys()
        values = value if rna.is_enum_flag else {value}
        assert not items or all(item in items for item in values), f'{where}: {value!r} is not an item'
    elif rna.type == 'POINTER':
        assert isinstance(value, bpy.types.bpy_struct), f'{where} needs Blender data, got {value!r}'


def number(rna, value):
    if rna is None or rna.type == 'INT':
        return f'{value:.3g}' if isinstance(value, float) else str(value)
    if rna.unit == 'TIME_ABSOLUTE':
        return f'{value:g} s'
    if rna.unit == 'ROTATION':
        return f'{math.degrees(value):.0f}°'
    if rna.subtype == 'PERCENTAGE':
        return f'{value:.0f}%'
    return f'{value:.4g}'


def shown(data, name, given):
    """A property field as text: [x] for a checkbox, [value v] for a menu, *item* for the chosen expanded item."""
    if name.startswith('["'):
        rna, label, value = None, name[2:-2], data[name[2:-2]]
    else:
        rna = data.bl_rna.properties[name]
        label, value = rna.name, getattr(data, name)
    label = given.get('text', label)
    if given.get('index', -1) >= 0:
        value = value[given['index']]
    if rna is not None and rna.type == 'BOOLEAN':
        if given.get('toggle', -1) > 0 or given.get('icon_only'):
            return f'[{label}{" (on)" if value else ""}]'
        return ('[x] ' if value else '[ ] ') + label
    if rna is not None and rna.type == 'ENUM':
        if given.get('expand'):
            return ' | '.join(f'*{item.name}*' if item.identifier == value else item.name for item in rna.enum_items)
        value = bpy.types.UILayout.enum_item_name(data, name, value) or value
        return f'{label}: [{value} v]' if label else f'[{value} v]'
    if rna is not None and rna.type == 'POINTER':
        value = value.name if value else '-'
    elif rna is None or rna.type in ('INT', 'FLOAT'):
        value = number(rna, value) + (' slider' if given.get('slider') else '')
    return f'{label}: [{value}]' if label else f'[{value}]'


class Text(str):
    """A label's text, with its icon."""
    icon = 'NONE'


class Button:
    """Stands in for the properties of an operator button: only the operator's own properties, with fitting values."""
    def __init__(self, rna):
        object.__setattr__(self, 'rna', rna)

    def __setattr__(self, name, value):
        prop = self.rna.properties.get(name)
        assert prop is not None and name != 'rna_type', f'{self.rna.identifier} has no property {name!r}'
        check(f'{self.rna.identifier}.{name}', prop, value)


class Layout:
    """Stands in for a UILayout: checks each call against the real one and records what it draws."""
    def __init__(self, kind='column', columns=0):
        object.__setattr__(self, 'kind', kind)
        object.__setattr__(self, 'columns', columns)
        object.__setattr__(self, 'items', [])
        object.__setattr__(self, 'state', {})

    def __setattr__(self, name, value):
        rna = UI.properties.get(name)
        assert rna is not None and not rna.is_readonly, f'UILayout has no attribute {name!r} to set'
        check(f'layout.{name}', rna, value)
        self.state[name] = value

    def __getattr__(self, name):
        if name in UI.properties:
            return self.state.get(name, UI.properties[name].default)
        raise AttributeError(f'UILayout has no {name}' if name not in UI.functions else
                             f'the stand-in layout does not draw {name}() yet; add it to blender_panels.py')

    def _child(self, name, args, kwargs, kind):
        given = arguments(name, args, kwargs)
        child = Layout(kind, given.get('columns', 0))
        self.items.append(child)
        return child

    def row(self, *args, **kwargs):
        return self._child('row', args, kwargs, 'row')

    def column(self, *args, **kwargs):
        return self._child('column', args, kwargs, 'column')

    def column_flow(self, *args, **kwargs):
        return self._child('column_flow', args, kwargs, 'column')

    def box(self, *args, **kwargs):
        return self._child('box', args, kwargs, 'box')

    def split(self, *args, **kwargs):
        return self._child('split', args, kwargs, 'row')

    def grid_flow(self, *args, **kwargs):
        return self._child('grid_flow', args, kwargs, 'grid')

    def panel(self, *args, **kwargs):
        given = arguments('panel', args, kwargs)
        header, body = Layout('row'), Layout('column')
        self.items.append(('panel', header, body))
        return header, body

    def separator(self, *args, **kwargs):
        arguments('separator', args, kwargs)

    def label(self, *args, **kwargs):
        given = arguments('label', args, kwargs)
        assert '\n' not in given.get('text', ''), 'a label shows one line'
        text = Text(given.get('text', ''))
        text.icon = given.get('icon', 'NONE')
        self.items.append(text)

    def prop(self, *args, **kwargs):
        given = arguments('prop', args, kwargs)
        data, name = given['data'], given['property']
        if name.startswith('["') and name.endswith('"]'):
            assert name[2:-2] in data.keys(), f'{data!r} has no custom property {name}'
        else:
            assert name in data.bl_rna.properties, f'{data.bl_rna.identifier} has no property {name!r}'
            rna = data.bl_rna.properties[name]
            length = getattr(rna, 'array_length', 0)
            assert given.get('index', -1) < length or given.get('index', -1) < 0, ('no such index', name)
            assert not given.get('expand') or rna.type == 'ENUM' or length, ('only menus and arrays expand', name)
            assert not given.get('slider') or rna.type in ('INT', 'FLOAT'), ('only numbers slide', name)
        self.items.append(shown(data, name, given))

    def prop_search(self, *args, **kwargs):
        given = arguments('prop_search', args, kwargs)
        data, name, search, collection = (given[key] for key in ('data', 'property', 'search_data', 'search_property'))
        assert name in data.bl_rna.properties and data.bl_rna.properties[name].type in ('STRING', 'POINTER'), name
        assert search.bl_rna.properties.get(collection) and search.bl_rna.properties[collection].type == 'COLLECTION', collection
        self.items.append(shown(data, name, given) + ' (search)')

    def prop_enum(self, *args, **kwargs):
        given = arguments('prop_enum', args, kwargs)
        rna = given['data'].bl_rna.properties[given['property']]
        assert rna.type == 'ENUM' and (not rna.enum_items or given['value'] in rna.enum_items.keys()), given['value']
        self.items.append(f"<{given.get('text', given['value'])}>")

    def operator(self, *args, **kwargs):
        given = arguments('operator', args, kwargs)
        group, _, name = given['operator'].partition('.')
        try:
            rna = getattr(getattr(bpy.ops, group), name).get_rna_type()
        except (AttributeError, KeyError):
            raise AssertionError(f'no operator {given["operator"]}') from None
        text = given.get('text', rna.name)
        self.items.append(f'({text})' if text else f"({given.get('icon', 'NONE').lower()})")
        return Button(rna)

    def template_list(self, *args, **kwargs):
        given = arguments('template_list', args, kwargs)
        cls = getattr(bpy.types, given['listtype_name'], None)
        assert isinstance(cls, type) and issubclass(cls, bpy.types.UIList), given['listtype_name']
        data, name = given['dataptr'], given['propname']
        assert data.bl_rna.properties[name].type == 'COLLECTION', name
        assert given['active_dataptr'].bl_rna.properties[given['active_propname']].type == 'INT', given['active_propname']
        rows = getattr(data, name)
        # UIList.bitflag_filter_item, Blender's reserved bit for a row that the filter shows.
        helper = SimpleNamespace(bitflag_filter_item=1 << 30, filter_name='',
                                 use_filter_invert=False, use_filter_sort_alpha=False, use_filter_sort_reverse=False,
                                 layout_type='DEFAULT')
        flags, order = cls.filter_items(helper, bpy.context, data, name) if hasattr(cls, 'filter_items') else ([], [])
        visible = [i for i in range(len(rows)) if not flags or flags[i] & helper.bitflag_filter_item]
        lines = Layout('column')
        for index in visible:
            item = Layout('column')
            cls.draw_item(helper, bpy.context, item, data, rows[index], 0, given['active_dataptr'],
                          given['active_propname'], index)
            if len(lines.items) < 3:
                lines.items.append(item)
        self.items.append(f'{{list: {len(visible)} of {len(rows)} rows, {given.get("rows", 5)} at a time}}')
        self.items.append(('list', lines))


def cut(node, room):
    """The labels of columns and boxes that get too little room, so that Blender would cut them with an ellipsis."""
    found = []
    for item in node.items:
        if isinstance(item, Text) and item:
            if blf.dimensions(0, item)[0] + (28 if item.icon != 'NONE' else 0) > room:
                found.append(str(item))
        elif isinstance(item, Layout) and item.kind in ('column', 'box'):
            found += cut(item, room - (16 if item.kind == 'box' else 0))
    return found


def render(node):
    """Lines of text for what a stand-in layout recorded."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, tuple) and node[0] == 'panel':
        return ['> ' + '  '.join(render(node[1]))] + ['  ' + line for line in render(node[2])]
    if isinstance(node, tuple) and node[0] == 'list':
        return ['  . ' + line for line in render(node[1])]
    parts = [render(item) for item in node.items]
    if node.kind == 'row':
        lines = ['  '.join(' / '.join(part) for part in parts if part)] if any(parts) else []
    elif node.kind == 'grid':
        width = node.columns or 1
        flat = [' / '.join(part) for part in parts if part]
        lines = ['  '.join(flat[i:i + width]) for i in range(0, len(flat), width)]
    else:
        lines = [line for part in parts for line in part]
    if node.kind == 'box':
        lines = ['| ' + line for line in lines]
    marks = ('' if node.state.get('enabled', True) else ' (greyed out)') + ('' if node.state.get('active', True) else ' (dimmed)')
    return [('! ' if node.state.get('alert') else '') + line + marks for line in lines]


class Context:
    """bpy.context as a sidebar panel's draw receives it, with a sidebar region of the given width."""
    def __init__(self, width=WIDTH):
        self.region = SimpleNamespace(width=width, type='UI')

    def __getattr__(self, name):
        return getattr(bpy.context, name)


class Self:
    """Stands in for a panel instance: its layout, and the panel class's other attributes."""
    def __init__(self, cls, layout):
        self.cls, self.layout = cls, layout

    def __getattr__(self, name):
        return getattr(self.cls, name)


def panels():
    """The add-on's panel classes, each followed by its sub-panels in registration order, as Blender draws them."""
    classes = [cls for cls in sekiro_retarget.CLASSES if issubclass(cls, bpy.types.Panel)]
    ids = {getattr(cls, 'bl_idname', cls.__name__): cls for cls in classes}
    for cls in classes:
        parent = getattr(cls, 'bl_parent_id', '')
        assert not parent or parent in ids, (cls.__name__, 'has no parent panel', parent)
        assert cls.bl_space_type == 'VIEW_3D' and cls.bl_region_type == 'UI' and cls.bl_category in ('Retarget', 'Animate'), cls
        assert not parent or ids[parent].bl_category == cls.bl_category, (cls.__name__, 'is in another tab than its parent')
        assert set(getattr(cls, 'bl_options', set())) <= {'DEFAULT_CLOSED', 'HIDE_HEADER', 'INSTANCED', 'HEADER_LAYOUT_EXPAND'}, cls

    def tree(parent, depth):
        for cls in classes:
            if getattr(cls, 'bl_parent_id', '') == parent:
                yield cls, depth
                yield from tree(getattr(cls, 'bl_idname', cls.__name__), depth + 1)
    # Each sidebar tab shows its own panels: the Retarget tab's, then the Animate tab's.
    return sorted(tree('', 0), key=lambda item: TABS.index(item[0].bl_category))


TABS = ('Retarget', 'Animate')


def outline(context):
    """Every panel of the add-on as rows of text, in drawing order; sub-panels whose poll fails are left out."""
    lines, hidden, tab = [], set(), None
    blf.size(0, bpy.context.preferences.ui_styles[0].widget.points)
    for cls, depth in panels():
        if cls.bl_category != tab:
            tab = cls.bl_category
            lines.append(f'[{tab} tab]')
        if getattr(cls, 'bl_parent_id', '') in hidden or (hasattr(cls, 'poll') and not cls.poll(context)):
            hidden.add(getattr(cls, 'bl_idname', cls.__name__))
            continue
        indent = '    ' * depth
        options = set(getattr(cls, 'bl_options', set()))
        if 'HIDE_HEADER' not in options:
            header = Layout('row')
            for name in ('draw_header', 'draw_header_preset'):
                if hasattr(cls, name):
                    getattr(cls, name)(Self(cls, header), context)
            extra = '  '.join(render(header))
            lines.append(indent + ('> ' if 'DEFAULT_CLOSED' in options else 'v ') + cls.bl_label +
                         (' (starts closed)' if 'DEFAULT_CLOSED' in options else '') + (f'  {extra}' if extra else ''))
        layout = Layout('column')
        cls.draw(Self(cls, layout), context)
        lines += [indent + '    ' + line for line in render(layout)]
        too_wide = cut(layout, context.region.width - MARGIN)
        assert not too_wide, (cls.__name__, 'cuts', too_wide)
    return '\n'.join(lines)


def bridge_rig(name, bones, clip, scale=1.0):
    """A rig imported by the bridge from synthetic motion JSON, with root motion; ANIMATED bones swing about X."""
    index = {bone[0]: i for i, bone in enumerate(bones)}

    def game(v):
        return Vector((v[0], v[2], v[1])) * scale
    skeleton = [dict(index=i, name=bone, parent=index[parent] if parent else -1, rotation=[0, 0, 0, 1], scale=[1, 1, 1],
                     translation=list(game(head) - (game(bones[index[parent]][2]) if parent else Vector())))
                for i, (bone, parent, head, label) in enumerate(bones)]
    tracks = [i for i, bone in enumerate(bones)
              if bone[3] or bone[0] in ('Master', 'RootPos', 'RootRotY', 'RootRotXZ', 'L_Weapon', 'R_Weapon')]
    frames = []
    for f in range(COUNT):
        swing = math.sin(2 * math.pi * f / (COUNT - 1))
        frames.append([dict(translation=skeleton[i]['translation'], scale=[1, 1, 1],
                            rotation=[math.sin(ANIMATED.get(bones[i][0], 0) * swing / 2), 0, 0,
                                      math.cos(ANIMATED.get(bones[i][0], 0) * swing / 2)]) for i in tracks])
    return import_motion(dict(
        format='sekiro-animation-bridge', formatVersion=1, clip=clip + '.hkx', skeletonName=name, game='sekiro',
        skeleton=dict(name=name, boneCount=len(skeleton), bones=skeleton), frameCount=COUNT, frameRate=RATE,
        duration=(COUNT - 1) / RATE, trackCount=len(tracks), trackBoneIndices=tracks,
        trackNames=[bones[i][0] for i in tracks], frames=frames,
        rootMotion=[[.01 * f, 0, .02 * f, .005 * f] for f in range(COUNT)], rootUp=[0, 1, 0, 0], rootForward=[0, 0, 1, 0]))


def activate(rig):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == rig)
    bpy.context.view_layer.objects.active = rig


def states():
    """Bring an empty scene, with the add-on registered, into each state the panels draw; yields the state's name."""
    scene = bpy.context.scene
    settings, fix = scene.sekiro_retarget, scene.sekiro_fix
    yield 'Nothing chosen'

    # The donor first, so that the target is the rig the scene records for export, as after a two-character import.
    source = bridge_rig('Donor', humanoids.fromsoftware(0, 'souls'), 'a000_003008')
    target = bridge_rig('Hero', humanoids.fromsoftware(45, 'elden'), 'a000_000401', 1.1)
    # A weapon mesh on the target's right weapon bone, as the bridge attaches weapons, for the defaults of the fixes.
    blade = bpy.data.objects.new('Blade', bpy.data.meshes.new('Blade'))
    blade.data.from_pydata([(0, 0, 0), (.8, 0, 0), (.8, .02, 0)], [], [(0, 1, 2)])
    scene.collection.objects.link(blade)
    blade.parent, blade.parent_type, blade.parent_bone = target, 'BONE', 'R_Weapon'
    bpy.ops.object.mode_set(mode='OBJECT')
    activate(target)
    yield 'Rig imported'

    settings.target, settings.source = target, source
    yield 'Source and target chosen'

    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    rows = list(settings.rows)
    review = [i for i, row in enumerate(rows) if row.suggestion and not row.source] or \
             [i for i, row in enumerate(rows) if row.source and row.confidence < .94] or [0]
    settings.active_row = review[0]
    yield 'Bones matched'

    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    yield 'Baked'

    settings.export_path, settings.export_format = '//a000_000401.hkx', 'spline'
    settings.auto_scale, settings.root_motion = False, 'EXTRACT'
    yield 'Every option shown'

    settings.auto_scale, settings.root_motion, settings.export_format = True, 'AUTO', 'interleaved'
    settings.method = 'BODY'
    settings.rows.clear()
    yield 'Full body without a bone list'

    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    yield 'Full body baked'

    scene.frame_set(10)
    settings.grip_item = 'R_Weapon|R_Hand'
    assert bpy.ops.sekiro_retarget.grip_adjust() == {'FINISHED'}
    yield 'Weapon in hand: posing'

    weapon = target.pose.bones['R_Weapon']
    weapon.matrix = Matrix.Translation((0, 0, .01)) @ weapon.matrix
    assert bpy.ops.sekiro_retarget.grip_apply() == {'FINISHED'}, settings.status
    yield 'Weapon in hand: aligned'

    assert bpy.ops.sekiro_retarget.grip_reset() == {'FINISHED'}, settings.status
    bpy.ops.object.mode_set(mode='OBJECT')

    settings.method = 'BONES'
    assert bpy.ops.sekiro_retarget.match_bones() == {'FINISHED'}
    assert bpy.ops.sekiro_retarget.bake() == {'FINISHED'}, settings.status
    activate(target)
    assert bpy.ops.sekiro_retarget.add_control_rig() == {'FINISHED'}
    yield 'Control rig on'

    data = control_rig.layout(target)
    limbs = {limb['label']: index for index, limb in enumerate(data['limbs'])}
    for limb in data['limbs']:
        if limb['kind'] == 'arm':
            target.pose.bones[limb['control']][control_rig.SWITCH] = 1.0
    target.update_tag()
    scene.frame_set(12)
    fix.task = 'HAND'
    fix.span, fix.frame_start, fix.frame_end = 'RANGE', 8, 16
    assert bpy.ops.sekiro_retarget.fix_pose() == {'FINISHED'}, fix.status
    yield 'Fix: hand on weapon, one frame posed'

    fix.task = 'PLANT'
    fix.limb = str(limbs['Left leg'])
    yield 'Fix: plant foot with the leg in FK'

    fix.task = 'ADJUST'
    scene.tool_settings.use_keyframe_insert_auto = True
    yield 'Fix: adjust over frames with auto keying on'

    scene.tool_settings.use_keyframe_insert_auto = False
    fix.task = 'HAND'
    fix.span, fix.frame_start, fix.frame_end = 'RANGE', 8, 16
    bpy.ops.sekiro_retarget.fix_apply()
    yield 'Fix applied'

    bpy.ops.object.mode_set(mode='OBJECT')  # As after opening the file again.
    yield 'Control rig in Object Mode'

    assert bpy.ops.sekiro_retarget.remove_control_rig(keep='EDITED') == {'FINISHED'}
    scene.sekiro_join.second = bpy.data.actions['a000_000401_Sekiro']
    yield 'Join chosen'

    assert bpy.ops.sekiro_retarget.join_animations() == {'FINISHED'}, settings.status
    settings.export_binder = True
    yield 'Joined, export to a binder'


# What each state's outline must show and must not show, in the words of its rows, however they wrap; a row
# starting with ! is an alert's first line.
EXPECTED = {
    'Nothing chosen': (['(Match bones automatically) (greyed out)', 'Choose the target and the source first.',
                        '(Bake motion onto target) (greyed out)', 'Export needs a target imported by the bridge.',
                        'Select the armature to pose, such as the target after a bake.'],
                       ['Export settings', '{list']),
    'Rig imported': (['Adds controls to pose the arms and legs', '(Add control rig)'], []),
    'Source and target chosen': (['(Save map) (greyed out)  (Load map)', 'Match bones first.'],
                                 ['(Match bones automatically) (greyed out)']),
    'Bones matched': (['(Match bones again)', '55 of 58 bones matched, 3 to review.', '{list: 58 of 58 rows',
                       'Master: Same normalized name', '(Export HKX) (greyed out)', 'Choose the Output file first.'],
                      ['(Bake motion onto target) (greyed out)', 'Match bones first.']),
    'Baked': (['Baked 24 frames from 55 mapped bones'], []),
    'Every option shown': (['Travel scale: [1]', '[ ] Turn root with the body', 'Rotations', 'Tolerance: [0.001]'],
                           ['(Export HKX) (greyed out)']),
    'Full body without a bone list': (['Bake method', '[Full body v]',
                                       "Finds the body in both rigs and keeps the feet on the source's footprint.",
                                       '(Bake motion onto target)'],
                                      ['(Bake motion onto target) (greyed out)', 'Match bones first.', '{list']),
    'Full body baked': (["Baked 24 frames from the full body", "Full body: 52 body bones follow the source's body chains",
                         'R_Weapon sits in R_Hand'], ['foot kept on the source']),
    'Weapon in hand: posing': (['Frame 10: turn (R) or move (G) R_Weapon until it sits in R_Hand as you want',
                                '(Apply to all frames)  (Cancel)'], ['(Adjust weapon)']),
    'Weapon in hand: aligned': (['R_Weapon sits in R_Hand as you aligned it under Weapon in hand', '(Adjust weapon)',
                                 'Aligned: 1.0 cm, 0.0°  (Reset)'], ['(Apply to all frames)']),
    'Control rig on': (['The target has a control rig. Remove it under Control rig before baking',
                        'IK slider: 0 follows FK, 1 follows IK.', '(Remove control rig)', 'v Fixes'],
                       ['(Add control rig)', '(Pose Mode)']),
    'Fix: hand on weapon, one frame posed': (['Posed frames: 12', 'Posed frame 12. Pose another frame, or click Apply fix.'],
                                             []),
    'Fix: plant foot with the leg in FK': (['! Left leg is not in IK',
                                            'Left leg is not in IK on this frame. The fix moves its IK controls',
                                            '(Switch to IK)'], ['Posed frames']),
    'Fix: adjust over frames with auto keying on': (['! Auto keying is on.', 'Turn it off before you pose'], []),
    'Fix applied': (['Left arm follows R_Weapon on frames 8–16'], ['Posed frames']),
    'Control rig in Object Mode': (['The controls are posed in Pose Mode.', '(Pose Mode)'], []),
    'Join chosen': (['Then', '[a000_000401_Sekiro]', '(Join animations)'], ['(Join animations) (greyed out)']),
    'Joined, export to a binder': (['Joined ', '[x] Add to animation binder',
                                    'Uses a000_000401.hkx',
                                    'This scene does not record the archive its clip came from. Choose the binder.'], []),
}


def check_list(settings):
    """The bone list's name filter finds target and source bones, the review filter its rows to review, and its A-Z
    sort orders the rows by target bone."""
    def filtered(name, alpha=False):
        helper = SimpleNamespace(bitflag_filter_item=1 << 30, filter_name=name, use_filter_sort_alpha=alpha)
        return sekiro_retarget.SKR_UL_bones.filter_items(helper, bpy.context, settings, 'rows')
    flags, order = filtered('THIGH')
    found = [row for row, flag in zip(settings.rows, flags) if flag]
    assert len(found) >= 2 and all('thigh' in (row.target + row.source).lower() for row in found), found
    flags, order = filtered('', alpha=True)
    names = [row.target for row in settings.rows]
    assert all(flags) and [names[i] for i in sorted(range(len(names)), key=order.__getitem__)] == sorted(names, key=str.lower)
    settings.review_only = True
    flags, order = filtered('')
    settings.review_only = False
    assert sum(map(bool, flags)) == sum(map(sekiro_retarget.needs_review, settings.rows)) == 3, flags
    print(f'Bone list: the name filter THIGH shows {len(found)} of {len(names)} rows ({", ".join(r.target for r in found)}), '
          f'the review filter 3; the A-Z sort orders all {len(names)} by target bone')


def words(text):
    """An outline's rows as one line, without box and alert marks, so that a message is found however it wraps."""
    return ' '.join(line.strip().lstrip('|!').strip() for line in text.splitlines())


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sekiro_retarget.register()
    drawn = {}
    for state in states():
        drawn[state] = text = outline(Context())
        print(f'== {state}\n{text}\n', flush=True)
        shown, absent = EXPECTED[state]
        for row in shown:
            assert row in (text if row.startswith('!') else words(text)), (state, 'does not show', row)
        for row in absent:
            assert row not in words(text), (state, 'shows', row)
        # The target comes first, and the log, closed, after the last step; the Animate tab has its own.
        assert text.index('Target (receives the motion)') < text.index('Source (gives the motion)'), state
        animate = text.index('[Animate tab]')
        assert text.index('v 4. Export HKX') < text.index('> Log (starts closed)') < animate, (state, 'has no log after step 4')
        assert text.index('v Animation', animate) < text.index('v Control rig', animate) < text.rindex('> Log'), state
        if state == 'Bones matched':
            check_list(bpy.context.scene.sekiro_retarget)
    assert set(drawn) == set(EXPECTED), set(EXPECTED) ^ set(drawn)
    folder = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv[:-1] else None
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / 'panels.txt').write_text(''.join(f'== {state}\n{text}\n\n' for state, text in drawn.items()),
                                                 encoding='utf-8')
    sekiro_retarget.unregister()
    print(f'Panel check passed: {len(drawn)} states drawn without errors or cut labels, each with its expected rows')


if __name__ == '__main__':
    main()
