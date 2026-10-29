"""Build a game package ZIP from a package folder and its built tools.

python tools/package_game_package.py <package folder> --output <zip> [--tool <id>=<built folder> ...]

The ZIP has one top folder named after the package ID. It holds every file of the package except caches, build
output and the package's tools/ folder; each --tool adds the files of a built tool to the folder of that tool's
path in package.json, such as tools/re-decoder/ for tools/re-decoder/ReEngineDecoder.exe."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,re,zipfile

REQUIRED=('id','name','version','apiVersion')
SKIP={'__pycache__','bin','obj','.git'}


def manifest(folder):
    """package.json of a package folder, with its required fields and ID checked."""
    data=json.loads((Path(folder)/'package.json').read_text(encoding='utf-8'))
    missing=[key for key in REQUIRED if key not in data]
    if missing: raise ValueError('package.json lacks '+', '.join(missing))
    if not isinstance(data['id'],str) or not re.fullmatch(r'[a-z][a-z0-9_]*',data['id']):
        raise ValueError(f'The package ID {data["id"]!r} must be lower case letters, digits and _, starting with a letter.')
    return data


def members(folder,tools=()):
    """{name in the ZIP: file} for a package folder and its built tools as (tool ID, built folder) pairs."""
    folder=Path(folder).resolve();data=manifest(folder);top=PurePosixPath(data['id'])
    files={}
    for p in folder.rglob('*'):
        relative=p.relative_to(folder)
        if p.is_file() and relative.parts[0]!='tools' and not SKIP.intersection(relative.parts):
            files[(top/relative.as_posix()).as_posix()]=p
    declared={tool.get('id'):tool for tool in data.get('tools',[])}
    for tool_id,built in tools:
        if tool_id not in declared: raise ValueError(f'package.json has no tool {tool_id!r}')
        path=PurePosixPath(str(declared[tool_id].get('path','')).replace('\\','/'))
        if not path.name or path.is_absolute() or '..' in path.parts or ':' in path.as_posix():
            raise ValueError(f'The path of tool {tool_id!r} must stay inside the package: {path}')
        built=Path(built)
        if not (built/path.name).is_file(): raise ValueError(f'No {path.name} in {built}')
        for p in built.rglob('*'):
            if not p.is_file(): continue
            name=(top/path.parent/p.relative_to(built).as_posix()).as_posix()
            if name in files: raise ValueError(f'{name} comes from two places: {files[name]} and {p}')
            files[name]=p
    return data,files


def package(folder,output,tools=()):
    data,files=members(folder,tools)
    output=Path(output).resolve()
    if output.is_relative_to(Path(folder).resolve()): raise ValueError('Write the ZIP outside the package folder.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in sorted(files):
            archive.write(files[name],name)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip(): raise RuntimeError('ZIP integrity check failed')
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    print(f'{output}\n{data["id"]} {data["version"]}: {len(files)} files; {output.stat().st_size:,} bytes\nSHA256 {digest}')
    return output


def tool_argument(text):
    tool_id,separator,folder=text.partition('=')
    if not separator or not tool_id or not folder: raise argparse.ArgumentTypeError(f'expected <id>=<built folder>, got {text!r}')
    return tool_id,Path(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('package',type=Path,help='package folder with package.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tool',type=tool_argument,action='append',default=[],metavar='ID=FOLDER',
                        help='a built tool: its ID in package.json and the folder its build wrote')
    args=parser.parse_args()
    package(args.package,args.output,args.tool)
