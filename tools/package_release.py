"""Package source, launchers, docs and the add-on without game data or local settings.

A release build adds the prebuilt decoder (--decoder) and uv (--uv), so the bridge runs without build tools."""
from pathlib import Path
import argparse,hashlib,zipfile
from package_addon import OUTPUT as ADDON

ROOT=Path(__file__).resolve().parents[1]
TOP_FILES=['README.md','CHANGELOG.md','CREDITS.md','LICENSE','VERSION','requirements-writer.txt','Start Animation Bridge.cmd',ADDON.name]
SUFFIXES={'.py','.ps1','.cmd','.cs','.csproj','.html','.css','.js','.md','.txt'}
GAME_FILES={'.hkx','.flver','.tpf','.dcx','.blend','.anibnd','.chrbnd','.partsbnd','.texbnd','.mtdbnd','.matbinbnd'}
# Native binaries may only come from the decoder build and uv, never from the source tree.
BINARIES={'.dll','.exe'}
BINARY_FOLDERS=('decoder/','tools/uv/')
# SoulsAssetPipeline copies a Havok CompressAnim.exe next to the decoder for FBX import; decoding never uses it.
DECODER_SKIP=('SapResources/CompressAnim/',)


def members(decoder=None,uv=None):
    files={ROOT/name:name for name in TOP_FILES}
    for folder in ['standalone','tools','blender_addon','docs']:
        files.update((p,p.relative_to(ROOT).as_posix()) for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in SUFFIXES
                     and not any(part in {'__pycache__','bin','obj','.git'} for part in p.relative_to(ROOT).parts))
    if decoder:
        decoder=Path(decoder)
        if not (decoder/'SekiroMotionDecoder.exe').is_file(): raise ValueError(f'No SekiroMotionDecoder.exe in {decoder}')
        for p in decoder.rglob('*'):
            relative=p.relative_to(decoder).as_posix()
            if p.is_file() and not relative.startswith(DECODER_SKIP): files[p]='decoder/'+relative
    if uv:
        uv=Path(uv)
        if not (uv/'uv.exe').is_file(): raise ValueError(f'No uv.exe in {uv}')
        files.update((p,'tools/uv/'+p.name) for p in [uv/'uv.exe',*uv.glob('LICENSE*')])
    return files


def package(output,decoder=None,uv=None):
    files=members(decoder,uv)
    missing=[str(p) for p in files if not p.is_file()]
    if missing: raise ValueError('Missing release files: '+', '.join(missing))
    top=Path('SekiroAnimationBridge-'+(ROOT/'VERSION').read_text(encoding='utf-8').strip())
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for file,name in sorted(files.items(),key=lambda item:item[1]):
            archive.write(file,(top/name).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip(): raise RuntimeError('ZIP integrity check failed')
        names=[Path(n).relative_to(top).as_posix() for n in archive.namelist()]
        assert all(Path(n).suffix.lower() not in GAME_FILES for n in names)
        assert all(Path(n).suffix.lower() not in BINARIES or n.startswith(BINARY_FOLDERS) for n in names)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='ascii')
    print(f'{output}\n{len(files)} files; {output.stat().st_size:,} bytes\nSHA256 {digest}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--decoder',type=Path,help='decoder folder from build_decoder.cmd')
    parser.add_argument('--uv',type=Path,help='folder with uv.exe and its license')
    args=parser.parse_args()
    package(args.output,args.decoder,args.uv)
