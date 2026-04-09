# Music Mastery

Music Mastery is a fast native Windows desktop app for simple song mastering.

It is built with PySide6 and focuses on practical mastering workflows:
- live manual mastering with instant preview updates
- reference matching for beginners
- waveform comparison between original and mastered audio
- saved mastering memories
- Windows desktop packaging for direct use without a Python setup

## Windows Download

Download the latest Windows package from the GitHub Releases page:

[https://github.com/Shudufhadzo/music_mastery/releases/latest](https://github.com/Shudufhadzo/music_mastery/releases/latest)

Asset name:

`Music-Mastery-win64.zip`

Inside that zip you will find `Music Mastery.exe` and the runtime files it needs.

## Windows Install

1. Download `Music-Mastery-win64.zip` from the latest GitHub release.
2. Extract the zip to a normal folder such as `C:\Music Mastery`.
3. Open the extracted folder.
4. Run `Music Mastery.exe`.

Notes:
- Do not run the app directly from inside the zip.
- Keep the `.exe` together with the extracted files next to it.
- If Windows SmartScreen appears, choose `More info`, then `Run anyway`.

## Run From Source

Requirements:
- Windows
- Python 3.11
- `ffmpeg` available on `PATH`

Run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m mastery_native.main
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

## Build Windows App

```powershell
.\scripts\build.ps1
```

Build outputs:
- unpacked app folder: `release\Music Mastery`
- Windows download zip: `downloads\Music-Mastery-win64.zip`

## Clean Generated Files

```powershell
.\scripts\clean.ps1
```

This removes local caches and generated build folders without touching the virtual environment.

## Project Layout

- `src/mastery_native`: desktop app source
- `tests`: automated tests
- `scripts/build.ps1`: Windows packaging script
- `scripts/clean.ps1`: local cleanup script
- `downloads`: local packaged zip created during release builds

## License

MIT. See `LICENSE`.
