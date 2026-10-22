@echo off
setlocal
pushd "%~dp0" || exit /b 1
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Install 64-bit Python and add it to PATH.
    goto failure
)
python -c "import sys, struct, platform, tkinter; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64', 'x86_64') else 1)"
if errorlevel 1 (
    echo ERROR: Windows x64 Python with Tcl/Tk is required.
    goto failure
)
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto failure
if exist build rmdir /s /q build
if exist build goto failure
if exist dist rmdir /s /q dist
if exist dist goto failure
python -m PyInstaller --noconfirm --clean BinaryIDReplacer.spec
if errorlevel 1 goto failure
if not exist "dist\BinaryIDReplacer.exe" goto failure
echo SUCCESS: "%CD%\dist\BinaryIDReplacer.exe" created.
echo Test the executable on Windows 10 and 11 before distribution.
popd
exit /b 0
:failure
echo ERROR: Build failed. Review the messages above.
popd
exit /b 1
