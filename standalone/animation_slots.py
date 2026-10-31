"""Register an animation ID that export adds to an animation binder, so that the game can play it.

The game ignores a clip under a new ID until two more files know the ID:
- the character's TAE needs an entry of its own, with the events of the move (hit boxes, sounds, cancel windows).
  SekiroCharacterWriter's tae command copies the entry of a source clip (tools/SekiroCharacterWriter/Tae.cs).
- the character's behavior (chr/cXXXX.behbnd.dcx) needs a clip generator that plays it. The SDT HKB Duplicator by
  Ionian adds one with its variation operation (tools/setup_hkb_duplicator.cmd downloads it), on the behavior's XML
  from havok_xml. The bridge then writes what it added into the game's binary in place (patch_variations), since
  Sekiro crashes on a behavior that havok_xml.to_hkx rebuilds from XML.

A variation is another category of a move that the behavior already has. Each move's selector (a CMSG, such as
Attack3008_CMSG) holds one clip per category of the same number, such as a000_003008 and a100_003008, and plays the
clip of the character's current category; without one, the base clip. An enemy's category comes from animIdOffset in
NpcParam or SpEffectParam. So the new ID keeps the source clip's number and changes its category. A new number needs
a new state and AI that requests it, which this module does not write.

Every write is read back: the TAE entry plays its own HKX with the events it copied, and every other entry keeps its
events; the patched behavior keeps the game's bytes, reads back as the same object graph as the Duplicator's XML, and
its selector lists the new clip generator. Whether the game plays the clip is for a playtest to show.

Run as a script, `animation_slots.py variation JOB REPORT` drives the Duplicator in the Python that has lxml.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
APP = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SekiroAnimationBridge'
# The Duplicator commit that the bridge was tested with; tools/setup_hkb_duplicator.ps1 downloads it.
DUPLICATOR_COMMIT = '560426d59d2296f92200ba1ac996aefb5f9f924e'
NAME = re.compile(r'a(\d{3})_(\d{6})(?:\.hkx)?', re.I)
CHARACTER = re.compile(r'c\d{4}', re.I)
CATEGORY_TAE = re.compile(r'a(\d{2,3})\.tae', re.I)
CLIP_GENERATOR = 'hkbClipGenerator'
SELECTOR = 'CustomManualSelectorGenerator'


# Tools ---------------------------------------------------------------------------------------------------------------

def duplicator_root(explicit=''):
    """The Duplicator's folder (the one holding src/behavior.py): explicit, SEKIRO_HKB_DUPLICATOR, or where
    setup_hkb_duplicator.cmd puts it. None when it is missing."""
    for value in (explicit, os.environ.get('SEKIRO_HKB_DUPLICATOR', ''), str(APP / 'tools/SDT-HKB-Duplicator')):
        if value and all((Path(value) / 'src' / name).is_file() for name in ('behavior.py', 'project.py')):
            return Path(value).resolve()
    return None


def duplicator_commit(root):
    marker = Path(root) / 'bridge-commit.txt'
    return marker.read_text(encoding='ascii').strip() if marker.is_file() else ''


def duplicator_status(python, explicit=''):
    """(ready, detail) of the Duplicator and of lxml in the conversion Python, for bridge_cli env and the UI."""
    root = duplicator_root(explicit)
    if root is None:
        return False, 'Not found. Run tools\\setup_hkb_duplicator.cmd to register new animation IDs in a behavior.'
    commit = duplicator_commit(root)
    try:
        found = subprocess.run([str(python), '-E', '-c', 'import lxml'], capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        found = False
    if not found:
        return False, f'{root} · the conversion Python has no lxml: run tools\\setup_writer.cmd again.'
    tested = 'tested commit' if commit == DUPLICATOR_COMMIT else f"commit {commit[:7] or 'unknown'}, not the tested {DUPLICATOR_COMMIT[:7]}"
    return True, f'{root} · {tested}'


# Names and IDs -------------------------------------------------------------------------------------------------------

def parse(name):
    """(category, number) of a clip name such as a100_003008 or a100_003008.hkx, else None."""
    match = NAME.fullmatch(PureWindowsPath(str(name or '')).name)
    return (int(match[1]), int(match[2])) if match else None


def clip_name(category, number):
    return f'a{category:03d}_{number:06d}'


def tae_members(binder):
    """(member index, path, category or None) of each TAE in an animation binder. The player's TAE has a file per
    category (a050.tae holds a050 IDs by number); an enemy's has one (c1010.tae, by full ID)."""
    for index, (_, path, _) in enumerate(binder.members):
        name = PureWindowsPath(path).name
        if name.lower().endswith('.tae'):
            match = CATEGORY_TAE.fullmatch(name)
            yield index, path, int(match[1]) if match else None


