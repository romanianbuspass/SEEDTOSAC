# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for mseed2sac-gui.
# Build with:  python -m PyInstaller mseed2sac_gui.spec
#
# Bundles the compiled C binary `mseed2sac` (in ./bin/) as an internal
# asset; at runtime it is resolved via sys._MEIPASS/bin/mseed2sac.

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

BIN_NAME = "mseed2sac.exe" if os.name == "nt" else "mseed2sac"

# ObsPy ships data files and lazily-imported submodules — take it all.
obspy_datas, obspy_binaries, obspy_hidden = collect_all("obspy")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[(os.path.join("bin", BIN_NAME), "bin")] + obspy_binaries,
    datas=[("assets", "assets")] + obspy_datas,
    hiddenimports=obspy_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide2", "PySide6", "tkinter", "matplotlib.tests"],
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
    name="mseed2sac-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # windowed app — no console shell
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # .ico is Windows-only; PyInstaller ignores icons on Linux ELF builds
    icon=os.path.join("assets", "logo.ico") if os.name == "nt" else None,
)
