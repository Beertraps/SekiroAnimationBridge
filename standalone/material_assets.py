"""Resolve MTD and MATBIN samplers by authored names, including FLVER overrides."""
from pathlib import Path, PureWindowsPath
import re


def mesh_mask(name):
    match = re.match(r'#(\d+)#', name or '')
    return match[1] if match else ''


def definition_key(path):
    return PureWindowsPath(path).stem.lower()


def sampler_kind(name):
    name = (name or '').lower()
    if 'albedo' in name or 'diffuse' in name: return 'albedo'
    if 'normalmap' in name or name in ('g_bumpmap', 'g_bump'): return 'normal'
    if 'emissive' in name or 'emission' in name: return 'emissive'
    return ''


def sampler_order(name):
    value = (name or '').lower()
    layer = re.search(r'(?:albedomap|normalmap|emissivemap)_(\d+)$', value)
    slot = re.search(r'texture2d_(\d+)_', value)
    return (int(layer[1]) if layer else 0, int(slot[1]) if slot else 0)


class MaterialLibrary:
    def __init__(self, path='', game=''):
        self.definitions, self.parsed = {}, {}
        self.has_matbin = False
        if not path: return
        from dcx_codec import unwrap
        from soulstruct.containers import Binder
        source = Path(path)
        if source.is_dir():
            # Keep loose definitions lazy: an extracted library may be large.
            entries = [(str(p), p) for p in sorted(source.rglob('*')) if p.is_file() and p.suffix.lower() in ('.mtd', '.matbin')]
        elif source.suffix.lower() in ('.mtd', '.matbin'):
            entries = [(source.name, unwrap(source.read_bytes())[0])]
        else:
            data = unwrap(source.read_bytes())[0]
            entries = [(e.path, e.data) for e in Binder.from_bytes(data).entries]
            # DS1/Remastered ships a small companion patch library. Its entries
            # replace the corresponding base definitions when both are supplied.
            if game in ('ds1', 'ds1r') and source.name.lower() in ('mtd.mtdbnd', 'mtd.mtdbnd.dcx'):
                for patch in sorted(source.parent.iterdir()):
                    if patch.name.lower() in ('mtdpatch.mtdbnd', 'mtdpatch.mtdbnd.dcx'):
                        entries.extend((e.path, e.data) for e in Binder.from_bytes(unwrap(patch.read_bytes())[0]).entries)
            if game == 'er' and source.name.lower() in ('allmaterial.matbinbnd', 'allmaterial.matbinbnd.dcx'):
                for extra in sorted(source.parent.iterdir()):
                    if re.fullmatch(r'allmaterial_dlc\d+\.matbinbnd(?:\.dcx)?', extra.name, re.I):
                        entries.extend((e.path, e.data) for e in Binder.from_bytes(unwrap(extra.read_bytes())[0]).entries)
        for name, raw in entries:
            suffix = PureWindowsPath(name).suffix.lower()
            if suffix not in ('.mtd', '.matbin'): continue
            from game_profiles import path_game
            identified = path_game(name)
            if identified and game not in ('auto', '', identified) and not (identified=='ds1' and game=='ds1r'):
                raise ValueError(f'Material library contains {identified} definitions, but the animation is from {game}. Select the material library from this game.')
            if game == 'er' and suffix == '.mtd': continue
            self.definitions[definition_key(name)] = (suffix, raw)
            self.has_matbin |= suffix == '.matbin'

    def get(self, path):
        key = definition_key(path)
        if key not in self.definitions: return None
        if key not in self.parsed:
            from dcx_codec import unwrap
            from soulstruct.base.models.mtd import MTD
            from soulstruct.base.models.matbin import MATBIN
            suffix, raw = self.definitions[key]
            if isinstance(raw, Path): raw=raw.read_bytes()
            self.parsed[key] = (MATBIN if suffix == '.matbin' else MTD).from_bytes(unwrap(raw)[0])
        return self.parsed[key]


def material_samplers(material, definition):
    """MATBIN may be the sole source of samplers; FLVER paths override it."""
    originals = {t.texture_type or '': t for t in material.textures}
    definitions = {s.sampler_type: s for s in definition.samplers} if definition else {}
    for name in sorted(originals.keys() | definitions.keys(), key=sampler_order):
        tex, sampler = originals.get(name), definitions.get(name)
        path = tex.path if tex and tex.path else ''
        uv, scale = 0, [1, 1]
        if sampler:
            path = path or getattr(sampler, 'sampler_path', getattr(sampler, 'path', ''))
            uv = max(0, int(getattr(sampler, 'uv_index', 1)) - 1)
            floats = getattr(sampler, 'unk_floats', [])
            if len(floats) >= 2: scale = list(floats[:2])
        if tex:
            # Preserve authored FLVER tiling as well as MTD tiling.
            factor = list(getattr(tex, 'scale', (1, 1)))
            scale = [scale[i] * factor[i] for i in range(2)]
        yield dict(semantic=name, texture=PureWindowsPath(path).stem, uv=uv, scale=scale)
