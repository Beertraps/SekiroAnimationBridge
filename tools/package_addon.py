"""Build the optional Blender add-on without game data or local preferences."""
from pathlib import Path
import ast,hashlib,re,zipfile
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'blender_addon/sekiro_retarget'
VERSION='.'.join(str(part) for part in ast.literal_eval(
    re.search(r"'version': (\([^)]*\))",(SOURCE/'__init__.py').read_text(encoding='utf-8')).group(1)))
OUTPUT=ROOT/f'SekiroRetargetAssistant-{VERSION}.zip'
FILES=['__init__.py','mapping.py','retarget.py','export.py','README.md']


def package():
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in FILES:
            archive.write(SOURCE/name,Path('sekiro_retarget')/name)
    print(str(OUTPUT))
    print(f'{OUTPUT.stat().st_size:,} bytes; SHA256 '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__=='__main__':
    package()
