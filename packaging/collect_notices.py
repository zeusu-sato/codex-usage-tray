"""Copy installed runtime/build license texts; fail if the Python license is absent."""
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import sys


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    python_root = Path(sys.base_prefix)
    candidates = [python_root / "LICENSE.txt", python_root / "LICENSE_PYTHON.txt"]
    license_path = next((p for p in candidates if p.is_file()), None)
    if license_path is None:
        raise RuntimeError("Python license not found in the build interpreter")
    shutil.copyfile(license_path, output / "PYTHON-LICENSE.txt")
    components = [{"name": "CPython", "version": platform.python_version(), "source": "https://www.python.org/"}]
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
        "Python's license text contains notices for its included components. Microsoft VC runtime DLLs, when\n"
        "included by the official Python distribution, retain Microsoft's redistribution terms.\n"
        "Codex is installed separately by the user and is not bundled.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
