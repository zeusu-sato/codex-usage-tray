#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-0.4.1}"
INSTALLER="${2:?Pass the verified python.org installer path}"
PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
ARCH="$(uname -m)"
WORK="$ROOT/build/macos-package-$ARCH"
APP="$WORK/Codex Usage Tray.app"
mkdir -p "$WORK" "$ROOT/dist"
if [[ -e "$APP" ]]; then echo 'Choose a clean build directory; an app already exists.' >&2; exit 1; fi
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/macos/requirements-build.txt"
export PYTHONPATH="$ROOT/src"
"$WORK/venv/bin/python" -m unittest discover -s "$ROOT/tests" -q
bash "$ROOT/macos/build-ui.sh"
"$WORK/venv/bin/python" -m PyInstaller --noconfirm --onedir --console --name CodexUsageBackend \
  --target-architecture "$ARCH" --paths "$ROOT/src" --distpath "$WORK/backend-dist" --workpath "$WORK/work" --specpath "$WORK" "$ROOT/src/backend.py"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/build/macos-ui/CodexUsageTray" "$APP/Contents/MacOS/CodexUsageTray"
ditto "$WORK/backend-dist/CodexUsageBackend" "$APP/Contents/Resources/backend"
"$WORK/venv/bin/python" "$ROOT/macos/prepare_bundle.py" "$APP" "$VERSION"
# Sign nested binaries before recording their final hashes. Re-seal only the
# outer app after adding notices, so the recorded runtime bytes stay unchanged.
codesign --force --deep --sign - "$APP"
"$WORK/venv/bin/python" "$ROOT/macos/collect_notices.py" "$APP" "$INSTALLER"
codesign --force --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
"$WORK/venv/bin/python" "$ROOT/macos/test_package.py" "$APP" "$ARCH"
ZIP="$ROOT/dist/CodexUsageTray-$VERSION-macos-$ARCH.zip"
if [[ -e "$ZIP" ]]; then echo 'Output ZIP already exists.' >&2; exit 1; fi
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
cd "$ROOT/dist"
shasum -a 256 "$(basename "$ZIP")" > "SHA256SUMS-macos-$ARCH.txt"
