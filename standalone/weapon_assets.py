"""Game-specific weapon preview profiles and authored FLVER socket transforms.

Facts: vanilla EquipParamWeapon 8000000 -> model 300 / absorp 5000,
9700000 -> model 310 / absorp 5000; WepAbsorpPosParam 5000 uses
20 for a drawn sword and 147 for its sheath. Sekiro's Mortal Blade slot
uses socket 149 while stowed (also used by DSAnimStudio).
Prosthetic socket IDs below come from WepAbsorpPosParam 7000..7900.

DS3 and Elden Ring use the WepAbsorpPosParam default row (DS3
WEP_ABSORP_POS_PARAM_ST defaults; ER has the same field order): model 0 /
model 1 use 20 / 30 in the right hand, 21 / 31 in the left hand, 24 / 21
two-handed and 30 / 30 or 31 / 31 while sheathed. In the DS1, DS3 and ER
c0000 references dummy 30 is the left hip and 31 the right hip, so a
right-hand weapon's scabbard hangs on the opposite hip, as in Sekiro's row
5000 (sheath 147 on the left hip). DS1 has no such param; its dummies 30 / 31
are attached to L_Wepon_Case / R_Wepon_Case.
These are preview placements, not a simulation of equipment/TAE state.
"""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np

PROSTHETIC_SOCKETS = {700:112,710:113,720:114,730:115,740:116,750:117,760:118,770:119,780:123,790:124}
PLACEMENTS = {'right':20, 'left':21, 'sheath':147, 'back':149}
# (model 0, extra models) for each weapon state outside Sekiro.
ABSORP_DEFAULTS = {'right':(20,30), 'left':(21,31), 'both':(24,21), 'sheath':(30,30), 'sheath-left':(31,31)}
DS1_BONES = {20:'R_Weapon', 21:'L_Weapon', 24:'R_Weapon', 30:'L_Wepon_Case', 31:'R_Wepon_Case'}
# Extra models whose FLVER bones do not name a scabbard.
KNOWN_SCABBARDS = {'ds1': {'wp_a_0201'}, 'ds1r': {'wp_a_0201'}, 'ds3': {'wp_a_0201'}}
SOCKET_LABELS = {'sekiro': {20:'right hand', 21:'left hand', 147:'hip sheath', 149:'back'},
                 'souls': {20:'right hand', 21:'left hand', 24:'right hand, two-handed', 30:'left hip', 31:'right hip'}}


def weapon_id(name):
    match = re.match(r'wp_[a-z]_(\d{4,6})(?:_|$)', name.lower())
    return int(match[1]) if match else None


