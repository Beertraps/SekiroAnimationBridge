"""Write a weapon's part clips into its part binder in a mod folder, and read such a folder back.

A weapon part binder, parts/wp_a_0760.partsbnd.dcx, holds an animation binder for
each animated model: WP_A_0760_1.anibnd animates WP_A_0760_1.flver and holds
skeleton_1.hkx, a compendium, often a TAE, and the clips, whose names end in the
model's suffix (a076_405010_1.hkx). Member IDs are 1000000000 + category * 1000000
+ number and ignore the suffix. Some weapons have a second part binder with smaller
models and the same animation binder, wp_a_0300_l.partsbnd.dcx: both are written,
so that neither plays the old clip. _m files are left as they are.

The game folder is only read. A part binder that the mod folder already holds is
read in its place, so that clips written one after another add up. A me3 profile
beside the mod folder loads it, as for a new character (character_export).

Nothing is known yet about whether the game plays a part clip for an ID that the
part's own TAE does not list (docs/PART_ANIMATIONS_PLAN.md, M2).
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath

ANIMATION_BINDER = re.compile(r'(wp_[a-z]_\d{4,6})(_\d+)?\.anibnd(?:\.dcx)?', re.I)


def copies(source):
    """The part binder and the _l copy beside it, when the game has one: wp_a_0300 and wp_a_0300_l."""
    source = Path(source)
    stem, rest = source.name.split('.', 1)
    other = stem[:-2] if stem.lower().endswith('_l') else stem + '_l'
    sibling = source.with_name(f'{other}.{rest}')
    return [source] + ([sibling] if sibling.is_file() else [])


def model_suffix(binder):
    """The suffix that the clips of an animation binder end in: '_1' for WP_A_0760_1.anibnd, '' for WP_A_0760.anibnd."""
    match = ANIMATION_BINDER.fullmatch(PureWindowsPath(binder).name)
    return (match[2] or '') if match else None


def find(binder, name):
    return next((m for m in binder.members if PureWindowsPath(m[1]).name.lower() == name.lower()), None)


def put_clips(data, clips):
    """Add each (member, HKX bytes) to an animation binder's bytes. Returns (new bytes, rows)."""
    from binder_members import Binder, PART_CLIP, put_member
    from character_export import pack
    from dcx_codec import unwrap
    raw, kind = unwrap(data)
    binder = Binder(raw)
    rows = []
    for member, hkx in clips:
        path, ident, replaced = put_member(binder, member, hkx, pattern=PART_CLIP)
        rows.append(dict(member=PureWindowsPath(path).name, id=ident, replaced=replaced))
    written = binder.to_bytes()
    check = Binder(written)
    if len(check.members) != len(binder.members) or any(find(check, member) is None or find(check, member)[2] != hkx
                                                        for member, hkx in clips):
        raise RuntimeError('A rewritten animation binder did not read back with its new clips.')
    return pack(written, kind), rows


def write(clips, mod):
    """Add part clips to their part binders in mod/parts, and to each binder's _l copy.

    clips are dicts of source (the game's part binder), binder (the animation binder
    member, WP_A_0760_1.anibnd), member (the clip's name, a000_003000_1.hkx) and data
    (its HKX bytes). Returns (a report per written part binder, notices).
    """
    from binder_members import Binder
    from character_export import pack, me3_profile
    from dcx_codec import protect_output, unwrap
    mod = Path(mod).resolve()
    grouped = {}
    for clip in clips:
        grouped.setdefault(str(Path(clip['source']).resolve()), []).append(clip)
    written, notices = [], []
    for source, group in grouped.items():
        for copy in copies(source):
            target = mod / 'parts' / copy.name
            protect_output(target)
            base = target if target.is_file() else copy
            raw, kind = unwrap(base.read_bytes())
            outer = Binder(raw)
            report = dict(file=str(target), base=str(base), clips=[])
            by_binder = {}
            for clip in group:
                by_binder.setdefault(clip['binder'], []).append((clip['member'], clip['data']))
            for name, members in by_binder.items():
                entry = find(outer, name)
                if entry is None:
                    notices.append(f"{copy.name} has no {name}, so {', '.join(m for m, _ in members)} is not in it.")
                    continue
                entry[2], rows = put_clips(entry[2], members)
                report['clips'] += [dict(binder=name, **row) for row in rows]
            if not report['clips']:
                continue
            data = outer.to_bytes()
            if [m[1] for m in Binder(data).members] != [m[1] for m in outer.members]:
                raise RuntimeError(f'{copy.name} did not read back with its members.')
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_name(target.name + '.tmp')
            staging.write_bytes(pack(data, kind))
            os.replace(staging, target)
            written.append(report)
    profile = str(me3_profile(mod, mod.name)) if written else ''
    return written, notices, profile


def check(name, passed, detail):
    return dict(name=name, passed=bool(passed), detail=detail)


