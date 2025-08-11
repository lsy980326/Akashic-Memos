# main.spec

import os

block_cipher = None
spec_dir = os.getcwd()

# Analysis 객체는 PyInstaller가 내부적으로 생성하므로,
# 우리는 Analysis의 속성인 a.datas만 수정해주면 됩니다.
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
        datas=[
        ('resources', 'resources'),
        ('style.qss', '.'),
        ('custom.css', '.')
    ],
    hiddenimports=[
        'pystray._win32',
        'google.auth.transport.requests',
        'qtawesome'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AkashicMemo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(spec_dir, 'resources', 'icon.ico'),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AkashicMemo_App',
)