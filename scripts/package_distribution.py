"""Build a portable archive and a reviewed source staging area, excluding user media."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from synclab.version import VERSION,WINDOWS_ASSET,REPOSITORY

PUBLIC_README=(ROOT/'docs/PUBLIC_README.md').read_text(encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--app',required=True)
    args=parser.parse_args();app=Path(args.app).resolve()
    if not (app/'SyncLab.exe').is_file():raise ValueError('Build the app first')
    output=ROOT/'publish'/VERSION;source=output/'source';source.mkdir(parents=True,exist_ok=True)
    allow=[ROOT/'run_synclab.py',ROOT/'SyncLab.spec',ROOT/'requirements.txt',ROOT/'pytest.ini']
    allow+=sorted((ROOT/'synclab').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    allow+=sorted((ROOT/'synclab/assets').glob('*.png'))+sorted((ROOT/'synclab/assets').glob('*.ico'))+sorted((ROOT/'synclab/assets').glob('*.icns'))
    allow+=[ROOT/p for p in ['scripts/package_distribution.py','scripts/package_macos.py','scripts/ci_fixture.py','scripts/ci_smoke.py','scripts/MacInstaller.swift','.github/workflows/packages.yml','docs/PUBLIC_CHANGES.md','docs/PUBLIC_README.md','licenses/LGPL-3.0.txt','licenses/GPL-3.0.txt']]
    for file in allow:
        dest=source/file.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,dest)
    (source/'README.md').write_text(PUBLIC_README,encoding='utf-8')
    (source/'.gitignore').write_text('.venv/\n__pycache__/\n.pytest_cache/\nbuild/\ndist/\nvalidation/\nrecordings/\npublish/\n',encoding='utf-8')
    (source/'COPYRIGHT.txt').write_text('SyncLab\nCopyright (c) 2026 Contentrium.\nThird-party components retain their respective licenses.\n',encoding='utf-8')
    licenses=app/'LICENSES';licenses.mkdir(exist_ok=True)
    for name in ['av','numpy','scipy','PySide6-Essentials','PySide6-Addons','shiboken6','certifi']:
        d=metadata.distribution(name)
        for path in d.files or []:
            lower=str(path).lower()
            if any(token in lower for token in ['license','copying','copyright']) and not str(path).endswith(('.pyc','.py')):
                original=Path(d.locate_file(path))
                if original.is_file():
                    target=licenses/name/str(path);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,licenses/'Python.txt')
    for filename,url in [('LGPL-3.0.txt','https://www.gnu.org/licenses/lgpl-3.0.txt'),('GPL-3.0.txt','https://www.gnu.org/licenses/gpl-3.0.txt')]:
        target=licenses/filename
        if (ROOT/'licenses'/filename).is_file():shutil.copyfile(ROOT/'licenses'/filename,target)
        if not target.is_file():
            with urlopen(url,timeout=20) as response:target.write_bytes(response.read())
    import av
    runtime={'python':sys.version.split()[0],'FFmpeg':av.ffmpeg_version_info,
             'packages':{n:metadata.version(n) for n in ['av','numpy','scipy','PySide6-Essentials','PySide6-Addons','shiboken6']}}
    (licenses/'runtime-versions.json').write_text(json.dumps(runtime,indent=2),encoding='utf-8')
    notices='''# Third-party components

SyncLab bundles separate shared libraries. They retain their own licenses.
The application source is available in the accompanying source archive/repository.

- Python: https://www.python.org/ ; PSF license.
- NumPy: https://numpy.org/ ; BSD and bundled dependency notices.
- SciPy: https://scipy.org/ ; BSD and bundled dependency notices.
- PyAV: https://github.com/PyAV-Org/PyAV ; BSD-3-Clause.
- FFmpeg shared libraries: https://ffmpeg.org/ ; this wheel reports LGPL v3 or later.
  Exact upstream version is recorded in LICENSES/runtime-versions.json.
  Source archives: https://ffmpeg.org/releases/ ; build scripts: https://github.com/PyAV-Org/pyav-ffmpeg
- Qt for Python / PySide6 / Shiboken: https://code.qt.io/pyside/pyside-setup.git/ ;
  LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only as stated by the installed wheel metadata.
  Licensing documentation: https://doc.qt.io/qtforpython-6/licenses.html
- PyInstaller bootloader: https://pyinstaller.org/ ; GPL with distribution exception.

Full available license notices are collected in LICENSES, including LGPLv3 and GPLv3.
The certifi CA certificate bundle retains the Mozilla Public License 2.0; https://github.com/certifi/python-certifi .
Qt and FFmpeg libraries remain separate DLLs under _internal and can be replaced with
compatible modified builds. No source media, user projects, or analysis cache is bundled.
'''
    for folder in [source,app]:
        (folder/'THIRD_PARTY.md').write_text(notices,encoding='utf-8')
    (app/'README.md').write_text(PUBLIC_README,encoding='utf-8')
    shutil.copyfile(source/'COPYRIGHT.txt',app/'COPYRIGHT.txt')
    zip_path=output/WINDOWS_ASSET
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(app.rglob('*')):
            if p.is_file():z.write(p,str(Path('SyncLab')/p.relative_to(app)))
    source_zip=output/f'SyncLab-{VERSION}-source.zip'
    with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(source.rglob('*')):
            if p.is_file() and '.git' not in p.relative_to(source).parts:z.write(p,str(Path(f'SyncLab-{VERSION}')/p.relative_to(source)))
    sums=[]
    for p in [zip_path,source_zip]:
        with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        sums.append(digest+'  '+p.name)
    (output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='ascii')
    (output/'publish-manifest.json').write_text(json.dumps({'version':VERSION,'repository':REPOSITORY,'title':f'SyncLab {VERSION}',
        'assets':[str(p) for p in [zip_path,source_zip,output/'SHA256SUMS.txt']],
        'source_files':[str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and '.git' not in p.parts]},indent=2),encoding='utf-8')
    print(output,flush=True)


if __name__=='__main__':main()