def verify(mod, decode, work):
    """Read the part binders of a mod folder back.

    Each must read with its animation binders; each clip's name must end in its
    model's suffix and its ID follow the name; each clip must decode on its part
    skeleton; and a binder and its _l copy must hold the same clips. decode(clip,
    compendium, skeleton, output_json) runs the HKX decoder, with '-' for no
    compendium. Returns dict(checks, binders).
    """
    from binder_members import Binder, PART_CLIP, clip_id
    from dcx_codec import unwrap
    mod, work = Path(mod), Path(work)
    files = sorted((mod / 'parts').glob('wp_*.partsbnd.dcx'))
    checks, binders, decoded = [], [], {}
    if not files:
        return dict(checks=[check('part binders', False, f'{mod / "parts"} holds no wp_*.partsbnd.dcx')], binders=[])
    contents = {}
    for path in files:
        try:
            outer = Binder(unwrap(path.read_bytes())[0])
            animations = {PureWindowsPath(m[1]).name: Binder(unwrap(m[2])[0]) for m in outer.members
                          if ANIMATION_BINDER.fullmatch(PureWindowsPath(m[1]).name)}
        except Exception as error:  # noqa: BLE001 - any failure to read is the finding
            checks.append(check(f'{path.name} reads back', False, str(error)))
            continue
        checks.append(check(f'{path.name} reads back', animations, f'{len(animations)} animation binder(s)'))
        contents[path.name.lower()] = {name: {PureWindowsPath(m[1]).name: m[2] for m in inner.members}
                                       for name, inner in animations.items()}
        wrong, failed, count = [], [], 0
        for name, inner in animations.items():
            suffix = model_suffix(name)
            members = {PureWindowsPath(m[1]).name: m for m in inner.members}
            clips = {member: entry for member, entry in members.items() if PART_CLIP.fullmatch(member)}
            for member, entry in clips.items():
                stem = member.rsplit('.', 1)[0]
                if not re.fullmatch(r'a\d{3}_\d{6}' + re.escape(suffix), stem, re.I) or inner.member_id(entry) != clip_id(member, PART_CLIP):
                    wrong.append(f'{name}/{member}')
            skeleton = next((m for m in members if m.lower().startswith('skeleton') and m.lower().endswith('.hkx')), None)
            compendium = next((m for m in members if m.lower().endswith('.compendium')), None)
            if skeleton is None:
                failed.append(f'{name} has no skeleton')
                continue
            folder = work / path.name.split('.')[0] / name.split('.')[0]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / skeleton).write_bytes(unwrap(members[skeleton][2])[0])
            if compendium:
                (folder / compendium).write_bytes(unwrap(members[compendium][2])[0])
            for member, entry in clips.items():
                key = hashlib.sha1(skeleton.encode() + entry[2]).hexdigest()
                count += 1
                if key in decoded:
                    if decoded[key]:
                        failed.append(f'{name}/{member}: {decoded[key]}')
                    continue
                clip = folder / member
                clip.write_bytes(unwrap(entry[2])[0])
                output = folder / (clip.stem + '.json')
                try:
                    decode(clip, folder / compendium if compendium else '-', folder / skeleton, output)
                    motion = json.loads(output.read_text(encoding='utf-8-sig'))
                    bones = len(motion['skeleton']['bones'])
                    tracks = [int(i) for i in motion['trackBoneIndices']]
                    problem = ('no frames' if int(motion['frameCount']) < 1 else
                               'a track outside the skeleton' if any(i >= bones for i in tracks) else '')
                except Exception as error:  # noqa: BLE001 - a clip that does not decode is the finding
                    problem = str(error).splitlines()[0] if str(error) else type(error).__name__
                decoded[key] = problem
                if problem:
                    failed.append(f'{name}/{member}: {problem}')
        checks.append(check(f'{path.name} clip names', not wrong,
                            'each clip ends in its model\'s suffix and its ID follows its name' if not wrong
                            else 'wrong: ' + ', '.join(wrong[:8])))
        checks.append(check(f'{path.name} clips decode', not failed, f'{count} clip(s) decode on their part skeleton'
                            if not failed else '; '.join(failed[:6])))
        binders.append(dict(file=str(path), animationBinders=sorted(animations), clips=count))
    for name in sorted(contents):
        stem, rest = name.split('.', 1)
        if stem.endswith('_l') or f'{stem}_l.{rest}' not in contents:
            continue
        main, copy = contents[name], contents[f'{stem}_l.{rest}']
        differ = [f'{binder}/{member}' for binder in main.keys() & copy.keys()
                  for member in main[binder].keys() | copy[binder].keys()
                  if PART_CLIP.fullmatch(member) and main[binder].get(member) != copy[binder].get(member)]
        checks.append(check(f'{name} and its _l copy agree', not differ,
                            'both hold the same clips' if not differ else 'differ in ' + ', '.join(sorted(differ)[:8])))
    return dict(checks=checks, binders=binders)
