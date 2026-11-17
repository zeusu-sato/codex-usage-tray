import os
import subprocess
import unittest
from pathlib import Path


class SourceEncodingTests(unittest.TestCase):
    def test_text_sources_are_utf8_without_replacement_marks(self):
        root = Path(__file__).resolve().parent.parent
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
        files = subprocess.check_output(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root, env=env
        ).decode("utf-8").split("\0")
        extensions = {".cs", ".ps1", ".py", ".swift", ".md", ".iss"}
        for name in files:
            path = root / name
            if path.suffix.lower() not in extensions or not path.is_file():
                continue
            with self.subTest(path=name):
                content = path.read_bytes().decode("utf-8")
                self.assertNotIn("?" * 4, content)
