#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$ROOT/build/macos-ui}"
ARCH="$(uname -m)"
mkdir -p "$OUTPUT"
xcrun clang -target "$ARCH-apple-macos13.0" -Wall -Wextra -Werror -c "$ROOT/macos/ProcessBridge.c" -o "$OUTPUT/ProcessBridge.o"
xcrun swiftc -swift-version 5 -O -target "$ARCH-apple-macos13.0" -framework AppKit -framework ServiceManagement \
  -import-objc-header "$ROOT/macos/ProcessBridge.h" "$ROOT"/macos/*.swift "$OUTPUT/ProcessBridge.o" -o "$OUTPUT/CodexUsageTray"
"$OUTPUT/CodexUsageTray" --self-test "$OUTPUT/test-images"
