"""Animated weapon parts: which of a part's clips plays with a character clip.

A part binder (PARTSBND) holds an animation binder for each animated model, named
after it: WP_A_0760_1.anibnd animates WP_A_0760_1.flver. Its clips carry the
character's TAE animation IDs, so a076_405010_1.hkx plays while Wolf plays TAE ID
a076_405010. A character's TAE can give an ID the HKX of another ID (Wolf's
a076_412000 plays the body clip a070_412000), and so can the part's own TAE. A
part without a clip for the current ID holds a999_000000, its rest pose.

No TAE event starts a part animation in Sekiro's TAE template; the pairing above
follows the IDs and was checked on every animated prosthetic tool.

Where a weapon model sits is another matter: event 715 of the character's TAE
moves the models of one weapon slot to other dummies while it runs, and -1 hides
a model. Wolf's a076_405010 puts the umbrella's animated model WP_A_0760_1 on
dummy 21, the left hand, and hides WP_A_0760, which otherwise sits on the
forearm's dummy 118. locate() records these changes in the character manifest.
Events that hide a weapon (710) or a model mask (711, 713) are not read.

The UI's part view reads the same pairing backwards: pairings() runs
choose_clip() over every clip of the player, so a clip it lists is the one the
import keys.
"""
from __future__ import annotations
import re
import struct
from collections import Counter
from pathlib import Path, PureWindowsPath

REST = 999_000_000
# Sekiro's TAE. Other versions are not read: their parts pair by the same ID only.
TAE_VERSIONS = (0x1000D,)
CLIP = re.compile(r'a(\d{2,3})_(\d{6})(?:_\d+)?(?:\.hkx)?', re.I)
WEAPON = re.compile(r'wp_[a-z]_\d{4,6}(?:_\d+)?', re.I)
# Sekiro's part clips carry the player's TAE IDs.
PLAYER = 'c0000'
# OverrideWeaponModelLocation: a slot, then a dummy for each of its models 0-3.
LOCATION = 715
# The slot of event 715 that places a weapon, checked on Wolf's TAE against the
# clips of each part: 0 the sword, 2 the Mortal Blade, 3 the grappling hook, and
# 1 for the prosthetic tools wp_a_0700 to wp_a_0799.
LOCATION_SLOTS = {300: 0, 310: 2, 9500: 3}
_CACHE = {}


def animation_id(name):
    """The animation ID of a clip or member name such as a076_405010_1.hkx, else None."""
    match = CLIP.fullmatch(PureWindowsPath(str(name)).name)
    return int(match[1]) * 1_000_000 + int(match[2]) if match else None


def clip_name(ident):
    return f'a{ident // 1_000_000:03d}_{ident % 1_000_000:06d}'


def tae_entries(data, category=None):
    """(animation ID, offset of its header) for each animation of a TAE; none for a version this reader does not know.

    Character TAE files (a076.tae) number their animations within the category;
    part TAE files use full IDs.
    """
    if len(data) < 0x60 or data[:4] != b'TAE ' or data[4] != 0 or struct.unpack_from('<i', data, 8)[0] not in TAE_VERSIONS:
        return
    count, = struct.unpack_from('<i', data, 0x54)
    table, = struct.unpack_from('<q', data, 0x58)
    for index in range(count):
        ident, offset = struct.unpack_from('<qq', data, table + 16 * index)
        if category is not None and ident < 1_000_000:
            ident += category * 1_000_000
        yield ident, offset


def read_tae(data, category=None):
    """How each animation ID of a TAE gets its HKX: ('own', ID), ('hkx', source ID) or ('other', entry ID).

    A TAE version this reader does not know gives {}.
    """
    result = {}
    for ident, offset in tae_entries(data, category):
        file_offset, = struct.unpack_from('<q', data, offset + 24)
        reference, data_offset = struct.unpack_from('<qq', data, file_offset)
        if reference:
            result[ident] = ('other', struct.unpack_from('<i', data, data_offset)[0])
        else:
            imports, source = data[data_offset + 9], struct.unpack_from('<i', data, data_offset + 12)[0]
            result[ident] = ('hkx', source) if imports and source >= 0 else ('own', ident)
    return result


