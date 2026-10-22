$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Install 64-bit Python and add it to PATH.'
    }
    & python -c "import sys, struct, platform, tkinter; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64', 'x86_64') else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Windows x64 Python with Tcl/Tk is required.' }
    & python -m pip install --upgrade -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    foreach ($folder in @('build', 'dist')) {
        if (Test-Path -LiteralPath $folder) {
            Remove-Item -LiteralPath $folder -Recurse -Force
        }
    }
    & python -m PyInstaller --noconfirm --clean BinaryIDReplacer.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    if (-not (Test-Path -LiteralPath 'dist\BinaryIDReplacer.exe' -PathType Leaf)) {
        throw 'Expected executable was not created.'
    }
    Write-Host "SUCCESS: $PSScriptRoot\dist\BinaryIDReplacer.exe created."
    Write-Host 'Test the executable on Windows 10 and 11 before distribution.'
} catch {
    Write-Host "ERROR: Build failed. $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
