# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas = [('src/bookfetch/static', 'bookfetch/static')]
# N3 macOS 系统翻译桥（swiftc 产物；translator.py 在 _MEIPASS/bookfetch/translate_bridge 定位）
if os.path.exists('packaging/build/translate_bridge'):
    datas.append(('packaging/build/translate_bridge', 'bookfetch'))
# N3 翻译语言包准备器（独立 .app，首次翻译未装语言包时 open 拉起）
# datas 目录是平铺拷贝：源须指向 .app/Contents 以保留 Contents 内结构
if os.path.exists('packaging/activator/TranslationActivator.app/Contents'):
    datas.append(('packaging/activator/TranslationActivator.app/Contents',
                  'bookfetch/TranslationActivator.app/Contents'))
binaries = []
hiddenimports = []
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('opencc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['packaging/desktop_entry.py'],
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bookfetch',
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
    name='bookfetch',
)
app = BUNDLE(
    coll,
    name='bookfetch.app',
    icon=None,
    bundle_identifier=None,
)