def tae_for(members, category):
    """The TAE member that holds IDs of a category, and how it numbers them."""
    whole = [member for member in members if member[2] is None]
    if whole:
        return whole[0]
    return next((member for member in members if member[2] == category), None)


def local_id(member, category, number):
    return number if member[2] is not None else category * 1_000_000 + number


# TAE readback, independent of SoulsFormats --------------------------------------------------------------------------

def tae_events(data, ident):
    """(start s, end s, event type) of each event of a TAE entry, in file order; None without the entry."""
    import struct
    from part_animations import tae_entries
    for found, offset in tae_entries(data):
        if found != ident:
            continue
        events, = struct.unpack_from('<q', data, offset)
        count, = struct.unpack_from('<i', data, offset + 0x20)
        rows = []
        for index in range(count):
            start, end, block = struct.unpack_from('<qqq', data, events + 24 * index)
            rows.append((struct.unpack_from('<f', data, start)[0], struct.unpack_from('<f', data, end)[0],
                         struct.unpack_from('<i', data, block)[0]))
        return rows
    return None


def tae_kinds(data):
    """How each entry of a TAE gets its HKX: ('own', ID), ('hkx', ID whose HKX it plays) or ('other', ID of the entry it
    imports). The entry's file header is (type, offset of [name offset, fields]); an imported ID is the first field."""
    import struct
    from part_animations import tae_entries
    result = {}
    for ident, offset in tae_entries(data):
        file_offset, = struct.unpack_from('<q', data, offset + 24)
        reference, data_offset = struct.unpack_from('<qq', data, file_offset)
        if reference:
            result[ident] = ('other', struct.unpack_from('<i', data, data_offset + 8)[0])
        else:
            imports, source = data[data_offset + 9], struct.unpack_from('<i', data, data_offset + 12)[0]
            result[ident] = ('hkx', source) if imports and source >= 0 else ('own', ident)
    return result


def check_tae(before, source, after, ident, events_from):
    """Readback of a rewritten TAE: the entry plays its own HKX with the copied events; every other entry keeps its
    events and how it gets its HKX. Returns a sentence; raises when it differs."""
    kinds_before, kinds_after = tae_kinds(before), tae_kinds(after)
    if kinds_after.get(ident) != ('own', ident):
        raise RuntimeError(f'The rewritten TAE entry {ident} does not play its own HKX: {kinds_after.get(ident)}.')
    expected = tae_events(source, events_from)
    if tae_events(after, ident) != expected:
        raise RuntimeError(f'The rewritten TAE entry {ident} does not have the events of {events_from}.')
    others = [key for key in kinds_before if key != ident]
    if sorted(others) != sorted(key for key in kinds_after if key != ident):
        raise RuntimeError('The rewritten TAE does not have the same other entries.')
    changed = [key for key in others if kinds_before[key] != kinds_after[key] or tae_events(before, key) != tae_events(after, key)]
    if changed:
        raise RuntimeError(f'The rewritten TAE changed {len(changed)} other entries, such as {changed[0]}.')
    return f'entry {ident} plays its own HKX with {len(expected)} events; the other {len(others)} entries are unchanged'


# Behavior XML ----------------------------------------------------------------------------------------------------------

