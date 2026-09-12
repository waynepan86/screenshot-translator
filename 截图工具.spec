# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os
import sys
from pathlib import Path

# Build under a predictable DLL search path. Host applications may prepend
# native tool directories containing unrelated Windows runtime DLLs.
windir = Path(os.environ.get('WINDIR', r'C:\Windows'))
os.environ['PATH'] = os.pathsep.join([str(Path(sys.base_prefix)), str(Path(sys.base_prefix) / 'Scripts'), str(windir / 'System32'), str(windir)])

datas = [('app.ico', '.'), ('USER_GUIDE.md', '.')]
binaries = []
hiddenimports = ['winrt.windows.foundation.collections', 'winrt.windows.media.ocr', 'winrt.windows.graphics.imaging', 'winrt.windows.storage', 'winrt.windows.storage.streams', 'winrt.windows.globalization']
tmp_ret = collect_all('rapidocr')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('spellchecker')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Windows 10/11 provide these OS components. Never redistribute a copy found
# in an unrelated application's PATH; its forwarders can break Qt imports.
a.binaries = [item for item in a.binaries
              if not (Path(item[0]).name.lower().startswith(('api-ms-win-', 'ext-ms-win-'))
                      or Path(item[0]).name.lower() == 'ucrtbase.dll')]
trusted_roots = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), windir.resolve())
a.binaries = [item for item in a.binaries
              if any(Path(item[1]).resolve().is_relative_to(root) for root in trusted_roots)]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='截图工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
