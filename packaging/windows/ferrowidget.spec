# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for FerroWidget Windows Standalone Executable

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

repo_root = Path.cwd()
src_dir = repo_root / "src"

datas = [
    (str(src_dir / "ferrowidget" / "render" / "shaders"), "ferrowidget/render/shaders"),
    (str(repo_root / "packaging" / "icons"), "packaging/icons"),
]

hiddenimports = [
    "moderngl",
    "glcontext",
    "numpy",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtOpenGLWidgets",
    "sounddevice",
    "tomli_w",
    "PIL",
]

a = Analysis(
    [str(src_dir / "ferrowidget" / "__main__.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ferrowidget",
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
    icon=str(repo_root / "packaging" / "icons" / "ferrowidget.ico"),
)
