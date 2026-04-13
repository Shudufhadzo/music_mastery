# Music Mastery for macOS

This folder contains the Swift macOS desktop version of Music Mastery and the downloadable Mac build artifact.

It mirrors the Windows app workflow:

- Reference Match and Manual Controls modes
- WAV, MP3, and FLAC import
- A/B comparison between Original and Mastered
- waveform previews
- quick presets: Warm, Punchy, Balanced, and Bright
- mastering controls for volume, target loudness, clarity, bass, treble, punch, stereo width, low cut, high cut, peak safety, and tone fix
- saved mastering memories
- WAV export using the same `-master.wav` output suffix

## Requirements

- macOS 13 or newer
- Xcode 16 or newer, or Apple Swift 6 toolchain

The macOS app uses Apple-native frameworks:

- SwiftUI for the desktop interface
- AVFoundation for audio decoding, playback, conversion, and WAV writing
- native Swift DSP for the manual mastering chain

No Python runtime is required for the macOS app.

## Download

The checked-in Mac download is:

```text
downloads/Music-Mastery-macOS-universal.zip
```

Inside that zip you will find:

```text
Music Mastery.app
```

The zip contains a universal macOS app binary for Apple Silicon and Intel Macs.

## Run

From this folder:

```bash
swift run MusicMasteryMacOS
```

## Test

```bash
swift test
```

## Build App Bundle

```bash
./scripts/build_macos_app.sh
```

Build outputs:

- app bundle: `release/Music Mastery.app`
- download zip: `downloads/Music-Mastery-macOS-universal.zip`

The script ad hoc signs the app by default so the bundle validates locally. For Developer ID signing, pass your signing identity:

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./scripts/build_macos_app.sh
```

For public distribution outside source builds, notarize the resulting zip with Apple after Developer ID signing.

## Porting Note

The Windows app uses Python, PySide6, `ffmpeg-normalize`, SciPy, and Matchering. This macOS port keeps the same user-facing workflow and mastering controls, but uses a Swift-native AVFoundation audio engine so it can run as a Mac app without requiring Python packages.

Manual mastering follows the same control formulas as the Windows live preview engine. Reference Match uses native loudness and tonal matching with the same reference-strength blend behavior.
