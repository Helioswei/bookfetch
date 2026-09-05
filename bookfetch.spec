# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('src/bookfetch/static', 'bookfetch/static'),
    # 翻译桥 + 激活器（坑 39：Contents 内结构保留；onedir 剥离 app 名前缀后
    # translator 双形态查找兜住）。编译产物 gitignored——本机直接打；CI 的
    # desktop-build action 须先 build_translator.sh/build_activator.sh 再 pyinstaller。
    ('packaging/build/translate_bridge', 'bookfetch'),
    ('packaging/activator/TranslationActivator.app/Contents', 'bookfetch/TranslationActivator.app/Contents'),
]
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