def behavior_index(text):
    """Clip generators, selectors and animation paths of a behavior's XML, read with the standard library."""
    root = ET.fromstring(text)
    types = {t.get('id'): t.find('name').get('value') for t in root.findall('type')}
    objects = {o.get('id'): o for o in root.findall('object')}

    def value(obj, name):
        field = obj.find(f"record/field[@name='{name}']")
        if field is None or not len(field):
            return None
        return field[0].get('id') if field[0].tag == 'pointer' else field[0].get('value')

    clips = {oid: dict(name=value(o, 'name'), animation=value(o, 'animationName'), internalId=value(o, 'animationInternalId'))
             for oid, o in objects.items() if types.get(o.get('typeid')) == CLIP_GENERATOR}
    selectors = {}
    for oid, o in objects.items():
        if types.get(o.get('typeid')) == SELECTOR:
            array = o.find("record/field[@name='generators']/array")
            selectors[oid] = dict(name=value(o, 'name'), generators=[p.get('id') for p in (array if array is not None else [])])
    paths = []
    for o in objects.values():
        array = o.find("record/field[@name='animationNames']/array")
        if array is not None:
            paths += [s.get('value') for s in array]
    return dict(clips=clips, selectors=selectors, paths=paths)


def selectors_playing(index, animation):
    """Names of the selectors that hold a clip generator of an animation."""
    wanted = {oid for oid, clip in index['clips'].items() if (clip['animation'] or '').lower() == animation.lower()}
    return sorted(s['name'] for s in index['selectors'].values() if wanted & set(s['generators']))


# Plan and prepare ------------------------------------------------------------------------------------------------------

def plan(binder_path, member, base, source, scene_clip, duplicator=''):
    """What registering member needs, checked before anything is written. None when the binder already holds a clip
    of that name, since its TAE entry and behavior are the game's.

    source names the clip to copy, such as a000_003008; the scene's own clip by default."""
    from binder_members import Binder, plan_member
    from dcx_codec import protect_output, unwrap
    binder_path = Path(binder_path)
    read_from = binder_path if binder_path.is_file() else Path(base)
    anibnd = Binder(unwrap(read_from.read_bytes())[0])
    if plan_member(anibnd, member)[0] is not None:
        return None
    new = parse(member)
    given = source or scene_clip
    old = parse(given)
    if new is None:
        raise ValueError(f'Name the new clip like the game\'s clips, aXXX_YYYYYY.hkx: {member}')
    if old is None:
        raise ValueError('Name the source clip whose TAE entry and behavior the new ID copies, such as '
                         f'{clip_name(0, new[1])}' + (f'; the scene\'s clip {given} is not one.' if given else
                                                      '; the scene does not record its clip.'))
    if old[1] != new[1] or old == new:
        raise ValueError(f'{clip_name(*new)} cannot be a variation of {clip_name(*old)}. A variation keeps the number of its '
                         f'source and changes the category, such as {clip_name(100 if old[0] != 100 else 200, old[1])}. '
                         'A new number needs a new state in the behavior and AI that requests it, which the bridge does not '
                         'write. Choose a source clip with the same number.')
    match = CHARACTER.match(binder_path.name) or CHARACTER.match(Path(base or '').name)
    if not match:
        raise ValueError(f'The character ID is not in the binder\'s name, {binder_path.name}, such as c1010.anibnd.dcx.')
    character = match[0].lower()
    tae = plan_tae(anibnd, binder_path, read_from, base, character, old, new)
    behavior_write = binder_path.parent / f'{character}.behbnd.dcx'
    candidates = [behavior_write] + [Path(folder) / f'{character}.behbnd.dcx' for folder in
                                     (Path(base).parent if base else None, Path(tae['read']).parent) if folder]
    behavior_read = next((path for path in candidates if path.is_file()), None)
    if behavior_read is None:
        raise ValueError(f'No {character}.behbnd.dcx was found beside the binder or the archive the clip came from, so the '
                         'behavior cannot get the new clip.')
    protect_output(behavior_write)
    root = duplicator_root(duplicator)
    if root is None:
        raise ValueError('The SDT HKB Duplicator was not found. Run tools\\setup_hkb_duplicator.cmd once, then export again.')
    return dict(member=member, clip=clip_name(*new), source=clip_name(*old), character=character, tae=tae,
                behavior=dict(read=str(behavior_read), write=str(behavior_write)), duplicator=str(root))