def default_socket(name, model_index=0):
    ident = weapon_id(name)
    if ident in (300,301,9500):
        return 147 if model_index == 1 else 20
    if ident == 310:
        return 149
    if ident is not None and 700 <= ident < 800:
        return PROSTHETIC_SOCKETS.get((ident//10)*10)
    return None


def extra_model_kind(name, model_index, game, model_bones=()):
    """Classify an additional weapon model: scabbard, paired weapon or accessory."""
    names = [str(b).lower() for b in model_bones]
    if (model_index == 1 and name.lower() in KNOWN_SCABBARDS.get(game, set())) or \
            any(re.search(r'sheath|saya|scabbard|case', b) for b in names):
        return 'scabbard'
    # A second blade carries its own weapon dummy bone, as model 0 does.
    if any(b.startswith(('dymmy', 'dummy')) and 'sfx' not in b for b in names):
        return 'paired'
    return 'accessory'


def custom_sockets(placement, model_index):
    """dummy:ID applies to every model; dummy:20,30 lists model 0, model 1, ..."""
    try:
        values = [int(v) for v in placement[6:].split(',')]
    except ValueError:
        values = []
    if not values or len(values) > 8 or any(not 0 <= v <= 32767 for v in values):
        raise ValueError(f'Invalid weapon attachment: {placement}. Use dummy:ID or dummy:ID,ID for model 0, model 1.')
    return values[min(model_index, len(values) - 1)]


def socket_choice(name, model_index, placement='auto', game='sekiro', model_bones=()):
    if placement.startswith('dummy:'):
        return custom_sockets(placement, model_index)
    if game != 'sekiro':
        state = 'right' if placement == 'auto' else placement
        if state not in ABSORP_DEFAULTS:
            raise ValueError(f'{game} has no automatic {placement} placement. Choose a hand, Two-handed, a sheathed state or custom dummy IDs from its c0000 reference.')
        main, extra = ABSORP_DEFAULTS[state]
        if model_index == 0:
            return main
        # The default row moves model 1 into the left hand for paired weapons;
        # a scabbard stays on the hip it uses in the one-handed state.
        if state == 'both' and extra_model_kind(name, model_index, game, model_bones) != 'paired':
            return ABSORP_DEFAULTS['right'][1]
        return extra
    if placement == 'auto':
        result = default_socket(name, model_index)
        if result is None:
            raise ValueError(f'{name.upper()}: no verified automatic attachment profile. Choose Right hand, Left hand, Hip sheath, Back, or an explicit dummy ID under Weapons & extra parts.')
        return result
    if placement in PLACEMENTS:
        # A sword's sheath remains on the body when its blade is drawn.
        if model_index == 1 and placement in ('right','left'):
            return 149 if weapon_id(name)==310 else 147
        return PLACEMENTS[placement]
    raise ValueError(f'Invalid Sekiro weapon attachment: {placement}. Choose Auto, Right hand, Left hand, Hip sheath, Back or custom dummy IDs.')


def describe_attachment(result):
    """Short log text for a resolved weapon attachment."""
    if result['kind'] == 'bone':
        via = f' via {result["bone"]}' if result['bone'] != result['anchorBone'] else ''
        return f'bone {result["anchorBone"]}{via}'
    label = SOCKET_LABELS['sekiro' if result.get('game') == 'sekiro' else 'souls'].get(result['dummy'])
    return f'dummy {result["dummy"]}' + (f' · {label}' if label else '') + f' ({result["bone"] or "model root"})'


def reference_file(sources, texture_dir='', explicit=''):
    if explicit:
        path=Path(explicit).expanduser().resolve()
        if not path.is_file(): raise ValueError(f'Rig attachment model not found: {path}')
        return path
    roots={Path(p).resolve().parent for p in sources}
    if texture_dir: roots.add(Path(texture_dir).resolve())
    candidates=set()
    for root in list(roots):
        for base in [root,root.parent]:
            for relative in ('c0000.chrbnd.dcx','c0000.chrbnd','c0000.flver','chr/c0000.chrbnd.dcx',
                             'skeleton_reference/c0000.chrbnd.dcx','c0000-chrbnd-dcx/c0000.flver'):
                path=base/relative
                if path.is_file(): candidates.add(path.resolve())
        if root.is_dir():
            for pattern in ('**/c0000.chrbnd.dcx','**/c0000.flver'):
                candidates.update(p.resolve() for p in root.glob(pattern) if p.is_file())
    if not candidates:
        raise ValueError('Separate weapons need this game’s c0000.chrbnd.dcx (or its c0000.flver) for their attachment transforms. Put it in the assets folder and rescan, or choose Rig attachment model under Textures & materials.')
    # Original binder is preferred over its loose extracted copy. Conflicting
    # originals are left for explicit selection rather than chosen by filename.
    binders=sorted(p for p in candidates if 'bnd' in p.name.lower())
    preferred=binders or sorted(candidates)
    if len(preferred)>1:
        import hashlib
        if len({hashlib.sha256(p.read_bytes()).digest() for p in preferred})>1:
            raise ValueError('Several different c0000 reference models were found. Choose Rig attachment model explicitly under Textures & materials.')
    return preferred[0]


def read_reference(path):
    from dcx_codec import unwrap
    from soulstruct.flver import FLVER
    from soulstruct.containers import Binder
    path=Path(path);data=unwrap(path.read_bytes())[0]
    if path.name.lower().endswith(('.flver','.flver.dcx')):
        return FLVER.from_bytes(data)
    matches=[e for e in Binder.from_bytes(data).entries if e.name.lower()=='c0000.flver']
    if len(matches)!=1:
        raise ValueError('Rig attachment model must contain exactly one c0000.flver.')
    return FLVER.from_bytes(unwrap(matches[0].data)[0])


def bone_worlds(bones):
    """FLVER uses column-vector Ry Rz Rx local rotations, equivalent to XZY Euler."""
    worlds={};visiting=set()
    def world(i):
        if i in worlds:return worlds[i]
        if i in visiting:raise ValueError('FLVER bone hierarchy contains a cycle.')
        if not 0<=i<len(bones):raise ValueError('FLVER bone parent index is invalid.')
        visiting.add(i);b=bones[i];x,y,z=np.asarray(b.rotate,dtype=float)
        cx,cy,cz=np.cos([x,y,z]);sx,sy,sz=np.sin([x,y,z])
        rx=np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
        ry=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
        rz=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
        local=np.eye(4);local[:3,:3]=(ry@rz@rx)@np.diag(np.asarray(b.scale,dtype=float))
        local[:3,3]=np.asarray(b.translate,dtype=float)
        parent=int(b.parent_bone_index)
        worlds[i]=world(parent)@local if parent>=0 else local
        visiting.remove(i);return worlds[i]
    return [world(i) for i in range(len(bones))]


def dummy_frame(dummy):
    def normalize(value):
        value=np.asarray(value,dtype=float);length=np.linalg.norm(value)
        if length<1e-10:raise ValueError('Attachment dummy has a zero or parallel direction vector.')
        return value/length
    # The game's CreateWorld basis uses -forward as its local +Z axis.
    backward=-normalize(dummy.forward)
    up=normalize(dummy.upward) if dummy.use_upward_vector else np.array([0.,1.,0.])
    right=normalize(np.cross(up,backward));up=np.cross(backward,right)
    result=np.eye(4);result[:3,:3]=np.column_stack((right,up,backward))
    result[:3,3]=np.asarray(dummy.translate,dtype=float)
    return result


def attachment(reference, dummy_id, source='', game='sekiro'):
    matches=[d for d in reference.dummies if int(d.reference_id)==dummy_id]
    if len(matches)!=1:
        raise ValueError(f'Attachment dummy {dummy_id} has {len(matches)} matches in the reference model; choose an unambiguous socket.')
    d=matches[0];worlds=bone_worlds(reference.bones)
    parent=worlds[d.parent_bone_index] if d.parent_bone_index>=0 else np.eye(4)
    bind_frame=parent@dummy_frame(d)
    follows=d.follows_attach_bone and d.attach_bone_index>=0
    bone=reference.bones[d.attach_bone_index].name if follows else ''
    local=np.linalg.inv(worlds[d.attach_bone_index])@bind_frame if follows else bind_frame
    # DS3 and Sekiro use the same net Y half-turn in a dummy's frame.
    # DS1's left-side dummy already supplies the old-game left-hand basis.
    left_ds1 = game in ('ds1','ds1r') and bone.startswith('L_')
    local=local@(np.eye(4) if left_ds1 else np.diag([-1.,1.,-1.,1.]))
    conversion=np.array([[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]],dtype=float)
    return dict(kind='dummy',game=game,dummy=dummy_id,bone=bone,matrix=(conversion@local@conversion).tolist(),
                reference=str(source),bindMatrix=(conversion@bind_frame@conversion).tolist())


def bone_attachment(reference, bone_name, source='', side='right', skeleton_bones=None):
    """DS1 uses animation weapon bones directly, independently of skeleton.Name."""
    matches=[i for i,b in enumerate(reference.bones) if b.name==bone_name]
    if len(matches)!=1:
        raise ValueError(f'Weapon reference has {len(matches)} bones named {bone_name}. Select this game’s matching c0000 reference.')
    worlds=bone_worlds(reference.bones)
    original=matches[0];follow=original
    available=set(skeleton_bones) if skeleton_bones is not None else None
    # A model-only scabbard node may not be represented in the HKX. Its
    # nearest animated ancestor retains the authored rest offset.
    while available is not None and reference.bones[follow].name not in available:
        follow=int(reference.bones[follow].parent_bone_index)
        if follow<0: raise ValueError(f'{bone_name} has no matching ancestor in this animation skeleton. Choose its own c0000 animation rig/reference.')
    basis=np.diag([1.,-1.,-1.,1.]) if side=='left' else np.diag([-1.,-1.,1.,1.])
    local=np.linalg.inv(worlds[follow])@worlds[original]@basis
    conversion=np.array([[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]],dtype=float)
    return dict(kind='bone',dummy=-1,bone=reference.bones[follow].name,anchorBone=bone_name,
        matrix=(conversion@local@conversion).tolist(),reference=str(source),
        bindMatrix=(conversion@worlds[original]@conversion).tolist())


def weapon_attachment(reference, name, model_index, placement='auto', game='sekiro', source='', skeleton_bones=None, model_bones=()):
    """Resolve one member's preview placement using its game's conventions."""
    if not isinstance(placement,str): raise ValueError('Weapon placement must be Auto, a named placement, or dummy:ID.')
    socket=socket_choice(name,model_index,placement,game,model_bones)
    custom=placement.startswith('dummy:')
    if game in ('ds1','ds1r') and not custom:
        # Bone sides follow the body: L_Wepon_Case is the left hip.
        bone=DS1_BONES[socket]
        result=bone_attachment(reference,bone,source,'left' if bone.startswith('L_') else 'right',skeleton_bones)
    else:
        result=attachment(reference,socket,source,game)
    if skeleton_bones is not None and result['bone'] and result['bone'] not in set(skeleton_bones):
        raise ValueError(f'{name.upper()}: attachment requires bone {result["bone"]}, missing from the selected animation skeleton. Choose matching player animation and c0000 reference files.')
    result.update(game=game,placement=placement,package=name,modelIndex=model_index)
    if game!='sekiro' and model_index>1 and not custom:
        result['notice']=(f'{name.upper()} model {model_index}: placed like model 1 because the game param has no default for it. '
                          'Use custom dummy IDs (for example dummy:20,30,21) if it belongs elsewhere.')
    return result
