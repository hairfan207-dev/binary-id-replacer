# Binary ID Replacer 1.0.0

A Python/Tkinter desktop utility for replacing exact four-byte unsigned
little-endian IDs in user-selected binary files. Target release platforms:
Windows 10 and Windows 11, x64. No process manipulation or checksum, signature,
encryption, or integrity bypass features.

## Run from source

Use Python 3.10+ with Tcl/Tk (included in the standard Windows installer).
The application and tests use only the standard library. PyInstaller is needed
only to build the standalone executable.

From the `binary-id-replacer` directory:

```sh
python main.py
```

On macOS, use the actual project directory and `python3`:

```sh
cd "/Users/hassanmac/Desktop/Binary ID Replacer/binary-id-replacer"
python3 main.py
```

Browse for a file, enter two different decimal UINT32 IDs, and select
**Process & Save**. Live previews show four-byte little-endian HEX:

| Decimal ID | Little-endian HEX |
| --- | --- |
| 10100400 | B0 1E 9A 00 |
| 101004046 | 0E 33 05 06 |

Values must be between 0 and 4294967295. Blank values, negative numbers,
non-decimal input, and equal IDs are rejected. The engine also rejects booleans.
The examples above are not application defaults.

The window is centered on launch, supports resizing, and disables inputs while
a worker processes the file. A main-thread `after` callback polls a result
queue; workers never access Tk widgets. Completed workers are joined without
blocking the UI. Closing during a job asks the user to wait for completion.

Successful replacements show the count, original/output sizes, and output
path. On Windows, **Open Output Folder** is enabled only after at least one
replacement. If there are no matches, the GUI removes the unchanged output,
leaves the original untouched, and reports that no modified file was created.
If cleanup fails or the output appears to have changed, a warning identifies
the remaining path and the detailed exception is logged. Folder opening stays
disabled. Do not concurrently modify the selected file or generated output.

## Processing and safe publication

`binary_processor.py` exposes conversion, HEX formatting, output naming, and
chunked replacement functions. `struct.pack("<I", value)` encodes each ID into
four bytes with the least significant byte first. Little endian is the chosen
representation, not an assumption that every file format uses it.

The engine reads 8 MiB chunks by default and retains up to three undecided
bytes between reads. A match is consumed fully even when it crosses that
boundary. Matching is left-to-right and non-overlapping, like `bytes.replace`;
replacement bytes are never searched again. Memory use is bounded by chunk
size. The existing chunking algorithm has not changed for this release.

The original is read-only. A temporary file in the destination directory is
flushed, synced where supported, closed, and checked against the original size.
It is then copied in bounded chunks to an exclusively created normal output
file, with a final size check. No hard links are required. Existing outputs,
including concurrently created files and input aliases, are rejected. Failed
publication cleans up its partial output and temporary file where possible.
The second copy requires additional disk space and I/O; the final filename is
visible during copying, so consumers must wait for successful completion.
Abrupt termination can leave a temporary or partial file.

The engine itself still creates a copy for a zero-match result; only the GUI
applies the new cleanup policy. Output folders must exist and be writable.
Names use `sample_modified.pak`, then `sample_modified_2.pak`, and so on.
Generating a filename does not reserve it.

## Logging

Logs use `%LOCALAPPDATA%\Binary ID Replacer\binary_replacer.log` on Windows.
If LOCALAPPDATA is missing, empty, or relative, the user's home directory is
used instead. The folder is created automatically. The executable directory,
working directory, and PyInstaller extraction directory are never used for
logs. Rotation limits each log to 2 MiB with two backups. Startup, paths,
processing results, counts, and exceptions are logged; binary contents are not.
If logging cannot be initialized, a friendly startup dialog is shown.

## Tests

From the project directory:

```sh
python -m unittest -v
```

On macOS use `python3 -m unittest -v`. Run from a normal desktop session because
the GUI integration tests create real Tk widgets (dialogs and the file picker
are mocked). Tk may abort in a restricted macOS desktop sandbox rather than
raise a catchable display error. The original 44 engine tests are unchanged.
Additional tests cover GUI states, no-match deletion and cleanup failure,
thread completion, Windows folder opening, previews, and logging paths.

## WINDOWS BUILD

1. On the **build computer**, install x64 Python 3.10 or newer for Windows with
   Tcl/Tk and pip. Enable **Add Python to PATH**. Use an x64 Windows machine.
2. Open Command Prompt in the `binary-id-replacer` folder containing `main.py`
   and `BinaryIDReplacer.spec`.
3. Prefer a clean virtual environment to keep unrelated packages out of the
   build:

   ```bat
   python -m venv .venv
   .venv\Scripts\activate.bat
   ```

4. Run the tests, then the build script:

   ```bat
   python -m unittest -v
   build_windows.bat
   ```

   Alternatively, from PowerShell with the desired Python on PATH:

   ```powershell
   .\build_windows.ps1
   ```

   Follow your organization's PowerShell execution policy if scripts are
   restricted; the batch script is an equivalent option.

5. Both scripts validate Windows x64 Python and Tcl/Tk, install/upgrade build
   dependencies from `requirements.txt`, remove the project's old `build` and
   `dist` folders, run PyInstaller, and verify the expected output:

   ```text
   dist\BinaryIDReplacer.exe
   ```

   Save any previous releases outside those folders before rebuilding.
   The scripts stop on failure, report success/failure, and never launch the EXE.

6. Test the EXE on Windows 10 and Windows 11 x64, ideally clean machines without
   Python installed. Copy only `BinaryIDReplacer.exe` to the client. Python,
   Tcl/Tk, and required libraries are bundled; clients do not install Python.

`BinaryIDReplacer.spec` configures a one-file, windowed build without a console,
with version 1.0.0 metadata from `version_info.txt`. There is no custom icon
requirement. Paths are resolved relative to the spec/script, so builds can be
invoked from other directories. Build scripts remove only their local build
outputs. PyInstaller's temporary extraction location is not used for user data.

This preparation was tested on macOS at source level. A Windows EXE has **not**
been produced or validated here. PyInstaller must run on Windows to produce
this Windows release; macOS builds are not Windows executables.
See [PyInstaller spec documentation](https://pyinstaller.org/en/stable/spec-files.html)
and [platform/build information](https://pypi.org/project/pyinstaller/).

Before distributing, verify native Windows dialogs, Browse filters, DPI scaling,
minimum-size/resized layout, progress animation, close-during-processing behavior,
output folder opening, non-ASCII/spaced paths, no-match cleanup, unwritable output
errors, and logs under the client user's account. Repeat the two-occurrence
sample test and confirm both replacement count and exact file-size preservation.
