import hashlib
import io
import os
import json
import stat
import sys
import platform
import zipfile

import pytest

from synclab import updates


def mac_archive(unsafe_link=False):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,value,mode in [
            ('SyncLab.app/Contents/MacOS/SyncLab',b'mach-o-test',stat.S_IFREG|0o755),
            ('SyncLab.app/Contents/Info.plist',b'plist',stat.S_IFREG|0o644),
            ('SyncLab.app/Contents/Frameworks/QtCore',b'library',stat.S_IFREG|0o755),
            ('SyncLab.app/Contents/Resources/icon.icns',b'icon',stat.S_IFREG|0o644),
            ('SyncLab.app/Contents/Frameworks/Python',b'../Resources/icon.icns' if not unsafe_link else b'../../../../outside',stat.S_IFLNK|0o777),
        ]:
            entry=zipfile.ZipInfo(name);entry.create_system=3;entry.external_attr=mode<<16
            z.writestr(entry,value)
    return stream.getvalue()


def test_mac_download_selects_cpu_asset(monkeypatch):
    monkeypatch.setattr(sys,'platform','darwin')
    monkeypatch.setattr(platform,'machine',lambda:'arm64')
    data=mac_archive();digest=hashlib.sha256(data).hexdigest()
    def asset(name):
        return dict(name=name,size=len(data),digest='sha256:'+digest,
                    browser_download_url='https://github.com/contentriumkorea/synclab/releases/download/v1.1.0/'+name)
    payload=dict(tag_name='v1.1.0',assets=[asset('SyncLab-Windows-x64.zip'),asset('SyncLab-macOS-arm64.zip'),asset('SyncLab-macOS-x64.zip')])
    opener=lambda *a,**kw:io.BytesIO(json.dumps(payload).encode())
    assert updates.fetch_latest('1.0.3',opener=opener).url.endswith('SyncLab-macOS-arm64.zip')
    monkeypatch.setattr(platform,'machine',lambda:'x86_64')
    assert updates.fetch_latest('1.0.3',opener=opener).url.endswith('SyncLab-macOS-x64.zip')


@pytest.mark.skipif(os.name=='nt',reason='macOS bundle symlinks require POSIX; exercised on both Mac runners')
def test_mac_bundle_install_preserves_links_and_permissions(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'platform','darwin')
    data=mac_archive()
    info=updates.UpdateInfo('1.1.0','https://github.com/contentriumkorea/synclab/releases/download/v1.1.0/SyncLab-macOS-arm64.zip',len(data),hashlib.sha256(data).hexdigest(),'')
    checked=[]
    exe=updates.install_update(info,root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data),validator=lambda p:checked.append(p))
    assert exe.parts[-4:]==('SyncLab.app','Contents','MacOS','SyncLab')
    assert checked and exe.is_file()
    assert exe.stat().st_mode&0o111
    link=exe.parent.parent/'Frameworks/Python'
    assert link.is_symlink() and link.read_bytes()==b'icon'
    assert updates.find_installed_update('1.0.3',root=tmp_path)==exe
    assert not (exe.parent/'installed.json').exists()
    assert not (exe.parent.parent.parent/'installed.json').exists()


def test_mac_bundle_link_outside_bundle_never_activated(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'platform','darwin')
    data=mac_archive(True)
    info=updates.UpdateInfo('1.1.0','https://github.com/contentriumkorea/synclab/releases/download/v1.1.0/SyncLab-macOS-arm64.zip',len(data),hashlib.sha256(data).hexdigest(),'')
    with pytest.raises(ValueError):updates.install_update(info,root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data),validator=lambda p:None)
    assert not (tmp_path/'current.json').exists()


def test_mac_update_path_uses_application_support(monkeypatch):
    monkeypatch.setattr(sys,'platform','darwin')
    assert updates.update_root().parts[-4:]==('Library','Application Support','SyncLab','updates')
