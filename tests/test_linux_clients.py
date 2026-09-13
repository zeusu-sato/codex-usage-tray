"""Linux discovery and XDG regressions using only temporary installations."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import client_registry as clients
from storage import default_data_dir


@unittest.skipIf(os.name == "nt", "POSIX permissions and symlinks")
class LinuxClientsTests(unittest.TestCase):
    def extension(self, root, provider, target):
        identifier = "openai.chatgpt" if provider == "codex" else "anthropic.claude-code"
        relative = identifier + "-1.2.3-linux-x64"
        extensions = root / ".vscode-insiders/extensions"
        binary = extensions / relative / target
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"fixture only")
        binary.chmod(0o700)
        (extensions / "extensions.json").write_text(json.dumps([{
            "identifier": {"id": identifier}, "version": "1.2.3", "relativeLocation": relative}]))
        return binary

    def test_linux_registered_codex_for_each_architecture(self):
        for machine, arch in (("x86_64", "x86_64"), ("aarch64", "aarch64")):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                binary = self.extension(root, "codex", f"bin/linux-{arch}/codex")
                found = clients.discover(root, which=lambda _: None, platform_name="linux", machine=machine)
                self.assertEqual([c["binary_path"] for c in found], [str(binary)])
                self.assertEqual(found[0]["client_id"], "vscode-insiders")

    def test_claude_linux_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = self.extension(root, "claude", "resources/native-binary/claude")
            found = clients.discover(root, which=lambda _: None, provider="claude", platform_name="linux")
            self.assertEqual(found[0]["binary_path"], str(binary))

    def test_native_symlink_is_resolved_and_duplicate_extension_is_not_added(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = self.extension(root, "codex", "bin/linux-x86_64/codex")
            link = root / "codex"
            link.symlink_to(binary)
            found = clients.discover(root, which=lambda _: str(link), platform_name="linux", machine="x86_64")
            self.assertEqual(len(found), 1)
            version = root / "2.1.263"
            version.write_bytes(b"fixture only")
            version.chmod(0o700)
            claude = root / "claude"
            claude.symlink_to(version)
            found = clients.discover(root, which=lambda name: str(claude) if name == "claude" else None,
                                     provider="claude", platform_name="linux")
            self.assertEqual(found[0]["binary_path"], str(version))

    def test_nonexecutable_and_other_architecture_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = self.extension(root, "codex", "bin/linux-x86_64/codex")
            self.assertEqual(clients.discover(root, which=lambda _: None, platform_name="linux", machine="aarch64"), [])
            binary.chmod(0o600)
            self.assertEqual(clients.discover(root, which=lambda _: str(binary), platform_name="linux", machine="x86_64"), [])

    def test_xdg_absolute_root_and_relative_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, "platform", "linux"), \
                patch.dict(os.environ, {"XDG_DATA_HOME": directory, "LOCALAPPDATA": "/wrong"}):
            self.assertEqual(default_data_dir(), Path(directory) / "CodexUsageTray")
            os.environ["XDG_DATA_HOME"] = "relative-ignored"
            self.assertEqual(default_data_dir(), Path.home() / ".local/share/CodexUsageTray")


if __name__ == "__main__":
    unittest.main()
