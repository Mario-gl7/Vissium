# -*- mode: python ; coding: utf-8 -*-
# Genera Vissium.exe (Windows, un solo archivo, sin consola).
#
# Compilar (en Windows, con el venv activado y pyinstaller instalado):
#
#     pyinstaller vissium.spec
#
# El resultado queda en dist/Vissium.exe

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# pylibjpeg/pydicom localizan los decodificadores mediante metadatos de los
# paquetes (entry points); sin copiarlos, el .exe no lee DICOM comprimidos
# aunque funcione con `python main.py`.
_datas = [("assets", "assets")]
for _pkg in ("pydicom", "pylibjpeg", "pylibjpeg-libjpeg", "pylibjpeg-openjpeg", "pylibjpeg-rle", "python-gdcm"):
    try:
        _datas += copy_metadata(_pkg)
    except Exception:
        pass

_hidden = [
    "pythoncom", "pywintypes", "win32timezone", "win32com.client", "win32process",
    "keyboard", "vtkmodules.all", "vtkmodules.qt.QVTKRenderWindowInteractor",
]
# "pydicom" completo: en pydicom 3 los decodificadores de píxeles se cargan por
# importación dinámica y PyInstaller no los detecta por sí solo.
for _mod in ("pydicom", "pylibjpeg", "libjpeg", "openjpeg", "rle", "gdcm"):
    try:
        _hidden += collect_submodules(_mod)
    except Exception:
        pass

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Vissium",
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
    icon="assets/icon.ico",
)
