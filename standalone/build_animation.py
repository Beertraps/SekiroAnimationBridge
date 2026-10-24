"""Write sampled animation in its source game's native Havok version."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from soulstruct.dcx import DCXType
from game_profiles import animation_class, GAMES
from soulstruct.havok.utilities.maths.trs_transform import TRSTransform
from hkx_compression import QUANTIZATION, DEFAULT_QUANTIZATION, DEFAULT_TOLERANCE
from havok_compat import interleaved_animation, pad_packfile_sections, readable

# Readback differences above these limits are reported as visible.
ROTATION_WARNING_DEGREES, TRANSLATION_WARNING = 0.5, 0.005


def decoded_frames(animation) -> np.ndarray:
    """Local transforms of a written animation as a (frames, tracks, 10) array."""
    container = animation.animation_container
    if container.is_spline:
        container.load_spline_data()
        frames = container.spline_data.to_interleaved_transforms(
            container.hkx_animation.numFrames, container.hkx_animation.maxFramesPerBlock)
    else:
        container.load_interleaved_data()
        frames = container.interleaved_data
    return np.asarray([[transform.ravel() for transform in frame] for frame in frames], dtype=np.float64)


def compare(expected: np.ndarray, decoded: np.ndarray, track_names: list[str]) -> dict:
    """Largest rotation and translation differences between sampled and written transforms."""
    if decoded.shape != expected.shape:
        raise ValueError(f'Readback has {decoded.shape[0]} frames x {decoded.shape[1]} tracks; '
                         f'expected {expected.shape[0]} x {expected.shape[1]}.')
    dots = np.abs(np.sum(expected[..., 3:7] * decoded[..., 3:7], axis=-1))
    norms = np.linalg.norm(expected[..., 3:7], axis=-1) * np.linalg.norm(decoded[..., 3:7], axis=-1)
    angles = np.degrees(2 * np.arccos(np.clip(dots / np.maximum(norms, 1e-12), 0.0, 1.0)))
    distances = np.linalg.norm(expected[..., :3] - decoded[..., :3], axis=-1)
    frame, track = np.unravel_index(int(np.argmax(angles)), angles.shape)
    return dict(maxRotationDegrees=float(angles.max()), meanRotationDegrees=float(angles.mean()),
                maxTranslation=float(distances.max()), maxScale=float(np.abs(expected[..., 7:] - decoded[..., 7:]).max()),
                worstTrack=track_names[track], worstFrame=int(frame) + 1)


def build(input_json: Path, output_hkx: Path, output_format: str, game='auto', quantization=DEFAULT_QUANTIZATION,
          tolerance=DEFAULT_TOLERANCE, verify=False) -> dict:
    document = json.loads(input_json.read_text(encoding="utf-8"))
    if document.get("format") != "sekiro-animation-bridge" or document.get("formatVersion") != 1:
        raise ValueError("Unsupported JSON. Import and export it with Animation Bridge.")
    recorded = document.get('game', '')
    if game in ('auto', ''): game = recorded
    if not game:
        raise ValueError('This older scene has no source-game metadata. Select its source game in the UI (or CLI -Game), or import the original animation again with version 0.5.')
    if recorded and recorded != game:
        raise ValueError(f'This scene was imported from {GAMES.get(recorded, recorded)}. Export using its original game; retarget onto a scene imported from another game to change skeletons.')
    AnimationHKX = animation_class(game)

    frames_json = document["frames"]
    track_bone_indices = [int(index) for index in document["trackBoneIndices"]]
    track_names = [str(name) for name in document["trackNames"]]
    if not frames_json or len(track_bone_indices) != len(track_names):
        raise ValueError("The motion has no frames or its track map is incomplete.")
    if len(frames_json) < 2:
        raise ValueError("Havok animations need at least two frames. Widen the export frame range.")

    frames = [
        [
            TRSTransform(
                tuple(float(value) for value in track["translation"]),
                tuple(float(value) for value in track["rotation"]),
                tuple(float(value) for value in track["scale"]),
            )
            for track in frame
        ]
        for frame in frames_json
    ]
    if any(len(frame) != len(track_bone_indices) for frame in frames):
        raise ValueError("A frame does not have the same track count as the source motion.")

    root_samples = document.get("rootMotion")
    root_motion_array = None
    if root_samples is not None:
        if len(root_samples) != len(frames):
            raise ValueError("Root motion sample count does not match frame count.")
        root_motion_array = np.asarray(root_samples, dtype=np.float32)
        if root_motion_array.shape != (len(frames), 4):
            raise ValueError("Root motion must contain four values per frame.")

    animation = interleaved_animation(
        AnimationHKX,
        frames,
        track_bone_indices,
        root_motion_array=root_motion_array,
        original_skeleton_name=str(document["skeletonName"]),
        frame_rate=float(document["frameRate"]),
        track_names=track_names,
    )
    animation.dcx_type = DCXType.Null
    if output_format == "spline":
        from hkx_compression import compress_spline
        animation = compress_spline(animation, quantization, tolerance)
        animation.dcx_type = DCXType.Null

    # Retain native PC packfile layout; tagfile games keep their own SDK version.
    source_info = document.get('sourceHavok', {})
    if source_info.get('container') == 'packfile' and animation.packfile_header_info:
        header = animation.packfile_header_info
        header.pointer_size = source_info['pointerSize']
        header.is_little_endian = source_info['littleEndian']
        header.reuse_padding_optimization = source_info['reusePadding']
        header.flags = source_info['flags']

    data = pad_packfile_sections(animation.to_bytes())
    output_hkx.parent.mkdir(parents=True, exist_ok=True)
    output_hkx.write_bytes(data)
    detail = f'{quantization}, tolerance {float(tolerance):g}' if output_format == 'spline' else 'uncompressed'
    print(f"Wrote {GAMES[game]} / {animation.hk_version} {output_format} HKX ({detail}, {len(data):,} bytes): {output_hkx}")
    stats = dict(bytes=len(data), format=output_format, quantization=quantization if output_format == 'spline' else '',
                 tolerance=float(tolerance) if output_format == 'spline' else 0.0)
    if verify:
        started = time.perf_counter()
        expected = np.asarray([[[*t['translation'], *t['rotation'], *t['scale']] for t in frame] for frame in frames_json],
                              dtype=np.float64)
        written = readable(AnimationHKX).from_bytes(data)
        result = compare(expected, decoded_frames(written), track_names)
        if root_motion_array is not None:
            readback = np.asarray(written.animation_container.get_reference_frame_samples(), dtype=np.float64)
            result['maxRootMotion'] = float(np.abs(readback[:, :4] - root_motion_array).max())
        visible = result['maxRotationDegrees'] > ROTATION_WARNING_DEGREES or result['maxTranslation'] > TRANSLATION_WARNING
        print(f"Readback check ({time.perf_counter() - started:.1f} s): max rotation difference "
              f"{result['maxRotationDegrees']:.4f} deg (mean {result['meanRotationDegrees']:.4f}), max translation "
              f"{result['maxTranslation'] * 1000:.3f} mm"
              + (f", root motion {result['maxRootMotion'] * 1000:.3f} mm" if 'maxRootMotion' in result else '')
              + f"; worst track {result['worstTrack']} at frame {result['worstFrame']}.")
        if visible:
            print('NOTICE: The compression difference may be visible. Use a smaller spline tolerance, THREECOMP48 '
                  'quantization or interleaved output for this clip.')
        stats['readback'] = result
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("motion_json", type=Path, help="edited JSON exported by Sekiro Animation Bridge")
    parser.add_argument("output_hkx", type=Path, help="output .hkx path (raw tagfile, not DCX)")
    parser.add_argument('--game', choices=['auto', *GAMES], default='auto', help='Source game; automatic for scenes imported by version 0.5+')
    parser.add_argument(
        "--format", choices=("spline", "interleaved"), default="interleaved",
        help="HKX animation storage format (default: interleaved)",
    )
    parser.add_argument('--quantization', choices=list(QUANTIZATION), default=DEFAULT_QUANTIZATION,
                        help='Spline rotation quantization (default: threecomp40)')
    parser.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE,
                        help='Spline rotation tolerance; smaller is more precise and larger (default: 0.001)')
    parser.add_argument('--verify', action='store_true', help='Decode the written HKX again and report the difference')
    parser.add_argument('--stats-json', type=Path, help='Optional file receiving size and readback statistics')
    args = parser.parse_args()
    try:
        stats = build(args.motion_json, args.output_hkx, args.format, args.game, args.quantization, args.tolerance, args.verify)
        if args.stats_json:
            args.stats_json.write_text(json.dumps(stats, indent=2), encoding='utf-8')
    except Exception as ex:
        parser.exit(1, f"HKX export failed: {ex}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
