#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Music Mastery"
EXECUTABLE_NAME="MusicMasteryMacOS"
CONFIGURATION="release"
RELEASE_DIR="$ROOT_DIR/release"
DOWNLOADS_DIR="$ROOT_DIR/downloads"
APP_DIR="$RELEASE_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
ZIP_PATH="$DOWNLOADS_DIR/Music-Mastery-macOS-universal.zip"
BUILT_EXECUTABLE="$ROOT_DIR/.build/apple/Products/Release/$EXECUTABLE_NAME"

cd "$ROOT_DIR"
swift build -c "$CONFIGURATION" --arch arm64 --arch x86_64

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR"
cp "$BUILT_EXECUTABLE" "$MACOS_DIR/$APP_NAME"

cat > "$CONTENTS_DIR/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Music Mastery</string>
    <key>CFBundleIdentifier</key>
    <string>com.shudufhadzo.musicmastery.macos</string>
    <key>CFBundleName</key>
    <string>Music Mastery</string>
    <key>CFBundleDisplayName</key>
    <string>Music Mastery</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

xattr -cr "$APP_DIR"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$APP_DIR"
else
  codesign --force --deep --sign - "$APP_DIR"
fi

xattr -cr "$APP_DIR"

mkdir -p "$DOWNLOADS_DIR"
rm -f "$ZIP_PATH"
ditto -c -k --keepParent --noextattr --noqtn "$APP_DIR" "$ZIP_PATH"
xattr -cr "$APP_DIR"

echo "Built $APP_DIR"
echo "Created $ZIP_PATH"
