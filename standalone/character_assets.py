"""Discover modular characters and prepare self-contained Blender preview packages."""
from __future__ import annotations
import json
import re
from pathlib import Path, PureWindowsPath

ROLES = {"fc": "Head", "am": "Arms / prosthetic", "bd": "Torso", "lg": "Legs", "wp": "Weapon", "hd": "Headwear", "hr": "Hair"}
PRESETS = {
    "wolf": ["fc_m_0200", "am_m_9000", "bd_m_9000", "lg_m_9000"],
    "tutorial": ["fc_m_0200", "am_m_9010", "bd_m_9030", "lg_m_9000"],
    "mortal": ["fc_m_0200", "am_m_9000", "bd_m_9040", "lg_m_9000"],
}
IMAGE_EXTS = {".png", ".tga", ".dds", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def sampler_priority(texture):
    # Layer zero is the base surface; damage and expression overlays can precede it in the file.
    return 0 if (texture.texture_type or '').lower().endswith(('albedomap_0', 'normalmap_0')) else 1


def material_uses_alpha(params, mtd_name):
    alpha_ref = params.get('g_AlphaRef', [])
    if isinstance(alpha_ref, (int, float)):
        alpha_ref = [alpha_ref]
    # Fur cutouts can use blend mode zero with an authored alpha-test threshold.
    return int(params.get('g_BlendMode', 0)) not in (0, 32) or any(v > 0 for v in alpha_ref) or 'ao_hair' in mtd_name


def asset_id(path):
    return Path(str(path).replace("\\", "/")).name.lower().split(".")[0]


def texture_tokens(text):
    """Character and part IDs named by a model, material or texture: c5069, bd_m_9000."""
    return set(re.findall(r"c\d{4}|[a-z]{2}_[a-z]_\d{4}", str(text).lower()))


def texture_family(path):
    """c2190_h.texbnd and c2190_l.texbnd both belong to c2190."""
    return re.sub(r"_[hlm]$", "", asset_id(path))


def model_files(source):
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Character source not found: {path}")
    if path.is_file():
        return [path]
    if (path / "parts").is_dir():
        path = path / "parts"
    found = {}
    for p in sorted(path.rglob("*")):
        if not p.is_file() or any(x.lower() in {"skeleton_reference", "backup", "work", ".git"} for x in p.relative_to(path).parts[:-1]):
            continue
        name = p.name.lower()
        if not (name.endswith((".flver", ".flver.dcx", ".partsbnd.dcx", ".partsbnd", ".chrbnd.dcx", ".chrbnd"))):
            continue
        ident = asset_id(p)
        if ident.endswith(("_l", "_m")) or ident == "c0000":
            continue
        # Prefer a binder because it includes the part's TPF as well as its model.
        if ident not in found or "bnd" in name:
            found[ident] = p
    return list(found.values())


def find_materials(source, game='auto'):
    path = Path(source).resolve()
    base = path if path.is_dir() else path.parent
    for root in [base, *list(base.parents)[:3]]:
        matbin = ['allmaterial.matbinbnd.dcx', 'material/allmaterial.matbinbnd.dcx', 'materials/allmaterial.matbinbnd.dcx']
        mtd = ["allmaterialbnd.mtdbnd.dcx", "mtd/allmaterialbnd.mtdbnd.dcx", 'Mtd.mtdbnd.dcx', 'mtd/Mtd.mtdbnd.dcx', "materials/wolf.mtdbnd", "source/mtd/wolf.mtdbnd", "mtd/wolf.mtdbnd"]
        for relative in matbin if game == 'er' else mtd if game not in ('auto', '') else matbin + mtd:
            p = root / relative
            if p.is_file():
                return str(p)
    return ""


def scan_character(source, preset="auto", game='auto'):
    files = model_files(source)
    if preset not in {"auto", "npc", "player", *PRESETS}:
        raise ValueError("Choose Auto detect, NPC / custom character, or a Wolf outfit.")
    if preset == "auto":
        wolf_parts = {part for outfit in PRESETS.values() for part in outfit}
        preset = "wolf" if game in ('auto', 'sekiro') and any(asset_id(p) in wolf_parts for p in files) else 'player' if any(re.match(r'^(hd|fc|hr|am|bd|lg)_', asset_id(p)) for p in files) else "npc"
    if game not in ('auto', 'sekiro') and preset in PRESETS: preset = 'player'
    npc = preset == "npc"
    wanted = set(PRESETS.get(preset, []))
    parts = []
    for path in files:
        ident = asset_id(path)
        role = "Character" if re.fullmatch(r"c\d{4}", ident) else ROLES.get(ident.split("_")[0], "Extra model")
        parts.append(dict(id=ident, name=ident.upper(), role=role, path=str(path), selected=ident in wanted,
                          container="Binder + textures" if "bnd" in path.name.lower() else "FLVER"))
    if len(parts) == 1 and not parts[0]['id'].startswith('wp_'):
        parts[0]["selected"] = True
    if preset == 'player':
        from game_profiles import player_parts
        player_parts(parts)
    missing = [ident for ident in PRESETS.get(preset, []) if not any(p["id"] == ident for p in parts)]
    # Costume sets with no base Wolf names are selectable rather than silently substituted.
    return dict(parts=parts, missing=missing, materials=find_materials(source, game), count=len(parts),
                preset=preset, characterType='npc' if npc else 'player' if preset=='player' else 'wolf')


def prepare_character(sources, output_dir, texture_dir="", material_binder="", texture_override="",
                      reference_model="", weapon_attachments=None, skeleton_name='', game='sekiro', skeleton_bones=None,
                      texture_folders=None, texture_recursive=False):
    """texture_folders are a game's shared folders (chr, parts): only packages named
    after the models and their materials are read there, not every package."""
    from soulstruct.containers import Binder, TPF
    from soulstruct.flver import FLVER
    from material_assets import MaterialLibrary, material_samplers, sampler_kind
    from flver_geometry import extract_model
    from dcx_codec import unwrap

    def read_binder(path):
        return Binder.from_bytes(unwrap(Path(path).read_bytes())[0])

    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    texture_out = out / "textures"; texture_out.mkdir(exist_ok=True)
    warnings, models = [], []
    textures, images, texture_scores = {}, {}, {}
    tpfs_seen = set()
    def add_tpf(data, origin):
        if origin in tpfs_seen:
            return
        tpfs_seen.add(origin)
        tpf = TPF.from_bytes(unwrap(data)[0])
        for tex in tpf.textures:
            stem = tex.stem.lower()
            data = tex.data
            # Shared high/low TEXBNDs can contain the same names. Retain the
            # largest available image rather than whichever binder was read last.
            pixels = int.from_bytes(data[12:16], 'little') * int.from_bytes(data[16:20], 'little') if data[:4] == b'DDS ' else 0
            low = bool(re.search(r'_[lm](?:\.|:)', origin.lower()))
            score = (pixels, not low)
            if stem not in textures or score > texture_scores[stem]:
                textures[stem] = tex
                texture_scores[stem] = score

    sources = [Path(s).resolve() for s in sources]
    if not sources:
        raise ValueError("Select at least one character part, or switch to Rig only.")
    search_dirs = set()
    for source in sources:
        if not source.is_file():
            raise ValueError(f"Model file not found: {source}")
        if not texture_folders:
            search_dirs.add(source.parent)
        if source.name.lower().endswith((".flver", ".flver.dcx")):
            models.append((asset_id(source), FLVER.from_bytes(unwrap(source.read_bytes())[0]), str(source)))
        else:
            binder = read_binder(source)
            for entry in binder.entries:
                suffix = entry.path.lower()
                if suffix.endswith((".flver", ".flver.dcx")):
                    models.append((asset_id(entry.path), FLVER.from_bytes(unwrap(entry.data)[0]), str(source)))
                elif suffix.endswith((".tpf", ".tpf.dcx")):
                    add_tpf(entry.data, f"{source}:{entry.path}")
    if texture_dir:
        if not Path(texture_dir).is_dir():
            raise ValueError(f"Texture folder not found: {texture_dir}")
        search_dirs.add(Path(texture_dir))
    for root in list(search_dirs):
        # A loose extracted model directory may have sibling textures / materials folders.
        for candidate in [root / "textures", root.parent / "textures", root.parent / "source/parts"]:
            if candidate.is_dir():
                search_dirs.add(candidate)
    def read_package(p):
        low = p.name.lower()
        if p.suffix.lower() in IMAGE_EXTS:
            images[p.stem.lower()] = str(p.resolve())
        elif low.endswith((".tpf", ".tpf.dcx")):
            add_tpf(p.read_bytes(), str(p))
        elif low.endswith((".texbnd", ".texbnd.dcx")) or (low.endswith((".partsbnd", ".partsbnd.dcx")) and asset_id(p) in {name for name, _, _ in models}):
            for entry in read_binder(p).entries:
                if entry.path.lower().endswith((".tpf", ".tpf.dcx")):
                    add_tpf(entry.data, f"{p}:{entry.path}")
    for root in sorted(search_dirs):
        for p in root.rglob("*"):
            if p.is_file():
                read_package(p)
    if not material_binder:
        material_binder = next((m for s in sources if (m := find_materials(s, game))), "")
    if material_binder:
        p = Path(material_binder)
        if not p.exists():
            raise ValueError(f"Material library not found: {p}")
    library = MaterialLibrary(material_binder, game)
    if texture_folders:
        # Texture names stay exact; the IDs only choose which packages to open.
        needed, tokens = set(), set()
        for name, flver, _ in models:
            tokens |= texture_tokens(name)
            for mesh in flver.meshes:
                mtd_name = PureWindowsPath(mesh.material.mat_def_path).name.lower()
                tokens |= texture_tokens(mtd_name)
                for info in material_samplers(mesh.material, library.get(mtd_name)):
                    if info['texture'] and sampler_kind(info['semantic'].lower()):
                        needed.add(info['texture'].lower())
                        tokens |= texture_tokens(info['texture'])
        packages = []
        for folder in texture_folders:
            folder = Path(folder)
            if folder.is_dir():
                packages += [p for p in (folder.rglob("*") if texture_recursive else folder.iterdir())
                             if p.is_file() and p.name.lower().endswith((".texbnd", ".texbnd.dcx", ".tpf", ".tpf.dcx"))]
        chosen = [p for p in packages if texture_family(p) in tokens or "common" in p.name.lower()]
        for p in chosen:
            read_package(p)
        if needed - textures.keys() - images.keys():
            # Variants share a family prefix: Owl c5060's packages include c5061 and c5069.
            families = {t[:4] for t in tokens if re.fullmatch(r"c\d{4}", t)}
            extra = [p for p in packages if p not in chosen and re.fullmatch(r"c\d{4}", texture_family(p)) and texture_family(p)[:4] in families]
            for p in extra:
                read_package(p)
            chosen += extra
        print(f"Texture packages: read {len(chosen)} of {len(packages)} in the source's texture folders", flush=True)
    if game == 'er' and not library.has_matbin:
        warnings.append('Elden Ring material assignments need material/allmaterial.matbinbnd.dcx. The legacy allmaterialbnd.mtdbnd.dcx does not supply them. Add the MATBIN binder and rescan, or choose it under Textures & materials. Explicit FLVER overrides can still be read.')
    elif not material_binder:
        warnings.append("No MTD material library found. Only explicit FLVER texture references can be matched; missing materials will stay neutral.")

    converted = {}
    def resolve_image(stem, is_color):
        stem = stem.lower()
        if not stem:
            return None
        if stem in converted:
            return converted[stem]
        if stem in textures:
            texture = textures[stem]
            target = texture_out / f"{re.sub(r'[^a-zA-Z0-9_.-]', '_', stem)}.png"
            texture.export_png(target)
            # Most Sekiro albedo TPFs are linear UNORM. Preserve the DDS transfer function.
            data = texture.data
            dx10 = len(data) >= 132 and data[84:88] == b'DX10'
            srgb = dx10 and int.from_bytes(data[128:132], 'little') in {29, 72, 75, 78, 91, 93, 99}
            value = dict(path=str(target.resolve()), linear=bool(dx10 and not srgb), stem=stem)
        elif stem in images:
            value = dict(path=images[stem], linear=False, stem=stem)
        else:
            return None
        converted[stem] = value
        return value

    result = dict(version=4, game=game, models=[], warnings=warnings, material_library=material_binder)
    weapon_attachments = weapon_attachments or {}
    reference, reference_path = None, ''
    for index, (name, flver, origin) in enumerate(models):
        if not flver.meshes:
            warnings.append(f"Skipped {name}: skeleton-only FLVER has no visible mesh.")
            continue
        weapon_attachment = None
        from weapon_assets import weapon_id, reference_file, read_reference, describe_attachment, weapon_attachment as resolve_weapon_attachment
        from game_profiles import model_game
        identified = model_game(flver)
        if identified and identified != game:
            raise ValueError(f'{name}: model authoring paths identify {identified}, but the animation is from {game}. Select models from the same game.')
        if weapon_id(name) is not None:
            if reference is None:
                reference_path = reference_file(sources, texture_dir, reference_model)
                reference = read_reference(reference_path)
                result['attachment_reference'] = str(reference_path)
            match = re.fullmatch(r'(wp_[a-z]_\d{4,6})(?:_(\d+))?(?:_[lm])?', name)
            if not match:raise ValueError(f'Could not identify the weapon model index in {name}. Use a WP_A_XXXX[_N] FLVER member name.')
            base = match[1]; model_index = int(match[2] or 0)
            placement = weapon_attachments.get(f'{base}:{model_index}', weapon_attachments.get(base, 'auto'))
            weapon_attachment = resolve_weapon_attachment(reference,base,model_index,placement,game,reference_path,skeleton_bones,
                                                          [b.name for b in flver.bones])
            print(f"Weapon {name.upper()} ({placement}): {describe_attachment(weapon_attachment)}", flush=True)
            if weapon_attachment.get('notice'):
                warnings.append(weapon_attachment['notice'])
        data_path = out / f"{index:02d}_{name}.npz"
        stats = extract_model(flver, data_path, name)
        material_specs = []
        for mesh in flver.meshes:
            mat = mesh.material
            mtd_name = PureWindowsPath(mat.mat_def_path).name.lower()
            mtd = library.get(mtd_name)
            spec = dict(name=mat.name, mtd=mtd_name, albedo=None, normal=None, emissive=None, samplers=[])
            params = {p.name: p.value for p in mtd.params} if mtd else {}
            spec['alpha'] = material_uses_alpha(params, mtd_name)
            spec['color'] = list(params.get('g_DiffuseMapColor', (1, 1, 1)))
            for info in material_samplers(mat, mtd):
                stem = info['texture']
                semantic = info['semantic'].lower()
                target = sampler_kind(semantic)
                color = target in ('albedo', 'emissive')
                if not stem or not target:
                    continue
                available = stem.lower() in textures or stem.lower() in images
                info['found'] = available
                spec['samplers'].append(info)
                if available and spec[target] is None:
                    image = resolve_image(stem, color)
                    spec[target] = dict(**image, uv=info['uv'], scale=info['scale'])
                if available and 'ao_hair' in mtd_name and semantic.endswith('albedomap_1'):
                    spec['tint'] = dict(**resolve_image(stem, True), uv=info['uv'], scale=info['scale'])
            if texture_override:
                spec['albedo'] = dict(path=str(Path(texture_override).resolve()), linear=False, uv=0, scale=[1, 1], stem=Path(texture_override).stem)
            expects_albedo = any('albedo' in s['semantic'].lower() or 'diffuse' in s['semantic'].lower() for s in spec['samplers'])
            if not spec['albedo'] and (not mtd or expects_albedo):
                warnings.append(f"{name} / {mat.name}: no matching base-color image.")
            missing_textures = sorted({s['texture'] for s in spec['samplers'] if not s['found']})
            if missing_textures:
                warnings.append(f"{name} / {mat.name}: missing texture assets: {', '.join(missing_textures)}. Include the character’s TEXBND/TPF and any shared textures it references.")
            material_specs.append(spec)
        result['models'].append(dict(name=name, source=origin, data=str(data_path.resolve()),
                                     materials=material_specs, stats=stats, attachment=weapon_attachment))
    if not result['models']:
        raise ValueError("No visible models were found. Select the parts folder or FLVER files with mesh geometry.")
    result['texture_count'] = len(converted)
    result['warnings'] = list(dict.fromkeys(warnings))
    manifest = out / 'character.json'
    manifest.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"Character ready: {len(result['models'])} parts, {len(converted)} texture images, {len(result['warnings'])} notices", flush=True)
    for warning in result['warnings']:
        print(f"NOTICE: {warning}", flush=True)
    return manifest
