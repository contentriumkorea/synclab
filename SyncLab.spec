# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys
from pathlib import Path
from synclab.version import VERSION
if sys.platform=='darwin':
    from PIL import Image
    Image.open('synclab/assets/app-icon.png').save('synclab/assets/app-icon.icns',format='ICNS')

datas = [('synclab/assets', 'synclab/assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run_synclab.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf', 'PySide6.QtQml', 'PySide6.QtQuick'],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows' unversioned ICU API. PATH may contain an incompatible
# Poppler/Conda ICU with the same DLL basename; do not bundle that DLL.
a.binaries = [entry for entry in a.binaries if entry[0].lower() not in {'icuuc.dll', 'icuin.dll'}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SyncLab',
    icon='synclab/assets/app-icon.icns' if sys.platform=='darwin' else 'synclab/assets/app-icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SyncLab',
)
if sys.platform=='darwin':
    app = BUNDLE(coll,name='SyncLab.app',icon='synclab/assets/app-icon.icns',
        bundle_identifier='com.contentrium.synclab',
        info_plist={'CFBundleShortVersionString':VERSION,'CFBundleVersion':VERSION,
                    'NSHighResolutionCapable':True,'LSMinimumSystemVersion':'15.0'})
