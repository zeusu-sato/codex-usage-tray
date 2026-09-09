"""Collect notices offline, only for the reviewed Windows CPython runtime."""
from importlib import metadata
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import sys


ASSETS = Path(__file__).with_name("license-assets")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_profile():
    return {"implementation": platform.python_implementation(), "python_version": platform.python_version(),
            "system": platform.system(), "machine": platform.machine().upper(), "pointer_bits": struct.calcsize("P") * 8}


def validate_runtime(runtime, python_root, manifest, profile):
    """Verify actual packaged bytes, not an assumed interpreter/DLL version."""
    if (manifest.get("schema_version") != 1 or profile.get("pointer_bits") != 64
            or any(profile.get(key) != manifest.get(key)
                   for key in ("implementation", "python_version", "system", "machine"))):
        raise RuntimeError("Unsupported runtime: review native dependencies and notices before packaging")
    candidates = [python_root / "LICENSE.txt", python_root / "LICENSE_PYTHON.txt"]
    license_path = next((p for p in candidates if p.is_file()), None)
    if license_path is None or digest(license_path) != manifest["python_license_sha256"]:
        raise RuntimeError("Python license does not match the reviewed official distribution")
    if not runtime.is_dir():
        raise RuntimeError("Packaged native runtime directory is missing")
    expected = {name.casefold(): value for name, value in manifest["native_files"].items()}
    found = {}
    for path in sorted(runtime.rglob("*")):
        if path.suffix.lower() not in (".dll", ".pyd"):
            continue
        name = path.name.casefold()
        if path.parent != runtime or path.is_symlink() or name in found:
            raise RuntimeError("Unexpected native runtime layout")
        sha256 = digest(path)
        if name in expected:
            if sha256 != expected[name]:
                raise RuntimeError("Native binary differs from the reviewed official distribution: " + name)
            source = "reviewed_cpython_distribution"
        elif name == "ucrtbase.dll" or re.fullmatch(r"api-ms-win-[a-z0-9-]+\.dll", name):
            source = "windows_build_environment"
        else:
            raise RuntimeError("Native component has no reviewed notice mapping: " + name)
        found[name] = {"sha256": sha256, "source": source}
    if not {"python313.dll", "libcrypto-3.dll", "libffi-8.dll"}.issubset(found):
        raise RuntimeError("Required reviewed native runtime files are missing")
    return license_path, found


def validated_assets(assets, manifest):
    result = []
    for component in manifest["licenses"]:
        fields = [(component["file"], component["sha256"])]
        if "notice_file" in component:
            fields.append((component["notice_file"], component["notice_sha256"]))
        for name, expected in fields:
            path = assets / name
            if Path(name).name != name or path.is_symlink() or digest(path) != expected:
                raise RuntimeError("Native license asset failed verification: " + name)
            result.append(path)
    return result


def collect(output, python_root=None, profile=None, assets=ASSETS):
    output = Path(output)
    python_root = Path(sys.base_prefix) if python_root is None else Path(python_root)
    manifest = json.loads((assets / "native-runtime.json").read_text(encoding="utf-8"))
    license_path, native_files = validate_runtime(output.parent / "backend" / "_internal", python_root,
                                                 manifest, runtime_profile() if profile is None else profile)
    asset_paths = validated_assets(assets, manifest)
    # No notices are copied until all runtime and source-asset checks have passed.
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, output / "PYTHON-LICENSE.txt")
    for path in asset_paths:
        shutil.copyfile(path, output / path.name)
    provenance = {**manifest, "bundled_native_files": native_files}
    (output / "native-runtime-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    components = [{"name": "CPython", "version": manifest["python_version"], "source": manifest["runtime_source_url"]}]
    for component in manifest["licenses"]:
        components.append({"name": component["name"], "version": component["version"], "source": component["source_url"],
                           "license_file": component["file"], "license_sha256": component["sha256"]})
    for name in ("pyinstaller", "altgraph", "packaging", "pefile", "pyinstaller-hooks-contrib", "pywin32-ctypes", "setuptools"):
        dist = metadata.distribution(name)
        for file in dist.files or ():
            if file.name.lower().startswith(("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    relative = str(file).replace("/", "_").replace("\\", "_")
                    shutil.copyfile(source, output / (name + "-" + relative))
        components.append({"name": name, "version": dist.version, "source": "https://pypi.org/project/" + name + "/"})
    (output / "components.json").write_text(json.dumps(components, indent=2) + "\n", encoding="utf-8")
    (output / "README.txt").write_text(
        "Codex Usage Tray is MIT licensed. CPython and bundled dependencies retain their own licenses.\n"
        "PyInstaller's unmodified bootloader uses its distribution exception; build-tool notices are also included.\n"
        "Additional native-library licenses and OpenSSL distributor attribution are included separately.\n"
        "native-runtime-provenance.json records reviewed source URLs, license hashes, and packaged DLL hashes.\n"
        "Microsoft VC runtime and Windows support DLLs retain Microsoft's redistribution terms.\n"
        "Codex and Claude Code are installed separately by the user and are not bundled.\n", encoding="utf-8")


def main():
    collect(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