def read_locations(data, category=None):
    """Event 715 of each animation ID of a TAE that has one: [(start s, end s, slot, (dummy of model 0, ..., 3))], in TAE order."""
    result = {}
    for ident, offset in tae_entries(data, category):
        events, = struct.unpack_from('<q', data, offset)
        count, = struct.unpack_from('<i', data, offset + 0x20)
        rows = []
        for index in range(count):
            start, end, block = struct.unpack_from('<qqq', data, events + 24 * index)
            kind, = struct.unpack_from('<i', data, block)
            if kind == LOCATION:
                parameters, = struct.unpack_from('<q', data, block + 8)
                rows.append((struct.unpack_from('<f', data, start)[0], struct.unpack_from('<f', data, end)[0],
                             data[parameters], struct.unpack_from('<4i', data, parameters + 4)))
        if rows:
            result[ident] = rows
    return result


def played_hkx(tae, ident):
    """The HKX that an animation ID plays: its own, another ID's HKX, or what a referenced entry plays."""
    seen = set()
    while ident not in seen:
        seen.add(ident)
        kind, source = tae.get(ident, ('own', ident))
        if kind == 'own':
            return ident
        if kind == 'hkx':
            return source
        ident = source
    return ident


def players_of(tae):
    """The IDs of a character TAE by the HKX that each one plays."""
    result = {}
    for ident in tae:
        result.setdefault(played_hkx(tae, ident), []).append(ident)
    return result


def binder_tae(binder, read=read_tae):
    """One index of every TAE member of an animation binder, by read_tae() or read_locations()."""
    from dcx_codec import unwrap
    result = {}
    for entry in binder.entries:
        name = PureWindowsPath(entry.path).name.lower()
        if name.endswith('.tae'):
            category = re.fullmatch(r'a(\d{2,3})\.tae', name)
            result.update(read(unwrap(entry.data)[0], int(category[1]) if category else None))
    return result