def plan_tae(anibnd, binder_path, read_from, base, character, old, new):
    """Where the TAE entry is read and written: in the chosen binder, or in the character's base binder beside it
    (c0000.anibnd.dcx for the player's c0000_a10x.anibnd.dcx)."""
    from binder_members import Binder
    from dcx_codec import protect_output, unwrap
    holder, write, read = anibnd, binder_path, read_from
    if not any(tae_members(anibnd)):
        write = binder_path.parent / f'{character}.anibnd.dcx'
        read = write if write.is_file() else Path(base).parent / f'{character}.anibnd.dcx' if base else write
        if not read.is_file():
            raise ValueError(f'{binder_path.name} holds no TAE, and no {character}.anibnd.dcx with the TAE is beside it or '
                             'beside the archive the clip came from.')
        protect_output(write)
        holder = Binder(unwrap(read.read_bytes())[0])
    members = list(tae_members(holder))
    target, source = tae_for(members, new[0]), tae_for(members, old[0])
    if target is None:
        raise ValueError(f'{read.name} has no TAE for category a{new[0]:03d} (a{new[0]:02d}.tae). The bridge adds entries to '
                         'existing TAE files and does not start one.')
    if source is None:
        raise ValueError(f'{read.name} has no TAE for category a{old[0]:03d}, the source clip\'s.')
    source_id = local_id(source, *old)
    if tae_events(unwrap(holder.members[source[0]][2])[0], source_id) is None:
        raise ValueError(f'The TAE has no entry for the source clip {clip_name(*old)}, so there are no events to copy.')
    return dict(read=str(read), write=str(write), shared=write == binder_path, member=target[1], sourceMember=source[1],
                id=local_id(target, *new), sourceId=source_id)


def prepare(plan, temp, python, progress=lambda message: None):
    """The new TAE member and behavior binder as bytes, read back; nothing is written outside temp."""
    temp = Path(temp)
    temp.mkdir(parents=True, exist_ok=True)
    progress(f"Copying the TAE entry of {plan['source']} to {plan['clip']}")
    tae = prepare_tae(plan, temp / 'tae')
    progress(f"Adding {plan['clip']} to the behavior with the SDT HKB Duplicator")
    behavior = prepare_behavior(plan, temp / 'behavior', python)
    return dict(plan=plan, tae=tae, behavior=behavior)


def member_bytes(binder, path):
    """(inner bytes, DCX type) of a binder member; TAE members may be DCX compressed of their own."""
    from dcx_codec import unwrap
    data = next(data for _, name, data in binder.members if name == path)
    return unwrap(data)


def packed(data, kind):
    from soulstruct.dcx import DCXType, compress
    return data if kind == DCXType.Null else compress(data, kind)


def prepare_tae(plan, folder):
    """Run SekiroCharacterWriter tae on the TAE, then read it back here. data is None when the entry was right already."""
    from binder_members import Binder
    from character_export import run_writer
    from dcx_codec import unwrap
    tae = plan['tae']
    holder = Binder(unwrap(Path(tae['read']).read_bytes())[0])
    before, kind = member_bytes(holder, tae['member'])
    source = member_bytes(holder, tae['sourceMember'])[0]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'target.tae').write_bytes(before)
    (folder / 'source.tae').write_bytes(source)
    try:
        report = run_writer('tae', dict(target=str(folder / 'target.tae'), source=str(folder / 'source.tae'), id=tae['id'],
                                        sourceId=tae['sourceId'], output=str(folder / 'written.tae')), folder)
    except RuntimeError as error:
        if 'Unknown command tae' in str(error):
            raise RuntimeError('This SekiroCharacterWriter.exe is older than 0.3.0 and cannot write TAE entries. Run '
                               'tools\\SekiroMotionDecoder\\build_decoder.cmd once, then export again.') from None
        raise
    result = dict(member=tae['member'], binder=tae['write'], id=tae['id'], kind=report['kind'],
                  eventsFrom=report['eventsFrom'], identicalLayout=report['unchangedIdentical'], data=None, readback='')
    if report['changed']:
        after = (folder / 'written.tae').read_bytes()
        result['readback'] = check_tae(before, source if report['kind'] == 'added' else before, after, tae['id'],
                                       report['eventsFrom'])
        result['data'] = packed(after, kind)
    return result


