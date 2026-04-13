# Music Mastery

Music Mastery is a fast native desktop app for simple song mastering on Windows and macOS.

It focuses on practical mastering workflows:
- live manual mastering with instant preview updates
- reference matching for beginners
- waveform comparison between original and mastered audio
- saved mastering memories
- Windows desktop packaging for direct use without a Python setup
- SwiftUI macOS desktop support for MacBooks and macOS

## Downloads

Windows:
- Download the latest Windows package from the GitHub Releases page:
  [https://github.com/Shudufhadzo/music_mastery/releases/latest](https://github.com/Shudufhadzo/music_mastery/releases/latest)
- Asset name: `Music-Mastery-win64.zip`
- Inside that zip you will find `Music Mastery.exe` and the runtime files it needs.

macOS:
- Download the Mac build from this repo:
  `macOS/downloads/Music-Mastery-macOS-universal.zip`
- Inside that zip you will find `Music Mastery.app`.
- The Mac build is universal and supports Apple Silicon and Intel Macs.

## Windows Install

1. Download `Music-Mastery-win64.zip` from the latest GitHub release.
2. Extract the zip to a normal folder such as `C:\Music Mastery`.
3. Open the extracted folder.
4. Run `Music Mastery.exe`.

Notes:
- Do not run the app directly from inside the zip.
- Keep the `.exe` together with the extracted files next to it.
- If Windows SmartScreen appears, choose `More info`, then `Run anyway`.

## macOS Install

1. Download `macOS/downloads/Music-Mastery-macOS-universal.zip`.
2. Unzip it.
3. Move `Music Mastery.app` to `Applications`.
4. Open `Music Mastery.app`.

Note:
- The bundled repo build is ad hoc signed. For public release distribution outside source builds, sign with a Developer ID certificate and notarize the zip with Apple.

## Windows From Source

Requirements:
- Windows
- Python 3.11
- `ffmpeg` available on `PATH`

Run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m mastery_native.main
```

Test:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

Build:

```powershell
.\scripts\build.ps1
```

Build outputs:
- unpacked app folder: `release\Music Mastery`
- Windows download zip: `downloads\Music-Mastery-win64.zip`

## macOS From Source

Requirements:
- macOS 13 or newer
- Xcode 16 or newer, or Apple Swift 6 toolchain

Run:

```bash
cd macOS
swift run MusicMasteryMacOS
```

Test:

```bash
cd macOS
swift test
```

Build:

```bash
cd macOS
./scripts/build_macos_app.sh
```

Build outputs:
- macOS app bundle: `macOS/release/Music Mastery.app`
- macOS download zip: `macOS/downloads/Music-Mastery-macOS-universal.zip`

For Developer ID signing:

```bash
cd macOS
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./scripts/build_macos_app.sh
```

## Clean Generated Files

Windows:

```powershell
.\scripts\clean.ps1
```

macOS:

```bash
rm -rf macOS/.build macOS/release
```

## Project Layout

- `src/mastery_native`: Windows desktop app source
- `macOS`: SwiftUI macOS app source and macOS download build
- `tests`: Windows app automated tests
- `macOS/Tests`: macOS core automated tests
- `scripts/build.ps1`: Windows packaging script
- `scripts/clean.ps1`: Windows cleanup script
- `macOS/scripts/build_macos_app.sh`: macOS packaging script
- `downloads`: local Windows packaged zip created during release builds
- `macOS/downloads`: macOS downloadable zip

## License

MIT. See `LICENSE`.
