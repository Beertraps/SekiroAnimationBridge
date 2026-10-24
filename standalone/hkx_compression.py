"""Isolated spline compression with the correct Havok 2010 packfile version header."""
from pathlib import Path
import subprocess
import tempfile
from soulstruct.dcx import DCXType
from soulstruct.havok.types import hk2010
from soulstruct.havok.fromsoft.darksouls1ptde import AnimationHKX as AnimationHKX2010
from soulstruct.havok.utilities.files import SOULSTRUCT_HAVOK_PATH

# CompressAnim's rotation quantization argument (Havok RotationQuantization).
# POLAR32 (0), THREECOMP24 (3) and STRAIGHT16 (4) are omitted: neither
# Soulstruct nor the bridge's SoulsAssetPipeline decoder reads them back
# correctly, so their output could not be checked or imported again.
QUANTIZATION = {'threecomp40': 1, 'threecomp48': 2, 'uncompressed': 5}
DEFAULT_QUANTIZATION, DEFAULT_TOLERANCE = 'threecomp40', 0.001


def prepare_2010(animation):
    converted = animation if animation.HAVOK_MODULE.name == 'hk2010' else animation.to_2010_hkx()
    # Soulstruct Havok 1.5.0 leaves a 2016 tagfile version in this 2010 packfile header.
    # The 2010 compression utility crashes when it tries to load that mismatch.
    converted.hk_version = hk2010.VERSION
    converted.packfile_header_info.contents_version_string = hk2010.VERSION
    return converted


def compress_spline(animation, quantization=DEFAULT_QUANTIZATION, tolerance=DEFAULT_TOLERANCE):
    if not animation.animation_container.is_interleaved:
        raise ValueError('Spline compression requires interleaved source transforms.')
    if quantization not in QUANTIZATION:
        raise ValueError(f'Rotation quantization must be one of: {", ".join(QUANTIZATION)}.')
    tolerance=float(tolerance)
    if not 1e-6 <= tolerance <= 0.1:
        raise ValueError('Spline rotation tolerance must be between 0.000001 and 0.1.')
    with tempfile.TemporaryDirectory(prefix='SekiroSpline-') as directory:
        folder=Path(directory)
        source, target = folder/'interleaved2010.hkx', folder/'spline2010.hkx'
        source.write_bytes(prepare_2010(animation).to_bytes())
        utility=SOULSTRUCT_HAVOK_PATH('havok/resources/CompressAnim.exe')
        result=subprocess.run([str(utility),str(source),str(target),str(QUANTIZATION[quantization]),f'{tolerance:g}'],cwd=folder,
            capture_output=True,text=True,encoding='utf-8',errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not target.is_file():
            detail=(result.stdout+'\n'+result.stderr).strip()
            raise RuntimeError(f'Spline compressor failed (0x{result.returncode & 0xffffffff:08X}). {detail}')
        packed=AnimationHKX2010.from_path(target)
        spline=packed if animation.HAVOK_MODULE.name == 'hk2010' else type(animation).from_2010_hkx(packed,dcx_type=DCXType.Null)
        spline.hsh_overrides=animation.hsh_overrides.copy()
        for index, track_animation in enumerate(spline.animation_container.hkx_container.animations):
            spline.animation_container.hkx_container.bindings[index].animation=track_animation
            track_animation.type=5 if animation.HAVOK_MODULE.name == 'hk2010' else 3
        return spline