def variation_names(index, animation, new):
    """The selectors that need the new clip, each with the name of a source clip generator in it and a free name for
    the new one, such as a100_003008_hkx_AutoSet_00 beside a000_003008_hkx_AutoSet_00."""
    taken = {clip['name'] for clip in index['clips'].values()}
    jobs, present = [], []
    for selector in index['selectors'].values():
        held = [index['clips'][g] for g in selector['generators'] if g in index['clips']]
        sources = [clip for clip in held if (clip['animation'] or '').lower() == animation.lower()]
        if not sources:
            continue
        if any((clip['animation'] or '').lower() == new.lower() for clip in held):
            present.append(selector['name'])
            continue
        name = re.sub(re.escape(animation), new, sources[0]['name'], count=1, flags=re.I)
        if name == sources[0]['name']:
            name = f'{new}_hkx_AutoSet_00'
        stem, number = (re.fullmatch(r'(.*?)(\d+)', name).groups() if re.fullmatch(r'.*?\d+', name) else (name + '_', '0'))
        count = int(number)
        while name in taken:
            count += 1
            name = f'{stem}{count:0{len(number)}d}'
        taken.add(name)
        jobs.append(dict(selector=selector['name'], sourceClip=sources[0]['name'], clipName=name))
    return jobs, present


