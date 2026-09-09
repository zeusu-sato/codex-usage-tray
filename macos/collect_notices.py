"""Validate the official macOS runtime and preserve its dependency notices."""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import ssl
import sys

ASSETS = Path(__file__).with_name('license-assets')
SHARED = ASSETS.parents[1] / 'packaging' / 'license-assets'
MACHO_MAGICS = (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sections(path, arch):
    """Compare immutable code/data, allowing relocation and ad-hoc signatures."""
    from macholib.MachO import MachO
    from macholib.mach_o import LC_SEGMENT_64
    cpu = 0x0100000c if arch == 'arm64' else 0x01000007
    headers = [h for h in MachO(str(path)).headers if h.header.cputype == cpu]
    if len(headers) != 1:
        raise RuntimeError('Missing expected Mach-O architecture: ' + str(path))
    header = headers[0]
    result = {}
    with Path(path).open('rb') as stream:
        for command, _, sections in header.commands:
            if command.cmd != LC_SEGMENT_64:
                continue
            for section in sections:
                name = section.sectname.rstrip(b'\0').decode('ascii')
                segment = section.segname.rstrip(b'\0')
                if segment == b'__TEXT' and name in ('__text', '__const', '__cstring'):
                    stream.seek(header.offset + section.offset)
                    result[name] = hashlib.sha256(stream.read(section.size)).hexdigest()
    if '__text' not in result:
        raise RuntimeError('Mach-O has no code section: ' + str(path))
    return result


def collect(app, installer):
    import _decimal
    app, installer = Path(app), Path(installer)
    manifest = json.loads((ASSETS / 'runtime.json').read_text(encoding='utf8'))
    root = Path(sys.base_prefix).resolve()
    if (sys.platform != 'darwin' or platform.python_version() != manifest['python_version']
            or str(root) != '/Library/Frameworks/Python.framework/Versions/3.13'
            or sha(installer) != manifest['installer_sha256']
            or not ssl.OPENSSL_VERSION.startswith('OpenSSL 3.0.21 ')
            or _decimal.__libmpdec_version__ != '4.0.1'):
        raise RuntimeError('Runtime differs from the reviewed python.org macOS installer')
    arch = platform.machine()
    if arch not in ('arm64', 'x86_64'):
        raise RuntimeError('Unsupported macOS architecture')
    backend = app / 'Contents/Resources/backend'
    runtime = backend / '_internal'
    output = app / 'Contents/Resources/licenses'
    output.mkdir(parents=True, exist_ok=True)
    notices = []
    for entry in manifest['licenses']:
        path = ASSETS / entry['file']
        if sha(path) != entry['sha256']:
            raise RuntimeError('Changed license: ' + path.name)
        shutil.copyfile(path, output / path.name); notices.append(entry)
    windows = json.loads((SHARED / 'native-runtime.json').read_text(encoding='utf8'))
    openssl = next(item for item in windows['licenses'] if item['name'] == 'OpenSSL')
    for key, hashkey in [('file', 'sha256'), ('notice_file', 'notice_sha256')]:
        path = SHARED / openssl[key]
        if sha(path) != openssl[hashkey]:
            raise RuntimeError('Changed OpenSSL notice')
        shutil.copyfile(path, output / path.name)
    notices.append(openssl)
    native = []
    dylibs = {'libcrypto.3.dylib', 'libssl.3.dylib', 'liblzma.5.dylib', 'libmpdec.4.dylib'}
    import PyInstaller
    bootloaders = list((Path(PyInstaller.__file__).parent / 'bootloader').glob('Darwin*/run'))
    if len(bootloaders) != 1:
        raise RuntimeError('Cannot identify the unmodified PyInstaller bootloader')
    for path in sorted(backend.rglob('*')):
        if path.is_symlink():
            if not path.resolve().is_relative_to(backend.resolve()):
                raise RuntimeError('Bundle symlink escapes backend')
            continue
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic not in MACHO_MAGICS:
            continue
        if path == backend / 'CodexUsageBackend':
            source = bootloaders[0]
        elif path.name == 'Python':
            source = root / 'Python'
        elif path.suffix == '.so':
            source = root / 'lib/python3.13/lib-dynload' / path.name
        elif path.name in dylibs:
            candidates = [p for p in root.rglob(path.name) if p.is_file()]
            resolved = set(p.resolve() for p in candidates)
            if len(resolved) != 1:
                raise RuntimeError('Cannot identify native dependency: ' + path.name)
            source = resolved.pop()
        else:
            raise RuntimeError('Unreviewed native dependency: ' + path.name)
        if not source.is_file() or text_sections(source, arch) != text_sections(path, arch):
            raise RuntimeError('Packaged code differs from reviewed runtime: ' + path.name)
        native.append({'path': str(path.relative_to(backend)), 'sha256': sha(path),
                       'original': str(source.relative_to(root)) if source.is_relative_to(root) else 'PyInstaller/bootloader/Darwin/run',
                       'original_sha256': sha(source), 'text_sections_verified': True})
    if not any(Path(item['path']).name == 'Python' for item in native):
        raise RuntimeError('Python runtime is missing')
    components = []
    for name in ('pyinstaller', 'altgraph', 'macholib', 'packaging', 'pyinstaller-hooks-contrib', 'setuptools'):
        dist = metadata.distribution(name)
        copied = []
        for item in dist.files or ():
            if item.name.lower().startswith(('license', 'copying', 'notice')):
                path = Path(dist.locate_file(item))
                if path.is_file():
                    target = name + '-' + str(item).replace('/', '_')
                    shutil.copyfile(path, output / target); copied.append(target)
        if not copied:
            raise RuntimeError('Build dependency has no collected notice: ' + name)
        components.append({'name': name, 'version': dist.version, 'notice_files': copied})
    record = {**manifest, 'architecture': arch, 'openssl': ssl.OPENSSL_VERSION,
              'code_verification': 'Mach-O __TEXT code, constants and strings match the verified python.org runtime or unmodified PyInstaller bootloader; load commands and ad-hoc signatures are relocated.',
              'native_files': native, 'notices': notices, 'build_dependencies': components}
    (output / 'runtime-provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf8')
    (output / 'README.txt').write_text('The app is MIT licensed. Bundled CPython, OpenSSL, liblzma, libmpdec and PyInstaller retain their licenses.\nPyInstaller uses its unmodified-bootloader distribution exception. Build-tool notices are included.\nmacOS system frameworks and libraries are provided by macOS and are not redistributed.\nCodex, Claude Code and their provider logo files are not bundled.\n', encoding='utf8')
    print('Verified runtime code and notices:', arch, len(native), 'Mach-O files')


if __name__ == '__main__':
    collect(sys.argv[1], sys.argv[2])