def cached(path, kind, read):
    """Read a file once per change: the UI asks again whenever the selection changes."""
    path = Path(path)
    stat = path.stat()
    key = (kind, str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        if len(_CACHE) > 48:
            _CACHE.clear()
        _CACHE[key] = read(path)
    return _CACHE[key]


def character_binder(catalog, clip):
    """The character's base animation binder (c0000.anibnd.dcx), which holds its TAE, or None."""
    character = (clip.get('character') or '').lower()
    if not character:
        return None
    names = (character + '.anibnd', character + '.anibnd.dcx')
    candidates = list(clip.get('inputArchives') or [])
    entry = next((c for c in catalog.get('characters', []) if c.get('id') == clip.get('characterKey')), None)
    candidates += (entry or {}).get('archives', [])
    folder = Path(clip.get('archive') or clip.get('path') or '.').parent
    candidates += [s['path'] for s in catalog.get('sources', []) if Path(s['path']).parent == folder]
    return next((Path(p) for p in candidates if Path(p).name.lower() in names and Path(p).is_file()), None)


def character_tae(path):
    """Animation IDs of a character's TAE, from its base animation binder; {} without one."""
    if not path:
        return {}

    def read(file):
        from soulstruct.containers import Binder
        from dcx_codec import unwrap
        return binder_tae(Binder.from_bytes(unwrap(file.read_bytes())[0]))
    return cached(path, 'tae', read)


def character_locations(path):
    """Event 715 of a character's TAE by animation ID, from its base animation binder; {} without one."""
    if not path:
        return {}

    def read(file):
        from soulstruct.containers import Binder
        from dcx_codec import unwrap
        return binder_tae(Binder.from_bytes(unwrap(file.read_bytes())[0]), read_locations)
    return cached(path, 'locations', read)


def part_binders(path):
    """The animation binders of a part binder, by the model they animate (wp_a_0760_1)."""
    def read(file):
        from soulstruct.containers import Binder
        from dcx_codec import unwrap
        if file.name.lower().endswith(('.flver', '.flver.dcx')):
            return {}
        binder = Binder.from_bytes(unwrap(file.read_bytes())[0])
        return {PureWindowsPath(e.path).name.lower().split('.')[0]: read_part(e.data, PureWindowsPath(e.path).name)
                for e in binder.entries if e.path.lower().endswith(('.anibnd', '.anibnd.dcx'))}
    return cached(path, 'parts', read)


def read_part(data, name):
    """Skeleton, compendium, TAE and clips of a part's animation binder. Members stay as raw bytes."""
    from soulstruct.containers import Binder
    from dcx_codec import unwrap
    binder = Binder.from_bytes(unwrap(data)[0])
    part = dict(binder=name, skeleton=None, compendium=None, tae={}, clips={}, members={})
    for entry in binder.entries:
        member = PureWindowsPath(entry.path).name
        low = member.lower()
        part['members'][member] = entry.data
        if low.endswith('.tae'):
            part['tae'] = read_tae(unwrap(entry.data)[0])
        elif low.endswith('.compendium'):
            part['compendium'] = member
        elif low.startswith('skeleton') and low.endswith('.hkx'):
            part['skeleton'] = member
        elif animation_id(member) is not None:
            part['clips'][animation_id(member)] = member
    return part


def choose_clip(body, part, tae, character='', players=None):
    """The ID of the part clip that plays with the character clip body, and why; None when there is none.

    The same ID comes first. Then a character TAE ID that plays the body clip's
    HKX, preferring the part's own animation category (Wolf's a076_412000 plays
    a070_412000, and the umbrella has a076_412000_1). Last, the rest pose.
    players is players_of(tae), for a caller that pairs many clips with one TAE.
    """
    chosen = choose_entry(body, part, tae, character, players)
    return chosen[:2] if chosen else None


def choose_entry(body, part, tae, character='', players=None):
    """choose_clip() with the character TAE ID that the pairing plays: (part clip ID, reason, TAE ID or None).

    The TAE ID is the body clip's own unless another ID of the character's TAE
    pairs the clip; the rest pose names none.
    """
    clips, own = part['clips'], part['tae']

    def found(ident):
        hkx = played_hkx(own, ident)
        return hkx if hkx in clips else None
    if body is not None:
        same = found(body)
        if same is not None:
            return same, 'same ID' if same == body else f'its TAE plays {clip_name(same)} for {clip_name(body)}', body
        categories = Counter(ident // 1_000_000 for ident in clips if ident != REST)
        category = categories.most_common(1)[0][0] if categories else None
        players = sorted((ident for ident in (players_of(tae) if players is None else players).get(body, ()) if ident != body),
                         key=lambda ident: (ident // 1_000_000 != category, ident))
        label = f'TAE of {character.upper()}' if character else 'the character TAE'
        for ident in players:
            hkx = found(ident)
            if hkx is not None:
                return hkx, f'{label}: {clip_name(ident)} plays {clip_name(body)}', ident
    if REST in clips:
        return REST, 'rest pose, no clip for this ID', None
    return None


def pairings(part, bodies, tae, character='', players=None):
    """The character clips that each clip of a part plays with: {part clip ID: [(body ID, reason)]}.

    choose_clip() asked for every body clip ID, so that importing a listed body
    clip keys the part clip it is listed under. The rest pose is left out: it
    plays with every body clip that the part has no clip for.
    """
    players = players_of(tae) if players is None else players
    result = {}
    for body in sorted(set(bodies)):
        chosen = choose_clip(body, part, tae, character, players)
        if chosen is not None and chosen[0] != REST:
            result.setdefault(chosen[0], []).append((body, chosen[1]))
    return result


def plan(models, clip, tae, character=''):
    """Which clip each animated weapon model of the chosen part files plays with a character clip.

    models are part binder or FLVER paths; clip is the character clip's file name.
    Rows name the model, its animation binder, the chosen member, the reason and
    the character TAE ID that plays it (entry, None for the rest pose).
    """
    body, rows, players = animation_id(clip), [], players_of(tae)
    for path in models:
        # Only weapon part binders hold animated models; outfit binders are not read for this.
        if not WEAPON.match(Path(path).name) or not Path(path).is_file():
            continue
        for model, part in part_binders(path).items():
            if not WEAPON.fullmatch(model):
                continue
            chosen = choose_entry(body, part, tae, character, players)
            if chosen is None:
                continue
            ident, reason, entry = chosen
            rows.append(dict(model=model, name=model.upper(), source=str(path), binder=part['binder'],
                             member=part['clips'][ident], id=clip_name(ident), reason=reason, rest=ident == REST, entry=entry))
    return rows


def prepare(manifest_path, rows, decode, work, game='sekiro'):
    """Decode each planned part clip and record it with its model in the character manifest.

    decode(clip, compendium, skeleton, output_json) runs the HKX decoder on
    extracted files; '-' stands for no compendium. A model that holds its rest
    pose keeps the static rig: its a999_000000 clip is shared by every animation
    without a clip of its own, so it is neither keyed nor exported. A model whose
    clip moves bones its FLVER lacks keeps its rest pose too. Returns report rows
    and notices.
    """
    import json
    import numpy as np
    from dcx_codec import unwrap
    from game_profiles import havok_info
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    report, notices = [], []
    for row in rows:
        model = next((m for m in manifest['models'] if m['name'] == row['model'] and m.get('attachment')
                      and Path(m['source']).resolve() == Path(row['source']).resolve()), None)
        if model is None:
            continue
        if row['rest']:
            report.append(dict(model=row['name'], clip=row['member'], binder=row['binder'], reason=row['reason'], rest=True))
            print(f"Part clip: {row['name']} holds its rest pose ({row['member']}), it has no clip for this animation", flush=True)
            continue
        part = part_binders(row['source'])[row['model']]
        if not part['skeleton']:
            notices.append(f"{row['name']}: {part['binder']} has no skeleton, so the part keeps its rest pose.")
            continue
        folder = Path(work) / row['model']
        folder.mkdir(parents=True, exist_ok=True)
        files = {}
        for key in ('skeleton', 'compendium', 'member'):
            member = part[key] if key != 'member' else row['member']
            if member:
                files[key] = folder / member
                files[key].write_bytes(unwrap(part['members'][member])[0])
        output = folder / (Path(row['member']).stem + '.json')
        compendium = files.get('compendium', '-')
        decode(files['member'], compendium, files['skeleton'], output)
        motion = json.loads(output.read_text(encoding='utf-8-sig'))
        info = havok_info(files['member'].read_bytes(), str(files['member']))
        info['game'] = game
        with np.load(model['data'], allow_pickle=False) as preview:
            flver_bones = {str(name) for name in preview['bone_names']}
        missing = [name for name in motion['trackNames'] if name not in flver_bones]
        if missing:
            notices.append(f"{row['name']}: {row['member']} moves bones that its model lacks ({', '.join(missing[:6])}), "
                           "so the part keeps its rest pose.")
            continue
        motion.update(game=game, sourceHavok=info, clip=row['member'],
                      part=dict(model=row['model'], binder=row['binder'], id=row['id'], reason=row['reason']))
        output.write_text(json.dumps(motion), encoding='utf-8')
        model['animation'] = dict(motion=str(output.resolve()), clip=row['member'], binder=row['binder'], id=row['id'],
                                  reason=row['reason'], frames=int(motion['frameCount']), frameRate=float(motion['frameRate']))
        report.append(dict(model=row['name'], clip=row['member'], binder=row['binder'], reason=row['reason'],
                           frames=int(motion['frameCount']), frameRate=float(motion['frameRate'])))
        print(f"Part clip: {row['name']} plays {row['member']} ({row['reason']}), "
              f"{motion['frameCount']} frames at {float(motion['frameRate']):g} fps", flush=True)
    Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return report, notices


def location_slot(name):
    """The slot of event 715 that places a weapon model such as wp_a_0760_1, else None."""
    match = re.match(r'wp_[a-z]_(\d{4,6})', name, re.I)
    if not match:
        return None
    ident = int(match[1])
    return 1 if 700 <= ident < 800 else LOCATION_SLOTS.get(ident)


def location_changes(events, slot, index, default):
    """Where events put model index of a slot: [[time s, dummy], ...] from 0 s, each held until the next; -1 hides it.

    Outside the events the model keeps default; where events overlap, the later one in the TAE holds.
    """
    ours = [(start, end, dummies[index] if index < 4 else default) for start, end, kind, dummies in events
            if kind == slot and end > start]
    result = []
    for time in sorted({0.0, *(max(t, 0.0) for start, end, _ in ours for t in (start, end))}):
        dummy = next((d for start, end, d in reversed(ours) if start <= time < end), default)
        if not result or result[-1][1] != dummy:
            result.append([round(time, 6), dummy])
    return result


def describe_changes(changes, sockets):
    return ', '.join(('hidden' if dummy < 0 else f"dummy {dummy}" + (f" ({sockets[str(dummy)]['bone']})" if str(dummy) in sockets else ''))
                     + f' from {time:.2f} s' for time, dummy in changes)


def locate(manifest_path, rows, clip, events, game='sekiro'):
    """Record in the character manifest where event 715 puts each weapon model while the character clip plays.

    events is character_locations() of the character's TAE. A model follows the
    TAE ID that its part clip pairs with, else the one that the import's animated
    parts play, else the clip's own ID. Only models placed automatically follow
    the events. A prosthetic tool's models after the first have no dummy of their
    own (WepAbsorpPosParam 7000-7900 gives them -1), so outside the events they are
    hidden. Each model that moves gets attachment['locations']: the TAE ID, the
    changes from location_changes() and the attachment of every other dummy they
    name. Returns report rows and notices.
    """
    import json
    body = animation_id(clip)
    if game != 'sekiro' or not events or body is None:
        return [], []
    from weapon_assets import attachment, read_reference
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    entries = {(row['model'], str(Path(row['source']).resolve())): row['entry'] for row in rows if row.get('entry') is not None}
    played = next(iter(entries.values()), body)
    reference, report, notices = None, [], []
    for model in manifest['models']:
        place = model.get('attachment')
        slot = location_slot(model['name'])
        if not place or place.get('kind') != 'dummy' or place.get('placement', 'auto') != 'auto' or slot is None:
            continue
        index, own = int(place.get('modelIndex', 0)), int(place['dummy'])
        entry = entries.get((model['name'], str(Path(model['source']).resolve())), played)
        changes = location_changes(events.get(entry, ()), slot, index, -1 if slot == 1 and index > 0 else own)
        if changes == [[0.0, own]]:
            continue
        sockets = {}
        try:
            for _, dummy in changes:
                if dummy >= 0 and dummy != own and str(dummy) not in sockets:
                    reference = reference or read_reference(manifest['attachment_reference'])
                    found = attachment(reference, dummy, manifest['attachment_reference'], game)
                    sockets[str(dummy)] = dict(dummy=dummy, bone=found['bone'], matrix=found['matrix'])
        except ValueError as exc:
            notices.append(f"{model['name'].upper()}: {clip_name(entry)} moves it to another dummy, but {exc} It stays on dummy {own}.")
            continue
        place['locations'] = dict(entry=clip_name(entry), changes=changes, sockets=sockets)
        report.append(dict(model=model['name'].upper(), entry=clip_name(entry), changes=changes))
        print(f"Weapon place: {model['name'].upper()} follows event 715 of {clip_name(entry)}: "
              f"{describe_changes(changes, dict(sockets, **{str(own): dict(bone=place['bone'])}))}", flush=True)
    Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return report, notices