def prepare_behavior(plan, folder, python):
    """Add the new clip to every selector that holds the source clip, in every behavior file that has one. data is None
    when every such selector holds the new clip already."""
    import havok_xml
    from binder_members import Binder
    from dcx_codec import unwrap
    folder.mkdir(parents=True, exist_ok=True)
    raw, kind = unwrap(Path(plan['behavior']['read']).read_bytes())
    behbnd = Binder(raw)
    tagfiles = [(index, path, data) for index, (_, path, data) in enumerate(behbnd.members)
                if path.lower().endswith('.hkx') and havok_xml.is_tagfile(data)]
    files = []
    for index, path, data in tagfiles:
        text = havok_xml.to_xml(data)
        found = behavior_index(text)
        if not selectors_playing(found, plan['source']):
            continue
        jobs, present = variation_names(found, plan['source'], plan['clip'])
        entry = dict(member=path, added=[], present=present, log=[])
        files.append(entry)
        if not jobs:
            continue
        xml = folder / f'behavior{index}.xml'
        xml.write_text(text, encoding='utf-8')
        job, answer = folder / f'variation{index}.json', folder / f'variation{index}.report.json'
        job.write_text(json.dumps(dict(duplicator=plan['duplicator'], xml=str(xml), animation=plan['clip'], jobs=jobs),
                                  indent=1), encoding='utf-8')
        result = subprocess.run([str(python), '-E', '-X', 'utf8', str(Path(__file__)), 'variation', str(job), str(answer)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f'exit code {result.returncode}'
            raise RuntimeError(f'The SDT HKB Duplicator could not add {plan["clip"]}: {detail}')
        entry['log'] = json.loads(answer.read_text(encoding='utf-8'))['log']
        edited = xml.read_text(encoding='utf-8')
        patched = patch_variations(data, text, edited, jobs)
        reread = check_patched(data, patched, edited, PureWindowsPath(path).name)
        entry['added'] = check_variations(behavior_index(reread), plan, jobs)
        behbnd.members[index][2] = patched
    if not files:
        raise ValueError(f"No selector in {Path(plan['behavior']['read']).name} plays {plan['source']}, so {plan['clip']} "
                         'cannot be a variation of it. Choose a source clip that the behavior plays.')
    data = None
    if any(entry['added'] for entry in files):
        written = behbnd.to_bytes()
        if [m[2] for m in Binder(written).members] != [m[2] for m in behbnd.members]:
            raise RuntimeError('The rewritten behavior binder does not read back with its members.')
        data = packed(written, kind)
        if unwrap(data)[0] != written:
            raise RuntimeError('The DCX readback of the rewritten behavior binder differs.')
    return dict(binder=plan['behavior']['write'], read=plan['behavior']['read'], files=files, data=data)


def patch_variations(data, original, edited, jobs):
    """The behavior tagfile with what the Duplicator added to its XML, written into the game's binary in place.

    Sekiro crashed on a behavior that havok_xml.to_hkx rebuilt from its XML with nothing changed, while files patched
    in place load (the character export). So every byte of the game's file stays: each new clip generator is a copy of
    its source clip generator's data with the name, animation and animation index of the edited XML, its selector's
    generators move to new data with the new clip generator at the end, and new animation paths go at the end of the
    behavior's animationNames. The new data goes after the game's (havok_tagfile)."""
    import struct
    import havok_tagfile as hk
    before, after = behavior_index(original), behavior_index(edited)
    if after['paths'][:len(before['paths'])] != before['paths']:
        raise RuntimeError("The Duplicator changed the behavior's animation paths; the bridge can only add paths.")
    tag = hk.Tagfile(data)
    clips, selectors, names = {}, {}, []
    for value in tag.walk():
        if value.type.format != hk.CLASS or value.item < 1:
            continue
        if value.type.name == CLIP_GENERATOR:
            fields = tag.class_fields(value)
            clips.setdefault(tag.text(fields['name'].at), []).append((tag.item_at(value.item), fields))
        elif value.type.name == SELECTOR:
            fields = tag.class_fields(value)
            selectors.setdefault(tag.text(fields['name'].at), []).append(fields['generators'])
        elif {'eventNames', 'animationNames'} <= {f.name for f in value.type.fields}:
            names.append(tag.class_fields(value)['animationNames'])
    if len(names) != 1:
        raise RuntimeError(f'The behavior has {len(names)} string data objects with animationNames, not one.')
    paths, path_slots = tag.array(names[0])
    if paths is None or not path_slots or len(path_slots) != len(before['paths']):
        raise RuntimeError("The behavior's animationNames do not match its XML.")

    def slot(index, size):
        return struct.pack('<I', index) + bytes(size - 4)

    like = tag.reference(path_slots[0])
    tag.append_elements(paths, [slot(tag.add_string(like, path), paths.type.size)
                                for path in after['paths'][len(before['paths']):]])
    for job in jobs:
        found = clips.get(job['sourceClip'], [])
        new = [clip for clip in after['clips'].values() if clip['name'] == job['clipName']]
        held = selectors.get(job['selector'], [])
        if len(found) != 1 or len(new) != 1 or len(held) != 1:
            raise RuntimeError(f"The behavior needs one clip generator {job['sourceClip']} and one selector "
                               f"{job['selector']}, and the Duplicator's XML one clip generator {job['clipName']}.")
        source, fields = found[0]
        start = tag.base + source.offset
        payload = bytearray(tag.item_bytes(source))
        for name, text in (('name', job['clipName']), ('animationName', new[0]['animation'])):
            struct.pack_into('<I', payload, fields[name].at - start, tag.add_string(tag.reference(fields[name].at), text))
        number = fields['animationInternalId']
        size = number.type.bits // 8
        payload[number.at - start:number.at - start + size] = int(new[0]['internalId']).to_bytes(
            size, 'little', signed=number.type.signed)
        clip = tag.copy_item(source, payload)
        generators, _ = tag.array(held[0])
        tag.append_elements(generators, [slot(clip, generators.type.size)])
    return tag.write()


def check_patched(data, patched, edited, name):
    """Readback of a behavior patched in place: the game's types and data are unchanged and its items keep their type,
    every slot that names an item is in the PTCH table, and the file reads back as the Duplicator's XML. Returns the
    XML of the patched file; raises when it differs."""
    import havok_tagfile as hk
    import havok_xml
    old, new = hk.Tagfile(data), hk.Tagfile(patched)
    kept = [s.tag for s in old.root.children if s.tag not in ('DATA', 'INDX')]
    if [data[s.start:s.end] for s in old.root.children if s.tag in kept] != \
            [patched[s.start:s.end] for s in new.root.children if s.tag in kept]:
        raise RuntimeError(f"The patched behavior {name} does not keep the game's {', '.join(kept)} sections.")
    size = old.data_section.end - old.base
    if patched[new.base:new.base + size] != data[old.base:old.data_section.end]:
        raise RuntimeError(f"The patched behavior {name} does not keep the game's data.")

    def kind(item):
        return item.type.index if item.type else 0, item.flags

    if any(kind(a) != kind(b) or ((a.offset, a.count) != (b.offset, b.count) and b.offset < size)
           for a, b in zip(old.items, new.items)):
        raise RuntimeError(f"The patched behavior {name} changed items of the game's file.")
    missing, extra = new.unpatched()
    if missing or extra:
        raise RuntimeError(f'The patched behavior {name} has {len(missing)} slots without a patch and {len(extra)} '
                           'patches that are not slots.')
    reread = havok_xml.to_xml(patched)
    difference = havok_xml.graph_difference(havok_xml.object_graph(edited), havok_xml.object_graph(reread))
    if difference:
        raise RuntimeError(f"The patched behavior {name} does not read back as the Duplicator's XML: {difference}.")
    return reread


def check_variations(index, plan, jobs):
    """Each new clip generator plays the new clip in its selector, and the animation list holds the clip's path."""
    if not any(PureWindowsPath(path).name.lower() == plan['clip'].lower() + '.hkx' for path in index['paths']):
        raise RuntimeError(f"The patched behavior does not list the animation {plan['clip']}.")
    added = []
    for job in jobs:
        selector = next((s for s in index['selectors'].values() if s['name'] == job['selector']), None)
        held = [index['clips'][g] for g in (selector or {}).get('generators', []) if g in index['clips']]
        if not any(clip['name'] == job['clipName'] and clip['animation'] == plan['clip'] for clip in held):
            raise RuntimeError(f"The patched behavior's {job['selector']} does not hold {job['clipName']}.")
        added.append(dict(selector=job['selector'], clipGenerator=job['clipName'], copiedFrom=job['sourceClip']))
    return added


# Write and check -------------------------------------------------------------------------------------------------------

def shared_replacement(prepared):
    """{TAE member path: bytes} for add_member, when the TAE is in the binder that gets the clip; else {}."""
    tae = prepared['tae']
    return {tae['member']: tae['data']} if tae['data'] is not None and prepared['plan']['tae']['shared'] else {}


def write(prepared, temp, copy):
    """Write the TAE binder (unless it is the clip's binder, which add_member writes) and the behavior binder, each kept
    as a .bak before its first change. copy(staged, target) replaces a file atomically. Returns the written paths."""
    from binder_members import Binder, backup
    from dcx_codec import unwrap
    plan, tae, behavior = prepared['plan'], prepared['tae'], prepared['behavior']
    files = []
    if tae['data'] is not None and not plan['tae']['shared']:
        raw, kind = unwrap(Path(plan['tae']['read']).read_bytes())
        holder = Binder(raw)
        next(member for member in holder.members if member[1] == tae['member'])[2] = tae['data']
        data = holder.to_bytes()
        if [member[2] for member in Binder(data).members] != [member[2] for member in holder.members]:
            raise RuntimeError('The rewritten TAE binder does not read back with its members.')
        files.append((packed(data, kind), Path(plan['tae']['write'])))
    elif tae['data'] is None and not plan['tae']['shared']:
        tae['binder'] = plan['tae']['read']
    if behavior['data'] is not None:
        files.append((behavior['data'], Path(behavior['binder'])))
    else:
        behavior['binder'] = behavior['read']
    written = []
    for number, (data, target) in enumerate(files):
        staged = Path(temp) / f'slot-{number}.dcx'
        staged.write_bytes(data)
        saved = backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy(staged, target)
        written.append(dict(path=str(target), backup=saved))
    return dict(written=written)


def report(prepared, checks):
    """The registration as the export report shows it, without the file bytes."""
    plan = prepared['plan']
    strip = lambda part: {key: value for key, value in part.items() if key != 'data'}
    return dict(clip=plan['clip'], source=plan['source'], character=plan['character'], tae=strip(prepared['tae']),
                behavior=strip(prepared['behavior']), checks=checks, passed=all(check['passed'] for check in checks))


def verify(prepared):
    """Read the written files back: the TAE entry, and the clip generators in the behavior. [{name, passed, detail}]."""
    import havok_xml
    from binder_members import Binder
    from dcx_codec import unwrap
    plan, checks = prepared['plan'], []
    tae = prepared['tae']
    anibnd = Binder(unwrap(Path(tae['binder']).read_bytes())[0])
    kind = tae_kinds(member_bytes(anibnd, tae['member'])[0]).get(tae['id'])
    checks.append(dict(name='TAE entry', passed=kind == ('own', tae['id']),
                       detail=f"{PureWindowsPath(tae['member']).name} in {Path(tae['binder']).name}: {plan['clip']} "
                              + ('plays its own HKX' if kind == ('own', tae['id']) else f'is {kind or "missing"}')))
    behavior = prepared['behavior']
    behbnd = Binder(unwrap(Path(behavior['binder']).read_bytes())[0])
    for entry in behavior['files']:
        index = behavior_index(havok_xml.to_xml(member_bytes(behbnd, entry['member'])[0]))
        playing = selectors_playing(index, plan['clip'])
        wanted = [row['selector'] for row in entry['added']] + entry['present']
        missing = [name for name in wanted if name not in playing]
        checks.append(dict(name='Behavior clip generator', passed=not missing,
                           detail=f"{PureWindowsPath(entry['member']).name} in {Path(behavior['binder']).name}: "
                                  + (f"{', '.join(wanted)} {'plays' if len(wanted) == 1 else 'play'} {plan['clip']}"
                                     if not missing else f"{', '.join(missing)} {'does' if len(missing) == 1 else 'do'} not "
                                                         f"play {plan['clip']}")))
    return checks


# The Duplicator, run in the Python that has lxml --------------------------------------------------------------------

def run_variations(job):
    """Apply the Duplicator's variation operation once per selector. Its Project.apply writes the XML in place and
    keeps a backup zip beside the project, both in the bridge's temporary folder."""
    sys.path.insert(0, str(Path(job['duplicator']) / 'src'))
    from behavior import Behavior
    from project import Project, Request
    xml = Path(job['xml'])
    project = Project.create(str(xml.with_suffix('.project.json')), 'bridge', behavior_xml=str(xml))
    log = []
    for row in job['jobs']:
        graph = Behavior(str(xml))
        chains = graph.find_chains(row['sourceClip'])
        index = next((i for i, chain in enumerate(chains) if chain.cmsg and graph.name_of(chain.cmsg) == row['selector']), None)
        if index is None:
            raise ValueError(f"{row['sourceClip']} is not directly inside {row['selector']}.")
        result = project.apply(Request(mode='variation', source_clip=row['sourceClip'], clip_name=row['clipName'],
                                       animation_name=job['animation'], chain_index=index))
        log += result.log
    return dict(log=log)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != 'variation':
        sys.exit('Usage: animation_slots.py variation JOB REPORT')
    task = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    Path(sys.argv[3]).write_text(json.dumps(run_variations(task)), encoding='utf-8')
