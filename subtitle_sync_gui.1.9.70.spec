app_version = "1.9.70"

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import os

# Collect hidden imports and data for faster_whisper
hiddenimports = collect_submodules('faster_whisper')
datas = collect_data_files('faster_whisper')

# Add local model and icons
datas += [
    ('models/whisper-large-v3', 'models/whisper-large-v3'),
    ('icons', 'icons'),
]

# Add FFmpeg binary
binaries = [('bin/ffmpeg.exe', 'bin/ffmpeg.exe')]

block_cipher = None

a = Analysis(
    ['subtitle_sync_gui.' + app_version + '.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision'],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],  # excluded binaries from EXE; they go to COLLECT
    [],
    [],
    [],
    name='subtitle_sync_gui.' + app_version,
    exclude_binaries=True,
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='subtitle_sync_gui.' + app_version,
)