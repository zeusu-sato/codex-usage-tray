import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
spec = importlib.util.spec_from_file_location("collect_notices", PACKAGING / "collect_notices.py")
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class PackagingNoticesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        shutil.copytree(notices.ASSETS, self.assets)
        self.manifest = json.loads((self.assets / "native-runtime.json").read_text())
        self.output = self.root / "package" / "licenses"
        self.runtime = self.root / "package" / "backend" / "_internal"
        self.runtime.mkdir(parents=True)
        self.python = self.root / "python"
        self.python.mkdir()
        (self.python / "LICENSE.txt").write_bytes(b"fixture Python license")
        self.manifest["python_license_sha256"] = notices.digest(self.python / "LICENSE.txt")
        self.manifest["native_files"] = {}
        for name in ("python313.dll", "libcrypto-3.dll", "libffi-8.dll"):
            (self.runtime / name).write_bytes(("fixture " + name).encode())
            self.manifest["native_files"][name] = notices.digest(self.runtime / name)
        (self.assets / "native-runtime.json").write_text(json.dumps(self.manifest))
        self.profile = {key: self.manifest[key] for key in ("implementation", "python_version", "system", "machine")}
        self.profile["pointer_bits"] = 64
        self.dist_license = self.root / "LICENSE-fixture"
        self.dist_license.write_text("fixture dependency license")

    def collect(self, profile=None):
        dist = SimpleNamespace(version="fixture", files=[Path("LICENSE-fixture")], locate_file=lambda _: self.dist_license)
        with patch.object(notices.metadata, "distribution", return_value=dist):
            notices.collect(self.output, self.python, profile=profile or self.profile, assets=self.assets)

    def test_committed_native_notice_assets_have_verified_bytes_and_pinned_sources(self):
        manifest = json.loads((notices.ASSETS / "native-runtime.json").read_text())
        files = notices.validated_assets(notices.ASSETS, manifest)
        self.assertEqual(len(files), 7)
        openssl = next(item for item in manifest["licenses"] if item["name"] == "OpenSSL")
        self.assertEqual(openssl["version"], "3.0.21")
        self.assertIn("51ea949dc1436e865935b47874b21a3bb31a102e", openssl["source_url"])
        self.assertIsNone(manifest["openssl_upstream_notice"])
        self.assertIn("not presented as an upstream NOTICE", (notices.ASSETS / openssl["notice_file"]).read_text())

    def test_verified_collection_records_actual_binaries_and_copies_exact_notices(self):
        (self.runtime / "api-ms-win-crt-runtime-l1-1-0.dll").write_bytes(b"fixture Windows support")
        self.collect()
        saved = json.loads((self.output / "native-runtime-provenance.json").read_text())
        self.assertEqual(saved["bundled_native_files"]["libcrypto-3.dll"]["sha256"], self.manifest["native_files"]["libcrypto-3.dll"])
        self.assertEqual(saved["bundled_native_files"]["api-ms-win-crt-runtime-l1-1-0.dll"]["source"], "windows_build_environment")
        self.assertEqual((self.output / "openssl-3.0.21-LICENSE.txt").read_bytes(),
                         (notices.ASSETS / "openssl-3.0.21-LICENSE.txt").read_bytes())
        self.assertTrue((self.output / "OPENSSL-NOTICE.txt").is_file())
        components = json.loads((self.output / "components.json").read_text())
        self.assertEqual(next(row for row in components if row["name"] == "OpenSSL")["version"], "3.0.21")
        self.assertNotIn(str(self.root), (self.output / "native-runtime-provenance.json").read_text())

    def test_other_interpreters_architectures_and_platforms_fail_before_copying(self):
        for field, value in (("python_version", "3.12.3"), ("python_version", "3.13.16"),
                             ("implementation", "PyPy"), ("machine", "ARM64"), ("system", "Linux"), ("pointer_bits", 32)):
            with self.subTest(field=field, value=value):
                profile = dict(self.profile, **{field: value})
                with self.assertRaisesRegex(RuntimeError, "Unsupported runtime"):
                    self.collect(profile)
                self.assertFalse(self.output.exists())

    def test_changed_libcrypto_or_python_license_fail_before_copying(self):
        for path in (self.runtime / "libcrypto-3.dll", self.python / "LICENSE.txt"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(b"different unreviewed version")
                with self.assertRaises(RuntimeError):
                    self.collect()
                self.assertFalse(self.output.exists())
                path.write_bytes(original)

    def test_unknown_or_missing_native_component_requires_review(self):
        unknown = self.runtime / "unreviewed-library.dll"
        unknown.write_bytes(b"unreviewed dependency")
        with self.assertRaisesRegex(RuntimeError, "no reviewed notice mapping"):
            self.collect()
        self.assertFalse(self.output.exists())
        unknown.unlink()
        (self.runtime / "libcrypto-3.dll").unlink()
        with self.assertRaisesRegex(RuntimeError, "Required reviewed"):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_tampered_upstream_license_is_not_shipped(self):
        (self.assets / "openssl-3.0.21-LICENSE.txt").write_bytes(b"truncated license")
        with self.assertRaisesRegex(RuntimeError, "license asset failed verification"):
            self.collect()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
