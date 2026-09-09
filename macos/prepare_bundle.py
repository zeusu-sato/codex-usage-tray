import plistlib
from pathlib import Path
import re
import shutil
import sys

app, version = Path(sys.argv[1]), sys.argv[2]
if not re.fullmatch(r'\d+\.\d+\.\d+', version):
    raise ValueError('Invalid bundle version')
root = Path(__file__).resolve().parent.parent
info = {'CFBundleName': 'Codex Usage Tray', 'CFBundleDisplayName': 'Codex + Claude Usage',
        'CFBundleIdentifier': 'io.github.zeusu-sato.codex-usage-tray', 'CFBundleVersion': version,
        'CFBundleShortVersionString': version, 'CFBundleExecutable': 'CodexUsageTray',
        'CFBundlePackageType': 'APPL', 'NSPrincipalClass': 'NSApplication',
        'LSUIElement': True, 'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Copyright 2026 Zeusu Sato. MIT License.'}
with (app / 'Contents/Info.plist').open('wb') as stream:
    plistlib.dump(info, stream)
resources = app / 'Contents/Resources'
for name in ['LICENSE', 'README.md', 'README.ja.md']:
    shutil.copyfile(root / name, resources / name)
docs = resources / 'docs'
docs.mkdir()
for name in ['PRIVACY.md', 'RELEASE_NOTES.md']:
    shutil.copyfile(root / 'docs' / name, docs / name)
images = docs / 'images'
images.mkdir()
for name in ['demo.png', 'macos-demo.png']:
    shutil.copyfile(root / 'docs/images' / name, images / name)
mac_docs = resources / 'macos'
mac_docs.mkdir()
shutil.copyfile(root / 'macos/README.md', mac_docs / 'README.md')
