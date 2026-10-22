# Build on Windows x64 with: python -m PyInstaller --noconfirm --clean BinaryIDReplacer.spec
from pathlib import Path
import sys
import struct
import platform

if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
    raise SystemExit("Build on Windows with 64-bit x86 Python.")

project = Path(SPECPATH)
a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
# Passing binaries and data to EXE directly produces a single-file build.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BinaryIDReplacer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    version=str(project / "version_info.txt"),
)
