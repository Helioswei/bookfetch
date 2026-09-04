#!/bin/bash
# 编译 SwiftUI 语言包准备器 → packaging/activator/TranslationActivator.app
# 要求 macOS 26.4+（TranslationSession.Configuration 26.4+，本机 26.6）
set -euo pipefail
cd "$(dirname "$0")"
APP=activator/TranslationActivator.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -parse-as-library -O -target arm64-apple-macosx26.4 activator/activator.swift \
  -o "$APP/Contents/MacOS/TranslationActivator"
cat > "$APP/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>TranslationActivator</string>
  <key>CFBundleIdentifier</key><string>com.helioswei.bookfetch.activator</string>
  <key>CFBundleName</key><string>TranslationActivator</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>26.4</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "OK: $(pwd)/$APP"
