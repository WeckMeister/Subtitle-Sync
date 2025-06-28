# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import os

# Add hidden modules and data from faster_whisper
hiddenimports = collect_submodules('faster_whisper')
datas = collect_data_files('faster_whisper')

# Bundle your local Whisper model
datas += [
    ('models/whisper-large-v3', 'models/whisper-large-v3'),
    ('icons', 'icons'),
]


# Bundle ffmpeg binary
binaries = [('bin/ffmpeg.exe', 'ffmpeg.exe')]

block_cipher = None

a = Analysis(
    ['subtitle_sync_gui.1.9.25.py'],
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
    cipher=block_cipher,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='subtitle_sync_gui.1.9.25',
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