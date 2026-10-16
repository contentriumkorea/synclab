"""Verified, per-user, side-by-side updates from the project's public GitHub assets."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid
import zipfile

from .engine import check_cancel
from .storage import atomic_write
from .version import VERSION, REPOSITORY, WINDOWS_ASSET

MAX_DOWNLOAD=1024**3
MAX_EXPANDED=3*1024**3


def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'v?\d{1,6}\.\d{1,6}\.\d{1,6}',value):
        raise ValueError('업데이트 버전 형식이 올바르지 않습니다.')
    return tuple(int(x) for x in value.removeprefix('v').split('.'))


def update_root():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'SyncLab'/'updates'


def _allowed_url(url):
    u=urlsplit(url)
    return (u.scheme=='https' and not u.username and not u.password and u.port in (None,443)
            and (u.hostname in {'github.com','api.github.com'} or
                 bool(u.hostname and u.hostname.endswith('.githubusercontent.com'))))


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not _allowed_url(newurl):raise ValueError('GitHub 외부의 다운로드 주소는 허용하지 않습니다.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _open(url,opener):
    if not _allowed_url(url):raise ValueError('업데이트 주소가 올바르지 않습니다.')
    req=Request(url,headers={'User-Agent':'SyncLab/'+VERSION,'Accept':'application/vnd.github+json'})
    try:
        return (opener or build_opener(_Redirects()).open)(req,timeout=20)
    except HTTPError as exc:
        raise ValueError(f'GitHub 업데이트 확인/다운로드 실패 (HTTP {exc.code}). 잠시 후 다시 시도해 주세요.') from exc
    except (URLError,TimeoutError,OSError) as exc:
        raise ValueError('업데이트 서버에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.') from exc


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    size: int
    sha256: str
    notes: str


def fetch_latest(current=VERSION,opener=None):
    with _open(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',opener) as response:
        raw=response.read(1024**2+1)
    if len(raw)>1024**2:raise ValueError('업데이트 응답이 너무 큽니다.')
    try:
        doc=json.loads(raw)
        latest=doc['tag_name'].removeprefix('v')
        if doc.get('draft') or doc.get('prerelease'):raise ValueError('정식 배포 버전이 아닙니다.')
        if version_tuple(latest)<=version_tuple(current):return None
        asset=next(a for a in doc['assets'] if a.get('name')==WINDOWS_ASSET)
        u=urlsplit(asset['browser_download_url'])
        valid_paths={f'/{REPOSITORY}/releases/download/{tag}/{WINDOWS_ASSET}' for tag in [latest,'v'+latest]}
        if not _allowed_url(asset['browser_download_url']) or u.hostname!='github.com' or u.path not in valid_paths or u.query or u.fragment:
            raise ValueError('업데이트 파일의 저장소/주소가 올바르지 않습니다.')
        digest=asset.get('digest') or ''
        if not re.fullmatch('sha256:[0-9a-fA-F]{64}',digest):raise ValueError('업데이트 파일의 SHA256 검증 정보가 없습니다.')
        if type(asset['size']) is not int or not 0<asset['size']<=MAX_DOWNLOAD:raise ValueError('업데이트 파일 크기가 올바르지 않습니다.')
        return UpdateInfo(latest,asset['browser_download_url'],asset['size'],digest[7:].lower(),str(doc.get('body') or '')[:2000])
    except (KeyError,StopIteration,TypeError,json.JSONDecodeError,AttributeError) as exc:
        raise ValueError('업데이트 파일 정보를 읽을 수 없습니다.') from exc


def _members(z):
    members=z.infolist();seen=set()
    if len(members)>20000 or sum(x.file_size for x in members)>MAX_EXPANDED:
        raise ValueError('업데이트 압축 크기/파일 수가 제한을 초과합니다.')
    reserved={'con','prn','aux','nul',*[f'com{i}' for i in range(1,10)],*[f'lpt{i}' for i in range(1,10)]}
    for m in members:
        parts=m.filename.rstrip('/').split('/')
        if ('\\' in m.filename or not parts or parts[0]!='SyncLab' or
            any(p in {'','..','.'} or ':' in p or p.endswith((' ','.')) or p.split('.')[0].lower() in reserved for p in parts) or
            stat.S_ISLNK(m.external_attr>>16)):
            raise ValueError('업데이트 압축에 안전하지 않은 경로가 있습니다.')
        key='/'.join(parts).casefold()
        if key in seen:raise ValueError('업데이트 압축에 중복 경로가 있습니다.')
        seen.add(key)
        yield m,PurePosixPath(*parts)


def check_executable(exe):
    report=Path(exe).parent/'health.json'
    env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONPATH':'','PYINSTALLER_RESET_ENVIRONMENT':'1'}
    if os.name=='nt':env['PATH']=os.environ.get('SystemRoot',r'C:\Windows')+r'\System32'
    try:
        result=subprocess.run([str(exe),'--update-health-check',str(report)],env=env,capture_output=True,
                              timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        health=json.loads(report.read_text())
        if result.returncode or not health.get('success'):raise ValueError('실행 검사 실패')
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        raise ValueError('새 버전 실행 검사에 실패했습니다. 현재 버전은 유지합니다.') from exc


def install_update(info,cancelled=lambda:False,progress=lambda p,m:None,root=None,opener=None,validator=None):
    check_cancel(cancelled)
    version_tuple(info.version)
    root=Path(root or update_root()).resolve();root.mkdir(parents=True,exist_ok=True)
    versions=root/'versions';versions.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stage-',dir=root) as temp:
        stage=Path(temp).resolve()
        if not stage.is_relative_to(root):raise ValueError('업데이트 임시 경로가 올바르지 않습니다.')
        archive=stage/'download.zip';digest=hashlib.sha256();total=0
        with _open(info.url,opener) as response, archive.open('wb') as out:
            while chunk:=response.read(256*1024):
                check_cancel(cancelled);total+=len(chunk)
                if total>info.size or total>MAX_DOWNLOAD:raise ValueError('업데이트 파일 크기가 예상과 다릅니다.')
                digest.update(chunk);out.write(chunk)
                progress(round(75*total/info.size),'업데이트 다운로드 중…')
        if total!=info.size or digest.hexdigest()!=info.sha256:raise ValueError('업데이트 파일 검증에 실패했습니다. 현재 버전은 유지합니다.')
        with zipfile.ZipFile(archive) as z:
            members=list(_members(z))
            for index,(m,relative) in enumerate(members):
                check_cancel(cancelled)
                target=stage/Path(str(relative))
                if not target.resolve().is_relative_to(stage):raise ValueError('잘못된 압축 경로입니다.')
                if m.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(m) as src,target.open('wb') as dst:
                    while chunk:=src.read(256*1024):check_cancel(cancelled);dst.write(chunk)
                progress(75+round(20*(index+1)/max(1,len(members))),'업데이트 파일 확인 중…')
        exe=stage/'SyncLab'/'SyncLab.exe'
        if not exe.is_file() or not (stage/'SyncLab'/'_internal').is_dir():raise ValueError('업데이트 실행 파일/런타임이 없습니다.')
        progress(97,'새 버전 실행 검사 중…')
        (validator or check_executable)(exe)
        with exe.open('rb') as src:exe_hash=hashlib.file_digest(src,'sha256').hexdigest()
        receipt={'version':info.version,'archive_sha256':info.sha256,'executable_sha256':exe_hash}
        atomic_write(stage/'SyncLab'/'installed.json',json.dumps(receipt).encode())
        check_cancel(cancelled)
        directory=info.version+'-'+uuid.uuid4().hex[:8]
        destination=versions/directory;destination.mkdir()
        os.replace(stage/'SyncLab',destination/'SyncLab')
        atomic_write(root/'current.json',json.dumps({'version':info.version,'directory':directory}).encode())
        progress(100,'업데이트 준비 완료 · 새 버전으로 다시 시작합니다.')
        return destination/'SyncLab'/'SyncLab.exe'


def find_installed_update(current=VERSION,root=None):
    root=Path(root or update_root()).resolve()
    try:
        pointer=json.loads((root/'current.json').read_text())
        version=pointer['version'];directory=pointer['directory']
        if version_tuple(version)<=version_tuple(current):return None
        if not isinstance(directory,str) or not re.fullmatch(re.escape(version)+r'-[0-9a-f]{8}',directory):return None
        folder=root/'versions'/directory/'SyncLab';exe=folder/'SyncLab.exe'
        if not folder.resolve().is_relative_to(root/'versions'):return None
        receipt=json.loads((folder/'installed.json').read_text())
        if receipt['version']!=version:return None
        with exe.open('rb') as src:
            if hashlib.file_digest(src,'sha256').hexdigest()!=receipt['executable_sha256']:return None
        return exe
    except (OSError,ValueError,KeyError,TypeError):return None
