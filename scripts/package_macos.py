"""Build native macOS packages and the small latest-version bootstrap installer."""
from importlib import metadata
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from synclab.version import VERSION
from synclab.platforms import distribution_asset
from synclab.updates import UpdateInfo, install_update, find_installed_update, check_executable


def archive_app(bundle,output):
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for directory,dirs,files in os.walk(bundle,followlinks=False):
            for name in dirs+files:
                p=Path(directory)/name
                if p.is_symlink():
                    entry=zipfile.ZipInfo(str(p.relative_to(bundle.parent)).replace(os.sep,'/'))
                    entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
                    z.writestr(entry,os.readlink(p).encode('utf-8'))
                elif p.is_file():z.write(p,str(p.relative_to(bundle.parent)))


def licenses_for(bundle):
    dest=bundle/'Contents/Resources/LICENSES';dest.mkdir(parents=True,exist_ok=True)
    for name in ['av','numpy','scipy','PySide6-Essentials','PySide6-Addons','shiboken6','certifi']:
        distribution=metadata.distribution(name)
        for item in distribution.files or []:
            if any(key in str(item).lower() for key in ['license','copyright','copying']) and not str(item).endswith(('.py','.pyc')):
                source=Path(distribution.locate_file(item))
                if source.is_file():
                    target=dest/name/Path(*[p for p in item.parts if p not in {'.','..'}])
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,dest/'Python.txt')
    for name in ['LGPL-3.0.txt','GPL-3.0.txt']:
        shutil.copyfile(ROOT/'licenses'/name,dest/name)
    for name in ['README.md','THIRD_PARTY.md','COPYRIGHT.txt']:
        source=ROOT/name
        if source.is_file():shutil.copyfile(source,bundle/'Contents/Resources'/name)


def main():
    assert sys.platform=='darwin','macOS runner required'
    parser=argparse.ArgumentParser();parser.add_argument('--app',required=True);args=parser.parse_args()
    bundle=Path(args.app).resolve();output=ROOT/'publish'/VERSION;output.mkdir(parents=True,exist_ok=True)
    assert (bundle/'Contents/MacOS/SyncLab').is_file()
    licenses_for(bundle)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(bundle)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(bundle)],check=True)
    package=output/distribution_asset();archive_app(bundle,package)
    with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    info=UpdateInfo(VERSION,'https://github.com/contentriumkorea/synclab/releases/download/v'+VERSION+'/'+package.name,
                    package.stat().st_size,digest,'Native verification')
    with tempfile.TemporaryDirectory(prefix='synclab-updater-check-') as folder:
        installed=install_update(info,root=folder,opener=lambda *a,**kw:package.open('rb'))
        assert find_installed_update('0.0.0',root=folder)==installed
        check_executable(installed)
        subprocess.run(['codesign','--verify','--deep','--strict',str(installed.parents[2])],check=True)
    cpu='arm64' if platform.machine()=='arm64' else 'x64'
    installer=ROOT/'build'/('installer-'+cpu)/'SyncLab 설치.app'
    macos=installer/'Contents/MacOS';macos.mkdir(parents=True,exist_ok=True)
    resources=installer/'Contents/Resources';resources.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'synclab/assets/app-icon.icns',resources/'app-icon.icns')
    with (installer/'Contents/Info.plist').open('wb') as f:
        plistlib.dump({'CFBundleIdentifier':'com.contentrium.synclab.installer','CFBundleName':'SyncLab 설치',
            'CFBundleExecutable':'SyncLabInstaller','CFBundlePackageType':'APPL','CFBundleVersion':'1',
            'CFBundleShortVersionString':'1.0','CFBundleIconFile':'app-icon.icns',
            'LSMinimumSystemVersion':'15.0','NSHighResolutionCapable':True},f)
    executable=macos/'SyncLabInstaller'
    subprocess.run(['swiftc','-O','-swift-version','5',str(ROOT/'scripts/MacInstaller.swift'),'-o',str(executable),
                    '-target',platform.machine()+'-apple-macosx15.0','-framework','AppKit','-framework','CryptoKit'],check=True)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(installer)],check=True)
    digest=hashlib.file_digest(package.open('rb'),'sha256').hexdigest()
    with tempfile.TemporaryDirectory(prefix='synclab-installer-check-') as folder:
        bad=subprocess.run([str(executable),'--verify-install',str(package),'0'*64,VERSION,str(Path(folder)/'SyncLab.app')],capture_output=True,timeout=60)
        assert bad.returncode!=0 and not (Path(folder)/'SyncLab.app').exists()
        subprocess.run([str(executable),'--verify-install',str(package),digest,VERSION,str(Path(folder)/'SyncLab.app')],check=True,timeout=180)
        subprocess.run([str(executable),'--verify-install',str(package),digest,VERSION,str(Path(folder)/'SyncLab.app')],check=True,timeout=180)
    assert not Path(folder).exists()
    dmg=output/f'SyncLab-Install-macOS-{cpu}.dmg'
    subprocess.run(['hdiutil','create','-volname','SyncLab 설치','-srcfolder',str(installer.parent),
                    '-ov','-format','UDZO',str(dmg)],check=True)
    with (output/f'SHA256SUMS-macOS-{cpu}.txt').open('w',encoding='ascii') as f:
        for path in [package,dmg]:
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            f.write(digest+'  '+path.name+'\n')
    (ROOT/'validation'/f'macOS-{cpu}-package.json').write_text(json.dumps({'success':True,'version':VERSION,
        'platform':platform.platform(),'architecture':platform.machine(),'installer_bytes':dmg.stat().st_size,
        'app_bytes':package.stat().st_size,'codesign':'ad-hoc; not notarized','installer_verified':True,
        'updater_verified':True,'bad_digest_rejected':True,'reinstall_verified':True,'temporary_install_removed':True}),encoding='utf-8')


if __name__=='__main__':main()
