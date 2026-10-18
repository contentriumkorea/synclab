import hashlib
import io
import json
import zipfile
import sys
import platform
from pathlib import Path
import pytest

from synclab import updates


@pytest.fixture(autouse=True)
def windows_distribution(monkeypatch):
    # These fixtures exercise the existing Windows distribution on every CI host.
    monkeypatch.setattr(sys,'platform','win32')
    monkeypatch.setattr(platform,'machine',lambda:'AMD64')


def archive(entries=None):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for name,value in (entries or {'SyncLab/SyncLab.exe':b'MZ-test','SyncLab/_internal/runtime.dll':b'library'}).items():
            z.writestr(name,value)
    return b.getvalue()


def info(data):
    return updates.UpdateInfo('1.1.0','https://github.com/contentriumkorea/synclab/releases/download/v1.1.0/SyncLab-Windows-x64.zip',len(data),hashlib.sha256(data).hexdigest(),'Changes')


def test_latest_version_checks_asset_digest_and_owner():
    data=archive();asset=info(data)
    payload={'tag_name':'v1.1.0','draft':False,'prerelease':False,'body':'Changes',
             'assets':[{'name':'SyncLab-Windows-x64.zip','size':len(data),'digest':'sha256:'+asset.sha256,'browser_download_url':asset.url}]}
    opener=lambda *a,**kw:io.BytesIO(json.dumps(payload).encode())
    result=updates.fetch_latest('1.0.0',opener=opener)
    assert result.version=='1.1.0'
    assert updates.fetch_latest('1.1.0',opener=opener) is None
    payload['assets'][0]['browser_download_url']='https://example.com/app.zip'
    with pytest.raises(ValueError):updates.fetch_latest('1.0.0',opener=opener)
    payload['assets'][0]['browser_download_url']=asset.url
    payload['assets'][0]['digest']=None
    with pytest.raises(ValueError):updates.fetch_latest('1.0.0',opener=opener)


def test_verified_update_installs_beside_current_app_and_persists_pointer(tmp_path):
    data=archive();seen=[]
    exe=updates.install_update(info(data),root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data),progress=lambda *p:seen.append(p),validator=lambda exe:None)
    assert exe.read_bytes()==b'MZ-test'
    assert updates.find_installed_update('1.0.0',root=tmp_path)==exe
    assert updates.find_installed_update('1.1.0',root=tmp_path) is None
    assert seen[-1][0]==100
    exe.write_bytes(b'corrupt')
    assert updates.find_installed_update('1.0.0',root=tmp_path) is None


@pytest.mark.parametrize('bad_name',['SyncLab/../outside.exe','/outside.exe','SyncLab/C:bad','SyncLab/dir/../../outside','SyncLab/CON'])
def test_unsafe_archive_is_not_activated(tmp_path,bad_name):
    data=archive({bad_name:b'bad','SyncLab/SyncLab.exe':b'MZ-test'})
    with pytest.raises(ValueError):updates.install_update(info(data),root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data))
    assert not (tmp_path/'current.json').exists()
    assert not list(tmp_path.glob('.stage-*'))


def test_checksum_failure_and_cancellation_leave_previous_pointer(tmp_path):
    data=archive();asset=info(data)
    old=tmp_path/'current.json';old.write_text('{"version":"0.9.0"}')
    with pytest.raises(ValueError):updates.install_update(asset,root=tmp_path,opener=lambda *a,**kw:io.BytesIO(b'wrong'))
    assert json.loads(old.read_text())['version']=='0.9.0'
    from synclab.models import Cancelled
    with pytest.raises(Cancelled):updates.install_update(asset,root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data),cancelled=lambda:True)
    assert json.loads(old.read_text())['version']=='0.9.0'


def test_active_pointer_cannot_escape_versions_directory(tmp_path):
    (tmp_path/'current.json').write_text(json.dumps({'version':'9.0.0','directory':'../../outside'}))
    assert updates.find_installed_update('1.0.0',root=tmp_path) is None


def test_unstartable_update_does_not_replace_the_active_version(tmp_path):
    data=archive();old=tmp_path/'current.json';old.write_text('{"version":"0.9.0"}')
    def fail(exe):raise ValueError('cannot start')
    with pytest.raises(ValueError):updates.install_update(info(data),root=tmp_path,opener=lambda *a,**kw:io.BytesIO(data),validator=fail)
    assert json.loads(old.read_text())['version']=='0.9.0'
