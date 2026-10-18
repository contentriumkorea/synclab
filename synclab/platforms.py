"""Platform-specific locations and packaged application layout."""
from pathlib import Path
import os
import platform
import sys

from .version import WINDOWS_ASSET


def distribution_asset():
    machine=platform.machine().lower()
    if sys.platform=='darwin':
        if machine in {'arm64','aarch64'}:return 'SyncLab-macOS-arm64.zip'
        if machine in {'x86_64','amd64'}:return 'SyncLab-macOS-x64.zip'
    elif sys.platform=='win32' and machine in {'amd64','x86_64'}:
        return WINDOWS_ASSET
    raise ValueError('이 운영체제 또는 CPU에 맞는 배포 파일이 없습니다.')


def application_data():
    if sys.platform=='darwin':return Path.home()/'Library'/'Application Support'/'SyncLab'
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'SyncLab'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'SyncLab'


def audio_cache():
    if os.environ.get('SYNCLAB_CACHE_DIR'):return Path(os.environ['SYNCLAB_CACHE_DIR'])
    if sys.platform=='darwin':return Path.home()/'Library'/'Caches'/'SyncLab'/'audio-cache-v1'
    return application_data()/'audio-cache-v1'


def bundle_name():
    return 'SyncLab.app' if sys.platform=='darwin' else 'SyncLab'


def executable_in(directory):
    if sys.platform=='darwin':return Path(directory)/'SyncLab.app'/'Contents'/'MacOS'/'SyncLab'
    return Path(directory)/'SyncLab'/'SyncLab.exe'
