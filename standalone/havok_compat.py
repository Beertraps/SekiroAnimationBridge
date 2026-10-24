"""Workarounds for Soulstruct Havok 1.5.0 when writing and checking animations.

* Havok 2014 packfiles (Dark Souls III) end each section header with sixteen
  0xFF bytes, and their header declares that padding. Soulstruct's packer tests
  the version string without its 'hk_' prefix, so it never writes the padding.
  Game files and Soulstruct's own reader expect it. Soulstruct's Havok 2014
  types also follow Bloodborne, whose objects reuse base class padding. Dark
  Souls III PC files do not (reusePadding 0), so some animation members sit 4
  or 12 bytes later.
* Havok 2018 objects (Elden Ring) require property bags that the minimal
  interleaved builder leaves out. Soulstruct's 2010 -> 2018 converter, which
  spline output already uses, fills them in. Havok 2018 also tags strings as
  ConstCharArray, which the tagfile packer's item check does not accept,
  although its type layer handles both string tags. Its property bags refer
  to hkFlags<hkPropertyFlags::Enum, hkUint32>, which the packer would write
  under its Python class name without format flags; the game's compendiums
  describe it as a templated hkFlags type.
* Some Havok 2016 type names (Sekiro) resolve to submodules instead of
  classes, so reading a written tagfile back fails until they are restored.
  The spline reader also reads THREECOMP48 rotations with a single-value call.
"""
from __future__ import annotations

import importlib
import struct
import types

PACKFILE_MAGIC = bytes.fromhex('57e0e05710c0c010')
# Version 11 header plus its extension; section headers follow directly.
SECTIONS_START, SECTION_HEADER, SECTION_COUNT, SECTION_PADDING = 80, 48, 3, 16


def pad_packfile_sections(data: bytes) -> bytes:
    """Insert the section header padding a version 11 packfile declares but lacks."""
    if data[:8] != PACKFILE_MAGIC or len(data) < SECTIONS_START + SECTION_COUNT * SECTION_HEADER:
        return data
    order = '<' if data[17] == 1 else '>'
    version, = struct.unpack_from(order + 'I', data, 12)
    declared, = struct.unpack_from(order + 'h', data, 62)
    if version != 11 or declared != SECTION_PADDING:
        return data
    first_end = SECTIONS_START + SECTION_HEADER
    if data[first_end:first_end + SECTION_PADDING] == b'\xff' * SECTION_PADDING:
        return data  # Already written by a fixed Soulstruct version.
    # Section contents use offsets relative to their own start, so only each
    # absolute start moves when padding is inserted before all contents.
    shift = SECTION_COUNT * SECTION_PADDING
    result = bytearray(data[:SECTIONS_START])
    for index in range(SECTION_COUNT):
        offset = SECTIONS_START + index * SECTION_HEADER
        header = bytearray(data[offset:offset + SECTION_HEADER])
        absolute, = struct.unpack_from(order + 'I', header, 20)
        struct.pack_into(order + 'I', header, 20, absolute + shift)
        result += header + b'\xff' * SECTION_PADDING
    result += data[SECTIONS_START + SECTION_COUNT * SECTION_HEADER:]
    return bytes(result)


def use_ds3_layout():
    """Place Havok 2014 animation members at the offsets of Dark Souls III PC files."""
    from soulstruct.havok.types import hk2014
    animation, frame = hk2014.hkaAnimation, hk2014.hkaDefaultAnimatedReferenceFrame
    if getattr(animation, 'bridge_ds3_layout', False):
        return

    def relocate(cls, offsets, byte_size=None):
        cls.local_members = tuple(member._replace(offset=offsets[member.name])
                                  for member in cls.local_members if member.name in offsets)
        if byte_size: cls.byte_size = byte_size

    # hkReferencedObject fills 16 bytes, so these start after its padding.
    relocate(animation, dict(type=16, duration=20, numberOfTransformTracks=24, numberOfFloatTracks=28,
                             extractedMotion=32, annotationTracks=40))
    relocate(frame, dict(up=32, forward=48, duration=64, referenceFrameSamples=72), 88)
    for cls in (animation, hk2014.hkaInterleavedUncompressedAnimation, hk2014.hkaSplineCompressedAnimation,
                frame):
        cls.members = cls.__base__.members + cls.local_members
    animation.bridge_ds3_layout = True


def fix_hk2018_tagfiles():
    """Accept Havok 2018 strings in tagfile items and describe property flags as the game does."""
    from soulstruct.havok.enums import TagDataType
    from soulstruct.havok.tagfile.structs import TagFileItem
    from soulstruct.havok.types import hk2018
    from soulstruct.havok.types.hk import TemplateType
    original = TagFileItem.get_item_hk_data_type
    if getattr(original, 'bridge_fix', False):
        return

    def get_item_hk_data_type(self):
        if self.hk_type is not None and self.hk_type.get_tag_data_type() == TagDataType.ConstCharArray:
            return self.hk_type.get_data_type()
        return original(self)

    get_item_hk_data_type.bridge_fix = True
    TagFileItem.get_item_hk_data_type = get_item_hk_data_type

    flags = next(member.type for member in hk2018.hkPropertyDesc.local_members if member.name == 'flags')
    build_type_info = flags.get_type_info.__func__

    def get_type_info(cls, long_varints):
        info = build_type_info(cls, long_varints)
        info.parent_type_py_name = None  # The generated base class is not a Havok type.
        return info

    # Name, templates and format flags as in Elden Ring's type compendiums.
    flags.set_real_name('hkFlags')
    flags.set_tag_format_flags(41)
    flags.set_templates([TemplateType('tBITS', hk2018.hkPropertyFlagsEnum),
                         TemplateType('tSTORAGE', flags.local_members[0].type)])
    flags.get_type_hierarchy = classmethod(lambda cls: [cls])
    flags.get_type_info = classmethod(get_type_info)


def interleaved_animation(animation_class, frames, track_bone_indices, **options):
    """Build an uncompressed animation, routing Havok 2018 through the 2010 converter."""
    if animation_class.HAVOK_MODULE.name == 'hk2014':
        use_ds3_layout()
    if animation_class.HAVOK_MODULE.name != 'hk2018':
        return animation_class.from_minimal_data_interleaved(frames, track_bone_indices, **options)
    fix_hk2018_tagfiles()
    from soulstruct.dcx import DCXType
    from soulstruct.havok.fromsoft.darksouls1ptde import AnimationHKX as AnimationHKX2010
    source = AnimationHKX2010.from_minimal_data_interleaved(frames, track_bone_indices, **options)
    return animation_class.from_2010_hkx(source, dcx_type=DCXType.Null)


def readable(animation_class):
    """Prepare Soulstruct to read a written file back: restore shadowed classes and THREECOMP48 decoding."""
    module = importlib.import_module(f'soulstruct.havok.types.{animation_class.HAVOK_MODULE.name}')
    for name, value in list(vars(module).items()):
        if isinstance(value, types.ModuleType) and isinstance(getattr(value, name, None), type):
            setattr(module, name, getattr(value, name))
    from soulstruct.havok import spline_compression as spline
    original = spline.unpack_quantized_quaternion
    if not getattr(original, 'bridge_fix', False):
        def unpack_quantized_quaternion(reader, quantization):
            if quantization == spline.RotationQuantizationType.ThreeComp48:
                return spline.Quaternion.decode_ThreeComp48(*reader.unpack('3H'))
            return original(reader, quantization)

        unpack_quantized_quaternion.bridge_fix = True
        spline.unpack_quantized_quaternion = unpack_quantized_quaternion
    return animation_class
